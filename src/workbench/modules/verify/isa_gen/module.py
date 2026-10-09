"""ISA 激励 —— 场景 DSL → ISA 事务层 IR，在界面上跑。

这个模块的定位：**把「生成一次激励」变成能看见过程的事**。

工具本身（`src/tools/isa_gen_tools/`）已经能做完整的六段编译，但它是命令行的
—— 而"这次到底生成了什么"恰恰是最需要看的地方：

  · 事务数 / 指令数 / epoch 数、派生了哪些随机流（**可复现链**）
  · 地址分配落在哪（SPAD / CIMC / Share DRAM 各多少）
  · 事务的配对有没有闭合（`gemm` 前是不是真有那条 `pre`）
  · 有哪些 note（`illegal_ratio` 没生效、epoch 是空的……）

这些在终端里是一屏文本，在界面上是**四张能对着看的表**。

界面只经 `bridge/catalog.py` 的绑定访问工具，**不 import 工具包**
—— 「界面能碰什么」因此永远是一份可审计的清单（见工具层架构文档 §4.1）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QSplitter, QTabWidget, QVBoxLayout,
                               QWidget)

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import LEFT, RIGHT, RowsModel
from ...base import ModuleBase

#: 四条表 —— 列定义 (键, 表头, 宽, 对齐)
INSTRUCTION_COLUMNS = (
    ("tag", "tag", 56, LEFT),
    ("op", "指令", 200, LEFT),
    ("mask", "mask", 78, LEFT),
    ("flags", "xd/xs1/xs2", 92, LEFT),
    ("ref", "数据", 240, LEFT),
)
REPORT_COLUMNS = (("key", "项", 160, LEFT), ("value", "值", 420, LEFT))
ALLOC_COLUMNS = (
    ("name", "对象", 90, LEFT),
    ("region", "区域", 130, LEFT),
    ("offset", "偏移", 90, RIGHT),
    ("size", "大小", 80, RIGHT),
    ("role", "角色", 80, LEFT),
)
NOTE_COLUMNS = (("kind", "类型", 120, LEFT), ("text", "说明", 520, LEFT))

#: 编码后的指令流（`payload["encode"]["items"]`）—— **单位是 32bit 字，不是 IR 条目**。
#: 与 IR 那张表的区别：IR 是"要求做什么"，这张是"真的编成了什么位模式"。
ENCODE_COLUMNS = (
    ("off", "off", 62, RIGHT),
    ("word", "word", 84, LEFT),
    ("isa", "isa", 58, LEFT),
    ("op", "指令", 186, LEFT),
    ("tag", "tag", 52, LEFT),
    ("mask", "mask", 74, LEFT),
    ("flags", "xd/xs1/xs2", 84, LEFT),
    ("rs1", "rs1", 116, LEFT),
    ("rs2", "rs2", 116, LEFT),
    ("rd", "rd", 64, LEFT),
    ("note", "备注", 150, LEFT),
)

#: 张量（tensor_gen 的产物）—— 每行一个对象。
TENSOR_COLUMNS = (
    ("name", "对象", 78, LEFT),
    ("ref", "ref", 90, LEFT),
    ("shape", "形状", 116, LEFT),
    ("dtype", "dtype", 62, LEFT),
    ("size", "字节", 80, RIGHT),
    ("layout", "布局", 190, LEFT),
    ("pattern", "模式", 74, LEFT),
    ("hash", "content_hash", 150, LEFT),
)

#: 页签下标 —— 与 `build_content` 里的 addTab 顺序一一对应。
(TAB_INSTRUCTION, TAB_ENCODE, TAB_TENSOR, TAB_REPORT,
 TAB_ALLOC, TAB_NOTES, TAB_RAW) = range(7)

#: 兜底示例 —— 与 `config/isa_gen/examples/npu_gemm.yaml` 同一份的极简版。
#: 清单里配了 `input` 时用那份文件；没有才用这个，保证打开就有东西可跑。
#:
#: **`role: origin` 不能省**：`gemm_txn` 的 `gemm_out_org_pre_xn` 第二个操作数
#: 在编码表里是 `base_addr_orig`（原累加器），`txn.registry.json` 把它声明成
#: 角色 `origin`。少了它，编译期会以 `UnresolvedRefError` 停下 —— 这是对的
#: （它在说"你声明要的东西不存在"），但示例不该是个跑不起来的东西。
SAMPLE = """meta: {name: quick, seed: 4242}
resources: {cores: [0..3]}
txn_pool: {include: [mask_txn, tld_txn, gemm_txn, sync_txn]}
orchestration: {epochs: 2, epoch_boundary_sync: always}
alloc:
  - {name: img, pool: dram.share,     shape: [64,128], dtype: fp16, role: src}
  - {name: out, pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: dst}
  - {name: wgt, pool: lmem.core.cimc, shape: [64,64],  dtype: fp16, role: wgt}
  - {name: act, pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: in}
  - {name: res, pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: out}
  - {name: org, pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: origin}
"""


class IsaGenModule(ModuleBase):
    """场景 DSL → IR 的编译与查看。"""

    HINT = ("写一份场景 DSL（或打开一份文件），点「编译」看它展开成哪些事务与指令。"
            "同一个 seed 编两次，产物逐字节相同 —— 这是可复现链的根。")

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        self.payload: Optional[Dict[str, Any]] = None
        self.dsl_path: str = ""

    # ════════════════════════════════════════════════════════
    # 界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(self._build_toolbar(root))

        splitter = QSplitter(Qt.Orientation.Vertical, root)

        self.editor = QPlainTextEdit(splitter)
        self.editor.setFont(theme.mono_font())
        self.editor.setPlaceholderText("场景 DSL（YAML）—— 七段：meta / resources / "
                                       "txn_pool / shape_space / intent / "
                                       "orchestration / alloc")
        self.editor.setPlainText(SAMPLE)
        splitter.addWidget(self.editor)

        # 页签顺序与下面的 TAB_* 常量一一对应 —— 别用字面量下标，
        # 中间插一页就会把"跳到 notes"那几处静默指错地方。
        self.tabs = QTabWidget(splitter)
        self.tabs.addTab(self._build_table_page(INSTRUCTION_COLUMNS, "instruction"),
                         "指令流（IR）")
        self.tabs.addTab(self._build_table_page(ENCODE_COLUMNS, "encode"),
                         "编码清单")
        self.tabs.addTab(self._build_table_page(TENSOR_COLUMNS, "tensor"), "张量")
        self.tabs.addTab(self._build_table_page(REPORT_COLUMNS, "report"), "编译报告")
        self.tabs.addTab(self._build_table_page(ALLOC_COLUMNS, "alloc"), "地址分配")
        self.tabs.addTab(self._build_table_page(NOTE_COLUMNS, "notes"),
                         "注意 / 疑点")
        self.tabs.addTab(self._build_raw_page(), "原始 JSON")
        splitter.addWidget(self.tabs)

        splitter.setSizes([280, 380])
        layout.addWidget(splitter, 1)
        return root

    def _build_toolbar(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(3)

        hint = QLabel(self.HINT, panel)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        outer.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("DSL：", panel))
        self.path_edit = QLineEdit(panel)
        self.path_edit.setPlaceholderText("（未打开文件 —— 用下面编辑框里的内容）")
        self.path_edit.setReadOnly(True)
        row.addWidget(self.path_edit, 1)

        self.btn_open = QPushButton("打开…", panel)
        self.btn_open.clicked.connect(self.open_dsl)
        row.addWidget(self.btn_open)
        self.btn_sample = QPushButton("填示例", panel)
        self.btn_sample.clicked.connect(lambda: self.editor.setPlainText(SAMPLE))
        row.addWidget(self.btn_sample)
        outer.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_check = QPushButton("校验", panel)
        self.btn_check.clicked.connect(self.check_dsl)
        row2.addWidget(self.btn_check)

        self.btn_compile = QPushButton("编译", panel)
        self.btn_compile.setDefault(True)
        self.btn_compile.clicked.connect(self.compile_dsl)
        row2.addWidget(self.btn_compile)

        row2.addWidget(QLabel("seed：", panel))
        self.seed_spin = QSpinBox(panel)
        self.seed_spin.setRange(0, 2_000_000_000)
        self.seed_spin.setSpecialValueText("（用 DSL 里的）")
        self.seed_spin.setValue(0)
        row2.addWidget(self.seed_spin)

        row2.addWidget(QLabel("最多事务：", panel))
        self.max_spin = QSpinBox(panel)
        self.max_spin.setRange(1, 500)
        self.max_spin.setValue(16)
        row2.addWidget(self.max_spin)

        self.btn_export = QPushButton("落盘…", panel)
        self.btn_export.clicked.connect(self.export_artifacts)
        self.btn_export.setEnabled(False)
        row2.addWidget(self.btn_export)

        self.summary = QLabel("还没有编译过。", panel)
        row2.addWidget(self.summary, 1)
        outer.addLayout(row2)
        return panel

    def _build_table_page(self, columns, attr: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        model = RowsModel(columns, page)
        table = table_helpers.configure_table(page, model)
        layout.addWidget(table, 1)
        setattr(self, f"{attr}_model", model)
        return page

    def _build_raw_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        self.raw = QPlainTextEdit(page)
        self.raw.setReadOnly(True)
        self.raw.setFont(theme.mono_font())
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.raw.setPlaceholderText("编译产物的完整 JSON 会出现在这里")
        layout.addWidget(self.raw, 1)
        return page

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def create_actions(self) -> List[QAction]:
        compile_action = QAction("编译 ISA 激励", self.content)
        compile_action.triggered.connect(self.compile_dsl)
        check_action = QAction("校验 ISA 场景 DSL", self.content)
        check_action.triggered.connect(self.check_dsl)
        export_action = QAction("ISA 产物落盘…", self.content)
        export_action.triggered.connect(self.export_artifacts)
        return [compile_action, check_action, export_action]

    def on_input_changed(self, path) -> None:
        """清单的 `input` 或 `--input` 指过来时载入。"""
        target = Path(path)
        if not target.is_file():
            return
        try:
            self.editor.setPlainText(target.read_text(encoding="utf-8",
                                                       errors="replace"))
        except OSError as exc:
            self.show_error(f"读不了这份 DSL：{exc}")
            return
        self.dsl_path = str(target)
        self.path_edit.setText(str(target))
        self.set_status(f"已载入 {target.name}")

    def on_activated(self) -> None:
        # 第一次被打开、而且还没编译过 —— 顺手跑一次，别让人对着空表猜
        if self.payload is None:
            self.compile_dsl()

    # ════════════════════════════════════════════════════════
    # 动作
    # ════════════════════════════════════════════════════════

    def open_dsl(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self.content, "选择场景 DSL", "", "DSL (*.yaml *.yml);;所有文件 (*)")
        if path:
            self.on_input_changed(path)

    def check_dsl(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip():
            self.show_warning("还没有 DSL —— 打开一份文件，或用「填示例」。")
            return
        payload = self.run_tool("isa_gen.validate", dsl_text=text)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            return
        errors = payload.get("issues", [])
        if payload.get("valid"):
            self.show_info(f"DSL 合法（{len(errors)} 条提示）")
            self.set_status("DSL 校验通过")
            return
        self.show_error(f"DSL 不合法：{payload.get('error_count', 0)} 处 error —— "
                        "切到「注意 / 疑点」页看逐条")
        self.notes_model.set_rows(
            [{"kind": i.get("rule", ""), "text": _issue_text(i)} for i in errors])
        self.tabs.setCurrentIndex(TAB_NOTES)

    def compile_dsl(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip():
            self.show_warning("还没有 DSL —— 打开一份文件，或用「填示例」。")
            return
        seed = self.seed_spin.value() or None
        payload = self.run_tool("isa_gen.compile", dsl_text=text, seed=seed,
                                max_txns=self.max_spin.value())
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            self.payload = None
            self.btn_export.setEnabled(False)
            return
        self.payload = payload
        self.btn_export.setEnabled(True)
        self._render(payload)

    def export_artifacts(self) -> None:
        if not self.payload:
            self.show_warning("先编译一次再落盘。")
            return
        default = self.payload.get("name", "isa_case")
        path = QFileDialog.getExistingDirectory(self.content, "选择输出目录")
        if not path:
            return
        target = Path(path) / default
        result = self.run_tool("isa_gen.export", force=True, out_dir=str(target),
                               payload=self.payload)
        if not isinstance(result, dict) or self.report_payload_error(result):
            return
        names = result.get("written", [])
        self.log(f"已写出 {len(names)} 份产物 → {target}")

        tail = ""
        gaps = result.get("operand_gaps") or []
        if gaps:
            # **不静默**：这些字里有一槽是 0（读 x0），0 是合法操作数，
            # 仿真不会在那里报错 —— 所以落盘这一步就得说出来。
            tail = (f"\n\n⚠ {len(gaps)} 个操作数槽没有填出来"
                    f"（对应字里那一槽是 0）：\n  " + "、".join(gaps[:6])
                    + ("…" if len(gaps) > 6 else ""))
        notes = result.get("tensor_notes") or []
        if notes:
            tail += "\n\n张量：" + "；".join(notes[:3])
        missing = result.get("not_produced") or []
        if missing:
            tail += "\n\n未产出：" + "、".join(m.get("file", "") for m in missing)

        QMessageBox.information(
            self.content, "已落盘",
            f"写出到\n{target}\n\n" + "\n".join(names) + tail)

    # ════════════════════════════════════════════════════════
    # 渲染
    # ════════════════════════════════════════════════════════

    def _render(self, payload: Dict[str, Any]) -> None:
        self.instruction_model.set_rows(_instruction_rows(payload))
        self.encode_model.set_rows(_encode_rows(payload))
        self.tensor_model.set_rows(_tensor_rows(payload))
        self.report_model.set_rows(_report_rows(payload))
        self.alloc_model.set_rows(_alloc_rows(payload))
        self.notes_model.set_rows(_note_rows(payload))
        self.raw.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2,
                                         default=str))

        encode = payload.get("encode") or {}
        tensors = payload.get("tensors") or {}
        summary = (f"{payload['name']}　seed={payload['seed']}　"
                   f"事务 {payload['txn_count']}　指令 {payload['instruction_count']}　"
                   f"epoch {payload['epoch_count']}")
        if encode.get("words") is not None and not encode.get("error"):
            stats = encode.get("stats") or {}
            summary += (f"　编码 {len(encode['words'])} 字"
                        f"（合成 {stats.get('synthesized', 0)}）")
            if encode.get("gaps"):
                summary += f"　⚠ 空操作数 {len(encode['gaps'])} 处"
        if tensors.get("entries"):
            total = sum(e.get("n_bytes", 0) for e in tensors["entries"])
            summary += f"　张量 {len(tensors['entries'])} 个 / {total} 字节"
        self.summary.setText(summary)
        self.set_status(summary + f"　（{payload.get('elapsed_ms', 0)}ms）")

        # 顶到"需要人看一眼"的那一页：有 note → notes；
        # 有空洞的操作数 → 编码清单（那里当场标着 ⚠）；否则回第一页
        if payload.get("notes"):
            self.tabs.setCurrentIndex(TAB_NOTES)
        elif encode.get("gaps"):
            self.tabs.setCurrentIndex(TAB_ENCODE)
        elif payload.get("allocations", {}).get("objects"):
            self.tabs.setCurrentIndex(TAB_INSTRUCTION)


# ════════════════════════════════════════════════════════════
# 纯函数：产物 → 表格行
# ════════════════════════════════════════════════════════════

def _instruction_rows(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    rows = []
    for ins in payload.get("ir", {}).get("instructions", []):
        refs = []
        if ins.get("binds"):
            refs.append("读 " + ",".join(ins["binds"]))
        for entry in ins.get("writes", []) or []:
            name = entry.get("ref") if isinstance(entry, dict) else str(entry)
            refs.append("写 " + str(name))
        flags = ins.get("flags") or {}
        rows.append({
            "tag": ins.get("tag", ""),
            "op": ins.get("op", ""),
            "mask": ins.get("mask", ""),
            "flags": (f"{flags.get('xd', 0)}/{flags.get('xs1', 0)}/"
                      f"{flags.get('xs2', 0)}" if flags else "—"),
            "ref": "　".join(refs),
        })
    return rows


def _encode_rows(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """编码后的指令流 —— 与 `seq.lst` 同一份内容，单位是 **32bit 字**。

    与「指令流（IR）」那张表的区别：IR 是"要求做什么"，这张是"真的编成了
    什么位模式"。`off` 就是那个字在流里的字节偏移，对着 ISS 的 PC 能直接找。

    这里**不自己按 bit 位置解 flags** —— `payload["encode"]["items"]` 已经把
    `flags` 摊平给出来了。界面按位布局自己解，就是把位布局抄了第二份，
    而两份迟早对不上（这个仓库里已经有过一次同类教训）。
    """
    encode = payload.get("encode") or {}
    if encode.get("error"):
        return [{"off": "—", "word": "编码失败", "isa": "",
                 "op": str(encode.get("error", "")), "tag": "", "mask": "",
                 "flags": "", "rs1": "", "rs2": "", "rd": "",
                 "note": str(encode.get("fix", ""))}]

    registers = {int(k): v for k, v in (encode.get("registers") or {}).items()}
    gaps = {(g.get("index"), g.get("slot")) for g in (encode.get("gaps") or [])}

    def cell(enabled: Any, index: Any) -> str:
        """`x2 = 0x4000` / `—`（使能位没置位时那个字段没有意义）。"""
        if not enabled:
            return "—"
        value = registers.get(int(index))
        return f"x{index}" if value is None else f"x{index} = 0x{value:X}"

    rows: List[Dict[str, str]] = []
    word_idx = 0
    for it in encode.get("items") or []:
        if not it.get("encoded"):
            continue
        off = f"0x{word_idx * 4:x}"
        word_idx += 1
        f = it.get("flags") or {}
        notes = []
        if it.get("synthesized"):
            notes.append("mask 变化→自动补")
        if (it.get("index"), "rs1val") in gaps:
            notes.append("⚠rs1val 未填")
        if (it.get("index"), "rs2val") in gaps:
            notes.append("⚠rs2val 未填")
        rows.append({
            "off": off, "word": it.get("word_hex", ""),
            "isa": it.get("isa", ""), "op": it.get("op", ""),
            "tag": it.get("tag", ""), "mask": it.get("mask", ""),
            "flags": f"{f.get('xd', '—')}/{f.get('xs1', '—')}/{f.get('xs2', '—')}",
            "rs1": cell(f.get("xs1"), it.get("rs1")),
            "rs2": cell(f.get("xs2"), it.get("rs2")),
            "rd": cell(f.get("xd"), it.get("rd")),
            "note": "　".join(notes),
        })
    return rows


def _tensor_rows(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """tensor_gen 的产物 —— 每行一个对象（数据 + manifest 摘要）。"""
    tensors = payload.get("tensors") or {}
    if tensors.get("error"):
        return [{"name": "—", "ref": "", "shape": "tensor_gen 失败", "dtype": "",
                 "size": "", "layout": str(tensors.get("error", "")),
                 "pattern": "", "hash": ""}]
    rows: List[Dict[str, str]] = []
    for entry in tensors.get("entries") or []:
        manifest = entry.get("manifest") or {}
        layout = manifest.get("layout") or {}
        exp = manifest.get("exp_range") or {}
        bits = [f"stride1={layout.get('stride_dim1')}",
                f"rem0={layout.get('rem_dim0')}"]
        if layout.get("bc_only"):
            bits.append("bc_only")
        # 缩放过 = E1 真的出手了，值得看见（不然只会以为"生成得很顺"）
        if exp.get("scaled"):
            bits.append("exp 已缩放")
        rows.append({
            "name": entry.get("name", ""), "ref": entry.get("ref", ""),
            "shape": "×".join(str(x) for x in (manifest.get("shape") or [])),
            "dtype": manifest.get("dtype", ""),
            "size": str(entry.get("n_bytes", "")),
            "layout": "　".join(bits),
            "pattern": manifest.get("pattern", ""),
            "hash": entry.get("content_hash", ""),
        })
    return rows


def _report_rows(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    rows = [
        {"key": "case", "value": payload.get("name", "")},
        {"key": "seed", "value": str(payload.get("seed", ""))},
        {"key": "ISA 版本", "value": payload.get("isa_rev", "")},
        {"key": "事务数", "value": str(payload.get("txn_count", 0))},
        {"key": "指令数", "value": str(payload.get("instruction_count", 0))},
        {"key": "epoch 数", "value": str(payload.get("epoch_count", 0))},
        {"key": "memmap", "value": f"{payload.get('memmap', {}).get('source', '')}"
                                   f" ({payload.get('memmap', {}).get('version', '')})"},
        {"key": "耗时", "value": f"{payload.get('elapsed_ms', 0)} ms"},
    ]
    # 派生流是**可复现链的一部分** —— 少了它就说不清"这次怎么来的"
    for name in payload.get("streams", []):
        rows.append({"key": "派生流", "value": name})
    for txn_id, weight in sorted(payload.get("weights", {}).items()):
        if weight != 1:
            rows.append({"key": "权重", "value": f"{txn_id} = {weight}"})
    return rows


def _alloc_rows(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    objects = payload.get("allocations", {}).get("objects", [])
    return [{"name": o.get("name", ""), "region": o.get("region", ""),
             "offset": o.get("offset", ""), "size": o.get("size", ""),
             "role": o.get("role", "")} for o in objects]


def _note_rows(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """notes 与观测锚点合成一页 —— 两者都是"需要人看一眼"的东西。"""
    rows = [{"kind": "注意", "text": text} for text in payload.get("notes", [])]
    anchors = payload.get("expect", {}).get("anchors", [])
    if anchors:
        rows.append({"kind": "观测点",
                     "text": f"{len(anchors)} 个：" +
                             "、".join(a.get("tag", "") for a in anchors)})
    return rows


def _issue_text(issue: Dict[str, Any]) -> str:
    bits = [issue.get("message", "")]
    if issue.get("target"):
        bits.append(f"@ {issue['target']}")
    if issue.get("fix"):
        bits.append(f"→ {issue['fix']}")
    return "　".join(b for b in bits if b)

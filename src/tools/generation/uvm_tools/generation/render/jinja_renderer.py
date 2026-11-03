"""Jinja2 渲染器与模板过滤器 —— 只渲染，不判断业务。

从 `tool_uvm/gen_uvm.py` 搬出；调用方直接从这里导入（门面已删）。
`now()` 保持确定性（SOURCE_DATE_EPOCH），否则生成物不可复现。
"""
from __future__ import annotations

import os
import re
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

try:
    from jinja2 import Environment, FileSystemLoader, pass_context
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: Jinja2 is required. Install with: pip install jinja2"
    ) from exc


COMPANY_TRADEMARK = "SignOffAI（功能签核）"   # ← 替换成你的公司/组织名
COPYRIGHT_YEAR = "2026"

def reproducible_now() -> str:
    """模板里 `now()` 的实现 —— **确定性**，不再取墙上时钟。

    为什么必须确定：这个值会写进**每个**生成文件的头注释
    （`base_templates/base_template.sv.j2` 的「创建时间 / 修改时间」）。
    取墙上时钟的话，同一份输入跑两次得到不同的字节 —— 实测 86 个生成文件里
    76 个内容哈希不同。而证据链/产物比对正是靠内容哈希判断「这个产物有没有被
    动过」，假差异会让它失去意义；「可复现」这个卖点也就落不了地。

    规则对齐 reproducible-builds 的 `SOURCE_DATE_EPOCH` 约定：

      · 设了 `SOURCE_DATE_EPOCH`（Unix 秒）→ 用它格式化。CI 想钉死时间、
        或想要真实时间，都通过这个变量显式给。
      · 没设 → 返回**空串**，模板里那两行整行不输出（见模板改动）。
        默认就是可复现的，而不是默认不可复现、要用户自己去关。

    想做「确定性但带时间」，用 YAML 的 `meta.created` / `meta.modified` ——
    模板已经支持这两个键优先于 `now()`（`meta.created | default('') or now()`）。
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        # 值给错了不该让生成失败 —— 退回不可复现也要比炸掉好，但要出声
        print(f"[warn] SOURCE_DATE_EPOCH 不是合法 Unix 秒: {epoch!r}，本次不写时间戳")
        return ""


def _attr_slug(text: Any) -> str:
    """一段文本 → ASCII 标识符片段（非 [A-Za-z0-9] 一律折成 `_`）。

    中文维度名/取值都过这一道：它们能出现在注释里，但**不能出现在类名里**。
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").lower()


def attr_key(entry: Dict[str, Any]) -> str:
    """config_db 的键前缀。

    显式给的 `key` **原样用**（那是作者的命名选择，不该被我们小写化）；没给才由
    维度名推导。推导结果保证 ASCII —— config_db 的键会进 SV 字面量。
    """
    explicit = str(entry.get("key") or "").strip()
    if explicit:
        return explicit
    return _attr_slug(entry.get("dimension", "")) or "attr"


def attr_int_value(entry: Dict[str, Any]) -> int:
    """机器可读的整型取值 —— 这是**唯一进 SV 字面量的东西**。

    优先级：显式 `int_value` → 取值本身是数字 → 0。
    落到 0 意味着取值是中文且作者没给 `int_value`；类名那边会用 crc32 兜底保证
    不重名（见 `attr_class_slug`），而原取值仍以注释形式留在文件里。
    """
    explicit = entry.get("int_value")
    if isinstance(explicit, int) and not isinstance(explicit, bool):
        return explicit
    text = str(entry.get("value", "")).strip()
    try:
        return int(text)
    except ValueError:
        return 0


def attr_class_slug(entry: Dict[str, Any]) -> str:
    """类名里的 `<维度>_p<取值>` 片段，**保证全 ASCII**。

    取值是 ASCII 就直接用（`D_ratio` + `50` → `ratio_p50`）；是中文就投影到
    `int_value`（`D_mode` + 首拍 + 1 → `mode_p1`）。既非 ASCII 又没给 int_value
    时用 crc32 —— 硬编码成 `p0` 会让多个中文取值**撞成同一个类名**，那是编译错误。
    """
    dim = _attr_slug(entry.get("dimension", "")) or "attr"
    text = str(entry.get("value", "")).strip()
    if re.fullmatch(r"[A-Za-z0-9_]+", text):
        return f"{dim}_p{text}"
    if isinstance(entry.get("int_value"), int):
        return f"{dim}_p{attr_int_value(entry)}"
    return f"{dim}_p{zlib.crc32(text.encode('utf-8')) & 0xFFFF:04x}"


class JinjaRenderer:
    def __init__(self, templates_dir: Path) -> None:
        self.environment = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            keep_trailing_newline=True,
            autoescape=False,
        )
        # 文件头元数据（创建/修改时间 + 商标变量，base_template 兜底用）
        #
        # **`now` 必须是确定性的，否则生成物不可复现。**
        # 它落在每个生成文件的头注释里（base_template.sv.j2 的「创建/修改时间」）。
        # 取墙上时钟的话：同一份输入跑两次，实测 86 个文件里 76 个内容哈希不同 ——
        # 而证据链正是靠**内容哈希**判断「这个产物有没有被动过」。假差异会让比对
        # 失去意义，「可复现」也就无从谈起。
        self.environment.globals["now"] = reproducible_now
        self.environment.globals["trademark"] = COMPANY_TRADEMARK
        self.environment.globals["copyright_year"] = COPYRIGHT_YEAR
        self.environment.filters["nl2br"] = lambda value: str(value).replace("\n", "\\n")
        # 属性测试用的三个过滤器 —— 纯函数，能脱离 Jinja 单测
        self.environment.filters["attr_key"] = attr_key
        self.environment.filters["attr_int_value"] = attr_int_value
        self.environment.filters["attr_class_slug"] = attr_class_slug
        self.environment.globals["get_clock_index"] = lambda name, clocks: clocks.index(name) if name in clocks else 0
        self.environment.globals["get_reset_index"] = lambda name, resets: resets.index(name) if name in resets else 0
        self.environment.globals["get_transaction_type"] = self._get_transaction_type

    @staticmethod
    @pass_context
    def _get_transaction_type(context, transaction_name: str) -> str:
        transactions = context.get("transactions", [])
        for transaction in transactions:
            if transaction.get("name") == transaction_name:
                return transaction.get("type", f"{transaction_name}_transaction")
        return f"{transaction_name}_transaction"

    def render(self, template_path: str, context: Dict[str, Any]) -> str:
        template = self.environment.get_template(template_path)
        return template.render(**context)



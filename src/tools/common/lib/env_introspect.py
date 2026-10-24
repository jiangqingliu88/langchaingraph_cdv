"""从**生成出来的 UVM 环境**里读出接线 —— 句柄名、序列器、事务项类型。

为什么需要这个：往环境里补东西（补定向激励、注入序列、加断言）必须知道
"发给谁、发什么类型"，而这两件事**每套环境的命名都不一样** —— 名字是模板按
协议/agent 名拼出来的：

    env/apb_uart_env.sv            apb_master_agent apb_agent_h;   ← 句柄
    agents/apb_agent/5_agent/apb_master_agent.sv
                                   apb_master_sequencer sqr;       ← 序列器成员
    agents/apb_agent/3_transaction_sequencer/apb_master_sequencer.sv
                                   class apb_master_sequencer
                                     extends uvm_sequencer #(apb_master_seq_item);

补激励的那段代码原来**把这三个名字都写死了**（`{agent}_agent_h` /
`{agent}_base_seq` / `{agent}_seq_item`），一个都对不上：序列器参数类型不对 →
生成的序列编译不过 → 被 EDA 编译门禁退回空实现。补测试这一步看着跑了，
实际产出 0。

所以这里不猜：**从文件里读**。读不出来就返回空，让调用方如实说"没找到"，
而不是拿一个编出来的名字去生成编译不过的代码。

（同类错在这个仓库里出现过三次：覆盖率编译的 filelist 漏 UVM 库、补激励按平铺名
找文件、以及这里。共同点是"一处改了布局/命名，另一处照旧猜"。）
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _find_class_file(output_dir: Path, class_name: str) -> Optional[Path]:
    """在运行目录里找**定义这个类的文件**（`class <name> extends ...`）。"""
    pattern = re.compile(rf"\bclass\s+{re.escape(class_name)}\b")
    for base in ("agents", "env", "bench"):
        root = output_dir / base
        if not root.is_dir():
            continue
        for sv in sorted(root.rglob("*.sv")):
            if pattern.search(_read(sv)):
                return sv
    return None


def env_agent_bindings(output_dir: Path) -> List[Dict[str, str]]:
    """环境里每个 agent 的接线：`{handle, member, agent_type, sequencer, item}`。

    走查：**环境文件**里的 `apb_master_agent apb_agent_h;` → 该 agent 类里的
    序列器成员 → 序列器类的参数类型（事务项）。任何一步读不出来就把这个 agent
    跳过（宁缺毋滥），并在 `unresolved` 键上留个原因给调用方记日志。

    `member` 是 agent 里那个序列器**成员的名字** —— 模板给的是 `sequencer`
    （不是 uvm 惯用的 `sqr`），所以这个也要读、不能猜。
    """
    env_dir = output_dir / "env"
    if not env_dir.is_dir():
        return []
    env_file = None
    for cand in sorted(env_dir.glob("*_env.sv")):
        if re.search(r"^\s*class\s+\w+_env\b", _read(cand), re.M):
            env_file = cand
            break
    if env_file is None:
        return []
    env_text = _read(env_file)

    bindings: List[Dict[str, str]] = []
    # `apb_master_agent apb_agent_h;` —— 类型必须长得像 agent（排除 clk_rst 那类
    # 由模板另起的、没有 `_agent_h` 后缀的句柄）
    for m in re.finditer(r"^\s*(\w+_agent)\s+(\w+_agent_h)\s*;", env_text, re.M):
        agent_type, handle = m.group(1), m.group(2)
        agent_file = _find_class_file(output_dir, agent_type)
        if agent_file is None:
            bindings.append({"handle": handle, "agent_type": agent_type,
                             "unresolved": "找不到 agent 类文件"})
            continue
        # 序列器成员：agent 里的 `<type>_sequencer <member>;`（成员名模板给的是
        # `sequencer`，uvm 惯用 `sqr` —— 两个都收，取实际那个）
        seq_m = re.search(r"(\w+_sequencer)\s+(\w+)\s*;", _read(agent_file))
        if not seq_m:
            bindings.append({"handle": handle, "agent_type": agent_type,
                             "unresolved": "agent 里没有序列器成员"})
            continue
        sequencer, member = seq_m.group(1), seq_m.group(2)
        seqr_file = _find_class_file(output_dir, sequencer)
        item = ""
        if seqr_file is not None:
            item_m = re.search(
                rf"class\s+{re.escape(sequencer)}\s+extends\s+uvm_sequencer\s*#\s*\(\s*(\w+)\s*\)",
                _read(seqr_file))
            item = item_m.group(1) if item_m else ""
        binding = {"handle": handle, "member": member, "agent_type": agent_type,
                   "sequencer": sequencer, "item": item}
        if not item:
            binding["unresolved"] = f"序列器 {sequencer} 的事务项类型读不出来"
        bindings.append(binding)
    return bindings


def env_active_agents(output_dir: Path) -> Dict[str, bool]:
    """`{agents/ 下的目录名: 是不是 active}` —— 从 **env 模型**（`env.yaml`）读。

    ## 为什么这件事必须问模型，不能从生成物里"看出来"

    **passive agent 根本没有 sequencer。** 模板里它是这样建的：

        if (cfg.is_active == UVM_ACTIVE) begin
          sequencer = <ty>_sequencer::type_id::create("sequencer", this);
          ...
        end

    所以给一个 passive agent 注激励序列，`start()` 拿到的 `m_sequencer` 是 null，
    `start_item` 当场报

        UVM_FATAL [SEQ] neither the item's sequencer nor dedicated sequencer
                       has been supplied to start item in _gseq

    整条测试判失败（实测：`npu_sched_out` 是 `is_active: false` 的纯观察者，
    p0 就卡在这一条上，而它看起来像"DUT 挂了"）。

    原来这里用的是"接口文件里有没有 `output`"这个**文本启发式** —— 它与"sequencer
    会不会被建出来"根本不是一回事：观察者 agent 的接口里同样有 `output` 字样，
    于是照样被判成"会驱动 DUT"。**能算出来的东西不要猜。**

    读不到 `env.yaml` 的场合返回**空字典**（不是"全都 active"）—— 调用方据此
    一个都不注并记日志：注错是**必然** fatal，不注只是少一段激励。
    """
    import yaml as _yaml

    path = Path(output_dir) / "inputs" / "yaml" / "uvm" / "env.yaml"
    try:
        data = _yaml.safe_load(_read(path)) or {}
    except Exception:                                  # noqa: BLE001 读坏了当没有
        return {}
    if not isinstance(data, dict):
        return {}
    env = data.get("environment")
    if not isinstance(env, dict):
        return {}
    out: Dict[str, bool] = {}
    for a in (env.get("agents") or []):
        if isinstance(a, dict) and a.get("name"):
            # `name: apb_master` → 目录名 `apb_master_agent`（模板拼名字的约定）
            out[f"{a['name']}_agent"] = bool(a.get("is_active", True))
    return out


def binding_for_agent(bindings: List[Dict[str, str]], agent_dir_name: str) -> Optional[Dict[str, str]]:
    """把 `agents/` 下的目录名（`apb_agent`）对上一条接线（`apb_agent_h`）。

    目录名去掉 `_agent` 就是模板拼名字用的前缀（`apb`），句柄是
    `<前缀>_agent_h` —— 按这个对上。对不上返回 None（调用方如实记一笔）。
    """
    prefix = agent_dir_name[:-len("_agent")] if agent_dir_name.endswith("_agent") \
        else agent_dir_name
    for b in bindings:
        if b.get("handle", "").startswith(f"{prefix}_"):
            return b
    return None

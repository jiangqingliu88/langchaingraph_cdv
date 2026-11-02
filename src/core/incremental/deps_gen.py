"""用例依赖映射自动生成（`test_dependencies_v1`）。

输入**全部来自 run 目录**，不跑 EDA：

  1. `regression.yaml` 的 `file_pattern`（最可信，直接物化）；
  2. `inputs/yaml/uvm/env.yaml`：agent → interface；
  3. `coverage/testpoints.json` + `coverage/attribution.json` +
     `coverage/round_manifest.json`：test → TP → agent；
  4. `rtl/**/*.sv|v`：模块/接口名与 `` `include `` 依赖。

映射规则（**保守优先**）：

  · 只被一个 interface 命中的 RTL 文件 → 只进用该 interface 的用例；
  · 没命中任何 interface、命中多个 interface、或只是 package/include 的文件
    → 视为公共依赖，**所有用例**都依赖它；
  · agent/interface 任一映射不上 → 该用例不写进映射（`affected_tests` 会把它
    当 undeclared，保守全跑）；
  · `` `include `` 依赖做闭包。

这是**文件级启发式**，不是编译级真依赖；`source` 字段会写清楚。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

SCHEMA = "test_dependencies_v1"

_SEED_RE = re.compile(r"_seed_\d+")
_RUN_RE = re.compile(r"_run_\d+")
_MODULE_RE = re.compile(r"\b(?:module|interface|package)\s+([A-Za-z_]\w*)")
_INCLUDE_RE = re.compile(r'`include\s+"([^"]+)"')


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml
        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:                               # noqa: BLE001 可选依赖
        return {}
    return doc if isinstance(doc, dict) else {}


def _base_test(name: str) -> str:
    name = str(name or "").strip()
    if name.startswith("test_"):
        name = name[5:]
    return _RUN_RE.sub("", _SEED_RE.sub("", name)).rstrip("_") or name


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


# ── agent / interface ─────────────────────────────────────────

def _agent_interfaces(root: Path) -> Dict[str, str]:
    """从 env.yaml 读 agent → interface；找不到就按 `_master/_slave` 后缀推。"""
    out: Dict[str, str] = {}
    for path in sorted(root.glob("inputs/**/env.yaml")) + \
            sorted(root.glob("inputs/**/env.yml")):
        doc = _read_yaml(path)
        env = doc.get("environment") or doc
        agents = env.get("agents") if isinstance(env, dict) else None
        if isinstance(agents, dict):
            agents = list(agents.values())
        for agent in agents or []:
            if not isinstance(agent, dict) or not agent.get("name"):
                continue
            name = str(agent["name"])
            iface = str(agent.get("interface") or "").strip()
            if iface:
                out[name] = iface
        if out:
            break
    return out


def _iface_of_agent(name: str, mapping: Dict[str, str]) -> str:
    if name in mapping:
        return mapping[name]
    for suffix in ("_master", "_slave", "_agent", "_monitor", "_driver"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return ""


def _testpoint_maps(root: Path) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    tps = (_read_json(root / "coverage" / "testpoints.json").get("testpoints")
           or [])
    tp_agents: Dict[str, Set[str]] = {}
    test_tps: Dict[str, Set[str]] = {}
    for tp in tps:
        if not isinstance(tp, dict):
            continue
        tp_id = str(tp.get("tp_id") or "")
        if not tp_id:
            continue
        agent = str((tp.get("realization") or {}).get("agent") or "")
        if agent:
            tp_agents.setdefault(tp_id, set()).add(agent)
        test = _base_test(((tp.get("execution") or {}).get("test") or ""))
        if test:
            test_tps.setdefault(test, set()).add(tp_id)
    return tp_agents, test_tps


def _fact_tests(root: Path,
                test_tps: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    facts = _read_json(root / "coverage" / "round_manifest.json")
    for rnd in facts.get("rounds") or []:
        for fact in rnd.get("facts") or []:
            test = _base_test((fact or {}).get("test_name") or "")
            tp_id = str((fact or {}).get("tp_id") or "")
            if test and tp_id:
                test_tps.setdefault(test, set()).add(tp_id)
    return test_tps


def _attribution_tests(root: Path,
                       test_tps: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    exact = _read_json(root / "coverage" / "attribution.json")
    for item in exact.get("bins") or []:
        if not isinstance(item, dict) or item.get("confidence") != "exact":
            continue
        tp_id = str(item.get("tp_id") or "")
        if not tp_id:
            continue
        for test in item.get("tests") or []:
            test = _base_test(test)
            if test:
                test_tps.setdefault(test, set()).add(tp_id)
    return test_tps


def _test_agents(root: Path) -> Tuple[Dict[str, Set[str]], List[str]]:
    """test → agent 集合；也返回 agent 全空的用例名（不写进映射）。"""
    tp_agents, test_tps = _testpoint_maps(root)
    test_tps = _fact_tests(root, test_tps)
    test_tps = _attribution_tests(root, test_tps)
    agents_of: Dict[str, Set[str]] = {}
    for test, tp_ids in test_tps.items():
        agents: Set[str] = set()
        for tp_id in tp_ids:
            agents.update(tp_agents.get(tp_id, set()))
        agents_of[test] = agents
    unmapped = sorted(t for t, a in agents_of.items() if not a)
    return {t: a for t, a in agents_of.items() if a}, unmapped


# ── RTL 文件索引 ──────────────────────────────────────────────

EXTS = (".v", ".sv", ".svh", ".vh")


def _rtl_rel(path: Path, root: Path) -> str:
    """依赖路径口径 = `rtl_diff.snapshot()` 的口径（相对 `run/rtl`）。"""
    rtl = root / "rtl"
    try:
        return path.resolve().relative_to(rtl.resolve()).as_posix()
    except (ValueError, OSError):
        return _rel(path, root)


def _rtl_files(root: Path) -> List[Path]:
    rtl = root / "rtl"
    if not rtl.is_dir():
        return []
    return sorted(p for p in rtl.rglob("*")
                  if p.is_file() and p.suffix.lower() in EXTS)


def _index_rtl(root: Path, files: Iterable[Path],
               interfaces: Set[str]) -> Dict[str, Any]:
    defs: Dict[str, str] = {}
    texts: Dict[str, str] = {}
    includes: Dict[str, Set[str]] = {}
    file_ifaces: Dict[str, Set[str]] = {}
    mentioned: Dict[str, Set[str]] = {}
    defined: Set[str] = set()
    for path in files:
        rel = _rtl_rel(path, root)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        texts[rel] = text
        names = set(_MODULE_RE.findall(text))
        defined.update(names)
        for name in names:
            defs.setdefault(name, rel)
    for rel, text in texts.items():
        own = set(_MODULE_RE.findall(text))
        hit = {iface for iface in interfaces
               if re.search(rf"\b{re.escape(iface)}\b", text, re.IGNORECASE)}
        stem = Path(rel).stem.lower()
        hit.update(iface for iface in interfaces
                   if iface.lower() in stem)
        file_ifaces[rel] = hit
        mentioned[rel] = {name for name in defined - own
                          if re.search(rf"\b{re.escape(name)}\b", text,
                                       re.IGNORECASE)}
        incs = set()
        for inc in _INCLUDE_RE.findall(text):
            base = Path(inc).name
            for cand in texts:
                if Path(cand).name == base:
                    incs.add(cand)
                    break
        includes[rel] = incs
    # include 继承：被一个接口专属文件 include 的头文件，也归到该接口。
    changed = True
    while changed:
        changed = False
        for rel, incs in includes.items():
            iface = file_ifaces.get(rel) or set()
            if len(iface) != 1:
                continue
            for inc in incs:
                if not file_ifaces.get(inc):
                    file_ifaces[inc] = set(iface)
                    changed = True
    return {"defs": defs, "defined": defined, "texts": texts,
            "includes": includes, "file_ifaces": file_ifaces,
            "mentioned": mentioned}


def _common_files(index: Dict[str, Any]) -> Set[str]:
    """多接口/零接口/集成文件/package 文件 → 所有用例都依赖。"""
    out: Set[str] = set()
    for rel, ifaces in index["file_ifaces"].items():
        integration = len(index["mentioned"].get(rel) or []) > 1
        if len(ifaces) != 1 or integration:
            out.add(rel)
    return out


def _include_closure(files: Set[str], index: Dict[str, Any]) -> Set[str]:
    out = set(files)
    stack = list(files)
    while stack:
        cur = stack.pop()
        for inc in index["includes"].get(cur, set()):
            if inc not in out:
                out.add(inc)
                stack.append(inc)
    return out


# ── 生成 / 读取 ───────────────────────────────────────────────

def write_dependency_map(run_root: str | Path, doc: Dict[str, Any]) -> str:
    path = Path(run_root) / "coverage" / "test_dependencies.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return str(path)


def generate_dependency_map(run_root: str | Path, *, write: bool = False,
                            force: bool = False) -> Dict[str, Any]:
    """生成映射；已有 sidecar 且非 `force` 时原样返回。"""
    root = Path(run_root)
    existing = _read_json(root / "coverage" / "test_dependencies.json")
    from src.core.incremental.dependencies import derive_dependency_map
    from src.core.incremental.dependencies import all_tests as _all_tests
    if existing.get("tests") and not force:
        names = set(_all_tests(root)) | set(existing.get("tests") or {})
        return {**existing, "source": str(existing.get("source") or "existing"),
                "coverage_of_tests": (f"{len(existing.get('tests') or {})}/{len(names)}"
                                      if names else "0/0"),
                "path": str(root / "coverage" / "test_dependencies.json")}


    patterns = derive_dependency_map(root)
    if patterns:
        tests = {name: {"files": sorted(files)}
                 for name, files in patterns.items() if files}
        doc: Dict[str, Any] = {"schema": SCHEMA, "source": "regression_yaml",
                               "tests": tests, "unmapped_tests": [],
                               "notes": ["来自 regression.yaml 的 file_pattern"]}
    else:
        doc = _auto_from_agents(root)

    names = set(_all_tests(root)) | set(doc.get("tests") or {})
    doc["coverage_of_tests"] = (f"{len(doc.get('tests') or {})}/{len(names)}"
                                if names else "0/0")
    if write and doc.get("tests"):
        path = root / "coverage" / "test_dependencies.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
        doc["path"] = str(path)
    return doc


def _auto_from_agents(root: Path) -> Dict[str, Any]:
    notes: List[str] = []
    test_agents, unmapped = _test_agents(root)
    iface_map = _agent_interfaces(root)
    if not iface_map:
        # 没 env.yaml：按 agent 名的 `_master/_slave/...` 后缀推接口。
        for agents in test_agents.values():
            for agent in agents:
                iface = _iface_of_agent(agent, {})
                if iface:
                    iface_map[agent] = iface
        notes.append("没有 env.yaml，agent→interface 按名字后缀推断")
    if not iface_map:
        return {"schema": SCHEMA, "source": "none", "tests": {},
                "unmapped_tests": sorted(set(unmapped)),
                "notes": notes + ["没有可推断的 agent→interface 映射"]}
    interfaces = set(iface_map.values())
    files = _rtl_files(root)
    if not files:
        return {"schema": SCHEMA, "source": "none", "tests": {},
                "unmapped_tests": [],
                "notes": ["run 里没有 rtl/ 文件"]}

    index = _index_rtl(root, files, interfaces)
    common = _common_files(index)
    tests: Dict[str, Dict[str, List[str]]] = {}
    unresolved: List[str] = []
    for test, agents in sorted(test_agents.items()):
        ifaces = {_iface_of_agent(a, iface_map) for a in agents}
        if not all(ifaces):
            unresolved.append(test)
            continue
        deps = set(common)
        for rel, hit in index["file_ifaces"].items():
            if hit & ifaces:
                deps.add(rel)
        deps = _include_closure(deps, index)
        rels = sorted(deps)
        if rels:
            tests[test] = {"files": rels}

    notes.append("按 testpoint agent/interface 自动生成；未识别/多接口文件按公共依赖")
    if unresolved:
        notes.append(f"{len(unresolved)} 条用例的 agent 映射不全，按 undeclared 全跑")
    if not tests:
        notes.append("没有可映射的用例（testpoint/attribution/env 不完整）")
    return {"schema": SCHEMA, "source": "auto_agents", "tests": tests,
            "unmapped_tests": sorted(set(unmapped) | set(unresolved)),
            "agent_interfaces": dict(sorted(iface_map.items())),
            "common_files": sorted(common), "notes": notes}

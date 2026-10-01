"""YAML → CaseModel。

设计模式：**Repository**。上层只问「给我一个已解析好的模型」，
不关心它来自文件、字符串还是字典；也不关心解析里的别名归一。

这里是唯一允许把「人写的宽松写法」翻译成领域对象的地方 ——
所有别名查表都走 domain.vocab，本模块只负责结构组装。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from ..domain import (CHECK_ALIASES, CHECK_NAMES, DEFAULT_ID_PREFIX,
                      DEFAULT_REPEAT, DEFAULT_SEED, ENV_KEYS, METHOD_ALIASES,
                      METHOD_NAMES, CaseDefaults, CaseModel, CrossPair,
                      Generation, as_list, build_cross_group, build_cross_pair,
                      build_dimension, build_org_tree, build_theme, canon,
                      derive_code, flatten, normalize_priority, sort_themes)
from ..domain.errors import CaseModelError


# ════════════════════════════════════════════════════════════
# 代码 / 检查 / 方法
# ════════════════════════════════════════════════════════════

def _parse_coded_list(raw: Any, aliases: Dict[str, str],
                      names: Dict[str, str]) -> Tuple[List[str], Dict[str, str]]:
    """方法 / 检查这两段结构同形：字符串代号或 {id, name}，都归一成代号列表。"""
    out: List[str] = []
    labels: Dict[str, str] = {}
    for item in as_list(raw):
        if isinstance(item, dict):
            code = canon(str(item.get("id", "")), aliases)
            label = item.get("name") or ""
        else:
            code = canon(str(item), aliases)
            label = ""
        if code and code not in out:
            out.append(code)
            if label:
                labels[code] = str(label)
    for code in out:
        labels.setdefault(code, names.get(code, code))
    return out, labels


# ════════════════════════════════════════════════════════════
# 环境 / 生成参数 / 缺省属性
# ════════════════════════════════════════════════════════════

def _parse_env_defaults(raw: Any) -> Tuple[Dict[str, Any], List[str]]:
    """→ (已知键的缺省值, 未登记的键)。

    未登记的键**不静默丢弃** —— 拼错的键如果被吞掉，配置会「看似生效实则失效」，
    与「可复现·可审计」的定位不符，改为留给 analysis 报出来。
    """
    known: Dict[str, Any] = {}
    unknown: List[str] = []
    for k, v in (raw or {}).items():
        if k in ENV_KEYS:
            known[k] = v
        else:
            unknown.append(k)
    return known, unknown


def _parse_environment(raw: Any) -> Tuple[List[str], Dict[str, Any], List[str]]:
    """→ (必需的已知键, 缺省值, 未登记的键)。"""
    if not isinstance(raw, dict):
        return [], {}, []
    table = {k.upper(): k for k in ENV_KEYS}
    required: List[str] = []
    for x in as_list(raw.get("required")):
        hit = canon(str(x), table) or (str(x).strip() if str(x).strip() in ENV_KEYS else None)
        if hit and hit not in required:
            required.append(hit)
    defaults, unknown = _parse_env_defaults(raw.get("defaults"))
    return required, defaults, unknown


def _parse_generation(raw: Any, model_methods: Sequence[str]) -> Generation:
    if not isinstance(raw, dict):
        return Generation(methods=list(model_methods), declared=False)

    methods = [m for m in (canon(str(x), METHOD_ALIASES)
                           for x in as_list(raw.get("methods"))) if m]
    try:
        seed = int(raw["seed"]) if raw.get("seed") is not None else DEFAULT_SEED
    except (TypeError, ValueError):
        seed = DEFAULT_SEED
    try:
        repeat = int(raw.get("repeat") or DEFAULT_REPEAT)
    except (TypeError, ValueError):
        repeat = DEFAULT_REPEAT
    max_cases: Optional[int] = None
    if raw.get("max_cases") is not None:
        try:
            max_cases = int(raw["max_cases"])
        except (TypeError, ValueError):
            max_cases = None

    priorities: List[str] = []
    for x in as_list(raw.get("priorities")):
        p = normalize_priority(x, default="")
        if p and p not in priorities:
            priorities.append(p)

    return Generation(
        themes=[str(t) for t in as_list(raw.get("themes"))],
        priorities=priorities,
        methods=methods or list(model_methods),
        groups=[str(g) for g in as_list(raw.get("groups"))],
        dimensions=[str(d) for d in as_list(raw.get("dimensions"))],
        sub_objects=[str(s) for s in as_list(raw.get("sub_objects"))],
        seed=seed,
        repeat=max(1, repeat),
        max_cases=max_cases,
        declared=True,
    )


def _parse_case_defaults(raw: Any) -> Tuple[CaseDefaults, List[str]]:
    if not isinstance(raw, dict):
        return CaseDefaults(), []
    checks = [c for c in (canon(str(x), CHECK_ALIASES)
                          for x in as_list(raw.get("checks"))) if c]
    env, unknown = _parse_env_defaults(raw.get("environment"))
    prefix = str(raw.get("id_prefix") or DEFAULT_ID_PREFIX).strip().upper()
    return CaseDefaults(id_prefix=prefix or DEFAULT_ID_PREFIX,
                        expected_result=str(raw.get("expected_result") or ""),
                        checks=checks, environment=env), unknown


def _parse_cross(raw: Any) -> List[CrossPair]:
    """两种等价写法：映射式 {"长度×模式": required} 或列表式 [{pair, level}]。"""
    pairs: List[CrossPair] = []
    if isinstance(raw, dict):
        for key, level_raw in raw.items():
            pair = build_cross_pair(str(key), level_raw)
            if pair:
                pairs.append(pair)
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            refs = as_list(item.get("pair"))
            if len(refs) != 2:
                continue
            from ..domain.vocab import CROSS_LEVEL_ALIASES
            pairs.append(CrossPair(
                a=str(refs[0]), b=str(refs[1]),
                level=canon(str(item.get("level")), CROSS_LEVEL_ALIASES) or "optional",
                reason=str(item.get("reason") or ""), source="declared"))
    return pairs


# ════════════════════════════════════════════════════════════
# 组装
# ════════════════════════════════════════════════════════════

def model_from_dict(data: Any, source: str = "<dict>") -> CaseModel:
    """dict → CaseModel（含归一化与引用解析）。结构非法时抛 CaseModelError。"""
    if not isinstance(data, dict):
        raise CaseModelError(f"顶层必须是 mapping，当前为 {type(data).__name__}")

    raw_obj = data.get("object")
    if not isinstance(raw_obj, str) or not raw_obj.strip():
        raise CaseModelError(
            "缺少必填字段 'object'（必须是对象名的字符串，"
            f"当前为 {type(raw_obj).__name__}）")
    obj = raw_obj.strip()

    dims_raw = data.get("dimensions")
    if not isinstance(dims_raw, list) or not dims_raw:
        raise CaseModelError("缺少必填字段 'dimensions'（至少一个维度）")

    declared_code = str(data.get("object_code") or "").strip().upper()
    object_code = declared_code or derive_code(obj) or "OBJ"

    dimensions = [d for d in (build_dimension(x) for x in dims_raw) if d is not None]
    if not dimensions:
        raise CaseModelError("dimensions 里没有任何合法维度条目")

    org_root = build_org_tree(data.get("sub_objects"), object_code)
    themes = [t for t in (build_theme(x, i)
                          for i, x in enumerate(as_list(data.get("themes")), start=1))
              if t is not None]
    methods, method_names = _parse_coded_list(data.get("methods"),
                                              METHOD_ALIASES, METHOD_NAMES)
    checks, check_names = _parse_coded_list(data.get("checks"),
                                            CHECK_ALIASES, CHECK_NAMES)
    env_required, env_defaults, env_unknown = _parse_environment(data.get("environment"))
    case_defaults, defaults_unknown = _parse_case_defaults(data.get("case_defaults"))
    generation = _parse_generation(data.get("generation"), methods)

    model = CaseModel(
        object=obj,
        dimensions=dimensions,
        version=str(data.get("version") or ""),
        object_cn=str(data.get("object_cn") or ""),
        object_code=object_code,
        object_code_declared=bool(declared_code),
        description=str(data.get("description") or ""),
        org_root=org_root,
        sub_objects=flatten(org_root),
        themes=sort_themes(themes),
        methods=methods,
        method_names=method_names,
        checks=checks,
        check_names=check_names,
        cross_pairs=_parse_cross(data.get("cross_matrix")),
        cross_groups=[g for g in (build_cross_group(x, i)
                                  for i, x in enumerate(
                                      as_list(data.get("cross_groups")), start=1))
                      if g is not None],
        env_required=env_required,
        env_defaults=env_defaults,
        env_unknown_keys=list(dict.fromkeys(env_unknown + defaults_unknown)),
        generation=generation,
        case_defaults=case_defaults,
        source=source,
    )
    # environment.defaults 与 case_defaults.environment 合并，后者优先
    merged = dict(env_defaults)
    merged.update(case_defaults.environment)
    model.case_defaults.environment = merged
    if not model.case_defaults.checks:
        model.case_defaults.checks = list(checks)

    return model.resolve()


# ════════════════════════════════════════════════════════════
# Repository 门面
# ════════════════════════════════════════════════════════════

def load_model(path: str | Path) -> CaseModel:
    """读取 YAML 文件 → CaseModel。"""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise                       # 交给调用方报「文件不存在」，别伪装成模型错误
    except OSError as exc:
        raise CaseModelError(f"读取失败 {p}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CaseModelError(f"YAML 解析失败 {p.name}: {exc}") from exc
    return model_from_dict(data, source=str(p))


def load_model_from_text(text: str, source: str = "<text>") -> CaseModel:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CaseModelError(f"YAML 解析失败: {exc}") from exc
    return model_from_dict(data, source=source)

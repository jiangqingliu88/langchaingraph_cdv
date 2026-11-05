"""外部真实 case 列表的读取。

设计模式：**Repository**。把 YAML / JSON / CSV 三种外壳都收敛成
`List[ExternalCase]`，上层不必知道输入长什么样。

四种输入形状都接受（与 `generate --format` 的输出同构，所以能闭环）：
    ① {cases: [...]}       —— generate --format yaml/json 的输出
    ② [ {...}, {...} ]     —— 裸列表
    ③ {case_id: ..., ...}  —— 单条
    ④ .csv                 —— generate --format csv 的输出

fields 也写得宽松：mapping、['k=v', ...] 列表、'k=v|k2=v2' 字符串都认 ——
真实工程里的 case 列表往往是脚本生成的，形状不会整齐。
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..domain import ENV_KEYS, ExternalCase
from ..domain.errors import CaseListError

YAML_SUFFIXES = (".yaml", ".yml")
JSON_SUFFIXES = (".json",)
CSV_SUFFIXES = (".csv",)


# ════════════════════════════════════════════════════════════
# 取值归一
# ════════════════════════════════════════════════════════════

def _norm_token(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _as_str_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [s.strip() for s in re.split(r"[、,;|]", raw) if s.strip()]
    if isinstance(raw, (list, tuple)):
        return [t for t in (_norm_token(x) for x in raw) if t]
    return [_norm_token(raw)]


def _parse_fields(raw: Any) -> Dict[str, str]:
    """fields 允许写成 mapping、'name=value' 列表、或 'a=1|b=2' 字符串。"""
    if raw is None:
        return {}
    if isinstance(raw, str):
        return _parse_fields(_as_str_list(raw))
    if isinstance(raw, dict):
        return {str(k).strip(): _norm_token(v) for k, v in raw.items()}
    if isinstance(raw, (list, tuple)):
        out: Dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict):
                out.update({str(k).strip(): _norm_token(v)
                            for k, v in item.items()})
                continue
            text = _norm_token(item)
            for sep in ("=", ":"):
                if sep in text:
                    name, _, value = text.partition(sep)
                    out[name.strip()] = value.strip()
                    break
        return out
    return {}


def _parse_environment(raw: Any) -> Dict[str, Any]:
    """只认登记的键 —— 环境指纹的键集合是全项目唯一来源（domain.vocab）。"""
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if k in ENV_KEYS}
    if isinstance(raw, str):
        out: Dict[str, Any] = {}
        for part in raw.split("|"):
            if "=" in part:
                k, _, v = part.partition("=")
                if k.strip() in ENV_KEYS:
                    out[k.strip()] = v.strip()
        return out
    return {}


def _case_from_item(item: Any, index: int) -> ExternalCase:
    if isinstance(item, str):
        return ExternalCase(index=index, case_id=item.strip())
    if not isinstance(item, dict):
        raise CaseListError(f"第 {index} 条不是 mapping（{type(item).__name__}）")
    case_id = _norm_token(item.get("case_id") or item.get("id") or item.get("name"))
    if not case_id:
        raise CaseListError(f"第 {index} 条没有 case_id")
    return ExternalCase(
        index=index,
        case_id=case_id,
        object=_norm_token(item.get("object")),
        sub_object=_norm_token(item.get("sub_object") or item.get("sub_object_name")),
        sub_object_id=_norm_token(item.get("sub_object_id")),
        theme=_norm_token(item.get("theme") or item.get("theme_id")),
        priority=_norm_token(item.get("priority")),
        tree_path=_norm_token(item.get("tree_path")),
        method=_norm_token(item.get("method") or item.get("method_code")).upper(),
        cross_group=_norm_token(item.get("cross_group")),
        fields=_parse_fields(item.get("fields") or item.get("field_values")),
        checks=[c.upper() for c in _as_str_list(item.get("checks"))],
        cover_bins=_as_str_list(item.get("cover_bins")),
        environment=_parse_environment(item.get("environment")),
        expected_result=_norm_token(item.get("expected_result")),
    )


def cases_from_payload(data: Any) -> List[Any]:
    """把各种外壳拆成 case 条目列表。"""
    if isinstance(data, dict):
        for key in ("cases", "case_list", "testcases", "tests"):
            if key in data:
                return list(data[key] or [])
        return [data]                      # 单条 case
    if isinstance(data, list):
        return data
    raise CaseListError(f"case 列表必须是 mapping 或 list，当前为 {type(data).__name__}")


# ════════════════════════════════════════════════════════════
# Repository 门面
# ════════════════════════════════════════════════════════════

def load_cases(path: str | Path) -> List[ExternalCase]:
    """读取外部 case 列表文件（.yaml/.yml/.json/.csv）。"""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise CaseListError(f"读取失败 {p}: {exc}") from exc
    return cases_from_text(text, hint=p.suffix.lower(), source=p.name)


def cases_from_text(text: str, hint: str = ".yaml",
                    source: str = "<text>") -> List[ExternalCase]:
    """文本 → ExternalCase 列表。hint 决定按哪种格式解析。"""
    try:
        if hint in CSV_SUFFIXES:
            rows = list(csv.DictReader(io.StringIO(text)))
        elif hint in JSON_SUFFIXES:
            rows = cases_from_payload(json.loads(text))
        elif hint in YAML_SUFFIXES:
            rows = cases_from_payload(yaml.safe_load(text))
        else:
            raise CaseListError(
                f"不支持的格式 '{hint}'（支持 .yaml/.yml/.json/.csv）")
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise CaseListError(f"解析失败 {source}: {exc}") from exc

    return [_case_from_item(item, i) for i, item in enumerate(rows, start=1)]


def load_case_file(path: Optional[str | Path]) -> Optional[List[ExternalCase]]:
    return None if path is None else load_cases(path)

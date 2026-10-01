"""case 属性表的导出格式。

设计模式：**Strategy**。四种格式（table / yaml / json / csv）是对同一份
CaseAttribute 列表的四种排布，彼此可替换。新增格式 = 新增一个子类 + 登记。

导出的形状与 `repository.case_list` 的输入形状**刻意保持同构** ——
所以「生成 → 落盘 → 拿它当真实 case 核对」能闭环，不用转换脚本。
四种格式都有往返测试固定这一点。
"""
from __future__ import annotations

import csv
import io
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Sequence

import yaml

from ..domain import CaseAttribute


class ExportStrategy(ABC):
    """一种导出格式。"""
    key: str = ""
    name: str = ""

    @abstractmethod
    def render(self, cases: Sequence[CaseAttribute], meta: Dict) -> str:
        ...


class JsonExporter(ExportStrategy):
    key = "json"
    name = "JSON"

    def render(self, cases, meta) -> str:
        return json.dumps({**meta, "cases": [c.to_dict() for c in cases]},
                          ensure_ascii=False, indent=2)


class YamlExporter(ExportStrategy):
    key = "yaml"
    name = "YAML"

    def render(self, cases, meta) -> str:
        return yaml.safe_dump({**meta, "cases": [c.to_dict() for c in cases]},
                              allow_unicode=True, sort_keys=False,
                              default_flow_style=False)


class CsvExporter(ExportStrategy):
    """CSV —— fields / checks / cover_bins / environment 用 '|' 连接。

    列集合与 case_list._parse_csv 读的列一一对应。
    """
    key = "csv"
    name = "CSV"

    COLUMNS = ("case_id", "object", "sub_object", "sub_object_id", "theme",
               "priority", "tree_path", "dimensions", "fields", "method",
               "cross_group", "checks", "cover_bins", "environment",
               "expected_result", "seed")

    def render(self, cases, meta) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(self.COLUMNS)
        for c in cases:
            writer.writerow([
                c.case_id, c.object, c.sub_object, c.sub_object_id, c.theme,
                c.priority, c.tree_path, "|".join(c.dimensions),
                "|".join(f"{k}={v}" for k, v in c.fields.items()),
                c.method, c.cross_group, "|".join(c.checks),
                "|".join(c.cover_bins),
                "|".join(f"{k}={v}" for k, v in c.environment.items()),
                c.expected_result, c.seed,
            ])
        return buf.getvalue()


class TableExporter(ExportStrategy):
    """人读的文本表 —— 按专题分组，专题内按 case_id 排列。"""
    key = "table"
    name = "文本表"

    def render(self, cases, meta) -> str:
        head = (f"case 属性表 —— {len(cases)} 个"
                f"（seed={meta.get('seed')}"
                f"{'，已截断' if meta.get('truncated') else ''}）")
        out: List[str] = [head, "─" * 78]
        current_theme = None
        for c in cases:
            if c.theme != current_theme:
                current_theme = c.theme
                label = c.theme or "（无专题）"
                out.append(f"  ── {c.priority} {label} ──" if c.priority
                           else f"  ── {label} ──")
            out.append(f"    {c.case_id}  {c.method}  "
                       f"{c.tree_path or '（不作用功能组织树）'}")
            out.append("        字段   "
                       + "；".join(f"{k}={v}" for k, v in c.fields.items()))
            out.append(f"        检查   {'、'.join(c.checks) or '（无）'}")
        for note in meta.get("notes") or []:
            out.append(f"  注意: {note}")
        return "\n".join(out)


EXPORTERS: Dict[str, ExportStrategy] = {
    e.key: e for e in (TableExporter(), YamlExporter(), JsonExporter(), CsvExporter())
}

EXPORT_FORMATS = tuple(EXPORTERS)


def exporter(key: str) -> ExportStrategy:
    return EXPORTERS.get(key) or EXPORTERS["table"]


def export_cases(cases: Sequence[CaseAttribute], fmt: str = "table",
                 **meta) -> str:
    return exporter(fmt).render(cases, meta)

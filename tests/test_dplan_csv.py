"""dplan CSV 人读视图：写出/读回，并且人工改 CSV 要盖过 JSON sidecar。"""
from __future__ import annotations

import csv
from pathlib import Path

from src.engine.front.main import _apply_dplan_csv
from src.engine.front.vplan.dplan_csv import (
    load_dplan_csvs, write_dplan_csvs)


def _contract():
    return {
        "design_name": "demo",
        "overview": "demo design",
        "architecture": {"top": "demo"},
        "interfaces": [
            {"name": "clk", "data_width": 1, "direction": "INPUT",
             "protocol": "clock", "description": "clock"},
            {"name": "cmd_vld", "data_width": 1, "direction": "INPUT",
             "protocol": "valid-ready", "description": "valid"},
            {"name": "cmd_data", "data_width": 74, "direction": "INPUT",
             "protocol": "valid-ready", "description": "bit[73:0]"},
        ],
        "modules": [
            {"name": "demo", "level": "top", "interfaces": [
                {"name": "clk", "data_width": 1, "direction": "INPUT"},
                {"name": "cmd_vld", "data_width": 1, "direction": "INPUT"},
                {"name": "cmd_data", "data_width": 74, "direction": "INPUT"}]},
            {"name": "decode", "level": "sub", "method": "pipeline",
             "function": "decode", "interfaces": [
                 {"name": "cmd_data", "data_width": 74, "direction": "INPUT"}]},
        ],
        "model_contract": {"module": "demo", "scoreboard": "sb",
                           "ports": [{"name": "cmd_data", "data_width": 74,
                                      "direction": "INPUT", "protocol": ""}]},
    }


def test_dplan_csv_roundtrip(tmp_path):
    paths = write_dplan_csvs(tmp_path, "demo", _contract())
    for key in ("interfaces", "modules", "model_ports"):
        assert Path(paths[key]).is_file(), key
    loaded = load_dplan_csvs(tmp_path, "demo")
    assert len(loaded["interfaces"]) == 3
    assert {m["name"] for m in loaded["modules"]} == {"demo", "decode"}
    top = next(m for m in loaded["modules"] if m["name"] == "demo")
    assert len(top["interfaces"]) == 3
    assert loaded["model_contract"]["ports"][0]["data_width"] == 74


def test_edited_csv_overrides_json(tmp_path):
    write_dplan_csvs(tmp_path, "demo", _contract())
    # 人工审阅时把 cmd_data 位宽从 74 改成 64
    path = tmp_path / "demo_dplan_interfaces.csv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    fields = list(rows[0])
    for row in rows:
        if row["name"] == "cmd_data":
            row["data_width"] = "64"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    doc = {"design_name": "demo", "interfaces": _contract()["interfaces"]}
    out = _apply_dplan_csv(doc, tmp_path / "demo_dplan.json")
    widths = {i["name"]: i["data_width"] for i in out["interfaces"]}
    assert widths["cmd_data"] == 64

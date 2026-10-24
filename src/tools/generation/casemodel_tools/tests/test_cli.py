"""两个 CLI 入口 —— 工具自带的 cli.py 与主 CLI 的 `vagent case-model`。

两者能力等价，只有退出码与输出格式的约定要一致。
"""
from __future__ import annotations

import json
import pytest
import yaml
from click.testing import CliRunner

from src.tools.generation.casemodel_tools.cli import main as cli_main

from .conftest import CPU, CPU_FLAWED, EXAMPLES, FC, FC_REAL


SUBCOMMANDS = ("check", "analyze", "matrix", "tree", "rules", "generate",
               "uvm-tests", "testpoints", "covergroups", "coverage-plan",
               "associate", "constraints")


def test_cli_help_lists_every_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out + capsys.readouterr().err
    for name in SUBCOMMANDS:
        assert name in out


def test_tool_cli_has_no_gui_subcommand():
    """界面不在本包里 —— 它搬去了验证工作台。

    这条防的是「顺手把 gui 加回来」：加回来就意味着本包又要认识 Qt，
    而它现在能在不装 PySide6 的环境里单独用，那正是搬走界面的收益。
    `vagent case-model gui` 仍在，但它属于主 CLI，不属于这里。
    """
    from src.tools.generation.casemodel_tools.cli import build_parser
    choices = set()
    for action in build_parser()._subparsers._group_actions:      # noqa: SLF001
        choices |= set(action.choices)
    assert choices == set(SUBCOMMANDS)
    assert "gui" not in choices


def test_importing_the_package_pulls_in_neither_qt_nor_langchain():
    """纯工具的含义就是字面的：导入它不该把 PySide6 或 langchain 拖进来。"""
    import subprocess
    import sys as _sys

    code = (
        "import sys\n"
        "import src.tools.generation.casemodel_tools.cli\n"
        "import src.tools.generation.casemodel_tools.api\n"
        "heavy = [m for m in sys.modules\n"
        "         if m.startswith(('PySide6', 'langchain'))]\n"
        "print(heavy)\n"
    )
    result = subprocess.run([_sys.executable, "-c", code],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_cli_check_exit_codes():
    assert cli_main(["check", str(CPU)]) == 0
    assert cli_main(["check", str(CPU_FLAWED)]) == 0     # 语法合法，语义有问题


def test_cli_check_directory(capsys):
    from .conftest import EXAMPLES
    assert cli_main(["check", str(EXAMPLES), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    by_name = {p["file"].split("\\")[-1].split("/")[-1]: p for p in payload}
    assert by_name["cpu_pipeline.yaml"]["valid"] is True
    assert by_name["fc_real_cases.yaml"]["valid"] is False   # 它是 case 列表


def test_cli_analyze_exit_code_reflects_errors():
    assert cli_main(["analyze", str(CPU)]) == 0
    assert cli_main(["analyze", str(CPU_FLAWED)]) == 1


def test_cli_analyze_json_payload(capsys):
    cli_main(["analyze", str(CPU), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["case_count"] > 0
    assert payload["themes"] and payload["org_tree"]
    assert payload["score_total"] > 0
    assert "external" not in payload            # 没给 --cases


def test_cli_analyze_with_cases_and_report(tmp_path, capsys):
    report = tmp_path / "r.txt"
    assert cli_main(["analyze", str(FC), "--cases", str(FC_REAL),
                     "--report", str(report)]) == 1
    out = capsys.readouterr().out
    assert "真实 case 核对" in out and "评分必须只是模型的属性" in out
    assert "真实 case 核对" in report.read_text(encoding="utf-8")


def test_cli_analyze_with_cases_json(capsys):
    cli_main(["analyze", str(FC), "--cases", str(FC_REAL), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["external"]["case_count"] == 45


def test_cli_tree_and_matrix(capsys):
    assert cli_main(["tree", str(CPU)]) == 0
    assert "功能组织树" in capsys.readouterr().out
    assert cli_main(["matrix", str(CPU)]) == 0
    assert "维度交叉矩阵" in capsys.readouterr().out


def test_cli_rules(capsys):
    assert cli_main(["rules"]) == 0
    assert "校验规则" in capsys.readouterr().out
    assert cli_main(["rules", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) >= 45


@pytest.mark.parametrize("fmt", ["yaml", "json", "csv", "table"])
def test_cli_generate_formats(capsys, fmt):
    assert cli_main(["generate", str(CPU), "--format", fmt,
                     "--max-cases", "3"]) == 0
    assert capsys.readouterr().out.strip()


def test_cli_generate_writes_file_and_reports_notes(tmp_path, capsys):
    out = tmp_path / "cases.yaml"
    assert cli_main(["generate", str(CPU), "--format", "yaml",
                     "--out", str(out), "--max-cases", "4"]) == 0
    assert "已写出" in capsys.readouterr().out
    assert len(yaml.safe_load(out.read_text(encoding="utf-8"))["cases"]) == 4


def test_cli_seed_override(capsys):
    cli_main(["generate", str(CPU), "--format", "json", "--seed", "9"])
    assert json.loads(capsys.readouterr().out)["seed"] == 9


def test_cli_missing_file_is_exit_2(tmp_path):
    assert cli_main(["analyze", str(tmp_path / "nope.yaml")]) == 2


def test_cli_rejects_broken_yaml(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    assert cli_main(["analyze", str(bad)]) == 2


# ════════════════════════════════════════════════════════════
# vagent case-model（主 CLI）
# ════════════════════════════════════════════════════════════

def vagent(args):
    from src.cli.commands import cli
    return CliRunner().invoke(cli, args, catch_exceptions=False)


def test_vagent_group_has_all_subcommands():
    res = vagent(["case-model", "--help"])
    assert res.exit_code == 0
    # **两个入口能力等价** —— 这里列的是契约，漏一个就是"工具 CLI 有、主 CLI 没有"
    for sub in ("check", "analyze", "generate", "uvm-tests", "gui", "tree", "rules",
                "covergroups", "coverage-plan", "associate", "constraints"):
        assert sub in res.output


def test_vagent_check_and_analyze_exit_codes():
    assert vagent(["case-model", "check", str(CPU)]).exit_code == 0
    assert vagent(["case-model", "analyze", str(CPU)]).exit_code == 0
    assert vagent(["case-model", "analyze", str(CPU_FLAWED)]).exit_code == 1


def test_vagent_analyze_with_cases(tmp_path):
    report = tmp_path / "r.txt"
    res = vagent(["case-model", "analyze", str(FC), "--cases", str(FC_REAL),
                  "--report", str(report)])
    assert res.exit_code == 1                   # 真实 case 有 error
    assert "真实 case 核对" in res.output
    assert report.exists()


def test_vagent_analyze_json_has_external():
    res = vagent(["case-model", "analyze", str(FC), "--cases", str(FC_REAL),
                  "--json"])
    payload = json.loads(res.output)
    assert payload["external"]["case_count"] == 45


def test_vagent_tree_and_rules():
    assert "功能组织树" in vagent(["case-model", "tree", str(CPU)]).output
    assert "校验规则" in vagent(["case-model", "rules"]).output


def test_vagent_generate_to_file(tmp_path):
    out = tmp_path / "c.yaml"
    res = vagent(["case-model", "generate", str(CPU), "-f", "yaml",
                  "-o", str(out), "--max-cases", "3"])
    assert res.exit_code == 0
    assert len(yaml.safe_load(out.read_text(encoding="utf-8"))["cases"]) == 3


def test_vagent_generate_table_to_stdout():
    res = vagent(["case-model", "generate", str(CPU), "--max-cases", "2"])
    assert res.exit_code == 0 and "case 属性表" in res.output


def test_vagent_uvm_tests_stdout_and_file(tmp_path):
    """主 CLI 的 `uvm-tests` 与工具自带那条等价 —— 产物就是能直接贴的那段 YAML。"""
    res = vagent(["case-model", "uvm-tests", str(FC), "-d", "D_ratio"])
    assert res.exit_code == 0
    # 首行是 `# 4 条属性测试（维度：…）` 注释，YAML 会忽略它
    assert len(yaml.safe_load(res.output)["tests"]) == 4

    out = tmp_path / "tests.yaml"
    res = vagent(["case-model", "uvm-tests", str(FC), "-d", "D_ratio",
                  "--max-tests", "2", "-o", str(out)])
    assert res.exit_code == 0
    assert len(yaml.safe_load(out.read_text(encoding="utf-8"))["tests"]) == 2

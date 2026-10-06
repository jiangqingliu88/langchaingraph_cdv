"""验证 v7 修复：① gaps reason 契约对齐 ② fixer ReAct 循环 ③ 动作闭环参数传递。"""
import sys, tempfile, pathlib
sys.path.insert(0, 'src')
from unittest.mock import patch

# ── ① gaps reason 规范化 ──
from layers_engine.l3_decision.domain.analyzer import coverage_gap_analysis

# LLM 只给 suggestion 不给 reason → 应映射为 reason
llm_json = ('{"uncovered_bins": ["b1"], '
            '"gaps": [{"metric": "Branches", "suggestion": "RELAX_CONSTRAINT", "cause": "约束过紧"}, '
            '          {"metric": "Statements", "suggestion": "GENERATE_DIRECTED_TEST", "cause": "未激励"}], '
            '"analysis": "测试"}')
with tempfile.TemporaryDirectory() as d:
    od = pathlib.Path(d)
    # 造一个 fake vcover 输出：无 ucdb → 走 LLM 分支
    (od / 'sim' / 'coverage').mkdir(parents=True)
    with patch('layers_engine.l3_decision.domain.analyzer.call_llm', return_value=llm_json):
        r = coverage_gap_analysis(od, {"Total": {"pct": 15.0}}, target=30.0)
    reasons = [g.get('reason') for g in r['gaps']]
    print('[1] gaps reasons:', reasons)
    assert reasons == ['constraint', 'unstimulated'], f"FAIL: {reasons}"
    print('[1] PASS: suggestion→reason 映射正确')

# ── ② fixer ReAct 循环收敛 ──
from layers_engine.l3_decision.domain.fixer import debug_fix_files

# 模拟：第一次 LLM 修复不彻底（verify 返回 failed），第二次修复后 verify 返回 passed
fix1 = ('{"fixes": [{"file": "agents/intr/intr_driver.sv", "line": 1, '
        '"old": "bad line", "new": "fixed line"}]}')
fix2 = ('{"fixes": [{"file": "agents/intr/intr_driver.sv", "line": 2, '
        '"old": "bad line2", "new": "fixed line2"}]}')
llm_calls = {"calls": 0}

def fake_llm(system, user, **kw):
    llm_calls["calls"] += 1
    return fix1 if llm_calls["calls"] == 1 else fix2

verify_results = iter([(False, "new error log"), (True, "")])

def fake_verify(_od):
    return next(verify_results)

with tempfile.TemporaryDirectory() as d:
    od = pathlib.Path(d)
    f = od / 'agents' / 'intr' / 'intr_driver.sv'
    f.parent.mkdir(parents=True)
    f.write_text('bad line\nbad line2\n', encoding='utf-8')
    # 日志必须含真实文件路径（extract_sv_files_from_log 从错误行提取目标文件）
    sim_log = f"** Error: D:/{od.name}/agents/intr/intr_driver.sv(1): bad syntax"
    with patch('layers_engine.l3_decision.domain.fixer.call_llm', side_effect=fake_llm):
        n = debug_fix_files(od, sim_log, "compile",
                            verify=fake_verify, max_react=3)
    print('[2] fixed:', n, '| llm calls:', llm_calls["calls"])
    print('[2] file:', repr(f.read_text(encoding='utf-8')))
    assert n == 2 and llm_calls["calls"] == 2, "FAIL: ReAct 应两次修复"
    print('[2] PASS: ReAct 循环（修复→验证→再修→收敛）')

# ── ③ 动作闭环参数 ──
from layers_engine.l3_decision.driver import _exec_action
r = _exec_action("GENERATE_DIRECTED_TEST", {"gaps": []}, pathlib.Path('.'), seed=5)
print('[3] action:', r.get('action'), 'seed:', r.get('seed'), 'num_trans:', r.get('num_transactions'))
assert r.get('seed') == 6 and r.get('num_transactions') == 200, "FAIL"
print('[3] PASS: GENERATE_DIRECTED_TEST → seed=6 + 事务=200')

print('\nALL PASS')

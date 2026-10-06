import sys, tempfile, pathlib
sys.path.insert(0, 'src')
from layers_engine.l3_decision.domain.fixer import apply_minimal_fixes as _apply_minimal_fixes, parse_minimal_fixes as _parse_minimal_fixes

# 解析测试（带 markdown 围栏）
txt = ('```json\n{"fixes": [{"file": "agents/intr/intr_driver.sv", "line": 143, '
       '"old": "  vif.cb.irq <= req.irq;", "new": "  // irq is DUT output; monitor samples only"}]}\n```')
fixes = _parse_minimal_fixes(txt)
print('parsed fixes:', len(fixes), '->', fixes[0]['file'], fixes[0]['line'])

# 应用测试
with tempfile.TemporaryDirectory() as d:
    od = pathlib.Path(d)
    f = od / 'agents' / 'intr' / 'intr_driver.sv'
    f.parent.mkdir(parents=True)
    f.write_text('line1\n  vif.cb.irq <= req.irq;\nline3\n', encoding='utf-8')
    n = _apply_minimal_fixes(od, txt)
    print('applied:', n)
    print('result:', repr(f.read_text(encoding='utf-8')))

# 行数保护测试（LLM 试图整文件重写）
txt2 = ('{"fixes": [{"file": "agents/intr/intr_driver.sv", "line": 1, "old": "line1", '
        '"new": "a\\nb\\nc\\nd\\ne\\nf\\ng\\nh\\ni\\nj"}]}')
with tempfile.TemporaryDirectory() as d:
    od = pathlib.Path(d)
    f = od / 'agents' / 'intr' / 'intr_driver.sv'
    f.parent.mkdir(parents=True)
    f.write_text('line1\nline2\nline3\n', encoding='utf-8')
    n = _apply_minimal_fixes(od, txt2)
    print('blocked rewrite applied:', n, '(expect 0)')

# 删除行测试（new 为空字符串）
txt3 = ('{"fixes": [{"file": "agents/intr/intr_driver.sv", "line": 2, '
        '"old": "  vif.cb.irq <= req.irq;", "new": ""}]}')
with tempfile.TemporaryDirectory() as d:
    od = pathlib.Path(d)
    f = od / 'agents' / 'intr' / 'intr_driver.sv'
    f.parent.mkdir(parents=True)
    f.write_text('line1\n  vif.cb.irq <= req.irq;\nline3\n', encoding='utf-8')
    n = _apply_minimal_fixes(od, txt3)
    print('delete-line applied:', n)
    print('result:', repr(f.read_text(encoding='utf-8')))

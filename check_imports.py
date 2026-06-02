# check_imports.py
import sys
print("Python路径:")
for p in sys.path:
    print(f"  {p}")

print("\n检查导入:")

tests = [
    ("config.settings", "Settings"),
    ("src.core.base", "BaseAgent"),
    ("src.core.registry", "AgentRegistry"),
    ("src.core.llm_factory", "LLMFactory"),
    ("src.tools.spec_tools", "SpecAnalysisTools"),
    ("src.tools.uvm_tools", "UVMTools"),
    ("src.tools.assertion_tools", "AssertionTools"),
    ("src.tools.debug_tools", "DebugTools"),
    ("src.tools.coverage_tools", "CoverageTools"),
]

for module, class_name in tests:
    try:
        exec(f"from {module} import {class_name}")
        print(f"✅ {module}.{class_name}")
    except Exception as e:
        print(f"❌ {module}.{class_name}: {e}")
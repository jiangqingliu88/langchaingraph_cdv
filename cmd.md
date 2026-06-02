# ============================================
# IC验证智能体系统 - 完整流程
# ============================================

# 1. 激活虚拟环境
cd C:\Users\liujiangqing\Desktop\cdv_advanced
.\venv\Scripts\activate

# 2. 设置 API Key（替换为你的真实 Key）
$env:LLM_API_KEY="sk-your-deepseek-key"

# 3. 初始化系统
ic-verify init

# 4. 查看所有 Agent 状态
ic-verify status

# 5. bypass 模式分析规格（不消耗 API）
ic-verify analyze spec_uart.txt --bypass

# 6. LLM 真实分析规格（消耗 API）
ic-verify analyze spec_uart.txt

# 7. bypass 模式运行完整验证流程（7阶段）
ic-verify verify spec_uart.txt --bypass

# 8. 快速检查（3阶段）
ic-verify verify spec_uart.txt -w quick_check --bypass

# 9. LLM 模式运行完整验证（消耗 API）
ic-verify verify spec_uart.txt

# 10. 查看历史记录
ic-verify history

# 11. 交互式 REPL 模式
ic-verify repl --bypass

# 12. 运行测试
pytest tests/ -v --tb=short
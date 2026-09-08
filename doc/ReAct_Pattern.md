1. 用户说：“帮我运行 test_uart，如果失败就修复代码，然后重新仿真。”
2. LLM 分析 → 需要先 run_simulation
3. 调用 run_simulation → 得到 log 路径
4. LLM 看到返回结果 → 需要 analyze_log
5. 调用 analyze_log → 得到错误信息
6. LLM 分析错误 → 需要 judge_pass_fail → 判断 fail
7. LLM 根据错误决定修改哪个文件 → 调用 modify_code
8. LLM 调用 compile_design 重新编译
9. LLM 再次调用 run_simulation 验证修复
10. 最终回复用户结果
# GOAL

# SUBAGENT TASK demo
agent_type: spec_analyst
parent: (none)

## OBJECTIVE
分析 npu_sched 接口

## SCOPE
- read: specs/, docs/, data/, cases/
- write: (none)

## CONSTRAINTS
- 工程只读分析
- 交付物只写本子 Agent 工作区
- 结论必须给出文件与行号
- 不得宣布验证通过

## DELIVERABLES
- findings.json

## ACCEPTANCE
- 每个结论可追溯到文件/行号
- 未知项显式列出

## PROJECT CONTEXT
# PROJECT CONTEXT

root: C:\Users\jiang\AppData\Local\Temp\tmpu1chv2me

## TASK MEMORY
# TASK MEMORY

## GOAL
分析 npu_sched 接口驱动

## COMPLETED
- G1: 分析 npu_sched 接口驱动

## CURRENT / NEXT

## DECISIONS

## BLOCKERS

## SUBAGENT RESULTS

## RULES
- 只做本 contract 范围内的任务，不扩大 scope。
- 结论必须有文件/行号或工具证据；不确定就写进 unresolved。
- 不要互相调用其它子 Agent；完成/阻塞后调用 finish。
- 如允许写，在 workspace 下写 result.json / findings.json 等交付物。
- COMPLETED 只表示执行结束，不代表主 Agent 已接受结论。

## ACCEPTANCE


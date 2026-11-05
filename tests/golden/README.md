# Golden 产物基线

用于架构重构的“行为没变”证明。只收**结构性产物**，不收波形/耗时。

## 基线

- 来源 run：`output_e2e_final4_jiang_20261104_044624`
- 模块：`npu_sched`
- 冻结日期：2026-11-04
- 冻结内容：

```text
coverage/case_ir.json
coverage/testpoints.yaml
coverage/gates.json
contract/contract_manifest.json
status/worklist.json
```

## 用法

```bash
python scripts/golden_diff.py tests/golden/architecture_baseline <new_run>
```

- 退出码 `0` = 一致；`1` = 有差异；`2` = 输入缺失。
- 对比前剔除易变字段：`generated_at` / `timestamp` / `run_id` / 绝对路径等
  （见 `scripts/golden_diff.py::VOLATILE_KEYS`）。
- `coverage/case_closure.json` / `coverage/coverage_holes.json` 若当前 run
  有、基线没有，会被记为 `baseline_missing` —— 这两个是新增产物，需要时
  先补进基线再比。

## 刷新基线

**只在确认行为变化是有意的时候刷新**，并在 PR 里写明原因：

```bash
cp <new_run>/coverage/case_ir.json tests/golden/architecture_baseline/coverage/
cp <new_run>/coverage/testpoints.yaml tests/golden/architecture_baseline/coverage/
cp <new_run>/coverage/gates.json tests/golden/architecture_baseline/coverage/
cp <new_run>/contract/contract_manifest.json tests/golden/architecture_baseline/contract/
cp <new_run>/status/worklist.json tests/golden/architecture_baseline/status/
```

## 不纳入比较

- `coverage/case_cov/**`（逐用例证据，体量大且含路径）
- `regression_run/**`（覆盖库 / 波形 / 日志）
- `signoff_evidence/**`（证据包逐文件 sha，随 run 变化）

这些由端到端 run 的 verdict / gates 摘要来验收，不逐字节比。

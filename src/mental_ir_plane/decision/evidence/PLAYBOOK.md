# coverage_tools skill

## 什么时候用我

- 需要把回归逐用例的 `cov/*/questa.db` 合并成**计划覆盖率**；
- 需要从 `ucdb` 出 HTML / 文本 / 覆盖率缺口；
- 需要按 `tp_id` / 覆盖仓做缺口归因；
- 需要打开 Visualizer 看覆盖率（先 `materialize_ucdb`）。

## 不要用我

- 只是想跑仿真 → 用 `execution/regression_tools`；
- 想改 RTL / UVM → 用 `generation/uvm_tools` 或 design executor；
- 想直接读 `questa.db` 的功能覆盖 → 先 materialize，否则功能覆盖会丢。

## 正确调用方式

```bash
# 合并回归覆盖率（签核口径）
python -m src.interfaces.cli.commands coverage merge --runs <run1,run2>

# HTML / 文本报告
python -m src.interfaces.cli.commands coverage report --run <run>

# 缺口
python -m src.interfaces.cli.commands coverage gaps --run <run>

# 排除登记
python -m src.interfaces.cli.commands coverage exclude --coverage <pct> --total <n>
```

Python API：

```python
from src.tools.checking.coverage_tools.cov_api import materialize_ucdb, build_coverage_report
from src.tools.common.lib.collect_real_coverage import merge_regression_coverage
```

## 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| `ucdb` 有文件但功能覆盖 0 | 编译没加 `+cover` / `-coverage` | 查 build 命令；`sim_modes` 开 `cov` |
| 覆盖率库叫 `(null).data` | `-testname` 漏传 | `sim_modes` 的 `cov+wave` 必须带 `-testname ${EMAN_TEST_NAME}` |
| 直接读 `questa.db` 没有 functional | coverstore 不能直读 | 先 `vcover merge "<store>:<test>"`（`materialize_ucdb`） |
| merge 报锁 | 上一次 vcover 留下 `._lock` | 清 `*.ucdb._lock` / `.questatmp` 后重试 |
| `cg_dut` 恒 0 | bind 探针没挂上 / 信号名漂 | 查 `env_cov_bins.yaml` 的 `dut_if` 与 `coverage/<if>.sv` |

## 日志里看什么

- `Saving coverage data in ...` → 正常落库
- `No coverage data collected` → 编译没开覆盖
- `TOTAL COVERGROUP COVERAGE: x%` → 功能覆盖口径
- `Design hierarchy mismatch` → 多 build 层次不同，功能覆盖可合并、代码覆盖按层次跳过

## 产物

| 文件 | 用途 |
|---|---|
| `sim/coverage/plan_merged.ucdb` | 计划覆盖率（签核门禁） |
| `coverage/plan_merge_manifest.json` | 合并输入清单 + 哈希 |
| `coverage/tp_matrix.json` | TP × bin 命中/缺口 |
| `coverage/seed_diversity.json` | 种子是否改变分布 |

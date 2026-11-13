# Architecture Guard 原则（Guard 2.0）

> 适用范围：`config/architecture_guard.py`、`config/architecture_budget.yaml`、
> `config/complexity_baseline.json`、`config/architecture_debt_history.jsonl`。
>
> 本文件定义**规则**，不定义实现细节。实现必须能被这张规则表逐条验证。

## 0. 一句话

**预算不是永久豁免，而是一笔只能变小的债务。**

Guard 的目标不是让模块永远保持现状，而是让系统在增加能力的同时，
持续降低结构性债务；任何新增或上调债务都必须留下人工审批痕迹。

## 1. 定位：架构治理，不是指标治理

Guard 是**小型、确定性、离线**的静态检查器：

- 只用 Python 标准库 + `yaml`；
- 不调用 LLM、不启动 Agent、不依赖运行时服务、不访问网络；
- 只读源码与预算文件；除显式 `--reduce-debt` / `--approve-debt` 外不写文件；
- 自身也受同一套预算约束（见 §8）。

Guard 不做的事：

- 不统计“复杂度趋势”看板；
- 不自动重构、不自动修复；
- 不把“通过检查”解释为“架构合规”——它只证明**预算内**；
- 不允许 LLM 修改预算、批准豁免或宣布合规。

## 2. 四个预算

| 预算 | 约束对象 | 硬失败阈值 | 债务载体 |
|---|---|---|---|
| Size | 单文件行数 | > 2000；已登记文件 > registered | `architecture_budget.yaml` |
| Complexity | 单函数圈复杂度 | > 20 且未登记；已登记函数增长 | `complexity_baseline.json` |
| Dependency | `src.*` 静态 import 方向 | 逆向依赖、未登记模块、新增环 | `_ALLOWED` + 依赖债务文件 |
| Debt | 四个维度的历史债务 | 债务未随重构下降 | `architecture_debt_history.jsonl` |

Debt 不是第五套规则，而是前三个预算的**变更纪律**。

## 3. 单向棘轮（核心原则）

### 3.1 允许 / 禁止

| 操作 | 是否允许 | 执行方式 |
|---|---|---|
| 新增复杂度债务（>20 未登记） | 禁止自动接受 | 人工 `--approve-debt`，必须给 reason + approver |
| 已登记复杂度增长 | 禁止 | 无 |
| 已登记复杂度下降 | 允许且必须记录 | `--reduce-debt` 下调 baseline |
| baseline 随下降自动降低 | 必须 | CI 检查 `debt_unrepaid` |
| baseline 无理由提高 | 禁止 | 仅 `--approve-debt` |
| 删除已解决债务 | 允许且必须 | `--reduce-debt` |
| 批量覆盖 baseline | 禁止 | 删除 `--update-baseline` |
| 文件缩小后 registered 不降 | 禁止 | CI 检查 `budget_not_tightened` |

### 3.2 大小预算的收紧判定

对每个 `watched` 文件：

```text
actual <= registered                      # 硬约束
registered - actual <= DEBT_SLACK         # 否则 budget_not_tightened
```

`DEBT_SLACK` 是防止行数自然波动导致噪声的容忍带（建议 5%，且不超过 50 行）。
超过容忍带说明已经发生实质性重构，必须在同一个 PR 里 `--reduce-debt`。

`--reduce-debt` 对文件只做一件事：`registered = min(registered, actual)`。
它**不能**新增条目、不能提高 registered、不能删除 reason/plan。

### 3.3 复杂度预算的收紧判定

对每个登记函数：

```text
actual <= baseline                        # 硬约束
actual <= threshold  →  必须从 baseline 删除
actual < baseline    →  必须下调到 actual
```

`--reduce-debt` 对所有函数执行：`baseline = min(baseline, actual)`；
`actual <= 20` 的条目直接删除。它不能新增条目，不能提高 baseline。

### 3.4 新增债务的唯一入口

```text
python -m config.architecture_guard --approve-debt \
    --reason "..." --approver "<human>" --key "<file::func 或 file>"
```

要求：

- `--reason`、`--approver` 必填，空字符串视为用法错误；
- 一次只允许一个 key（禁止批量批准）；
- 写入 `config/architecture_debt_history.jsonl`，字段见 §6；
- 只允许登记**当前真实值**，不能预登记未来空间；
- CI 不执行这个命令。

## 4. 复杂度计算规则

### 4.1 函数独立计算

每个函数独立计算 McCabe 近似值；**不把嵌套函数/lambda 的分支算进外层**。

```python
def _own_nodes(func):
    for child in ast.iter_child_nodes(func):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        yield from _own_nodes(child)
```

### 4.2 稳定标识

- 模块级函数：`<relpath>::<func>`
- 类方法：`<relpath>::<Class>.<func>`
- 嵌套函数单独登记为 `outer.inner`；其分支不计入外层。

标识迁移（从 `file::func` 到带类名）是一次性债务变更：同一 PR 内重写 baseline，
并在 history 里写一条 `identity_migration`，`old`/`new` 记录旧/新键。

### 4.3 阈值

- `> 20` 必须登记；
- 已登记值只能下降；
- 低于阈值后必须删除条目；
- 阈值本身是数据（可审批调整），不是代码常量。

## 5. 依赖预算规则

### 5.1 扫描范围

必须覆盖：

- 模块级 `import` / `from ... import`；
- 函数体内的延迟 import（**也算静态依赖**）；
- `importlib.import_module("src.x.y")` 的字符串常量；
- 多个目标 import（`import a, b`）逐个检查。

相对 import 先解析成绝对模块名再判定。

### 5.2 未登记即失败

- `src/` 下每个一级目录必须在 zone 表里有归属；
- 每个 `src.*` import 目标必须解析到已知 zone；
- 否则 `unregistered_zone` / `unknown_import_target` 硬失败。

### 5.3 环

- 模块级 import 图做 SCC；新增环硬失败（**尚未实现，下一轮**）；
- 历史环登记在依赖债务文件里，只能缩小、不能新增。

### 5.4 Engine 的允许集合

目标方向：

```text
engine → core, tools, ir, runtime, engine/executors
```

**不允许**长期依赖 `l2/l3/l4/l5/workspace`。当前 `engine/{front,ops,coverage,audit}`
模块级依赖 `l2_orchestration.executors.base`，这是 `ExecutorBase` 尚未迁到
`engine/executors` 的过渡债务；必须登记在依赖债务文件里，并随迁移清零。
在清零之前，allowlist 中的 `l2` 不是默许，而是已登记债务。

### 5.5 动态 import 的登记

`importlib.import_module` / `__import__` 的**字符串常量**与静态 import
同口径检查方向；字符串拼接的路径无法静态解析，属于已知盲区。

## 6. 债务变更历史

`config/architecture_debt_history.jsonl`，每行一个 JSON 对象：

```json
{
  "ts": "2026-11-13T02:00:00Z",
  "kind": "complexity|size|dependency|identity_migration",
  "key": "src/engine/ops/main.py::OpsExecutor.execute_task",
  "old": 35,
  "new": 28,
  "reason": "抽出 _incremental_filter",
  "approver": "human",
  "commit": "可选；由 CI 回填"
}
```

规则：

- `--reduce-debt` 只能产生 `new <= old` 或删除；
- `--approve-debt` 才能产生 `new > old`；
- 不允许手写历史条目（除 `identity_migration` 的一次性迁移）；
- 历史只追加，不改写。

## 7. 命令与退出码

```text
python -m config.architecture_guard              # 检查；有违规 exit 1
python -m config.architecture_guard --json       # 机器读
python -m config.architecture_guard --reduce-debt  # 只降不升；写 history
python -m config.architecture_guard --approve-debt --reason ... --approver ...
```

| 退出码 | 含义 |
|---|---|
| 0 | 预算内，且债务已收紧 |
| 1 | 存在违规（含 `debt_unrepaid`） |
| 2 | 配置/用法错误（预算文件损坏、缺 reason/approver 等） |

JSON 输出必须包含：`ok`、`line_issues`、`complexity_issues`、`import_issues`、
`debt_issues`、`budget`、`tool_version`。issue 必须有稳定的 `type` 字段。

## 8. Guard 自身的预算

治理系统不能成为新的复杂度来源：

| 项 | 上限 |
|---|---|
| `config/architecture_guard.py` 行数 | 600 |
| 单函数复杂度 | 20（无豁免） |
| 运行时依赖 | 标准库 + `yaml` |
| 网络 / LLM / Agent / Runtime 服务 | 0 |
| 写入操作 | 仅 `--reduce-debt` / `--approve-debt` 和对应 history |

Guard 的实现必须用同一套 `line_violations` / `complexity_violations` 检查自己；
不允许为 Guard 自己开 `watched` 豁免。

## 9. 当前实现与目标的差距

| 问题 | 当前 | Guard 2.0 |
|---|---|---|
| A. 文件缩小不收紧 | 只查 `actual > registered` | 增加 `budget_not_tightened` |
| B. baseline 不偿还 | 只查增长 | 低于阈值必须删除；下降必须下调 |
| C. `--update-baseline` 权限过大 | 整表重写 | 删除；改为 `--reduce-debt` + `--approve-debt` |
| D. 嵌套函数污染外层复杂度 | `ast.walk` 全树 | 排除嵌套函数/lambda |
| E. 函数标识不含类名 | `file::func` | `file::Class.func` |
| F. 只扫模块级 import | 延迟 import 漏检 | 全部 import + `importlib` 字符串 |
| G. 未登记目录不报错 | 静默跳过 | `unregistered_zone` 失败 |
| H. `_iter_py(root)` 不生效 | 固定全局 `ROOT` | 所有扫描使用传入 root |
| I. Engine allowlist 过宽 | 可依赖 l2-l5 | 目标只允许 core/tools/ir/runtime，过渡依赖登记为债务 |

## 10. 变更本文件的程序

1. 新增/删除预算维度：必须写 ADR，人工审批；
2. 调整阈值：走 `--approve-debt` 同类流程，并在 history 记录；
3. 放宽依赖方向：必须同时给出迁移计划与债务登记；
4. 任何豁免都不能是永久的：必须带 `reason`、`plan`、`expires`（可选）；
5. Guard 不接受 LLM 生成的预算变更。

## 11. 定义完成（对一次重构）

- 没有新增未登记债务；
- 已偿还的债务在同一 PR 内下调或删除；
- 依赖方向未新增逆向边；
- `python -m config.architecture_guard` 通过；
- history 里有本次债务变化的记录。

## 12. 实现状态（2026-11-13）

已落地：`--reduce-debt` / `--approve-debt`、history、单向收紧、嵌套函数独立
复杂度、类限定身份、延迟/动态 import 检查、未归类模块检查、`root` 参数修复。

回归测试：`tests/test_architecture_guard.py`（17 条）。

尚未实现：import 环检测、字符串拼接动态 import、依赖债务文件的独立记账。

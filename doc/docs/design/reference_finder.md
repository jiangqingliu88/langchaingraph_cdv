# Reference Finder —— 逐版本溯源定位

> 范围：只谈「哪个提交引入了这个失败」这一件事的机制与落点。
> 回归框架本身的契约（`run_cmd` / `variables` / `EMAN_*`）见
> `src/tools/regression_tools/regression_framework/` 各模块 docstring。
> 本文补的是**跨模块的那条线**——三个文件各自的 docstring 都只讲了自己那一段。
>
> 实现落点：
> - 机制：`src/layers/l1_infrastructure/reference_finder.py`（二分 + worktree + 证据）
> - 地基：`src/layers/l1_infrastructure/env_snapshot.py`（环境快照）
> - 缓存：`src/layers/l4_memory/reference_finder_cache.py`
> - 框架面：`regression_framework/core/config.py`、`generators/shell.py`、`regression.py`

---

## 0. 一句话结论

**它就是二分查找，只不过「比较两个元素」的代价是跑一次完整回归。**

```
经典二分           在有序数组里找「第一个 ≥ x 的元素」
Reference Finder   在提交序列里找「第一个失败的提交」
    比较数组元素   ←→   跑一次该版本的回归，得到 pass / fail / inconclusive
```

这个类比不是修辞，它解释了全部设计取舍：**因为「比较」贵（一次编译+仿真，分钟级），
所以用二分（O(log n)）而不是 ExecMan 手册里画的线性回溯（O(n)）**；**因为「比较」有
第三种结果（编译不过、缺 license），所以判定是三态而不是布尔**；**因为「比较」必须
可信，所以每一层都在回答「凭什么说这次比较是有效的」**。

---

## 1. 它回答什么问题

某个用例在最新版本失败了。问：**它是从哪个提交开始坏的？**

即：在 `good..bad` 区间里找出**第一个失败的提交**。它前面那个提交是最后一个好版本，
坏的引入者就是它。

---

## 2. 调用链

```
python -m src.tools.regression_tools.regression --config X.yaml --reference-finder
│
└─ regression.py : _run_reference_finder()            ← 框架的配置面
     │  ConfigBuilder(X).load_reference_finder()
     │      只读 `reference_finder:` 块，**不做完整渲染**
     │      （run_cmd / ref_run_cmd 里引用的 RF_* 只在逐版本运行时才存在，
     │        这里完整渲染会误报「变量引用未定义」）
     │
     └─ reference_finder.py : ReferenceFinder.find_first_bad(good, bad, paths)
          │
          ├─ list_revisions()      git log --format=%H --reverse good..bad
          │                        ↑ **正序**：最早的在最前。二分的语义是
          │                          「找第一个失败的」，比的是时间先后
          │
          ├─ run_at_revision(good)   前置校验：结论必须是 pass
          ├─ run_at_revision(bad)    前置校验：结论必须是 fail
          │
          └─ while lo < hi:        二分收敛
               run_at_revision(revs[mid])
                 fail          → hi = mid      （往早缩）
                 pass          → lo = mid + 1
                 inconclusive  → hi = mid，**并记下缺口、降级可靠性**
```

---

## 3. `run_at_revision(rev)` —— 整个功能的原子动作

一次版本检查做四件事：

| 步骤 | 动作 | 为什么这么做 |
|---|---|---|
| ① 解析 ref | `git rev-parse <ref>` → 完整 SHA | 用户可能传 `HEAD` / tag / 分支名。不解开的话同一个提交换个名字就有两份产物，**缓存键也不一致**（端点按 `HEAD` 缓存、中点按 SHA 缓存，白跑两次） |
| ② 隔离代码 | `git worktree add --detach <tmp> <rev>` | **绝不用 `git checkout`** —— 那会把用户正在用的工作区切走，中途一中断就留下半切状态的树 |
| ③ 拍环境快照 | `env_snapshot.capture(worktree, config)` | 记下这个版本是在什么环境下跑的。少了它，结论换台机器就不可复核 |
| ④ 跑回归 | `InfrastructureManager(<该版本的 run_root>).run_regression(cfg, tests=<用例>, reference_mode=True, overrides=[...])` | 复用现成的回归框架，**框架的执行逻辑一行没改** |
| ⑤ 拆工作区 | `git worktree remove --force` | 跑完即删，不留残留（`--keep-worktrees` 可保留排查） |

隔离发生在**三个层面**，缺一不可：

- **代码层**：worktree 独立目录、独立 HEAD
- **产物层**：每个版本一个 `output_root`（回归框架本来就是 per-output_root 的，
  所以这块不用改框架）
- **变量层**：`overrides` 把 `RF_WORKTREE` / `RF_RUN_DIR` / `WORK` 指向该版本自己的目录

---

## 4. 框架面：这件事是框架自己的能力

ExecMan 里 Reference Finder 是回归框架的特性，配置就写在 EMC 里。这里对齐同一套契约——
**框架自己知道「我现在跑的是一个历史版本」**，而不是靠外面猜。

### 4.1 配置块

```yaml
reference_finder:
  good: "v1.0"          # 已知通过的提交/ref（必填）
  bad: HEAD             # 已知失败的提交/ref（默认 HEAD）
  test: smoke_basic     # 要复现的用例名/正则（必填）
  paths: ["rtl/"]       # 可选：只考虑这些路径下的提交
  mode: local
  work_root: ./reference_finder_work
```

区间与用例**默认从这里读**，命令行 flag 只是覆盖。这样一次排查的参数能跟配置一起进版本
控制，而不是散在一次性的命令行里。

### 4.2 `ref_run_cmd`：历史版本要用它该用的方式跑

```yaml
builds:
  - name: b1
    run_cmd:     '...针对当前树...'      # 普通回归用
    ref_run_cmd: '...针对历史版本...'    # 溯源时用
tests:
  - name: t_behavior
    build: b1
    run_cmd:     '...针对当前树...'
    ref_run_cmd: '...针对历史版本...'
```

选择逻辑在 `ShellGenerator._pick_run_cmd()`：

```
reference_mode 且配置里有 ref_run_cmd  →  ref_run_cmd
否则                                   →  run_cmd
```

**为什么必须两条命令？** 老版本的编译方式、文件布局常和新版本不同。沿用 `run_cmd`
会编译不过 → 于是「版本差异」被误读成「bug 引入点」。这是溯源结论最容易被污染的地方。

### 4.3 命令选择矩阵（ExecMan 的 Alternative Fields）

两个**正交**的维度决定用哪条命令：

| | 普通版本 | 历史/参考版本 |
|---|---|---|
| **normal** | `run_cmd` | `ref_run_cmd` |
| **debug** | `debug_run_cmd` | `ref_debug_run_cmd` |

实现是 `ShellGenerator._pick_run_cmd()`，**逐级回退**：精确命中的没有，就退到同一
维度下更通用的那条，最后才用 `run_cmd`；全缺则返回空串、回落到 `settings.simulators`
模板。

- **参考版本**为什么要换命令：见上一节。
- **debug 模式**为什么要换命令：调试跑法要开波形、放大日志，比普通跑慢得多，
  只在要给调试分析提供素材时才用。

debug 维度由 `--debug-run`（框架 CLI）/ `run_regression(debug_mode=)` 打开。

> **一条踩过的坑**：`_pick_run_cmd` 是矩阵化的，但**调用点的条件**一开始只判断了
> `reference_mode`。结果「只写了 `debug_run_cmd`、没写 `run_cmd`」的 build 会掉回
> 模板生成一条空命令。修法是让调用点只问「挑得出命令吗」，不再自己重算一遍条件 ——
> 判断逻辑只留一处。

两个 schema 细节：

- `run_cmd` / `ref_run_cmd` / `debug_run_cmd` / `ref_debug_run_cmd` **都延迟渲染**
  （只在真要用的那次、用 per-task 上下文渲染）。否则一份带了 `ref_run_cmd`
  （内含只在溯源时注入的 `RF_WORKTREE`）的配置，**连普通回归都跑不了**。
- 四个字段都在 schema 里、都有真实消费者。加字段时请确认这一点 ——
  「schema 收了但没人读」正是本项目反复出现的坏模式。

### 4.3 CLI

```bash
python -m src.tools.regression_tools.regression \
    --config regression.yaml --reference-finder --repo-path .
```

| 参数 | 说明 |
|---|---|
| `--reference-finder` | 进入溯源模式 |
| `--ref-good` / `--ref-bad` / `--ref-test` | 覆盖配置里的区间与用例 |
| `--ref-paths` | 逗号分隔，只看这些路径下的提交 |
| `--ref-work-root` | 工作目录，默认 `<repo>/reference_finder_work` |
| `--ref-no-cache` | 忽略缓存，强制重跑 |

---

## 5. 三态判定，不是布尔

```
verdict ∈ { pass, fail, inconclusive }
```

`inconclusive` 覆盖：编译不过、缺 license、超时、用例没被选中（`total == 0`）、
各任务全 unknown。

**为什么单独一态**：它们既不能说「这个版本是好的」（会把 bug 引入点推后），
也不能说「这个版本已经坏了」（会推向更早）。静默归入任何一边，都会给出
**看起来确定、实际错误**的结论。

触发 `inconclusive` 时的行为：

- `reliable: False`、`confidence: degraded`
- `inconclusive_revisions` 点名列出，附说明
- caveat 写明「定位结果可能偏早，请复核下列版本」

二分遇到它时**往失败侧缩**（继续收敛），但把缺口记下来 —— 不能假装没发生。

---

## 6. 两道防错

### 6.1 端点前置校验

`good` 必须 pass、`bad` 必须 fail，否则**直接报错不做二分**：

```
reason: "端点不满足「good 通过 / bad 失败」，二分无意义。
         常见原因：环境不一致、用例选择没命中、或区间选错了。"
```

拿一个错误前提去二分，只会得到一条精确但无意义的结论。

> **这道校验真的拦住过一次错误。** 早期实现里 `RF_WORKTREE` 注入的是 Windows
> 反斜杠路径，bash 把反斜杠当转义符吃掉 → **好版本被误判成 fail**。没有这道校验的话，
> 二分照样跑完、照样给出一个 culprit —— 一个安静的错误答案。

### 6.2 环境一致性比对

各版本的 snapshot `digest` 不一致时，标记 `reliable: False` 并列出具体差异字段：

```
env_mismatches: [{revision: ..., differences: ["eda_version_guess: ... → ..."]}]
caveat: "各版本的环境快照不一致 —— 结果差异不能只归因于代码"
```

---

### 6.3 边界 Debug Run

定位到之后，可选地在**两个边界版本**（`last_good` 与 `culprit`）上各跑一次 Debug Run，
产出可供对比的素材（波形、详细日志），落在各自的 run 目录下。

```
--ref-debug-at-boundary          # 或配置里 reference_finder.debug_at_boundary: true
```

用的是 `ref_debug_run_cmd`（没写就按矩阵回退）。**只产出素材，不做差异分析** ——
ExecMan 的 Debug Engine 那层没实现。跑失败不抛：边界素材是附加价值，拿不到不该让
已经得到的定位结论作废。

---

## 7. 与 `git bisect` 的区别

`git bisect` 只能跑一条命令（比如 `make test`）。它不知道你的回归框架、不知道
`ref_run_cmd`、不知道环境快照，也不会把结论写成可审计的证据。

这里围绕「**这个结论凭什么可信**」加的每一层：

| 加的东西 | 回答的问题 |
|---|---|
| worktree 隔离 | 结论是在干净的树上得到的吗 |
| 环境快照 + digest 比对 | 各版本是在同一环境下跑的吗 |
| 三态 + 端点校验 | 结论有没有被一次编译失败污染 |
| `ref_run_cmd` | 历史版本是用它该用的方式跑的吗 |
| 缓存键含 `env_digest` | 这个结论在新环境下还算数吗 |
| `result.json` + `summary.md` | 换台机器还能复核吗 |

最后一行是重点：**项目宣称的差异化是「可复现 · 可审计 · 可治理」，而不是「能不能溯源」**
（`git bisect` 早就能溯源）。所以这里真正在做的不是溯源本身，而是**让溯源结论可审计**。

---

## 8. 落盘产物与目录布局

```
<work_root>/
├── worktrees/<rev12>/              # 临时检出，跑完删（--keep-worktrees 保留）
├── runs/<rev12>/                   # 该版本的 output_root
│   └── regression_run/             # 框架生成的 build_*/test_* + 报告
├── reference_finder_result.json    # 机器可读：结论 + 全部版本结果 + 环境快照
└── reference_finder_summary.md     # 人可读（签核场景直接贴给人看）
```

缓存：`.signoffai/reference_finder_cache.db`，键为
`(repo, rev, test_pattern, env_digest)`。

> **缓存键为什么带 `env_digest`**：结论不只取决于代码，还取决于跑它的环境。
> 同一个提交在换过 EDA / UVM 版本之后重新判定，结论可能不同。不带环境摘要的话，
> 缓存会用一个旧环境的结论回答新环境的问题，**而且看起来毫无破绽**。
>
> `inconclusive` 也进缓存 —— 它是「这次没测出来」这一事实本身，下次可据此决定
> 要不要重试，而不是误当成从没跑过。

---

## 9. 使用前提（不做这些，结论不可信）

**1. 配置在版本之间必须保持同一份。** 这是「同一份配置、不同代码」的语义要求。
所以配置里不能写死路径 —— 用逐版本注入的变量引用：

| 变量 | 含义 |
|---|---|
| `RF_WORKTREE` | 该版本代码的检出目录 |
| `RF_RUN_DIR` | 该版本的回归输出目录 |
| `WORK` | 该版本的编译工作目录 |

**2. 你真实的 `regression.yaml` 需要配合改造**：把绝对路径（`WORK`、filelist）改成
引用上面的变量，并在 tests 里写 `ref_run_cmd`。否则所有版本共用同一份产物，
**「换版本」名存实亡**。

**3. 环境钉死目前只做到「记录 + 比对」，没做到「强制」。** 各版本环境不一致会被
标记为不可信，但真正让它一致（锁 EDA 版本、清掉散落在十几处的
`f:/questasim64_2024.1` / `win64` / `uvm-1.2` / `gcc-8.1.0` 硬编码）是另一件事，
**尚未完成**。

---

## 10. 验证方式（可重跑）

用一个**已知答案**的合成仓库验证，不需要真实 EDA：

```python
# 1. 造仓库：5 个提交，rev3 起把 value.txt 改成 bad
#    ⚠ 每个提交必须有不同的内容，否则 git 认为「无改动」会跳过提交
for i in range(1, 6):
    open('value.txt','w').write('good' if i < 3 else 'bad')
    open('marker.txt','w').write(f'rev{i}')      # 保证每版都有改动
    git('add','-A'); git('commit','-qm', f'rev{i}')

# 2. 配置里 tests[].ref_run_cmd 用 {{ RF_WORKTREE }} 读该版本的值
# 3. 跑
python -m src.tools.regression_tools.regression \
    --config regression.yaml --reference-finder --repo-path <repo>
```

| 验证项 | 期望 |
|---|---|
| 定位结果 | culprit = rev3，last_good = rev2，confidence = high |
| 二分次数 | 4 次（端点 + 2 步），不是线性的 5 次 |
| 工作区未污染 | `git status --porcelain` 为空、HEAD 未动、`git worktree list` 只剩主树 |
| 普通回归不受影响 | 生成的 `sim.sh` 用 `run_cmd`，`ref_run_cmd` 出现 0 次 |
| 溯源确实换命令 | 各版本 runner 里都是 `ref_run_cmd` |
| inconclusive | 造一个「用例选择不到」的版本 → `reliable: False` + 点名列出，**不被当成 pass/fail** |
| 缓存 | 第二遍 4/4 命中，结论一致，2.3s → 0.2s |

### 10.1 真实 EDA 下的验证（更强的一种）

上面那套用 `mode=mock`，只验机制。**用真实 QuestaSim 再跑一遍**才是最终证据：
配置里 `ref_run_cmd` 真的调 `vlog` + `vsim`，每个版本各编译仿真一次。

```yaml
variables: {}
builds:
  - name: b1
    # WORK 由 ReferenceFinder 逐版本注入（= <run_root>/build/work）
    run_cmd: 'mkdir -p {{ WORK }} && vlog -work {{ WORK }} -sv {{ RF_WORKTREE }}/dut.sv {{ RF_WORKTREE }}/tb.sv'
tests:
  - name: t_func
    build: b1
    ref_run_cmd: 'vsim -c -work {{ WORK }} tb -l {{ RF_RUN_DIR }}/sim.log -do "run -all; quit -f" ; ! grep -q MISMATCH {{ RF_RUN_DIR }}/sim.log'
```

`dut.sv` 在第三个提交把 `a + b` 改成 `a - b`，TB 里比对期望值。

实测结果（4 个版本，11 秒）：

| 版本 | 真实 vsim 输出 |
|---|---|
| rev1 / rev2（好） | `# OK y=13` |
| rev3 / rev4 / rev5（坏） | `# MISMATCH: expected 13 got 7` |

定位结果 `culprit = rev3`、`last_good = rev2`、`confidence = high`。
各版本的 `build/work/` 下是真的 QuestaSim 编译库（`_info` / `_lib.qdb`），
`sim.log` 里是 `vsim -c -work ... -do "run -all; quit -f"` 的原始输出 ——
即**逐版本真的编译仿真了**，不是走流程。

---

## 11. 已知限制

| 限制 | 说明 |
|---|---|
| **每版本一次完整编译 + 仿真** | 二分把 n 降到 log n，但**依然不廉价**。实测：一个最小 SV 设计（vlog+vsim ≈ 4s/版本）跑 4 个版本共 11s；UVM 级的环境每个版本是分钟级 |
| **不做 LLM 根因分析（Debug Engine）** | ExecMan 的 Debug Engine 会对比 reference 与当前版本的调试结果给根因。这里 `--ref-debug-at-boundary` 只在边界两版本上**产出素材**（波形/详细日志），**不做差异分析** —— 拿到素材之后仍要人看 |
| **`debug_run_cmd` 的实际调试效果取决于配置** | 框架只负责「选对命令」，波形/日志本身由配置里的命令决定 |
| **`paths` 过滤是提交级的** | 用 `git log -- paths` 过滤候选提交，不分析 diff 内容 |
| **缓存无失效策略** | 只按 `env_digest` + rev 区分，没有 TTL；`clear(repo)` 手动清 |

---

## 12. 与既有能力的关系

**`bisect_failed_tests`（debug_tools）和本文不是一回事**，别混：

| | `bisect_failed_tests` | Reference Finder |
|---|---|---|
| 二分什么 | **失败用例集合** | **提交历史** |
| 碰 git 吗 | 不碰（`git`/`commit`/`change-list` 出现 0 次） | 就是它的核心 |
| 回答 | 「先跑哪一半用例」 | 「哪个提交引入的」 |
| 层次 | agent 内部的一个工具 | 回归框架的能力 |

（前者原名 `bisect_test`，在 EDA 语境里极易被读成版本溯源，已改名以消除误判。）

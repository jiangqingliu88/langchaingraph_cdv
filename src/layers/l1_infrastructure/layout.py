"""运行目录布局 —— **这个契约只能有一处定义**。

## 为什么要这个文件

`<run>/regression_run/...` 这套布局原先**散在读写两边各自手里**：

  · 写的：`infrastructure.py` 拼 `self.output_root / "regression_run"`
  · 读的：`flow_tools/api.py` 拼 `root / "regression_run"` 后 glob `build_*`

两边**谁也不知道对方**。于是分级回归一改成"每级一个子目录"
（`regression_run/<stage>/build_*/test_*/`），写的那边改对了、读的那边没跟上 ——
**GUI 的「回归状态」整页空白**（扫描在 `regression_run/` 下直接找 `build_*`，
一个都匹配不到），波形/覆盖率列也全空。

这不是孤例。同一个会话里同一类病犯了五次：

```
schema 加字段      生成器改了、schema 没改     → 整轮校验失败
_stream_run 初始化  一处加了、另一处没加        → 98 个测试崩
--rtl 拷贝         补了 _stream_run 漏了 CLI   → --rtl 被整个忽略
regression_run 布局 写的改了、读的没改          → GUI 整页空白
改种子             实现改了、测试断言没改       → 用例红
```

**根因是同一个：契约没有单点定义。** 这份文件就是把这条契约收成一处，
让"改一处漏一处"从**靠运气发现**变成**结构上不可能**。

## 纪律

**读写的两边都必须走这里的函数，不许各自拼字符串。** 谁再写一句
`Path(root) / "regression_run"`，就是又开了一份真相。

## 布局（两种并存，读的必须都认）

```
平的   <run>/regression_run/build_*/test_*/          老布局，仍在用
分级的 <run>/regression_run/<stage>/build_*/test_*/  分级回归：每级各占一个子目录
```

分级那一层是**故意**加的：`run_regression` 每调一次会 `rmtree` 掉整个
`regression_run`，五级跑完盘上只剩最后一级（p0/p1/p2 的日志、波形、覆盖率
全被冲掉 —— 实测：28 个用例目录里只有 3 个有 `sim.log`）。
每级一个子目录，五级的证据才都留得住。

## 入参的容忍（**判据收在这一处**，别让调用点各判一次）

读端的入参名义上是"运行目录"，但历史上实际传进来过三种东西：

    <run>/                        运行根            —— 名义契约
    <run>/regression_run/         回归目录**本身**   —— 测试夹具就传这个
    <run>/                        且 build_* 直接挂在它下面（没有 regression_run 这层）

**"两种都认"是读端的义务**，所以判据在这里一次性判掉；调用方只管调
`latest_root()` / `test_dirs()`，不用知道传进来的是哪种。这条容忍是
**实测补上的**：收口第一版只认运行根，`run_regression_status` 立刻扫到 0 行、
17 个 workbench 用例变红（夹具传的正是 `<tmp>/regression_run`）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

#: 回归运行目录名（相对 run 根）。**唯一一处**。
REGRESSION_RUN = "regression_run"

#: 用例目录的前缀：`build_*` 下面是 `test_*`。
BUILD_PREFIX = "build_"
TEST_PREFIX = "test_"

#: 分级回归的级名 —— 与 `InfrastructureManager.REGRESSION_STAGES` 同名。
#: 这里只作**识别用**（判断某个子目录是不是"一级"），不是分级定义的真相源：
#: 分级定义在 `infrastructure.py` 的 `REGRESSION_STAGES`，一处。
#: `tests/test_layout_contract.py` 钉住两者的从属关系，改一边漏一边会红。
STAGE_DIRS = ("loopback", "p0", "p1", "p2", "p3")


def regression_root(run_root: str | Path) -> Path:
    """`<run>/regression_run` —— **写端**的落点（`infrastructure.py` 用）。

    写端只有一个落点，所以这里不做过多的猜测：给运行根，还回归目录。
    """
    return Path(run_root) / REGRESSION_RUN


def casemodel_path(run_root: str | Path) -> Path:
    """`<run>/inputs/casemodel.yaml` —— 用例属性模型的落点，**写和读都走这里**。

    ## 为什么**不能**放在 `inputs/yaml/uvm/` 下（踩过）

    那个目录是 `tool_find_spec_yaml` 的**私有产物目录**，它每次跑都会
    **清空 `*.yaml`**（`tool_find_spec_yaml/main.py` 里那句 "清理旧 YAML"）。
    而 casemodel 是 **front 在更早的阶段**写出来的：

        ① front  写 `<run>/inputs/yaml/uvm/casemodel.yaml`（20:08:13，桥也据此落库）
        ② find_spec_yaml 跑起来，**第一步就把该目录清空**
        ③ 同一趟的第 8 步 `_casemodel_test_lines` 再去读 —— **文件刚被自己删掉**
        ④ → 注入不了 `environment.tests` → 生成不出 `{env}_attr_test.sv`
        ⑤ → 回归里每个属性取值跑的都是同一个 test 类，取值只进了目录名

    删它和读它的是**同一个工具、同一趟运行**。`inputs/` 谁都不会整个清空，
    放这儿才活得下来 —— 而且库里 4 个读端（verify / quality_guard / workbench
    / `_find_case_model`）本来就在这儿找，收过来还顺带把"两派路径"合成一派。
    """
    return Path(run_root) / "inputs" / "casemodel.yaml"


def find_case_model(spec: Any, run_root: str | Path) -> Optional[Path]:
    """这次运行**该用哪份 case 模型** —— 判据只有这一处。

    四个来源，按「离这次运行由近到远」：

      1. `spec["case_model"]`     —— 设计阶段若产出了就把路径写在这儿；
      2. `<specs>/<模块>/casemodel.yaml` —— **和 spec 放在一起的手写模型**。
         这是人写模型最自然的位置（模型是"这份规格该测什么"的产物），
         所以它的优先级高于项目级默认值；
      3. `config/casemodel/<模块>.yaml`  —— 项目级常备的那一份；
      4. `<run>/inputs/casemodel.yaml`   —— **front 的草稿**（自动生成的那份）。

    ## 为什么收成一处

    这条链上原来有**两个读法**：verify 分解测试点走 `_find_case_model`
    （认识 `config/` 与 `specs/`），而覆盖率侧生成覆盖点、写 DUT 探针直接读
    `casemodel_path()`（**只认 `inputs/`**）。于是同一个 run 里：

        verify 拿 `config/casemodel/npu_sched.yaml` 分解测试点
        coverage 拿 front 的草稿 `inputs/casemodel.yaml` 生成覆盖点

    两份模型的覆盖点不一样，而**两边都觉得自己对**。收成一处之后，"用哪份"
    只有一个答案。front 的草稿仍然会被写出来（它是链路自己产的那份），
    只是**人写了模型时它不再是首选**。

    找不到返回 `None` —— **不编一份出来**（"这件事没做"要在日志里说没做）。
    """
    candidates: list[Path] = []
    if isinstance(spec, dict):
        declared = spec.get("case_model")
        if isinstance(declared, str) and declared.strip():
            candidates.append(Path(declared))
        module = str(spec.get("design_name") or "").strip()
        if module:
            candidates.append(Path("specs") / module / "casemodel.yaml")
            candidates.append(Path("config") / "casemodel" / f"{module}.yaml")
    candidates.append(casemodel_path(run_root))

    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def latest_root(run_root: str | Path) -> Optional[Path]:
    """有产物的**那一层**的路径（读 `report.json` / `state_file` 用）。

    `run_regression_status` / `compare_runs` 要的正是这**一个** root：它们从
    这里读 `report.json`、再在这一层下数用例。分级布局下取**最后一级**
    （盘上最新最完整的那份）；平布局就是 `regression_run` 自己。
    取不到返回 `None` —— 调用方据此报"没有回归产物"，**别自己再拼一遍路径**。
    """
    roots = _candidate_roots(run_root)
    return roots[-1] if roots else None


def stage_roots(run_root: str | Path) -> List[Path]:
    """每一级的 root 路径，**按旧到新**（平布局就是 `regression_run` 自己那一个）。

    `latest_root` 的全量版：它取末尾一个（读 `report.json` 用），这里要**全要**
    （每一级各有一份 `report.json`，合并起来才是这次回归的全貌）。
    与 `latest_root` / `test_dirs` 共用同一套判据（`_candidate_roots`），
    不另写一份"哪几层算一级"。
    """
    return _candidate_roots(run_root)


def test_dirs(run_root: str | Path) -> List[Path]:
    """run 根下**所有**用例目录（`test_*`），两种布局都认。

    与 `latest_root` 的区别是**看全**：分级布局下会扫到**每一级**的用例 ——
    这些都是证据，GUI 要能一并看到，不是只看最后一级。老布局下就是
    `build_*/test_*`。
    """
    out: List[Path] = []
    for r in _candidate_roots(run_root):
        for b in sorted(r.glob(f"{BUILD_PREFIX}*")):
            if b.is_dir():
                out.extend(p for p in sorted(b.glob(f"{TEST_PREFIX}*")) if p.is_dir())
    return out


def _candidate_roots(run_root: str | Path) -> List[Path]:
    """哪几层有 `build_*`，**按旧到新排序**（末尾的即"最新那一份"）。

    返回列表而不是单个路径 —— 因为读的一方有两种需求：`latest_root` 取末尾一个，
    `test_dirs` 全要。两种需求共用**同一套判据**，才不会两边判得不一样。
    """
    p = Path(run_root)
    # 传进来的可能就是回归目录本身 —— 剥一层，剩下的判断就只有一套
    p = p.parent if p.name == REGRESSION_RUN else p
    rr = p / REGRESSION_RUN
    if any(rr.glob(f"{BUILD_PREFIX}*")):
        return [rr]                                   # 平布局
    stages = [d for d in sorted(rr.glob("*/"))
              if d.is_dir() and any(d.glob(f"{BUILD_PREFIX}*"))]
    if stages:
        return stages                                 # 分级：每级一个，末尾最新
    if any(p.glob(f"{BUILD_PREFIX}*")):
        return [p]                                    # build_* 直接在 run 根下
    return []

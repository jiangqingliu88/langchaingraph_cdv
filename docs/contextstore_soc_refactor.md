# ContextStore SoC 层级重构设计

> 日期：2026-08-09  
> 现状：平铺单 IP 的 `{key: value}` 字典  
> 目标：层级化 `{scope.key: value}`，支持 SoC → IP → SubBlock 多级上下文

---

## 1. 现状诊断

### 1.1 当前 ContextStore

```python
# src/core/context.py — 当前只有 8 个全局 key
ctx.put("spec",        {...})   # 哪个 IP 的 spec？
ctx.put("design_arch", {...})   # 哪个 IP 的设计？
ctx.put("model",       {...})
ctx.put("env",         {...})   # 哪个 IP 的 UVM env？
ctx.put("tests",       {...})   # 哪个 IP 的测试？
ctx.put("regression",  {...})   # 哪个 IP 的回归？
ctx.put("coverage",    {...})   # 哪个 IP 的覆盖率？
ctx.put("debug",       {...})
```

### 1.2 问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | **单 IP 假设** — key 隐含只有一个 DUT | 多 IP SoC 无法区分 uart.spec 和 dma.spec |
| 2 | **无层级** — chip/it/bt/ut 数据混在一起 | chip 级 coverage 和 IP 级 coverage 冲突覆盖 |
| 3 | **拓扑写死** — `_CONSUMES_TOPOLOGY` 是硬编码的 8 个 key | 新增 IP 需要改代码 |
| 4 | **无隔离** — 所有 Agent 共享一个平铺命名空间 | uart 的 env 可能被 dma 的 Agent 误读 |
| 5 | **无聚合** — 无法"汇总所有 IP 的覆盖率" | signoff 报告需要手动收集各 IP 数据 |
| 6 | **prune 粗粒度** — 按 agent role 清理，不是按 IP | 一个 IP 跑完不能及时释放内存 |

---

## 2. 目标设计

### 2.1 层级 Key 体系

```
key 命名规则:  {scope}.{data_type}

scope 层级:
  chip                              ← SoC 顶层
  chip.conn                         ← 芯片连接性
  ip.<name>                         ← IP 模块（uart/dma/gpio/...）
  ip.<name>.<sub_module>            ← IP 子模块（uart.tx/uart.rx/...）

data_type:
  spec, design_arch, model,
  env, tests, regression,
  coverage, debug, testplan,
  checklist, signoff
```

### 2.2 完整 Key Map

```
chip.spec                    ← 芯片级规格
chip.testplan                ← 芯片级验证计划
chip.regression              ← 芯片级回归结果
chip.coverage                ← 芯片级覆盖率（汇总）
chip.signoff                 ← 芯片级签核

chip.conn.clk                ← 连接性：时钟连接
chip.conn.rst                ← 连接性：复位连接
chip.conn.bus                ← 连接性：总线连接
chip.conn.intr               ← 连接性：中断连接

ip.uart.spec                 ← UART 规格
ip.uart.design_arch          ← UART 设计架构
ip.uart.model                ← UART 参考模型
ip.uart.env                  ← UART UVM 环境
ip.uart.tests                ← UART 测试用例
ip.uart.regression           ← UART 回归结果
ip.uart.coverage             ← UART 覆盖率
ip.uart.checklist            ← UART 签核清单

ip.uart.tx.spec              ← UART TX 子模块规格
ip.uart.tx.env               ← UART TX 子模块 UVM
ip.uart.tx.coverage          ← UART TX 子模块覆盖率

ip.dma.spec                  ← DMA 规格
ip.dma.env                   ← DMA UVM 环境
ip.dma.regression            ← DMA 回归结果
...
```

### 2.3 消费拓扑（通配符）

```python
# 从固定 agent 名 → 变为通配符模式
_CONSUMES_TOPOLOGY = {
    # 每个 IP 独立的数据流
    "ip.*.spec":        ["design_architect", "model_agent", "verification_architect"],
    "ip.*.design_arch": ["model_agent", "verification_architect"],
    "ip.*.model":       ["verification_architect"],
    "ip.*.env":         ["test_engineer", "regression_manager"],
    "ip.*.tests":       ["regression_manager"],
    "ip.*.regression":  ["coverage_manager", "debug_engineer"],
    "ip.*.coverage":    ["signoff_service"],

    # 芯片级流转
    "chip.spec":        ["vplan_generator"],
    "chip.testplan":    ["regression_manager"],
    "chip.regression":  ["signoff_service"],
    "chip.coverage":    ["signoff_service"],

    # 连接性（跨 IP）
    "chip.conn.*":      ["coverage_manager"],
}
```

---

## 3. API 设计

### 3.1 基础操作

```python
class ContextStore:
    """SoC 层级上下文 — 点号分隔 key + scope 隔离 + 通配查询"""

    # ── 写入 ──

    def put(self, key: str, value: Any, source: str = "", synthetic: bool = False):
        """层级写入。
        ctx.put("ip.uart.spec", {"features": [...]}, source="spec_planner")
        """

    def update(self, key: str, partial: dict, source: str = ""):
        """合并更新已有条目。
        ctx.update("ip.uart.coverage", {"line_pct": 96.5}, source="coverage_manager")
        """

    # ── 读取 ──

    def get(self, key: str, default=None):
        """精确读取单个 key。"""

    def fetch(self, key: str, fields: List[str] = None):
        """读取单个 key，可选只取部分字段。"""

    def collect(self, pattern: str) -> Dict[str, Any]:
        """通配符批量读取。
        ctx.collect("ip.*.coverage")  → {
            "ip.uart.coverage": {...},
            "ip.dma.coverage": {...},
            "ip.gpio.coverage": {...},
        }
        """

    def aggregate(self, pattern: str, field: str) -> Any:
        """聚合某个字段。
        ctx.aggregate("ip.*.coverage", "line_pct")  → [96.5, 88.3, 99.1]
        """

    # ── Scope 隔离 ──

    def scoped(self, prefix: str) -> "ContextStore":
        """返回 prefix 下的子上下文（视图，非拷贝）。
        ip_ctx = ctx.scoped("ip.uart")
        ip_ctx.get("spec")       # 等价于 ctx.get("ip.uart.spec")
        ip_ctx.get("env")        # 等价于 ctx.get("ip.uart.env")
        所有操作自动加 prefix 前缀。
        """

    def list_children(self, prefix: str) -> List[str]:
        """列出某 scope 下的直接子 scope。
        ctx.list_children("ip")   → ["uart", "dma", "gpio"]
        """

    # ── 生命周期 ──

    def prune_scope(self, scope: str):
        """清理某个 scope 下的所有 key。
        ctx.prune_scope("ip.uart")  # UART 所有阶段完成后释放
        """

    def snapshot(self) -> dict: ...

    # ── 兼容旧 API ──
    def __getitem__(self, key): ...
    def __setitem__(self, key, value): ...
    def __contains__(self, key): ...
```

### 3.2 使用示例（SoC Pipeline）

```python
ctx = ContextStore()

# Phase 1: 芯片级 spec 分析
ctx.put("chip.spec", spec_data, source="spec_planner")

# Phase 2: 各 IP 并行分析（未来）
for ip_name in ["uart", "dma", "gpio"]:
    ip_ctx = ctx.scoped(f"ip.{ip_name}")
    ip_ctx.put("spec", extract_ip_spec(chip_spec, ip_name))
    ip_ctx.put("design_arch", design_architect.analyze(ip_ctx))
    ip_ctx.put("env", verification_architect.generate(ip_ctx))
    ip_ctx.put("tests", test_engineer.generate(ip_ctx))

# Phase 3: 各 IP 回归（并行）
for ip_name in ["uart", "dma", "gpio"]:
    ip_ctx = ctx.scoped(f"ip.{ip_name}")
    ip_ctx.put("regression", run_dvsim(ip_ctx.get("env"), ip_ctx.get("tests")))
    ip_ctx.put("coverage", analyze_coverage(ip_ctx.get("regression")))

# Phase 4: 芯片级汇总
all_coverage = ctx.collect("ip.*.coverage")
chip_coverage = merge_coverage(all_coverage)
ctx.put("chip.coverage", chip_coverage)

# Phase 5: 签核
ctx.put("chip.signoff", signoff_service.generate(ctx))
```

---

## 4. ScopedContextStore（视图实现）

```python
class ScopedContextStore:
    """ContextStore 的 scope 视图 — 自动加前缀，不拷贝数据"""

    def __init__(self, parent: "ContextStore", prefix: str):
        self._parent = parent
        self._prefix = prefix

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}.{key}" if self._prefix else key

    def put(self, key: str, value: Any, **kwargs):
        return self._parent.put(self._full_key(key), value, **kwargs)

    def get(self, key: str, default=None):
        return self._parent.get(self._full_key(key), default)

    def scoped(self, sub: str) -> "ScopedContextStore":
        return ScopedContextStore(self._parent, self._full_key(sub))

    def collect(self, pattern: str):
        return self._parent.collect(self._full_key(pattern))

    def __repr__(self):
        keys = self._parent._data.keys()
        mine = [k for k in keys if k.startswith(self._prefix + ".")]
        return f"ScopedCtx({self._prefix}, {len(mine)} keys)"
```

---

## 5. 拓扑 & prune 改造

### 5.1 通配匹配

```python
import fnmatch

class _Topology:
    """动态消费拓扑 — 支持 fnmatch 通配"""

    @staticmethod
    def consumers_of(key: str) -> List[str]:
        """返回消费 key 的 agent 列表。
        key="ip.uart.coverage" → 匹配模式 "ip.*.coverage" → ["signoff_service"]
        """
        consumers = []
        for pattern, agents in _CONSUMES_TOPOLOGY.items():
            if fnmatch.fnmatch(key, pattern):
                consumers.extend(agents)
        return list(set(consumers))

    @staticmethod
    def is_all_consumed(key: str, completed_agents: List[str]) -> bool:
        consumers = _Topology.consumers_of(key)
        return all(c in completed_agents for c in consumers)
```

### 5.2 按 Scope Prune

```python
def prune_scope(self, scope: str) -> List[str]:
    """清理某个 scope 下的所有已消费 key。"""
    removed = []
    for key in list(self._data.keys()):
        if key.startswith(scope + ".") or key == scope:
            if _Topology.is_all_consumed(key, self._completed_agents):
                del self._data[key]
                removed.append(key)
    return removed
```

---

## 6. Pydantic Schema 扩展

```python
# src/core/context.py — 替换现有 flat Pydantic models

class IpContext(BaseModel):
    """单个 IP 的完整上下文"""
    spec:          dict = {}
    design_arch:   dict = {}
    model:         dict = {}
    env:           dict = {}
    tests:         dict = {}
    regression:    dict = {}
    coverage:      dict = {}
    checklist:     dict = {}
    signoff:       dict = {}

class ChipContext(BaseModel):
    """SoC 芯片级上下文"""
    spec:          dict = {}
    testplan:      dict = {}
    regression:    dict = {}
    coverage:      dict = {}
    conn:          dict = {}            # 连接性测试结果
    signoff:       dict = {}
    ips:           Dict[str, IpContext] = {}

class SoCContext(BaseModel):
    """SoC 完整上下文 — 序列化/反序列化"""
    chip:   ChipContext
    project: dict = {}                   # .signoffai.yaml 内容
    run_id:  str = ""
    workflow: str = ""

# ContextStore 增加 export/import
class ContextStore:
    def to_soc_model(self) -> SoCContext:
        """将层级 ContextStore 导出为类型安全的 SoC 模型"""

    @classmethod
    def from_soc_model(cls, model: SoCContext) -> "ContextStore":
        """从 SoC 模型恢复 ContextStore"""
```

---

## 7. 改造路线

| 阶段 | 改动 | 向后兼容 |
|:---:|------|:---:|
| **1** | `ContextStore` 支持层级 key（不改现有 API） | ✅ 旧 key 仍可用 |
| **2** | 新增 `scoped()`, `collect()`, `aggregate()`, `list_children()` | ✅ 纯增量 |
| **3** | `_CONSUMES_TOPOLOGY` 改为 fnmatch 通配 | ✅ 旧精确 key 仍匹配 |
| **4** | `SoCContext` Pydantic model | ✅ 新增 |
| **5** | Pipeline 逐步切换为 scope 模式 | ⚠️ `execution.py` 需改 |

**向后兼容策略**：旧代码 `ctx.put("spec", {...})` 等价于 `ctx.put("spec", {...})`（无前缀 key 仍然有效），新代码用 `ctx.scoped("ip.uart").put("spec", {...})`。

---

## 8. 代码量估算

| 文件 | 改动量 | 说明 |
|------|:---:|------|
| `src/core/context.py` | +200 行 | 新增 scoped/collect/prune_scope/SoCContext |
| `src/core/execution.py` | ~100 行 | 适配 scope 模式，保留旧路径兼容 |
| `src/core/agent_tools.py` | ~30 行 | 拓扑通配 |
| `src/agents/*/main.py` | 不改 | Agent 不感知 scope，由 Pipeline 传入 |
| **总计** | ~330 行 | 1-2 天 |

# 约束策略系统（constraint policy）模板文档

> 对应模板：`src/tools/uvm_tools/tool_uvm/templates/environment_templates/env_cons_*.j2`
> 驱动 YAML：`constraint:` 文档（示例见 `examples/apb_constraint.yaml`）
> 生成位置：`generated/env/cons/`

## 1. 一句话定位

**多端口事务组合场景的约束引擎**：把「A 端口的事务和 B 端口的事务满足什么关系」这类跨事务约束，
拆成一个可叠加、可组合、可运行时配置（plusargs）的策略链，由协调序列统一调度生成与发送。

## 2. 五个文件的关系（生成 = 编译依赖 = 调用链）

```
{env}_constraint_policy.sv  ── 基类 + 事务容器（policy_context）
        │ include
{project}_constraint_policies.sv  ── 每个策略一个派生类（apply/verify 逻辑）
        │ include
{project}_policy_combinator.sv  ── 组合器：policies 队列 + 5 种 apply 模式
        │ include
{project}_policy_factory.sv  ── 工厂：注册/创建组合器（plusargs 选择策略）
        │ include
{project}_coordinated_sequence.sv ── 协调序列：循环 [造事务 → 策略链应用 → 校验 → 入队]，
                                       并行 [出队 → 发送到各端口 sequencer → 超时看护]
```

## 3. 核心对象

### 3.1 `policy_context` —— 一次「组合事务」的容器

一次迭代（iteration）里**所有端口的事务**打包在一个 context 里流转：

```
policy_context {
  {端口1}_trans   // 如 apb_master_trans : APB_master_seq_item
  {端口2}_trans
  ...
  scenario_name / iteration / total_iterations / timestamp   // 元数据
  get_transaction(name) / set_transaction(name, trans)       // 按名字存取
  copy(other)                                                 // 深拷贝（SEQUENTIAL/CHAIN 模式用）
}
```

策略之间不直接互相调用，**全部通过 context 读写事务**——这是组合能成立的关键。

### 3.2 `constraint_policy` 基类 —— 一条策略的接口

```
policy_name / enabled / priority / params[string]
apply(ref ctx)     ← 核心：修改 ctx 里的端口事务（子类实现）
verify(ref ctx)    ← 校验一致性（默认 return 1）
get_stats()        ← 统计串（报告用）
parse_params(str)  ← "k=v,k2=v2" 解析进 params
```

### 3.3 策略派生类（`{project}_constraint_policies.sv`）

每个 YAML `policies[]` 一项 → 一个类 `{name}_policy`：

- 成员：YAML `params` 每项一个成员（int/string/bool/list/float）+ `applies_to` 每个端口一个事务句柄
- `new()`：policy_name/priority/params 默认值初始化
- `apply()`：
  1. 从 ctx 取出 `applies_to` 列出的端口事务（`$cast` 失败则告警退出）
  2. `case (policy_name)` 执行协议逻辑
     - **内置策略名**（precision_consistency / mem_capacity / data_dependency /
       boundary_overflow / concurrent_access / power_performance / compute_mode）
       → 模板自带默认逻辑分支
     - **自定义名** → 空分支（骨架），**手填协议逻辑**
- `parse_plusargs()`：每个 param 支持 `<param>=<值>` plusarg 覆盖

### 3.4 组合器 `policy_combinator` —— 策略怎么叠加

```
policies[$] 队列 + apply_mode（YAML combinator.modes 生成枚举）
apply(ctx):
  1. sort_by_priority()           // 优先级小的先
  2. case (apply_mode) 五种模式:
     APPLY_ALL          全部策略依次施加（叠加）
     APPLY_WEIGHTED     按 priority 加权随机选一个施加
     APPLY_FIRST_MATCH  第一个 should_apply() 命中的施加（可手写命中条件）
     APPLY_SEQUENTIAL   每条策略作用在上一条的副本上，最后拷回
     APPLY_CHAIN        每条策略输出新 context 传给下一条（链式流水）
verify(ctx): 所有策略的 verify 逐个执行
configure_from_plusargs():
  +{ENV}_POLICY_MODE=APPLY_ALL|...    // 运行时换模式
  +NO_<policy> / +ENABLE_<policy>     // 关/开单个策略
  +<policy>_PRIORITY=<n>              // 改优先级
  +<param>=<v>                        // 各策略参数
report_stats(): 每条策略 apply/verify 计数 + get_stats()
```

### 3.5 工厂 `policy_factory` —— 策略注册与创建

```
register_policy(name, policy) / get_policy(name)    // 注册表
create_default_combinator()                          // 全策略注册进组合器
create_from_plusargs():
  +{ENV}_POLICY_LIST=a,b,c   → 只取 a/b/c 三条策略（clone 出新实例）
  无该 plusarg              → 默认全部
register_all_policies() + initial 自动注册（文件尾部 initial begin）
```

### 3.6 协调序列 `coordinated_sequence` —— 总调度

```
body():
  configure_from_plusargs()       // +NUM_TRANS / +QUEUE_SIZE / +TIMEOUT_MS
  fork
    generate_transactions():      // 生产者
      for i in [0, num_transactions):
        ctx = new()
        create_base_transactions(ctx)   // 每个端口事务 new + randomize（可覆写）
        policy_combo.apply(ctx)         // ★ 策略链在此施加
        policy_combo.verify(ctx)
        queue.push_back(ctx)            // 入队（队列 > queue_size 则 #1 流控）
    process_transactions():        // 消费者
      出队 → fork send_transactions(ctx) + 超时看护 join_any
  join
  report_summary()
send_transactions():  每个端口事务 start_item/finish_item 到
                      p_sequencer.{端口名}_sqr（null 则跳过）
```

## 4. YAML schema 全字段

```yaml
constraint:
  name: apb_cons          # 文件前缀（{project}）
  env_name: APB_env       # 类名前缀（{env}，与 env agents 关联）

transactions:             # 端口清单
  - { name: apb_master, type: APB_master_seq_item }   # name 必须 = env agent 名
    # type: 该端口 seq_item 类型

policies:                 # 策略清单
  - name: apb_addr_align  # 内置名 → 默认逻辑；自定义名 → 空骨架（手填）
    description: "..."
    priority: 10          # 越小越先施加；APPLY_WEIGHTED 时作权重
    params:               # 参数成员（可 plusargs 覆盖）
      - { name: align, type: int, default: 4 }
        # type: int / string / bool / list / float
    applies_to: [apb_master]   # 本策略读写哪些端口（多端口组合 = 列多个）

combinator:
  default_mode: APPLY_ALL
  modes: [APPLY_ALL, APPLY_WEIGHTED, APPLY_FIRST_MATCH, APPLY_SEQUENTIAL, APPLY_CHAIN]
```

## 5. 运行时数据流（一次迭代）

```
coordinated_sequence
  └─ create_base_transactions: new+randomize 每个端口事务 → ctx
  └─ combinator.apply(ctx)
        ├─ policy1.apply(ctx): 从 ctx 取 applies_to 端口事务 → 改字段
        ├─ policy2.apply(ctx): ...
        └─ ...（模式决定叠加方式）
  └─ verify → 入队
  └─ send_transactions: 每个端口事务 → p_sequencer.{端口}_sqr
        （发送给对应 env agent 的 sequencer → driver 驱动到总线）
```

## 6. 自定义策略怎么写（手填 apply 骨架示例：APB 地址对齐）

在 `apb_cons_constraint_policies.sv` 的 `apb_addr_align_policy` 类里，
`case (policy_name)` 的 `"apb_addr_align":` 分支填：

```systemverilog
"apb_addr_align": begin
  // apb_master_trans 是 applies_to 声明的端口事务句柄
  apb_master_trans.paddr = (apb_master_trans.paddr / align) * align;
end
```

之后重新生成时怎么办？—— 该文件是**生成文件**：把这段逻辑放进 YAML 的自定义区域
（`custom_code` 槽）或用 `-m` merge 流程保留手改，见 gen_uvm 的 pragma custom 机制。

## 7. plusargs 一览

| plusarg | 作用 |
|---|---|
| `+{ENV}_POLICY_MODE=APPLY_WEIGHTED` | 运行时切换组合模式 |
| `+{ENV}_POLICY_LIST=addr,b2b` | 只启用指定策略 |
| `+NO_<policy>` / `+ENABLE_<policy>` | 关/开单条策略 |
| `+<policy>_PRIORITY=5` | 改优先级 |
| `+<param>=<v>` | 策略参数覆盖（如 `+align=8`） |
| `+{ENV}_NUM_TRANS=100` / `+QUEUE_SIZE=` / `+TIMEOUT_MS=` | 协调序列配置 |

## 8. 与 testpoint/回归的衔接

- `constraint_policy` 列（testpoint xlsx）填这里的策略名 → traceability 关联
- 组合模式 + 策略参数用 plusargs 控制 → 同一 test 类跑多种约束组合（回归矩阵）
- 校验层规则：transactions 重名 / policy 重名 / applies_to 未命中 → error；
  自定义策略名 → warning（提示手填 apply 逻辑）

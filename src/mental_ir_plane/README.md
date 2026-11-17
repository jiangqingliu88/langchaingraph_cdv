# mental_ir_plane —— 唯一 IR 根（总分架构）

```text
src/mental_ir_plane/
│
├── 总：理解层
│   ├── model.py                 MentalIR（goals/assumptions/ambiguities/intents/risks）
│   └── store.py                 Mental IR 原子读写
│
├── 总：设计与模型契约
│   └── dplan/
│       ├── model.py             DPlan IR（interfaces/features/modules/model_contract）
│       ├── load.py              原始 DPlan JSON/YAML → DesignPlan
│       ├── validate.py          结构检查（只报缺口）
│       └── store.py             dplan_ir_v1 原子读写
│
├── 总：融合层
│   └── unified/
│       ├── schema.py            统一包络 / Entity / Relation / Issue
│       ├── normalize.py         id / token / 列表归一化
│       ├── adapters/            mental / dplan / vplan 快照适配
│       ├── build.py             项目作用域对象图 + 最佳候选关系
│       ├── views.py             Mental / DPlan / VPlan 三种投影
│       ├── store.py             统一 IR 原子读写
│       └── vplan_types.py       VPlan 测试点 IR 类型
│
├── 分：引擎与契约
│   ├── contract/                VPlan/测试点契约、映射、ledger/shadow
│   ├── decision/                l3：case IR、case view、evidence、knowledge、spec tools
│   ├── formal/                  FormalPlan（性质 / 假设 / 证明义务）
│   ├── interface_timing/        Temporal IR 与 binding
│   ├── proposal/                受控修复 Proposal
│   ├── specification_compiler/  Specification 编译契约
│   └── vplan/                   VPlan 项目加载 / 用例构建 / 执行 / 覆盖率 / UVM 架构
│
└── example/                     样例输入（不是运行证据）
```

## 分层规则

1. **总层**（`model.py / store.py / unified/`）只回答“理解与融合”：
   - 不直接执行 EDA；
   - 不把 candidate 关系升级成 confirmed / PASS；
   - unified 只消费快照，不复制引擎实现。
2. **分层**（`contract/ decision/ formal/ interface_timing/ proposal/
   specification_compiler/ vplan/`）回答“契约、计划、用例、执行模型”：
   - 保留各引擎原有的状态与边界；
   - 不反向依赖 Agent / Engine 的业务实现。
3. **Execution / Evidence** 不混入以上对象图；它们由独立记录回答“真跑过什么”。

## 入口

```bash
vagent mental build   ...        # 生成 Mental IR
vagent mental dplan check <dplan.json>       # DPlan IR 结构检查
vagent mental dplan normalize <in> --out <ir.json>
vagent mental unify   ...        # Mental + DPlan + VPlan → 统一 IR
vagent vplan status|review|execute <project>
```

## 兼容

- 原 `src/ir_plane` 已删除；import 统一为 `src.mental_ir_plane.<subpackage>`。
- `src/mental_ir_plane/vplan/types.py` 是兼容入口，类型定义在
  `unified/vplan_types.py`。

# 黄金参考模型库设计（Golden Reference Model Library）

> 版本: v0.1 | 日期: 2026-08-17 | 状态: 设计
> 目标: 彻底解决"参考模型是 a+b 模板"与"LLM 生成不稳定"——参考模型必须真实、可验证、可复用。

---

## 一、问题背景

审计发现（2026-08-17）：
- `model agent` 的 `_render` 把所有 op 渲染成 `a + b`（ALU 假设），对 APB/UART 等设计完全错误
- `tb_top.sv.j2` 里 ref_model 默认未实例化 → "参考模型比对"从未真正发生过
- LLM 现场生成参考模型 → 不稳定：语法过但语义错，且无法证明正确

**结论**：参考模型不能"每次现场生成"，必须来自**经过验证的黄金模型库**——LLM 只做"选模型 + 参数化"，正确性由入库前的定向仿真保证。

## 二、设计原则

| 原则 | 含义 |
|------|------|
| **入库必须验证** | 黄金模型进库前必须通过定向 case 仿真（scoreboard matched==N && mismatched==0） |
| **LLM 只做选择** | 从库中按 spec 特征匹配黄金模型并参数化，不现场写功能逻辑 |
| **无匹配 = 诚实占位** | 库中无匹配 → placeholder（audit 拒绝签核），禁止降级为模板 |
| **版本不可变** | 入库后模型不可修改，只能新增版本（哈希 + 版本号） |

## 三、库结构

```
model_library/                      # 黄金模型库（仓库内，git 版本化）
├── apb_slave/
│   ├── v1/model.sv                 # 黄金 SV 模型（APB 读写语义，参数化寄存器表）
│   ├── v1/manifest.json            # {sha256, 验证证据, 参数 schema, 版本}
│   └── v1/verify/                  # 入库验证证据（定向 case 仿真日志 + scoreboard 结果）
├── uart_tx/
│   ├── v1/model.sv                 # 黄金 UART TX（起始位+8数据+停止位，波特率参数化）
│   └── v1/manifest.json
├── uart_rx/
│   └── v1/...
├── fifo16/
│   └── v1/...
├── irq_gen/
│   └── v1/...
└── INDEX.yaml                      # 索引：IP 名 → 可用版本 + 参数 schema + 匹配关键词
```

### manifest.json 字段

```json
{
  "ip": "uart_tx", "version": "v1",
  "sha256": "…", "size": 1234,
  "verified_by": {"test": "uart_tx_directed", "sim_time_ns": 100000,
                  "scoreboard": {"matched": 500, "mismatched": 0},
                  "sim_log_sha256": "…"},
  "params_schema": {"baud_div": {"type": "int", "default": 1302},
                    "data_bits": {"type": "int", "enum": [7, 8]}},
  "matched_features": ["uart_tx", "serial", "baud", "起始位"]
}
```

## 四、入库流程（一次，人工/CI 把关）

```
1. 编写黄金模型（SV，含 parameter 化接口）
2. 生成定向 case（覆盖寄存器读写/协议时序/边界）
3. 仿真验证（vsim + scoreboard）：matched==N && mismatched==0 才继续
4. 计算 sha256 + 记录验证证据 → manifest.json
5. 入 INDEX.yaml → git 提交（模型不可变，只能加版本）
```

**验证脚本**：`scripts/model_library_verify.py <ip> <version>`（复用 `check_env_arch.check_scoreboard` 的 scoreboard 断言逻辑）。

## 五、model agent 新流程（替换现场模板渲染）

```
spec.json
  ↓
1. IP 匹配：按 spec.features/interfaces 查 INDEX.yaml（关键词 + 协议匹配）
  ├── 命中 → 2. 参数化（从 spec 提取 baud_div/寄存器表等 → 实例化参数）
  │         3. 落盘 model/<module>_vN/ + 记录库引用 {ip, version, sha256}（可追溯）
  │         placeholder=False（模型来自验证过的黄金库）
  └── 未命中 → 4. 诚实占位：placeholder=True + 提示"需要为该 IP 建黄金模型入库"
                   （audit 门禁 model_real 拒绝签核）
```

**关键点**：
- `model_data["golden_ref"] = {"ip": "uart_tx", "version": "v1", "sha256": "…"}` → audit 可核验
- audit 门禁 `model_real`：placeholder=False **且** golden_ref.sha256 与库中一致
- 库版本升级不影响旧 run 复现（run 记录引用版本 + sha256）

## 六、与现有代码的落点

| 现有组件 | 改动 |
|----------|------|
| `src/agents/model/main.py` | `_render_sv` 保留（端口生成），功能逻辑改从库加载；新增 `_match_golden(spec)` / `_parameterize(ip, spec)` |
| `src/tools/cmodel_tools/` | C++/DPI 桥接保留，黄金模型优先用 SV（与 env 同语言，无需 DPI） |
| `src/layers/l2_orchestration/evidence/manifest.py` | model 阶段记录 `golden_ref`（入库模型 sha256 进证据链） |
| `src/agents/audit/main.py` | `model_real` 门禁增强：校验 golden_ref.sha256 |
| `tb_top.sv.j2` | `ref_model_enabled` 在黄金模型命中时置 true（真正实例化比对） |
| `scripts/` | 新增 `model_library_verify.py`（入库验证）+ `model_library_import.py`（入索引） |

## 七、首批黄金模型（按价值排序）

| IP | 来源 | 验证 case |
|----|------|----------|
| apb_slave（寄存器表参数化） | 从 `find_spec_yaml._gen_apb_register_model` 泛化（已有雏形） | 读写回环 + 边界地址 |
| uart_tx | 新写 | 9600/115200 波特率逐位比对 |
| uart_rx | 新写 | 采样窗口 + 帧错误注入 |
| fifo16 | 新写 | 满/空/溢出/水印 |
| irq_gen | 新写 | 触发条件 + 延迟 |

## 八、验收标准

- [ ] `model agent` 对 apb_uart 命中 apb_slave + uart_tx/rx 黄金模型 → placeholder=False 且 sha256 可追溯
- [ ] 无匹配时 → placeholder=True，audit 拒绝签核（不允许静默降级）
- [ ] `tb_top` 在黄金模型命中时真实实例化比对（ref_model_enabled=true）
- [ ] 入库模型 sha256 进 manifest（复现时核验库版本）
- [ ] `scripts/model_library_verify.py` 对首批 5 个模型全部 PASS

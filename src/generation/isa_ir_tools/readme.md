# isa_ir_tools — ISA IR → 激励命令流

本目录是一个**自闭环**工具包：只依赖标准库和包内相对导入，不引用仓库其它模块。
输入一个 case IR 文件，按 `tensors → ir → commands` 三段产出可直接交接给 TB 的命令包。

## 入口

唯一入口是 `run_flow.py`，内部按顺序 fork `isa_ir_tools.pipeline` / `isa_ir_tools.cli` / `isa_ir_tools.cmd_compile`：

```bash
cd src/generation/isa_ir_tools
python -B -X utf8 run_flow.py ir_seq/<case>.ir.txt \
    --target standalone --core-id 0 [--out-dir artifacts/<case>]
```

- 不传 `--out-dir` 时默认写到本目录旁的 `artifacts/<case>/`（`<case>` 为去掉 `.ir.txt` 的文件名）。
- `--target` 目前只实现了 `standalone`；`cluster` 会明确报 `UNSUPPORTED_TARGET`。
- 可选：`--isa-revision {v1.4,ISA_VERSION_V1.4,xlsx_v0.3_reviewed}`、`--no-cfg-lint`、`--csr-clk-rst`。
- 退出码：`0` 成功；`2` 输入/解析/编译失败（失败阶段会写进对应的 `stageN.log`）。

也可以不经 `run_flow.py`，直接跑分阶段命令：

```bash
# 三段一起
python -m isa_ir_tools.pipeline all <case.ir.txt> --out-dir <bundle> \
    --target standalone --core-id 0
# 只做命令编译（输入必须是 operand-resolved 的 seq.ir）
python -m isa_ir_tools.cmd_compile <bundle>/02_ir/seq.ir \
    --target standalone --core-id 0 --out-dir <bundle>/03_commands
```

> 注意：`-m` 形式的 cwd 必须是本包的父目录 `src/generation`；`run_flow.py` 已自行处理 `sys.path`，可在本目录直接运行。

## 三阶段流水线

`pipeline.py` 依次启动三个子进程，每个目录的产出者一一对应：

| 目录 | 产出者 | 内容 |
| :--- | :--- | :--- |
| `01_tensors/` | `isa_ir_tools.pipeline tensors` → `isa_ir_tools.cli`（core.py / formats.py） | `tensor_spec.json`、`scalars.json`、`data/{*.bin,*.hex,*.memh}`、`data/manifest.json`（含文件级 sha256） |
| `02_ir/` | `isa_ir_tools.pipeline ir` → `ir_flow.FixedIRFlow.generate` | 重新解析源文件、合并 tensor manifest、推导 CFG 行、归一化操作数，产出 `seq.ir`、`seq.ir.json`、`tensor_spec.json`、`tensors/`、`cfg_bindings.json`、`case_catalog.json`、`source_map.json`、`build_report.txt`、`generation_report.json` |
| `03_commands/` | `isa_ir_tools.cmd_compile.compile_seq` | 最终 TB 交接物：`commands.tsv`、`commands.json`、`commands.txt`、`cmddata.memh`、`data/`（mem_init 引用的二进制/hex 资产） |

`pipeline.py` 还会在 bundle 根目录写 `pipeline.report.json` 和 `stage1..3.log`。

## 输入格式

手写源文件示例（`ir_seq/sanity_glsu_local_dram_smoke.ir.txt` 即此类）：

- 声明：`.case`、`.profile`、`.tensor`、`.bind`、`.view`、`.reserve_output`
- 指令：`tld_drv_xn / tst_drv_xn / gemm_* / noc_* / npu_cfg_drv_xn ...`
- TB 控制：`wait_done / wait_cycles / mem_init / mem_scrub / checkpoint / expect_* / csr_write / csr_read ...`

### 已解析的 `seq.ir` 也可以直接回灌

本工具**同时接受已经 operand-resolved 的 `seq.ir`**（带 `// Operand-resolved IR` 头）：

- `.view NAME, tensor="..."` 会被当作 allocation view（等价于源语法的 `.bind`）。
- 指令已带显式 `rs1val/rs2val`（或 `operand_encoding`）时，`src/dst` 符号即使没有声明也允许通过——以显式操作数为准，符号只作溯源。
- `.tensor` 的 `generation` 里由生成期回填的元数据（`file`、`stream_version`、`actual_special_values` 等）会被忽略，只用 `mode/pattern/seed/...` 重新生成载荷。

## 版本契约

- 当前唯一有效契约：`ISA_VERSION_V1.4` / `GLOBAL48_V1.4`（`isa_versions.py`）。
- 已退役的 `xlsx_v0.3_reviewed` / `global48_xlsx_v0.3_reviewed` 仅作为**窄别名**接受，目的是让历史 `seq.ir` 可读；指令的 `operand_encoding` 仍会按 V1.4 描述符表重新校验，不一致会报 `ISA REVISION MISMATCH`。

## 关键格式契约

- **74-bit cmddata**（`cmd_compile.py:pack_cmddata`）：
  `(rs2val<<42) | (rs1val<<10) | (funct7<<3) | (xd<<2) | (xs1<<1) | xs2`
  写进 `cmddata.memh` 和 TSV 时用 `%019x`（19 位小写 hex）。`instr_flag` 不打包，只留在 JSON 记录里。
- **两级 sha256**：Stage 1 在 `01_tensors/data/manifest.json` 记录每个载荷文件的 sha256；`commands.json` 的 `source.source_sha256 = sha256(seq.ir 原始字节)`。
- **TSV 行形态**（`commands.tsv`）：
  - 指令行：`index \t seq.ir 行号 \t source_isa`
  - 控制/透传行：同三列，第三列为原始文本（`wait_done`、`mem_scrub` 等）；`csr_*` 会把 `name=` 规范化成 `addr=`；`mem_init` 的文件路径会被重写为 `data/<资产名>`
  - 分发行：`dispatch_mask \t {"mask":N} \t 行号 \t source_isa`，以及 `dispatch_skip`
- **`commands.json` 头**：`schema=cmd sch program v2`、`target/core_id`、`isa_revision/address_schema`、`csr_clk_rst`、`playback_file=commands.tsv`、`control_execution=testbench_player_required`、`dispatch_policy{initial_nice_mask, group_mask, non_target, raw cmd}`、`source{source, source_sha256, cmddata_width=74, layout 位段}`、有序 `commands[]`（每条含 `index/op/kind/source_line`，以及 `cmddata` 或 `passthrough+parameters`）。
- **CSR 符号名 → 地址**（`csr_map.py`）：`csr_write name=creg_perf_ctrl, data=...` 会重写为 `addr=0x...`；clk/reset 区间默认禁止写入，需 `.case csr_clk_rst=1` 或 `--csr-clk-rst`。

## 工作台接入

桌面工作台的「ISA 激励」页（`verify.isa_gen`）不 import 本包，统一经
`src/workbench/bridge/catalog.py` 的两条绑定调用：

| 绑定 | 入口 | 纯度 | 用途 |
| :--- | :--- | :--- | :--- |
| `isa_ir.validate` | `isa_ir_tools.api:run_validate` | 纯 | 只解析：动作 / 张量 / 视图计数（不写盘） |
| `isa_ir.build` | `isa_ir_tools.api:run_build` | 非纯 | 跑完整三阶段并落盘（**写盘 + 子进程**，必须显式触发） |

`api.run_build` 等价于 `run_flow.py`：把源写进 bundle 的 `source.ir.txt`，
依次产出 `01_tensors / 02_ir / 03_commands`，返回 `seq_ir`、`commands.json`
摘要与阶段日志。

## 已知限制

- `data/csr_map.csv` 目前只有 127 行，而加载器固定要求 232 行（含 8 个 `_icg_en`）。含 `csr_write/csr_read` 的 case 会**显式失败**；不含 CSR 操作的 case 不受影响（映射表按需加载）。
- `artifacts/` 是可再生产物，不要手工编辑；重跑会覆盖同名文件。

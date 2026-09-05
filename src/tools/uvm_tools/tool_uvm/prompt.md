禁止简化代码，有问题的直接咨询我。

# pragma custom 槽位注入契约（LLM 写入 custom_code 前必读）

生成器对每个文件模板开放若干 `// pragma custom <slot> begin ... end` 区域。
你（Agent）把协议时序/自定义逻辑写进 YAML 的 `custom_code.<slot>`，生成时注入对应位置；
区域内容为空时回退模板默认实现。**只写细槽（语义槽），不写粗区。**

## 槽位一览（interface YAML → custom_code）

| slot | 注入位置 | 可见变量 | 缺省行为（留空时） |
|---|---|---|---|
| `drive_logic` | master/slave driver 驱动 task 内 | `req`（master seq_item）/ `rsp`（slave seq_item）、`cfg`、`vif`（含 master_cb/slave_cb 时钟块） | APB 两拍 / 通用单拍驱动 |
| `collect_logic` | monitor 采样 task 内 | `tx`（目标 seq_item）、`vif`（mon_cb） | 逐字段采样（APB 仅采完整访问拍） |
| `field_decl` | 类体成员声明区 | 无（纯声明） | 空 |
| `build_logic` | build_phase 末尾 | 组件全部成员 | 空 |
| `connect_logic` | env connect_phase 末尾 | env 全部成员 | 空 |
| `seq_body` | sequence 类体 | `req`/`req_resp`、`p_sequencer` | 空 |

## 写入格式

```yaml
custom_code:
  drive_logic: |
    // 自定义协议时序（缩进按模板上下文 4 空格）
    @(vif.master_cb);
    vif.master_cb.psel <= 1'b1;
```

规则：
1. 内容为 SystemVerilog 语句块，`|` 块字符串，缩进与模板上下文一致
2. 字段名必须出现在 interface YAML 的 transaction_vars/ports（语义校验层会拦）
3. 协议级逻辑优先写 `drive_logic`/`collect_logic`；成员加 `field_decl`；组装连接加 `build_logic`/`connect_logic`
4. 回填优先级：custom_code 非空 > merge 源手改 > 模板默认 —— 你要覆盖手改代码就直接写 custom_code

## 示例（APB 加一个 stall 周期）

```yaml
custom_code:
  drive_logic: |
    @(vif.master_cb);
    vif.master_cb.psel    <= 1'b1;
    vif.master_cb.paddr   <= req.paddr;
    vif.master_cb.pwrite  <= req.pwrite;
    vif.master_cb.pwdata  <= req.pwdata;
    repeat (2) @(vif.master_cb);   // 两个等待拍（stall）
    vif.master_cb.penable <= 1'b1;
    do @(vif.master_cb); while (vif.master_cb.pready !== 1'b1);
    vif.master_cb.penable <= 1'b0;
    vif.master_cb.psel    <= 1'b0;
```

## 约束策略（constraint YAML）的 LLM 注入点

自定义策略名（非 7 个内置名）生成空 apply 骨架；把策略逻辑写进对应分支即可（生成文件内手填，
或告诉我策略名 + 逻辑，我把它做成模板内置分支）。

# 代码风格要求（所有生成代码 + custom_code 注入内容都必须遵守）

1. **缩进**: 2 空格（不用 tab）；begin 与所属语句同行，end 单独一行
2. **命名**: 类/变量小写蛇形（`apb_master_driver`）；句柄加 `_h` 后缀、端口 `_p`；
   宏与参数全大写（`` `UVM_ERROR ``、`ADDR_WIDTH`）；枚举值全大写（`READ`）
3. **注释**: 中文注释；每个类头有职责说明；非显然逻辑必须注释「为什么」；
   协议时序逐拍注释（setup 拍 / access 拍 / 撤拍）
4. **UVM 约定**: 组件打印用 `uvm_info/error/fatal` 不用 `$display`；
   消息里带上下文（get_name() / get_type_name() + 关键值）
5. **禁止 magic number**: 用参数/宏/配置字段替代硬编码数字
6. **时序代码**: 全部通过时钟块（`vif.master_cb.xxx <= ...`）驱动/采样，不裸写信号
7. **pragma custom 区域内代码**同样遵守以上全部规则，且不重复定义模板已有的信号/成员
8. **简化禁止**: 不删除模板既有结构，不在槽位里复制整个 task（只写差异逻辑）

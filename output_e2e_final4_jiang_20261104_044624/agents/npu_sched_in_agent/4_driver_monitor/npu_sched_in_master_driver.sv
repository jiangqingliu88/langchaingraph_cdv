// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_in_master_driver.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Master Driver Callback: npu_sched_in_master_driver_cb
// ============================================================
// UVM callback 扩展点：测试可派生本类插入自己的行为（改激励、注入错误、
// 记录时序），**无需改动 driver 本体**。
//
// 注册（test 的 build_phase）：
//   npu_sched_in_master_driver_cb cb;
//   cb = npu_sched_in_master_driver_cb::type_id::create("cb");
//   uvm_callbacks#(npu_sched_in_master_driver,
//                  npu_sched_in_master_driver_cb)::add(drv, cb);
//
// 注：typedef class 是前置声明 —— callback 的方法签名要用到 driver 类型，
//     而 driver 定义在下方，SystemVerilog 要求先声明后使用。

typedef class npu_sched_in_master_driver;

class npu_sched_in_master_driver_cb extends uvm_callback;
  `uvm_object_utils(npu_sched_in_master_driver_cb)

  function new(string name = "npu_sched_in_master_driver_cb");
    super.new(name);
  endfunction

  // 驱动前：可修改 req 字段（地址边界、错误注入、延迟调整等）
  virtual task pre_drive(npu_sched_in_master_driver drv,
                         npu_sched_in_master_seq_item req);
  endtask

  // 驱动后：时序记录 / 协议检查
  virtual task post_drive(npu_sched_in_master_driver drv,
                          npu_sched_in_master_seq_item req);
  endtask
endclass : npu_sched_in_master_driver_cb

// ============================================================
// Master Driver: npu_sched_in_master_driver
// ============================================================

class npu_sched_in_master_driver extends uvm_driver #(npu_sched_in_master_seq_item);
  `uvm_component_utils(npu_sched_in_master_driver)
  // 建立 driver 类型 ↔ callback 类型的回调池（uvm_do_callbacks 依赖它）
  `uvm_register_cb(npu_sched_in_master_driver, npu_sched_in_master_driver_cb)

  virtual npu_sched_in_if vif;
  npu_sched_in_port_config cfg;
  // ── 「我发了什么」：驱动出去的事务 ──
  // loopback 自检的 expected 取这里（见 `<ag>_loopback_env.sv` 的 connect_phase）：
  // **driver 驱动出去的事务** vs slave monitor 在总线上看到的 actual，才是真正的闭环。
  // 取 master monitor 的话，loopback 里两个 agent 拿的是同一个接口实例
  //（见 `<ag>_loopback_tb.sv`），那就成了"同一个接口读两遍"，恒真。
  // 真实 env 里没有人接这个口，不产生任何影响。
  uvm_analysis_port #(npu_sched_in_master_seq_item) driven_ap;
  // pragma custom field_decl begin
  // pragma custom field_decl end

  function new(string name, uvm_component parent);
    super.new(name, parent);
    driven_ap = new("driven_ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual npu_sched_in_if)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")
    if (!uvm_config_db#(npu_sched_in_port_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")
    // pragma custom build_logic begin
    // pragma custom build_logic end
  endfunction

  // ⚠️ **刻意不写 `configure_phase` / `reset_phase`。**
  //
  // 驱动器**只在复位释放之后才驱动**，这是设计意图（见下面 main_phase 的
  // `wait (vif.rst_n == …)`）—— 复位期间 DUT 的输入是什么它不关心。
  //
  // 曾经在这里加过一个 `reset_phase` 去"提前压空闲值"，那**是错的**：
  // ① 它违背上面那条时序约定；② 用时钟块写时，值要等时钟事件才生效，
  // 实测落在复位释放后的**第一个沿**上 —— 与 DUT 采样那一拍**同拍**，
  // 谁先谁后取决于调度，等于把一处确定行为换成一处竞态；
  // ③ 想"立刻生效"改成直接 `vif.<sig> = '0;` 更糟：接口信号已被时钟块驱动，
  // 再叠一个直接赋值成两个驱动源，信号变成 **`z`**，比 X 更难查。
  //
  // 输入在复位期间是 X 本身没问题（DUT 那时在被复位）。真正要保证的是
  // **复位一释放就有人在驱动** —— 那件事由 `main_phase` 往下那段负责，
  // 而它能不能及时开始，取决于相位与复位释放的先后（见 `main_phase` 的注释）。

  task main_phase(uvm_phase phase);
    super.main_phase(phase);
    `uvm_info(get_type_name(), "main_phase: start", UVM_MEDIUM)
    // driver 的 forever 循环不 raise objection（避免悬挂）；复位门控后才开始驱动
    wait (vif.rst_n == 1'b1);
    forever begin
      npu_sched_in_master_seq_item req;
      seq_item_port.get_next_item(req);
      drive_transaction(req);
      // 广播「这一拍驱动了什么」——必须紧跟在 drive_transaction 之后：
      // 它是在**第二个** `@(vif.master_cb)` 之后返回的，也就是 slave monitor
      // 采到这一拍的那个边沿。SCB 按 `$time` 配对，所以这三者同拍。
      driven_ap.write(req);
      seq_item_port.item_done();
    end
  endtask

  virtual task drive_transaction(npu_sched_in_master_seq_item req);
    // 回调：驱动前（可改 req）
    `uvm_do_callbacks(npu_sched_in_master_driver, npu_sched_in_master_driver_cb,
                      pre_drive(this, req))
    // pragma custom drive_logic begin
    // === Default: 将 is_rand=True 且映射到 output 端口的字段单拍驱动 ===
    //
    // ⚠️ **必须先对齐到时钟沿再驱动**（下面这个 `@(vif.master_cb);` 不能省）：
    // 时钟块的 output 驱动**只在时钟事件上生效**。若进任务就立刻写，而进来的时刻
    // 落在沿与沿之间（sequence 刚 `start()` 时就是这样），这笔要等到下一个沿才上
    // 总线；偏偏本任务末尾那个 `@(vif.master_cb)` 也正好在那个沿返回 —— 于是下一笔
    // 驱动跟它**在同一时刻**覆盖掉它，**第一笔被吃掉**（实测 loopback 首笔：
    // driver 说发了 `paddr=cc`、slave monitor 总线上看到的是 `x`；此后每一笔都对）。
    @(vif.master_cb);
    repeat (cfg.drive_delay_max > 0 ? $urandom_range(cfg.drive_delay_min, cfg.drive_delay_max) : 0)
      @(vif.master_cb);
    vif.master_cb.instr_valid <= req.instr_valid;
    vif.master_cb.instr_opcode <= req.instr_opcode;
    vif.master_cb.instr_type <= req.instr_type;
    vif.master_cb.instr_dtype <= req.instr_dtype;
    vif.master_cb.instr_tile_id <= req.instr_tile_id;
    vif.master_cb.instr_src_addr <= req.instr_src_addr;
    vif.master_cb.instr_dst_addr <= req.instr_dst_addr;
    vif.master_cb.barrier_type <= req.barrier_type;
    vif.master_cb.op_priority <= req.op_priority;
    @(vif.master_cb);
    // pragma custom drive_logic end
    // 回调：驱动后
    `uvm_do_callbacks(npu_sched_in_master_driver, npu_sched_in_master_driver_cb,
                      post_drive(this, req))
  endtask
endclass : npu_sched_in_master_driver

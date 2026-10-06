// ════════════════════════════════════════════════════════════════
// apb_ral_pkg —— APB 寄存器模型（RAL）+ 总线适配器
//
// 与 `apb_slave_dut.sv` 的寄存器表**一一对应**，改一处必须改两处：
//
//   0x00 CTRL     RW  en[0] mode[3:1] div[15:8]     保留位 [15:9][31:16]
//   0x04 STATUS   RO  busy[0] err[1] state[7:4]
//   0x08 DATA     RW  [31:0]
//   0x0C SCRATCH  RW  [31:0]
//
// **保留位不建模**是刻意的：`uvm_reg_bit_bash_seq` 只翻**建模到的字段位**，
// 没建模的位它不碰（写别的字段时那几位写 0，DUT 存的也是 0，读回来一致）。
// 把它们硬建模成 RO 字段反而会让 bit_bash 去"验证"它们 —— 那是白费。
//
// 编译顺序：本包 `import apb_pkg::*`（要用 apb_master_seq_item），
// 所以必须排在 `apb_pkg` 之后。
// ════════════════════════════════════════════════════════════════

package apb_ral_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"
  // 注：**不 import apb_pkg**。适配器不在这里 —— 它归 agent
  //（`agents/<ag>/8_ral/<ag>_reg_adapter.sv`，由 interface 模板生成）。
  // 拆开的理由：适配器认识**总线**（seq_item 的字段名），寄存器模型认识**寄存器**。
  // 放一起的话两边都会各写一份，而它们一定漂移 —— 实测撞过一次：
  // agent 侧生成一个 `apb_reg_adapter`，RAL 里我另写一个，同名冲突。

  // ════════════════════════════════════════════════════════════
  // 寄存器定义
  // ════════════════════════════════════════════════════════════
  //
  // `uvm_reg_field::configure(父, 位宽, 起始位, access, volatile,
  //                           复位值, 有复位, 可随机, 可单独访问)
  //
  // 最后那个"可单独访问"一律 **0**：这些字段都与同寄存器的其它字段共享一个地址，
  // 写它们要连整字一起写（bit_bash 正是这么做的）。

  // ── 0x00 CTRL ──
  class apb_ctrl_reg extends uvm_reg;
    `uvm_object_utils(apb_ctrl_reg)

    rand uvm_reg_field en;        // [0]     使能
    rand uvm_reg_field mode;      // [3:1]   模式
    rand uvm_reg_field div;       // [15:8]  分频

    function new(string name = "apb_ctrl_reg");
      super.new(name, 32, UVM_NO_COVERAGE);
    endfunction

    virtual function void build();
      en = uvm_reg_field::type_id::create("en");
      en.configure(this, 1, 0, "RW", 0, 1'b0, 1, 1, 0);

      mode = uvm_reg_field::type_id::create("mode");
      mode.configure(this, 3, 1, "RW", 0, 3'b000, 1, 1, 0);

      div = uvm_reg_field::type_id::create("div");
      div.configure(this, 8, 8, "RW", 0, 8'h00, 1, 1, 0);
    endfunction
  endclass : apb_ctrl_reg

  // ── 0x04 STATUS（只读）──
  //
  // volatile=1：值是**硬件在动**的，模型不能假设"我写进去的就是读出来的"。
  // is_rand=0：只读字段不该被随机化。
  // 这两条设对，bit_bash 才会整块跳过它（而不是去翻它然后误报）。
  class apb_status_reg extends uvm_reg;
    `uvm_object_utils(apb_status_reg)

    uvm_reg_field busy;           // [0]
    uvm_reg_field err;            // [1]
    uvm_reg_field state;          // [7:4]

    function new(string name = "apb_status_reg");
      super.new(name, 32, UVM_NO_COVERAGE);
    endfunction

    virtual function void build();
      busy = uvm_reg_field::type_id::create("busy");
      busy.configure(this, 1, 0, "RO", 1, 1'b0, 1, 0, 0);

      err = uvm_reg_field::type_id::create("err");
      err.configure(this, 1, 1, "RO", 1, 1'b0, 1, 0, 0);

      state = uvm_reg_field::type_id::create("state");
      state.configure(this, 4, 4, "RO", 1, 4'h0, 1, 0, 0);
    endfunction
  endclass : apb_status_reg

  // ── 0x08 DATA ──
  class apb_data_reg extends uvm_reg;
    `uvm_object_utils(apb_data_reg)

    rand uvm_reg_field data;      // [31:0]

    function new(string name = "apb_data_reg");
      super.new(name, 32, UVM_NO_COVERAGE);
    endfunction

    virtual function void build();
      data = uvm_reg_field::type_id::create("data");
      data.configure(this, 32, 0, "RW", 0, 32'h0, 1, 1, 0);
    endfunction
  endclass : apb_data_reg

  // ── 0x0C SCRATCH ──
  class apb_scratch_reg extends uvm_reg;
    `uvm_object_utils(apb_scratch_reg)

    rand uvm_reg_field scratch;   // [31:0]

    function new(string name = "apb_scratch_reg");
      super.new(name, 32, UVM_NO_COVERAGE);
    endfunction

    virtual function void build();
      scratch = uvm_reg_field::type_id::create("scratch");
      scratch.configure(this, 32, 0, "RW", 0, 32'h0, 1, 1, 0);
    endfunction
  endclass : apb_scratch_reg

  // ════════════════════════════════════════════════════════════
  // 寄存器块 —— 地址映射
  // ════════════════════════════════════════════════════════════
  //
  // 注：这里**不调 `lock_model()`** —— 环境模板在 create 之后会调
  //（`{{ reg_block }}.build(); {{ reg_block }}.lock_model();`）。
  // 两边都调会重复锁，没必要。

  class apb_reg_block extends uvm_reg_block;
    `uvm_object_utils(apb_reg_block)

    rand apb_ctrl_reg    ctrl;
    rand apb_status_reg  status;
    rand apb_data_reg    data;
    rand apb_scratch_reg scratch;

    function new(string name = "apb_reg_block");
      super.new(name, UVM_NO_COVERAGE);
    endfunction

    virtual function void build();
      // create_map(名, 基地址, 每个地址占几字节, 端序)
      //   4 = 32 位总线一个字 4 字节；地址按字节偏移（0x00/0x04/0x08/0x0C）
      default_map = create_map("reg_map", 'h0, 4, UVM_LITTLE_ENDIAN);

      ctrl = apb_ctrl_reg::type_id::create("ctrl");
      ctrl.configure(this, null, "");
      ctrl.build();
      default_map.add_reg(ctrl, 'h00, "RW");

      status = apb_status_reg::type_id::create("status");
      status.configure(this, null, "");
      status.build();
      default_map.add_reg(status, 'h04, "RO");

      data = apb_data_reg::type_id::create("data");
      data.configure(this, null, "");
      data.build();
      default_map.add_reg(data, 'h08, "RW");

      scratch = apb_scratch_reg::type_id::create("scratch");
      scratch.configure(this, null, "");
      scratch.build();
      default_map.add_reg(scratch, 'h0C, "RW");
    endfunction
  endclass : apb_reg_block

  // ════════════════════════════════════════════════════════════
  // 适配器（`apb_reg_adapter`）**不在这里**
  // ════════════════════════════════════════════════════════════
  //
  // 它由 interface 模板生成在 `agents/apb_agent/8_ral/apb_reg_adapter.sv`，
  // 并随 `apb_pkg` 一起编译 —— env 里 `import apb_pkg::*` 就看得见。
  //
  // 这样分是因为**职责不同**：适配器认识**总线**（seq_item 的字段名、读写时序），
  // 寄存器模型认识**寄存器**（字段、地址、访问权限）。放一起两边都会各写一份，
  // 而它们必然漂移 —— 实测撞过一次：agent 侧生成一个、这里另写一个，同名冲突。

endpackage : apb_ral_pkg


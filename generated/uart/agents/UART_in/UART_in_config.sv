// ============================================================
// Config: UART_in_config
// ============================================================

class UART_in_config extends uvm_object;
  `uvm_object_utils(UART_in_config)

  rand uvm_active_passive_enum is_active = UVM_ACTIVE;

  // ─── 子组件开关 ───
  bit has_coverage         = 0;

  // ─── Sequencer 配置 ───
  int  max_pending         = 0;
  int  min_interval_ns     = 0;
  int  arbitration_mode    = 0;
  string default_sequence  = "";

  // ─── Driver 配置 ───
  int  drive_delay_min     = 0;
  int  drive_delay_max     = 0;
  int  max_retries         = 0;

  // ─── Monitor 配置 ───
  bit  check_xz            = 1;
  bit  filter_enabled      = 0;

  // ─── Scoreboard 配置 ───
  int  compare_mode        = 0;  // 0=InOrder 1=OutOfOrder 2=Window
  int  scb_window_size     = 10;
  int  scb_timeout_ns      = 100000;
  bit  scb_mask_enabled    = 0;

  // ─── Sequence 配置 ───
  bit  fatal_on_rand_fail   = 0;

  function new(string name = "UART_in_config");
    super.new(name);
  endfunction

endclass : UART_in_config
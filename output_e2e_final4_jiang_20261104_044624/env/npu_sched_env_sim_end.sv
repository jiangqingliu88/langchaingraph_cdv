// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_sim_end.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Simulation Auto-End: npu_sched_env_sim_end
// ============================================================
// 仿真自动结束组件（tb_top 不再内嵌仿真控制块，统一由此组件负责）：
//   1) 自动结束 —— run_phase 全部 objection 清零（phase_done）后，
//      等报告阶段完成再 $finish；+SIM_NO_AUTO_FINISH 可关闭
//   2) 看门狗   —— +SIM_WATCHDOG_NS=<n> 指定超时（ns），超时 UVM_FATAL 强制退出；
//      0 / 缺省 = 关闭（防悬挂序列挂死回归）
//   3) 本组件不 raise objection —— 只监控，不延长仿真

class npu_sched_env_sim_end extends uvm_component;
  `uvm_component_utils(npu_sched_env_sim_end)

  // 看门狗超时（ns；0 = 关闭）。
  //
  // **缺省给一个有限值**：留着 0（关闭）时，一条卡住的测试谁都不会去掐它 ——
  // UVM 只会在 9200 秒仿真时间的 PH_TIMEOUT 上收场，回归要挂几小时。
  // 实测：`dut_error_injection` 半夜卡了 11048 秒（3 小时），把闭环的
  // governor 预算耗光 → 直接被 BLOCK，**覆盖率阶段整段没跑**。
  // 100us（10 万 ns）对本工程的用例（跑完约 1.8us）宽裕三个数量级，
  // 真卡住时几十毫秒就 $fatal 出来。
  longint unsigned watchdog_ns = 100_000;
  // 报告阶段完成后自动 $finish
  bit auto_finish = 1;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    // **声明必须在语句之前**：SV 不允许在一个 begin/end 块里
    // 「先 super.build_phase() 再 longint wd = 0;」—— vlog 判
    // "Illegal declaration after the statement"。放到最上面。
    longint unsigned wd = 0;
    super.build_phase(phase);
    if ($value$plusargs("SIM_WATCHDOG_NS=%0d", wd) && wd > 0)
      watchdog_ns = wd;
    if ($test$plusargs("SIM_NO_AUTO_FINISH"))
      auto_finish = 0;
    `uvm_info(get_type_name(),
              $sformatf("watchdog_ns=%0d auto_finish=%0d", watchdog_ns, auto_finish),
              UVM_LOW)
  endfunction

  virtual task run_phase(uvm_phase phase);
    super.run_phase(phase);
    // 看门狗：到点还没结束就响亮地死，别让整条回归陪着挂。
    // `join_none` —— 这条 fork 不参与本任务的结束条件；仿真正常时由
    // report_phase 的 $finish 收尾，进程随仿真一起消失。
    fork
      begin
        #(watchdog_ns * 1ns);
        `uvm_fatal("SIM_WATCHDOG",
                   $sformatf("watchdog timeout: 仿真 %0d ns 内没有结束（疑似挂死）",
                             watchdog_ns))
      end
    join_none
  endtask

  virtual function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    if (auto_finish) begin
      `uvm_info(get_type_name(), "SIMULATION COMPLETE — $finish", UVM_NONE)
      $finish;
    end
  endfunction
endclass : npu_sched_env_sim_end

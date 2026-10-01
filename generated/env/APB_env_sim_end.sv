// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     APB_env_sim_end.sv
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Simulation Auto-End: APB_env_sim_end
// ============================================================
// 仿真自动结束组件（tb_top 不再内嵌仿真控制块，统一由此组件负责）：
//   1) 自动结束 —— run_phase 全部 objection 清零（phase_done）后，
//      等报告阶段完成再 $finish；+SIM_NO_AUTO_FINISH 可关闭
//   2) 看门狗   —— +SIM_WATCHDOG_NS=<n> 指定超时（ns），超时 UVM_FATAL 强制退出；
//      0 / 缺省 = 关闭（防悬挂序列挂死回归）
//   3) 本组件不 raise objection —— 只监控，不延长仿真

class APB_env_sim_end extends uvm_component;
  `uvm_component_utils(APB_env_sim_end)

  // 看门狗超时（ns；0 = 关闭）
  longint unsigned watchdog_ns = 0;
  // 报告阶段完成后自动 $finish
  bit auto_finish = 1;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    longint unsigned wd = 0;
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
    fork
      begin
        // ── 看门狗：超时强制结束 ──
        if (watchdog_ns > 0) begin
          #(watchdog_ns * 1ns);
          `uvm_fatal("SIM_WATCHDOG", $sformatf("watchdog timeout: %0d ns", watchdog_ns))
        end
      end
      begin
        // ── 自动结束检测：等 run_phase 真正结束（全部 objection 清零）──
        phase.phase_done.wait_for();
        `uvm_info(get_type_name(), "run_phase done (all objections dropped)", UVM_LOW)
      end
    join_any
    disable fork;
  endtask

  virtual function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    if (auto_finish) begin
      `uvm_info(get_type_name(), "SIMULATION COMPLETE — $finish", UVM_NONE)
      $finish;
    end
  endfunction
endclass : APB_env_sim_end

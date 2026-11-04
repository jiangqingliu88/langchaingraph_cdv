// ════════════════════════════════════════════════════════════════
// scb_pkg.sv —— 计分板组件族包（顶层组装文件）
// 职责: 按依赖顺序 include 各分片（.svh），对外仅暴露本 package；
//   filelist 只需编译本文件，分片经 +incdir 解析
// 分片:
//   common_pred.svh                     通用参考模型 / predictor 模板
//   in_order_scoreboard.svh             基座: 比较器接口 + 顺序计分板
//   out_of_order_scoreboard.svh         乱序计分板（按事务 ID 关联匹配）
// 注:
//   1. uvm_analysis_imp_decl(_expected) 在本 package 内声明，
//      与其它包 / $unit 的同名 imp 不冲突（各自独立命名空间）
//   2. 多通道 / 单类型便捷类 / 算法计分板分片已下线（无消费方），
//      需要时按下方示例手写子类扩展
// ════════════════════════════════════════════════════════════════

package scb_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // 依赖顺序: predictor → 基座(in_order) → 乱序
  // （各分片自带 include 守卫与依赖 include，顺序仅作显式声明）
  `include "common_pred.svh"
  `include "in_order_scoreboard.svh"
  `include "out_of_order_scoreboard.svh"

endpackage : scb_pkg

// ════════════════════════════════════════════════════════════════
// 在环境中使用计分板（示例；使用方先 import scb_pkg::*）
// ════════════════════════════════════════════════════════════════
// 1) 具名特化：参数化类无工厂注册，不能直接当 sb_type 用，
//    须手写一个具体子类（放在自有 VIP 包或生成代码的手改区域），
//    之后 YAML 里即可写 sb_type: apb_in_order_scb
//      class apb_in_order_scb extends in_order_scoreboard#(
//          apb_master_seq_item, apb_master_seq_item,
//          default_comparator#(apb_master_seq_item));
//        `uvm_component_utils(apb_in_order_scb)
//        function new(string name, uvm_component parent);
//          super.new(name, parent);
//        endfunction
//      endclass
//
// 2) 连接: monitor.analysis_port   → scb.actual_export
//          predictor.analysis_port → scb.expected_export
// ════════════════════════════════════════════════════════════════

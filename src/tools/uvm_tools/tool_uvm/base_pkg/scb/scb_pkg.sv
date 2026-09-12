// ════════════════════════════════════════════════════════════════
// scb_pkg.sv —— 计分板组件族包（顶层组装文件）
// 职责: 按依赖顺序 include 各分片（.svh），对外仅暴露本 package；
//   filelist 只需编译本文件，分片经 +incdir 解析
// 分片:
//   in_order_scoreboard.svh             基座: 比较器接口 + 顺序计分板
//   out_of_order_scoreboard.svh         乱序计分板（按事务 ID 关联匹配）
//   multich_in_order_scoreboard.svh     多通道顺序计分板
//   multich_out_of_order_scoreboard.svh 多通道乱序计分板
//   typed_scoreboard.svh                DEFINE_TYPED_SCOREBOARD 宏 + 单类型便捷类
//   algorithm_scoreboard.svh            算法计分板（内嵌参考模型，抽象类）
// 注:
//   1. uvm_analysis_imp_decl(_expected/_resp) 在本 package 内声明，
//      与其它包 / $unit 的同名 imp 不冲突（各自独立命名空间）
//   2. DEFINE_TYPED_SCOREBOARD 为预处理宏，编译单元内全局可见；
//      在其它包中展开前须先 import scb_pkg::*
// ════════════════════════════════════════════════════════════════

package scb_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // 依赖顺序: 基座(in_order) → 乱序 → 多通道顺序/乱序 → 特化宏 → 算法
  // （各分片自带 include 守卫与依赖 include，顺序仅作显式声明）
  `include "in_order_scoreboard.svh"
  `include "out_of_order_scoreboard.svh"
  `include "multich_in_order_scoreboard.svh"
  `include "multich_out_of_order_scoreboard.svh"
  `include "typed_scoreboard.svh"
  `include "algorithm_scoreboard.svh"

endpackage : scb_pkg

// ════════════════════════════════════════════════════════════════
// 在环境中使用计分板（示例；使用方先 import scb_pkg::*）
// ════════════════════════════════════════════════════════════════
// 1) 一行声明特化顺序计分板（工厂可注册）:
//      `DEFINE_TYPED_SCOREBOARD(apb_scb, apb_seq_item, apb_seq_item, default_comparator#(apb_seq_item))
//
// 2) 算法计分板（子类实现 predict 参考模型）:
//      class alu_algorithm_scb extends algorithm_scoreboard#(alu_seq_item, alu_seq_item);
//        `uvm_component_utils(alu_algorithm_scb)
//        function new(string name, uvm_component parent);
//          super.new(name, parent);
//        endfunction
//        virtual function alu_seq_item predict(alu_seq_item req);
//          alu_seq_item exp = alu_seq_item::type_id::create("exp");
//          exp.copy(req);
//          exp.result = req.a + req.b;
//          return exp;
//        endfunction
//      endclass
//
// 3) 连接: monitor.analysis_port   → scb.actual_export / channel_export[i]
//          predictor.analysis_port → scb.expected_export
// ════════════════════════════════════════════════════════════════

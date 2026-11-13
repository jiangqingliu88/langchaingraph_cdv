
// hm057 project common typedef
package common_typedefs_pkg;
// 端口类型（package 作用域声明：pkg 内各组件可直接引用 MASTER / SLAVE）
typedef enum bit { MASTER, SLAVE } port_kind_enum;
  // ── Slave 侧（响应侧）──
  // 响应模式
  typedef enum {READ, WRITE} xact_type_e;
typedef enum {AUTO_MEMORY, SEQUENCER_DRIVEN, ERROR_INJECTION} response_mode_e;
typedef enum {RESP_RANDOM=0, RESP_OKAY=1, RESP_ERROR=2, RESP_DECERR=3} resp_type_e;
//niccgen_inner_end===================
endpackage : common_typedefs_pkg

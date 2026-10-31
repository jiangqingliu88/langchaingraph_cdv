// Open NPU SoC v0.1 bare-metal 入口（E203 集成 seam）。
//
// v0.1 的 RTL 仿真用 `nice_cmd_sequencer` 驱动命令时序；这份 startup 是给
// 后续接入真实 E203 时准备的：设置栈、跳 main、异常自陷。
    .section .text.start
    .globl _start
_start:
    la      sp, _stack_top
    call    main
1:
    j       1b

    .section .bss
    .align  4
_stack:
    .space  4096
_stack_top:

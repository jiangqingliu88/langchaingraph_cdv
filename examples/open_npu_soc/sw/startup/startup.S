// Open NPU SoC v0.1 bare-metal 入口（E203 集成 seam）。
//
// v0.1 的 RTL 仿真用 `nice_cmd_sequencer` 驱动命令时序；这份 startup 是给
// 后续接入真实 E203 时准备的：设置栈、跳 main、异常自陷。
    .section .text.start
    .globl _start
_start:
    la      sp, _stack_top
    call    main
    // E203 自检 TB 的约定：x3=1 表示 PASS；跳到 0x80000086（tohost 标记）
    seqz    x3, a0
    li      t0, 0x80000086
    jr      t0
1:
    j       1b

    // TB 在 PC==0x80000086 时采样 x3；这里放一个自循环，
    // 让提交 PC 停在标记地址上（不是数据/非法指令）。
    .section .tohost, "ax"
    .globl tohost
tohost:
    j       tohost

    .section .bss
    .align  4
_stack:
    .space  4096
_stack_top:

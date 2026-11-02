/* E203 hbirdv2 的内存映射（ITCM 0x8000_0000 / DTCM 0x9000_0000）。
 * v0.1 的自定义固件只跑整数/GEMM 命令，不需要 libc。 */
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY {
  ITCM (rx) : ORIGIN = 0x80000000, LENGTH = 64K
  DTCM (rw) : ORIGIN = 0x90000000, LENGTH = 64K
}

SECTIONS {
  .text : {
    *(.text.start)
    /* E203 自检 TB 的 PC_WRITE_TOHOST 是 0x80000086 —— 固定放一个自循环
       标记；放在 main 之前，且 .text.start 只有十几字节，不会冲突。 */
    . = ORIGIN(ITCM) + 0x86;
    *(.tohost)
    *(.text*)
    *(.rodata*)
  } > ITCM

  .data : {
    *(.data*)
  } > DTCM AT > ITCM

  .bss (NOLOAD) : {
    *(.bss*)
    *(COMMON)
  } > DTCM

  _stack_top = ORIGIN(DTCM) + LENGTH(DTCM);
}

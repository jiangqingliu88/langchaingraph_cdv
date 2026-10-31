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

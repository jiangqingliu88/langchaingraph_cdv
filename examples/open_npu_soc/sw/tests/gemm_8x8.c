// Open NPU SoC M1 —— E203 NICE 驱动 INT8 GEMM。
//
// 命令编码（与 rtl/cpu/e203_nice_npu_adapter.sv 对齐）：
//   START : custom3, func3=2, func7=1, rs1=descriptor 地址
//   STATUS: custom3, func3=4, func7=1 -> bit0=done, bit1=irq
//   ACK   : custom3, func3=0, func7=1
//
// func3 的 bit1/bit2 就是 E203 的 rs1en/rdwen 控制位（instr[13]/[14]）：
// START 必须置 bit13 才会真正读 rs1；STATUS 必须置 bit14 才会写回 rd。
//
// descriptor = {a_addr, b_addr, c_addr, M, N, K}，6 个 32-bit 字。
// A/B 是 8x8 INT8（DTCM，按 4 字节打包），C 是 8x8 INT32。
//
// 这是裸机程序；不依赖 libc。`startup.S` 负责栈与 main。

#include <stdint.h>

#define M 8
#define N 8
#define K 8

static volatile int8_t  a[M][K];
static volatile int8_t  b[K][N];
static volatile int32_t c[M][N];
static volatile int32_t c_ref[M][N];
static volatile uint32_t desc[6];

static inline void nice_gemm(uint32_t desc_addr) {
    asm volatile(".insn r 0x7b, 2, 1, x0, %0, x0" :: "r"(desc_addr));
}

static inline uint32_t nice_status(void) {
    uint32_t value;
    asm volatile(".insn r 0x7b, 4, 1, %0, x0, x0" : "=r"(value));
    return value;
}

static inline void nice_ack(void) {
    asm volatile(".insn r 0x7b, 0, 1, x0, x0, x0");
}

static void golden(void) {
    for (int i = 0; i < M; i++)
        for (int j = 0; j < N; j++) {
            int32_t acc = 0;
            for (int k = 0; k < K; k++)
                acc += (int32_t)a[i][k] * (int32_t)b[k][j];
            c_ref[i][j] = acc;
        }
}

int main(void) {
    // 固定向量：与 Python golden 的 seed 语义一致（这里给一组小值）。
    for (int i = 0; i < M; i++)
        for (int k = 0; k < K; k++)
            a[i][k] = (int8_t)((i * K + k) % 13 - 6);
    for (int k = 0; k < K; k++)
        for (int j = 0; j < N; j++)
            b[k][j] = (int8_t)((k * N + j) % 11 - 5);

    desc[0] = (uint32_t)(uintptr_t)&a[0][0];
    desc[1] = (uint32_t)(uintptr_t)&b[0][0];
    desc[2] = (uint32_t)(uintptr_t)&c[0][0];
    desc[3] = M;
    desc[4] = N;
    desc[5] = K;

    nice_gemm((uint32_t)(uintptr_t)desc);
    // 有界轮询：正常路径几百拍内 done 置位；上限只是防止 RTL 握手回退时
    // 整条仿真挂死。真正的完成判据仍是下面的 golden 比对。
    for (volatile uint32_t spin = 0; spin < 100000u; spin++) {
        if (nice_status() & 1u) break;
    }
    nice_ack();

    golden();
    int fail = 0;
    for (int i = 0; i < M; i++)
        for (int j = 0; j < N; j++)
            if (c[i][j] != c_ref[i][j]) fail++;
    return fail == 0 ? 0 : 1;
}

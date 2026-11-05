#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "test_vv_v_add.h"

// ===========================================================
// 1. 测试用例配置宏 (基地址, 形状, 大小)
// ===========================================================
#define DIM0 16
#define DIM1 4
#define DIM2 1
#define TOTAL_ELEMENTS 64
#define TOTAL_BYTES 256

#define BASE_ADDR_IN0 0x00000000
#define BASE_ADDR_IN1 0x00004000
#define BASE_ADDR_OUT 0x00008000

#define FILL_PATTERN_IN0(idx) ((float)(idx) * 1.0f)
#define FILL_PATTERN_IN1(idx) ((float)(idx) * 2.0f)
#define EXPECTED_OUT(idx) (FILL_PATTERN_IN0(idx) + FILL_PATTERN_IN1(idx))

// ===========================================================
// 2. 仿真结束与结果返回机制 (非常重要!)
// ===========================================================
// 注意: 根据您的仿真环境，请将以下函数替换为对应的 TLM 写操作或系统宏。
// 例如: hal_sim_end(0) -> 0表示成功, 1表示失败。
// 或者: exit(0) / return 0;
static void simulation_end(int exit_code) {
    printf("\n========= TEST CASE test_vv_v_add =========\n");
    if (exit_code == 0) {
        printf("[TEST PASSED] Simulation finished successfully.\n");
    } else {
        printf("[TEST FAILED] Mismatch detected. Simulation finished with error.\n");
    }
    
    // =========== 在这里写入您的仿真结束寄存器 ===========
    // *(volatile uint32_t *)0x10000000 = (uint32_t)exit_code; 
    // 或者:
    // exit(exit_code); // 标准 C 退出
}

// ===========================================================
// 3. 辅助函数 (内存搬运与参考计算)
// ===========================================================
void hal_memcpy(void *dst, void *src, size_t n) {
    memcpy(dst, src, n);
}

void reference_vv_v_add(float* in0, float* in1, float* out, int count) {
    for (int i = 0; i < count; i++) {
        out[i] = in0[i] + in1[i];
    }
}

// ===========================================================
// 4. 核心测试用例执行函数 (调用 HAL 算子)
// ===========================================================
int run_test_vv_v_add_test(void) {
    printf("[INFO] Running HAL Test Case: test_vv_v_add\n");

    // 1. 分配内存并生成输入
    float host_in0[TOTAL_ELEMENTS];
    float host_in1[TOTAL_ELEMENTS];
    float host_golden[TOTAL_ELEMENTS];
    float host_output[TOTAL_ELEMENTS];

    for (int i = 0; i < TOTAL_ELEMENTS; i++) {
        host_in0[i] = FILL_PATTERN_IN0(i);
        host_in1[i] = FILL_PATTERN_IN1(i);
        host_golden[i] = EXPECTED_OUT(i);
        host_output[i] = 0.0f;
    }

    printf("  - Input Size: %d elements (Shape: %dx%dx%d)\n", 
           TOTAL_ELEMENTS, DIM0, DIM1, DIM2);

    // 2. 写数据到设备内存
    hal_memcpy((void*)BASE_ADDR_IN0, host_in0, TOTAL_BYTES);
    hal_memcpy((void*)BASE_ADDR_IN1, host_in1, TOTAL_BYTES);

    // 3. 调用硬件 HAL 算子
    printf("  - [TODO] Calling HAL Operator...\n");
    // hal_vv_v_add((void*)BASE_ADDR_IN0, (void*)BASE_ADDR_IN1, (void*)BASE_ADDR_OUT, DIM0, DIM1, DIM2, FP32);

    // 4. 读回设备输出
    hal_memcpy(host_output, (void*)BASE_ADDR_OUT, TOTAL_BYTES);

    // 5. 执行软件对比验证
    int fail_count = 0;
    for (int i = 0; i < TOTAL_ELEMENTS; i++) {
        if (host_golden[i] != host_output[i]) {
            printf("  [FAIL] Index %d: Golden=%.6f, Actual=%.6f\n", 
                   i, host_golden[i], host_output[i]);
            fail_count++;
        }
    }

    if (fail_count == 0) {
        printf("  [PASS] All %d elements match!\n", TOTAL_ELEMENTS);
        simulation_end(0); // 仿真成功
        return 0;
    } else {
        printf("  [FAIL] %d mismatches detected!\n", fail_count);
        simulation_end(1); // 仿真失败
        return 1;
    }
}

// ===========================================================
// 5. Main 主入口
// ===========================================================
int main() {
    return run_test_vv_v_add_test();
}

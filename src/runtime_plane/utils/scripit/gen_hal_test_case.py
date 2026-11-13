#!/usr/bin/env python3
import os

# ================== 用户配置区 ==================
CASE_NAME = "test_vv_v_add"
SHAPE = (16, 4, 1)  # (dim0, dim1, dim2)

DTYPE_C = "float" 
DTYPE_NAME = "FP32"
ELEM_SIZE = 4 

ADDR_INPUT0 = 0x00000000
ADDR_INPUT1 = 0x00004000
ADDR_OUTPUT  = 0x00008000

OUTPUT_DIR = "./hal_test_cases"
# ================================================

def generate_hal_test():
    total_elements = SHAPE[0] * SHAPE[1] * SHAPE[2]
    total_bytes = total_elements * ELEM_SIZE
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    c_file_path = os.path.join(OUTPUT_DIR, f"{CASE_NAME}.c")
    h_file_path = os.path.join(OUTPUT_DIR, f"{CASE_NAME}.h")

    with open(c_file_path, 'w') as f_c:
        f_c.write(f"""#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "{CASE_NAME}.h"

// ===========================================================
// 1. 测试用例配置宏 (基地址, 形状, 大小)
// ===========================================================
#define DIM0 {SHAPE[0]}
#define DIM1 {SHAPE[1]}
#define DIM2 {SHAPE[2]}
#define TOTAL_ELEMENTS {total_elements}
#define TOTAL_BYTES {total_bytes}

#define BASE_ADDR_IN0 0x{ADDR_INPUT0:08X}
#define BASE_ADDR_IN1 0x{ADDR_INPUT1:08X}
#define BASE_ADDR_OUT 0x{ADDR_OUTPUT:08X}

#define FILL_PATTERN_IN0(idx) ((float)(idx) * 1.0f)
#define FILL_PATTERN_IN1(idx) ((float)(idx) * 2.0f)
#define EXPECTED_OUT(idx) (FILL_PATTERN_IN0(idx) + FILL_PATTERN_IN1(idx))

// ===========================================================
// 2. 仿真结束与结果返回机制 (非常重要!)
// ===========================================================
// 注意: 根据您的仿真环境，请将以下函数替换为对应的 TLM 写操作或系统宏。
// 例如: hal_sim_end(0) -> 0表示成功, 1表示失败。
// 或者: exit(0) / return 0;
static void simulation_end(int exit_code) {{
    printf("\\n========= TEST CASE {CASE_NAME} =========\\n");
    if (exit_code == 0) {{
        printf("[TEST PASSED] Simulation finished successfully.\\n");
    }} else {{
        printf("[TEST FAILED] Mismatch detected. Simulation finished with error.\\n");
    }}
    
    // =========== 在这里写入您的仿真结束寄存器 ===========
    // *(volatile uint32_t *)0x10000000 = (uint32_t)exit_code; 
    // 或者:
    // exit(exit_code); // 标准 C 退出
}}

// ===========================================================
// 3. 辅助函数 (内存搬运与参考计算)
// ===========================================================
void hal_memcpy(void *dst, void *src, size_t n) {{
    memcpy(dst, src, n);
}}

void reference_vv_v_add({DTYPE_C}* in0, {DTYPE_C}* in1, {DTYPE_C}* out, int count) {{
    for (int i = 0; i < count; i++) {{
        out[i] = in0[i] + in1[i];
    }}
}}

// ===========================================================
// 4. 核心测试用例执行函数 (调用 HAL 算子)
// ===========================================================
int run_{CASE_NAME}_test(void) {{
    printf("[INFO] Running HAL Test Case: {CASE_NAME}\\n");

    // 1. 分配内存并生成输入
    {DTYPE_C} host_in0[TOTAL_ELEMENTS];
    {DTYPE_C} host_in1[TOTAL_ELEMENTS];
    {DTYPE_C} host_golden[TOTAL_ELEMENTS];
    {DTYPE_C} host_output[TOTAL_ELEMENTS];

    for (int i = 0; i < TOTAL_ELEMENTS; i++) {{
        host_in0[i] = FILL_PATTERN_IN0(i);
        host_in1[i] = FILL_PATTERN_IN1(i);
        host_golden[i] = EXPECTED_OUT(i);
        host_output[i] = 0.0f;
    }}

    printf("  - Input Size: %d elements (Shape: %dx%dx%d)\\n", 
           TOTAL_ELEMENTS, DIM0, DIM1, DIM2);

    // 2. 写数据到设备内存
    hal_memcpy((void*)BASE_ADDR_IN0, host_in0, TOTAL_BYTES);
    hal_memcpy((void*)BASE_ADDR_IN1, host_in1, TOTAL_BYTES);

    // 3. 调用硬件 HAL 算子
    printf("  - [TODO] Calling HAL Operator...\\n");
    // hal_vv_v_add((void*)BASE_ADDR_IN0, (void*)BASE_ADDR_IN1, (void*)BASE_ADDR_OUT, DIM0, DIM1, DIM2, {DTYPE_NAME});

    // 4. 读回设备输出
    hal_memcpy(host_output, (void*)BASE_ADDR_OUT, TOTAL_BYTES);

    // 5. 执行软件对比验证
    int fail_count = 0;
    for (int i = 0; i < TOTAL_ELEMENTS; i++) {{
        if (host_golden[i] != host_output[i]) {{
            printf("  [FAIL] Index %d: Golden=%.6f, Actual=%.6f\\n", 
                   i, host_golden[i], host_output[i]);
            fail_count++;
        }}
    }}

    if (fail_count == 0) {{
        printf("  [PASS] All %d elements match!\\n", TOTAL_ELEMENTS);
        simulation_end(0); // 仿真成功
        return 0;
    }} else {{
        printf("  [FAIL] %d mismatches detected!\\n", fail_count);
        simulation_end(1); // 仿真失败
        return 1;
    }}
}}

// ===========================================================
// 5. Main 主入口
// ===========================================================
int main() {{
    return run_{CASE_NAME}_test();
}}
""")

    # 写入头文件
    with open(h_file_path, 'w') as f_h:
        f_h.write(f"""#ifndef __{CASE_NAME.upper()}_H__
#define __{CASE_NAME.upper()}_H__

#ifdef __cplusplus
extern "C" {{
#endif

int run_{CASE_NAME}_test(void);

#ifdef __cplusplus
}}
#endif

#endif // __{CASE_NAME.upper()}_H__
""")

    print(f"✅ 已生成 C 测试用例:")
    print(f"   - 源文件: {c_file_path}")
    print(f"   - 头文件: {h_file_path}")
    print(f"\n   - Tensor 形状: {SHAPE}")
    print(f"   - 输入0基地址: 0x{ADDR_INPUT0:08X}")
    print(f"   - 输入1基地址: 0x{ADDR_INPUT1:08X}")
    print(f"   - 输出 基地址: 0x{ADDR_OUTPUT:08X}")
    print("\n核心提示: 请在生成的 .c 文件中，修改 `simulation_end` 函数内的写寄存器逻辑，适配您的仿真停止机制。")

if __name__ == "__main__":
    generate_hal_test()
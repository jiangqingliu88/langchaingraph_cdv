如果**没有对 GCC 做深度扩展**,无法直接使用那些“理想”的编程模型(比如声明式布局、近存计算原语),那就必须**退回到更底层、更手动的方式**来使用存算一体硬件。但这不代表硬件不能用,只是意味着**所有的“智能”都要从编译器/语言层,转移到库、运行时或手写汇编中**。

以下是几种在实践中绕过编译器限制的可行方案,按从“最痛苦”到“相对优雅”排序:

---

### 方案一:手写内联汇编 + 自定义指令(最底层,完全手动)

如果芯片基于 RISC-V 扩展了自定义指令(例如 `near_mem_matmul`、`stripe_load`),但 GCC 不加修改不认识,那么你可以**在 C 代码中直接插入内联汇编**来调用它们。

```c
// 假设硬件定义了一个自定义指令：near_mem_matmul
// 该指令操作码为 0x0B (custom0), 功能码 0x7
// 格式：near_mem_matmul rd, rs1, rs2
// 其中 rs1 指向 A 矩阵本地基址，rs2 指向 B 矩阵本地基址，rd 接收结果指针

#define NEAR_MEM_MATMUL(rd, rs1, rs2) \
    __asm__ volatile (".word (0x0B << 2 | 0x7) \n\t" \
                      : "=r"(rd) : "r"(rs1), "r"(rs2))

// 使用
void* A_local = get_channel_base_addr(0);
void* B_local = get_channel_base_addr(4);
void* C_local;

NEAR_MEM_MATMUL(C_local, A_local, B_local);
```

**代价**：需要你**手动管理所有通道的地址、同步、数据分块**,相当于用汇编思维写应用代码,可维护性极低,但硬件能跑通。

---

### 方案二:纯运行时库封装(最常用,工业界主流)

既然编译器不动,那就**让链接器和运行时库来担当重任**。芯片厂商通常提供一套**硬件抽象层(HAL)或运行时库**,用标准 C 函数封装硬件操作。你通过调用这些 API,间接完成内存映射、通道分配和算子调用。

```c
#include "chip_hal.h"  // 厂商提供的硬件抽象层

void vector_add(int n) {
    // 1. 通过运行时 API 申请条带化的分布式内存
    mem_handle_t A = hal_alloc_dist(n * sizeof(float), LAYOUT_STRIPED, CHANNEL_ALL);
    mem_handle_t B = hal_alloc_dist(n * sizeof(float), LAYOUT_STRIPED, CHANNEL_ALL);
    mem_handle_t C = hal_alloc_dist(n * sizeof(float), LAYOUT_STRIPED, CHANNEL_ALL);

    // 2. 对于每个通道，获取本地指针
    for (int ch = 0; ch < 8; ch++) {
        float* A_ch = (float*)hal_get_local_addr(A, ch);
        float* B_ch = (float*)hal_get_local_addr(B, ch);
        float* C_ch = (float*)hal_get_local_addr(C, ch);

        // 3. 调用运行时函数，在当前通道的近存单元上启动计算
        //    内核本身仍是标准 C 循环（由 GCC 编译），但被运行时“分发”到通道
        hal_near_mem_execute(ch, [=]() {
            int local_n = hal_get_local_size(A, ch);
            for (int i = 0; i < local_n; i++) {
                C_ch[i] = A_ch[i] + B_ch[i];
            }
        });
    }

    // 4. 运行时内部维护一个全局句柄，可通过 hal_get_global_view 获取统一视图
}
```

**本质**：
- GCC 仍然只编译出**标准 RISC-V 指令**,不感知任何存算一体特性。
- `hal_near_mem_execute` 内部可能通过**写特定内存映射寄存器(MMIO)**来触发通道控制器,让它将这段代码的指令序列转换为本地执行。
- 运行时库负责**地址映射、通道选择、同步栅栏**。

**这是目前绝大多数商用存内计算/PIM 芯片的真实使用方式。** 编译器无感,硬件通过运行时库暴露能力。

---

### 方案三:修改 LLVM/MLIR,做领域专用编译器(对硬件最友好)

如果 GCC 难以扩展,可以用 **MLIR (Multi-Level Intermediate Representation)** 这种更现代的编译框架,为你的存算一体芯片**自定义一个方言(Dialect)**,并在编译流程中插入硬件感知的优化 Pass。

这避开了直接修改 GCC 的复杂性,但需要构建新的编译流程:

```python
// 伪代码：在 MLIR 中定义 “近存计算” 方言
func.func @matmul(%A: tensor<1024x1024xf16, layout=striped_rows>,
                  %B: tensor<1024x1024xf16, layout=striped_cols>)
    -> tensor<1024x1024xf16>
{
  // "cim.near_mem_matmul" 是自定义操作
  %C = cim.near_mem_matmul %A, %B {tile_size = 64}
       : tensor<...> -> tensor<...>
  return %C
}
```

之后,在 MLIR 的 Lowering 阶段,这个 `cim.near_mem_matmul` 操作会被分解为:
1.  为每个通道生成一个独立的函数(用标准 RISC-V 指令)。
2.  插入通道间通信的同步原语。
3.  最终输出一个可链接的目标文件。

但这条路需要深厚的编译器团队支撑,适合芯片自研厂商,不太适合应用开发者直接使用。

---

### 方案四:固件态的通道管理(把复杂留给固件)

如果你连运行时库都很难改,还有一个更“土”但有效的办法:**把复杂的分布式管理和调度逻辑写进一个运行在芯片上的固件**,也就是一个小型操作系统内核。

-   应用程序通过标准系统调用(如 `write`)或共享内存请求固件服务。
-   固件负责解析请求、分配通道、生成通道级任务、收集结果。
-   应用只需链接一个轻量客户端库,发送命令即可。

这在很多嵌入式异构芯片(包括一些 NPU)中十分普遍。开发应用时你根本感觉不到底层是 3D 堆叠,因为固件把复杂性全吞了。

---

### 总结:没有编译器扩展的现实路径

-   **短期/实用主义**:**用厂商提供的运行时库**。GCC 保持原样,所有硬件特性通过标准 C 函数调用和 MMIO 来激活,这是目前产业界的通行做法。
-   **长期/自研**:**构建基于 MLIR 的领域专用编译栈**,逐步脱离对 GCC 扩展的依赖,形成自己的编译生态。
-   **最坏情况(原型验证)**:手写内联汇编和内存映射,让硬件先跑起来,代码细节完全暴露。

**核心结论**:即使没有修改 GCC,**只要硬件提供了可通过软件(如 MMIO、自定义指令)访问的控制接口,就能用标准 C + 运行时库来驾驭它**。真正的挑战是运行时库的封装是否足够优雅,是否能把“分布式存算”的威力以最小心智负担交给开发者。
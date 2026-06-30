[HM056]-CDD-MPU

## 版本更新记录

| 版本 | 日期 | 修改人 | 备注 |
|------|------|--------|------|
| V0.1 | 2025/10/01 | 杨xxx | 发布初版 |
| V0.2 | 2025/10/13 | 杨皓然 | 修改接口列表 |
| V0.3 | 2025/10/14 | 杨皓然 | 修改接口列表、低功耗描述和新增支持数据精度格式 |
| V0.4 | 2025/10/15 | 杨皓然 | 新增反压处理描述 |
| V0.5 | 2025/10/16 | 杨皓然 | 新增接口时序和MPU_CIMC存储地址映射关系，修改精度支持表格（细分） |
| V0.6 | 2025/10/24 | 杨皓然 | 修改Activaiton输入接口支持MX-INT4格式数据 |
| V0.7 | 2026/01/04 | 杨皓然 | 修改部分数据通路细节适配最新架构和修改接口 |
| V0.8 | 2026/02/05 | 杨皓然 | 重新撰写模块整体定位 |
| V0.9 | 2026/02/21 | 杨皓然 | 新增算法介绍、数据流场景，重构架构设计、接口设计 |


## 1. 术语描述

| 缩写 | 术语 | 描述 |
|------|------|------|
| MPU | Matrix Processing Unit | NPU子模块，矩阵运算单元 |
| SPAD | Scratchpad | Local Memory中的一部分，与CIM共同组成NPU中的Local Memory |
| CIMM | CIM Macro | CIM硬件宏单元 |
| CIME | CIM Engine | CIM被调用的最小粒度单元，由多个CIMM组成 |
| CIMC | CIM Cluster | 由多个CIME组成的核心计算部件，存储部分作为Local Memory中的一部分存在 |


2. 规格介绍


MPU Summary

Technology

TSMC 22NM ULL

Bitcell Type

6T (logic rule)

Temperature

0-75°C

SRAM Density

1.254Mb/mm²

Supply Voltage

0.6-0.9V

Frequency

500MHz

MPU Area


MPU Power


Power Region


Low Power


### 2.1 MPU内部规格

| MPU规格 | 数量 |
|---------|------|
| MPU 单次可执行算子数 | 1 |
| MPU 内部计算模块数量（CIMM） | 8 |
| 软件可调用 MPU 内部的最小单元数量（CIME） | 4 |
| MPU 读通道数量 | 2 |
| MPU 读通道位宽 | 512bit |
| MPU 写通道数量 | 1 |
| MPU 写通道位宽 | 512bit |
| MPU 存储通道数量 | 1 |
| MPU 存储通道位宽 | 512bit |
| MPU 存储空间容量（单页） | 软件可见地址容量：8KB  软件不可见地址容量：0.25KB |
| MPU 存储空间总容量 | 软件可见地址容量：128KB  软件不可见地址容量：4KB |
| NPU内存储空间相对地址 | 0x0004_0000 ~ 0x0005_FFFF |


## 3. 模块总体定位

MPU在NPU子系统中主要承担矩阵计算加速的任务，在NPU中负责保证算力密度。从模块结构上看，MPU的计算能力来自内部的CIMM模块，同时作为权重矩阵的存储模块，在NPU中承担部分存储任务。在模块交互上，MPU在配置端口与COMMAND SCHEDULAR交互，接收来自COMMAND SHCEDULAR下发的任务配置；MPU在计算模式的读写端口上与XBAR交互，从SPAD中读取数据送入MPU进行计算，计算结果再送入SPAD；MPU在存储端口与SPAD_MPU（协议桥）交互，MPU在此刻作为SLAVE接收MASTER下发的读写请求并返回对应的响应。


## 4. 算法介绍

### 4.1 算法实现

MPU主要完成 1. 矩阵乘加  2.矩阵乘加后与另外一个矩阵完成累加 这两项操作。

矩阵乘加介绍：

MatrixA：输入矩阵（左矩阵）

MatrixB：权重矩阵（右矩阵）

MatrixC：输出矩阵（结果矩阵）


矩阵乘加+累加介绍：

MatrixA：输入矩阵（左矩阵）

MatrixB：权重矩阵（右矩阵）

MatrixC：部分和矩阵（累加矩阵）

MatrixD：输出矩阵（结果矩阵）


### 4.2 精度支持


精度

INT4

INT8

INT16

INT32

MX-INT8

FP8(E5M2)

FP8(E4M3)

FP16

BF16

FP32

INPUT(ACTIVATION)


√

√


√

√

√

√

√


WEIGHT

√

√

√


√

√

√

√

√


PSUM


√


√

OUTPUT


√


√


### 4.3 浮点精度介绍


FP8E4M3

FP8E5M2

FP16

BF16

FP32

Exponent bias

7

15

15

127

127

Infinities

不存在

S 11111 00

S 11111 00_0000_0000

S 1111_1111 000_0000

S 1111_1111 000_0000_0000_0000_0000_0000

NaN

S 1111 111

S 11111 {01，10，11}

S 11111 mantissa!= 0

S 1111_1111 mantissa!= 0

S 1111_1111 mantissa!= 0

Zeros

S 0000 000

S 00000 00

S 00000 00_0000_0000

S 0000_0000 000_0000

S 0000_0000 000_0000_0000_0000_0000_0000

Max normal

S 1111 110

S 11110 11

S 11110 11_1111_1111

S 1111_1110 111_1111

S 1111_1110 111_1111_1111_1111_1111_1111

Min normal

S 0001 000

S 00001 00

S 00001 00_0000_0000

S 0000_0001 000_0000

S 0000_0001 000_0000_0000_0000_0000_0000

Max subnormal

S 0000 111

S 00000 11

S 00000 11_1111_1111

S 0000_0000 111_1111

S 0000_0000 111_1111_1111_1111_1111_1111

Min subnormal

S 0000 001

S 00000 01

S 00000 00_0000_0001

S 0000_0000 000_0001

S 0000_0000 000_0000_0000_0000_0000_0001


### 4.4 支持计算类型

根据大模型的特性，MPU将对以下的组合进行全力支持并且充分验证，对于剩余的组合进行支持但不保证计算准确度与性能。


组合

INPUT(ACTIVATION)

WEIGHT

PSUM

OUTPUT

组合一

INT8

INT4

无 / INT32

INT32

组合二

INT8

INT8

无 / INT32

INT32

组合三

FP16

FP16

无 / FP32

FP32

组合四

BF16

BF16

无 / FP32

FP32

组合五

FP8

FP8

无 / FP32

FP32

组合六

BF16

FP16

无 / FP32

FP32

组合七

FP16

BF16

无 / FP32

FP32

组合八

FP16

INT4

无 / FP32

FP32

组合九

BF16

INT4

无 / FP32

FP32

组合十

FP16

INT8

无 / FP32

FP32

组合十一

BF16

INT8

无 / FP32

FP32

组合十二

INT8

FP16

无 / FP32

FP32

组合十三

INT8

BF16

无 / FP32

FP32

组合十四

MX-INT8

MX-INT8

无 / FP32

FP32

组合十五

FP16

MX-INT8

无 / FP32

FP32

组合十六

BF16

MX-INT8

无 / FP32

FP32

组合十七

FP8

MX-INT8

无 / FP32

FP32


### 4.5 支持算子

MPU支持的算子如下：

Switch Pattern算子：该算子用于调整存储时权重在MPU内8个CIMM内的形状。支持按照CIME为最小粒度的2X2形状（PATTERN2），支持按照CIME为最小粒度的1X4形状（PATTERN3）。


两种模式下支持的权重形状细节：


GEMM算子：该算子是矩阵乘加算子，将左矩阵从SPAD读入，将右矩阵从CIMM中载入，完成计算后将计算结果矩阵送入SPAD。支持矢量乘矩阵和矩阵乘矩阵。

### 4.6 计算特性


输入

权重

部分和

输出

备注

INF/NaN

Dont Care

Dont Care

Dont Care

输入为INF或者NaN时，会上报中断结束该算子，无结果

Dont Care

INF/NaN

Dont Care

Dont Care

当权重为INF或NaN时，GLSU或LLSU会上报中断结束算子确保存入CIMM中的数据非NaN或INF

Dont Care

Dont Care

INF/NaN

Dont Care

部分和为INF或者NaN时，会上报中断结束该算子，无结果


计算过程中出现特殊值加法

累加过程中特殊场景

-INF+INF

根据IEEE 754协议，该场景计算结果为NaN

-INF+0

根据IEEE 754协议，该场景计算结果为-INF

INF+0

根据IEEE 754协议，该场景计算结果为INF

-0+0

根据IEEE 754协议，该场景计算结果为0

输出前结果为-0

根据IEEE 754协议，该场景计算结果会从-0调整为0


### 4.7 NPU数据精度编码


Precision

MX Enable Flag

Type code

Float Mantissa Config

Width code

Description

INT4

0

0: 'INT'

0

010: '4'

4位有符号整数

INT8

0

0: 'INT'

0

011: '8'

8位有符号整数

INT16

0

0: 'INT'

0

100: '16'

16位有符号整数

INT32

0

0: 'INT'

0

101: '32'

32位有符号整数

FP4(E2M1)

0

1: 'FP'

0

010: '4'

1位符号 + 2位指数 + 1位尾数

FP4(E1M2)

0

1: 'FP'

1

010: '4'

1位符号 + 1位指数 + 2位尾数

FP8(E5M2)

0

1: 'FP'

0

011: '8'

1位符号 + 5位指数 + 2位尾数

FP8(E4M3)

0

1: 'FP'

1

011: '8'

1位符号 + 4位指数 + 3位尾数

FP16

0

1: 'FP'

0

100: '16'

1位符号 + 5位指数 + 11位尾数

BF16

0

1: 'FP'

1

100: '16'

1位符号 + 8位指数 + 7位尾数

FP32

0

1: 'FP'

0

101: '32'

1位符号 + 8位指数 + 23位尾数

MX-INT4

1

0: 'INT'

0

010: '4'

MX INT4

MX-FP4(E2M1)

1

1: 'FP'

0

010: '4'

MX FP4，其中FP4 = 1位符号 + 2位指数 + 1位尾数

MX-FP4(E1M2)

1

1: 'FP'

1

010: '4'

MX FP4，其中FP4 = 1位符号 + 1位指数 + 2位尾数

MX-INT8

1

0: 'INT'

0

011: '8'

MX INT8

MX-FP8(E5M2)

1

1: 'FP'

0

011: '8'

MX FP8 其中FP8 = 1位符号 + 5位指数 + 2位尾数

MX-FP8(E4M3)

1

1: 'FP'

1

011: '8'

MX FP8 其中FP8 = 1位符号 + 4位指数 + 3位尾数

MX-INT16

1

0: 'INT'

0

100: '16'

MX-INT16

MX-FP16

1

1: 'FP'

0

100: '16'

MX-FP16 其中FP16 = 1位符号 + 5位指数 + 11位尾数

MX-BF16

1

1: 'FP'

1

100: '16'

MX-BF16 其中BF16 =1位符号 + 8位指数 + 7位尾数


## 5. 数据流场景

### 5.1 总体数据流

MPU模块在NPU子系统内部的交互上一共分成四类数据流：

红色通路：该通路与COMMAND SCHEDULAR交互，COMMAND SCHEDULAR会给MPU下发算子任务，MPU做完算子后返回结束响应。

紫色通路：该通路与NPU CORE REG交互，NPU CORE REG中的MPU相关配置寄存器直连MPU，MPU的异常信号也和NPU CORE REG相连。

绿色通路：该通路与SPAD MPU(协议桥)交互，在把MPU当成存储去使用的时候，NIU/GLSU/LLSU对MPU的权重数据进行存取。

橙色通路：该通路与XBAR交互，MPU在计算模式下，读写通道通过XBAR将SPAD中的输入数据载入MPU，将计算结果通过XBAR存入MPU。


### 5.2 内部算法数据流

#### 5.2.1 MPU算法思想

因为MPU内部是通过CIM进行具体的乘累加运算，当前使用CIM为INT类型CIM，CIM内部只能进行INT类型计算，FP数据均为外围浮点电路实现，所以算法整体要适配CIM行为。CIM对数据的要求如下：

存储数据时，每一个page的0-31行存储INT型数据，第32行存储权重对齐后找到的最大指数；

计算数据时，输入通道每个CHANNEL只能输入INT类型数据进行乘累加运算；

单CIM每次计算通道数是32CHANNEL，因此每次输入元素的最小粒度是32个为一组的元素；

基于上述思想，MPU在拿到FP类型的输入数据后会先按照32个元素为一组的粒度进行对齐，对齐完成后将INT数据送入CIM进行计算、将EXP数据送入FP外围浮点电路进行计算，计算完成同步后，多个CIMM之间进行累加时也会根据相加的CIMM的最大指数进行比较，将较小的EXP对应的INT数据右移后与另外一个INT相加，最后送入格式转换模块将数据转换成FP32。在这一整套算法流程中始终保持一个思想，浮点数转成INT+EXP后，后续无论INT怎么计算，小数点始终放在最高位开始2bit后。[SIGN, HIDDEN_BIT, MANTISSA]，SIGN 1bit，HIDDEN_BIT 1bit，小数点在HIDDEN_BIT后。具体算法细节会在子模块章节中在对应模块进行介绍。

#### 5.2.2 输入INT、权重INT 算法数据流


#### 5.2.3 输入INT、权重FP 算法数据流


#### 5.2.4 输入FP、权重INT 算法数据流


#### 5.2.5 输入FP、权重FP 算法数据流


#### 5.2.6 输入MX、权重MX 算法数据流


#### 5.2.7 输入FP、权重MX 算法数据流


#### 5.2.8 不同数据精度对应场景分析

当输入数据精度为8时，FP8/INT8场景下，SPAD带宽512bit，一次可以取回512/8=64个元素，对应一个完整的CIME，因此，如果数据精度为8时，此时有效数据会占据1-4个完整的CIME，不会出现CIME中存在无效数据的情况。

当输入数据精度为16时，FP16/BF16/INT16场景下，SPAD带宽512bit，一次可以取回512/16=32个元素，对应半个完整的CIME，因此，如果数据精度为16时，此时有效数据会占据1-4个完整的CIME，会出现CIME中未使用满全部通道的场景，在这些场景下，会给CIME的输入通道补足一个完整的64个元素，无效数据部分会填零。

一个CIME的位宽固定为256bit，当权重精度为4时，INT4场景下，256/4=64个元素，此时一个CIME中的一行存储了64个有效元素；当权重精度为8时，FP8/INT8场景下，256/8=32个元素，此时一个CIME中的一行存储了32个有效元素；当权重精度为16时，FP16/BF16/INT16场景下，256/16=16个元素，此时一个CIME中的一行存储了16个有效元素。

软件约束：在PATTERN2场景下，一列有效数据中不存在使用96个有效元素的场景。

## 6. 架构设计

从MPU的算法数据流来看主要MPU主要有四大步骤，取数预处理->计算->后处理->存数。按照数据流分解流水设计思路，MPU做如下规划：

MPU拥有一个MPU_CTRL，用于控制整体配置解析分发和状态管理。

MPU拥有一个MPU_RD_CHANNEL，用于读取Input Activation、Psum和MX Shared EXP，同时进行输入数据的预处理与送入CIMM前的数据排布。

MPU拥有一个MPU_CIMC，用于完成Weigth的存储和矩阵计算。

MPU拥有一个MPU_POST_PROCESS，用于完成矩阵计算累加和后处理以及送出数据前的数据排布。

MPU拥有一个MPU_WR_CHANNEL，用于写出计算结果或PSUM。


### 6.1 MPU使用流程


### 6.2 MPU算子依赖


## 7. 接口设计

7.1 参数与接口定义

Parameters


Type

Name

Default

Descriptions

MPU_CFG

P_ADDR_WIDTH

32

地址总线位宽


P_DIM0_WIDTH

14

维度0位宽


P_DIM1_WIDTH

13

维度1位宽


P_IO_DATA_WIDTH

512

输入输出数据位宽

MPU_RD_PATH

P_RD_CHL_NUM

64

读通道数量


P_RD_CHL_WIDTH

16

读通道位宽


P_RD1_OUT_NUM

4

读1输出数量

MPU_FIFO

P_FIFO_DEPTH

2

FIFO深度

CIM_INTERFACE

P_CIMC_ADDR_WIDTH

13

CIMC地址位宽


P_RD_CIM_GRP_NUM

4

读CIME组数量


P_CIME_IN_WIDTH

1024

CIME输入数据位宽

MPU_POST

P_POST_IN1_WIDTH

2432

后处理输入1数据位宽


P_POST_IN2_WIDTH

512

后处理输入2数据位宽


P_POST_GRP_NUM

16

后处理组数量


接口定义


信号类型

信号名称

方向

位宽

信号种类

信号含义

时钟

compute_clk

Input

1

脉冲

时钟，频率：500MHz@T22，计算域时钟

storage_clk

Input

1

脉冲

时钟，频率：500MHz@T22，存储域时钟

rst_n

Input

1

电平

异步复位，低复位有效

配置地址

cmd_mpu_cfg_base_out

Input

32

电平

计算输出基地址

cmd_mpu_cfg_base_in

Input

32

电平

计算输入基地址

cmd_mpu_cfg_base_orig

Input

32

电平

原始向量基地址（PSUM）

cmd_mpu_cfg_base_wt

Input

32

电平

输入权重基地址

cmd_mpu_cfg_base_mx

Input

32

电平

共享指数基地址

其余配置

cmd_mpu_cfg_mx_out

Input

1

电平

输出数据MX数据格式使能（目前输出数据不支持MX格式）

cmd_mpu_cfg_mx_orig

Input

1

电平

原始向量MX数据格式使能（目前原始向量不支持MX格式）

cmd_mpu_cfg_mx_in

Input

1

电平

输入数据MX数据格式使能

cmd_mpu_cfg_mx_wt

Input

1

电平

权重数据MX数据格式使能

cmd_mpu_cfg_type_out

Input

1

电平

输出数据类型：0：INT；1：FP；

cmd_mpu_cfg_type_orig

Input

1

电平

原始向量类型：0：INT；1：FP；

cmd_mpu_cfg_type_in

Input

1

电平

输入数据类型：0：INT；1：FP；

cmd_mpu_cfg_type_wt

Input

1

电平

权重数据类型：0：INT；1：FP；

cmd_mpu_cfg_manti_out

Input

1

电平

输出数据特殊尾数使能：0：正常；1：特殊；

cmd_mpu_cfg_manti_orig

Input

1

电平

原始向量特殊尾数使能：0：正常；1：特殊；

cmd_mpu_cfg_manti_in

Input

1

电平

输入数据尾数使能：0：正常；1：特殊；

cmd_mpu_cfg_manti_wt

Input

1

电平

权重数据特殊尾数使能：0：正常；1：特殊；

cmd_mpu_cfg_width_out

Input

3

电平

输出数据位宽：010:4；011:8；100:16；101:32；

cmd_mpu_cfg_width_orig

Input

3

电平

原始向量位宽：010:4；011:8；100:16；101:32；

cmd_mpu_cfg_width_in

Input

3

电平

输入数据位宽：010:4；011:8；100:16；101:32；

cmd_mpu_cfg_width_wt

Input

3

电平

权重数据位宽：010:4；011:8；100:16；101:32；

cmd_mpu_cfg_cim_pattern

Input

3

电平

使用CIME的Pattern：010：Pattern1(2*2)；100：Pattern2(1*4)

cmd_mpu_cfg_acc_en

Input

1

电平

PSUM累加使能

cmd_mpu_cfg_mx_size

Input

32

电平

MX EXP共享通道数：

1：32CHANNEL；

2：64CHANNEL；

3：128CHANNEL；

cmd_mpu_cfg_task_select

Input

2

电平

选择任务配置：00(默认)  01(SWITCH PATTERN)  11(GEMM)

cmd_mpu_cfg_decode_stage_en

Input

1

电平

指示处于Decode阶段使能信号（但不使用）

cmd_mpu_cfg_size_dim0_out

Input

14

电平

输出数据一维搬移次数（元素个数*精度/256）

cmd_mpu_cfg_rem_dim0_out

Input

6

电平

暂不使用

cmd_mpu_cfg_size_dim1_out

Input

13

电平

输出数据二维搬移次数

cmd_mpu_cfg_stride_dim1_out

Input

13

电平

输出数据二维搬移步长

cmd_mpu_cfg_size_dim0_in

Input

14

电平

输入数据一维搬移次数

cmd_mpu_cfg_rem_dim0_in

Input

6

电平

暂不使用

cmd_mpu_cfg_size_dim1_in

Input

13

电平

输入数据二维搬移次数

cmd_mpu_cfg_stride_dim1_in

Input

13

电平

输入数据二维搬移步长

配置FLAG

cmd_mpu_start

Input

1

脉冲

配置有效指示

mpu_cmd_done_lclrd

Output

1

脉冲

CIM Macro ren_loacl结束指示

mpu_cmd_done

Output

1

脉冲

算子计算完成指示

写通道

wr_xbar_req_addr

Output

32

脉冲

写请求通道地址

wr_xbar_req_data

Output

512

脉冲

写请求通道数据

wr_xbar_req_flag

Output

1

脉冲

LAST信号，强制要求SLAVE端回响应

wr_xbar_req_strobe

Output

2

脉冲

指示写入SPAD粒度和有效位，

2’b01：低256bit有效；

2‘b10：高256bit有效；

2’b11：512bit有效

wr_xbar_req_vld

Output

1

脉冲

写请求通道valid

wr_xbar_req_rdy

Input

1

脉冲

写请求通道ready

wr_xbar_rsp_vld

Input

1

脉冲

写响应通道valid

wr_xbar_rsp_rdy

Output

1

脉冲

写响应通道ready

读通道0

mpu_xbr_rd0_req_addr

Output

32

脉冲

读请求通道0 地址

mpu_xbr_rd0_req_vld

Output

1

脉冲

读请求通道0 valid

xbr_mpu_rd0_req_rdy

Input

1

脉冲

读请求通道0 ready

xbr_mpu_rd0_rsp_data

Input

512

脉冲

读响应通道0 数据

xbr_mpu_rd0_rsp_vld

Input

1

脉冲

读响应通道0 valid

mpu_xbr_rd0_rsp_rdy

Output

1

脉冲

读响应通道0 ready

读通道1

mpu_xbr_rd1_req_addr

Output

32

脉冲

读请求通道1 地址

mpu_xbr_rd1_req_vld

Output

1

脉冲

读请求通道1 valid

xbr_mpu_rd1_req_rdy

Input

1

脉冲

读请求通道1 ready

xbr_mpu_rd1_rsp_data

Input

512

脉冲

读响应通道1 数据

xbr_mpu_rd1_rsp_vld

Input

1

脉冲

读响应通道1 valid

mpu_xbr_rd1_rsp_rdy

Output

1

脉冲

读响应通道1 ready

存储通道

xbr_cim_wen_vld

Input

1

脉冲

写使能请求 valid

cim_xbr_wen_rdy

Output

1

脉冲

写使能请求 ready

xbr_cim_wen_flag

Input

1

脉冲

写使能请求 last

cim_xbr_wen_ack_vld

Output

1

脉冲

写使能响应 valid

xbr_cim_wen_ack_rdy

Input

1

脉冲

写使能响应 ready

cim_xbr_ren_global_vld

Input

1

脉冲

全局读使能 valid

xbr_cim_ren_global_rdy

Output

1

脉冲

全局读使能 ready

xbr_cim_ren_global_ack_vld

Output

1

脉冲

全局读使能响应 valid

cim_xbr_ren_global_ack_rdy

Input

1

脉冲

全局读使能响应 ready

xbr_cim_addr

Input

32

脉冲

CIM请求地址

xbr_cim_strobe

Input

2

脉冲

指示写入CIM粒度和有效位，

2’b01：低256bit有效；

2‘b10：高256bit有效；

2’b11：512bit有效

xbr_cim_mem_d

Input

512

脉冲

输入数据

cim_xbr_mem_q

Output

512

脉冲

输出数据

xbr_cim_exp_flag

Input

1

脉冲

指数访问flag

维测信号

creg_mpu_start

Input

1

脉冲

MPU性能统计开始

creg_mpu_pause

Input

1

脉冲

MPU性能统计暂停

creg_mpu_continue

Input

1

脉冲

MPU性能统计继续

creg_mpu_end

Input

1

脉冲

MPU性能统计结束

mpu_creg_perf_count_reg

Output

192

脉冲

MPU性能统计结果

creg_mpu_perf_enable

Input

1

脉冲

MPU性能统计使能

mpu_creg_int

Output

32

脉冲

MPU中断

mpu_creg_dbg_reg0

Output

32

脉冲

MPU维测信号0

mpu_creg_dbg_reg1

Output

32

脉冲

MPU维测信号1

mpu_creg_dbg_reg2

Output

32

脉冲

MPU维测信号2

测试通道

dft_scan_en

Input

1

电平

低功耗时钟DFT信号

dft_dcim_bist_mode

Input

1

脉冲

CIM BIST测试模式：1：开；0：关

dft_dcim_bist_start

Input

1

脉冲

CIM BIST测试使能

dft_dcim_alg_sel

Input

1

脉冲

CIM bist算法选择：1: March C-    0: checkboard

dft_dcim_mbist_en

Input

1

脉冲

CIM bist选择使能：1：有效

dft_dcim_mcomp_go

Output

8

脉冲

CIM bist测试结果：1：有效；0：异常

dft_dcim_lbist_en

Input

1

脉冲

CIM logic bist选择使能：1：有效

dft_dcim_lcomp_go

Output

8

脉冲

CIM logic bist测试结果：1：有效；0：异常

dft_dcim_alg_end

Output

8

脉冲

CIM bist结束： 1：结束

dft_dcim_atpg_end

Output

8

脉冲

CIM logic bist结束： 1：结束

dft_dcim_ram_cen

Output

1

脉冲

给SPAD0的CIM bist 片选信号（低有效）

dft_dcim_ram_wen

Output

1

脉冲

给SPAD0的CIM bist 写信号（低有效）：1：读；0：写

dft_dcim_ram_addr

Output

32

脉冲

给SPAD0的CIM bist 地址信号

dft_dcim_ram_q

Input

512

脉冲

SPAD0返回的数据信号


7.2 接口时序

配置通道时序：


读通道时序（读0通道/读1通道）：


写通道时序：


存储通道时序：


7.3 接口时序约束

7.3.1 配置接口约束

配置有效信号start为单脉冲信号，代表当前算子有效信号，在MPU未返回当前算子对应的done信号（结束信号）时，COMMAND SCHEDULAR不会下发新算子的start信号。

违反约束后果：可能会因为配置切换造成MPU挂死、数据计算异常、有效数据地址踩踏。

波形：


7.3.2 计算读写接口约束

读通道遵循XBAR设计时序（OUTSTANDING=0），行为描述为：1. 当前读请求的rsp_vld信号应该在req通道握手之后拉高；2. 在上一个rsp响应握手前，下一个读请求的req_rdy保持拉低；

违反约束后果：可能会因为XBAR行为异常造成MPU挂死、数据计算异常。

波形：


写通道遵循XBAR设计时序（只有最后一个写请求回响应），行为描述为：1. 非最后一个写请求时，写请求下发后不会返回响应；2. 最后一个写请求时，需拉高flag信号给XBAR，XBAR返回rsp_vld，与MPU相应通道握手后结束。

违反约束后果：可能会因为XBAR行为异常造成MPU挂死、数据计算异常。

波形：


7.3.3 存储读写接口约束

存储接口遵循SRAM接口协议，行为描述为：1. 读写请求不能同拍握手，即ren_global_req_vld和ren_global_req_rdy握手与wen_req_vld和wen_req_rdy握手不会同时发生。

违反约束后果：因为当前CIM为手工定制SRAM，不保证CIM同拍读写数据准确性。

波形：


8. 子模块设计

8.1 MPU_CTRL

MPU_CTRL是MPU的核心控制模块，该模块负责MPU配置管理、配置二次解析、软复位、低功耗策略和状态上报。当MPU收到start信号时从Command Schedular接收配置，配置检查并且二次解析后分发到各子模块。LP_CTRL根据上级传来的低功耗信息（配置或低功耗指示寄存器）控制子模块低功耗方式。当子模块结束使用时，MPU_CTRL会给子模块发送清空使能用于将信号回复初始状态。MPU_CTRL会将异常和算子结束信号返回给Command Schedular。

8.1.1 MPU_CTRL规格


模块名

数量

功能

占用拍数

CFG_CHK

1

检查上级模块下发的算子配置是否合理，当配置无问题时下发工作使能到CFG_CTRL和CFG_SEC_RESOLUTION

1

CFG_SEC_RESOLUTION

1

下发的算子配置进行二次解析，将算子配置信息转换为MPU内部模块所需使用的各种配置信息和配置模式

1

CFG_CTRL

1

将二次解析以及原始算子配置中所包含的算子控制链路信息在合适的算子中发给对应的子模块

1

LP_CTRL

1

将二次解析以及原始算子配置中所包含的算子通路低功耗信息在合适的算子中发给对应的子模块

1

STATE_REPORT

1

将CFG_CHK中检查出的异常、MPU各子模块在执行中检查出的异常、性能统计结果发送至NPU_CORE_REG模块

将算子结束后的算子完成信息发送至COMMAND SCHEDUALR

计算算子结束时产生clr软复位信号，复位MPU各模块关键信号

1


8.1.2 MPU_CTRL子模块架构示意图


8.1.3 MPU_CTRL子模块流水并行示意图

无异常中断示意图：


配置异常中断示意图：


计算异常中断示意图：


8.2 MPU_RD_CHANNEL

MPU_RD_CHANNEL是MPU从SPAD中读取数据整形后送入后续模块运算的功能模块，主要完成下发地址请求 -> 接收数据响应 -> 数据整形 -> 送入对应的计算通道的处理流程。MPU_RD_CHANNEL有两组独立的读通道与XBAR相连，每组读通道有一个请求通道和一个响应通道。RD0_CHANNEL用于处理Input数据(ACTIVATION)，RD1_CHANNEL则由PSUM数据(Origional Vector) 和 MX-EXP数据共享。

8.2.1 MPU_RD_CHANNEL规格


公用模块

模块名称

数量

接口协议

功能

占用拍数


RD_REQ_CTRL

1

Valid & Ready

根据配置决定当前是否下发RD0请求或者RD1请求

0

ADDR_GEN

ADDR_GEN

1

Valid & Ready

接收配置后下发RD0通道读请求与读地址

1

ADDR_GEN_ORIG

1

Valid & Ready

接收配置后下发RD1通道PSUM(Orig Vector)读请求与读地址

1


ADDR_GEN_MX

1

Valid & Ready

定制地址生成器，接收配置后下发RD1通道MX-EXP读请求与都地址，按照DIM1方向读取数据，然后再按照DIM0方向读取数据

1


INPUT_ALIGN

1

Valid & Ready

RD0通道返回FP数据，该模块会按照32个元素的粒度进行指数对齐(按最大指数)，输出对齐后的EXP和MANTISSA，如果是INT数据类型，不做对齐直接输出

1

FRR_DISPATCHER

FRR_DISPATCHER_DATA

1

Valid & Ready

将INPUT ALIGN下发的data数据当拍分发到对应的通道

0

FRR_DISPATCHER_EXP

1

Valid & Ready

将INPUT ALIGN下发的exp数据当拍分发到对应的通道

0

FRR_DISPATCHER_MX

1

Valid & Ready

将响应通道的MX-EXP数据当拍分发到对应的通道

0

SHAPING_REG

SHAPING_REG

4

Valid & Ready

将紧排的元素按照CIME64通道的粒度进行拆分下发，与下游模块握手完成后等待4拍(数据精度为8)/8拍(数据精度为16)后再次下发新的数据

4/8

RD0_GLUE_LOGIC

RD0_GLUE_LOGIC

4

Valid & Ready

FP8数据类型，上游一次会产生2个9bit EXP，将2个EXP同时存到下游2个EXP FIFO里面。

FP16/BF16数据类型，上游一次会产生1个9bit EXP，将EXP轮询送入下游的2个EXP FIFO中的一个。

0

SHOWHEAD_FIFO

EXP_FIFO

8

Valid & Ready

位宽：9bit；深度：2。

1

ORIG_FIFO

1

Valid & Ready

位宽：512bit；深度：2。

1


RD1_REQ_CTRL

1

Valid & Ready

根据配置和状态选择当前RD1读请求通道是被PSUM(Orig Vector)请求占用还是MX请求占用

0

NAN_DETECT_FP

NAN_DETECT_FP

1

Valid & Ready

根据配置检测当前的一笔紧排元素的数据中是否存在INF或者NaN数据，如果存在就上报中断

0

NAN_DETECT_MX

NAN_DETECT_MX

4

Valid & Ready

根据配置检测当前的一笔紧排EXP的数据中是否存在NaN数据，如果存在就上报中断

0

SHIFT_TRANSMIT_REG

SHIFT_TRANSMIT_REG

4

Valid & Ready

将上游模块传入的数据保存，然后按照移位的方式每次送出固定的几bit，当所有有效数据送出后接收下一笔上游模块传入的数据

1

BANYAN

BANYAN

2

Valid & Ready

根据算子配置决定数据的路由通路和分发方式，将输入数据按照特定的通路发送到特定的下游模块

0


RD1_GLUE_LOGIC

1

Valid & Ready

根据配置决定当前与上游模块和下游多通道握手的次数

0

INPUT_GLUE_LOGIC

INPUT_GLUE_LOGIC

4

Valid & Ready

同步模块，来自RD0通道和RD1通道的数据同步后发送到下游模块，确保数据一致性

0


8.2.2 MPU_RD_CHANNEL子模块架构示意图


8.2.3 子模块流水并行示意图

INT + PSUM示意图（INT8为例）（RD0与RD1访问不同SPAD）：


FP  + PSUM示意图（FP8为例）（RD0与RD1访问不同SPAD）：


FP  + PSUM示意图（FP16为例）（RD0与RD1访问不同SPAD）：


MX-INT + INT示意图（MXEXP 32元素共享一个）（MXEXP和INPUT不在同一块SPAD上）：


MX-INT + INT示意图（MXEXP 32元素共享一个）（MXEXP和INPUT在同一块SPAD上）：


8.2.4 ADDR_GEN 逻辑分析

ADDR_GEN模块负责地址生成，从MPU_CTRL模块接收关于地址维度的配置信息以及地址生成模式的配置信息，地址生成模式支持3种PATTERN：


PATTERN

编码

地址生成方式

特点

type0

001

addr0 -> addr1 -> addr2 -> addr3 -> addr4 -> XXXX -> addr_final

地址无重复

type1

010

addr0 -> addr1 -> addr0 -> addr1 -> addr2 -> addr3 -> addr2 -> addr3 -> addr4 -> addr5 -> addr4 -> addr5

按照DIM0_SIZE循环两次

type2

100

addr0 -> addr1 -> addr0 -> addr1 -> addr0 -> addr1 -> addr0 -> addr1 -> addr2 -> addr3 -> addr2 -> addr3 -> addr2 -> addr3 -> addr2 -> addr3

按照DIM0_SIZE循环四次


8.2.5 FRR_DISPATCHER 逻辑分析

FRR_DISPATCHER模块负责将数据公平轮询发送到后续的数据通道，支持对一个SLAVE模块传输1/2/4次数据后轮询到下一个SLAVE数据通路，支持对多个通道的MASK掩码操作。FRR_DISPATHCER模块还支持多种补零模式：


模块配置信号名称

编码

备注

dispatch_mode

00

给Slave通道传输一次数据后轮循到下一个有效通道

01

给Slave通道传输两次数据后轮循到下一个有效通道

10

给Slave通道传输四次数据后轮循到下一个有效通道

special_mode

00

最后一个有效通道需要补零

01

每个有效通道都需要补零

10

每两个有效通道中的第二个有效通道需要补零

channel_mask

XXXX

根据例化时参数生成的通道总数，每个bit代表一个通道，从低往高，1：有效；0：无效

zero_time

2‘b00 - 2'b11

每个通道需要补零的次数，0-3


8.2.6 INPUT_ALIGN 逻辑分析

INPUT_ALIGN模块主要负责两个任务，1. 将输入的浮点类型数据按照32个元素为一组的粒度做找指数的最大值做对齐，然后将尾数根据指数差进行对应的右移。将浮点数据转换成指数EXP（有符号数）和尾数（有符号数）传递到后级。2. 适配MPU整体算法，将输入的数据的指数EXP进行提前补偿，目的是为了保持小数点在最高位MSB往右数两bit后面。

INPUT_ALIGN模块有两级流水，数据输入后会先进行非数的检查，检查通过后会进行下面的算法处理，其中第一到三步会在第一级流水处理，第四到七步在第二级流水处理。


INPUT_ALIGN模块支撑输入INT8 / FP8E5M2 / FP8E4M3 / INT16 / FP16 / BF16，当输入精度为8bit精度的时候，一次会完成64个元素的处理（512bit/8bit = 64元素），当输入精度为16bit的时候，一次会完成32个元素的处理（512bit/16bit = 32元素）。exp_max加预偏移的数值原因为预对齐后续在CIMM中累加会导致小数移位，为了保持整个MPU内小数点固定在数据第二位后不动，在这里要做预补偿，这样在CIMM中计算结束后就不会存在重新对exp进行移位的操作。

8.2.7 SHAPING_REG 逻辑分析

8.2.8 RD0_GLUE_LOGIC 逻辑分析

8.2.9 RD1_REQ_CTRL 逻辑分析

8.2.10 SHIFT_TRANSMIT_REG 逻辑分析

8.2.11 BANYAN 逻辑分析

8.2.12 RD1_GLUE_LOGIC 逻辑分析

8.2.13 RD_REQ_CTRL 逻辑分析

8.2.14 INPUT_GLUE_LOGIC 逻辑分析

8.2.15 NAN_DETECT 逻辑分析

8.2.16 MX数据场景分析

5.3 MPU_CIMC

MPU_CIMC是MPU内部核心计算模块同时也是NPU中的存储模块，计算功能由CIM Macro实现，存储由CIM Macro中SRAM实现。MPU_CIMC有两个时钟域，计算域和存储域，两个域相互独立，CIME则由两个域共同管理。两个CIM Macro与一个累加器组成最小的计算单元CIM Engine。CIMC实现CIM的存储路由功能，CIMC_ADDR_MAP负责地址重映射将XBAR中的32bit地址映射到CIME的10bit地址。在CIMC_ADDR_MAP与CIME之间有一个XBAR负责一对四的互联。


下图为MPU_CIMC存储模式下地址映射关系：


CIMM EXP 内部地址

位置

模式

PAGE偏移

CIM偏移

XBAR地址

000100000

单PAGE内 CIME[0] CIMM[0]

PATTERN2

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b0000_0000

PATTERN3

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b0000_0000

001100000

单PAGE内 CIME[0] CIMM[1]

PATTERN2

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b0100_0000

PATTERN3

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8"b1000_0000

010100000

单PAGE内 CIME[1] CIMM[0]

PATTERN2

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b1000_0000

PATTERN3

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b0000_0001

011100000

单PAGE内 CIME[1] CIMM[1]

PATTERN2

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b1100_0000

PATTERN3

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b1000_0001

100100000

单PAGE内 CIME[2] CIMM[0]

PATTERN2

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b0000_0001

PATTERN3

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b0000_0010

101100000

单PAGE内 CIME[2] CIMM[1]

PATTERN2

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b0100_0001

PATTERN3

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b1000_0010

110100000

单PAGE内 CIME[3] CIMM[0]

PATTERN2

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8"b1000_0001

PATTERN3

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b0000_0011

111100000

单PAGE内 CIME[3] CIMM[1]

PATTERN2

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b1100_0001

PATTERN3

XBAR[16:13]

XBAR[19:17] = 3'b010

XBAR[12:5] = 8'b1000_0011


8.4 MPU_POST_PROCESS

MPU_POST_PROCESS模块负责根据不同的PATTERN对CIME的数据进行累加处理和数据还原。在Pattern2（2*2）场景下，CIME0的计算结果需要与CIME1的计算结果相加，CIME2的计算结果需要与CIME3的计算结果相加；然后CIME0+CIME1的计算结果与CIME2+CIME3的计算结果依次交替送出。累加结束后会根据算子配置送入格式转换模块转换成INT32/FP32，后续如果需要与PSUM部分和(Orig Vector)累加，则在最后一级累加器进行累加，如果不需要累加，则送入最后一级累加器走完流水，然后送到MPU_WR_CHANNEL中。

8.4.1 MPU_POST_PROCESS规格


公用模块

模块名称

数量

接口协议

功能

占用拍数

POST_GLUE_LOGIC

POST_GLUE_LOGIC

2

Valid & Ready

粘合保序逻辑，根据配置决定上下两个CIME中的哪个与后级模块握手

0

INT_ACC_PIPE1

INT_ACC_PIPE1

2

Valid & Ready

INT38加法器，前级送入的两个INT38进行相加后生成INT39送入后级

2


POST_SELECT

1

Valid & Ready

粘合保序逻辑，根据配置决定上下两个INT_ACC_PIPE1中的哪个与后级模块握手

0


FORMAT_CONVERSION_39

1

Valid & Ready

格式转换模块，将INT39根据配置转换成INT32或FP32的Wrapper

0


TRANS_INT32ORFP32_39

4

Valid & Ready

格式转换模块，将INT39根据配置转换成INT32或FP32的实体

1


NORMALIZATION_39

16

Valid & Ready

归一化处理模块，寻找一个元素中的Mantissa的MSB的1的位置，然后移位恢复到特定格式

1

INT_FP_ACCUMULATOR

INT_FP_ACCUMULATOR

1

Valid & Ready

INT32/FP32加法器，能实现INT32+INT32或者FP32+FP32，上报异常中断以及归一化处理

4


8.4.2 MPU_POST_PROCESS子模块架构示意图


8.4.3 子模块流水并行示意图

Pattern2所有CIME全部使用场景，权重使用精度为16的数据，一个CIME一次出一组有效的数，简化流水：


Pattern4所有CIME全部使用场景，权重使用精度为16的数据，一个CIME一次出一组有效的数，简化流水：


8.4.4 POST_GLUE_LOGIC 逻辑分析

Post_glue_logic

8.4.5 INT_ACC_PIPE1 逻辑分析

8.4.6 POST_SELECT 逻辑分析

8.4.7 FORMAT_CONVERSION_39 逻辑分析

8.4.8 INT_FP_ACCUMULATOR 逻辑分析

INT_FP_ACCUMULATOR实现从CIM中计算出的结果与PSUM进行累加

8.5 MPU_WR_CHANNEL

MPU_WR_CHANNEL模块负责将后处理完成的数据根据MPU_CTRL的配置送入SPAD中的对应地址。在发送出最后一个数据时拉高flag信号，等到最后一个数据写入SPAD完成后MPU_WR_CHANNEL会收到这笔请求的写响应。收到写响应后，MPU_WR_CHANNEL会给MPU_CTRL返回一个脉冲done信号用于告诉MPU_CTRL算子已经计算结束。

8.5.1 MPU_WR_CHANNEL规格


公用模块

模块名称

数量

接口协议

功能

占用拍数

ADDR_GEN

ADDR_GEN

1

Valid & Ready

接收配置后下发WR通道读地址

1


8.5.2 MPU_WR_CHANNEL子模块结构示意图


8.5.3 子模块流水并行示意图


9. MPU低功耗设计

9.1 MPU整体低功耗

MPU存在3个时钟域，计算域、存储域、DFT测试域。

DFT测试时钟域为常开时钟，该时钟由NPU顶层时钟直接接入。

计算域时钟控制源头为Command Schedular，由其决定什么时候开启MPU的计算时钟。当MPU有GEMM算子或Switch Pattern时，开启时钟，当算子结束后关闭时钟。

存储域时钟控制源头为NPU TOP中的顶层控制时钟。


9.2 MPU内部低功耗

MPU内部有细粒度门控时钟，低功耗信息来自于配置中隐藏的低功耗信息。

第一类低功耗信息来自于配置中显性需要配置的使能信息：

1. PSUM使能。当PSUM使能为低时，RD1通道中的PSUM门控时钟将会处于低功耗状态；当PSUM使能为高时，RD1通道中的PSUM门控时钟将会处于非低功耗状态。该类门控属于算子粒度控制时钟。

2. MX使能。MX使能为低时，RD1通道中的MX EXP相关组件门控时钟将处于低功耗状态；MX使能为高时，RD1通道中的MX EXP相关组件门控时钟将处于非低功耗状态。该类门控属于算子粒度控制时钟。

第二类低功耗信息主要来自于配置中的矩阵形状，矩阵对CIME的使用量会直接决定CIME相关通道的使用，当使用CIME中一半的CIMM的时候，此时无法进行门控低功耗怕，但不使用的CIMM会在输入口输入0用于确保CIMM不进行翻转，控制策略如下图：


第三类门控比较特殊，该类门控的主要目的不是为了低功耗，主要是为了保证CIMM数据在后级遇到反压时将数据保持不丢失进行门控处理。因此每一个CIMM都会有一个这样的门控时钟。

9.3 MPU低功耗策略

Command Schedular进行算子级别的门控低功耗。

MPU解析配置，根据配置进行低功耗。

CIMM在遇到后级反压后为保持数据完整性做的主动门控低功耗。

内部模块在无数据流动时保持数据不反转的低功耗策略。

10. 代码健壮性

10.1 异常检测 & 中断

10.1.1 异常检测列表


异常检测名字

含义

触发条件

是否致命

mpu_creg_int[31]

MX共享通道数量配置异常，1'b1:发生；1'b0:未发生

MX共享指数的配置与当前配置的矩阵形状存在冲突

致命

mpu_creg_int[30]

原始向量数据格式异常，1'b1:发生；1'b0:未发生

PSUM(原始向量)数据格式不符合MPU计算格式要求

致命

mpu_creg_int[29]

权重数据数据格式异常，1'b1:发生；1'b0:未发生

权重数据格式不符合MPU计算格式要求

致命

mpu_creg_int[28]

输出数据数据格式异常，1'b1:发生；1'b0:未发生

输出数据格式不符合MPU计算格式要求

致命

mpu_creg_int[27]

输入数据数据格式异常，1'b1:发生；1'b0:未发生

Activation(输入)数据格式不符合MPU计算格式要求

致命

mpu_creg_int[26]

输入矩阵DIM1 SIZE与输出矩阵DIM1 SIZE不匹配，1'b1:发生；1'b0:未发生

输入矩阵配置的M维和输出矩阵配置的M维不相等

致命

mpu_creg_int[25]

REM配置异常，1'b1:发生；1'b0:未发生

配置DIM0维度存在步长内存在无效数据，REM>0

致命

mpu_creg_int[24]

SIZE配置异常，1'b1:发生；1'b0:未发生

输入DIM0配置与输出DIM0配置之间存在矩阵形状不匹配的问题

致命

mpu_creg_int[23]

所有数据占用超过六个SPAD异常，1'b1:发生；1'b0:未发生

MPU 配置所有使用的数据占用超过6块SPAD

致命

mpu_creg_int[22]

MX EXP数据占用超过一个SPAD异常，1'b1:发生；1'b0:未发生

MPU 配置MX EXP数据占用超过1块SPAD

致命

mpu_creg_int[21]

原始向量占用超过两个SPAD异常，1'b1:发生；1'b0:未发生

MPU 配置PSUM(原始向量)数据占用超过2块SPAD

致命

mpu_creg_int[20]

输出数据占用超过两个SPAD异常，1'b1:发生；1'b0:未发生

MPU 配置输出数据占用超过2块SPAD

致命

mpu_creg_int[19]

输入数据占用超过一个SPAD异常，1'b1:发生；1'b0:未发生

MPU 配置Activation(输入)数据占用超过1块SPAD

致命

mpu_creg_int[18]

MX EXP数据未按照512bit地址对齐异常，1'b1:发生；1'b0:未发生

MX EXP数据基地址配置未按照512bit地址对齐

致命

mpu_creg_int[17]

原始向量未按照512bit地址对齐异常，1'b1:发生；1'b0:未发生

PSUM(原始向量)数据基地址配置未按照512bit地址对齐

致命

mpu_creg_int[16]

输出数据未按照512bit地址对齐异常，1'b1:发生；1'b0:未发生

输出数据基地址配置未按照512bit地址对齐

致命

mpu_creg_int[15]

输入数据未按照512bit地址对齐异常，1'b1:发生；1'b0:未发生

Activation(输入)数据基地址配置未按照512bit地址对齐

致命

mpu_creg_int[14]

输出数据地址与原始向量地址部分重合异常，1'b1:发生；1'b0:未发生

输出数据与PSUM(原始向量)数据在除原位读写的情况外发生部分数据踩踏，数据有效性丧失

致命

mpu_creg_int[13]

输出数据地址与MX EXP地址重合异常，1'b1:发生；1'b0:未发生

输出数据与MX EXP数据发生部分或全部数据踩踏，数据有效性丧失

致命

mpu_creg_int[12]

原始向量地址与MX EXP地址重合异常，1'b1:发生；1'b0:未发生

PSUM(原始向量)数据与MX  EXP数据发生部分或全部数据踩踏，数据有效性丧失

致命

mpu_creg_int[11]

输入数据地址与原始向量地址重合异常，1'b1:发生；1'b0:未发生

Activation(输入)数据与PSUM(原始向量)数据发生部分或全部数据踩踏，数据有效性丧失

致命

mpu_creg_int[10]

输入数据地址与MX EXP地址重合异常，1'b1:发生；1'b0:未发生

Activation(输入)数据与MX EXP数据发生部分或全部数据踩踏，数据有效性丧失

致命

mpu_creg_int[9]

输入数据地址与输出数据地址重合异常，1'b1:发生；1'b0:未发生

Activation(输入)数据与输出数据发生部分或全部数据踩踏，数据有效性丧失

致命

mpu_creg_int[8]

MX EXP数据地址超界异常，1'b1:发生；1'b0:未发生

MX EXP数据地址超过SPAD有效空间

致命

mpu_creg_int[7]

权重数据地址超界异常，1'b1:发生；1'b0:未发生

权重数据地址超CIM存储有效空间

致命

mpu_creg_int[6]

输出数据地址超界异常，1'b1:发生；1'b0:未发生

输出数据地址超过SPAD有效空间

致命

mpu_creg_int[5]

原始向量地址超界异常，1'b1:发生；1'b0:未发生

PSUM(原始向量)数据地址超过SPAD有效空间

致命

mpu_creg_int[4]

输入数据地址超界异常，1'b1:发生；1'b0:未发生

Activation(输入)数据地址超过SPAD有效空间

致命

mpu_creg_int[3]

计算过程中出Inf，1'b1:发生；1'b0:未发生

MPU输入数据或计算过程中产生Inf数据

非致命

mpu_creg_int[2]

计算过程中出现NaN，1'b1:发生；1'b0:未发生

MPU输入数据或计算过程中产生NaN数据

致命

mpu_creg_int[1]

计算过程中出现unferflow，1'b1:发生；1'b0:未发生

MPU计算过程中发生下溢出

非致命

mpu_creg_int[0]

计算过程中出现overflow，1'b1:发生；1'b0:未发生

MPU计算过程中发生上溢出

非致命


10.1.2 接口


信号名称

位宽

方向

行为

使用约束

mpu_creg_int

32

output

脉冲

无

creg_mpu_excep_en

1

input

电平（高有效）

中断检查使能，0：MPU不上报异常或中断，1：MPU上报异常或中断


10.1.3 接口波形

MPU发生配置类相关致命异常中断(mpu_creg_int[31:4])(开启中断检查)：


MPU发生配置类相关致命异常中断(mpu_creg_int[31:4])(关闭中断检查)：存在挂死风险，可能不返回done信号

硬件检查逻辑错误，关闭后可正常结束


硬件检查逻辑正确，关闭后无法返回done信号导致挂死


MPU发生计算类相关致命异常中断(mpu_creg_int[3:2])(开启中断检查)：


MPU发生计算类相关致命异常中断(mpu_creg_int[2])(关闭中断检查)：关闭后可正常结束，计算结果不保证正确


MPU发生计算类相关非致命异常中断(mpu_creg_int[1:0]/[3])(开启中断检查)：


MPU发生计算类相关非致命异常中断(mpu_creg_int[1:0]/[3])(关闭中断检查)：关闭后可正常结束，计算结果不保证正确


10.2 性能监测

10.2.1 性能监测列表


性能监测信号

监测的含义

计数规则

mpu_creg_perf_cnt_reg[191:160]

写通道写入SPAD次数

按256bit对齐粒度统计，strobe=2’b11，cnt+2；strobe=2’b01/2‘b10，cnt+1；记满清零重新计数；

mpu_creg_perf_cnt_reg[159:128]

读1通道从SPAD读取次数

按256bit对齐粒度统计，读取按照512bit粒度时，cnt+2；读取按照256bit粒度时，cnt+1；PSUM每次加2，MX-EXP每次加1；记满清零重新计数；

mpu_creg_perf_cnt_reg[127:96]

读0通道从SPAD读取次数

按256bit对齐粒度统计，读取按照512bit粒度时，cnt+2；记满清零重新计数；

mpu_creg_perf_cnt_reg[95:64]

MPU计算总cycle数

MPU计算总周期数，compute clk有效下每1 cycle+1；记满清零重新计数；

mpu_creg_perf_cnt_reg[63:32]

MPU计算期间读写访存次数

MPU计算期间发生访存CIM行为，读取/写入按照512bit粒度时，cnt+2；读取/写入按照256bit粒度时，cnt+1；记满清零重新计数；

mpu_creg_perf_cnt_reg[31:0]

FP-CIM计算忙总周期数

FP-CIM计算总周期数，CEN信号开始计算，输入精度分别为8/16时，建立流水时每次+15/19，后续每次+4/8；记满清零重新计数；


10.2.2 接口


信号名称

位宽

方向

行为

使用约束

creg_mpu_perf_enable

1

input

电平（高有效）

性能统计使能

creg_mpu_start

1

input

电平（高有效）

四个输入ONEHOT使用，只会有一个信号拉高，性能统计开始使能

creg_mpu_pause

1

input

电平（高有效）

四个输入ONEHOT使用，只会有一个信号拉高，性能统计暂停使能

creg_mpu_continue

1

input

电平（高有效）

四个输入ONEHOT使用，只会有一个信号拉高，性能统计暂停后再继续使能

creg_mpu_end

1

input

电平（高有效）

四个输入ONEHOT使用，只会有一个信号拉高，性能统计结束使能

mpu_creg_perf_cnt_reg

192

output

脉冲

无


10.2.3 接口波形

计数器示意，所有计数器均符合该行为，但每次计数递增值不同


10.3 Debug信号

10.3.1 Debug信号接口


DEBUG信号名字

含义

type

description or constraint（使用约束）

mpu_creg_dbg_reg0[0]

MPU RD0通道请求VLD信号

level 


mpu_creg_dbg_reg0[1]

MPU RD0通道请求RDY信号

posedge trigger


mpu_creg_dbg_reg0[2]

MPU RD0通道响应VLD信号


mpu_creg_dbg_reg0[3]

MPU RD0通道响应RDY信号


mpu_creg_dbg_reg0[4]

MPU RD1通道请求VLD信号

 negedge trigger


mpu_creg_dbg_reg0[5]

MPU RD1通道请求RDY信号


mpu_creg_dbg_reg0[6]

MPU RD1通道响应VLD信号


mpu_creg_dbg_reg0[7]

MPU RD1通道响应RDY信号


mpu_creg_dbg_reg0[8]

MPU RD1通道MX EXP通道请求VLD信号


mpu_creg_dbg_reg0[9]

MPU RD1通道MX EXP通道请求RDY信号


mpu_creg_dbg_reg0[10]

MPU RD1通道MX EXP通道响应VLD信号


mpu_creg_dbg_reg0[11]

MPU RD1通道MX EXP通道响应RDY信号


mpu_creg_dbg_reg0[12]

MPU RD1通道PSUM通道请求VLD信号


mpu_creg_dbg_reg0[13]

MPU RD1通道PSUM通道请求RDY信号


mpu_creg_dbg_reg0[14]

MPU RD1通道PSUM通道响应VLD信号


mpu_creg_dbg_reg0[15]

MPU RD1通道PSUM通道响应RDY信号


mpu_creg_dbg_reg0[16]

MPU RD0 Input_align出口VLD信号


mpu_creg_dbg_reg0[17]

MPU RD0 Input_align出口RDY信号


mpu_creg_dbg_reg0[21:18]

MPU RD0 Frr_dispatcher_data出口VLD信号


mpu_creg_dbg_reg0[25:22]

MPU RD0 Frr_dispatcher_data出口RDY信号


mpu_creg_dbg_reg0[29:26]

MPU RD0 Frr_dispatcher_exp出口VLD信号


mpu_creg_dbg_reg0[31:30]

MPU RD0 Frr_dispatcher_exp出口RDY信号[1:0]


mpu_creg_dbg_reg1[1:0]

MPU RD0 Frr_dispatcher_exp出口RDY信号[3:2]


mpu_creg_dbg_reg1[5:2]

MPU RD0 Shaping_reg出口VLD信号


mpu_creg_dbg_reg1[9:6]

MPU RD0 Shaping_reg出口RDY信号


mpu_creg_dbg_reg1[17:10]

MPU RD0 Exp_fifo出口VLD信号


mpu_creg_dbg_reg1[25:18]

MPU RD0 Exp_fifo出口RDY信号


mpu_creg_dbg_reg1[29:26]

MPU RD1 Frr_dispatcher_mx出口VLD信号


mpu_creg_dbg_reg1[31:30]

MPU RD1 Frr_dispatcher_mx出口RDY信号[1:0]


mpu_creg_dbg_reg2[1:0]

MPU RD1 Frr_dispatcher_mx出口RDY信号[3:2]


mpu_creg_dbg_reg2[5:2]

MPU RD1 Shift_transmit_reg出口VLD信号


mpu_creg_dbg_reg2[9:6]

MPU RD1 Shift_transmit_reg出口RDY信号


mpu_creg_dbg_reg2[13:10]

MPU RD1 Psum_fifo出口VLD信号


mpu_creg_dbg_reg2[17:14]

MPU RD1 Psum_fifo出口RDY信号


mpu_creg_dbg_reg2[21:18]

MPU RD1 Rd1_glue_logic出口VLD信号


mpu_creg_dbg_reg2[25:22]

MPU RD1 Rd1_glue_logic出口RDY信号


mpu_creg_dbg_reg2[29:26]

MPU RD Input_glue_logic出口VLD信号


mpu_creg_dbg_reg2[31:30]

MPU RD Input_glue_logic出口RDY信号[1:0]


mpu_creg_dbg_reg3[1:0]

MPU RD Input_glue_logic出口RDY信号[3:2]


mpu_creg_dbg_reg3[2]

MPU CIMC 存储WEN VLD信号


mpu_creg_dbg_reg3[3]

MPU CIMC 存储WEN RDY信号


mpu_creg_dbg_reg3[4]

MPU CIMC 存储WEN FLAG信号


mpu_creg_dbg_reg3[5]

MPU CIMC 存储WEN ACK VLD信号


mpu_creg_dbg_reg3[6]

MPU CIMC 存储WEN ACK RDY信号


mpu_creg_dbg_reg3[7]

MPU CIMC 存储REN GLOBAL VLD信号


mpu_creg_dbg_reg3[8]

MPU CIMC 存储REN GLOBAL RDY信号


mpu_creg_dbg_reg3[9]

MPU CIMC 存储REN ACK VLD信号


mpu_creg_dbg_reg3[10]

MPU CIMC 存储REN ACK RDY信号


mpu_creg_dbg_reg3[11]

MPU CIME0 Post_glue_logic 入口IN0_VLD信号


mpu_creg_dbg_reg3[12]

MPU CIME0 Post_glue_logic 入口IN1_VLD信号


mpu_creg_dbg_reg3[13]

MPU CIME0 Post_glue_logic 出口OUT0_VLD信号


mpu_creg_dbg_reg3[14]

MPU CIME0 Post_glue_logic 出口OUT0_RDY信号


mpu_creg_dbg_reg3[15]

MPU CIME0 Post_glue_logic 出口OUT1_VLD信号


mpu_creg_dbg_reg3[16]

MPU CIME0 Post_glue_logic 出口OUT1_RDY信号


mpu_creg_dbg_reg3[17]

MPU CIME0 Int_acc_pipe3 出口OUT_VLD信号


mpu_creg_dbg_reg3[18]

MPU CIME0 Int_acc_pipe3 出口OUT_RDY信号


mpu_creg_dbg_reg3[19]

MPU CIME1 Post_glue_logic 入口IN0_VLD信号


mpu_creg_dbg_reg3[20]

MPU CIME1 Post_glue_logic 入口IN1_VLD信号


mpu_creg_dbg_reg3[21]

MPU CIME1 Post_glue_logic 出口OUT0_VLD信号


mpu_creg_dbg_reg3[22]

MPU CIME1 Post_glue_logic 出口OUT0_RDY信号


mpu_creg_dbg_reg3[23]

MPU CIME1 Post_glue_logic 出口OUT1_VLD信号


mpu_creg_dbg_reg3[24]

MPU CIME1 Post_glue_logic 出口OUT1_RDY信号


mpu_creg_dbg_reg3[25]

MPU CIME1 Int_acc_pipe3 出口OUT_VLD信号


mpu_creg_dbg_reg3[26]

MPU CIME1 Int_acc_pipe3 出口OUT_RDY信号


mpu_creg_dbg_reg3[27]

MPU CIME2 Post_glue_logic 入口IN0_VLD信号


mpu_creg_dbg_reg3[27]

MPU CIME2 Post_glue_logic 入口IN1_VLD信号


mpu_creg_dbg_reg3[28]

MPU CIME2 Post_glue_logic 出口OUT0_VLD信号


mpu_creg_dbg_reg3[29]

MPU CIME2 Post_glue_logic 出口OUT0_RDY信号


mpu_creg_dbg_reg3[30]

MPU CIME2 Post_glue_logic 出口OUT1_VLD信号


mpu_creg_dbg_reg3[31]

MPU CIME2 Post_glue_logic 出口OUT1_RDY信号


mpu_creg_dbg_reg4[0]

MPU CIME2 Int_acc_pipe3 出口OUT_VLD信号


mpu_creg_dbg_reg4[1]

MPU CIME2 Int_acc_pipe3 出口OUT_RDY信号


mpu_creg_dbg_reg4[2]

MPU CIME3 Post_glue_logic 入口IN0_VLD信号


mpu_creg_dbg_reg4[3]

MPU CIME3 Post_glue_logic 入口IN1_VLD信号


mpu_creg_dbg_reg4[4]

MPU CIME3 Post_glue_logic 出口OUT0_VLD信号


mpu_creg_dbg_reg4[5]

MPU CIME3 Post_glue_logic 出口OUT0_RDY信号


mpu_creg_dbg_reg4[6]

MPU CIME3 Post_glue_logic 出口OUT1_VLD信号


mpu_creg_dbg_reg4[7]

MPU CIME3 Post_glue_logic 出口OUT1_RDY信号


mpu_creg_dbg_reg4[8]

MPU CIME3 Int_acc_pipe3 出口OUT_VLD信号


mpu_creg_dbg_reg4[9]

MPU CIME3 Int_acc_pipe3 出口OUT_RDY信号


mpu_creg_dbg_reg4[10]

MPU POST Post_glue_logic0 出口OUT0_VALID信号


mpu_creg_dbg_reg4[11]

MPU POST Post_glue_logic0 出口OUT0_READY信号


mpu_creg_dbg_reg4[12]

MPU POST Post_glue_logic0 出口OUT1_VALID信号


mpu_creg_dbg_reg4[13]

MPU POST Post_glue_logic0 出口OUT1_READY信号


mpu_creg_dbg_reg4[14]

MPU POST Post_glue_logic1 出口OUT0_VALID信号


mpu_creg_dbg_reg4[15]

MPU POST Post_glue_logic1 出口OUT0_READY信号


mpu_creg_dbg_reg4[16]

MPU POST Post_glue_logic1 出口OUT1_VALID信号


mpu_creg_dbg_reg4[17]

MPU POST Post_glue_logic1 出口OUT1_READY信号


mpu_creg_dbg_reg4[18]

MPU POST Int_acc_pip1_0 出口OUT_VLD信号


mpu_creg_dbg_reg4[19]

MPU POST Int_acc_pip1_0 出口OUT_RDY信号


mpu_creg_dbg_reg4[20]

MPU POST Int_acc_pip1_1 出口OUT_VLD信号


mpu_creg_dbg_reg4[21]

MPU POST Int_acc_pip1_1 出口OUT_RDY信号


mpu_creg_dbg_reg4[22]

MPU POST Post_select 出口OUT_VLD信号


mpu_creg_dbg_reg4[23]

MPU POST Post_select 出口OUT_RDY信号


mpu_creg_dbg_reg4[24]

MPU POST Format_conversion_39 出口O_VLD信号


mpu_creg_dbg_reg4[25]

MPU POST Format_conversion_39 出口I_RDY信号


mpu_creg_dbg_reg4[26]

MPU WR通道请求VLD信号


mpu_creg_dbg_reg4[27]

MPU WR通道请求RDY信号


mpu_creg_dbg_reg4[28]

MPU WR通道响应VLD信号


mpu_creg_dbg_reg4[29]

MPU WR通道响应RDY信号


mpu_creg_dbg_reg4[30]

MPU WR Addr_gen出口VLD信号


mpu_creg_dbg_reg4[31]

MPU WR Addr_gen出口RDY信号


mpu_creg_dbg_reg5[0]


10.3.2 Debug寄存器列表


Debug 寄存器名字

寄存器含义

预期行为


11. MPU BIST

11.1 MPU BIST介绍

MPU的CIM需要做两种bist相关测试，CIM Memory Bist测试和CIM Logic Bist测试。BIST测试开始后全自动流程，仅需通过信号线控制开始信息，之后即可获得测试结果。CIM Memory Bist测试关注CIM本身存储阵列的质量，如果存在制造问题，会返回异常信息。CIM Logic Bist测试关注CIM 计算阵列质量，因此需要外部生成大量测试PATTERN，这些PATTERN需要在CIM BIST测试开始前送入SPAD_BIST中，然后CIM开始不断地从SPAD_BIST中读取PATTERN，如果存在制造问题，会返回异常信息。

11.2 MPU BIST接口

11.2.1 接口信号列表


分类

名称

位宽

方向

行为

含义

备注

CIM BIST信号

dft_dcim_bist_mode

1

INPUT

电平

CIM BIST测试模式

1：开；0：关

dft_dcim_bist_start

1

INPUT

脉冲

CIM BIST测试使能

1：启动

dft_dcim_alg_sel

1

INPUT

电平

CIM bist算法选择

1: March C-

0: checkboard

dft_dcim_alg_end

8

OUTPUT

电平

CIM bist结束

1：结束

dft_dcim_atpg_end

8

OUPUT

电平

Logic bist结束

1：结束

dft_dcim_mbist_en

1

INPUT

电平

mbist选择使能

1：有效

dft_dcim_mcomp_go

8

OUTPUT

电平

mbist测试结果

1：正常；0：异常

dft_dcim_lbist_en

1

INPUT

电平

lbist选择使能

1：有效

dft_dcim_lcomp_go

8

OUTPUT

电平

lbist测试结果

1：正常；0：异常


11.2.2 接口波形

CIM MBIST时序（无异常）


CIM MBIST时序（有异常）


CIM LBIST时序（无异常）


CIM LBIST时序（有异常）


12. 反压设计

设计原则：所有模块均通过VALID&READY握手协议进行数据交互，通过模块内空满进行逐级反压。

计算通路反压通道：


 存储通路反压通道：


13. 对外约束

当多指令均是对MPU的同一数据行为的配置操作或计算操作时，由Command Schedular收集，当收集齐所有针对同一数据的所有操作时（最后一个计算指令）给MPU下发指令。

MPU在做CIM存取时，MASTER需保证读写请求不同拍下发，防止读写竞争冲突。

MPU计算类指令暂不支持配置保留，一次计算后会清空，需重新配置后可进行下次计算。

14. MPU误差分析

在MPU整条算法链路中能引起精度误差的地方有三个地方，INPUT_ALIGN模块、INT_ACC模块、FORMAT_CONVERSION模块和INT_FP_ACCUMULATOR模块。

INPUT ALIGN模块的精度损失主要来源于对齐最大指数引起的尾数丢弃。

INT_ACC模块的精度损失主要来源于对齐最大指数引起的尾数丢弃。

FORMAT CONVERSION模块的精度损失主要来源于格式转换时引起的尾数丢弃。

INT_FP_ACCUMULATOR模块的精度损失主要来源于对齐指数引起的尾数丢弃。

不同的数据精度格式在通过MPU算法通路的时候会造成不同的精度损失，后续将分析所有的数据精度格式可能引起的精度误差。

14.1 INPUT ALIGN模块精度损失分析

INPUT ALIGN模块输出结果中，如果输入数据是精度为8的FP类型数据，输出数据中尾数部分仅会保留8位；如果输入数据是精度为16的FP类型数据，输出数据中尾数部分仅会保留16位。


数据精度类型

指数范围

最大指数差

最大无损精度中其余指数与最大指数的差

备注

FP8_E5M2

-15 ~ 16

31

4

前项小于等于4时，Mantissa中所有位可保留，如果Mantissa数据存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时FP8E5M2最大无损精度差为5。

FP8_E4M3

-7 ~ 8

15

3

前项小于等于3时，Mantissa中所有位可保留，如果Mantissa数据存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时FP8E4M3最大无损精度差为5。

FP16

-15~16

31

4

前项小于等于4时，Mantissa中所有位可保留，如果Mantissa数据存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时FP16最大无损精度差为13。

BF16

-127 ~ 128

255

7

前项小于等于4时，Mantissa中所有位可保留，如果Mantissa数据存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时BF最大无损精度差为13。


14.2 INT ACC PIPE3模块精度损失分析

INT_ACC_PIPE3模块输入INT37数据，输出INT38bit数据。输入的两个INT37会先比各自对应的EXP，将小的EXP向大的EXP对齐后，小的EXP对应的Mantissa右移对应的EXP差。如果当前算子计算的数据为FP数据类型，INT37表示的含义为[sign, hidden_bit, mantissa]，其中sign 1bit，hidden_bit 1bit，mantissa 35bit。因为CIMM输出数据时FP数据中的Mantissa放在高位，低位放无效冗余位，所以无效冗余位为可保持的数据精度位数。无效冗余位的有效精度为INT_ACC_PIPE3和INT_ACC_PIPE1和FORMAT CONVERSION共享，所以设置参数X，该参数仅表示当前INT_ACC_PEPE3中根据指数差使用的冗余位个数。


数据精度类型

Activation格式

Weight格式

最大无损精度中其余指数与最大指数差

备注

INT37 + EXP

数据精度为8

数据精度为4

24

前项小于等于24时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为X+34。

数据精度为16

数据精度为4

24

前项小于等于24时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为X+34。

数据精度为8

数据精度为8

20

前项小于等于20时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为X+34。

数据精度为16

数据精度为8

12

前项小于等于12时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为X+34。

数据精度为8

数据精度为16

8

前项小于等于20时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为X+34。

数据精度为16

数据精度为16

0

前项小于等于0时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为34。


14.3 INT ACC PIPE1模块精度损失分析

INT_ACC_PIPE1模块输入INT38数据，输出INT39bit数据。输入的两个INT38会先比各自对应的EXP，将小的EXP向大的EXP对齐后，小的EXP对应的Mantissa右移对应的EXP差。如果当前算子计算的数据为FP数据类型，INT38表示的含义为[sign, hidden_bit, mantissa]，其中sign 1bit，hidden_bit 1bit，mantissa 36bit。无效冗余位的有效精度为INT_ACC_PIPE3和INT_ACC_PIPE1和FORMAT CONVERSION共享，所以设置参数Y，该参数仅表示当前INT_ACC_PEPE1中根据指数差使用的冗余位个数。


数据精度类型

Activation格式

Weight格式

最大无损精度中其余指数与最大指数差

备注

INT38 + EXP

数据精度为8

数据精度为4

24

前项小于等于24时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为Y+35。

数据精度为16

数据精度为4

24

前项小于等于24时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为Y+35。

数据精度为8

数据精度为8

20

前项小于等于20时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为Y+35。

数据精度为16

数据精度为8

12

前项小于等于12时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为Y+35。

数据精度为8

数据精度为16

8

INT_ACC_PIPE3占用的X位前项小于等于20时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为Y+35。

数据精度为16

数据精度为16

0

前项小于等于0时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为35。


14.4 FORMAT CONVERSION模块精度损失分析

FORMAT CONVERSION中输入INT39数据和EXP，输出INT32或FP32。当算子输入数据格式为INT16，权重格式为INT16时，如果输出格式为INT32，会有精度损失，高位数据会丢失。如果计算链路为FP数据，输出结果转换截位时可能会导致精度损失。当INT_ACC_PIPE3占用了X位冗余保护位以及当INT_ACC_PIPE1占用了Y位冗余保护位后，FORMAT CONVERSION中如果想保持全部数据，首先会从INT39中Mantissa所占的37位截位为FP32中Mantissa所占的23位，存在冗余位的占用，只能占用冗余保护位总数减去INT_ACC_PIPE3占用的X位后再减去INT_ACC_PIPE1占用的Y位。


数据精度类型

Activation格式

Weight格式

最大无损精度中其余指数与最大指数差

备注

INT39 + EXP

转换成FP32

数据精度为8

数据精度为4

24 - 14 = 10

前项小于等于10时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为10-X-Y+36。

数据精度为16

数据精度为4

24 -14 = 10

前项小于等于10时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为10-X-Y+36。

数据精度为8

数据精度为8

20 - 14 = 6

前项小于等于6时，Mantissa中所有位可保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为6-X-Y+36。

数据精度为16

数据精度为8

12 - 14 < 0

Mantissa中所有有效位无法全部保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为36-X-Y-2。

数据精度为8

数据精度为16

8 - 14 < 0

Mantissa中所有有效位无法全部保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为36-X-Y-6。

数据精度为16

数据精度为16

0 - 14 < 0

Mantissa中所有有效位无法全部保留，如果Mantissa存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时INT37最大无损精度指数差为22-X-Y-14。

INT39 + EXP

转换成INT32

数据精度为8

数据精度为4

不存在

无精度损失

数据精度为16

数据精度为4

不存在

无精度损失

数据精度为8

数据精度为8

不存在

无精度损失

数据精度为16

数据精度为8

不存在

无精度损失

数据精度为8

数据精度为16

不存在

无精度损失

数据精度为16

数据精度为16

不存在

存在INT39转INT32，数据过大是，高位会丢失。


14.5 INT FP ACCUMULATOR模块精度损失分析

INT_FP_ACCUMULATOR模块输入FP32数据，输出FP32数据。输入的两个FP会先比各自对应的EXP，将小的EXP向大的EXP对齐后，小的EXP对应的Mantissa右移对应的EXP差。因为INT_FP_ACCUMULATOR中Mantissa加法器复用了INT加法器，INT加法器为32bit加法器，所以FP数据中Mantissa放在高位，Mantissa数据格式为[sign, hidden_bit, Mantissa]，sign 1bit，hidden_bit 1bit，mantissa 23bit，总有效位宽为25bit，将Mantissa放在高位，低位为7'b0，因此存在7bit冗余移位保护。


数据精度类型

指数范围

最大指数差

最大无损精度中其余指数与最大指数的差

备注

FP32

-127 ~ 128

255

7

前项小于等于7时，Mantissa中所有位可保留，如果Mantissa数据存在有效位且不在LSB，可保留对应LSB到部分有效位之间的数据精度，Mantiisa中存在有效位时FP32最大无损精度指数差为29。



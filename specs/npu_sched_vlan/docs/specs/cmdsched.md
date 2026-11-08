
1. 发布初版CMD Scheduler Arch Spec.

1.2 Abbreviations
缩写
全称
定义说明
CMD
Command Scheduler
命令调度器。
SHazard
Structural Hazard
结构冒险，因硬件资源冲突导致的流水线冒险。
DHazard
Data Hazard
数据冒险，因指令间数据依赖导致的流水线冒险。




1.3 需求来源输入 
序列
需求描述
需求来源
解决方案
优化方向
1
删除CPU读取csr配置寄存器功能
指令集修改csr规格，且输入来源由软件配置，故不再通过指令读取寄存器配置。
- 删除rd_csr nice指令;
- cfg 寄存器信息写入core reg，通过访问core reg实现查阅寄存器配置.
指令集简化

2
删除CIMC的1x4形状
MPU 考虑矩阵尺寸较大，删掉1x4模式
- 删掉setCIMC指令解析，默认仅支持2x2模式.
指令集简化
3
删除creg_cmd_icg_en[5:0]信号
删除各组件低功耗模式
NPU低功耗设计由各个master ip控制
- 不再对各模块进行低功耗控制，改由各模块自己控制
优化硬件低功耗
低功耗灵活
4
删掉多组件访问同一SPAD的阻塞条件
非hazard引起的读写口冲突由xbar控制
- 多组件之间需无RAW/WAW/WAR冲突，XABR需要做读写仲裁
清晰功能规划
5
增加指令ost=2
各个master缩短指令间的读取时间，增加指令存储fifo，深度为2。
- 各个master反压cmd指令分发的条件：master ins_fifo_full.

提高NPU指令性能

6
增加同一组件两条drv指令间做无structure hazard处理

当某一功能组件正在执行时，下一条同组件的drv指令无data hazard时不会被阻塞（存在data hazard会阻塞），再下一条同组件的drv指令会被阻塞
特别的：对于NIU组件，不能同时下发两条store指令 [软件插fence可保证]
- 仅针对noc 指令;
-----------------------------------------
额外需要确定点：
- 跨Cluster noc 指令确认》不支持
- Niu axi_id function 确认@刘影  TODO

- 增加drv指令 data hazard 冲突检查。

提高NPU指令性能
7
增加指令序列乱序发射

指令存储fifo增加，对于当前阻塞master_0，但不阻塞master_i指令的情况可以跳过当前指令，去检查后续不阻塞指令并分发。
- 增加指令fifo深度，可以跳过阻塞的指令，发送无structure/data  hazard 阻塞的指令。
- 乱序发射指令最大查询窗口为dRF_DP。
提高NPU指令性能
8
增加多xd=1指令下发

指令存储fifo增加，对于xd=1指令返回乱序的场景，应该也对应增加xd=1的指令返回的包容度。
- cmd 仅返回32bit 返回值
- 增加返回数据深度，数据按照id乱序返回。
- 如果多个返回数据在同一拍有效，会做仲裁处理
提高NPU指令性能
9
增加按tile切分SPAD，Tensor按tile占用
SPAD 结构改变，增加tile颗粒度。

- tile个数参数可配，需为2的整数次幂，最小为1，最大为单个SPAD深度。
适配存储模型修改

10

增加GLSU调用TMU指令和LLSU调用TMU指令同时下发
硬件对于硬件转置单元tmu使用冲突判断转移。
- 指令间需无data hazard，先下发的指令会先占用TMU，直到占用完成才给下一条指令使用；
- 当GLSU指令和LLSU指令同时抢占TMU时，GLSU优先级更高
清晰功能规划
11

增加指令cfg配置信息存储在core_reg
删掉rd_csr nice指令后，将指令配置信息传输至core_reg中。
- 增加core reg 指令cfg对应存储空间。
对齐指令集并保留原有共功能
12
tile冲突：仅支持 起始地址与终止地址之间的地址冲突。即使一条指令直接存在非占用的地址空间，也视为此空间被占用。
tile冲突释放：根据master 传输个tile_rls信号 释放对应的tile。master 仅会释放自己 实际占有的读/写tile，故对于跨过无读写的tile只有当指令结束后，才可以释放[例如：读写tile0,tile2。tile1只有在指令结束后才可以释放]
验证测试corner case出现离散idle场景，但硬件不支持。

- 对齐约束，不支持指令起始地址与终止地址中间非占空间判断。

对齐约束

13
dram冲突：整个dram
指令阻塞关系需要细化
- 对齐地址冲突约束。
对齐约束


2. 总述 
2.1 CMD_Scheduler 微架构
2.1.1 Overview 
暂时无法在飞书文档外展示此内容

2.1.2 子模块功能  
name
function
decode
- 接收CPU下发的指令原语，解析指令中的配置寄存器/基地址/指令类型。
- 解析rd/wr_lmem指令，与spad进行数据交互。
- 存储6组 master [XBAR/NIU/GLSU/LLSU/MPU/VPU] 一条指令
- 分发指令至dispatch/ins_buffer
scoreboard

- 接收cmd decode 模块解析的指令信息，进行指令data hazard/structure hazard判断。
- 记录所有分发但未完成的指令信息以及状态，分发并没有结束指令的状态，判断cfg/drv_buffer 保存指令的状态，选择
  - 对于当拍输入NPU cmd 且 与当前各个master   无data hazard/structure hazard的指令进行选择分发至dsp_en。
  - 对于与当前各个master存在data hazard/structure hazard的指令进行选择分发至ins_buffer。
ins_buffer
- 存储无法直接下发指令的cfg信息/基地址/指令类型信息。
dispatch
- 指令分发至各个master。
cmd_int_perf
- 指令中断检查，指令性能监控。

decode 
暂时无法在飞书文档外展示此内容
- 考虑指令集cfg/pre指令存在时序性，decode 模块  需要根据cfg/pre定义寄存器，保存cfg/pre信息;
- 一条完整的指令需与dispatch/ins_buffer 模块进行指令交互;
- 一条完整的指令需与scoreboard 模块进行 地址/指令类型 等关键数据交互.

scoreboard
暂时无法在飞书文档外展示此内容

- 新指令与指令buffer分发优先级：新指令最高。
- status指令状态记录:
  - statusi 对应 ins_buff_i 的状态，但是id i并不代表指令的先后顺序;
  - 指令buffer分发顺序：id先后顺序分发; 

状态
status3

status2

status1

status0

master  ins

master doing ins

数据冒险
结构冒险
数据冒险
结构冒险
数据冒险
结构冒险
数据冒险
结构冒险
数据冒险
结构冒险
数据冒险
status0
√
√
√
√
√
√
\
\
√
√
√
status1
√
√
√
√
\
\
√
√
√
√
√
status2
√
√
\
\
√
√
√
√
√
√
√
status3
\
\
√
√
√
√
√
√
√
√
√

- 指令数据流：
  - 接收新指令后，先判断最新是否与【指令buffer中的指令 / 各master中的指令】存在【资源 /数据 竞争】;
    - 若无竞争，直接将新指令分发至 dispatch ；
    - 若有竞争，且指令buffer为非满状态，将新指令存入指令buffer，并将当前指令的竞争状态保存在ins_status 模块;
    - 若有竞争，且指令buffer为满状态   ，反压decode指令下发，直至指令buffer非满，将新指令存入指令buffer，并将当前指令的竞争状态保存在ins_status 模块 ;

- 指令buffer更新：
  - 根据ins_buff_xx_vld 确认空余buffer_id;
  - 将当前存在竞争的新指令写入对应id的buffer中，并将该状态同步保存在ins_status;
  - 当master完成一条指令后且无新指令传输时，ins_status 更新指令状态，并选择出无竞争的指令发送至dispatch，对应的指令buffer状态valid更新为0;


2.1.3 CMD_Scheduler 数据流
暂时无法在飞书文档外展示此内容

- CMD 接收 Inst Dispatcher 指令原语，在decode中进行解析 cfg/drv信息，发送至 scoreboard;
- scoreboard 记录接收并未完成的指令信息，检测当前指令与已接收指令是否存在 SHazard 或 DHazard。
  - 若无Hazard，scoreboard 发送 dsp_en=1    至 decode，decode 分发 当前指令信息至dispatch;
  - 若有Hazard，scoreboard 发送 store_en=1 至 decode，decode 分发 当前指令信息至cfg_buffer/drv_buffer ;
- dispatch 根据指令类型，将指令下发至各个master。 
- master 完成指令，发送地址 rtile_rls_vld/wtile_rls_vld 等信息与ins_done 信息至scoreboard，scoreboard更新目前接收指令是否存在 SHazard 或 DHazard。
  - 若新进指令无 SHazard 或 DHazard，发送至dispatch；若存在SHazard 或 DHazard 则存入cfg_buffer / drv_buffer 。
  - 若释放后，cfg_buffer/drv_buffer 存在无Hazard的指令，scoreboard 发送ren_id / ren 至cfg_buffer / drv_buffer。

2.1.4 CMD_Scheduler 反压机制
暂时无法在飞书文档外展示此内容

- decode 模块：存在2深度的指令存储buffer。
- cfg_buffer/drv_buffer 存在4深度的指令buffer。
- master：各个 master 存在2深度的buffer。
- master 指令buffer满，反压cfg_buffer/drv_buffer； cfg_buffer/drv_buffer 指令满时反压decode；decode满时，反压Ins Dispatcher。

模块
深度
wen
ren
cfg/drv_buffer
4
store_en 
 scoreboard_ren

decode_buff
2
指令握手成功
cfg_drv_buffer_not_full

2.1.5 Top Signal
全局信号
Type
Name
Dir
Width
Description
Clk & rstn
clk
input
1
目标700MHz@T22

rst_n
input
1
复位信号，低有效
Clock gating
creg_cmd_icg_en

Input
32
时钟ICG使能信号，
- 1：打开ICG功能，低功耗模式；
- 0：关闭ICG功能，时钟常开
低功耗ICG信号
Type
Name
Dir
Width
Description
For write / read icg
cmd_xbar_ch0_icg_wstart
output
1
cmd ch0的icg信号

cmd_xbar_ch1_icg_rstart
output
1
cmd ch1的icg信号
To master icg
cmd_niu_icg_start
output
1
niu模块预启动，脉冲信号，用于给模块开启时钟

cmd_glsu_icg_start
output
1
glsu模块预启动，脉冲信号，用于给模块开启时钟

cmd_llsu_icg_start
output
1
llsu模块预启动，脉冲信号，用于给模块开启时钟

cmd_vpu_icg_start
output
1
vpu模块预启动，脉冲信号，用于给模块开启时钟

cmd_mpu_icg_start
output
1
mpu模块预启动，脉冲信号，用于给模块开启时钟

Inst dispatch 交互指令信号
Type
Name
Dir
Width
Description
Ins dispatch
disp_cmd_inst

input
2*32+10
指令信号，各bit位含义如下：
- [2          :0        ]：xd, xs1, xs2
- [9          :3        ]：func7
- [ 9+32   :10       ]：rs1val
- [ 9+2*32:10+32 ]：rs2val

disp_cmd_inst_flag
input
1
输入指令类型:
- 0：表示NICE指令
- 1：表示VNICE指令

disp_cmd_vld
input
1
指令valid信号，高有效

cmd_disp_rdy
output
1
指令ready信号，高有效

cmd_disp_rsp_data
output
32+3
指令返回值

cmd_disp_rsp_vld
output
1
指令返回值valid信号，高有效

disp_cmd_rsp_rdy
input
1
指令返回值ready信号，高有效

disp_cmd_inst_tag
input
3
xd=1时的指令id，用于数据保序

spad 交互指令信号
Type
Name
Dir
Width
Description
Status flag

cmd_llsu_xbr_sel_vld

output
2
“read/write lmem指令”/“tensor move”指令状态：
- cmd_llsu_xbr_sel_vld[0] : CMD执行read/write lmem指令状态
  - 1'd0：非 “CMD执行read/write lmem指令” 状态
  - 1'd1：      CMD执行read/write lmem指令 状态
- cmd_llsu_xbr_sel_vld[1] : CMD执行tensor move 指令状态
  - 1'd0：非 “CMD执行tensor move 指令” 状态
  - 1'd1：      CMD执行tensor move 指令 状态
*read/write lmem指令与tensor move 指令不支持并行，故cmd_llsu_xbr_sel_vld只存在
- 2'b00 : 非 “CMD执行read/write lmem指令” && 非 “CMD执行tensor move 指令”
- 2'b01 : CMD执行read/write lmem指令
- 2'b10 ：CMD执行tensor move 指令
write_lmem
cmd_xbr_ch0_req_waddr
output
18
写请求地址

cmd_xbr_ch0_req_wdata
output
512
写请求数据

cmd_xbr_ch0_req_wstrb
output
2
写请求选通信号
- 2'b11：高低256bit数据均有效
- 2'b10：高256bit数据有效
- 2'b01：低256bit数据有效

cmd_xbr_ch0_req_wvld
output
1
写请求valid信号，高有效

cmd_xbr_ch0_req_wrdy
input
1
写请求ready信号，高有效

xbr_cmd_ch0_rsp_wvld
input
1
COMMAND_SCHEDULER 写响应有效信号，高有效

xbr_cmd_ch0_rsp_wlast
input
1
COMMAND_SCHEDULER写响应最后一笔数据的标志位，高有效

cmd_xbr_ch0_rsp_wrdy
output
1
COMMAND_SCHEDULER写响应接收就绪信号，高有效

cmd_xbr_ch0_req_wid_for_dv
output
32
COMMAND_SCHEDULER写请求ID

xbr_cmd_ch0_rsp_wid_for_dv
input
32
COMMAND_SCHEDULER写响应ID
read_lmem
cmd_xbr_ch1_req_raddr
output
44
读请求地址

cmd_xbr_ch1_req_rvld
output
1
读请求valid信号，高有效

xbr_cmd_ch1_req_rrdy
input
1
读请求ready信号，高有效

xbr_cmd_ch1_rsp_rdata
input
512
读响应数据

xbr_cmd_ch1_rsp_rvld
input
1
读响应valid信号，高有效

cmd_xbr_ch1_rsp_rrdy
output
1
读响应ready信号，高有效
For dv
cmd_xbr_ch1_req_rid_for_dv
output
32
COMMAND_SCHEDULER RD1读请求ID

xbr_cmd_ch1_rsp_rid_for_dv
input
32
COMMAND_SCHEDULER RD1读响应ID

niu 交互指令信号 
Type
Name
Dir
Width
Description
NIU
niu_cmd_inst0_done_vld
input
1
niu模块inst0执行结束，脉冲信号

niu_cmd_inst0_rtile_rls_vld
input
1
niu模块inst0读SPAD释放标志，脉冲信号

niu_cmd_inst0_rtile_rls_idx
input
3
niu模块inst0读释放SPAD的index

niu_cmd_inst0_wtile_rls_vld
input
1
niu模块inst0写SPAD释放标志，脉冲信号

niu_cmd_inst0_wtile_rls_idx
input
3
niu模块inst0写释放SPAD的index

niu_cmd_inst0_page_rls_vld
input
1
niu模块inst0 page释放标志，脉冲信号

niu_cmd_inst0_page_rls_idx
input
4
niu模块inst0释放page的index

niu_cmd_inst1_done_vld
input
1
niu模块inst1执行结束，脉冲信号

niu_cmd_inst1_rtile_rls_vld
input
1
niu模块inst1读SPAD释放标志，脉冲信号

niu_cmd_inst1_rtile_rls_idx
input
3
niu模块inst1读释放SPAD的index

niu_cmd_inst1_wtile_rls_vld
input
1
niu模块inst1写SPAD释放标志，脉冲信号

niu_cmd_inst1_wtile_rls_idx
input
3
niu模块inst1写释放SPAD的index

niu_cmd_inst1_page_rls_vld
input
1
niu模块inst1 page释放标志，脉冲信号

niu_cmd_inst1_page_rls_idx
input
4
niu模块inst1释放page的index

cmd_niu_start
output
1
niu模块启动，脉冲信号

cmd_niu_start_inst_id
output
1
niu模块指令启动id，0：启动inst0；1：启动inst1，脉冲信号

cmd_niu_task_select
output
2
2'b01:niu执行load操作；2'b10::niu执行store操作；2'b00：default值

cmd_niu_dst_base_addr
output
44
dest NPU core的基地址

cmd_niu_src_base_addr
output
44
source NPU core的基地址

cmd_niu_cfg_type
output
1
浮点格式数据，1：BF/BBF/FP，default：0

cmd_niu_cfg_wd
output
3
数据位宽，4/8/16..., 其他保留，default：3

cmd_niu_cfg_num_dim0
output
19
Tensor在dim0上的元素个数，default：7

cmd_niu_cfg_size_dim1
output
13
Tensor在dim1上的size大小，default：1

cmd_niu_cfg_size_dim2
output
13
Tensor在dim2上的size大小，default：1

cmd_niu_cfg_src_stride_dim1
output
13
输入tensor在dim1上的步长，default：1

cmd_niu_cfg_src_stride_dim2
output
25
输入tensor在dim2上的步长，default：1

cmd_niu_cfg_dst_stride_dim1
output
13
输出tensor在dim1上的步长，default：1

cmd_niu_cfg_dst_stride_dim2
output
25
输出tensor在dim2上的步长，default：1

glsu  交互指令信号
Type
Name
Dir
Width
Description
GLSU
glsu_cmd_inst0_done_vld
input
1
glsu模块inst0执行结束，脉冲信号

glsu_cmd_inst0_rtile_rls_vld
input
1
glsu模块inst0读SPAD释放标志，脉冲信号

glsu_cmd_inst0_rtile_rls_idx
input
5
glsu模块inst0读释放SPAD的index

glsu_cmd_inst0_wtile_rls_vld
input
1
glsu模块inst0写SPAD释放标志，脉冲信号

glsu_cmd_inst0_wtile_rls_idx
input
5
glsu模块inst0写释放SPAD的index

glsu_cmd_inst0_page_rls_vld
input
1
glsu模块inst0 page释放标志，脉冲信号

glsu_cmd_inst0_page_rls_idx
input
4
glsu模块inst0释放page的index

glsu_cmd_inst0_rdram_rls_vld
input
1
glsu模块inst0读dram释放标志，脉冲信号

glsu_cmd_inst0_rdram_rls_idx
input
4
glsu模块inst0读释放dram的index

glsu_cmd_inst1_done_vld
input
1
glsu模块inst1执行结束，脉冲信号

glsu_cmd_inst1_rtile_rls_vld
input
1
glsu模块inst1读SPAD释放标志，脉冲信号

glsu_cmd_inst1_rtile_rls_idx
input
5
glsu模块inst1读释放SPAD的index

glsu_cmd_inst1_wtile_rls_vld
input
1
glsu模块inst1写SPAD释放标志，脉冲信号

glsu_cmd_inst1_wtile_rls_idx
input
5
glsu模块inst1写释放SPAD的index

glsu_cmd_inst1_page_rls_vld
input
1
glsu模块inst1 page释放标志，脉冲信号

glsu_cmd_inst1_page_rls_idx
input
4
glsu模块inst1释放page的index

glsu_cmd_inst1_rdram_rls_vld
input
1
glsu模块inst1读dram释放标志，脉冲信号

glsu_cmd_inst1_rdram_rls_idx
input
4
glsu模块inst1读释放dram的index

cmd_glsu_start
output
1
glsu模块启动，脉冲信号

cmd_glsu_start_inst_id
output
1
glsu模块指令启动id，0：启动inst0；1：启动inst1，脉冲信号

cmd_glsu_task_select

output
4
glsu模块操作选择信号，其中：
- 4'b0001：tld
- 4'b0010：ttld
- 4'b0011：gather
- 4'b0100：loadcimcexp
- 4'b0101：tensor dma
- 4'b0110：tst
- 4'b0111：storecimcexp

cmd_glsu_src_base_addr
output
44
source core访存基地址

cmd_glsu_dst_base_addr
output
44
dst core访存基地址

cmd_glsu_cfg_mx
output
1
操作数为MX格式的标志，1：表示为MX格式，default：0

cmd_glsu_cfg_type
output
1
操作数为浮点格式的标志，1：表示为FP格式，default：0

cmd_glsu_cfg_mantissa
output
1
用来区分FP8中的E5M2和E4M3，和区分FP16和BF16，default：0 

cmd_glsu_cfg_wd

output
3
数据位宽
- 3'b010：4bit
- 3'b011：8bit
- 3'b100：16bit
- 3'b101：32bit

cmd_glsu_gather_dst_spad

output
1
仅gather指令下指示dst端是local spad or local dram
- 0: local dram 
- 1: local spad

cmd_glsu_cfg_index_base_addr
output
18
gather 指令 index 在本地SPAD的存储地址

cmd_glsu_src_global
output
1
仅gather指令下指示dst端是local spad or local dram
- 1：global
- 0：local

cmd_glsu_dst_global
output
1


cmd_glsu_cfg_num_dim0
output
19
Tensor在dim0上的元素个数

cmd_glsu_cfg_index_num_dim0
output
19
gather指令index用到的dim0操作数数量

cmd_glsu_cfg_size_dim1
output
13
Tensor在dim1上的size大小

cmd_glsu_cfg_size_dim2
output
13
Tensor在dim2上的size大小

cmd_glsu_cfg_src_stride_dim1
output
13
输入Tensor在dim1上的步长

cmd_glsu_cfg_src_stride_dim2
output
25
输入Tensor在dim2上的步长

cmd_glsu_cfg_dst_stride_dim1
output
13
输出Tensor在dim1上的步长

cmd_glsu_cfg_dst_stride_dim2
output
25
输出Tensor在dim2上的步长

llsu 交互指令信号
Type
Name
Dir
Width
Description
LLSU
llsu_cmd_inst0_done_vld
input
1
llsu模块inst0执行结束，脉冲信号

llsu_cmd_inst1_done_vld
input
1
llsu模块inst1执行结束，脉冲信号

llsu_cmd_rtile_rls_vld
input
1
llsu模块读SPAD释放标志，脉冲信号

llsu_cmd_rtile_rls_idx
input
3
llsu模块读释放SPAD的index

llsu_cmd_rtile_rls_inst_id
input
1
llsu模块读释放SPAD的指令ID，0：表示inst0；1：表示inst1

llsu_cmd_wtile_rls_vld
input
1
llsu模块写SPAD释放标志，脉冲信号

llsu_cmd_wtile_rls_idx
input
3
llsu模块写释放SPAD的index

llsu_cmd_wtile_rls_inst_id
input
1
llsu模块写释放SPAD的指令ID，0：表示inst0；1：表示inst1

llsu_cmd_page_rls_vld
input
1
llsu模块page释放标志，脉冲信号

llsu_cmd_page_rls_idx
input
4
llsu模块释放page的index

llsu_cmd_page_rls_inst_id
input
1
llsu模块释放page的指令ID，0：表示inst0；1：表示inst1

llsu_cmd_rls_inst_id
input
1
llsu模块指令释放资源选择指令标志，0：当前指令为inst0；1：当前指令为inst1

cmd_llsu_start
output
1
llsu模块启动，脉冲信号

cmd_llsu_start_inst_id
output
1
llsu模块指令启动id，0：启动inst0；1：启动inst1，脉冲信号

cmd_llsu_base_addr_out
output
18
输出tensor的基地址

cmd_llsu_base_addr_in
output
18
输入tensor的基地址

cmd_llsu_task_select
output
3
操作模式选择，3'b000: bc；3'b001：vbc；3'b010：trans_vbc；3'b011：setCIMExp；3'b100：getCIMExp；3'b101：mov；3'b110：trans

cmd_llsu_scalar_val_in
output
32
广播的标量值

cmd_llsu_cfg_mx
output
1
MX格式使能信号，1: mx data enable，default：0

cmd_llsu_cfg_type
output
1
浮点格式数据，1：BF/BBF/FP，default：0

cmd_llsu_cfg_mantissa
output
1
区分FP8中的E5M2和E4M3；区分FP16和BF16，default：0

cmd_llsu_cfg_wd
output
3
数据位宽，4/8/16..., 其他保留，default：0

cmd_llsu_cfg_num_dim0_in
output
19
输入Tensor在dim0上的元素个数，default：7

cmd_llsu_cfg_num_dim0_trans_vbc_out
output
19
trans_vbc下输出Tensor在dim0上的元素个数，default：7

cmd_llsu_cfg_num_dim0_out
output
19
bc/trans_vbc下输出Tensor在dim0上的元素个数，default：7

cmd_llsu_cfg_size_dim1
output
13
Tensor在dim1上的size大小，default：1

cmd_llsu_cfg_size_dim2
output
13
Tensor在dim2上的size大小，default：1

cmd_llsu_cfg_stride_dim1_out
output
13
输出tensor在dim1上的步长，default：1

cmd_llsu_cfg_stride_dim2_out
output
25
输出tensor在dim2上的步长，default：1

cmd_llsu_cfg_stride_dim1_in
output
13
输入tensor在dim1上的步长，default：1

cmd_llsu_cfg_stride_dim2_in
output
25
输入tensor在dim2上的步长，default：1

vpu 交互指令信号
Type
Name
Dir
Width
Description
VPU

vpu_cmd_inst0_done_vld
input
1
vpu模块inst0执行结束，脉冲信号

vpu_cmd_inst1_done_vld
input
1
vpu模块inst1执行结束，脉冲信号

vpu_cmd_ch1_rtile_rls_vld
input
1
vpu模块ch1读SPAD释放标志，脉冲信号

vpu_cmd_ch1_rtile_rls_idx
input
5
vpu模块ch1读释放SPAD的index

vpu_cmd_ch2_rtile_rls_vld
input
1
vpu模块ch2读SPAD释放标志，脉冲信号

vpu_cmd_ch2_rtile_rls_idx
input
5
vpu模块ch2读释放SPAD的index

vpu_cmd_ch3_rtile_rls_vld
input
1
vpu模块ch3读SPAD释放标志，脉冲信号

vpu_cmd_ch3_rtile_rls_idx
input
5
vpu模块ch3读释放SPAD的index

vpu_cmd_rtile_rls_inst_id
input
1
vpu模块读释放SPAD的指令ID，
- 0：表示inst0
- 1：表示inst1

vpu_cmd_wtile_rls_vld
input
1
vpu模块写SPAD释放标志，脉冲信号

vpu_cmd_wtile_rls_idx
input
5
vpu模块写释放SPAD的index

vpu_cmd_wtile_rls_inst_id
input
1
vpu模块写释放SPAD的指令ID，
- 0：表示inst0
- 1：表示inst1

cmd_vpu_start
output
1
vpu模块启动，脉冲信号

cmd_vpu_start_inst_id
output
1
vpu模块指令启动id，0：启动inst0；1：启动inst1，脉冲信号

cmd_vpu_base_addr_out
output
18
输出tensor的基地址

cmd_vpu_base_addr_in1
output
18
输入tensor1的基地址

cmd_vpu_base_addr_in2
output
18
输入tensor2的基地址

cmd_vpu_base_addr_in3
output
18
输入tensor3的基地址

cmd_vpu_base_addr_mx
output
18
输入MX格式tensor的基地址

cmd_vpu_scalar_data_in1
output
32
输入scalar I1的值

cmd_vpu_scalar_data_in2
output
32
输入scalar I2的值

vpu_cmd_scalar_data
input
32
输出scalar O的值

cmd_vpu_funct_sel
output
3
功能选择信号
- 3'b000: VV_V
- 3'b001: VS_V
- 3'b010: V_S
- 3'b011: V_V
- 3'b100: M_V
- 3'b101:MV_M

cmd_vpu_cfg_mv_m_type
output
1
 mv_m 类型
- 0：vs_v 扩展
- 1：vv_v 扩展

cmd_vpu_cfg_mx_out
output
1
输入矢量Vector1元素MX格式标志, default 0 
- 1'b0: not mx data type 
- 1'b1: mx data type 

cmd_vpu_cfg_mx_in1
output
1


cmd_vpu_cfg_mx_in2
output
1


cmd_vpu_cfg_mx_in3
output
1


cmd_vpu_cfg_mx_an
output
1







cmd_vpu_cfg_type_out
output
1
输入矢量Vector1元素数据精度选择, default 0 
- float_4 
  - 1'b0: f121 
  - 1'b1: f112
- float_8 
  - 1'b0: f152 
  - 1'b1: f143 
- float_16 
  - 1'b0: fp16 
  - 1'b1: bf16

cmd_vpu_cfg_type_in1
output
1


cmd_vpu_cfg_type_in2
output
1


cmd_vpu_cfg_type_in3
output
1


cmd_vpu_cfg_type_an
output
1


cmd_vpu_cfg_mantissa_out
output
1
输入多项式系数MX格式标志
- 1'b0: not mx data type 
- 1'b1: mx data type 


cmd_vpu_cfg_mantissa_in1
output
1


cmd_vpu_cfg_mantissa_in2
output
1


cmd_vpu_cfg_mantissa_in3
output
1


cmd_vpu_cfg_mantissa_an
output
1


cmd_vpu_cfg_wd_out
output
3
输入多项式系数元素数据位宽选择 
- 3'b010: W4
- 3'b011: W8
- 3'b100: W16
- 3'b101: W32

cmd_vpu_cfg_wd_in1
output
3


cmd_vpu_cfg_wd_in2
output
3


cmd_vpu_cfg_wd_in3
output
3


cmd_vpu_cfg_wd_an
output
3


cmd_vpu_cfg_op
output
6
操作模式，default：0

cmd_vpu_cfg_num_dim0
output
19
输入/输出向量在dim0上的元素个数

cmd_vpu_cfg_size_dim1
output
13
输入/输出Tensor在dim1上的size大小

cmd_vpu_cfg_stride_dim1_out
output
13
输出Tensor在dim1上的步长

cmd_vpu_cfg_stride_dim1_in1
output
13
输入Tensor in1在dim1上的步长

cmd_vpu_cfg_satu
output
1
结果是否做饱和处理
- 1'b0：不做饱和
- 1'b1：做饱和

cmd_vpu_cfg_denor_is0
output
1
Denormalized float numbers
- 1'b0: 输出结果不做任何处理
- 1'b1: 输出结果为denor时，结果输出为0.

cmd_vpu_cfg_rm
output
3
Round mode: default：0 3'b000 round to floor 3'b001 round to ceiling 3'b010 round to zero 3'b011 round away from zero 3'b100 round to nearest, tiles to zero 3'b101 round to nearest, tiles to even

cmd_vpu_cfg_ite_num
output
3
输入多项式配置，default：1

cmd_vpu_cfg_poly_an_buf_0
output
16
多项式迭代系数a0

cmd_vpu_cfg_poly_an_buf_1
output
16
多项式迭代系数a1

cmd_vpu_cfg_poly_an_buf_2
output
16
多项式迭代系数a2

cmd_vpu_cfg_poly_an_buf_3
output
16
多项式迭代系数a3

cmd_vpu_cfg_poly_an_buf_4
output
16
多项式迭代系数a4

cmd_vpu_cfg_poly_an_buf_5
output
16
多项式迭代系数a5

cmd_vpu_cfg_poly_an_buf_6
output
16
多项式迭代系数a6

cmd_vpu_cfg_poly_an_buf_7
output
16
多项式迭代系数a7

cmd_vpu_cfg_poly_an_buf_8
output
16
多项式迭代系数a8

cmd_vpu_cfg_poly_an_buf_9
output
16
多项式迭代系数a9

cmd_vpu_cfg_poly_an_buf_10
output
16
多项式迭代系数a10

cmd_vpu_cfg_poly_an_buf_11
output
16
多项式迭代系数a11

mpu 交互指令信号
Type
Name
Dir
Width
Description
MPU
mpu_cmd_inst0_done_vld
input
1
mpu模块inst0执行结束，脉冲信号

mpu_cmd_inst1_done_vld
input
1
mpu模块inst1执行结束，脉冲信号

mpu_cmd_inst0_page_rls_vld
input
1
mpu模块inst0 page释放标志，脉冲信号

mpu_cmd_inst1_page_rls_vld
input
1
mpu模块inst1 page释放标志，脉冲信号

mpu_cmd_ch1_rtile_rls_vld
input
1
mpu模块ch1读SPAD释放标志，脉冲信号

mpu_cmd_ch1_rtile_rls_idx
input
5
mpu模块ch1读释放SPAD的index

mpu_cmd_ch2_rtile_rls_vld
input
1
mpu模块ch2读SPAD释放标志，脉冲信号

mpu_cmd_ch2_rtile_rls_idx
input
5
mpu模块ch2读释放SPAD的index

mpu_cmd_rtile_rls_inst_id
input
1
mpu模块读释放SPAD的指令ID，0：表示inst0；1：表示inst1

mpu_cmd_wtile_rls_vld
input
1
mpu模块写SPAD释放标志，脉冲信号

mpu_cmd_wtile_rls_idx
input
5
mpu模块写释放SPAD的index

mpu_cmd_wtile_rls_inst_id
input
1
mpu模块写释放SPAD的指令ID，0：表示inst0；1：表示inst1

cmd_mpu_start
output
1
mpu模块启动，脉冲信号

cmd_mpu_start_inst_id
output
1
mpu模块指令启动id，0：启动inst0；1：启动inst1，脉冲信号

cmd_mpu_base_addr_mx_in
output
18
输入MX格式tensor的基地址

cmd_mpu_base_addr_wt
output
18
权重tensor的基地址

cmd_mpu_base_addr_out
output
18
输出tensor的基地址

cmd_mpu_base_addr_in
output
18
输入tensor的基地址

cmd_mpu_base_addr_orig
output
18
原始tensor的基地址

cmd_mpu_base_addr_scale
output
18
dq操作系数的基地址

cmd_mpu_cfg_mx_in
output
1
MX格式使能信号，1: mx data enable，default：0

cmd_mpu_cfg_mx_wt
output
1
MX格式使能信号，1: mx data enable，default：0

cmd_mpu_cfg_mx_scale
output
1
MX格式使能信号，1: mx data enable，default：0

cmd_mpu_cfg_type_out
output
1
浮点格式数据，1：BF/BBF/FP，default：0

cmd_mpu_cfg_type_orig
output
1
浮点格式数据，1：BF/BBF/FP，default：0

cmd_mpu_cfg_type_in
output
1
浮点格式数据，1：BF/BBF/FP，default：0

cmd_mpu_cfg_type_wt
output
1
浮点格式数据，1：BF/BBF/FP，default：0

cmd_mpu_cfg_type_scale
output
1
浮点格式数据，1：BF/BBF/FP，default：0

cmd_mpu_cfg_mantissa_out
output
1
区分FP8中的E5M2和E4M3；区分FP16和BF16，default：0

cmd_mpu_cfg_mantissa_orig
output
1
区分FP8中的E5M2和E4M3；区分FP16和BF16，default：0

cmd_mpu_cfg_mantissa_in
output
1
区分FP8中的E5M2和E4M3；区分FP16和BF16，default：0

cmd_mpu_cfg_mantissa_wt
output
1
区分FP8中的E5M2和E4M3；区分FP16和BF16，default：0

cmd_mpu_cfg_mantissa_scale
output
1
区分FP8中的E5M2和E4M3；区分FP16和BF16，default：0

cmd_mpu_cfg_wd_out
output
3
数据位宽，4/8/16..., 其他保留，default：0

cmd_mpu_cfg_wd_orig
output
3
数据位宽，4/8/16..., 其他保留，default：0

cmd_mpu_cfg_wd_in
output
3
数据位宽，4/8/16..., 其他保留，default：0

cmd_mpu_cfg_wd_wt
output
3
数据位宽，4/8/16..., 其他保留，default：0

cmd_mpu_cfg_wd_scale
output
3
数据位宽，4/8/16..., 其他保留，default：0

cmd_mpu_cfg_acc_en
output
1
累加使能信号，default：0

cmd_mpu_cfg_satu
output
1
1'd0:浮点数溢出为inf
1'd1:浮点数溢出为max/min. 

cmd_mpu_cfg_scale_en
output
1
1'd0:不启用反量化
1'd1:启用反量化

cmd_mpu_cfg_num_dim0_in
output
19
输入Tensor在dim0上的元素个数，default：1

cmd_mpu_cfg_num_dim0_out
output
19
输入Tensor在dim0上的元素个数，default：1

cmd_mpu_cfg_size_dim1_in
output
13
输入tensor在dim1上的size大小，default：1

cmd_mpu_cfg_stride_dim1_out
output
13
输出tensor在dim1上的步长，default：1

cmd_mpu_cfg_stride_dim1_in
output
13
输入tensor在dim1上的步长，default：1

cmd_mpu_cfg_stride_dim1_orig
output
13
输出tensor original在dim1上的步长，default：1

中断信号
Type
Name
Dir
Width
Description
Interrupt

creg_cmd_excep_en
input
32
中断使能信号

cmd_creg_int
output
32
CMD模块原始中断信号，脉冲

creg_cmd_mpu_inst0_masked_int
input
32
MPU inst0 mask后的中断使能信号

creg_cmd_mpu_inst1_masked_int
input
32
MPU inst1 mask后的中断使能信号

creg_cmd_vpu_inst0_masked_int
input
32
vpu inst0 mask后的中断使能信号

creg_cmd_vpu_inst1_masked_int
input
32
vpu inst1 mask后的中断使能信号

creg_cmd_glsu_inst0_masked_int
input
32
glsu inst0 mask后的中断使能信号

creg_cmd_glsu_inst1_masked_int
input
32
glsu inst1 mask后的中断使能信号

creg_cmd_llsu_inst0_masked_int
input
32
llsu inst0 mask后的中断使能信号

creg_cmd_llsu_inst1_masked_int
input
32
llsu inst1 mask后的中断使能信号

creg_cmd_niu_inst0_masked_int
input
32
niu inst0 mask后的中断使能信号

creg_cmd_niu_inst1_masked_int
input
32
niu inst1 mask后的中断使能信号

cmd_creg_exce0
output
32
CMD中断信息

cmd_creg_exce1
output
32
CMD中断信息

cmd_creg_exce2
output
32
CMD中断信息

cmd_creg_mpu_exce0
output
32
MPU inst0中断信息

cmd_creg_mpu_exce1
output
32
MPU inst0中断信息

cmd_creg_mpu_exce2
output
32
MPU inst0中断信息

cmd_creg_mpu_exce3
output
32
MPU inst0中断信息

cmd_creg_mpu_exce4
output
32
MPU inst0中断信息

cmd_creg_mpu_exce5
output
32
MPU inst0中断信息

cmd_creg_mpu_exce6
output
32
MPU inst0中断信息

cmd_creg_mpu_exce7
output
32
MPU inst0中断信息

cmd_creg_mpu_exce8
output
32
MPU inst0中断信息

cmd_creg_mpu_exce9
output
32
MPU inst1中断信息

cmd_creg_mpu_exce10
output
32
MPU inst1中断信息

cmd_creg_mpu_exce11
output
32
MPU inst1中断信息

cmd_creg_mpu_exce12
output
32
MPU inst1中断信息

cmd_creg_mpu_exce13
output
32
MPU inst1中断信息

cmd_creg_mpu_exce14
output
32
MPU inst1中断信息

cmd_creg_mpu_exce15
output
32
MPU inst1中断信息

cmd_creg_mpu_exce16
output
32
MPU inst1中断信息

cmd_creg_mpu_exce17
output
32
MPU inst1中断信息

cmd_creg_vpu_exce0
output
32
VPU inst0中断信息

cmd_creg_vpu_exce1
output
32
VPU inst0中断信息

cmd_creg_vpu_exce2
output
32
VPU inst0中断信息

cmd_creg_vpu_exce3
output
32
VPU inst0中断信息

cmd_creg_vpu_exce4
output
32
VPU inst0中断信息

cmd_creg_vpu_exce5
output
32
VPU inst0中断信息

cmd_creg_vpu_exce6
output
32
VPU inst1中断信息

cmd_creg_vpu_exce7
output
32
VPU inst1中断信息

cmd_creg_vpu_exce8
output
32
VPU inst1中断信息

cmd_creg_vpu_exce9
output
32
VPU inst1中断信息

cmd_creg_vpu_exce10
output
32
VPU inst1中断信息

cmd_creg_vpu_exce11
output
32
VPU inst1中断信息

cmd_creg_glsu_exce0
output
32
GLSU inst0中断信息

cmd_creg_glsu_exce1
output
32
GLSU inst0中断信息

cmd_creg_glsu_exce2
output
32
GLSU inst0中断信息

cmd_creg_glsu_exce3
output
32
GLSU inst1中断信息

cmd_creg_glsu_exce4
output
32
GLSU inst1中断信息

cmd_creg_glsu_exce5
output
32
GLSU inst1中断信息

cmd_creg_llsu_exce0
output
32
LLSU inst0中断信息

cmd_creg_llsu_exce1
output
32
LLSU inst0中断信息

cmd_creg_llsu_exce2
output
32
LLSU inst0中断信息

cmd_creg_llsu_exce3
output
32
LLSU inst1中断信息

cmd_creg_llsu_exce4
output
32
LLSU inst1中断信息

cmd_creg_llsu_exce5
output
32
LLSU inst1中断信息

cmd_creg_niu_exce0
output
32
NIU inst0中断信息

cmd_creg_niu_exce1
output
32
NIU inst0中断信息

cmd_creg_niu_exce2
output
32
NIU inst0中断信息

cmd_creg_niu_exce3
output
32
NIU inst0中断信息

cmd_creg_niu_exce4
output
32
NIU inst0中断信息

cmd_creg_niu_exce5
output
32
NIU inst0中断信息

cmd_creg_niu_exce6
output
32
NIU inst1中断信息

cmd_creg_niu_exce7
output
32
NIU inst1中断信息

cmd_creg_niu_exce8
output
32
NIU inst1中断信息

cmd_creg_niu_exce9
output
32
NIU inst1中断信息

cmd_creg_niu_exce10
output
32
NIU inst1中断信息

cmd_creg_niu_exce11
output
32
NIU inst1中断信息

Debug 信号 
Type
Name
Dir
Width
Description
debug
cmd_creg_dbg0
output
32
CMD debug0寄存器

cmd_creg_dbg1
output
32
CMD debug0寄存器

cmd_creg_dbg2
output
32
CMD debug0寄存器

性能监控信号 
Type
Name
Dir
Width
Description
Performance
creg_cmd_perf_en
input
1
性能监测使能信号，电平

creg_cmd_perf_start
input
1
性能监测开始信号，电平

creg_cmd_perf_pause
input
1
性能监测暂停信号，电平

creg_cmd_perf_conti
input
1
性能监测继续信号，电平

creg_cmd_perf_end
input
1
性能监测结束信号，电平

cmd_creg_perf_cnt
output
96
性能监测计数器

SPAD exclusive 信号  
Type
Name
Dir
Width
Description
SPAD exclusive en
creg_cmd_spad_excl_en
input
32

控制MST各个读写通道是否独占访问SPAD，default：32'h0
bit[0]：1：GLSU读通道为独占访问；0：GLSU读通道为非独占访问；
bit[1]：1：GLSU写通道为独占访问；0：GLSU写通道为非独占访问；
bit[2]：1：MPU第一个读通道为独占访问；0：MPU第一个读通道为非独占访问；
bit[3]：1：MPU第二个读通道为独占访问；0：MPU第二个读通道为非独占访问；
bit[4]：1：MPU写读通道为独占访问；0：MPU写通道为非独占访问；
bit[5]：1：VPU第一个读通道为独占访问；0：VPU第一个读通道为非独占访问；
bit[6]：1：VPU第二个读通道为独占访问；0：VPU第二个读通道为非独占访问；
bit[7]：1：VPU第三个读通道为独占访问；0：VPU第三个读通道为非独占访问；
bit[8]：1：VPU写读通道为独占访问；0：VPU写通道为非独占访问；
bit[9]：1：LLSU读通道为独占访问；0：LLSU读通道为非独占访问；
bit[10]：1：LLSU写通道为独占访问；0：LLSU写通道为非独占访问；
bit[11]：1：NIU读通道为独占访问；0：NIU读通道为非独占访问；
bit[12]：1：NIU写通道为独占访问；0：NIU写通道为非独占访问；
bit[31:13]：reserved

预留接口
Type
Name
Dir
Width
Description
预留接口
creg_cmd_reserve_in
Input
128
预留输入接口

creg_cmd_reserve_out
Output
128
预留输出接口
3. 规格阐述 
规格项
规格值
说明
备注
对外接口
- 与SPAD间的数据带宽               ：512bit
- 与Ins dispatch间的读写数据带宽：32 bit
- 与Ins dispatch间的指令数据带宽：75bit
- 通道数量      ：1读1写


指令OST
1
cmd指令仅支持串行，每个周期最多发送一条指令

算力

无


阵列形状
无


存储容量/带宽
无/无
内部无存储单元

数据精度
FP32/FP16/BF16/F143/F152/FP4
Int32/Int16/Int4
MXFP8/MXFP4/MXINT8/MXINT4
cmd模块只传输指令信息中配置的数据精度，并不会创造精度。

时钟
700MHz TBD
参考文件：[HM057]-AI System-NPU Arch Spec

电压
 0.9V     TBD
参考文件：[HM057]-AI System-NPU Arch Spec

工艺节点
TT 85C  TBD
参考文件：[HM057]-AI System-NPU Arch Spec

功耗
TBD
参考文件：[HM057]-AI System-NPU Arch Spec

面积
0.04mm^2
参考文件：[HM057]-AI System-NPU Arch Spec

4. Feature List 
Feature 名称
功能描述与边界
支持各个功能组件的信息配置和启动
- 各个master指令分发由CMD控制输出.
- master分组：MPU、VPU、GLSU、LLSU和NIU.
支持各个功能组件的信指令outstanding=2
- 各个master 指令存储深度为2.
支持指令间的sync同步
- sync_drv指令与所有组件存在SHazard，阻塞后续所有指令下发。
支持NIU指令间的同步
- noc_fence_drv指令与后续所有noc指令均存在SHazard，阻塞后续所有noc指令下发。
支持CPU读写LMEM(SPAD)
- wr_lmem_drv和rd_lmem_drv指令相关，每次操作数据位宽32bit
- 指令地址支持32bit 对齐。
支持CPU读写LMEM与LLSU指令间做SHazard处理
- 考虑硬件结构，wr/rd_lmem_drv指令与LLSU指令存在SHazard.

支持GLSU内部load和store操作并行执行
- load和store操作需要无data hazard.

支持当前接收指令的data hazard 指令阻塞
- 支持硬件存储所有接收但没有结束的指令data hazard 判断.
- 包含在master中存储的指令 与 ins_buffer中存储的指令.
支持按tile切分SPAD，Tensor按tile占用
tile个数参数可配，需为2的整数次幂，最小为1，最大为单个SPAD深度
支持多组件访问同一SPAD
多组件之间需无RAW/WAW/WAR冲突，XABR需要做读写仲裁
支持指令序列乱序发射
- 乱序发射指令最大查询窗口为ins_buffer
支持多xd=1指令下发
- 数据乱序返回，如果多个返回数据在同一拍有效，会做仲裁处理
支持GLSU调用TMU指令和LLSU调用TMU指令同时下发
- 指令间需无data hazard，先下发的指令会先占用TMU，直到占用完成才给下一条指令使用；
- 当GLSU指令和LLSU指令同时抢占TMU时，GLSU优先级更高
删除creg_cmd_icg_en[5:0]信号
- 不再对各模块进行低功耗控制，改由各模块自己控制
删除各组件低功耗模式
- 不再对各模块进行低功耗控制，改由各模块自己控制



5. 约束  
- 满足指令集中的指令组合;
- 满足指令集中对应指令的数据精度组合;
*详细约束可以参考 软件编程指导 [HM057]-CMD_Scheduler Arch Spec

- fence/sync 负责收集指令完成状态;
- 满足fence/sync指令阻塞向下分发; 【dispatch】
6. 低功耗设计 

6.1 时钟门控
暂时无法在飞书文档外展示此内容

模块
open
close
cmd_int_perf
打开中断/性能监控功能
关闭中断/性能监控功能
decode
scoreboard
ins_buff
dispatch

接收指令原语开始
指令fifo为空&&master 所有指令已经回done

6.2 电源域划分与开关/DVFS/存储低功耗 
  - CMD 电压域划分域开关/DVFS/存储低功耗与NPU相同，故不在此章节设计。【后续贴NPU的设计链接】
6.3 功耗估算
- 估算功耗类型：
  - 静态功耗（漏电功耗）：
    - 公式：$$P=VI_l$$
    - 基于工艺库（Library）在特定PVT（工艺、电压、温度）条件下的漏电参数进行估算。
  
  - 动态功耗：
    - 公式 ：$$P=aCV^2f$$
    - 通过EDA工具（如PrimePower/PTPX），结合RTL仿真生成的SAIF/VCD翻转率文件进行精确估算。
  - 模版
模块
动态功耗
静态功耗
频率
工艺参数















  
- 目标值制定：
  - Ideal 功耗：空闲动态功耗、静态功耗、总功耗。
  - Max 功耗 ： 满负载平均功耗、指定时间窗口内峰值功耗。
  - Ideal_2_Max 功耗：从空闲唤醒，快速进入满负载时间段的平均功耗。
  - Max_2_Ideal 功耗：停止新任务，排空流水线时间段间的平均功耗。
  - 指令功耗：按真实指令比例、利用率及空闲比例运行的平均功耗。
- 模版
指令
Ideal 
Max
Ideal_2_Max
Max_2_Ideal
指令功耗




















7. 软件编程指导 

7.1 指令组合
cmd为指令调度模块，其指令分发包含所有指令，可参考下表指令组合：
*cfg、pre指令原语在每条指令中不需要均更新。
模块
指令组合
ctrl
[HM057]-[ISA]-指令原语-指令组合
noc
[HM057]-[ISA]-指令原语-指令组合
tld_tst
[HM057]-[ISA]-指令原语-指令组合
tmu
[HM057]-[ISA]-指令原语-指令组合
mpu
[HM057]-[ISA]-指令原语-指令组合
vpu
[HM057]-[ISA]-指令原语-指令组合

7.2 指令约束
- 所有指令 funct7，xd, xs1, xs2，opcode 与指令集对齐且唯一;
- 数据搬运指令 输入/输出 数据类型一致;【例如：Noc/Glsu/Llsu 指令】
  - 输入/输出 数据精度cfg一致;
  - num_dim0 保持一致;
  - tensor数据 in/out_stride 单独配置;
- 数据计算单元，根据数据指令类型确认有效参数并各参数的数据精度遵循数据精度
  - [HM057]-[ISA]-指令数据精度
- vnice指令 在rs1val有效时，仅配置第一组rs1val[31:26] 为group_mask;
- vnice指令 在rs1val无效且rs2val有效时，仅配置第一组rs2val[31:26] 为group_mask;
7.3 特殊约束
7.3.1 ctrl 
- 无配置寄存器;
指令名称
约束类型
group_mask_drv_xn
- rs1val[31:16]高16bit对指令无影响;
- rs1val[15:0 ] 在xd=1的指令中，最多存在1bit为非0
npu_cfg_drv_xn
- rs1val[31:16]: address of cfg_reg 仅存在指令配置寄存器的组合
  - {rs1val[31:24], rs1val[31:24]} 组合约束
- {rs1val[15:0],rs2val[31:0]}: bits_val of cfg_reg 仅存在指令配置寄存器的组合
  - {rs1val[31:24], rs1val[31:24]}  确定时，数据值必须与寄存器表一致
wr_lmem_drv_xn
- 地址32bit对齐;
- rs1val[31:28] 无效;
rd_lmem_drv_xn
- 地址32bit对齐;
- rs1val[31:28] 无效;
sync_drv_xn
- 阻塞后续指令分发;
fast_sync_drv_xn
- 阻塞后续指令分发;

7.3.2 noc 
- noc指令的cfg寄存器配置适配于dest / sorce核;
指令名称
约束类型
noc_dst_drv_xn
- 仅配置destination address;
- 用于跨cluster spad 数据传输;
- 必须与noc_src_drv_xn配对出现;
noc_src_drv_xn
- 配置sorce核与destination 核地址信息;
- 用于跨cluster spad 数据传输;
- 必须与noc_dst_drv_xn配对出现;
noc_drv_xn
- 配置sorce核与dest 核地址信息;
- 仅支持1对1传输;
- 仅支持同cluster传输;
noc_fence_drv_xn
- 阻塞后续noc指令分发;
fast_noc_fence_drv_xn
- 阻塞后续noc指令分发;
noc_drv_vn01
- 仅配置第一组rs1val[31:26] 为group_mask;
- 相同 vnice-group 1条指令配置 sorce核与destn 核地址信息;
- 不同相同 vnice-group 需要2条指令配置 sorce核与destn 核地址信息;
noc_drv_vn11
- 仅配置第一组rs1val[31:26] 为group_mask;
- 相同 vnice-group 1条指令配置 sorce核与destn 核地址信息;
- 不同相同 vnice-group 需要2条指令配置 sorce核与destn 核地址信息;

7.3.3 tld_tst 
- tld_tst 指令分为本核与跨核指令;
- tld_drv_xn/tst_drv_xn/gtld_drv_xn/gtst_drv_xn 指令仅在地址位cimc时，cfg_exp_mode 有效;
- gat2dram_drv_xn / gat2dram_drv_xn / gat2gdram_drv_xn 指令，cfg_gat_base_addr / cfg_gat_base_addr_id / cfg_index_num_dim0 为 必配选项;

指令名称
约束类型
die_cluster_rs1_pre_xn
- 用于全局地址补充高位cluster_id/die_id 信息;
- 建议本核指令不要配配置此指令;【本核指令配置也无影响】
die_cluster_rs2_pre_xn
- 用于全局地址补充高位cluster_id/die_id 信息;
- 建议本核指令不要配配置此指令;【本核指令配置也无影响】

7.3.4 tmu 
- bc指令 无cfg_size_dim1/cfg_size_dim2 输入配置，则使用cfg_size_dim1/cfg_size_dim2 配置输出;

7.3.5 mpu 
- 计算数据精度必须满足数据精度约束.
- [HM057]-[ISA]-指令数据精度
7.3.6 vpu
- cfg_op_mode 必须在有效范围内，且各组寄存器配置必须遵守数据精度约束;
- [HM057]-[ISA]-指令数据精度

7.4 指令使用示例【VPU】：
[HM057]-VPU Arch Spec

8. 异常与错误处理
列出可能出现错误/异常：错误类型/触发条件/检测机制/上报路径/恢复策略。覆盖指令错误、数据错误、协议错误、超时等；错误码需有统一定义表。
错误类型
触发条件
检测机制
上报路径
恢复策略
硬件实现等级
指令错误
指令配置信息与指令集不匹配
- func7，func3，opcode组合不匹配
- read/write_lmem指令目的地址是否为spad。
译码逻辑/中断检查
读取core_reg (状态寄存器)
软件重新配置正确指令，重置队列
P0
协议错误
总线握手失败（如AXI响应超时/非法响应）、跨SPAD块访问
总线协议检查器/边界检测逻辑
错误中断 + 总线错误寄存器
复位总线接口，重新发起传输
P0
超时

指令执行周期超过看门狗阈值；DMA搬运无响应
硬件看门狗定时器 (WDT)
触发致命中断（NMI/IRQ）
硬件自动强制停止执行；软件复位模块，清理流水线
P1

系统/硬件异常
不可纠正的ECC错误；电压异常；时钟丢失
硬件监控单元/传感器
致命错误中断
触发系统级复位（Warm Reset/冷启动）
P1
9. 性能指标与验收口径 

指标须可测量、口径明确：指标名/定义与计算口径/目标值/测试条件/备注。区分峰值与典型场景；统计口径注明（P50/P95、冷启动/稳态、是否包含排队）。目标与「需求来源输入」对齐。
指标
定义与计算口径
目标值
测试条件
备注
典型场景分发吞吐率

每周期成功分发的指令数。
公式：指令数/ 周期数
1 条/ cycle
- 轮询配置master指令，且指令无DHazard ;
- 指令数据量选择小参数，建议挑选6个周期内可以完成的指令。
- 在配置第一次的cfg/pre后，仅仅发送drv指令






10. 调试验证考虑

①可观测性：debug 寄存器、计数器、log/事件上报、断言；②测试激励：针对 Feature List 与约束的用例清单；③覆盖率目标与验证团队约定；④仿真与 FPGA/样片调试手段。
10.1 可观测性设计（Observability）
核心目标：当系统出现异常或性能不达标时，软硬件工程师有足够的“窗口”定位问题。
- Debug寄存器：
  - 记录各个功能组件是否处于busy状态;
  - cfg 指令原语计算器; 
  - drv 指令原语计算器; 
  - pre 指令原语计算器;  @牛云飞 
- 性能计数器（Performance Counters）：
  - 每个周期同时在执行的功能部件数，该数据会在性能监控期间进行累加，以统计平均并行度；
  - 每个周期MPU是否在执行，该数据会在性能监控期间进行累加，以统计MPU平均并行度；
  - 每个功能部件对应的指令在ins_buffer中的数量，以统计指令的拥塞程度；
  - Ins Primative fifo 满状态监控;【新增 监控Ins buffer 深度是否合理，如果时间占比时间太长，可以增加深度】 【16bit】
  - Ins buffer 满状态监控; 【新增 监控Ins buffer 深度是否合理，如果时间占比时间太长，可以增加深度】 【16bit】 @牛云飞 
- Log/事件上报（Trace & Events）：
  - 软件上报错误信息
- 硬件断言（Assertions）：
  - 初始化寄存器应为0，可在指令拉高时加断言检查CMD内部所有计算器为0。
  - 初始化FIFO应为empty状态，可在指令拉高时加断言检查CMD内部所有fifo为empty。
10.2 测试激励设计（Test Stimulus）
- 所有指令类型
  - drv指令遍历;
  - drv对应的cfg/pre组合遍历测试;
  - drv依赖原配置cfg/pre连续发出15+，测试cmd对于连续指令分配的抗压边界;
  - 并行指令连续组合分发

10.3 覆盖率目标与验证团队约定（Coverage & Sign-off）
- 代码覆盖率（Code Coverage）：
  - 语句覆盖率（Statement） 均达到100% ;
  - 分支覆盖率（Branch）均达到100%      ;
  - 条件覆盖率（Condition）均达到100%  ;
  - 翻转覆盖率（Toggle）均达到100%      。
- 功能覆盖率（Functional Coverage）：
  - 基于Feature List定义Covergroup 
    - 配置组合覆盖
    - 状态机状态转移覆盖
    - 异常注入覆盖
    - 性能档位覆盖
- 断言覆盖率（Assertion Coverage）：
  - 确保所有植入的断言在测试中至少被触发一次。
- 约定与豁免机制：
  - 与验证团队约定Sign-off标准（如功能覆盖率>95%，未覆盖部分需逐条Review并签署豁免书）。
  - 约定回归测试（Regression）的周期与通过率标准（如必须100% Pass）。

10.4 仿真与 FPGA/样片调试手段（Debug Methodologies）
阶段
方法
标准
仿真阶段

- UVM验证平台 + 波形分析（Verdi/DVE）
- C/C++参考模型（Golden Model）与RTL联合仿真，自动比对计算结果
- 事务级调试（Transaction-level Debugging），快速定位软硬件接口错误。
PASS率100%
FPGA/硬件加速阶段
- 使用Palladium/Zebu等硬件加速器，或Xilinx VU19P等FPGA平台
- 运行真实的软件栈（驱动 + Runtime + 算子），验证系统级性能与并发调度
- 通过片上逻辑分析仪（ILA）抓取长序列波形，复现仿真中难以遇到的长尾问题
PASS率100%
样片Bring-up阶段
- 通过JTAG/SWD接口读写寄存器、执行内存Dump。
- 利用片上Trace（如ETM/ETB）记录指令执行流。
- 使用外部逻辑分析仪（LA）或示波器抓取总线时序，验证物理层信号完整性。
PASS率100%


11. 待决问题与风险
记录尚未决策的问题与风险，评审时逐条关闭，避免悬而未决影响后续设计。
问题
影响
决策点
截止时间
负责人
















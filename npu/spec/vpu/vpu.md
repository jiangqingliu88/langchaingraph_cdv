1.  版本更新记录 ﻿            版本号   日期  说明  修改人   v2.2  2025/12/10  1.  增加compare逻辑数据输出格式   李xxx   v2.1  2025/11/18  1.  增加VPU_TOP架构图。  2.  增加数据类型。  3.  增加data_top架构图。  4.  增加data存储分析内容。   李xxx   v2.0  2025/11/03  1.  CDD文件增加子模块架构。   李xxx   v1.0  2025/09/25  1.  初版CDD。   李xxx      ﻿ ﻿
 2. Terminology & Abbreviation ﻿        Name  Descriptiom   SIMD  Single Instruction Multiple Data   VPU  Vector Processing Unit   VPE  Vector Processing Engine   VV_V  Vector Vector SIMD   VS_V  Vector Scalar SIMD   V_V  Vector Type Convert   V_S  Vector Reduce   denor  Denormal number   nor  Normal number   inf  Infinity   Nan  Not a number   denor_is0  Treat denormal number as zero   Nor_op  Normal number   F2F  Float to int conversion   F2I  Float to float conversion   I2F  Int to Float conversion   M2I  MX to Int   M2F  MX to Float   F2M  Float to MX   I2M  Int to MX    Vector 0  Operand0    Vector 1  Operand1    Vector O  Result      ﻿ ﻿
 3. VPU_Top      VPU用于执行复杂激活函数等非线性计算，以及数据类型转换等向量操作。就功能而言，NPU中的VPU可以视为基于RV-V的部分裁剪、添加和限制，以更加符合当前场景需求。 ﻿
 3.1 Overview  VPU接收寄存器配置指令，根据指令类型以及地址信息，通过r0_channel，r1_channel读取SPAD的数据。在接受到数据后，data_top模块根据寄存器配置的指令信息对操作数进行拼接与扩展等处理，然后将处理后的数据传输至vpe_top模块进行计算，vpe_top计算结果再传输至data_top，最后根据指令类型选择将计算结果传输至w0_fifo或者再传输至vpe_top做计算。最后，指令计算结果通过w0_channel写入SPAD。 ﻿
 ﻿﻿   ﻿ ﻿
 ﻿
 3.2 Parameters ﻿              Type  Name  Constraint  Default  Descriptions   RISC-V  RV_LEN  32,64  32  RISC-V寄存器宽度   SPAD 
﻿  SPAD_NUM  
﻿  6  Local memory中包含的SPAD数量   SPAD_BANK_NUM  
﻿  1  每个SPAD中包含的Memory Bank数量   SPAD_WD  
﻿  512  SPAD的数据宽度   SPAD_DEPTH  ﻿
  512  SPAD的数据深度   SPAD_BANK_DP  
﻿  32KB  SPAD中每个Bank的存储容量   Local Memory (SPAD+CIM)  LMEM_WD  
﻿  512  SPAD和CIMC的统一数据位宽   LMEM_ADDR_WD  
﻿  32  基于SPAD和CIMC组成的LMEM的寻址位宽 ﻿
   VPU  VPE_NUM  
﻿  16  Vector Processing Engine (VPE)个数      ﻿ •  软件配置颗粒度为256bit，其中维度参数均以256bit为一个单元。  •  vpu硬件设计位宽为512bit。   3.3 Top Signal ﻿                Type  Name  Dir  Width   Form   Descriptions   clk & rst_n  clk_i  Input  1  Pulse  Target frequency: 500MHz@T22 ULL   rst_n  Input  1  Pulse  Async reset, active low   Configuration SIgnals 
﻿  cfg_type_out  Input  2  Level   Vector O data type •  2‘b00: INT    •  2'b01:  FP   •  2'b10:  BF    •  2'b11:  BFF    cfg_wd_out  Input  3  Level 
﻿   Vector O data width,  other reserved •  3'b010: W4   •  3'b011: W8   •  3'b100: W16   •  3'b101: W32    cfg_exp_wd_out  Input  2  Level   Vector O exp width,  other reserved •  2'b11: W8     cfg_type_in1  Input  3  Level  Vector0  data type •  3‘b000: INT    •  3'b001:  FP  (F152)  •  3'b010:  BF    •  3'b011:  BFF (F143)  •  3'b100: MX+INT  •  3'b101: MX+FP  (FP152)  •  3'b111: MX+FP8 (FP143)  •  3'b110: MX+BF    cfg_wd_in1  Input  3  Level  Vector 0  data width,  other reserved •  3'b010: W4   •  3'b011: W8   •  3'b100: W16   •  3'b101: W32    cfg_exp_wd_in1  Input  2  Level   Vector 0 exp width,  other reserved •  2'b11: W8     cfg_type_in2  Input  3  Level  Vector1  data type •  3‘b000: INT    •  3'b001:  FP  (F152)  •  3'b010:  BF    •  3'b011:  BFF (F143)  •  3'b100: MX+INT  •  3'b101: MX+FP  (FP152)  •  3'b111: MX+FP8 (FP143)  •  3'b110: MX+BF    cfg_wd_in2  Input  3  Level  Vector1  data width,  other reserved •  3'b010: W4   •  3'b011: W8   •  3'b100: W16   •  3'b101: W32    cfg_size_dim0_in1  Input  16  Level  Dim0 size of transferred Vector 0   cfg_rem_dim0_in1  Input  5  Level  Dim0 reminder of transferred Vector 0   cfg_size_dim0_in2  Input  16  Level  Dim0 size of transferred Vector 1   cfg_rem_dim0_in2  Input  5  Level  Dim0 reminder of transferred Vector 1   cfg_size_dim0_out  Input  16  Level  Dim0 size of transferred Vector O   cfg_rem_dim0_out  Input  5  Level  Dim0 reminder of transferred Vector O   cfg_op  Input  6 
﻿  Level  Operation mode Add/Subtract:
6'b000_000: add
6'b000_001: sub
6'b000_010: rsub
Min/Max:
6'b001_000: min
6'b001_001: max
Compare:
6'b010_000: equal
6'b010_001: not equal
6'b010_010: greater
6'b010_011: greater or equal
6'b010_100: less
6'b010_101: less or equal
Shift:
6'b011_000: left
6'b011_001: right
Bitwise logical
6'b100_000: and
6'b100_001: or
6'b100_010: xor
Mul:
6'b101_000: mul 6'b101_001: mac   cfg_funct_sel 
﻿  Input  2  Level  Function selection signal: •  2'b00: VV_V    •  2'b01: VS_V  •  2'b10: V_S     •  2'b11: V_V    cfg_satu  Input  1  Level  Saturate •  1'b1: Results do saturate  •  1'b0: Results as it is    cfg_dis0  Input  1  Level  Denormalized floating-poin  treat •  1'b1:  treated as 0  •  1'b0:  as it is    cfg_rm  Input  3  Level  Round mode •  3'b000 round to floor       •  3'b001 round to ceiling   •  3'b010 round to zero    •  3'b011 round away from zero    •  3'b100 round to nearest, ties to zero   •  3'b101 round to nearest, ties to even      cfg_bypass  Input  1  Level  Bypass •  1'b0 normal computation  •  1'b1 bypass vector1（no computation）    Base Address 
﻿  byte_base_out  Input  LMEM_ADDR_WD  Level  Base byte address of Vector O   byte_base_out_vld  Input  1  Pluse  Base byte address Valid of Vector O •  1'b1 非MX数据基地址    •  1'b0 MX数据共享指数基地址     byte_base_in1  Input  LMEM_ADDR_WD  Level  Base byte address of Vector 0   byte_base_in1_vld  Input  1  Pluse  Base byte address Valid of Vector 0 •  1'b1 非MX数据基地址    •  1'b0 MX数据共享指数基地址     byte_base_in2  Input  LMEM_ADDR_WD  Level  Base byte address of  Vector 1   Data signal   scalar_data_in2  Input  RV_XLEN  Level  Value of input Scalar 2   scalar_data_o  Output  32  Level  Value of output Scalar O   Start-Done Signals 
﻿  start_i  Input  1  Pulse  Start signal, one cycle pulse   done_o  Output  1  Pulse  Done signal, one cycle pulse   Access Channel ch0_wr 
﻿  ch0_wr_req_addr_o  Output  LMEM_ADDR_WD  Pulse  Write addr   ch0_wr_req_data_o  Output  LMEM_WD  Pulse  Write data   ch0_wr_req_flag_o 
﻿  Output  1  Pulse   Flag signal: •  1'b1: last w_data  •  1'b1: not last w_data     ch0_wr_req_valid_o  Output  1  Pulse  Write address and write data valid   ch0_wr_exp_valid_o  Output  1  Pulse  Write exp data valid   ch0_wr_req_ready_i  Input  1  Pulse  Write address and write data ready   ch0_wr_ack_valid_i  Input  1  Pulse  Deallocation feedback  valid   ch0_wr_req_strobe_o  output  2  Pulse  2'b01 : 低256bit有效 2'b10 : 高256bit有效 2'b11 : 高低256bit有效，即512bit全有效 2'b00 : 高低256bit均无效   ch0_wr_ack_ready_o  Output  1  Pulse  Deallocation feedback ready   Access Channel ch1_rd 
﻿  ch1_rd_req_addr_o  Output  LMEM_ADDR_WD  Pulse  Read address   ch1_rd_req_valid_o  Output  1  Pulse  Read address valid   ch1_rd_req_ready_i  Input  1  Pulse  Read address ready   ch1_rd_exp_valid_i  Input  1  Pulse  Read exp data valid   ch1_rd_ack_data_i  Input  LMEM_WD  Pulse  Read data   ch1_rd_ack_valid_i  Input  1  Pulse  Read data valid   ch1_rd_ack_ready_o  Output  1  Pulse  Read data ready   Access Channel ch2_rd 
﻿  ch2_rd_req_addr_o  Output  LMEM_ADDR_WD  Pulse  Read address   ch2_rd_req_valid_o  Output  1  Pulse  Read address valid   ch2_rd_req_ready_i  Input  1  Pulse  Read address ready   ch2_rd_ack_data_i  Input  LMEM_WD  Pulse  Read data   ch2_rd_ack_valid_i  Input  1  Pulse  Read data valid   ch2_rd_ack_ready_o  Output  1  OP1  Read data ready      ﻿ ﻿
 4. VPU_Sub 4.1 data_top  1）架构图 ﻿﻿   ﻿ 2) SPAD存储模型 NPU核内部含有6个SPAD，每块SPAD位宽为512bit，深度为512。VPU主要从SPAD中读取操作数，并将计算结果输出至SPAD。 ﻿﻿   ﻿ 3) VPU_ADDR NPU addr定义32bit，full addr解析如下图所示。 ﻿﻿   ﻿ ﻿
 4) fifo存储计算 由于软件配置数据位宽的颗粒度为256bit，硬件设计为512bit，在地址计算时需要考虑非对齐的情况写入r_fifo，以及如何写入w_fifo。具体情况分析如下图所示。、 1.  op_prec not less & w_l256   ﻿﻿   ﻿ ﻿
 2.  op_prec not less & w_h256bit   ﻿﻿   ﻿ 3.   op_prec less   ﻿﻿   ﻿ 4.3 cmd_top  4.4 f2m_top  4.5 check_top 1）架构图 ﻿﻿   ﻿ 2）function ﻿ https://pingcode.nanocorechip.com/wiki/spaces/HMJ/pages/Z9EW3yQH#TGEQG ﻿ 4.6 vpe_top   1. vpe_cunt  ﻿
 5. 指令计算 VPN主要完成单一维度的向量计算，包括SIMD计算和Reduce计算。主要支持add，sub，rsub，max， min，equal，greater，greater or equal，data convert，and，or，xor等运算，支持VV_V，VS_V，V_V，V_S，M_V等指令。 5.1 伪代码 Add 运算  ﻿      def float_add(a, b，satu，denor_is_0) :       A=0, if (exp(a)=0) & denor_is_0 else A=a      B=0, if (exp(b)=0) & denor_is_0 else B=b     return satu(A+B) if satu else (A+B)   def int_add(a,b) :    return a+b      ﻿ ﻿
 Sub运算  ﻿      def float_sub(a, b，satu，denor_is_0) :       A=0, if (exp(a)=0) & denor_is_0 else A=a      B=0, if (exp(b)=0) & denor_is_0 else B=b   return satu(A-B) if satu else (A-B)   def int_sub(a,b) :    return a-b      ﻿ Mul运算 ﻿      def mul(a, b，satu，denor_is_0) :    A=0, if (exp(a)=0) & denor_is_0 else A=a   B=0, if (exp(b)=0) & denor_is_0 else B=b   return satu(A*B) if satu else (A*B)   def int_mul(a,b) :    return A*B      ﻿ ﻿
 Mac运算 ﻿      def mac(a, b, c, satu, denor_is_0) :    A=0, if (exp(a)=0) & denor_is_0 else A=a   B=0, if (exp(b)=0) & denor_is_0 else B=b   C=0, if (exp(c)=0) & denor_is_0 else C=c   return satu(A*B+C) if satu else (A*B+C)      ﻿ ﻿
 Max运算 ﻿      def max(a, b) :   return a if a > b else b      ﻿ ﻿
 Min运算  ﻿      def min(a, b) :       return a if a < b else b      ﻿ ﻿
 Equal运算  ﻿      def equal(a, b) -> int:   return 1 if a = b else 0      ﻿ ﻿
 Not Equal运算  ﻿      def not_equal(a, b) -> int:      return 1 if a != b else 0      ﻿ ﻿
 Greater运算  ﻿      def equal(a, b) -> int:       return 1 if a > b else 0      ﻿ ﻿
 Greater or equal运算 ﻿      def great_or_equal(a, b) -> int:       return 1 if a >= b else 0      ﻿ Less运算  ﻿      def less(a, b) -> int:   return 1 if a < b else 0      ﻿ Less or equal运算  ﻿      def less_or_equal(a, b) -> int:       return 1 if a <= b else 0      ﻿ Or运算 ﻿      def or(a, b, w):   a = a & ((1 << w) - 1)     b = b & ((1 << w) - 1)     result = a | b              return result      ﻿ Xor运算  ﻿      def xor(a, b, w):   a = a & ((1 << w) - 1)     b = b & ((1 << w) - 1)     result = a ^ b              return result      ﻿ And运算   ﻿      def and(a, b, w):   a = a & ((1 << w) - 1)         b = b & ((1 << w) - 1)         result = a & b                  return result      ﻿ Shift运算  a: 移位数操作数 d: 移位数 c: 移位方向  =1 rd_mode: 右移取舍模式 ﻿      def shift(a, d, c, rd_moude):   return a<<d if  c=1    else rd_mode(a>>b )               ﻿ F2F运算  ﻿      def f2f(a, a_type, res_type, rd_mode, satu, denor_is0):   a_value   = decode(a, a_type,denor_is0)        #按照数据类型以及denor_is0配置转换a值   res_value = float(res_type,a_value,rd_mode)  #将a值按照result数据类型以及rd_mode输出   return satu(res_value) if satu=1                    #饱和处理   else res_value      ﻿ F2I运算  ﻿      def f2i(a, a_type, res_type, rd_mode, denor_is0):   a_value   = decode(a, a_type,denor_is0)           res_value = int(res_type,a_value,rd_mode)        return res_value      ﻿ I2F运算  ﻿      def i2f(a, a_type, res_type, rd_mode, denor_is0):   a_value   = decode(a, a_type)           res_value = float(res_type,a_value,rd_mode,  denor_is0)  #对取舍后的计算结果做denor_is0处理    return satu(res_value) if satu=1                      else res_value      ﻿ ﻿
 F2M运算  ﻿      def f2m(a, a_type, res_type, rd_mode, denor_is0):   a_value   = decode(a, a_type,denor_is0)           res_value = mx(res_type,a_value,rd_mode)    return satu(res_value) if satu=1                      else res_value      ﻿ ﻿
 I2M运算  ﻿      def i2m(a, a_type, res_type, rd_mode):   a_value   = decode(a, a_type)           res_value = mx(res_type,a_value,rd_mode)   return satu(res_value) if satu=1                      else res_value      ﻿ ﻿
 M2F运算  ﻿      def m2f(a, a_type, res_type, rd_mode, denor_is):   a_value   = decode(a, a_type)           res_value = float(res_type,a_value,rd_mode, denor_is)   return satu(res_value) if satu=1                      else res_value      ﻿ ﻿
 M2I运算  ﻿      def m2i(a, a_type, res_type, rd_mode, denor_is):   a_value   = decode(a, a_type)           res_value = int(res_type,a_value,rd_mode)   return satu(res_value) if satu=1                 else res_value      ﻿ ﻿
 ﻿
 5.2 指令数据精度约束 VV_V指令        VV_V操作完成如下三步骤操作:   Step1: 根据byte_base_in1，byte_base_in2，分别从LMEM中读出两个长度相同的一维向量 Vector I1，I2.   Step2: 将两个向量读出，并逐个元素进行SIMD计算后，输出长度相同的输出向量 Vector O.   Step3: 根据byte_base_out 将 Vector O 写入Local Memory中，结束执行。       VV_V指令主要支持Add/Sub，Mul，Max/Min，Shift，CMP，Bitwise 指令类型。 ﻿                  prec\op  Add/Sub  Mul  Shift  Max/Min  CMP  Bitwise   int  I4+/-I4=I4
I4+/-I4=I8
I8+/-I8=I8
I8+/-I8=I16
I16+/-I16=I16
I16+/-I16=I32
I32+/-I32=I32  I4*I4=I8
I8*I8=I16  shift(I4)=I4
shift(I8)=I4
shift(I8)=I8
shift(I16)=I8
shift(I32)=I16  Max/Min(I4) = I4
Max/Min(I8) = I8
﻿  CMP(I4) = I4
CMP(I8) = I8  Logical(I4) = I4
Logical(I8) = I8
﻿   float  FP8+/-FP8=FP8
FP8+/-FP8=FP16
FP8+/-FP8=BF16
FP16+/-FP16=FP16
FP16+/-FP16=FP32
BF16+/-BF16=BF16
BF16+/-BF16=FP32
FP32+/-FP32=FP32  FP8*FP8=FP8
FP8*FP8=FP16
FP8*FP8=BF16
FP16*FP16=FP16
FP16*FP16=FP32
BF16*BF16=BF16
BF16*BF16=FP32
FP32*FP32=FP32  ﻿
  Max/Min(FP8)=FP8
Max/Min(FP16)=FP16
Max/Min(BF16)=BF16  CMP(FP8)=FP8
CMP(FP16)=FP16
CMP(BF16)=BF16   ﻿
      ﻿ ﻿
 VS_V指令       VS_V操作完成如下三步骤操作:       Step1: 根据byte_base_in1，从LMEM中读出一维向量 Vector I1。       Step2: 将 Scalar I2 广播到 I1 长度，与一维Vector I1 逐元素进行SIMD计算操作后，输出长度相同的输出向量 Vector O。       Step3: 根据byte_base_out 将 Vector O 写入Local Memory中，结束执行。       VS_V指令主要支持Add/Sub，Mul，Max/Min，Shift，CMP，Bitwise 指令类型。 ﻿                  prec\op  Add/Sub  Mul  Shift  Max/Min  CMP  Bitwise   int  I4+/-I4=I4
I4+/-I4=I8
I8+/-I8=I8
I8+/-I8=I16
I16+/-I16=I16
I16+/-I16=I32
I32+/-I32=I32  I4*I4=I8
I8*I8=I16  shift(I4)=I4
shift(I8)=I4
shift(I8)=I8
shift(I16)=I8
shift(I32)=I16  Max/Min(I4) = I4
Max/Min(I8) = I8
﻿  CMP(I4) = I4
CMP(I8) = I8  Logical(I4) = I4
Logical(I8) = I8
﻿   float  FP8+/-FP8=FP8
FP8+/-FP8=FP16
FP8+/-FP8=BF16
FP16+/-FP16=FP16
FP16+/-FP16=FP32
BF16+/-BF16=BF16
BF16+/-BF16=FP32
FP32+/-FP32=FP32  FP8*FP8=FP8
FP8*FP8=FP16
FP8*FP8=BF16
FP16*FP16=FP16
FP16*FP16=FP32
BF16*BF16=BF16
BF16*BF16=FP32
FP32*FP32=FP32  ﻿
  Max/Min(FP8)=FP8
Max/Min(FP16)=FP16
Max/Min(BF16)=BF16  CMP(FP8)=FP8
CMP(FP16)=FP16
CMP(BF16)=BF16   ﻿
      ﻿ ﻿
 V_V指令     V_V操作完成如下三步骤操作: Step1: 根据byte_base_in，从LMEM中读出一维向量 Vector I1。 Step2: 对 Vector I1 进行逐元素的数据转换，输出一维输出向量 Vector O。 Step3: 根据byte_base_out 将 Vector O 写入Local Memory中，结束执行。       V_V指令主要支持Type Convert指令类型。 ﻿                  I2F  F2I  F2F  m2f  f2m  m2i  i2m   I4_2_FP8 I8_2_FP8 I8_2_FP16 I8_2_BF16 I16_2_FP8 I16_2_FP16 I16_2_BF16 I16_2_FP32 I32_2_FP16 I32_2_BF16 I32_2_FP32  FP8_2_I4 FP8_2_I8 FP8_2_I16 FP16_2_I8 FP16_2_I16 FP16_2_I32 BF16_2_I8 BF16_2_I16 BF16_2_I32 BF16_2_I16 BF16_2_I32  FP8_2_FP16 FP8_2_BF16 FP16_2_FP8 FP16_2_BF16 FP16_2_FP32 BF16_2_FP8 BF16_2_FP16 BF16_2_FP32 FP32_2_FP16 FP32_2_BF16  MXINT4_2_FP32 MXINT8_2_FP32 MXFP4_2_FP32 MXFP8_2_FP32  FP32_2_MXNT4 FP32_2_MXNT8 FP32_2_MXFP4 FP32_2_MXFP8  MXINT4_2_I32 MXINT8_2_I32 MXFP4_2_I32 MXFP8_2_I32  I32_2_MXNT4 I32_2_MXNT8 I32_2_MXFP4 I32_2_MXFP8      ﻿   V_S指令 V_S操作完成如下两步骤操作: Step1: 根据byte_base_in1，从LMEM中读出一维向量 Vector I1 Step2: 将输入向量 Vector I1 进行Reduce操作，输出标量结果 Scalar O Step3: 将 Scalar O 返回，结束执行。     V_S指令主要支持Sum，Max/Min，Bitwise 指令类型。 ﻿            Sum  Max/Min  and/or/xor  ﻿
   int  I4+I4=I4
I4+I4=I8
I8+I8=I8
I8+I8=I16
I16+I16=I16
I16+I16=I32
I32+I32=I32  Max/Min(I4) = I4
Max/Min(I8) = I8  Logical(I4) = I4
Logical(I8) = I8   float  FP8+FP8=FP8
FP8+FP8=FP16
FP8+FP8=BF16
FP16+FP16=FP16
FP16+FP16=FP32
BF16+BF16=BF16
BF16+BF16=FP32
FP32+FP32=FP32  Max/Min(FP8)=FP8
Max/Min(FP16)=FP16
Max/Min(BF16)=BF16  ﻿
      ﻿ ﻿
 6. 数据计算处理 6.1 数据格式 ﻿          数据格式  数据组成  特殊数据   fp32  符号位  :1bit 表示正负 ;   指数位  :8bit 表示数值的规模; 尾数位  :23bit  表示数值的精度  inf  : 指数位全为1，尾数位全为0。 nan: 指数位全为1，尾数位不全为0。 zero: 指数位全为0，尾数位全为0。 denor:  指数位全为0，尾数位不全为0。   fp16  符号位  :1bit 表示正负 ;   指数位  :5bit 表示数值的规模; 尾数位  :10bit  表示数值的精度  inf  : 指数位全为1，尾数位全为0。 nan: 指数位全为1，尾数位不全为0。 zero: 指数位全为0，尾数位全为0。 denor:  指数位全为0，尾数位不全为0。   bf16  符号位  :1bit 表示正负 ;   指数位  :8bit 表示数值的规模; 尾数位  :7bit  表示数值的精度  inf  : 指数位全为1，尾数位全为0。 nan: 指数位全为1，尾数位不全为0。 zero: 指数位全为0，尾数位全为0。 denor:  指数位全为0，尾数位不全为0。   f152  符号位  :1bit 表示正负 ;   指数位  :5bit 表示数值的规模; 尾数位  :2bit  表示数值的精度  inf  : 指数位全为1，尾数位全为0。 nan: 指数位全为1，尾数位不全为0。 zero: 指数位全为0，尾数位全为0。 denor:  指数位全为0，尾数位不全为0。   f143  符号位  :1bit 表示正负 ;   指数位  :8bit 表示数值的规模; 尾数位  :23bit  表示数值的精度  无inf nan: 指数位全为1，尾数位不全为0。 zero: 指数位全为0，尾数位全为0。 denor:  指数位全为0，尾数位不全为0。   mxi8  符号位  :1bit 表示正负 ;   数据位  :7bit 表示数据值;  其中数据位为数据值的绝对值，与传统的int8不同。   mxf143  符号位  :1bit 表示正负 ;   指数位  :8bit 表示数值的规模; 尾数位  :23bit  表示数值的精度  无inf nan: 指数位全为1，尾数位不全为0。 zero: 指数位全为0，尾数位全为0。 denor:  指数位全为0，尾数位不全为0。   mxf152  符号位  :1bit 表示正负 ;   指数位  :5bit 表示数值的规模; 尾数位  :2bit  表示数值的精度  inf  : 指数位全为1，尾数位全为0。 nan: 指数位全为1，尾数位不全为0。 zero: 指数位全为0，尾数位全为0。 denor:  指数位全为0，尾数位不全为0。      ﻿ ﻿
 6.2 输出向量 1) 逻辑数据  在compare指令中，计算结果输出结果与操作数数据位宽对齐，最低位为有效逻辑输出，高位补0。 2) Nar_2输出       输出向量数据位宽为输入向量的一半时，输出向量按照输出数据位宽256bit紧密排列输出，不足高位补0。 ﻿
 6.3 浮点数特殊数据处理  1）非规格化数         默认当做0处理，同时可以通过配置方式，保留尾数有效值向后传播。 2）Nan  当计算结果为Nan时，统一格式。保留原始计算符号位，阶码全1，尾数全1。 6.4 Rounding mode 1）Round to Floor •  向负无穷方向舍入，结果 ≤ 原数。  •  示例： ◦  ﻿ 1.8  →  1 ﻿  ◦  ﻿ -1.8  →  -2 ﻿    2）Round to Ceiling •  向正无穷方向舍入，结果 ≥ 原数。  •  示例： ◦  ﻿ 1.2  →  2 ﻿  ◦  ﻿ -1.2  →  -1 ﻿    3）Round Toward Zero •  直接截断小数部分，不改变符号。  •  结果绝对值 ≤ 原数绝对值。  •  示例： ◦  ﻿ 1.9  →  1 ﻿  ◦  ﻿ -1.9  →  -1 ﻿    4）Round Away From Zero •  向远离零的方向舍入（即正数向上，负数向下）。  •  示例： ◦  ﻿ 1.3  →  2 ﻿  ◦  ﻿ -1.3  →  -2 ﻿    5）Round to Nearest, Ties to Away Zero •  类似“Ties to Even”，但中间值舍入到绝对值较大的方向。  •  示例： ◦  ﻿ 1.5  →  2 ﻿  ◦  ﻿ -2.5  →  -3 ﻿    6）Round to Nearest, Ties to Even •  舍入到最接近的可表示值，若恰好在中间（即两个可表示值距离相等），则选择偶数位（最低有效位为0）的结果。  •  示例： ◦  ﻿ 1.4  →  1 ﻿  ◦  ﻿ 1.5  →  2 （因为2是偶数）  ◦  ﻿ 2.5  →  2 （因为2是偶数）    ﻿
 6.2 浮点加法运算  1）特殊数据计算规则 •  当Nan为异号时，result的符号位为0。  •  当opa/opb为异号inf时，result的符号位为0，数值为Nan。  •  当opa/opb为异号0时，result的符号位为0，数值为0。   2）fadd计算表格 ﻿                              opa\opb  +Nan  -Nan  +inf  -inf  +denor  -denor  +denor_is0  -denor_is0  +0  -0  +nor  -nor   +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan   -Nan  +NAN  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan   +inf  +Nan  -Nan  +inf  Nan  +inf  +inf  +inf  +inf  +inf  +inf  +inf  +inf   -inf  +Nan  -Nan  +Nan  -inf  -inf  -inf  -inf  -inf  -inf  -inf  -inf  -inf   +denor  +Nan  -Nan  +inf  -inf  Nor_op  Nor_op  \  \  +denor  +denor  Nor_op  Nor_op   -denor  +Nan  -Nan  +inf  -inf  Nor_op  Nor_op  \  \  -denor  -denor  Nor_op  Nor_op   +denor_is0  +Nan  -Nan  +inf  -inf  \  \  +0  +0  +0  +0  +nor  -nor   -denor_is0  +Nan  -Nan  +inf  -inf  \  \  +0  -0  +0  -0  +nor  -nor   +0  +Nan  -Nan  +inf  -inf  +denor  -denor  +0  +0  +0  +0  +nor  -nor   -0  +Nan  -Nan  +inf  -inf  +denor  -denor  +0  -0  +0  -0  +nor  -nor   +nor  +Nan  -Nan  +inf  -inf  Nor_op  Nor_op  +nor  +nor  +nor  +nor  Nor_op  Nor_op   -nor  +Nan  -Nan  +inf  -inf  Nor_op  Nor_op  -nor  -nor  -nor  -nor  Nor_op  Nor_op      ﻿ 6.3 浮点减法运算 1）特殊数据计算规则 •  当Nan为同号时，result的符号位为0。  •  当opa/opb为同号inf时，result的符号位为0，数值为Nan。  •  当opa/opb为同号0时，result的符号位为0，数值为0。    2）fsub计算表格 ﻿                              opa\opb  +Nan  -Nan  +inf  -inf  +denor  -denor  +denor_is0  -denor_is0  +0  -0  +nor  -nor   +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan  +Nan   -Nan  -NAN  +Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan  -Nan   +inf  -Nan  +Nan  Nan  +inf  +inf  +inf  +inf  +inf  +inf  +inf  +inf  +inf   -inf  -Nan  +Nan  -inf  -Nan  -inf  -inf  -inf  -inf  -inf  -inf  -inf  -inf   +denor  -Nan  +Nan  -inf  +inf  Nor_op  Nor_op  \  \  +denor  +denor  Nor_op  Nor_op   -denor  -Nan  +Nan  -inf  +inf  Nor_op  Nor_op  \  \  -denor  -denor  Nor_op  Nor_op   +denor_is0  -Nan  +Nan  -inf  +inf  \  \  +0  -0  +0  -0  -nor  +nor   -denor_is0  -Nan  +Nan  -inf  +inf  \  \  -0  +0  -0  +0  -nor  +nor   +0  -Nan  +Nan  -inf  +inf  -denor  +denor  +0  -0  +0  -0  -nor  +nor   -0  -Nan  +Nan  -inf  +inf  -denor  +denor  -0  +0  -0  +0  -nor  +nor   +nor  -Nan  +Nan  -inf  +inf  Nor_op  Nor_op  +nor  +nor  +nor  +nor  Nor_op  Nor_op   -nor  -Nan  +Nan  -inf  +inf  Nor_op  Nor_op  -nor  -nor  -nor  -nor  Nor_op  Nor_op      ﻿ 6.4 浮点乘法运算 1）特殊数据计算规则 •  符号位res_sgin=opa_sign ^ opb_sign。  •  当opa*opb=inf*0，result的符号位为正常运算的符号位，数值为Nan。  •  当乘法存在结果溢出，其结果处理为inf。若op_satu=1，则处理为最大有效值。   2）fmul计算表格 ﻿                              opa\opb  +Nan  -Nan  +inf  -inf  +denor  -denor  +denor_is0  -denor_is0  +0  -0  +nor  -nor   +Nan  +Nan  -Nan  +Nan  -Nan  +Nan  -Nan  +Nan  -Nan  +Nan  -Nan  +Nan  -Nan   -Nan  --Nan  +Nan  -Nan  +Nan  -Nan  +Nan  -NAN  +Nan  -Nan  +Nan  -Nan  +Nan   +inf  +Nan  -Nan  +inf  -inf  +inf  -inf  +Nan  +Nan  +Nan  +Nan  +inf  -inf   -inf  -Nan  +Nan  -inf  +inf  -inf  +inf  +Nan  +Nan  +Nan  +Nan  -inf  +inf   +denor  +Nan  -Nan  +inf  -inf  +Nor_op   -Nor_op  \  \  +0  -0  +Nor_op  -Nor_op   -denor  -Nan  +Nan  -inf  +inf  -Nor_op   +Nor_op  \  \  -0  +0  -Nor_op  +Nor_op   +denor_is0  +Nan  -Nan  +Nan  -Nan  \  \  +0  -0  +0  -0  +0  -0   -denor_is0  -Nan  +Nan  -Nan  +Nan  \  \  -0  +0  -0  +0  -0  +0   +0  +Nan  -Nan  +Nna  -Nan  +0  -0  +0  -0  +0  -0  +0  -0   -0  -Nan  +Nan  -Nan  +Nan  -0  +0  -0  +0  -0  +0  -0  +0   +nor  +Nan  -Nan  +inf  -inf  +Nor_op  -Nor_op  +0  -0  +0  -0  +Nor_op  -Nor_op   -nor  -Nan  +Nan  -inf  +inf  -Nor_op  +Nor_op  -0  +0  -0  +0  -Nor_op  +Nor_op      ﻿ 6.5 Max/CMP  1）特殊数据计算规则 CMP(opa,opb)/max(opa,opb)/min(opa,opb) •  denor不做特殊处理，视为正常数计算。  •  +0/-0视为相等。  •  Nan与任何数做Max/Min，计算结果为+Nan。   •  Nan不等于任何值，在CPM运算中： ◦  not equal输出True  ◦  其余运算输出False   •  +inf大于除了+inf以外的所有值： ◦  equal输出True   •  -inf小于除了-inf以外的所有值： ◦  equal输出True    2）max/cmp计算表格 ﻿     [opa,opb]\op_ty  MAX  Min  Equal  Not Equal  Great  Great or Equal  Less  Less or Equal   [+Nan,+NAN]  +Nan  +Nan  0  1  0  0  0  0   [+Nan,-NAN]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,+NAN]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,-NAN]  +Nan  +Nan  0  1  0  0  0  0   [+Nan,+inf]  +Nan  +Nan  0  1  0  0  0  0   [+Nan,-inf]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,+inf]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,-inf]  +Nan  +Nan  0  1  0  0  0  0   [+Nan,+denor]  +Nan  +Nan  0  1  0  0  0  0   [+Nan,-denor]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,+denor]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,-denor]  +Nan  +Nan  0  1  0  0  0  0   [+Nan,+0]  +Nan  +Nan  0  1  0  0  0  0   [+Nan,-0]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,+0]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,-0]  +Nan  +Nan  0  1  0  0  0  0   [+Nan,+nor]  +Nan  +Nan  0  1  0  0  0  0   [+Nan,-nor]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,+nor]  +Nan  +Nan  0  1  0  0  0  0   [-Nan,-nor]  +Nan  +Nan  0  1  0  0  0  0   [+0,-0]  +0  -0  1  0  0  1  0  1   [-0,+0]  +0  -0  1  0  0  1  0  1   [+inf,+NAN]  +Nan  +Nan  0  1  0  0  0  0   [+inf,-NAN]  +Nan  +Nan  0  1  0  0  0  0   [-inf,+NAN]  +Nan  +Nan  0  1  0  0  0  0   [-inf,-NAN]  +Nan  +Nan  0  1  0  0  0  0   [+inf,+inf]  +inf  +inf  1  0  0  0  0  0   [+inf,-inf]  +inf  -inf  0  1  1  1  0  0   [-inf,+inf]  +inf  -inf  0  1  0  0  0  0   [-inf,-inf]  -inf  -inf  1  0  0  0  0  0   [+inf,+denor]  +inf  +denor  0  1  0  0  0  0   [+inf,-denor]  +inf  -denor  0  1  0  0  0  0   [-inf,+denor]  +denor  +inf  0  1  0  0  0  0   [-inf,-denor]  -denor  +inf  0  1  0  0  0  0   [+inf,+0]  +inf  +0  0  1  1  1  0  0   [+inf,-0]  +inf  -0  0  1  1  1  0  0   [-inf,+0]  +0  +inf  0  1  0  0  1  1   [-inf,-0]  -0  +inf  0  1  0  0  1  1   [+inf,+nor]  +inf  +nor  0  1  1  1  0  0   [+inf,-nor]  +inf  -nor  0  1  1  1  0  0   [-inf,+nor]  +nor  -inf  0  1  0  0  0  0   [-inf,-nor]  -nor  -inf  0  1  0  0  0  0
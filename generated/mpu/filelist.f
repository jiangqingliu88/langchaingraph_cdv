// MPU Compilation Filelist
// Hierarchy: mpu_top → cimc → cime → cimm(sub-modules) + ctrl + rd_channel + wr_channel

+incdir+.

//── Definitions ──
mpu_defines.vh

//── CIMM sub-modules ──
cimm/compute_format.v
cimm/controller.v
cimm/input_process.v
cimm/tmu.v
cimm/dcim_ip_bm_core.v
cimm/adder_tree.v
cimm/shift_accumulator.v
cimm/trans_int37.v
cimm/mantissa_mux.v
cimm/exponent_mux.v
cimm/cbist_top.sv
cimm/cimm.v

//── CIME ──
cime/cime.v

//── CIMC ──
cimc/addr_map.v
cimc/cimc.v

//── Control ──
ctrl/cfg_chk.v
ctrl/cfg_sec_resolution.v
ctrl/shape_analyzer.v
ctrl/cfg_ctrl.v
ctrl/lp_ctrl.v
ctrl/state_report.v
ctrl/mpu_ctrl.v
mpu_post_process.v

//── Data channels ──
rd_channel/mpu_rd_channel.v
wr_channel/mpu_wr_channel.v

//── Top ──
mpu_top.v

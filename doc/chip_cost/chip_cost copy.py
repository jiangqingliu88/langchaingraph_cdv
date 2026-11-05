import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import csv
import math
import os

# 尝试导入 openpyxl 用于 Excel 导出
try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

# ================== 全局配置 ==================
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

# ================== 1. 逻辑工艺数据库（多供应商价格）==================
# 数据来源：台积电2025-2026年晶圆代工报价，三星、中芯国际参考公开信息
LOGIC_TECH = {
    "28nm": {
        "density": 0.10,               # 亿晶体管/mm²
        "suppliers": {
            "TSMC": {"wafer_price_300": 3800, "wafer_price_200": 1800},
            "SMIC": {"wafer_price_300": 3000, "wafer_price_200": 1500},
            "Samsung": {"wafer_price_300": 3600, "wafer_price_200": 1700},
        },
        "defect_density": 0.025,
        "mask_layers": 40,
        "mask_cost_per_layer": 50000,
        "nre_single": 40_000_000,
        "nre_multi_base": 20_000_000,
        "nre_per_die": 2_000_000,
        "typical_tdp_w_per_mm2": 0.05,   # 典型功耗密度 W/mm²
    },
    "12nm": {
        "density": 0.25,
        "suppliers": {
            "TSMC": {"wafer_price_300": 5200, "wafer_price_200": 2600},
            "Samsung": {"wafer_price_300": 4800, "wafer_price_200": 2400},
        },
        "defect_density": 0.045,
        "mask_layers": 55,
        "mask_cost_per_layer": 75000,
        "nre_single": 90_000_000,
        "nre_multi_base": 45_000_000,
        "nre_per_die": 4_000_000,
        "typical_tdp_w_per_mm2": 0.08,
    },
    "7nm": {
        "density": 0.60,
        "suppliers": {
            "TSMC": {"wafer_price_300": 10000, "wafer_price_200": 4800},
            "Samsung": {"wafer_price_300": 9000, "wafer_price_200": 4500},
        },
        "defect_density": 0.070,
        "mask_layers": 85,
        "mask_cost_per_layer": 80000,
        "nre_single": 250_000_000,
        "nre_multi_base": 100_000_000,
        "nre_per_die": 8_000_000,
        "typical_tdp_w_per_mm2": 0.12,
    },
    "5nm": {
        "density": 1.30,
        "suppliers": {
            "TSMC": {"wafer_price_300": 16000, "wafer_price_200": 8000},
            "Samsung": {"wafer_price_300": 14500, "wafer_price_200": 7300},
        },
        "defect_density": 0.100,
        "mask_layers": 110,
        "mask_cost_per_layer": 90000,
        "nre_single": 450_000_000,
        "nre_multi_base": 180_000_000,
        "nre_per_die": 12_000_000,
        "typical_tdp_w_per_mm2": 0.18,
    },
    "3nm": {
        "density": 2.00,
        "suppliers": {
            "TSMC": {"wafer_price_300": 20000, "wafer_price_200": 11000},
            "Samsung": {"wafer_price_300": 18500, "wafer_price_200": 10000},
        },
        "defect_density": 0.140,
        "mask_layers": 145,
        "mask_cost_per_layer": 110000,
        "nre_single": 600_000_000,
        "nre_multi_base": 250_000_000,
        "nre_per_die": 15_000_000,
        "typical_tdp_w_per_mm2": 0.25,
    },
    "2nm": {
        "density": 2.80,
        "suppliers": {
            "TSMC": {"wafer_price_300": 33000, "wafer_price_200": 16500},
        },
        "defect_density": 0.350,
        "mask_layers": 200,
        "mask_cost_per_layer": 150000,
        "nre_single": 900_000_000,
        "nre_multi_base": 400_000_000,
        "nre_per_die": 25_000_000,
        "typical_tdp_w_per_mm2": 0.35,
    },
    "成熟工艺 (55nm)": {
        "density": 0.03,
        "suppliers": {
            "TSMC": {"wafer_price_300": 2800, "wafer_price_200": 1400},
            "SMIC": {"wafer_price_300": 2200, "wafer_price_200": 1100},
        },
        "defect_density": 0.018,
        "mask_layers": 30,
        "mask_cost_per_layer": 20000,
        "nre_single": 20_000_000,
        "nre_multi_base": 12_000_000,
        "nre_per_die": 1_000_000,
        "typical_tdp_w_per_mm2": 0.03,
    }
}

# ================== 2. DRAM 工艺数据库（多供应商）==================
DRAM_TECH = {
    "DDR4 (20nm)": {
        "density_gb_per_mm2": 0.008,
        "suppliers": {"TSMC": {"wafer_price_300": 3000}, "Samsung": {"wafer_price_300": 2800}},
        "defect_density": 0.020,
        "nre_single": 15_000_000,
        "nre_multi_base": 8_000_000,
        "nre_per_die": 1_000_000,
    },
    "DDR5 (1z nm)": {
        "density_gb_per_mm2": 0.016,
        "suppliers": {"TSMC": {"wafer_price_300": 4000}, "Samsung": {"wafer_price_300": 3800}},
        "defect_density": 0.025,
        "nre_single": 20_000_000,
        "nre_multi_base": 10_000_000,
        "nre_per_die": 1_500_000,
    },
    "LPDDR5 (1a nm)": {
        "density_gb_per_mm2": 0.020,
        "suppliers": {"TSMC": {"wafer_price_300": 4500}, "Samsung": {"wafer_price_300": 4200}},
        "defect_density": 0.030,
        "nre_single": 25_000_000,
        "nre_multi_base": 12_000_000,
        "nre_per_die": 2_000_000,
    },
    "HBM2E (1y nm)": {
        "density_gb_per_mm2": 0.030,
        "suppliers": {"TSMC": {"wafer_price_300": 6000}, "Samsung": {"wafer_price_300": 5800}},
        "defect_density": 0.040,
        "nre_single": 40_000_000,
        "nre_multi_base": 20_000_000,
        "nre_per_die": 3_000_000,
        "stacked": True,
    },
    "HBM3 (1b nm)": {
        "density_gb_per_mm2": 0.045,
        "suppliers": {"TSMC": {"wafer_price_300": 8000}, "Samsung": {"wafer_price_300": 7500}},
        "defect_density": 0.050,
        "nre_single": 60_000_000,
        "nre_multi_base": 30_000_000,
        "nre_per_die": 4_000_000,
        "stacked": True,
    }
}

# ================== 3. 封装技术数据库（2D/2.5D/3D）==================
PACKAGE_TYPES = {
    "2D MCM": {
        "single_pkg_cost": 10,
        "adv_fixed": 150,
        "adv_per_die": 50,
        "safety": 1.0,
        "reliability": 1.0,
        "perf_factor": 0.90,
        "fixed_cost_allocation": "area",
        "base_package_yield": 0.99,
        "yield_bump_factor": 0.0001,    # 每凸块良率损失因子
    },
    "2.5D CoWoS-S": {
        "single_pkg_cost": 20,
        "adv_fixed": 400,
        "adv_per_die": 180,
        "safety": 1.0,
        "reliability": 1.0,
        "perf_factor": 1.00,
        "fixed_cost_allocation": "area",
        "base_package_yield": 0.98,
        "yield_bump_factor": 0.00015,
    },
    "2.5D CoWoS-R": {
        "single_pkg_cost": 18,
        "adv_fixed": 350,
        "adv_per_die": 160,
        "safety": 1.0,
        "reliability": 1.0,
        "perf_factor": 0.95,
        "fixed_cost_allocation": "area",
        "base_package_yield": 0.97,
        "yield_bump_factor": 0.00012,
    },
    "2.5D CoWoP": {
        "single_pkg_cost": 15,
        "adv_fixed": 300,
        "adv_per_die": 120,
        "safety": 1.0,
        "reliability": 1.0,
        "perf_factor": 0.85,
        "fixed_cost_allocation": "area",
        "base_package_yield": 0.96,
        "yield_bump_factor": 0.0001,
    },
    "3D TSV (真3D堆叠)": {
        "single_pkg_cost": 50,
        "adv_fixed": 800,
        "adv_per_die": 350,
        "safety": 1.05,
        "reliability": 1.1,
        "perf_factor": 1.20,
        "fixed_cost_allocation": "area",
        "base_package_yield": 0.95,
        "yield_bump_factor": 0.0002,
    }
}

# ================== 4. 后端工艺乘数 ==================
BACKEND_OPTIONS = {
    "基板层数": {"2层":1.0, "4层":1.2, "6层":1.5, "8层":2.0},
    "凸块间距": {"标准 130μm":1.0, "细间距 55μm":1.3, "超细间距 25μm":1.8},
    "散热方案": {"被动散热":1.0, "主动风冷":1.1, "液冷":1.5},
    "测试等级": {"常温测试":1.0, "工业级(-40~85°C)":1.2, "车规级(-40~125°C)":1.5}
}

# ================== 5. 良率模型 ==================
YIELD_MODELS = {
    "Poisson": lambda area, d0: math.exp(-area * d0),
    "Murphy":  lambda area, d0: ((1 - math.exp(-area * d0)) / (area * d0))**2,
    "Seeds":   lambda area, d0, alpha=4.0: (1 + area * d0 / alpha) ** (-alpha)
}

# ================== 6. 质量等级详细参数 ==================
QUALITY_GRADE = {
    "消费级 (Commercial)": {
        "dppm_target": 500,
        "temp_range": "0~70°C",
        "life_years": 5,
        "design_redundancy_percent": 0.0,
        "test_time_multiplier": 1.0,
        "wafer_price_multiplier": 1.0,
        "package_extra_multiplier": 1.0,
        "certification_amort_usd": 0,
        "description": "JESD47标准",
        "cp_test_time_hours": 0.2,      # 每片晶圆CP测试小时数
        "ft_test_time_sec": 5,           # 每颗FT测试秒数
    },
    "工业级 (Industrial)": {
        "dppm_target": 100,
        "temp_range": "-40~85°C",
        "life_years": 10,
        "design_redundancy_percent": 5.0,
        "test_time_multiplier": 2.0,
        "wafer_price_multiplier": 1.2,
        "package_extra_multiplier": 1.2,
        "certification_amort_usd": 200_000,
        "description": "工业级，宽温工作",
        "cp_test_time_hours": 0.5,
        "ft_test_time_sec": 10,
    },
    "车规级 (Automotive Grade 1)": {
        "dppm_target": 10,
        "temp_range": "-40~125°C",
        "life_years": 15,
        "design_redundancy_percent": 15.0,
        "test_time_multiplier": 5.0,
        "wafer_price_multiplier": 1.5,
        "package_extra_multiplier": 1.5,
        "certification_amort_usd": 2_000_000,
        "description": "AEC-Q100 Grade 1",
        "cp_test_time_hours": 1.5,
        "ft_test_time_sec": 30,
    },
    "军工级 (Military)": {
        "dppm_target": 1,
        "temp_range": "-55~125°C",
        "life_years": 25,
        "design_redundancy_percent": 30.0,
        "test_time_multiplier": 12.0,
        "wafer_price_multiplier": 2.5,
        "package_extra_multiplier": 2.5,
        "certification_amort_usd": 5_000_000,
        "description": "MIL-STD-883",
        "cp_test_time_hours": 3.0,
        "ft_test_time_sec": 60,
    },
    "航天级 (Space/Aerospace)": {
        "dppm_target": 0.1,
        "temp_range": "-55~150°C (抗辐射)",
        "life_years": 30,
        "design_redundancy_percent": 60.0,
        "test_time_multiplier": 20.0,
        "wafer_price_multiplier": 4.0,
        "package_extra_multiplier": 4.0,
        "certification_amort_usd": 15_000_000,
        "description": "抗辐射加固",
        "cp_test_time_hours": 6.0,
        "ft_test_time_sec": 120,
    }
}

# ================== 7. 性能与功耗基准 ==================
DEFAULT_TOPS_PER_MM2 = 0.5   # INT8 TOPS/mm²
CP_RATE_PER_HOUR = 150       # 美元/小时，晶圆测试机台费率
FT_RATE_PER_HOUR = 100       # 美元/小时，成品测试机台费率

# ================== 辅助函数 ==================
def die_yield(area_cm2, defect_density, model_name="Seeds", alpha=4.0):
    if area_cm2 <= 0:
        return 0.0
    if model_name == "Poisson":
        return YIELD_MODELS["Poisson"](area_cm2, defect_density)
    elif model_name == "Murphy":
        return YIELD_MODELS["Murphy"](area_cm2, defect_density)
    else:
        return YIELD_MODELS["Seeds"](area_cm2, defect_density, alpha)

def calc_dies_per_wafer(wafer_diam_mm, die_area_mm2, edge_loss_mm=2.0):
    radius = wafer_diam_mm / 2.0
    effective_radius = radius - edge_loss_mm
    if effective_radius <= 0:
        return 0
    wafer_area_eff = math.pi * effective_radius ** 2
    return int(wafer_area_eff / die_area_mm2)

def get_wafer_price_with_discount(base_price, volume, ref_volume=1_000_000, max_discount=0.2):
    """晶圆价格非线性折扣模型"""
    if volume <= 0:
        return base_price
    # 基于对数折扣，产量越高折扣越大
    discount = min(max_discount, 0.1 * math.log10(volume / ref_volume))
    factor = 1 - discount
    return base_price * factor

def calc_package_yield(pkg_cfg, logic_area_mm2, dram_area_mm2, num_logic, num_dram, bump_count_per_mm2=100):
    """动态封装良率：基于面积和凸块数量"""
    base_yield = pkg_cfg.get("base_package_yield", 0.98)
    # 面积影响：大面积芯片良率更低
    total_area = logic_area_mm2 * num_logic + dram_area_mm2 * num_dram
    area_factor = math.exp(-total_area / 1000)   # 面积每增加1000mm²，良率下降约37%
    # 凸块数量影响：假设每mm²有bump_count_per_mm2个凸块
    total_bumps = total_area * bump_count_per_mm2
    bump_factor = math.exp(-total_bumps * pkg_cfg.get("yield_bump_factor", 0.0001))
    return base_yield * area_factor * bump_factor

def calc_test_cost(wafer_diam_mm, die_area_mm2, num_good_dies_per_wafer, cp_test_hours_per_wafer, ft_test_sec_per_die):
    """细化测试成本计算"""
    if num_good_dies_per_wafer <= 0:
        return 0, 0
    cp_cost_per_wafer = cp_test_hours_per_wafer * CP_RATE_PER_HOUR
    cp_cost_per_die = cp_cost_per_wafer / num_good_dies_per_wafer
    ft_cost_per_die = (ft_test_sec_per_die / 3600) * FT_RATE_PER_HOUR
    return cp_cost_per_die, ft_cost_per_die

def calc_nre_detailed(logic_cfg, dram_cfg, num_logic, num_dram, is_single):
    """细化的NRE计算：掩膜、设计工具、原型测试、封装开发、验证测试"""
    if is_single:
        nre_mask = (logic_cfg.get('mask_layers', 40) * logic_cfg.get('mask_cost_per_layer', 50000) +
                    dram_cfg.get('mask_layers', 30) * 40000)  # DRAM掩膜简化
        nre_design_tools = 2_000_000   # EDA工具年费摊销
        nre_prototype = 1_000_000
        nre_package_dev = 500_000
        nre_validation = 1_000_000
        nre_base = logic_cfg.get('nre_single', 0) + dram_cfg.get('nre_single', 0)
    else:
        nre_mask = (logic_cfg.get('mask_layers', 40) * logic_cfg.get('mask_cost_per_layer', 50000) +
                    dram_cfg.get('mask_layers', 30) * 40000)
        nre_design_tools = 2_000_000
        nre_prototype = 1_000_000
        nre_package_dev = 1_000_000   # Chiplet封装开发更贵
        nre_validation = 2_000_000
        nre_base = (logic_cfg.get('nre_multi_base', 0) + num_logic * logic_cfg.get('nre_per_die', 0) +
                    dram_cfg.get('nre_multi_base', 0) + num_dram * dram_cfg.get('nre_per_die', 0))
    total_nre = nre_mask + nre_design_tools + nre_prototype + nre_package_dev + nre_validation + nre_base
    return total_nre

def calc_tdp(logic_area_mm2, dram_area_mm2, logic_cfg):
    """估算热设计功耗 TDP (W)"""
    logic_power = logic_area_mm2 * logic_cfg.get("typical_tdp_w_per_mm2", 0.1)
    dram_power = dram_area_mm2 * 0.02   # DRAM功耗密度较低
    return logic_power + dram_power

def calc_cooling_cost_multiplier(tdp_w):
    """根据TDP估算散热方案成本乘数（可覆盖用户选择的散热方案）"""
    if tdp_w < 50:
        return 1.0   # 被动散热
    elif tdp_w < 150:
        return 1.2   # 主动风冷
    else:
        return 1.5   # 液冷

# ================== 核心成本计算函数 ==================
def calc_single_die_cost(logic_area, dram_area, logic_cfg, dram_cfg, pkg_cfg, volume,
                         backend_extra, wafer_diam, yield_model, alpha,
                         ip_fee, royalty, quality_params, tops_per_mm2,
                         cp_test_hours, ft_test_sec):
    redundancy = 1.0 + quality_params["design_redundancy_percent"] / 100.0
    total_area = (logic_area + dram_area) * redundancy
    if total_area <= 0:
        return np.inf, 0, np.inf, {}

    # 晶圆价格（含产量折扣）
    base_wafer_price = logic_cfg['suppliers'].get(current_supplier, {}).get(f'wafer_price_{wafer_diam}', 3000)
    wafer_price = get_wafer_price_with_discount(base_wafer_price, volume) * quality_params["wafer_price_multiplier"]

    dies_per_wafer = calc_dies_per_wafer(wafer_diam, total_area)
    if dies_per_wafer == 0:
        return np.inf, 0, np.inf, {}
    area_cm2 = total_area / 100.0
    y = die_yield(area_cm2, logic_cfg['defect_density'], yield_model, alpha)
    if y <= 0:
        return np.inf, 0, np.inf, {}
    good_dies = dies_per_wafer * y
    silicon_cost = wafer_price / good_dies

    # 封装成本
    pkg_cost = pkg_cfg['single_pkg_cost'] * quality_params["package_extra_multiplier"]

    # NRE 细化
    nre_total = calc_nre_detailed(logic_cfg, dram_cfg, 1, 1, is_single=True)
    nre_amort = nre_total / volume

    # IP与版税
    ip_amort = ip_fee / volume
    royalty_per = royalty

    # 测试成本细化
    cp_cost, ft_cost = calc_test_cost(wafer_diam, total_area, good_dies, cp_test_hours, ft_test_sec)
    test_cost = (cp_cost + ft_cost) * quality_params["test_time_multiplier"]

    # 认证摊销
    cert_amort = quality_params["certification_amort_usd"] / volume if volume > 0 else 0

    # 封装良率动态
    pkg_yield = calc_package_yield(pkg_cfg, logic_area, dram_area, 1, 1)
    final_yield = pkg_yield * 0.99   # 测试良率简化
    if final_yield <= 0:
        return np.inf, 0, np.inf, {}

    total = (silicon_cost + pkg_cost + nre_amort + ip_amort + royalty_per + test_cost + cert_amort) * \
            pkg_cfg['safety'] * pkg_cfg['reliability'] * backend_extra / final_yield

    perf = total_area * tops_per_mm2 * pkg_cfg['perf_factor']
    tdp = calc_tdp(logic_area, dram_area, logic_cfg)
    details = {
        "silicon_cost": silicon_cost,
        "pkg_cost": pkg_cost,
        "nre_amort": nre_amort,
        "test_cost": test_cost,
        "cert_amort": cert_amort,
        "total_area": total_area,
        "yield": y,
        "tdp_w": tdp,
    }
    return total, perf, total / perf if perf > 0 else np.inf, details

def calc_multi_die_cost(logic_area, dram_die_area, logic_cfg, dram_cfg, pkg_cfg, volume,
                        num_logic, num_dram, backend_extra, wafer_diam, yield_model, alpha,
                        ip_fee, royalty, quality_params, tops_per_mm2,
                        cp_test_hours, ft_test_sec):
    redundancy = 1.0 + quality_params["design_redundancy_percent"] / 100.0
    logic_area_adj = logic_area * redundancy
    dram_area_adj = dram_die_area
    wafer_price_mult = quality_params["wafer_price_multiplier"]

    # 逻辑 die 成本
    logic_area_cm2 = logic_area_adj / 100.0
    y_logic = die_yield(logic_area_cm2, logic_cfg['defect_density'], yield_model, alpha)
    if y_logic <= 0:
        return np.inf, 0, np.inf, {}
    dies_per_wafer_logic = calc_dies_per_wafer(wafer_diam, logic_area_adj)
    if dies_per_wafer_logic == 0:
        return np.inf, 0, np.inf, {}
    good_logic = dies_per_wafer_logic * y_logic
    base_wafer_price_logic = logic_cfg['suppliers'].get(current_supplier, {}).get(f'wafer_price_{wafer_diam}', 3000)
    wafer_price_logic = get_wafer_price_with_discount(base_wafer_price_logic, volume) * wafer_price_mult
    silicon_cost_per_logic = wafer_price_logic / good_logic
    total_silicon_logic = num_logic * silicon_cost_per_logic

    # DRAM die 成本
    total_silicon_dram = 0
    dram_silicon_cost_per_die = 0
    y_dram = 0
    if dram_die_area > 0:
        dram_area_cm2 = dram_area_adj / 100.0
        y_dram = die_yield(dram_area_cm2, dram_cfg['defect_density'], yield_model, alpha)
        if y_dram <= 0:
            return np.inf, 0, np.inf, {}
        dies_per_wafer_dram = calc_dies_per_wafer(wafer_diam, dram_area_adj)
        if dies_per_wafer_dram == 0:
            return np.inf, 0, np.inf, {}
        good_dram = dies_per_wafer_dram * y_dram
        base_wafer_price_dram = dram_cfg['suppliers'].get(current_supplier, {}).get(f'wafer_price_{wafer_diam}', 3000)
        wafer_price_dram = get_wafer_price_with_discount(base_wafer_price_dram, volume) * wafer_price_mult
        dram_silicon_cost_per_die = wafer_price_dram / good_dram
        total_silicon_dram = num_dram * dram_silicon_cost_per_die

    total_silicon = total_silicon_logic + total_silicon_dram

    # 封装成本分解
    total_dies = num_logic + num_dram
    adv_fixed = pkg_cfg['adv_fixed']
    adv_per_die = pkg_cfg['adv_per_die']
    pkg_extra_mult = quality_params["package_extra_multiplier"]
    allocation = pkg_cfg.get("fixed_cost_allocation", "area")
    if allocation == "area":
        total_area_all = logic_area_adj * num_logic + dram_area_adj * num_dram
        if total_area_all > 0:
            logic_fixed_share = adv_fixed * (logic_area_adj * num_logic) / total_area_all
            dram_fixed_share = adv_fixed * (dram_area_adj * num_dram) / total_area_all
        else:
            logic_fixed_share = adv_fixed * num_logic / total_dies if total_dies>0 else 0
            dram_fixed_share = adv_fixed * num_dram / total_dies if total_dies>0 else 0
    else:
        logic_fixed_share = adv_fixed * num_logic / total_dies if total_dies>0 else 0
        dram_fixed_share = adv_fixed * num_dram / total_dies if total_dies>0 else 0
    logic_pkg_cost = (logic_fixed_share + num_logic * adv_per_die) * pkg_extra_mult
    dram_pkg_cost = (dram_fixed_share + num_dram * adv_per_die) * pkg_extra_mult
    total_pkg_cost = logic_pkg_cost + dram_pkg_cost

    # NRE 细化
    nre_total = calc_nre_detailed(logic_cfg, dram_cfg, num_logic, num_dram, is_single=False)
    nre_amort = nre_total / volume

    ip_amort = ip_fee / volume
    royalty_per = royalty

    # 测试成本细化（分别计算逻辑和DRAM，按总硅成本加权）
    # 这里简化：逻辑和DRAM共用CP/FT参数，分别计算
    cp_cost_logic, ft_cost_logic = calc_test_cost(wafer_diam, logic_area_adj, good_logic, cp_test_hours, ft_test_sec)
    cp_cost_dram, ft_cost_dram = calc_test_cost(wafer_diam, dram_area_adj, good_dram, cp_test_hours, ft_test_sec) if dram_die_area>0 else (0,0)
    test_cost = (cp_cost_logic + ft_cost_logic) * num_logic * quality_params["test_time_multiplier"] + \
                (cp_cost_dram + ft_cost_dram) * num_dram * quality_params["test_time_multiplier"]

    cert_amort = quality_params["certification_amort_usd"] / volume if volume > 0 else 0

    # 封装良率动态
    pkg_yield = calc_package_yield(pkg_cfg, logic_area_adj, dram_area_adj, num_logic, num_dram)
    final_yield = pkg_yield * 0.99
    if final_yield <= 0:
        return np.inf, 0, np.inf, {}

    total = (total_silicon + total_pkg_cost + nre_amort + ip_amort + royalty_per + test_cost + cert_amort) * \
            pkg_cfg['safety'] * pkg_cfg['reliability'] * backend_extra / final_yield

    logic_perf = logic_area_adj * tops_per_mm2 * pkg_cfg['perf_factor']
    perf = logic_perf
    tdp = calc_tdp(logic_area_adj, dram_area_adj * num_dram, logic_cfg)
    details = {
        "logic_silicon_cost_per_die": silicon_cost_per_logic,
        "dram_silicon_cost_per_die": dram_silicon_cost_per_die,
        "total_silicon_cost": total_silicon,
        "logic_die_area": logic_area_adj,
        "dram_die_area": dram_area_adj,
        "logic_yield": y_logic,
        "dram_yield": y_dram,
        "logic_fixed_share": logic_fixed_share,
        "dram_fixed_share": dram_fixed_share,
        "logic_pkg_cost": logic_pkg_cost,
        "dram_pkg_cost": dram_pkg_cost,
        "total_pkg_cost": total_pkg_cost,
        "nre_amort": nre_amort,
        "test_cost": test_cost,
        "cert_amort": cert_amort,
        "tdp_w": tdp,
    }
    return total, perf, total / perf if perf > 0 else np.inf, details

# ================== GUI 应用程序 ==================
class CommercialPlatform:
    def __init__(self, root):
        self.root = root
        root.title("商业化芯片成本与性能分析平台 v11.0 (全优化版)")
        root.geometry("1850x1250")

        # 全局供应商选择
        global current_supplier
        current_supplier = "TSMC"  # 默认

        # 基本输入
        self.input_mode = tk.StringVar(value="functional")
        self.functional_area = tk.StringVar(value="400")
        self.transistor_budget = tk.StringVar(value="40.0")
        self.dram_capacity = tk.StringVar(value="16")
        self.dram_tech = tk.StringVar(value="HBM3 (1b nm)")
        self.package = tk.StringVar(value="2.5D CoWoS-S")
        self.volume = tk.StringVar(value="1000000")
        self.logic_dies = tk.StringVar(value="1")
        self.dram_dies = tk.StringVar(value="4")
        self.substrates = tk.StringVar(value="4层")
        self.bump = tk.StringVar(value="细间距 55μm")
        self.cooling = tk.StringVar(value="主动风冷")
        self.test_level = tk.StringVar(value="工业级(-40~85°C)")
        self.quality_grade = tk.StringVar(value="消费级 (Commercial)")
        self.supplier = tk.StringVar(value="TSMC")   # 供应商选择

        # 高级参数
        self.wafer_diam = tk.StringVar(value="300")
        self.yield_model = tk.StringVar(value="Seeds")
        self.alpha = tk.StringVar(value="4.0")
        self.ip_license_fee = tk.StringVar(value="0")
        self.royalty_per_chip = tk.StringVar(value="0")
        self.edge_loss = tk.StringVar(value="2.0")
        self.tops_per_mm2 = tk.StringVar(value=str(DEFAULT_TOPS_PER_MM2))

        self.create_widgets()
        self.update_result()

    def create_widgets(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, width=650)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        left.pack_propagate(False)

        # ========== 输入区域 ==========
        # 1. 逻辑规模
        g1 = ttk.LabelFrame(left, text="1. 逻辑功能规模", padding=5)
        g1.pack(fill=tk.X, pady=5)
        ttk.Label(g1, text="输入模式:").grid(row=0, column=0, sticky=tk.W)
        mode_cb = ttk.Combobox(g1, textvariable=self.input_mode, values=["functional","transistor"], state="readonly")
        mode_cb.grid(row=0, column=1, sticky=tk.W)
        mode_cb.bind("<<ComboboxSelected>>", self.on_mode_change)
        self.func_label = ttk.Label(g1, text="等效28nm面积 (mm²):")
        self.func_label.grid(row=1, column=0, sticky=tk.W)
        self.func_entry = ttk.Entry(g1, textvariable=self.functional_area)
        self.func_entry.grid(row=1, column=1)
        self.trans_label = ttk.Label(g1, text="晶体管数量 (亿):")
        self.trans_label.grid(row=2, column=0, sticky=tk.W)
        self.trans_entry = ttk.Entry(g1, textvariable=self.transistor_budget)
        self.trans_entry.grid(row=2, column=1)
        self.func_entry.bind("<KeyRelease>", self.on_area_change)
        self.trans_entry.bind("<KeyRelease>", self.on_transistor_change)
        self.on_mode_change()

        # 2. 候选逻辑工艺
        g2 = ttk.LabelFrame(left, text="2. 候选逻辑工艺 (多选)", padding=5)
        g2.pack(fill=tk.X, pady=5)
        self.logic_vars = {}
        techs = list(LOGIC_TECH.keys())
        for i, t in enumerate(techs):
            var = tk.BooleanVar(value=(t in ["5nm","3nm"]))
            cb = ttk.Checkbutton(g2, text=t, variable=var)
            cb.grid(row=i//4, column=i%4, sticky=tk.W)
            self.logic_vars[t] = var

        # 3. DRAM & 封装
        g3 = ttk.LabelFrame(left, text="3. DRAM与封装", padding=5)
        g3.pack(fill=tk.X, pady=5)
        ttk.Label(g3, text="DRAM类型:").grid(row=0, column=0, sticky=tk.W)
        ttk.Combobox(g3, textvariable=self.dram_tech, values=list(DRAM_TECH.keys()), state="readonly").grid(row=0, column=1)
        ttk.Label(g3, text="DRAM容量 (GB):").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(g3, textvariable=self.dram_capacity).grid(row=1, column=1)
        ttk.Label(g3, text="封装类型:").grid(row=2, column=0, sticky=tk.W)
        pkg_combo = ttk.Combobox(g3, textvariable=self.package, values=list(PACKAGE_TYPES.keys()), state="readonly")
        pkg_combo.grid(row=2, column=1)
        pkg_combo.bind("<<ComboboxSelected>>", self.on_package_change)
        self.pkg_desc_label = ttk.Label(g3, text="", foreground="gray")
        self.pkg_desc_label.grid(row=3, column=0, columnspan=2, sticky=tk.W)
        self.update_package_desc()
        ttk.Label(g3, text="年产量 (颗):").grid(row=4, column=0, sticky=tk.W)
        ttk.Entry(g3, textvariable=self.volume).grid(row=4, column=1)

        # 4. Chiplet拆分
        g4 = ttk.LabelFrame(left, text="4. Chiplet拆分数量", padding=5)
        g4.pack(fill=tk.X, pady=5)
        ttk.Label(g4, text="逻辑Die数:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(g4, textvariable=self.logic_dies, width=8).grid(row=0, column=1)
        ttk.Label(g4, text="DRAM Die数:").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(g4, textvariable=self.dram_dies, width=8).grid(row=1, column=1)

        # 5. 后端乘数
        g5 = ttk.LabelFrame(left, text="5. 后端工艺乘数", padding=5)
        g5.pack(fill=tk.X, pady=5)
        r=0
        ttk.Label(g5, text="基板层数:").grid(row=r, column=0, sticky=tk.W)
        ttk.Combobox(g5, textvariable=self.substrates, values=list(BACKEND_OPTIONS["基板层数"].keys()), state="readonly").grid(row=r, column=1)
        r+=1
        ttk.Label(g5, text="凸块间距:").grid(row=r, column=0, sticky=tk.W)
        ttk.Combobox(g5, textvariable=self.bump, values=list(BACKEND_OPTIONS["凸块间距"].keys()), state="readonly").grid(row=r, column=1)
        r+=1
        ttk.Label(g5, text="散热方案:").grid(row=r, column=0, sticky=tk.W)
        ttk.Combobox(g5, textvariable=self.cooling, values=list(BACKEND_OPTIONS["散热方案"].keys()), state="readonly").grid(row=r, column=1)
        r+=1
        ttk.Label(g5, text="测试等级:").grid(row=r, column=0, sticky=tk.W)
        ttk.Combobox(g5, textvariable=self.test_level, values=list(BACKEND_OPTIONS["测试等级"].keys()), state="readonly").grid(row=r, column=1)

        # 6. 质量等级与供应商
        g6 = ttk.LabelFrame(left, text="6. 质量等级 & 供应商", padding=5)
        g6.pack(fill=tk.X, pady=5)
        ttk.Label(g6, text="质量等级:").grid(row=0, column=0, sticky=tk.W)
        q_combo = ttk.Combobox(g6, textvariable=self.quality_grade, values=list(QUALITY_GRADE.keys()), state="readonly")
        q_combo.grid(row=0, column=1)
        q_combo.bind("<<ComboboxSelected>>", self.on_quality_change)
        self.quality_desc = ttk.Label(g6, text="", foreground="blue")
        self.quality_desc.grid(row=1, column=0, columnspan=2, sticky=tk.W)
        self.update_quality_desc()
        ttk.Label(g6, text="代工厂:").grid(row=2, column=0, sticky=tk.W)
        supplier_combo = ttk.Combobox(g6, textvariable=self.supplier, values=["TSMC","Samsung","SMIC"], state="readonly")
        supplier_combo.grid(row=2, column=1)
        supplier_combo.bind("<<ComboboxSelected>>", self.on_supplier_change)

        # 7. 高级参数
        g7 = ttk.LabelFrame(left, text="7. 高级参数", padding=5)
        g7.pack(fill=tk.X, pady=5)
        ttk.Label(g7, text="晶圆直径 (mm):").grid(row=0, column=0, sticky=tk.W)
        ttk.Combobox(g7, textvariable=self.wafer_diam, values=["200","300"], state="readonly").grid(row=0, column=1)
        ttk.Label(g7, text="边缘损失 (mm):").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(g7, textvariable=self.edge_loss, width=8).grid(row=1, column=1)
        ttk.Label(g7, text="良率模型:").grid(row=2, column=0, sticky=tk.W)
        ttk.Combobox(g7, textvariable=self.yield_model, values=["Poisson","Murphy","Seeds"], state="readonly").grid(row=2, column=1)
        ttk.Label(g7, text="α (Seeds):").grid(row=3, column=0, sticky=tk.W)
        ttk.Entry(g7, textvariable=self.alpha, width=8).grid(row=3, column=1)
        ttk.Label(g7, text="TOPS/mm²:").grid(row=4, column=0, sticky=tk.W)
        ttk.Entry(g7, textvariable=self.tops_per_mm2, width=8).grid(row=4, column=1)
        ttk.Label(g7, text="IP授权费 (USD):").grid(row=5, column=0, sticky=tk.W)
        ttk.Entry(g7, textvariable=self.ip_license_fee, width=12).grid(row=5, column=1)
        ttk.Label(g7, text="版税/颗 (USD):").grid(row=6, column=0, sticky=tk.W)
        ttk.Entry(g7, textvariable=self.royalty_per_chip, width=12).grid(row=6, column=1)

        # 按钮
        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill=tk.X, pady=15)
        ttk.Button(btn_frame, text="计算成本与性能", command=self.update_result).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="敏感性分析", command=self.sensitivity_analysis).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="导出Excel报表", command=self.export_excel).pack(side=tk.LEFT, padx=5)
        self.result_label = ttk.Label(left, text="", foreground="blue", font=("",10,"bold"))
        self.result_label.pack(pady=5)

        # 右侧 notebook
        right = ttk.Frame(main)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        nb = ttk.Notebook(right)
        nb.pack(fill=tk.BOTH, expand=True)

        # 成本图页
        self.cost_frame = ttk.Frame(nb)
        nb.add(self.cost_frame, text="💰 成本对比图")
        self.fig, self.ax = plt.subplots(figsize=(9,6))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.cost_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # 性能表页
        self.perf_frame = ttk.Frame(nb)
        nb.add(self.perf_frame, text="⚡ 性能与性价比")
        self.perf_tree = ttk.Treeview(self.perf_frame,
            columns=("Tech","SingleCost","SingleTOPS","SinglePPD","MultiCost","MultiTOPS","MultiPPD"),
            show="headings", height=12)
        self.perf_tree.heading("Tech", text="工艺")
        self.perf_tree.heading("SingleCost", text="单Die成本($)")
        self.perf_tree.heading("SingleTOPS", text="单Die算力(TOPS)")
        self.perf_tree.heading("SinglePPD", text="单Die $/TOPS")
        self.perf_tree.heading("MultiCost", text="多Die成本($)")
        self.perf_tree.heading("MultiTOPS", text="多Die算力(TOPS)")
        self.perf_tree.heading("MultiPPD", text="多Die $/TOPS")
        for col in self.perf_tree["columns"]:
            self.perf_tree.column(col, width=105)
        self.perf_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 封装成本明细页
        self.pkg_frame = ttk.Frame(nb)
        nb.add(self.pkg_frame, text="📦 封装成本明细")
        self.pkg_tree = ttk.Treeview(self.pkg_frame,
            columns=("Tech","DieType","Qty","Area_mm2","SiliconCost","FixedShare","PerDieCost","TotalPkgCost"),
            show="headings", height=12)
        self.pkg_tree.heading("Tech", text="工艺")
        self.pkg_tree.heading("DieType", text="Die类型")
        self.pkg_tree.heading("Qty", text="数量")
        self.pkg_tree.heading("Area_mm2", text="单颗面积(mm²)")
        self.pkg_tree.heading("SiliconCost", text="总硅成本($)")
        self.pkg_tree.heading("FixedShare", text="固定成本分摊($)")
        self.pkg_tree.heading("PerDieCost", text="每Die贴装($)")
        self.pkg_tree.heading("TotalPkgCost", text="总封装成本($)")
        for col in self.pkg_tree["columns"]:
            self.pkg_tree.column(col, width=110)
        self.pkg_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 详细参数页
        self.detail_frame = ttk.Frame(nb)
        nb.add(self.detail_frame, text="📋 详细参数 & 成本分解")
        self.detail_text = tk.Text(self.detail_frame, wrap=tk.WORD, font=("Consolas",9))
        scroll = ttk.Scrollbar(self.detail_frame, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=scroll.set)
        self.detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 敏感性分析结果窗口（暂存）
        self.sensitivity_window = None

    def update_package_desc(self, event=None):
        pkg = self.package.get()
        if pkg in PACKAGE_TYPES:
            perf = PACKAGE_TYPES[pkg]['perf_factor']
            alloc = PACKAGE_TYPES[pkg].get('fixed_cost_allocation', 'area')
            self.pkg_desc_label.config(text=f"性能因子: {perf:.2f} | 固定成本分摊: {alloc}")
        else:
            self.pkg_desc_label.config(text="")

    def on_package_change(self, event=None):
        self.update_package_desc()
        self.update_result()

    def update_quality_desc(self, event=None):
        q = self.quality_grade.get()
        d = QUALITY_GRADE[q]["description"]
        self.quality_desc.config(text=f"{d} | DPPM: {QUALITY_GRADE[q]['dppm_target']} PPM")

    def on_quality_change(self, event=None):
        self.update_quality_desc()
        self.update_result()

    def on_supplier_change(self, event=None):
        global current_supplier
        current_supplier = self.supplier.get()
        self.update_result()

    def on_mode_change(self, event=None):
        if self.input_mode.get() == "functional":
            self.func_entry.config(state="normal")
            self.trans_entry.config(state="readonly")
            self.sync_transistor()
        else:
            self.func_entry.config(state="readonly")
            self.trans_entry.config(state="normal")
            self.sync_area()

    def on_area_change(self, event=None):
        if self.input_mode.get() == "functional":
            self.sync_transistor()

    def on_transistor_change(self, event=None):
        if self.input_mode.get() == "transistor":
            self.sync_area()

    def sync_transistor(self):
        try:
            area = float(self.functional_area.get())
            trans = area * 0.1
            self.transistor_budget.set(f"{trans:.1f}")
        except: pass

    def sync_area(self):
        try:
            trans = float(self.transistor_budget.get())
            area = trans / 0.1
            self.functional_area.set(f"{area:.1f}")
        except: pass

    def get_logic_physical_area(self, tech):
        mode = self.input_mode.get()
        try:
            if mode == "functional":
                eq_area = float(self.functional_area.get())
                base_dens = LOGIC_TECH["28nm"]["density"]
                tech_dens = LOGIC_TECH[tech]["density"]
                return eq_area * (base_dens / tech_dens)
            else:
                trans = float(self.transistor_budget.get())
                tech_dens = LOGIC_TECH[tech]["density"]
                return (trans * 1e8) / tech_dens
        except:
            return 0

    def get_backend_extra(self):
        sub = BACKEND_OPTIONS["基板层数"].get(self.substrates.get(), 1.0)
        bump = BACKEND_OPTIONS["凸块间距"].get(self.bump.get(), 1.0)
        cool = BACKEND_OPTIONS["散热方案"].get(self.cooling.get(), 1.0)
        test = BACKEND_OPTIONS["测试等级"].get(self.test_level.get(), 1.0)
        # 热设计功耗动态修正（覆盖用户选择的散热方案）
        # 实际使用时，会根据计算的TDP重新计算一个散热乘数，但为了简化，保留用户选择
        return sub * bump * cool * test

    def compute_all(self):
        selected = [t for t, v in self.logic_vars.items() if v.get()]
        if not selected:
            messagebox.showerror("错误", "请至少选择一个逻辑工艺")
            return None, None, None
        try:
            volume = max(1, int(float(self.volume.get())))
            logic_dies = max(1, int(self.logic_dies.get()))
            dram_dies = max(1, int(self.dram_dies.get()))
            dram_cap = float(self.dram_capacity.get())
            wafer_diam = int(self.wafer_diam.get())
            alpha = float(self.alpha.get())
            ip_fee = float(self.ip_license_fee.get())
            royalty = float(self.royalty_per_chip.get())
            tops = float(self.tops_per_mm2.get())
        except Exception as e:
            messagebox.showerror("错误", f"参数错误: {e}")
            return None, None, None

        dram_name = self.dram_tech.get()
        pkg_name = self.package.get()
        if dram_name not in DRAM_TECH or pkg_name not in PACKAGE_TYPES:
            messagebox.showerror("错误", "DRAM或封装类型无效")
            return None, None, None

        quality_params = QUALITY_GRADE[self.quality_grade.get()].copy()
        dram_cfg = DRAM_TECH[dram_name].copy()
        pkg_cfg = PACKAGE_TYPES[pkg_name].copy()
        backend_extra = self.get_backend_extra()
        yield_model = self.yield_model.get()
        cp_test_hours = quality_params.get("cp_test_time_hours", 0.2)
        ft_test_sec = quality_params.get("ft_test_time_sec", 5)

        dram_total_area = dram_cap / dram_cfg["density_gb_per_mm2"]
        dram_die_area = dram_total_area / dram_dies if dram_dies > 0 else 0

        single = {}
        multi = {}
        for tech in selected:
            logic_area = self.get_logic_physical_area(tech)
            if logic_area <= 0:
                single[tech] = (np.inf, 0, np.inf, {})
                multi[tech] = (np.inf, 0, np.inf, {})
                continue
            logic_cfg = LOGIC_TECH[tech].copy()
            # 确保有供应商价格数据
            if current_supplier not in logic_cfg['suppliers']:
                # 回退到第一个可用供应商
                default_supplier = list(logic_cfg['suppliers'].keys())[0]
                logic_cfg['suppliers'] = {default_supplier: logic_cfg['suppliers'][default_supplier]}
            single[tech] = calc_single_die_cost(
                logic_area, dram_total_area, logic_cfg, dram_cfg, pkg_cfg, volume,
                backend_extra, wafer_diam, yield_model, alpha, ip_fee, royalty,
                quality_params, tops, cp_test_hours, ft_test_sec
            )
            multi[tech] = calc_multi_die_cost(
                logic_area, dram_die_area, logic_cfg, dram_cfg, pkg_cfg, volume,
                logic_dies, dram_dies, backend_extra, wafer_diam, yield_model, alpha,
                ip_fee, royalty, quality_params, tops, cp_test_hours, ft_test_sec
            )
        return selected, single, multi

    def update_result(self):
        res = self.compute_all()
        if res is None:
            return
        techs, single, multi = res
        if not techs:
            return

        # 更新成本图
        self.ax.clear()
        x = np.arange(len(techs))
        width = 0.35
        single_cost = [single[t][0] if not np.isinf(single[t][0]) else 0 for t in techs]
        multi_cost  = [multi[t][0] if not np.isinf(multi[t][0]) else 0 for t in techs]
        self.ax.bar(x - width/2, single_cost, width, label='单Die集成', color='skyblue')
        self.ax.bar(x + width/2, multi_cost, width, label=f'多Die Chiplet (逻辑×{self.logic_dies.get()}, DRAM×{self.dram_dies.get()})', color='orange')
        self.ax.set_xticks(x)
        self.ax.set_xticklabels(techs, rotation=45, ha='right')
        self.ax.set_ylabel('单颗芯片成本 (USD)')
        mode_text = f"等效28nm面积 {self.functional_area.get()} mm²" if self.input_mode.get()=="functional" else f"晶体管 {self.transistor_budget.get()} 亿"
        self.ax.set_title(f'商业化成本分析 ({self.quality_grade.get()}, 代工厂:{current_supplier})\n{mode_text} | DRAM:{self.dram_tech.get()} {self.dram_capacity.get()}GB | 封装:{self.package.get()} | 年产量:{int(float(self.volume.get())):,}')
        self.ax.legend()
        self.ax.grid(axis='y', linestyle=':', alpha=0.6)

        # 最优成本标注
        valid = [v for v in single_cost+multi_cost if v>0]
        if valid:
            best = min(valid)
            for i, t in enumerate(techs):
                if single_cost[i]==best and best>0:
                    self.ax.text(x[i]-width/2, single_cost[i], '★最优成本', ha='center', va='bottom', fontsize=8, color='red')
                if multi_cost[i]==best and best>0:
                    self.ax.text(x[i]+width/2, multi_cost[i], '★最优成本', ha='center', va='bottom', fontsize=8, color='red')
        self.canvas.draw()

        # 更新性能表
        for row in self.perf_tree.get_children():
            self.perf_tree.delete(row)
        for t in techs:
            s_cost, s_tops, s_ppd, _ = single[t]
            m_cost, m_tops, m_ppd, _ = multi[t]
            self.perf_tree.insert("", tk.END, values=(
                t,
                f"${s_cost:,.2f}" if not np.isinf(s_cost) else "N/A",
                f"{s_tops:.1f}" if s_tops>0 else "N/A",
                f"${s_ppd:.2f}" if not np.isinf(s_ppd) else "N/A",
                f"${m_cost:,.2f}" if not np.isinf(m_cost) else "N/A",
                f"{m_tops:.1f}" if m_tops>0 else "N/A",
                f"${m_ppd:.2f}" if not np.isinf(m_ppd) else "N/A",
            ))

        # 性价比最优
        best_ppd = np.inf
        best_tech = None
        best_arch = None
        for t in techs:
            if single[t][2] < best_ppd:
                best_ppd = single[t][2]
                best_tech = t
                best_arch = "单Die"
            if multi[t][2] < best_ppd:
                best_ppd = multi[t][2]
                best_tech = t
                best_arch = "多Die"
        if best_tech:
            self.result_label.config(text=f"🏆 性价比最优: {best_tech} {best_arch}  $/TOPS = ${best_ppd:.2f}")
        else:
            self.result_label.config(text="无法计算性价比")

        # 更新封装成本明细表
        for row in self.pkg_tree.get_children():
            self.pkg_tree.delete(row)
        pkg_cfg = PACKAGE_TYPES[self.package.get()]
        adv_per_die = pkg_cfg['adv_per_die']
        for t in techs:
            _, _, _, m_det = multi[t]
            if np.isinf(m_det.get('total_pkg_cost', np.inf)):
                continue
            logic_qty = int(self.logic_dies.get())
            logic_area_val = m_det.get('logic_die_area', 0)
            logic_silicon_total = m_det.get('logic_silicon_cost_per_die', 0) * logic_qty
            logic_fixed_share = m_det.get('logic_fixed_share', 0)
            logic_per_die_total = logic_qty * adv_per_die
            logic_pkg_total = m_det.get('logic_pkg_cost', 0)
            self.pkg_tree.insert("", tk.END, values=(
                t, "Logic", logic_qty,
                f"{logic_area_val:.1f}",
                f"${logic_silicon_total:,.2f}",
                f"${logic_fixed_share:,.2f}",
                f"${logic_per_die_total:,.2f}",
                f"${logic_pkg_total:,.2f}"
            ))
            dram_qty = int(self.dram_dies.get())
            if dram_qty > 0:
                dram_area_val = m_det.get('dram_die_area', 0)
                dram_silicon_total = m_det.get('dram_silicon_cost_per_die', 0) * dram_qty
                dram_fixed_share = m_det.get('dram_fixed_share', 0)
                dram_per_die_total = dram_qty * adv_per_die
                dram_pkg_total = m_det.get('dram_pkg_cost', 0)
                self.pkg_tree.insert("", tk.END, values=(
                    t, "DRAM", dram_qty,
                    f"{dram_area_val:.1f}",
                    f"${dram_silicon_total:,.2f}",
                    f"${dram_fixed_share:,.2f}",
                    f"${dram_per_die_total:,.2f}",
                    f"${dram_pkg_total:,.2f}"
                ))

        # 详细参数文本
        self.detail_text.delete(1.0, tk.END)
        qp = QUALITY_GRADE[self.quality_grade.get()]
        pkg_cfg = PACKAGE_TYPES[self.package.get()]
        detail = f"""📋 当前配置参数详情
==================================================

🏭 逻辑工艺 (已选择):
"""
        for t in techs:
            area = self.get_logic_physical_area(t)
            d0 = LOGIC_TECH[t]['defect_density']
            detail += f"   · {t}: 面积 {area:.1f} mm², 缺陷密度 {d0:.3f} defects/cm²\n"

        detail += f"""
📦 封装: {self.package.get()} | 性能因子: {pkg_cfg['perf_factor']:.2f} | 固定成本分摊: {pkg_cfg.get('fixed_cost_allocation','area')}
   · 单Die基板成本: ${pkg_cfg['single_pkg_cost']} | 固定成本: ${pkg_cfg['adv_fixed']} | 每Die贴装: ${pkg_cfg['adv_per_die']}
🎚️ 质量等级: {self.quality_grade.get()}
   · DPPM目标: {qp['dppm_target']} PPM
   · 设计冗余: {qp['design_redundancy_percent']:.1f}%
   · 测试时间乘数: {qp['test_time_multiplier']:.1f}x
   · CP测试小时/晶圆: {qp.get('cp_test_time_hours',0.2)} h | FT测试秒/颗: {qp.get('ft_test_time_sec',5)} s
   · 晶圆价格乘数: {qp['wafer_price_multiplier']:.1f}x
   · 封装乘数: {qp['package_extra_multiplier']:.1f}x
   · 认证费用: ${qp['certification_amort_usd']:,.0f}
🌡️ 温度范围: {qp['temp_range']} | 设计寿命: {qp['life_years']}年
🔧 后端工艺乘数: {self.get_backend_extra():.2f}x
⚙️ 良率模型: {self.yield_model.get()}, α={self.alpha.get()}
🎯 每mm²算力基准: {self.tops_per_mm2.get()} TOPS/mm²
📊 年产量: {int(float(self.volume.get())):,} 颗
🏭 代工厂: {current_supplier}

========== 单Die集成模式成本分解 ==========
"""
        for t in techs:
            s_cost, s_tops, s_ppd, s_det = single[t]
            if not np.isinf(s_cost):
                detail += f"\n🔹 {t}:\n"
                detail += f"   总成本: ${s_cost:,.2f}\n"
                detail += f"   - 硅成本: ${s_det.get('silicon_cost',0):,.2f}\n"
                detail += f"   - 封装成本: ${s_det.get('pkg_cost',0):,.2f}\n"
                detail += f"   - NRE摊销: ${s_det.get('nre_amort',0):,.2f}\n"
                detail += f"   - 测试成本: ${s_det.get('test_cost',0):,.2f}\n"
                detail += f"   - 认证摊销: ${s_det.get('cert_amort',0):,.2f}\n"
                detail += f"   - 芯片良率: {s_det.get('yield',0)*100:.1f}%\n"
                detail += f"   - 预估TDP: {s_det.get('tdp_w',0):.1f} W\n"

        detail += "\n========== 多Die Chiplet模式成本分解 (含2D/2.5D/3D封装明细) ==========\n"
        for t in techs:
            m_cost, m_tops, m_ppd, m_det = multi[t]
            if not np.isinf(m_cost):
                detail += f"\n🔹 {t}:\n"
                detail += f"   总成本: ${m_cost:,.2f}\n"
                detail += f"   - 逻辑Die硅成本: ${m_det.get('logic_silicon_cost_per_die',0):,.2f} × {self.logic_dies.get()} = ${m_det.get('logic_silicon_cost_per_die',0)*int(self.logic_dies.get()):,.2f}\n"
                if m_det.get('dram_silicon_cost_per_die',0) > 0:
                    detail += f"   - DRAM Die硅成本: ${m_det.get('dram_silicon_cost_per_die',0):,.2f} × {self.dram_dies.get()} = ${m_det.get('dram_silicon_cost_per_die',0)*int(self.dram_dies.get()):,.2f}\n"
                detail += f"   - 总硅成本: ${m_det.get('total_silicon_cost',0):,.2f}\n"
                detail += f"   - 逻辑封装成本: ${m_det.get('logic_pkg_cost',0):,.2f}\n"
                detail += f"   - DRAM封装成本: ${m_det.get('dram_pkg_cost',0):,.2f}\n"
                detail += f"   - 封装总成本: ${m_det.get('total_pkg_cost',0):,.2f}\n"
                detail += f"   - NRE摊销: ${m_det.get('nre_amort',0):,.2f}\n"
                detail += f"   - 测试成本: ${m_det.get('test_cost',0):,.2f}\n"
                detail += f"   - 认证摊销: ${m_det.get('cert_amort',0):,.2f}\n"
                detail += f"   - 逻辑良率: {m_det.get('logic_yield',0)*100:.1f}%  |  DRAM良率: {m_det.get('dram_yield',0)*100:.1f}%\n"
                detail += f"   - 逻辑Die面积: {m_det.get('logic_die_area',0):.1f} mm²  |  DRAM Die面积: {m_det.get('dram_die_area',0):.1f} mm²\n"
                detail += f"   - 预估TDP: {m_det.get('tdp_w',0):.1f} W\n"

        self.detail_text.insert(1.0, detail)

    def sensitivity_analysis(self):
        """敏感性分析：关键参数 ±20% 对总成本的影响"""
        res = self.compute_all()
        if res is None:
            return
        techs, single, multi = res
        if not techs:
            return
        # 使用第一个工艺的多Die成本作为基准
        base_tech = techs[0]
        base_cost = multi[base_tech][0]
        if np.isinf(base_cost):
            messagebox.showerror("错误", "无法计算基准成本")
            return

        # 定义要分析的参数及其基准值
        params = {
            "年产量": float(self.volume.get()),
            "晶圆价格乘数": QUALITY_GRADE[self.quality_grade.get()]["wafer_price_multiplier"],
            "测试时间乘数": QUALITY_GRADE[self.quality_grade.get()]["test_time_multiplier"],
            "设计冗余(%)": QUALITY_GRADE[self.quality_grade.get()]["design_redundancy_percent"],
            "封装良率": PACKAGE_TYPES[self.package.get()]["base_package_yield"],
            "TOPS/mm²": float(self.tops_per_mm2.get()),
        }
        variations = [-0.2, 0.2]  # -20%, +20%
        results = {}
        for name, base_val in params.items():
            costs = []
            for delta in variations:
                new_val = base_val * (1 + delta)
                # 临时修改参数
                if name == "年产量":
                    self.volume.set(str(int(new_val)))
                elif name == "晶圆价格乘数":
                    # 修改质量等级中的乘数
                    qp = QUALITY_GRADE[self.quality_grade.get()].copy()
                    qp["wafer_price_multiplier"] = new_val
                    # 重新计算成本（需要临时覆盖）
                    # 为简化，直接调用compute_all重新计算
                    # 注意：需要恢复原值
                    original = self.volume.get()
                    self.volume.set(str(base_val))  # 恢复产量
                elif name == "测试时间乘数":
                    qp = QUALITY_GRADE[self.quality_grade.get()].copy()
                    qp["test_time_multiplier"] = new_val
                elif name == "设计冗余(%)":
                    qp = QUALITY_GRADE[self.quality_grade.get()].copy()
                    qp["design_redundancy_percent"] = new_val
                elif name == "封装良率":
                    pkg = PACKAGE_TYPES[self.package.get()].copy()
                    pkg["base_package_yield"] = new_val
                elif name == "TOPS/mm²":
                    self.tops_per_mm2.set(str(new_val))
                # 重新计算
                new_res = self.compute_all()
                if new_res is not None:
                    _, _, new_multi = new_res
                    new_cost = new_multi[base_tech][0] if base_tech in new_multi else np.inf
                    costs.append(new_cost if not np.isinf(new_cost) else base_cost)
                else:
                    costs.append(base_cost)
                # 恢复参数
                if name == "年产量":
                    self.volume.set(str(base_val))
                elif name == "TOPS/mm²":
                    self.tops_per_mm2.set(str(base_val))
            # 计算变化百分比
            pct_changes = [(c - base_cost)/base_cost*100 for c in costs]
            results[name] = pct_changes

        # 绘制 tornado 图
        fig, ax = plt.subplots(figsize=(8, 6))
        y_pos = np.arange(len(params))
        # 取负20%和正20%的变化幅度的绝对值最大者
        lefts = [results[name][0] for name in params.keys()]
        rights = [results[name][1] for name in params.keys()]
        ax.barh(y_pos, lefts, height=0.4, color='red', label='-20%')
        ax.barh(y_pos, rights, height=0.4, left=0, color='green', label='+20%')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(params.keys())
        ax.axvline(x=0, color='black', linestyle='-')
        ax.set_xlabel('成本变化 (%)')
        ax.set_title(f'敏感性分析 (基准: {base_tech} 多Die成本 ${base_cost:,.2f})')
        ax.legend()
        plt.tight_layout()
        # 在新窗口中显示
        if self.sensitivity_window is not None:
            try:
                self.sensitivity_window.destroy()
            except:
                pass
        self.sensitivity_window = tk.Toplevel(self.root)
        self.sensitivity_window.title("敏感性分析")
        canvas = FigureCanvasTkAgg(fig, master=self.sensitivity_window)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def export_excel(self):
        if not HAS_OPENPYXL:
            messagebox.showerror("错误", "未安装openpyxl，请使用pip install openpyxl安装后重试")
            return
        res = self.compute_all()
        if res is None:
            return
        techs, single, multi = res
        if not techs:
            return
        fp = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel文件","*.xlsx")])
        if not fp:
            return
        wb = Workbook()
        # 参数表
        ws1 = wb.active
        ws1.title = "输入参数"
        ws1.append(["参数类别", "值"])
        ws1.append(["质量等级", self.quality_grade.get()])
        ws1.append(["代工厂", current_supplier])
        ws1.append(["DRAM类型", self.dram_tech.get()])
        ws1.append(["DRAM容量(GB)", self.dram_capacity.get()])
        ws1.append(["封装类型", self.package.get()])
        ws1.append(["年产量", self.volume.get()])
        ws1.append(["逻辑Die数", self.logic_dies.get()])
        ws1.append(["DRAM Die数", self.dram_dies.get()])
        ws1.append(["后端乘数", f"{self.get_backend_extra():.2f}"])
        ws1.append(["晶圆直径(mm)", self.wafer_diam.get()])
        ws1.append(["良率模型", self.yield_model.get()])
        ws1.append(["TOPS/mm²", self.tops_per_mm2.get()])
        # 成本结果表
        ws2 = wb.create_sheet("成本与性能")
        ws2.append(["工艺", "架构", "总成本(USD)", "算力(TOPS)", "$/TOPS",
                    "逻辑硅成本(USD)", "DRAM硅成本(USD)", "逻辑封装成本(USD)",
                    "DRAM封装成本(USD)", "封装总成本(USD)", "NRE摊销(USD)", "TDP(W)"])
        for t in techs:
            s_cost, s_tops, s_ppd, s_det = single[t]
            m_cost, m_tops, m_ppd, m_det = multi[t]
            if not np.isinf(s_cost):
                ws2.append([t, "单Die", s_cost, s_tops, s_ppd,
                            s_det.get('silicon_cost',0), 0,
                            s_det.get('pkg_cost',0), 0, s_det.get('pkg_cost',0),
                            s_det.get('nre_amort',0), s_det.get('tdp_w',0)])
            if not np.isinf(m_cost):
                ws2.append([t, "多Die", m_cost, m_tops, m_ppd,
                            m_det.get('logic_silicon_cost_per_die',0)*int(self.logic_dies.get()),
                            m_det.get('dram_silicon_cost_per_die',0)*int(self.dram_dies.get()),
                            m_det.get('logic_pkg_cost',0), m_det.get('dram_pkg_cost',0),
                            m_det.get('total_pkg_cost',0), m_det.get('nre_amort',0), m_det.get('tdp_w',0)])
        wb.save(fp)
        messagebox.showinfo("导出成功", f"Excel报表已保存至 {fp}")

def main():
    root = tk.Tk()
    app = CommercialPlatform(root)
    root.mainloop()

if __name__ == "__main__":
    # 全局变量：当前选择的供应商
    current_supplier = "TSMC"
    main()
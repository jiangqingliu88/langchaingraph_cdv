import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import csv

# ================== 全局配置 ==================
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

# ================== 工艺数据库 ==================
LOGIC_TECH = {
    "28nm": {"density": 0.10, "wafer_price": 3500, "defect_density": 0.025,
             "nre_single": 40e6, "nre_multi_base": 20e6, "nre_per_die": 2e6},
    "14nm": {"density": 0.25, "wafer_price": 8000, "defect_density": 0.045,
             "nre_single": 90e6, "nre_multi_base": 45e6, "nre_per_die": 4e6},
    "7nm":  {"density": 0.60, "wafer_price": 12000, "defect_density": 0.07,
             "nre_single": 250e6, "nre_multi_base": 100e6, "nre_per_die": 8e6},
    "5nm":  {"density": 1.30, "wafer_price": 18500, "defect_density": 0.10,
             "nre_single": 450e6, "nre_multi_base": 180e6, "nre_per_die": 12e6},
    "3nm":  {"density": 2.00, "wafer_price": 24000, "defect_density": 0.13,
             "nre_single": 600e6, "nre_multi_base": 250e6, "nre_per_die": 15e6},
    "成熟工艺 (55nm)": {"density": 0.03, "wafer_price": 2800, "defect_density": 0.018,
                        "nre_single": 20e6, "nre_multi_base": 12e6, "nre_per_die": 1e6}
}

DRAM_TECH = {
    "DDR4 (20nm)":   {"density_gb_per_mm2": 0.008, "wafer_price": 3000, "defect_density": 0.02,
                      "nre_single": 15e6, "nre_multi_base": 8e6, "nre_per_die": 1e6},
    "DDR5 (1z nm)":  {"density_gb_per_mm2": 0.016, "wafer_price": 4000, "defect_density": 0.025,
                      "nre_single": 20e6, "nre_multi_base": 10e6, "nre_per_die": 1.5e6},
    "LPDDR5 (1a nm)":{"density_gb_per_mm2": 0.020, "wafer_price": 4500, "defect_density": 0.03,
                      "nre_single": 25e6, "nre_multi_base": 12e6, "nre_per_die": 2e6},
    "HBM2E (1y nm)": {"density_gb_per_mm2": 0.030, "wafer_price": 6000, "defect_density": 0.04,
                      "nre_single": 40e6, "nre_multi_base": 20e6, "nre_per_die": 3e6, "stacked": True},
    "HBM3 (1b nm)":  {"density_gb_per_mm2": 0.045, "wafer_price": 8000, "defect_density": 0.05,
                      "nre_single": 60e6, "nre_multi_base": 30e6, "nre_per_die": 4e6, "stacked": True}
}

PACKAGE_TYPES = {
    "2D MCM":            {"single_pkg_cost": 10, "adv_fixed": 150, "adv_per_die": 50,  "safety":1.0, "reliability":1.0},
    "2.5D CoWoS-S":      {"single_pkg_cost": 20, "adv_fixed": 400, "adv_per_die": 180, "safety":1.0, "reliability":1.0},
    "2.5D CoWoS-R":      {"single_pkg_cost": 18, "adv_fixed": 350, "adv_per_die": 160, "safety":1.0, "reliability":1.0},
    "3D TSV (真3D堆叠)":  {"single_pkg_cost": 50, "adv_fixed": 800, "adv_per_die": 350, "safety":1.05, "reliability":1.1}
}

BACKEND_OPTIONS = {
    "基板层数":   {"2层":1.0, "4层":1.2, "6层":1.5, "8层":2.0},
    "凸块间距":   {"标准 130μm":1.0, "细间距 55μm":1.3, "超细间距 25μm":1.8},
    "散热方案":   {"被动散热":1.0, "主动风冷":1.1, "液冷":1.5},
    "测试等级":   {"常温测试":1.0, "工业级(-40~85°C)":1.2, "车规级(-40~125°C)":1.5}
}

# ================== 核心模型 ==================
def die_yield(area_cm2, defect_density, alpha=4.0):
    if area_cm2 <= 0: return 0.0
    return (1 + area_cm2 * defect_density / alpha) ** (-alpha)

def calc_single_die_cost(logic_phys_area, dram_total_area, logic_cfg, dram_cfg, pkg_cfg, volume, backend_extra):
    total_area = logic_phys_area + dram_total_area
    if total_area <= 0: return np.inf
    wafer_area_mm2 = np.pi * (150**2)
    area_cm2 = total_area / 100
    y = die_yield(area_cm2, logic_cfg['defect_density'])
    if y <= 0: return np.inf
    dies_per_wafer = wafer_area_mm2 / total_area
    good_dies = dies_per_wafer * y
    silicon_cost = logic_cfg['wafer_price'] / good_dies
    pkg_cost = pkg_cfg['single_pkg_cost']
    nre_amort = logic_cfg['nre_single'] / volume
    total = (silicon_cost + pkg_cost + nre_amort) * pkg_cfg['safety'] * pkg_cfg['reliability'] * backend_extra
    return total

def calc_multi_die_cost(logic_phys_area, dram_die_area, logic_cfg, dram_cfg, pkg_cfg, volume,
                        num_logic_dies, num_dram_dies, backend_extra):
    wafer_area_mm2 = np.pi * (150**2)
    # 逻辑die成本
    logic_area_cm2 = logic_phys_area / 100
    y_logic = die_yield(logic_area_cm2, logic_cfg['defect_density'])
    if y_logic <= 0: return np.inf
    logic_dies_per_wafer = wafer_area_mm2 / logic_phys_area
    good_logic_per_wafer = logic_dies_per_wafer * y_logic
    silicon_cost_per_logic = logic_cfg['wafer_price'] / good_logic_per_wafer
    total_silicon_logic = num_logic_dies * silicon_cost_per_logic
    # DRAM die成本
    dram_area_cm2 = dram_die_area / 100
    y_dram = die_yield(dram_area_cm2, dram_cfg['defect_density'])
    if y_dram <= 0: return np.inf
    dram_dies_per_wafer = wafer_area_mm2 / dram_die_area
    good_dram_per_wafer = dram_dies_per_wafer * y_dram
    silicon_cost_per_dram = dram_cfg['wafer_price'] / good_dram_per_wafer
    total_silicon_dram = num_dram_dies * silicon_cost_per_dram
    total_silicon = total_silicon_logic + total_silicon_dram
    # 封装成本
    total_dies = num_logic_dies + num_dram_dies
    pkg_cost = pkg_cfg['adv_fixed'] + total_dies * pkg_cfg['adv_per_die']
    # NRE
    nre_logic = logic_cfg['nre_multi_base'] + num_logic_dies * logic_cfg['nre_per_die']
    nre_dram = dram_cfg['nre_multi_base'] + num_dram_dies * dram_cfg['nre_per_die']
    nre_amort = (nre_logic + nre_dram) / volume
    total = (total_silicon + pkg_cost + nre_amort) * pkg_cfg['safety'] * pkg_cfg['reliability'] * backend_extra
    return total

# ================== GUI ==================
class FunctionFirstPlatform:
    def __init__(self, root):
        self.root = root
        root.title("芯片架构成本平台 - 功能优先版 (面积↔晶体管自动同步)")
        root.geometry("1400x950")

        # 默认参数
        self.input_mode = tk.StringVar(value="functional")
        self.functional_area = tk.StringVar(value="400")
        self.transistor_budget = tk.StringVar(value="40.0")     # 400*0.1=40
        self.dram_capacity = tk.StringVar(value="16")
        self.dram_tech = tk.StringVar(value="HBM3 (1b nm)")
        self.package = tk.StringVar(value="2.5D CoWoS-S")
        self.volume = tk.StringVar(value="1000000")
        self.logic_dies = tk.StringVar(value="1")
        self.dram_dies = tk.StringVar(value="4")
        self.substrates = tk.StringVar(value="4层")
        self.bump = tk.StringVar(value="细间距 55μm")
        self.cooling = tk.StringVar(value="主动风冷")
        self.test = tk.StringVar(value="工业级(-40~85°C)")

        self.create_widgets()
        self.update_result()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_frame, width=500)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        left_frame.pack_propagate(False)

        # ========== 1. 功能规模定义 ==========
        group1 = ttk.LabelFrame(left_frame, text="1️⃣ 确定逻辑功能规模（面积与晶体管等价）", padding=5)
        group1.pack(fill=tk.X, pady=5)

        ttk.Label(group1, text="输入模式:").grid(row=0, column=0, sticky=tk.W, pady=2)
        mode_combo = ttk.Combobox(group1, textvariable=self.input_mode, values=["functional", "transistor"], state="readonly")
        mode_combo.grid(row=0, column=1, sticky=tk.W, pady=2)
        mode_combo.bind("<<ComboboxSelected>>", self.on_mode_change)

        row=1
        self.func_label = ttk.Label(group1, text="等效28nm面积 (mm²):")
        self.func_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self.func_entry = ttk.Entry(group1, textvariable=self.functional_area)
        self.func_entry.grid(row=row, column=1, sticky=tk.W, pady=2)

        row+=1
        self.trans_label = ttk.Label(group1, text="晶体管数量 (亿):")
        self.trans_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self.trans_entry = ttk.Entry(group1, textvariable=self.transistor_budget)
        self.trans_entry.grid(row=row, column=1, sticky=tk.W, pady=2)

        # 绑定事件
        self.func_entry.bind("<KeyRelease>", self.on_area_change)
        self.trans_entry.bind("<KeyRelease>", self.on_transistor_change)

        self.on_mode_change()  # 初始状态

        # ========== 2. 候选逻辑工艺 ==========
        group2 = ttk.LabelFrame(left_frame, text="2️⃣ 选择候选逻辑工艺（多选）", padding=5)
        group2.pack(fill=tk.X, pady=5)

        self.logic_vars = {}
        frame_techs = ttk.Frame(group2)
        frame_techs.pack(fill=tk.X)
        tech_list = list(LOGIC_TECH.keys())
        for i, tech in enumerate(tech_list):
            var = tk.BooleanVar(value=(tech in ["5nm", "7nm"]))
            cb = ttk.Checkbutton(frame_techs, text=tech, variable=var)
            cb.grid(row=i//3, column=i%3, sticky=tk.W, padx=5)
            self.logic_vars[tech] = var

        # ========== 3. DRAM与封装 ==========
        group3 = ttk.LabelFrame(left_frame, text="3️⃣ DRAM与封装选型", padding=5)
        group3.pack(fill=tk.X, pady=5)

        ttk.Label(group3, text="DRAM类型:").grid(row=0, column=0, sticky=tk.W, pady=2)
        dram_combo = ttk.Combobox(group3, textvariable=self.dram_tech, values=list(DRAM_TECH.keys()), state="readonly")
        dram_combo.grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(group3, text="DRAM容量 (GB):").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(group3, textvariable=self.dram_capacity).grid(row=1, column=1, sticky=tk.W, pady=2)
        ttk.Label(group3, text="封装类型:").grid(row=2, column=0, sticky=tk.W, pady=2)
        pkg_combo = ttk.Combobox(group3, textvariable=self.package, values=list(PACKAGE_TYPES.keys()), state="readonly")
        pkg_combo.grid(row=2, column=1, sticky=tk.W, pady=2)
        ttk.Label(group3, text="年产量 (颗):").grid(row=3, column=0, sticky=tk.W, pady=2)
        ttk.Entry(group3, textvariable=self.volume).grid(row=3, column=1, sticky=tk.W, pady=2)

        # ========== 4. 架构选型 ==========
        group4 = ttk.LabelFrame(left_frame, text="4️⃣ 集成架构选择", padding=5)
        group4.pack(fill=tk.X, pady=5)

        ttk.Label(group4, text="逻辑Die拆分数:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(group4, textvariable=self.logic_dies, width=8).grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(group4, text="DRAM Die拆分数:").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(group4, textvariable=self.dram_dies, width=8).grid(row=1, column=1, sticky=tk.W, pady=2)

        # ========== 5. 后端工艺 ==========
        group5 = ttk.LabelFrame(left_frame, text="5️⃣ 后端工艺选型（成本乘数）", padding=5)
        group5.pack(fill=tk.X, pady=5)

        ttk.Label(group5, text="基板层数:").grid(row=0, column=0, sticky=tk.W, pady=2)
        sub_combo = ttk.Combobox(group5, textvariable=self.substrates, values=list(BACKEND_OPTIONS["基板层数"].keys()), state="readonly")
        sub_combo.grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(group5, text="凸块间距:").grid(row=1, column=0, sticky=tk.W, pady=2)
        bump_combo = ttk.Combobox(group5, textvariable=self.bump, values=list(BACKEND_OPTIONS["凸块间距"].keys()), state="readonly")
        bump_combo.grid(row=1, column=1, sticky=tk.W, pady=2)
        ttk.Label(group5, text="散热方案:").grid(row=2, column=0, sticky=tk.W, pady=2)
        cool_combo = ttk.Combobox(group5, textvariable=self.cooling, values=list(BACKEND_OPTIONS["散热方案"].keys()), state="readonly")
        cool_combo.grid(row=2, column=1, sticky=tk.W, pady=2)
        ttk.Label(group5, text="测试等级:").grid(row=3, column=0, sticky=tk.W, pady=2)
        test_combo = ttk.Combobox(group5, textvariable=self.test, values=list(BACKEND_OPTIONS["测试等级"].keys()), state="readonly")
        test_combo.grid(row=3, column=1, sticky=tk.W, pady=2)

        # 按钮
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=15)
        ttk.Button(btn_frame, text="计算成本对比", command=self.update_result).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="导出报告", command=self.export_report).pack(side=tk.LEFT, padx=5)

        self.result_label = ttk.Label(left_frame, text="", foreground="blue")
        self.result_label.pack(pady=5)

        # 右侧绘图区
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.fig, self.ax = plt.subplots(figsize=(9, 6))
        self.canvas = FigureCanvasTkAgg(self.fig, master=right_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def on_mode_change(self, event=None):
        mode = self.input_mode.get()
        if mode == "functional":
            # 功能模式：面积可编辑，晶体管只读
            self.func_entry.config(state="normal")
            self.trans_entry.config(state="readonly")
            self.sync_transistor_from_area()
        else:
            # 晶体管模式：晶体管可编辑，面积只读
            self.func_entry.config(state="readonly")
            self.trans_entry.config(state="normal")
            self.sync_area_from_transistor()

    def on_area_change(self, event=None):
        if self.input_mode.get() == "functional":
            self.sync_transistor_from_area()

    def on_transistor_change(self, event=None):
        if self.input_mode.get() == "transistor":
            self.sync_area_from_transistor()

    def sync_transistor_from_area(self):
        try:
            area = float(self.functional_area.get())
            transistors = area * 0.1   # 28nm密度 0.1 亿/mm²
            self.transistor_budget.set(f"{transistors:.1f}")
        except:
            pass

    def sync_area_from_transistor(self):
        try:
            trans = float(self.transistor_budget.get())
            area = trans / 0.1
            self.functional_area.set(f"{area:.1f}")
        except:
            pass

    def get_logic_physical_area(self, tech):
        mode = self.input_mode.get()
        try:
            if mode == "functional":
                eq_area = float(self.functional_area.get())
                base_density = LOGIC_TECH["28nm"]["density"]
                tech_density = LOGIC_TECH[tech]["density"]
                return eq_area * (base_density / tech_density)
            else:
                transistor_billions = float(self.transistor_budget.get())
                tech_density = LOGIC_TECH[tech]["density"]
                total_mtr = transistor_billions * 100
                return total_mtr / tech_density
        except:
            return 0

    def get_backend_extra(self):
        sub = BACKEND_OPTIONS["基板层数"].get(self.substrates.get(), 1.0)
        bump = BACKEND_OPTIONS["凸块间距"].get(self.bump.get(), 1.0)
        cool = BACKEND_OPTIONS["散热方案"].get(self.cooling.get(), 1.0)
        test = BACKEND_OPTIONS["测试等级"].get(self.test.get(), 1.0)
        return sub * bump * cool * test

    def compute_costs(self):
        selected_techs = [tech for tech, var in self.logic_vars.items() if var.get()]
        if not selected_techs:
            messagebox.showerror("错误", "请至少选择一个逻辑工艺")
            return None, None, None
        try:
            volume = int(float(self.volume.get()))
            logic_dies = int(self.logic_dies.get())
            dram_dies = int(self.dram_dies.get())
            dram_cap = float(self.dram_capacity.get())
        except ValueError:
            messagebox.showerror("错误", "请检查产量、拆分数、DRAM容量是否为数字")
            return None, None, None

        dram_tech_name = self.dram_tech.get()
        pkg_name = self.package.get()
        if dram_tech_name not in DRAM_TECH or pkg_name not in PACKAGE_TYPES:
            messagebox.showerror("错误", "DRAM或封装类型无效")
            return None, None, None

        dram_cfg = DRAM_TECH[dram_tech_name].copy()
        pkg_cfg = PACKAGE_TYPES[pkg_name].copy()
        backend_extra = self.get_backend_extra()

        dram_total_area_mm2 = dram_cap / dram_cfg["density_gb_per_mm2"]
        dram_die_area_mm2 = dram_total_area_mm2 / dram_dies if dram_dies > 0 else 0

        single_costs = {}
        multi_costs = {}
        for tech in selected_techs:
            logic_phys_area = self.get_logic_physical_area(tech)
            if logic_phys_area <= 0:
                single_costs[tech] = np.inf
                multi_costs[tech] = np.inf
                continue
            logic_cfg = LOGIC_TECH[tech].copy()
            single = calc_single_die_cost(logic_phys_area, dram_total_area_mm2,
                                          logic_cfg, dram_cfg, pkg_cfg, volume, backend_extra)
            multi = calc_multi_die_cost(logic_phys_area, dram_die_area_mm2,
                                        logic_cfg, dram_cfg, pkg_cfg, volume,
                                        logic_dies, dram_dies, backend_extra)
            single_costs[tech] = single
            multi_costs[tech] = multi
        return selected_techs, single_costs, multi_costs

    def update_result(self):
        result = self.compute_costs()
        if result is None:
            return
        selected_techs, single_costs, multi_costs = result
        # 防御：如果 selected_techs 为空或 None
        if not selected_techs:
            messagebox.showwarning("警告", "没有选中的逻辑工艺")
            return

        self.ax.clear()
        x = np.arange(len(selected_techs))
        width = 0.35
        single_vals = [single_costs[t] for t in selected_techs]
        multi_vals = [multi_costs[t] for t in selected_techs]

        # 替换inf为0（避免绘图出错）
        single_vals = [0 if np.isinf(v) else v for v in single_vals]
        multi_vals  = [0 if np.isinf(v) else v for v in multi_vals]

        self.ax.bar(x - width/2, single_vals, width, label='单Die集成 (逻辑+DRAM同die)', color='skyblue')
        self.ax.bar(x + width/2, multi_vals, width, label=f'多Die Chiplet (逻辑×{self.logic_dies.get()}, DRAM×{self.dram_dies.get()})', color='orange')
        self.ax.set_xticks(x)
        self.ax.set_xticklabels(selected_techs, rotation=45, ha='right')
        self.ax.set_ylabel('单颗芯片成本 (美元)')
        mode_text = f"等效28nm面积 {self.functional_area.get()} mm²" if self.input_mode.get() == "functional" else f"晶体管 {self.transistor_budget.get()} 亿"
        self.ax.set_title(f'实现相同逻辑功能 ({mode_text})\nDRAM:{self.dram_tech.get()} {self.dram_capacity.get()}GB, 封装:{self.package.get()}, 年产量:{int(float(self.volume.get())):,}')
        self.ax.legend()
        self.ax.grid(axis='y', linestyle=':', alpha=0.6)

        # 找出最优方案（忽略0值）
        valid_single = [v for v in single_vals if v>0]
        valid_multi  = [v for v in multi_vals if v>0]
        if not valid_single and not valid_multi:
            self.result_label.config(text="无法计算有效成本，请检查参数")
            self.canvas.draw()
            return
        best_cost = min(min(single_vals), min(multi_vals))
        best_idx_single = single_vals.index(best_cost) if best_cost in single_vals else -1
        best_idx_multi = multi_vals.index(best_cost) if best_cost in multi_vals else -1
        if best_idx_single >= 0:
            best_tech = selected_techs[best_idx_single]
            best_arch = "单Die"
        else:
            best_tech = selected_techs[best_idx_multi]
            best_arch = "多Die"
        self.result_label.config(text=f"推荐最优方案：{best_tech} 下的 {best_arch} 架构，成本 ${best_cost:,.0f}")

        # 标注最优柱
        for i, tech in enumerate(selected_techs):
            if single_vals[i] == best_cost and best_cost>0:
                self.ax.text(x[i] - width/2, single_vals[i], '★最优', ha='center', va='bottom', fontsize=8, color='red')
            if multi_vals[i] == best_cost and best_cost>0:
                self.ax.text(x[i] + width/2, multi_vals[i], '★最优', ha='center', va='bottom', fontsize=8, color='red')
        self.canvas.draw()

    def export_report(self):
        result = self.compute_costs()
        if result is None:
            return
        selected_techs, single_costs, multi_costs = result
        if not selected_techs:
            return
        file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV文件","*.csv")])
        if not file_path:
            return
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["参数", "值"])
            writer.writerow(["功能规模模式", self.input_mode.get()])
            if self.input_mode.get() == "functional":
                writer.writerow(["等效28nm面积 (mm²)", self.functional_area.get()])
            else:
                writer.writerow(["晶体管数量 (亿)", self.transistor_budget.get()])
            writer.writerow(["DRAM类型", self.dram_tech.get()])
            writer.writerow(["DRAM容量 (GB)", self.dram_capacity.get()])
            writer.writerow(["封装类型", self.package.get()])
            writer.writerow(["年产量 (颗)", self.volume.get()])
            writer.writerow(["逻辑Die拆分数", self.logic_dies.get()])
            writer.writerow(["DRAM Die拆分数", self.dram_dies.get()])
            writer.writerow(["后端成本乘数", f"{self.get_backend_extra():.2f}"])
            writer.writerow([])
            writer.writerow(["逻辑工艺", "单Die成本(USD)", "多Die成本(USD)"])
            for tech in selected_techs:
                writer.writerow([tech, f"{single_costs[tech]:.2f}", f"{multi_costs[tech]:.2f}"])
        messagebox.showinfo("导出成功", f"报告已保存至 {file_path}")

def main():
    root = tk.Tk()
    app = FunctionFirstPlatform(root)
    root.mainloop()

if __name__ == "__main__":
    main()
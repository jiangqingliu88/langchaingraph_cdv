"""参考模型库（SQL）—— TLM 1.0 事务级组件的注册 / 版本 / 选择 / 桥到装配单。

替掉的是老的 `model_library/<name>/v1/{manifest.json, model.sv}` + `INDEX.yaml`：
那种形状里"有哪些模型"要翻目录、"哪一版是当前"靠文件夹名、"验证过没有"写在
manifest 里（第二个真相源）。这里全部落到 SQL 的三列上。
"""
from __future__ import annotations

import pytest

from src.knowledge_plane.model_registry import (
    KIND_TLM10, STATUS_VERIFIED, ModelRegistry,
)


def _reg(tmp_path) -> ModelRegistry:
    return ModelRegistry(tmp_path / "model_registry.db")


def _apb(reg: ModelRegistry, body: str = "  // 写 regs[paddr]，读回"):
    return reg.register("apb_slave", protocol="apb",
                        trans_in="apb_master_seq_item",
                        trans_out="apb_master_seq_item",
                        semantics="写 regs[paddr]=pwdata；读 prdata=regs[paddr]",
                        body=body)


def test_a_model_must_declare_its_two_tlm_ports(tmp_path):
    """TLM 1.0 组件必须写清**进什么事务、出什么事务** —— 生成器靠这两列选它。

    没写就登记不了：一条不知道进出什么的"模型"，接进 env 也无从接线。
    """
    reg = _reg(tmp_path)
    with pytest.raises(ValueError, match="trans_in"):
        reg.register("apb_slave", trans_out="apb_master_seq_item")
    # 信号级那套（clk/rst_n/paddr 引脚）不是合法 kind
    with pytest.raises(ValueError, match="kind"):
        reg.register("apb_slave_golden", kind="rtl_module",
                     trans_in="a", trans_out="b")


def test_only_verified_models_are_selectable(tmp_path):
    """**只挑 `verified`。**

    这是 `_ref_mirror_gate` 那条教训的落实：拿没根据的东西当 expected，等于自己
    造一批假失败。`draft` 不是不能用，是**不该被自动选中**。
    """
    reg = _reg(tmp_path)
    _apb(reg)
    assert reg.select(trans_in="apb_master_seq_item") is None     # draft
    reg.set_status("apb_slave", STATUS_VERIFIED,
                   evidence={"case": "test_apb_uart_case_basic"})
    m = reg.select(trans_in="apb_master_seq_item", protocol="apb")
    assert m["name"] == "apb_slave" and m["status"] == STATUS_VERIFIED


def test_versions_are_rows_not_folders(tmp_path):
    """升版本 = 新行，**旧版原样留着**。

    老形状的"黄金模型不可变，新增行为只能升版本"靠 `v1/` 目录名落实；现在靠
    `(name, version)` 主键。改语义就是新版本，历史可回查、可回滚。
    """
    reg = _reg(tmp_path)
    _apb(reg, body="  // v1")
    _apb(reg, body="  // v2")
    assert reg.latest_version("apb_slave") == 2
    assert reg.get("apb_slave", 1)["body"] == "  // v1"      # 旧版没被覆盖
    assert len(reg.all()) == 1                               # 一个 name 一行（最新版）


def test_selection_prefers_a_protocol_specific_model(tmp_path):
    """泛化的（`protocol=''`）能兜底，**具体的优先** —— 有专门的就用专门的。"""
    reg = _reg(tmp_path)
    reg.register("generic_mirror", trans_in="apb_master_seq_item",
                 trans_out="apb_master_seq_item", semantics="通用寄存器镜像")
    _apb(reg)
    for n in ("generic_mirror", "apb_slave"):
        reg.set_status(n, STATUS_VERIFIED)
    assert reg.select(trans_in="apb_master_seq_item")["name"] == "apb_slave"
    # 没有具体的那条时，泛化的兜底
    reg.set_status("apb_slave", "deprecated")
    assert reg.select(trans_in="apb_master_seq_item")["name"] == "generic_mirror"


def test_only_the_dut_level_model_is_seeded(tmp_path):
    """库里只放 **DUT 级**的事务模型 —— 子模块**不建模**。

    `uart_tx` / `uart_rx` / `fifo16` / `irq_gen` 是 DUT 的内部件，没有自己的事务
    接口；把它们当参考模型，等于把"实现"当"规格"，而且会诱使下一轮再建一批信号级
    的东西回来。
    """
    from src.knowledge_plane import model_seed

    reg = _reg(tmp_path)
    # 种的是 **DUT 级**的 `apb_uart`（不是通用协议件 `apb_slave`）——
    # 建模建的是这个 DUT，`apb_slave` 那种"写什么读什么"的通用镜像对 UART
    # 行为零断言。种子改名之后这条断言没跟上（实测踩过）。
    assert model_seed.seed(reg) == 1
    assert model_seed.seed(reg) == 0                    # 幂等
    assert [m["name"] for m in reg.all()] == ["apb_uart"]
    assert reg.get("apb_slave") is None, "通用协议件不是 DUT 级模型，不该在库里"
    for retired in model_seed.RETIRED_SUBMODULE_MODELS:
        assert reg.get(retired) is None, f"{retired} 是子模块，不该在库里"
    # 落 `draft` —— **老 manifest 那句"已验证"验的是信号级模型**，
    # 这个事务级 body 一次都没跑过，不该一进来就是 verified。
    assert reg.all()[0]["status"] == "draft"
    assert reg.select(trans_in="apb_master_seq_item") is None


def test_seeded_models_declare_transaction_level_semantics(tmp_path):
    """种下去的必须是**事务级**：body 里不许出现 clk / 引脚。

    老形状是 `module xxx_golden (input logic clk, rst_n, paddr, ...)` +
    `always_ff @(posedge clk)` —— 那是信号级 RTL，不是参考模型。
    """
    from src.knowledge_plane import model_seed

    reg = _reg(tmp_path)
    model_seed.seed(reg)
    for m in reg.all():
        assert m["kind"] == KIND_TLM10
        assert m["trans_in"].endswith("_seq_item")      # 进出都是事务
        assert m["trans_out"].endswith("_seq_item")
        for banned in ("posedge", "clk", "rst_n", "always_ff"):
            assert banned not in m["body"], f"{m['name']} 的 body 里还有 {banned}"


def test_bridging_to_the_yaml_assembly_sheet(tmp_path):
    """**SQL 是库，yaml 是装配单** —— 缺了这道桥，库里存的东西就只是个文档。

    产出的形状必须能被 `tool_uvm/examples/apb/apb_util_comp.yaml` 那套直接吃：
    `analysis_exports` / `analysis_ports` → `util_comp.sv.j2` 渲染成
    `uvm_analysis_imp_<name>` + `uvm_analysis_port`。
    """
    reg = _reg(tmp_path)
    _apb(reg)
    uc = reg.to_util_component("apb_slave")
    assert uc["type"] == KIND_TLM10
    assert uc["analysis_exports"] == [{"name": "in_export",
                                       "type": "apb_master_seq_item"}]
    assert uc["analysis_ports"] == [{"name": "out_port",
                                     "type": "apb_master_seq_item"}]
    assert uc["source_version"] == "apb_slave/v1"
    assert reg.to_util_component("不存在的模型") is None

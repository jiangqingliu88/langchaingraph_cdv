"""YAML input discovery and parsing for the UVM generator.

This module converts YAML documents into generator data models. It does not
render templates or write generated artifacts.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from ..models import (
    AgentCollection,
    AgentModel,
    BenchAgentEntry,
    BenchModel,
    ConstraintModel,
    EnvironmentModel,
    HarnessModel,
    ScPredModel,
    ScPredPoint,
)
from .environment_specs import (
    _normalize_agents_list,
    _normalize_analysis_components,
    _normalize_analysis_ports,
    _normalize_batches,
    _normalize_harness,
    _normalize_register_model,
    _normalize_scoreboards,
    _normalize_subenvs,
    _normalize_tests,
    _normalize_typedefs,
    _normalize_vipenvs,
    _opt_bool,
    _with_system_type_name,
)


class YAMLLoader:
    SUPPORTED_SUFFIXES = {".yml", ".yaml"}
    LISTFILE_SUFFIXES = {".f"}   # 清单文件：一行一个 YAML 路径

    @staticmethod
    def _expand_listfile(path: Path) -> List[Path]:
        """把 .f 清单文件展开成路径列表。

        一行一个路径；`#` 或 `//` 起注释；空行跳过；`+incdir+`、`-f` 之类
        编译选项行忽略（直接从 vlog filelist 搬过来也不会报错）。
        相对路径先按当前工作目录解析，找不到再相对清单文件所在目录解析。
        """
        out: List[Path] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].split("//", 1)[0].strip()
            if not line or line.startswith(("+", "-")):
                continue
            p = Path(line)
            if not p.is_absolute() and not p.exists():
                p = path.parent / line
            out.append(p)
        return out

    @staticmethod
    def collect_paths(inputs: Iterable[Path]) -> List[Path]:
        files: List[Path] = []
        seen: set = set()
        for input_path in inputs:
            # .f 清单文件：展开后当作新的输入（也允许里面写目录）
            if input_path.is_file() and input_path.suffix.lower() in YAMLLoader.LISTFILE_SUFFIXES:
                expanded = YAMLLoader.collect_paths(YAMLLoader._expand_listfile(input_path))
                for p in expanded:
                    if p not in seen:
                        seen.add(p)
                        files.append(p)
                continue
            if input_path.is_dir():
                for path in sorted(input_path.rglob("*")):
                    if path.suffix.lower() in YAMLLoader.SUPPORTED_SUFFIXES and path.is_file():
                        if path not in seen:
                            seen.add(path)
                            files.append(path)
            elif input_path.is_file() and input_path.suffix.lower() in YAMLLoader.SUPPORTED_SUFFIXES:
                if input_path not in seen:
                    seen.add(input_path)
                    files.append(input_path)
        return files

    @staticmethod
    def parse_agent_model(data: Dict[str, Any]) -> Optional[AgentModel]:
        if not isinstance(data, dict):
            return None
        name = data.get("name") or data.get("agent_name")
        if not name:
            return None

        return AgentModel(
            name=name,
            agent_name=name,
            interface=data.get("interface", ""),
            interface_name=data.get("interface_name", data.get("interface", "")),
            clock=data.get("clock") or data.get("clk"),
            reset=data.get("reset"),
            protocol=data.get("protocol", ""),
            reset_active_low=_opt_bool(data.get("reset_active_low", True)) is not False,
            parameters=data.get("parameters", []),
            typedefs=_normalize_typedefs(data.get("typedefs")),
            ports=data.get("ports", []),
            base_transaction_vars=data.get("base_transaction_vars", []),
            base_transaction_constraints=data.get("base_transaction_constraints", []),
            transaction_vars=data.get("transaction_vars", []),
            transaction_constraints=data.get("transaction_constraints", []),
            config_vars=data.get("config_vars", []),
            config_constraints=data.get("config_constraints", []),
            response_info=data.get("response_info", {}),
            config=dict(data.get("config") or {}),
        )

    @staticmethod
    def parse_environment_model(data: Dict[str, Any]) -> EnvironmentModel:
        name = data.get("name")
        env_name = name      # env_name 已从 YAML 下线：生成前缀一律取 name
        agents = AgentCollection()
        for agent_config in _normalize_agents_list(data.get("agents")):
            agent_name = agent_config.get("name") or agent_config.get("agent_name")
            if not agent_name:
                continue
            agent = AgentModel(
                name=agent_name,
                agent_name=agent_name,
                interface=agent_config.get("interface", agent_name),
                interface_name=agent_config.get("interface", agent_name),
                clock=agent_config.get("clock"),
                reset=agent_config.get("reset"),
                agent_type=agent_config.get("type", ""),
                is_master=_opt_bool(agent_config.get("is_master")),
                active=_opt_bool(agent_config.get("is_active")),
            )
            agents.append(agent)

        clk_rst_vip = data.get("clk_rst_vip") or {}
        if not clk_rst_vip and data.get("clk_rst"):
            clk_rst_vip = {
                "enabled": True,
                "clocks": data["clk_rst"].get("clocks", []),
                "resets": data["clk_rst"].get("resets", []),
            }

        agent_names = [a.name for a in agents]
        register_model = _normalize_register_model(
            data.get("register_model") or data.get("reg_adapter"), list(agents))
        return EnvironmentModel(
            name=name,
            env_name=env_name,
            agents=agents,
            subenvs=_normalize_subenvs(data.get("subenvs", [])),
            vipenvs=_normalize_vipenvs(data.get("vipenvs", [])),
            scoreboards=_normalize_scoreboards(data.get("scoreboards", [])),
            analysis_components=_normalize_analysis_components(data.get("analysis_components", [])),
            analysis_exports=_normalize_analysis_ports(data.get("analysis_exports", [])),
            analysis_ports=_normalize_analysis_ports(data.get("analysis_ports", [])),
            clk_rst_vip=clk_rst_vip,
            register_model=register_model,
            harness_connect=dict(data.get("harness_connect") or {}),
            coverage_crosses=[
                [str(f) for f in c] for c in (data.get("coverage_crosses") or [])
                if isinstance(c, (list, tuple)) and len(c) >= 2],
            config_vars=data.get("config_vars", []),
            config_constraints=data.get("config_constraints", []),
            tlm_connections=data.get("tlm_connections", []),
            bench=data.get("bench", {}),
            # util_components 与 environment 在**同一份文档**里，所以这里读得到
            utils=[{"name": u.get("name")} for u in (data.get("util_components") or [])
                   if isinstance(u, dict) and u.get("name")],
            tests=_normalize_tests(data.get("tests", [])),
            batches=_normalize_batches(data.get("batches", [])),
        )

    @staticmethod
    def parse_bench_model(data: Dict[str, Any]) -> BenchModel:
        agents: Dict[str, BenchAgentEntry] = {}
        for agent_config in _normalize_agents_list(data.get("agents")):
            name = agent_config.get("name")
            if not name:
                continue
            agents[name] = BenchAgentEntry(
                name=name,
                interface=agent_config.get("interface", ""),
                clock=agent_config.get("clock", "clk"),
                reset=agent_config.get("reset", "rst_n"),
                instance=agent_config.get("instance", ""),
                config_db_path=agent_config.get("config_db_path", ""),
                connections=agent_config.get("connections", []),
                agent_type=agent_config.get("type", ""),
            )
        return BenchModel(
            name=data.get("name") or data.get("bench_name", "bench"),
            # env_name 已从 YAML 下线：由 run() 按已解析的 environment 回填
            env_name="",
            timeout=data.get("timeout", "10ms"),
            include_assertions=data.get("include_assertions", False),
            # 时钟复位：新名 clk_rst_if 优先，兼容旧名 clk_rst
            clk_rst=data.get("clk_rst_if") or data.get("clk_rst") or {},
            wire_decls=data.get("wire_decls", []),
            assignments=data.get("assignments", []),
            agents=agents,
            harness=dict(data.get("harness") or {}),
            dut_instance=data.get("dut_instance", "u_dut"),
            dut_module=data.get("dut_module", ""),
            # 接口实例清单（替代 harness）。只收形状完整的项 —— 缺 name/type_name
            # 的条目渲染不出东西，留着只会在 tb_top 里变成一行空声明。
            interfaces=[_with_system_type_name(i)
                        for i in (data.get("interfaces") or [])
                        if isinstance(i, dict) and i.get("name") and i.get("type_name")],
            dut_filelist=list(data.get("dut_filelist") or []),
            ral_filelist=list(data.get("ral_filelist") or []),
            uvm_config=data.get("uvm_config", {}),
            wave_dump=data.get("wave_dump", {}),
            simulation=data.get("simulation", {}),
        )

    @staticmethod
    def parse_sc_pred_model(data: Dict[str, Any]) -> Optional[ScPredModel]:
        """解析 sc_pred 配置为 ScPredModel。

        配置格式：
          sc_pred:
            name: "apb"
            id: "0"
            prod_points:
              - { point_name: "cmd_cfg", width: 512, channel_num: 1, ports: [...] }
            chck_points:
              - { point_name: "rd0_align", width: 512, channel_num: 1, ports: [...] }
        """
        if not isinstance(data, dict):
            return None

        sc_pred = data.get("sc_pred") or data.get("rtl_sc_components")
        if not sc_pred:
            return None

        # 解析 prod_points
        prod_points = []
        for pt in sc_pred.get("prod_points", []):
            if not isinstance(pt, dict) or not pt.get("point_name"):
                continue
            prod_points.append(ScPredPoint(
                point_name=pt["point_name"],
                width=pt.get("width", 32),
                channel_num=pt.get("channel_num", 1),
                ports=pt.get("ports", []),
            ))

        # 解析 chck_points
        chck_points = []
        for pt in sc_pred.get("chck_points", []):
            if not isinstance(pt, dict) or not pt.get("point_name"):
                continue
            chck_points.append(ScPredPoint(
                point_name=pt["point_name"],
                width=pt.get("width", 32),
                channel_num=pt.get("channel_num", 1),
                ports=pt.get("ports", []),
            ))

        return ScPredModel(
            name=sc_pred.get("name", "sc_pred"),
            id=str(sc_pred.get("id", "0")),
            prod_points=prod_points,
            chck_points=chck_points,
        )

    @staticmethod
    def parse_constraint_model(data: Dict[str, Any]) -> ConstraintModel:
        project = data.get("constraint") or {}
        name = project.get("name") or project.get("constraint_name") or "constraint"
        env_name = project.get("env") or ""      # env_name 已下线，改用 env
        return ConstraintModel(
            name=name,
            env_name=env_name,
            transactions=data.get("transactions", []),
            policies=data.get("policies", []),
            combinator=data.get(
                "combinator",
                {
                    "default_mode": "APPLY_ALL",
                    "modes": [
                        "APPLY_ALL",
                        "APPLY_WEIGHTED",
                        "APPLY_FIRST_MATCH",
                        "APPLY_SEQUENTIAL",
                        "APPLY_CHAIN",
                    ],
                },
            ),
        )

    @staticmethod
    def parse_documents(paths: Iterable[Path]) -> Dict[str, Any]:
        interfaces = AgentCollection()
        environments: List[EnvironmentModel] = []
        benches: List[BenchModel] = []
        constraints: List[ConstraintModel] = []
        harnesses: List[HarnessModel] = []
        utils: List[Dict[str, Any]] = []
        meta: Dict[str, str] = {}

        for path in paths:
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)

            if not isinstance(data, dict):
                continue

            # 顶层 meta: 文件头元数据（后读的文件覆盖同名键）
            if isinstance(data.get("meta"), dict):
                for k, v in data["meta"].items():
                    if v not in (None, ""):
                        meta[k] = str(v)

            if "util_components" in data:
                payload = data["util_components"]
                if isinstance(payload, list):
                    utils.extend(payload)
                elif isinstance(payload, dict):
                    utils.append(payload)

            if "interfaces" in data:
                payload = data["interfaces"]
                if isinstance(payload, list):
                    for item in payload:
                        agent = YAMLLoader.parse_agent_model(item)
                        if agent:
                            interfaces.append(agent)
                elif isinstance(payload, dict):
                    agent = YAMLLoader.parse_agent_model(payload)
                    if agent:
                        interfaces.append(agent)

            if "interface" in data:
                payload = data["interface"]
                if isinstance(payload, list):
                    for item in payload:
                        agent = YAMLLoader.parse_agent_model(item)
                        if agent:
                            interfaces.append(agent)
                elif isinstance(payload, dict):
                    agent = YAMLLoader.parse_agent_model(payload)
                    if agent:
                        interfaces.append(agent)

            if "environment" in data:
                payload = data["environment"]
                if isinstance(payload, dict):
                    environments.append(YAMLLoader.parse_environment_model(payload))

            if "bench" in data:
                payload = data["bench"]
                if isinstance(payload, dict):
                    bmodel = YAMLLoader.parse_bench_model(payload)
                    # DUT / RAL 清单在 YAML 里是**相对该 YAML 的路径**（习惯写法，
                    # 如 `../apb_slave_dut.sv`），而 Makefile 是在**生成目录**里跑的
                    # —— 原样渲染就会 "Failed to open design unit file
                    # ../apb_slave_dut.sv"。这里就地解析成绝对路径，生成目录放哪都能编。
                    base = path.parent
                    for attr in ("dut_filelist", "ral_filelist"):
                        files = getattr(bmodel, attr) or []
                        if files:
                            setattr(bmodel, attr, [
                                f if os.path.isabs(f)
                                else str((base / f).resolve()).replace("\\", "/")
                                for f in files])
                    benches.append(bmodel)

            if "constraint" in data:
                constraints.append(YAMLLoader.parse_constraint_model(data))

            if "harness" in data:
                payload = data["harness"]
                if isinstance(payload, list):
                    for item in payload:
                        h = _normalize_harness(item)
                        if h:
                            harnesses.append(h)
                elif isinstance(payload, dict):
                    h = _normalize_harness(payload)
                    if h:
                        harnesses.append(h)

            if "bench" in data and isinstance(data["bench"], dict):
                bh = data["bench"].get("harness")
                if isinstance(bh, dict):
                    h = _normalize_harness(bh)
                    if h:
                        harnesses.append(h)

        # 后处理：env agents 的 transaction_vars 从同名 interface 文档补齐
        # （校验层 coverage_cross 规则与 env_cov 渲染都需要；匹配:
        #  精确 → 忽略大小写 → 前缀包含，如 apb_master ↔ APB）
        _ifaces_lower = {a.interface_name.lower(): a for a in interfaces
                         if a.interface_name}
        _ifaces_name = {a.name.lower(): a for a in interfaces}
        for env in environments:
            for eagent in env.agents:
                if getattr(eagent, "transaction_vars", None):
                    continue
                key = getattr(eagent, "interface", "") or eagent.name
                ref = (_ifaces_name.get(key.lower())
                       or _ifaces_lower.get(key.lower()))
                if ref is None:   # 前缀匹配（apb_master → apb）
                    for lower, agent in _ifaces_name.items():
                        if lower and (key.lower().startswith(lower)
                                      or lower.startswith(key.lower())):
                            ref = agent
                            break
                if ref is not None:
                    eagent.transaction_vars = list(ref.transaction_vars)
                    # 单类 port_config：env 级 config 类型指向 interface 级单类
                    eagent._config_type_override = f"{ref.name}_port_config"

        return {
            "interfaces": interfaces,
            "environments": environments,
            "benches": benches,
            "constraints": constraints,
            "harnesses": harnesses,
            "utils": utils,
            "sc_preds": [pred for pred in [YAMLLoader.parse_sc_pred_model(data) for data in [data]] if pred is not None],

            "meta": meta,
        }

"""生成编排 —— 把解析结果装配成渲染任务（`UVMGenerator` / `generate_uvm`）。

从 `tool_uvm/gen_uvm.py` 原样搬入；调用方直接从这里导入（门面已删）。
本模块不做渲染（见 `tasks.py`），也不解析 YAML（见 `parsing/`）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from ..constants import DEFAULT_META, TEMPLATES_DIR
from ..models import (
    AgentCollection, AgentModel, BenchAgentEntry, BenchModel, ConstraintModel,
    EnvironmentModel, HarnessModel, ScPredModel,
)
from ..parsing.environment_specs import (
    _normalize_agents_list, _normalize_analysis_components,
    _normalize_analysis_ports, _normalize_batches, _normalize_harness,
    _normalize_register_model, _normalize_scoreboards, _normalize_subenvs,
    _normalize_tests, _normalize_typedefs, _normalize_vipenvs, _opt_bool,
)
from ..parsing.yaml_loader import YAMLLoader
from ..render.jinja_renderer import JinjaRenderer
from ..render.region_injector import RegionInjector
from ..render.templates import (
    BENCH_TEMPLATES, ENVIRONMENT_ATTR_TEST_TEMPLATES, ENVIRONMENT_ROOT_TEMPLATES,
    ENVIRONMENT_SEQ_TEMPLATES, ENVIRONMENT_TEST_TEMPLATES,
    ENV_CONSTRAINT_TEMPLATES, HARNESS_TEMPLATES, INTERFACE_TEMPLATES,
    _split_template_entry,
)
from .tasks import RenderTaskFactory, _generate_output_readme, _rel_or_abs


def _semantic_validator():
    """延迟导入 `semantic_check`：它在 `tool_uvm` 包里。

    模块级导入会形成 generation → tool_uvm.__init__ → gen_uvm → generation 的环，
    所以放到调用点（`run()`）再取。
    """
    try:
        from ...tool_uvm.semantic_check import SemanticValidator
    except ImportError:  # 直接脚本执行（python gen_uvm.py）
        from semantic_check import SemanticValidator  # type: ignore[no-redef]
    return SemanticValidator


class UVMGenerator:
    def __init__(self, renderer: JinjaRenderer, output_root: Path,
                 injector: Optional[RegionInjector] = None,
                 overwrite: bool = False,
                 generate_names: Optional[List[str]] = None,
                 quiet: bool = False,
                 schema_check: bool = True,
                 source_root: Optional[Path] = None) -> None:
        self.renderer = renderer
        self.output_root = output_root
        #: 输入根（YAML / env_cov_bins）。VPlan 布局下 output_root 是暂存目录，
        #: 输入仍在 run 根；分开后才能既不写顶层 agents/、又读得到覆盖率模型。
        self.source_root = source_root or output_root
        self.injector = injector if injector is not None else RegionInjector()
        self.overwrite = overwrite
        self.generate_names = generate_names or []
        self.quiet = quiet
        self.schema_check = schema_check  # Phase 0: YAML schema 语法检查（--skip-schema-check 关闭）
        self.skipped = 0
        self.meta: Dict[str, str] = dict(DEFAULT_META)
        self.validation_issues: List[Any] = []
        self.schema_issues: List[Any] = []

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def _should_skip(self, target_path: Path) -> bool:
        if self.overwrite or self.injector.merge_source is not None:
            return False
        return target_path.exists()

    def _filter_named(self, items: Iterable[Any], *keys) -> List[Any]:
        if not self.generate_names:
            return list(items)
        result = []
        for item in items:
            for key in keys:
                value = item.get(key, "") if isinstance(item, dict) else getattr(item, key, "")
                if value in self.generate_names:
                    result.append(item)
                    break
        return result

    def generate_agents(self, agents: Iterable[AgentModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "agent", self.renderer, self.output_root, self.injector, self.overwrite,
            self.meta, source_dir=self.source_root)
        generated: List[Optional[Path]] = []
        for agent in agents:
            generated.extend(task.generate(agent))
        self.skipped += task.skipped
        return generated

    def generate_environments(self, environments: Iterable[EnvironmentModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "environment", self.renderer, self.output_root, self.injector,
            self.overwrite, self.meta, source_dir=self.source_root)
        generated: List[Optional[Path]] = []
        for environment in environments:
            generated.extend(task.generate(environment))
        self.skipped += task.skipped
        return generated

    def generate_constraints(self, constraints: Iterable[ConstraintModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "constraint", self.renderer, self.output_root, self.injector,
            self.overwrite, self.meta, source_dir=self.source_root)
        generated: List[Optional[Path]] = []
        for constraint in constraints:
            generated.extend(task.generate(constraint))
        self.skipped += task.skipped
        return generated

    def generate_benches(self, benches: Iterable[BenchModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "bench", self.renderer, self.output_root, self.injector,
            self.overwrite, self.meta, source_dir=self.source_root)
        generated: List[Optional[Path]] = []
        for bench in benches:
            generated.extend([task.generate(bench)])
        self.skipped += task.skipped
        return generated

    def generate_harnesses(self, harnesses: Iterable[HarnessModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "harness", self.renderer, self.output_root, self.injector,
            self.overwrite, self.meta, source_dir=self.source_root)
        generated: List[Optional[Path]] = []
        for harness in harnesses:
            result = task.generate(harness)
            if result is not None:
                generated.append(result)
        self.skipped += task.skipped
        return generated

    def generate_utils(self, utils: Iterable[Dict[str, Any]]) -> List[Path]:
        """生成工具组件（Predictor 等）"""
        generated: List[Path] = []
        util_dir = self.output_root / "env" / "utils"
        _util_templates = [
            ("environment_templates/util_comp.sv.j2", "{name}_util.sv"),
        ]
        for comp in utils:
            if not isinstance(comp, dict):
                continue
            name = comp.get("name", "util")
            ctx = {
                "name": name,
                "type": comp.get("type", "uvm_component"),
                "description": comp.get("description", ""),
                "analysis_exports": comp.get("analysis_exports", []),
                "analysis_ports": comp.get("analysis_ports", []),
                # 带这一项 → util 模板把 `process_<port>` 的 TODO 空壳换成**事务级**
                # 语义（TLM 1.0，无 clk、无引脚）。它由 SQL 模型库给出
                #（`ModelRegistry` 的 `body`，经 `_util_component_yaml` 落进
                # `util_components`）。**原先这里没转发** —— 于是模板里那个
                # `{% if body %}` 分支永远不会进，库里存的模型语义一路白存，
                # 渲染出来的还是空壳。模板分支在 `util_comp.sv.j2:111-120`。
                "body": comp.get("body"),
                # `auto_send: false` = body 自己写 out_port，模板不再把输入事务
                # 原样 send_output。**必须转发**：不转发的后果不是"少一次发送"，
                # 而是把 `in_*_seq_item` 塞进 `out_port`（类型不兼容）→ vlog 报
                # `Illegal assignment ... Types are not assignment compatible`。
                "auto_send": comp.get("auto_send"),
                # 带这一项 → util 模板把 `process_<port>` 的 TODO 空壳换成真的
                # 参考模型镜像（见模板与 schema 的 `refModelMirror`）。缺省 None
                # 保持原样 —— 不带镜像的 util 组件行为逐字节不变。
                "ref_model": comp.get("ref_model"),
            }
            for tpl_path, target_pattern in _util_templates:
                target_name = target_pattern.format(name=name)
                target_path = util_dir / target_name
                if self._should_skip(target_path):
                    self.skipped += 1
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    content = self.renderer.render(tpl_path, ctx)
                    target_path.write_text(content, encoding="utf-8")
                    generated.append(target_path)
                except Exception as e:
                    pass
        return generated

    def generate_scpreds(self, sc_preds: Iterable[ScPredModel]) -> List[Path]:
        """生成 Scoreboard Predictor（监控器 + 产生器 + 环境类）。

        生成目录结构：
          env/rtl_sc/
            ├── {name}_sc_pred_env.sv    # 环境包装类
            ├── {{point}}_mon_ex.sv      # 监控器模板（每个检查点）
            └── {{point}}_prod.sv        # 产生器模板（每个产生点）
          env/rtl_sc/interfaces/        # 接口文件
          env/rtl_sc/prods/             # 产生器组件
          env/rtl_sc/mon_ex/            # 监控器组件
        """
        generated: List[Path] = []

        # 创建所有需要的目录结构
        rtl_sc_dir = self.output_root / "env" / "rtl_sc"
        interfaces_dir = rtl_sc_dir / "interfaces"
        prods_dir = rtl_sc_dir / "prods"
        mon_ex_dir = rtl_sc_dir / "mon_ex"
        for dir_path in [rtl_sc_dir, interfaces_dir, prods_dir, mon_ex_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # 使用 tool_sc_red 的模板路径（相对路径）
        sc_pred_templates = [
            ("sc_pred_templates/sc_pred_env.sv.j2", "{name}_sc_pred_env.sv"),
            ("sc_pred_templates/mon_ex.sv.j2", "{point_name}_mon_ex.sv"),
            ("sc_pred_templates/prod.sv.j2", "{point_name}_prod.sv"),
            ("sc_pred_templates/prod_point_if.sv.j2", "{point_name}_prod_if.sv"),
            ("sc_pred_templates/prod_point_if.sv.j2", "{point_name}_mon_if.sv"),
        ]

        # 辅助函数：生成 prod 的打印字段
        def generate_prod_print_fields(point):
            fields = []
            for port in point.ports:
                if port['name'] not in ['clk', 'rst'] and port['dir'] == 'input':
                    if port['width'] > 1:
                        fields.append(f", {port['name']}=0x%0h")
                    else:
                        fields.append(f", {port['name']}=%0d")
            return ''.join(fields)

        # 辅助函数：生成 prod 的转换字段
        def generate_prod_convert_fields(point):
            fields = []
            for port in point.ports:
                if port['name'] not in ['clk', 'rst'] and port['dir'] == 'input':
                    field_name = port['name']
                    if port['width'] > 1:
                        fields.append(f", {field_name}=0x%0h")
                    else:
                        fields.append(f", {field_name}=%0d")
            return ''.join(fields)

        # 辅助函数：生成 monitor 的打印字段
        def generate_mon_print_fields(point):
            fields = []
            for port in point.ports:
                if port['name'] not in ['clk', 'rst'] and port['dir'] == 'output':
                    if port['width'] > 1:
                        fields.append(f", {port['name']}=0x%0h")
                    else:
                        fields.append(f", {port['name']}=%0d")
            return ''.join(fields)

        # 辅助函数：生成 monitor 的转换字段
        def generate_mon_convert_fields(point):
            fields = []
            for port in point.ports:
                if port['name'] not in ['clk', 'rst'] and port['dir'] == 'output':
                    field_name = port['name']
                    if port['width'] > 1:
                        fields.append(f", {field_name}=0x%0h")
                    else:
                        fields.append(f", {field_name}=%0d")
            return ''.join(fields)

        for sc_pred in sc_preds:
            # 生成环境包装类
            ctx = sc_pred.to_context()
            # 将 sc_pred 内容提升到顶层
            ctx_top = ctx["sc_pred"]
            ctx_top["name"] = sc_pred.name  # 确保顶层有 name

            env_tpl_path, env_target_pat = sc_pred_templates[0]
            env_target_path = rtl_sc_dir / env_target_pat.format(name=sc_pred.name)
            if not self._should_skip(env_target_path):
                print(f"DEBUG: 生成 sc_pred_env.sv: {env_target_path}")
                print(f"DEBUG: 模板路径: {env_tpl_path}")
                try:
                    content = self.renderer.render(env_tpl_path, ctx_top)
                    content, _ = self.injector.inject(
                        content, {},
                        f"env/rtl_sc/{env_target_path.name}", banner_prefix="// "
                    )
                    env_target_path.write_text(content, encoding="utf-8")
                    generated.append(env_target_path)
                    print(f"SUCCESS: 生成 {env_target_path}")
                except Exception as e:
                    print(f"ERROR: 生成 {env_target_path} 失败: {e}")

            # 生成接口和组件文件
            # 生成 prod_points 的接口和组件
            for point in sc_pred.prod_points:
                ctx_point = point.to_context()
                # 提升到顶层
                ctx_top = ctx_point
                ctx_top.update({"name": sc_pred.name, "point": point})

                # 生成 prod interface
                prod_tpl_path, prod_target_pat = sc_pred_templates[3]
                prod_target_path = interfaces_dir / prod_target_pat.format(point_name=point.point_name)
                if not self._should_skip(prod_target_path):
                    try:
                        # 为 prod interface 添加额外的上下文
                        prod_ctx = {**ctx_point, "print_fields": generate_prod_print_fields(point),
                                  "convert_fields": generate_prod_convert_fields(point)}
                        content = self.renderer.render(prod_tpl_path, prod_ctx)
                        prod_target_path.write_text(content, encoding="utf-8")
                        generated.append(prod_target_path)
                        print(f"SUCCESS: 生成 {prod_target_path}")
                    except Exception as e:
                        print(f"ERROR: 生成 {prod_target_path} 失败: {e}")

                # 生成 prod 组件
                prod_tpl_path, prod_target_pat = sc_pred_templates[2]
                prod_target_path = prods_dir / prod_target_pat.format(point_name=point.point_name)
                if not self._should_skip(prod_target_path):
                    try:
                        # 为 prod 组件添加额外的上下文
                        prod_ctx = {**ctx_point, "print_fields": generate_prod_print_fields(point),
                                  "convert_fields": generate_prod_convert_fields(point)}
                        content = self.renderer.render(prod_tpl_path, prod_ctx)
                        prod_target_path.write_text(content, encoding="utf-8")
                        generated.append(prod_target_path)
                        print(f"SUCCESS: 生成 {prod_target_path}")
                    except Exception as e:
                        print(f"ERROR: 生成 {prod_target_path} 失败: {e}")

            # 生成 chck_points 的接口和组件
            for point in sc_pred.chck_points:
                ctx_point = point.to_context()
                # 提升到顶层
                ctx_top = ctx_point
                ctx_top.update({"name": sc_pred.name, "point": point})

                # 生成 mon interface
                mon_tpl_path, mon_target_pat = sc_pred_templates[4]
                mon_target_path = interfaces_dir / mon_target_pat.format(point_name=point.point_name)
                if not self._should_skip(mon_target_path):
                    try:
                        # 为 mon interface 添加额外的上下文
                        mon_ctx = {**ctx_point, "print_fields": generate_mon_print_fields(point),
                                  "convert_fields": generate_mon_convert_fields(point)}
                        content = self.renderer.render(mon_tpl_path, mon_ctx)
                        mon_target_path.write_text(content, encoding="utf-8")
                        generated.append(mon_target_path)
                        print(f"SUCCESS: 生成 {mon_target_path}")
                    except Exception as e:
                        print(f"ERROR: 生成 {mon_target_path} 失败: {e}")

                # 生成 mon_ex 组件
                mon_tpl_path, mon_target_pat = sc_pred_templates[1]
                mon_target_path = mon_ex_dir / mon_target_pat.format(point_name=point.point_name)
                if not self._should_skip(mon_target_path):
                    try:
                        # 为 mon_ex 组件添加额外的上下文
                        mon_ctx = {**ctx_point, "print_fields": generate_mon_print_fields(point),
                                  "convert_fields": generate_mon_convert_fields(point)}
                        content = self.renderer.render(mon_tpl_path, mon_ctx)
                        mon_target_path.write_text(content, encoding="utf-8")
                        generated.append(mon_target_path)
                        print(f"SUCCESS: 生成 {mon_target_path}")
                    except Exception as e:
                        print(f"ERROR: 生成 {mon_target_path} 失败: {e}")

        return generated

    def _run_schema_check(self, yaml_files: Iterable[Path]) -> List[Any]:
        """Phase 0: 原始 YAML 层 schema 语法检查（jsonschema 缺失时跳过并提示）。"""
        try:
            from ...tool_uvm.schema_check import SchemaChecker  # 包内导入（python -m 路径）
        except ImportError:
            try:
                from schema_check import SchemaChecker
            except ImportError as exc:
                self._log(f"Warning: schema check skipped "
                          f"(jsonschema not available: {exc})")
                return []
        return SchemaChecker().check(yaml_files)

    def run(self, inputs: Iterable[Path]) -> List[Path]:
        yaml_files = YAMLLoader.collect_paths(inputs)
        if not yaml_files:
            raise SystemExit("No YAML files were found in the input paths.")

        # ── Phase 0: YAML schema 语法检查（原始 YAML 层，先于解析/语义校验；
        #    error 阻断生成，warning 落盘不阻断）──
        self.schema_issues = self._run_schema_check(yaml_files) if self.schema_check else []
        if self.schema_issues:
            report_path = self.output_root / "schema_report.txt"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                "Schema check report (tool_uvm)\n"
                + "\n".join(str(i) for i in self.schema_issues) + "\n",
                encoding="utf-8")
            for i in self.schema_issues:
                if i.severity == "warning":
                    self._log(f"Warning: {i}")
            schema_errors = [i for i in self.schema_issues if i.severity == "error"]
            if schema_errors:
                for i in schema_errors:
                    self._log(f"Error: {i}")
                raise SystemExit(
                    f"Schema validation failed: {len(schema_errors)} error(s), "
                    f"{len(self.schema_issues) - len(schema_errors)} warning(s) "
                    f"— see {report_path}")

        data = YAMLLoader.parse_documents(yaml_files)
        self.meta = {**DEFAULT_META, **data["meta"]}   # YAML meta 覆盖默认文件头元数据
        interfaces = data["interfaces"]
        environments = data["environments"]
        benches = data["benches"]
        constraints = data["constraints"]
        harnesses = data["harnesses"]
        utils = data["utils"]
        sc_preds = data["sc_preds"]

        # ── Phase A: 渲染前语义校验（error 阻断生成，warning 不阻断）──
        issues = _semantic_validator().validate(data)
        self.validation_issues = issues
        # **规则命中落库**：没有这一刻，规则库就只会越加越多 ——
        # "从来没命中的规则"和"真在干活的规则"在源码里长得一模一样，
        # 于是没人敢删、也没人知道该调哪条阈值（见 l4_memory/rule_stats.py）。
        # 旁路：统计失败不影响生成。
        try:
            from src.knowledge_plane.rule_stats import record_rule_hits

            _n = record_rule_hits(issues, run_id=Path(self.output_root).name)
            if _n:
                self._log(f"规则命中已记账：{_n} 条（{self.output_root}/.signoffai）")
        except Exception as _e:                        # noqa: BLE001
            self._log(f"规则命中记账失败（不影响生成）: {_e}")
        if issues:
            report_path = self.output_root / "validation_report.txt"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                "Semantic check report (tool_uvm)\n"
                + "\n".join(str(i) for i in issues) + "\n",
                encoding="utf-8")
            for i in issues:
                if i.severity == "warning":
                    self._log(f"Warning: {i}")
            errors = [i for i in issues if i.severity == "error"]
            if errors:
                for i in errors:
                    self._log(f"Error: {i}")
                raise SystemExit(
                    f"Semantic validation failed: {len(errors)} error(s), "
                    f"{len(issues) - len(errors)} warning(s) — see {report_path}")

        # ── -g/--generate 名称过滤 ──
        if self.generate_names:
            interfaces = self._filter_named(interfaces, "name")
            environments = self._filter_named(environments, "name")
            benches = self._filter_named(benches, "name")
            constraints = self._filter_named(constraints, "name")
            harnesses = self._filter_named(harnesses, "name")
            utils = self._filter_named(utils, "name")
            if not any((interfaces, environments, benches, constraints, harnesses, utils)):
                available = sorted(
                    [a.name for a in data["interfaces"]]
                    + [e.name for e in data["environments"]]
                    + [b.name for b in data["benches"]]
                    + [c.name for c in data["constraints"]]
                    + [h.name for h in data["harnesses"]]
                    + [u.get("name", "") for u in data["utils"] if isinstance(u, dict)])
                raise SystemExit(
                    f"No component named '{', '.join(self.generate_names)}' found. "
                    f"Available: {', '.join(available)}")

        if not any((interfaces, environments, benches, constraints, harnesses, utils)):
            raise SystemExit("No supported YAML definitions were found.")

        generated_files: List[Optional[Path]] = []
        if interfaces:
            generated_files.extend(self.generate_agents(interfaces))
        # ── 约束模型的 env 名回填**必须早于 env 渲染** ──
        #
        # 原来这段在 `generate_environments` 之后 —— 于是 env 渲染时谁也说不清
        # "这一轮有没有约束"，`env_pkg` 只能不 include `cons/*`（事实也是：
        # 那些文件从来没进过编译）。现在先回填、再给每个 env 打标记，env_pkg
        # 与 gen_test 才有条件把约束层接上。
        default_env = environments[0].env_name if environments else ""
        for _c in constraints:
            if not _c.env_name:
                _c.env_name = default_env
        for _env in environments:
            _env.has_constraints = any(c.env_name == _env.env_name for c in constraints)
        if environments:
            # 把**文档级**收集的 util_components 注入每个环境 —— 它们通常写在
            # 另一个 YAML 里（如 apb_util_comp.yaml），`parse_environment_model`
            # 看的是自己那份文档，拿不到。env_pkg 要靠它 `include` 那些裸 class
            #（predictor 等），否则 env / env_config 里 `apb_predictor apb_pred;`
            # 全是 "Invalid type"。
            for _env in environments:
                _env.utils = [{"name": u.get("name")} for u in utils
                              if isinstance(u, dict) and u.get("name")]
            generated_files.extend(self.generate_environments(environments))
        # env_name 已从 YAML 下线：bench 的 env 名从本次解析出的 environment
        # 回填（constraint 的回填已在上文、环境渲染之前完成）。
        if benches:
            for b in benches:
                if not b.env_name:
                    b.env_name = default_env
            generated_files.extend(self.generate_benches(benches))
        if constraints:
            generated_files.extend(self.generate_constraints(constraints))
        if harnesses:
            generated_files.extend(self.generate_harnesses(harnesses))
        if utils:
            generated_files.extend(self.generate_utils(utils))
        if sc_preds:
            generated_files.extend(self.generate_scpreds(sc_preds))

        # ── ③ 整环境编译 filelist + Makefile（闭环：env + bench + tc_pkg 一键编译入口）──
        if environments:
            generated_files.extend(
                self._generate_env_filelists(environments, benches, harnesses, interfaces))

        # ── Generate overall README.md at output root ──
        readme_path = self.output_root / "README.md"
        if not self._should_skip(readme_path):
            try:
                generated_files.append(_generate_output_readme(
                    self.output_root,
                    list(interfaces) if interfaces else [],
                    list(environments) if environments else [],
                    list(benches) if benches else [],
                    list(harnesses) if harnesses else [],
                    list(sc_preds) if sc_preds else [],
                ))
            except Exception:
                pass  # README is optional, don't fail generation
        else:
            self.skipped += 1

        return [p for p in generated_files if p is not None]

    def _generate_env_filelists(self, environments: Iterable[EnvironmentModel],
                                benches: Iterable[BenchModel],
                                harnesses: Iterable[HarnessModel],
                                interfaces: Iterable[Any]) -> List[Path]:
        """渲染 {env}_pkg_filelist.f + 整环境 Makefile（env + bench + tc_pkg 一键编译入口）。

        interface_agents：interface 级 agent（agents/{name}_agent 目录布局）——
        文件清单与 Makefile 的 agent 段都按实际生成目录引用，不再用 env 级 agent 名。
        """
        rendered: List[Path] = []
        base_pkg_dir = Path(TEMPLATES_DIR).resolve().parent / "base_pkg"
        iface_agents = [{"name": getattr(a, "name", "")}
                        for a in interfaces if getattr(a, "name", "")]
        # filelist 里一律用 $WORK_PATH 而不是生成时刻的绝对路径：
        # WORK_PATH 由 output_root/Sourceme（`setenv WORK_PATH \`pwd\``）定义，
        # 故整份 filelist 可随目录整体搬迁/换机器，不必重新生成。
        # 相对基准 = output_root（源码 Sourceme 时 pwd 即此处）。
        _base_rel = _rel_or_abs(base_pkg_dir, self.output_root)
        for env in environments:
            ctx = {"environment": env, **env.to_context()}
            ctx["file_name"] = f"{env.env_name}_pkg_filelist.f"
            ctx["work_path"] = "$WORK_PATH"
            ctx["base_pkg_dir"] = f"$WORK_PATH/{_base_rel}"
            ctx["agent_dir"] = "$WORK_PATH/agents"
            ctx["env_dir"] = "$WORK_PATH/env"
            ctx["bench_dir"] = "$WORK_PATH/bench"
            ctx["bench_name"] = benches[0].name if benches else "BENCH"
            ctx["harnesses"] = list(harnesses)
            ctx["dut_path"] = "// TODO: 填入 DUT 源码路径（替换本行）"
            ctx["interface_agents"] = iface_agents

            target = self.output_root / "env" / f"{env.env_name}_pkg_filelist.f"
            if not self._should_skip(target):
                target.parent.mkdir(parents=True, exist_ok=True)
                content = self.renderer.render(
                    "environment_templates/env_pkg_filelist.f.j2", ctx)
                target.write_text(content, encoding="utf-8")
                rendered.append(target)
            else:
                self.skipped += 1

            # Sourceme：定义 $WORK_PATH（filelist / Makefile 的路径基准）。
            # 与 filelist 一并生成——否则引用 $WORK_PATH 的 filelist 没人定义它。
            # 放在生成目录根：`source Sourceme` 后 pwd 即 output_root。
            src_target = self.output_root / "Sourceme"
            if not self._should_skip(src_target):
                src_target.parent.mkdir(parents=True, exist_ok=True)
                src_target.write_text(
                    self.renderer.render("bench_templates/Sourceme", dict(ctx)),
                    encoding="utf-8")
                rendered.append(src_target)
            else:
                self.skipped += 1

            # 整环境 Makefile（生成目录根；Questar/VCS 双后端）
            mk_target = self.output_root / "Makefile"
            if not self._should_skip(mk_target):
                mk_ctx = dict(ctx)
                # Makefile 要读 bench 自己的字段（`dut_filelist` / `ral_filelist`），
                # 而 mk_ctx 原来只带了 `bench_name` 这个名字 —— 那两个清单因此在
                # 模板里恒为 undefined，DUT/RAL 一句都进不了编译命令。
                mk_ctx["bench"] = benches[0] if benches else None
                mk_ctx["file_name"] = "Makefile"
                mk_ctx["base_pkg_rel"] = _rel_or_abs(
                    base_pkg_dir, self.output_root)
                content = self.renderer.render(
                    "bench_templates/bench_makefile.j2", mk_ctx)
                content, _ = self.injector.inject(
                    content, {}, "Makefile", banner_prefix="# ")
                mk_target.write_text(content, encoding="utf-8")
                rendered.append(mk_target)
            else:
                self.skipped += 1
        return rendered


SUPPORTED_TOOL_TYPES = ("agent", "env", "bench", "harness", "constraint", "util")


def generate_uvm(tool_type: str, yaml_spec: str) -> str:
    """
    参数化 UVM 代码生成器 —— 根据 tool_type 和 YAML 输入生成 SystemVerilog。

    参数:
        tool_type:  类型 —— "agent" | "env" | "bench" | "constraint" | "util"
        yaml_spec:  YAML 规格字符串

    返回:
        生成的文件列表与代码摘要
    """
    if tool_type not in SUPPORTED_TOOL_TYPES:
        return (
            f"// Error: unsupported tool_type '{tool_type}'. "
            f"Supported: {', '.join(SUPPORTED_TOOL_TYPES)}"
        )

    try:
        data = yaml.safe_load(yaml_spec)
    except yaml.YAMLError as e:
        return f"// Error parsing YAML: {e}"

    if not isinstance(data, dict):
        return "// Error: YAML must be a dictionary"

    renderer = JinjaRenderer(TEMPLATES_DIR)

    # ── Agent ──────────────────────────────────────────────
    if tool_type == "agent":
        payload = data.get("interfaces") or data.get("interface")
        if payload is None:
            return "// Error: YAML must contain 'interfaces' or 'interface' key"
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return "// Error: 'interfaces' must be a list or dict"

        results = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("agent_name")
            if not name:
                continue
            agent = AgentModel(
                name=name, agent_name=name,
                interface=item.get("interface", ""),
                interface_name=item.get("interface_name", item.get("interface", "")),
                clock=item.get("clock") or item.get("clk"),
                reset=item.get("reset"),
                protocol=item.get("protocol", ""),
                parameters=item.get("parameters", []),
                typedefs=_normalize_typedefs(item.get("typedefs")),
                ports=item.get("ports", []),
                transaction_vars=item.get("transaction_vars", []),
                transaction_constraints=item.get("transaction_constraints", []),
                config_vars=item.get("config_vars", []),
                config_constraints=item.get("config_constraints", []),
                response_info=item.get("response_info", {}),
                config=dict(item.get("config") or {}),
            )
            ctx = {"agent": agent, **agent.to_context()}
            files = []
            for entry in INTERFACE_TEMPLATES:
                tpl, pat, extra = _split_template_entry(entry)
                try:
                    c = renderer.render(tpl, {**ctx, **extra})
                    files.append(f"  {pat.format(agent_name=name)}: {len(c)} chars")
                except Exception as e:
                    files.append(f"  {pat.format(agent_name=name)}: ERR - {e}")
            results.append(f"Agent: {name}\n" + "\n".join(files))
        return "\n\n".join(results)

    # ── Environment ────────────────────────────────────────
    if tool_type == "env":
        payload = data.get("environment")
        if payload is None or not isinstance(payload, dict):
            return "// Error: YAML must contain 'environment' dict"
        name = payload.get("name") or "env"
        env_name = name      # env_name 已从 YAML 下线：生成前缀一律取 name
        agents = AgentCollection()
        for acfg in _normalize_agents_list(payload.get("agents")):
            aname = acfg.get("name") or acfg.get("agent_name")
            if not aname:
                continue
            agents.append(AgentModel(
                name=aname, agent_name=aname,
                interface=acfg.get("interface", aname),
                interface_name=acfg.get("interface", aname),
                clock=acfg.get("clock"), reset=acfg.get("reset"),
                agent_type=acfg.get("type", ""),
                is_master=_opt_bool(acfg.get("is_master")),
                active=_opt_bool(acfg.get("is_active")),
            ))
        clk_rst_vip = payload.get("clk_rst_vip") or {}
        if not clk_rst_vip and payload.get("clk_rst"):
            clk_rst_vip = {
                "enabled": True,
                "clocks": payload["clk_rst"].get("clocks", []),
                "resets": payload["clk_rst"].get("resets", []),
            }
        env = EnvironmentModel(
            name=name, env_name=env_name, agents=agents,
            subenvs=_normalize_subenvs(payload.get("subenvs", [])),
            vipenvs=_normalize_vipenvs(payload.get("vipenvs", [])),
            scoreboards=_normalize_scoreboards(payload.get("scoreboards", [])),
            analysis_components=_normalize_analysis_components(payload.get("analysis_components", [])),
            analysis_exports=_normalize_analysis_ports(payload.get("analysis_exports", [])),
            analysis_ports=_normalize_analysis_ports(payload.get("analysis_ports", [])),
            clk_rst_vip=clk_rst_vip,
            register_model=_normalize_register_model(
                payload.get("register_model") or payload.get("reg_adapter"),
                list(agents)),
            harness_connect=dict(payload.get("harness_connect") or {}),
            coverage_crosses=[
                [str(f) for f in c] for c in (payload.get("coverage_crosses") or [])
                if isinstance(c, (list, tuple)) and len(c) >= 2],
            config_vars=payload.get("config_vars", []),
            config_constraints=payload.get("config_constraints", []),
            tlm_connections=payload.get("tlm_connections", []),
            bench=payload.get("bench", {}),
            utils=[{"name": u.get("name")} for u in (payload.get("util_components") or [])
                   if isinstance(u, dict) and u.get("name")],
            tests=_normalize_tests(payload.get("tests", [])),
            batches=_normalize_batches(payload.get("batches", [])),
        )
        ctx = {"environment": env, **env.to_context()}
        files = []
        templates = list(ENVIRONMENT_ROOT_TEMPLATES + ENVIRONMENT_TEST_TEMPLATES
                         + ENVIRONMENT_SEQ_TEMPLATES)
        # 属性测试与上面那条路径同一条件 —— 两条都得管，否则 CLI 与这条
        # 字符串入口会给出不一样的产物
        if env.tests:
            templates += ENVIRONMENT_ATTR_TEST_TEMPLATES
        for tpl, pat in templates:
            try:
                c = renderer.render(tpl, ctx)
                files.append(f"  {pat.format(env_name=env_name)}: {len(c)} chars")
            except Exception as e:
                files.append(f"  {pat.format(env_name=env_name)}: ERR - {e}")
        return f"Environment: {env_name}\n" + "\n".join(files)

    # ── Harness ────────────────────────────────────────────
    if tool_type == "harness":
        payload = data.get("harness")
        if payload is None and isinstance(data.get("bench"), dict):
            payload = data["bench"].get("harness")
        if payload is None or not isinstance(payload, dict):
            return "// Error: YAML must contain 'harness' dict"
        harness = _normalize_harness(payload)
        if harness is None:
            return "// Error: harness YAML missing 'name'"
        ctx = {"harness": harness, **harness.to_context()}
        c = renderer.render(HARNESS_TEMPLATES[0][0], ctx)
        return f"Harness: {harness.name}\n  {harness.name}.sv: {len(c)} chars"

    # ── Bench ──────────────────────────────────────────────
    if tool_type == "bench":
        payload = data.get("bench")
        if payload is None or not isinstance(payload, dict):
            return "// Error: YAML must contain 'bench' dict"
        agents_b: dict = {}
        for acfg in _normalize_agents_list(payload.get("agents")):
            aname = acfg.get("name")
            if not aname:
                continue
            agents_b[aname] = BenchAgentEntry(
                name=aname,
                interface=acfg.get("interface", ""),
                clock=acfg.get("clock", "clk"),
                reset=acfg.get("reset", "rst_n"),
                instance=acfg.get("instance", ""),
                config_db_path=acfg.get("config_db_path", ""),
                connections=acfg.get("connections", []),
                agent_type=acfg.get("type", ""),
            )
        bench = BenchModel(
            name=payload.get("name") or payload.get("bench_name", "bench"),
            env_name="",     # env_name 已从 YAML 下线（下游按 environment 回填）
            timeout=payload.get("timeout", "10ms"),
            include_assertions=payload.get("include_assertions", False),
            clk_rst=payload.get("clk_rst_if") or payload.get("clk_rst") or {},
            wire_decls=payload.get("wire_decls", []),
            assignments=payload.get("assignments", []),
            agents=agents_b,
            harness=dict(payload.get("harness") or {}),
            dut_instance=payload.get("dut_instance", "u_dut"),
            uvm_config=payload.get("uvm_config", {}),
            wave_dump=payload.get("wave_dump", {}),
            simulation=payload.get("simulation", {}),
        )
        ctx = {"bench": bench.to_context()}
        tpl = BENCH_TEMPLATES[0][0]
        c = renderer.render(tpl, ctx)
        return f"Bench: {bench.name}\n  {bench.name}_tb_top.sv: {len(c)} chars"

    # ── Constraint ─────────────────────────────────────────
    if tool_type == "constraint":
        proj = data.get("constraint") or {}
        cname = proj.get("name") or proj.get("constraint_name") or "constraint"
        cenv = proj.get("env") or ""     # env_name 已下线，改用 env
        constraint = ConstraintModel(
            name=cname, env_name=cenv,
            transactions=data.get("transactions", []),
            policies=data.get("policies", []),
            combinator=data.get("combinator", {
                "default_mode": "APPLY_ALL",
                "modes": ["APPLY_ALL", "APPLY_WEIGHTED", "APPLY_FIRST_MATCH",
                          "APPLY_SEQUENTIAL", "APPLY_CHAIN"],
            }),
        )
        ctx = constraint.to_context()
        files = []
        for tpl, pat in ENV_CONSTRAINT_TEMPLATES:
            try:
                c = renderer.render(tpl, ctx)
                files.append(f"  {pat.format(project_name=cname, env_name=cenv)}: {len(c)} chars")
            except Exception as e:
                files.append(f"  {pat.format(project_name=cname, env_name=cenv)}: ERR - {e}")
        return f"Constraint: {cname}\n" + "\n".join(files)

    # ── Util ───────────────────────────────────────────────
    if tool_type == "util":
        components = data.get("util_components")
        if components is None or not isinstance(components, list):
            return "// Error: YAML must contain 'util_components' list"
        results = []
        _util_templates = [
            ("environment_templates/util_comp.sv.j2", "{name}_util.sv"),
        ]
        for comp in components:
            if not isinstance(comp, dict):
                continue
            uname = comp.get("name", "util")
            # 与 `generate_utils` 的 ctx **逐键对齐** —— 这是同两个模板的两个入口
            # （一个是真生成、一个是预览），少传一个键就会让预览的字符数与真产物对不上，
            # 而"预览说生成了、真产物是空壳"正是这一类 bug 最难查的形态。
            ctx = {
                "name": uname,
                "type": comp.get("type", "uvm_component"),
                "description": comp.get("description", ""),
                "analysis_exports": comp.get("analysis_exports", []),
                "analysis_ports": comp.get("analysis_ports", []),
                "body": comp.get("body"),
                "auto_send": comp.get("auto_send"),
                "ref_model": comp.get("ref_model"),
            }
            files = []
            for tpl, pat in _util_templates:
                try:
                    c = renderer.render(tpl, ctx)
                    files.append(f"  {pat.format(name=uname)}: {len(c)} chars")
                except Exception as e:
                    files.append(f"  {pat.format(name=uname)}: ERR - {e}")
            results.append(f"Util: {uname}\n" + "\n".join(files))
        return "\n\n".join(results)

    return f"// Error: unknown tool_type '{tool_type}'"

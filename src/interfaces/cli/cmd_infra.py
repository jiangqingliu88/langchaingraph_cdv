"""CLI 命令组：环境、hub、插件、流水线、文档（env / hub / plugin / pipeline / docs）。

从 `src/interfaces/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
共享 helper 仍从 `commands` 导入，别在这里再造一份。
"""
from __future__ import annotations

import asyncio  # noqa: F401
import json  # noqa: F401
from pathlib import Path  # noqa: F401

import click
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

from src.interfaces.cli.output import common_options, get_output_adapter  # noqa: F401
from src.interfaces.cli.commands import (  # noqa: F401
    cli, console,
)

@cli.group()
def env():
    """UVM 环境操作"""
    pass


@env.command("generate")
@click.option("--spec", "-s", "spec_file", type=click.Path(exists=True), required=True,
              help="规格文件")
@click.option("--output", "-o", default="output/uvm_env", help="输出目录")
def env_generate(spec_file, output):
    """生成 UVM 环境

    \b
    示例:
      vagent env generate --spec spec.md
    """
    from src.layers.l1_infrastructure.output_config import make_output_root
    output_dir = make_output_root(output) + "/uvm_env"
    console.print(f"[cyan]Generating UVM environment from {spec_file}...[/cyan]")
    console.print(f"[dim]Output: {output_dir}[/dim]")
    console.print("[yellow]Use 'vagent verify <spec> --step UVM' for full UVM environment generation.[/yellow]")


@env.command("validate")
@click.option("--dir", "-d", "env_dir", type=click.Path(exists=True), required=True,
              help="UVM 环境目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def env_validate(env_dir, json_output):
    """校验 UVM 环境

    \b
    示例:
      vagent env validate --dir output/agents
    """
    out = get_output_adapter(json_output)
    env_path = Path(env_dir)
    sv_files = list(env_path.rglob("*.sv"))
    pkg_files = list(env_path.rglob("*_pkg.sv"))
    issues = []

    if not sv_files:
        issues.append("No .sv files found")

    out.print_result({
        "directory": str(env_path),
        "sv_files": len(sv_files),
        "pkg_files": len(pkg_files),
        "issues": issues,
        "valid": len(issues) == 0,
    }, title=f"UVM Env Validation: {Path(env_dir).name}")


@env.command("compile")
@click.option("--dir", "-d", "env_dir", type=click.Path(exists=True), required=True,
              help="UVM 环境目录")
def env_compile(env_dir):
    """编译 UVM 环境

    \b
    示例:
      vagent env compile --dir output/agents
    """
    env_path = Path(env_dir)
    # 搜索 filelist.f（可能在 inputs/filelists/ 子目录下）
    filelists = list(env_path.glob("**/filelist.f"))
    if not filelists:
        console.print(f"[red]No filelist.f found in {env_dir}[/red]")
        return
    filelist = filelists[0]
    if len(filelists) > 1:
        console.print(f"[dim]Found {len(filelists)} filelists, using: {filelist}[/dim]")

    console.print(f"[cyan]Compiling with filelist: {filelist}[/cyan]")

    # 实际运行编译 —— 走公共实现（`_tools_old` 那份带 `compile_dir=`，
    # 而 RegressionRunner 没有这个参数，每次都是 TypeError；公共版是对的）
    from src.tools.common.lib.compile import run_compile_check
    from src.tools.common.lib.uvm_context import ctx as _uctx

    output_dir = env_path
    # 尝试从 env.yaml 读取配置
    env_yaml = output_dir / "inputs" / "yaml" / "uvm" / "env.yaml"
    env_name = "dut_env"
    agents = []
    if env_yaml.exists():
        try:
            import yaml as _yaml
            with open(env_yaml, encoding="utf-8") as f:
                env_data = _yaml.safe_load(f)
            env_info = env_data.get("environment", {}) if isinstance(env_data, dict) else {}
            env_name = env_info.get("name", "dut_env")
            ag_list = env_info.get("agents", {})
            agents = list(ag_list.keys()) if isinstance(ag_list, dict) else []
        except Exception:
            pass

    if not agents:
        # 从 agents 目录推断
        ag_dir = output_dir / "agents"
        if ag_dir.exists():
            agents = [d.name for d in ag_dir.iterdir() if d.is_dir() and (d / f"{d.name}_pkg.sv").exists()]

    # run_compile_check 期望 agents 是 [{"name": "xxx"}, ...] 格式
    agent_dicts = [{"name": a} for a in agents]
    _uctx.set(output_dir=str(output_dir), agents=agent_dicts, env_name=env_name)
    result = run_compile_check(output_dir, agent_dicts, env_name)
    console.print(f"[bold]Compile:[/bold] {'PASS' if result.get('passed') else 'FAIL'}")
    console.print(f"  Errors: {result.get('errors', '?')}  Warnings: {result.get('warnings', '?')}")


@env.command("template")
@click.option("--type", "-t", "component_type", required=True,
              type=click.Choice(["agent", "scoreboard", "monitor", "driver", "sequence"]),
              help="组件类型")
@click.option("--name", "-n", required=True, help="组件名称")
@click.option("--output", "-o", default=".", help="输出目录")
def env_template(component_type, name, output):
    """生成单个 UVM 组件模板

    \b
    示例:
      vagent env template --type agent --name uart_rx
      vagent env template --type monitor --name axi_monitor
    """
    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)

    templates = {
        "agent": (
            f"class {name}_agent extends uvm_agent;\n"
            f"  `uvm_component_utils({name}_agent)\n\n"
            f"  {name}_sequencer sqr;\n"
            f"  {name}_driver    drv;\n"
            f"  {name}_monitor   mon;\n\n"
            f"  function new(string name, uvm_component parent);\n"
            f"    super.new(name, parent);\n"
            f"  endfunction\n\n"
            f"  function void build_phase(uvm_phase phase);\n"
            f"    super.build_phase(phase);\n"
            f"    sqr = {name}_sequencer::type_id::create(\"sqr\", this);\n"
            f"    drv = {name}_driver::type_id::create(\"drv\", this);\n"
            f"    mon = {name}_monitor::type_id::create(\"mon\", this);\n"
            f"  endfunction\n\n"
            f"  function void connect_phase(uvm_phase phase);\n"
            f"    drv.seq_item_port.connect(sqr.seq_item_export);\n"
            f"  endfunction\n"
            f"endclass\n"
        ),
        "monitor": (
            f"class {name}_monitor extends uvm_monitor;\n"
            f"  `uvm_component_utils({name}_monitor)\n\n"
            f"  virtual {name}_if vif;\n\n"
            f"  function new(string name, uvm_component parent);\n"
            f"    super.new(name, parent);\n"
            f"  endfunction\n\n"
            f"  task run_phase(uvm_phase phase);\n"
            f"    forever begin\n"
            f"      @(posedge vif.clk);\n"
            f"      // Sample and write to analysis port\n"
            f"    end\n"
            f"  endtask\n"
            f"endclass\n"
        ),
    }

    content = templates.get(component_type, f"// {component_type} template: {name}\n")
    ext = ".sv" if component_type != "sequence" else ".sv"
    filename = f"{name}.sv"

    (out_dir / filename).write_text(content, encoding="utf-8")
    console.print(f"[green]Generated {component_type} template: {out_dir / filename}[/green]")


@cli.group()
def hub():
    """统一工具注册中心管理"""
    pass


@hub.command("status")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def hub_status(json_output):
    """ToolHub 状态概览

    \b
    示例:
      vagent hub status
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        stats = hub.get_stats()
        result = {
            "total_tools": hub.tool_count,
            "categories": hub.categories,
            "tags": hub.tags,
            "tool_stats": stats,
            "agent_tools": {role: hub.list_by_agent(role) for role in
                           ["uvm", "test", "regress"]},
        }
        out.print_result(result, title="ToolHub Status")
    except Exception as e:
        out.print_error(str(e))


@hub.command("list")
@click.option("--agent", "-a", help="按 Agent 过滤")
@click.option("--tag", help="按标签过滤")
@click.option("--category", "-c", help="按分类过滤")
@click.option("--risk", type=click.Choice(["safe", "write", "danger"]), help="按风险等级过滤")
@click.option("--search", help="全文搜索")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def hub_list(agent, tag, category, risk, search, json_output):
    """列出所有已注册工具

    \b
    示例:
      vagent hub list                              # 所有工具
      vagent hub list --agent verify_architect     # 某 Agent
      vagent hub list --tag simulation             # 某标签
      vagent hub list --search vcs                 # 全文搜索
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        if search:
            manifests = hub.search(search)
        elif agent:
            manifests = hub.list_by_agent(agent)
        elif tag:
            manifests = hub.list_by_tag(tag)
        elif category:
            manifests = hub.list_by_category(category)
        elif risk:
            from src.layers.l2_orchestration.communication.tool_protocol import ToolRisk
            manifests = hub.list_by_risk(ToolRisk(risk))
        else:
            manifests = hub.list_all()

        rows = []
        for m in manifests:
            risk_icon = {"safe": "🟢", "write": "🟡", "danger": "🔴"}.get(m.risk_level.value, "⚪")
            rows.append([m.name, m.version, risk_icon, m.category or "-",
                         ", ".join(m.tags[:3]) or "-", m.description[:60]])
        out.print_table(
            ["Name", "Version", "Risk", "Category", "Tags", "Description"],
            rows, title=f"Tools ({len(rows)} registered)"
        )
    except Exception as e:
        out.print_error(str(e))


@hub.command("health")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def hub_health(json_output):
    """检查所有工具健康状态

    \b
    示例:
      vagent hub health
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        result = asyncio.run(hub.health_check())
        out.print_result(result, title="ToolHub Health Check")
    except Exception as e:
        out.print_error(str(e))


@hub.command("bootstrap")
def hub_bootstrap():
    """重新发现并加载所有工具（插件 + CLI + 内置）

    \b
    示例:
      vagent hub bootstrap
    """
    try:
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        # Reset
        hub._initialized = False
        hub._tools.clear()
        hub._manifests.clear()
        count = hub.bootstrap()
        console.print(f"[green]ToolHub bootstrapped: {count} tools loaded[/green]")
        console.print(f"  Categories: {hub.categories}")
        console.print(f"  Tags: {hub.tags[:20]}")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@cli.group()
def plugin():
    """插件管理"""
    pass


@plugin.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def plugin_list(json_output):
    """列出已安装插件

    \b
    示例:
      vagent plugin list
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.plugin_manager import PluginManager
        mgr = PluginManager()
        discovered = mgr.discover()

        rows = []
        for tool, roles in discovered:
            m = tool.manifest
            rows.append([m.name, m.version, m.author or "-", m.category or "-",
                         ", ".join(m.tags[:3]), "✅" if tool.check_health() else "❌"])
        out.print_table(["Name", "Version", "Author", "Category", "Tags", "Health"],
                        rows, title=f"Plugins ({len(rows)} discovered)")

        if mgr.errors:
            console.print("\n[yellow]Plugin errors:[/yellow]")
            for e in mgr.errors:
                console.print(f"  [red]{e['path']}: {e['error'][:120]}[/red]")
    except Exception as e:
        out.print_error(str(e))


@plugin.command("discover")
@click.option("--dir", "-d", "plugin_dir", help="扫描目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def plugin_discover(plugin_dir, json_output):
    """扫描插件目录

    \b
    示例:
      vagent plugin discover
      vagent plugin discover --dir ~/my_plugins
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.plugin_manager import PluginManager
        mgr = PluginManager()
        if plugin_dir:
            mgr.add_plugin_dir(plugin_dir)
        discovered = mgr.discover()

        out.print_result({
            "tools_found": len(discovered),
            "tools": [{"name": t.manifest.name, "version": t.manifest.version,
                       "category": t.manifest.category,
                       "tags": t.manifest.tags} for t, _ in discovered],
            "errors": mgr.errors,
            "plugin_dirs": mgr.plugin_dirs,
        }, title="Plugin Discovery")
    except Exception as e:
        out.print_error(str(e))


@plugin.command("install")
@click.argument("name")
@click.option("--version", "-v", help="版本")
@click.option("--upgrade", "-U", is_flag=True, help="升级")
def plugin_install(name, version, upgrade):
    """安装插件（从市场或本地）

    \b
    示例:
      vagent plugin install vcs_compile
      vagent plugin install vcs_compile --version 2.0.0
    """
    try:
        from src.layers.l2_orchestration.tool_marketplace import ToolMarketplace
        market = ToolMarketplace()
        success, msg = asyncio.run(market.install(name, version, upgrade))
        if success:
            console.print(f"[green]✓ {msg}[/green]")
        else:
            console.print(f"[red]✗ {msg}[/red]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@plugin.command("uninstall")
@click.argument("name")
def plugin_uninstall(name):
    """卸载插件

    \b
    示例:
      vagent plugin uninstall vcs_compile
    """
    try:
        from src.layers.l2_orchestration.tool_marketplace import ToolMarketplace
        market = ToolMarketplace()
        success, msg = market.uninstall(name)
        if success:
            console.print(f"[green]✓ {msg}[/green]")
        else:
            console.print(f"[red]✗ {msg}[/red]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@plugin.command("search")
@click.argument("query")
@click.option("--category", "-c", help="按分类过滤")
@click.option("--tag", help="按标签过滤")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def plugin_search(query, category, tag, json_output):
    """搜索工具市场

    \b
    示例:
      vagent plugin search vcs
      vagent plugin search compile --category simulation
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.tool_marketplace import ToolMarketplace
        market = ToolMarketplace()
        tags = [tag] if tag else None
        results = market.search(query, category=category, tags=tags)

        if json_output:
            click.echo(json.dumps([{
                "name": r.name, "version": r.version, "description": r.description,
                "author": r.author, "tags": r.tags, "category": r.category,
            } for r in results], indent=2, ensure_ascii=False))
        else:
            table = Table(title=f"Marketplace Search: '{query}'")
            table.add_column("Name", style="cyan")
            table.add_column("Version")
            table.add_column("Category")
            table.add_column("Description")
            for r in results[:20]:
                table.add_row(r.name, r.version, r.category or "-", r.description[:80])
            console.print(table)
    except Exception as e:
        out.print_error(str(e))


@cli.group()
def pipeline():
    """声明式工具编排"""
    pass


@pipeline.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def pipeline_list(json_output):
    """列出所有已注册流水线

    \b
    示例:
      vagent pipeline list
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.tool_orchestrator import ToolOrchestrator, BUILTIN_PIPELINES
        orch = ToolOrchestrator()

        # 注册内置流水线
        for name, pdef in BUILTIN_PIPELINES.items():
            orch.register_pipeline(pdef)

        rows = []
        for name, pdef in orch._pipelines.items():
            rows.append([name, pdef.version, pdef.description[:80],
                         str(len(pdef.steps)), ", ".join(s.id for s in pdef.steps[:5])])
        out.print_table(["Name", "Version", "Description", "Steps", "Step IDs"],
                        rows, title="Pipelines")
    except Exception as e:
        out.print_error(str(e))


@pipeline.command("run")
@click.argument("pipeline_name")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
@click.option("--dry-run", is_flag=True, help="只显示不执行")
def pipeline_run(pipeline_name, json_output, dry_run):
    """执行声明式工具流水线

    \b
    示例:
      vagent pipeline run uvm_quality_check
      vagent pipeline run code_generation --dry-run
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.tool_orchestrator import ToolOrchestrator, BUILTIN_PIPELINES
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        orch = ToolOrchestrator()
        for name, pdef in BUILTIN_PIPELINES.items():
            orch.register_pipeline(pdef)

        if dry_run:
            pipeline = orch._pipelines.get(pipeline_name)
            if not pipeline:
                out.print_error(f"Pipeline '{pipeline_name}' not found")
                return
            out.print_result({
                "name": pipeline.name,
                "steps": [{"id": s.id, "tool": s.tool, "depends_on": s.depends_on,
                           "condition": str(s.condition)} for s in pipeline.steps],
            }, title=f"Pipeline: {pipeline_name} (dry-run)")
            return

        def on_progress(step_id, status, msg):
            if not json_output:
                icon = {"running": "⏳", "passed": "✅", "failed": "❌"}.get(status, "·")
                console.print(f"  {icon} {step_id}: {msg}")

        result = asyncio.run(orch.run(pipeline_name, on_progress=on_progress))
        if json_output:
            click.echo(json.dumps({
                "pipeline": result.pipeline_name,
                "status": result.status.value,
                "passed": result.passed,
                "failed": result.failed,
                "skipped": result.skipped,
                "total_time_s": result.total_time_s,
                "steps": [{"id": s.step_id, "status": s.status.value, "elapsed_s": s.elapsed_s,
                           "error": s.error} for s in result.steps],
            }, indent=2, ensure_ascii=False))
        else:
            status_color = "green" if result.status.value == "passed" else "red"
            console.print(f"\n[bold {status_color}]Pipeline: {result.status.value}[/bold {status_color}]  "
                          f"({result.passed} passed, {result.failed} failed, "
                          f"{result.skipped} skipped, {result.total_time_s}s)")
    except Exception as e:
        out.print_error(str(e))


@pipeline.command("graph")
@click.argument("pipeline_name")
@click.option("--format", "-f", "fmt", default="mermaid",
              type=click.Choice(["mermaid", "dot"]), help="输出格式")
def pipeline_graph(pipeline_name, fmt):
    """生成流水线可视化图

    \b
    示例:
      vagent pipeline graph uvm_quality_check
      vagent pipeline graph uvm_quality_check --format dot
    """
    try:
        from src.layers.l2_orchestration.tool_orchestrator import ToolOrchestrator, BUILTIN_PIPELINES
        orch = ToolOrchestrator()
        for name, pdef in BUILTIN_PIPELINES.items():
            orch.register_pipeline(pdef)

        if fmt == "mermaid":
            click.echo(orch.to_mermaid(pipeline_name))
        else:
            click.echo(orch.to_dot(pipeline_name))
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@cli.group()
def docs():
    """文档自动生成"""
    pass


@docs.command("generate")
@click.option("--output", "-o", default="docs/tools", help="输出目录")
@click.option("--tool", help="只生成指定工具的文档")
def docs_generate(output, tool):
    """自动生成所有工具文档

    \b
    示例:
      vagent docs generate                     # 生成所有工具文档
      vagent docs generate --tool vcs_compile  # 只生成指定工具
      vagent docs generate -o docs/reference   # 指定输出目录
    """
    try:
        from src.layers.l2_orchestration.tool_doc_generator import ToolDocGenerator
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        gen = ToolDocGenerator(hub)

        if tool:
            manifest = hub.get_manifest(tool)
            if not manifest:
                console.print(f"[red]Tool '{tool}' not found[/red]")
                return
            md = gen.generate_tool_md(manifest)
            out_path = Path(output) / f"{tool}.md"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md, encoding="utf-8")
            console.print(f"[green]Generated: {out_path}[/green]")
        else:
            results = gen.generate_all(output)
            console.print(f"[green]Generated {len(results)} files in {output}/[/green]")
            for name, path in sorted(results.items()):
                console.print(f"  [dim]{name}[/dim] → {path}")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@docs.command("preview")
@click.argument("tool_name")
def docs_preview(tool_name):
    """预览工具文档（终端输出）

    \b
    示例:
      vagent docs preview check_compile
    """
    try:
        from src.layers.l2_orchestration.tool_doc_generator import ToolDocGenerator
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
        if not hub._initialized:
            hub.bootstrap()

        manifest = hub.get_manifest(tool_name)
        if not manifest:
            console.print(f"[red]Tool '{tool_name}' not found[/red]")
            return

        gen = ToolDocGenerator(hub)
        md = gen.generate_tool_md(manifest)
        console.print(Panel(md[:2000], title=f"Docs: {tool_name}"))
        if len(md) > 2000:
            console.print(f"[dim]... ({len(md)} chars total, use 'vagent docs generate --tool {tool_name}' for full)[/dim]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")

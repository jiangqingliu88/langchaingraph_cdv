"""
Knowledge Graph 持久化 —— 把验证图存进现有持久化表 / 从表载回。

打通"设计层三层映射模型"表（persistence/models.py）与内存图：
  DesignModule        ↔ module + signals
  DesignFeature       ↔ feature（module_id 存 feature→module 边）
  ReqFeatureMap       ↔ requirement→feature 边（req_id 存需求名）
  FeatureTestpointMap ↔ feature→test 边（testpoint_id 存测试名）

注意：
  - coverage_bin 是运行时数据（CoverageMap），不属于设计层表，不持久化。
  - DocRequirement 需要 document_id，本模块用 ReqFeatureMap.req_id 存需求名，不写 DocRequirement。

用法:
    from src.layers.l3_decision.knowledge.persistence import save_graph_to_db, load_graph_from_db
    await save_graph_to_db(graph, project_id)
    g = await load_graph_from_db(project_id)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from .schema import NodeType, EdgeType
from .graph import VerificationGraph

logger = structlog.get_logger()


async def save_graph_to_db(graph: VerificationGraph, project_id: Optional[int] = None) -> Dict[str, int]:
    """把图的设计时子图（module/signal/feature/requirement/test）写入持久化表。

    返回 {"modules": n, "features": n}。
    """
    from sqlalchemy import select
    from src.layers.l4_memory.persistence.connection import get_session
    from src.layers.l4_memory.persistence.models import (
        DesignModule, DesignFeature, ReqFeatureMap, FeatureTestpointMap,
    )

    s = await get_session()
    try:
        # 1. module + signal
        module_id_map: Dict[str, int] = {}   # 图 module id → db id
        for mod in graph.nodes(NodeType.MODULE):
            signals = [
                {"name": sig.name, "signal_type": sig.props.get("type", ""),
                 "description": sig.props.get("description", "")}
                for sig in graph.neighbors(mod.id, EdgeType.SIGNAL, direction="out")
            ]
            dm = DesignModule(
                name=mod.name,
                signals=signals,
                interfaces=mod.props.get("interfaces", []),
                rtl_file=mod.props.get("rtl_file", ""),
            )
            s.add(dm)
            await s.flush()                 # 拿自增 id
            module_id_map[mod.id] = dm.id

        # 2. feature（module_id 存 feature→module 边）
        feature_id_map: Dict[str, int] = {}  # 图 feature id → db id
        for feat in graph.nodes(NodeType.FEATURE):
            mods = graph.neighbors(feat.id, EdgeType.RTL, direction="out")
            mod_id = module_id_map.get(mods[0].id) if mods else None
            # module_id 非空约束：无模块映射的功能跳过（图降级，不写脏数据）
            if mod_id is None:
                continue
            df = DesignFeature(
                name=feat.name,
                module_id=mod_id,
                level=feat.props.get("level", "P0"),
                description=feat.props.get("description", ""),
            )
            s.add(df)
            await s.flush()
            feature_id_map[feat.id] = df.id

        # 3. requirement → feature
        for feat in graph.nodes(NodeType.FEATURE):
            fid = feature_id_map.get(feat.id)
            if not fid:
                continue
            for req in graph.neighbors(feat.id, EdgeType.IMPLEMENTS, direction="in"):
                s.add(ReqFeatureMap(req_id=req.name, feature_id=fid,
                                    mapping_type="DIRECT", confidence=1.0))

        # 4. feature → test
        for feat in graph.nodes(NodeType.FEATURE):
            fid = feature_id_map.get(feat.id)
            if not fid:
                continue
            for t in graph.neighbors(feat.id, EdgeType.TEST, direction="out"):
                s.add(FeatureTestpointMap(feature_id=fid, testpoint_id=t.name))

        # 5. coverage_bin（设计时寄存器 bin：带 module/signal 链接；运行时 bin 由 record_coverage_bins 写）
        from src.layers.l4_memory.persistence.models import CoverageBinRecord
        for bin_node in graph.nodes(NodeType.COVERAGE_BIN):
            mod_name, sig_name = "", ""
            for up in graph.neighbors(bin_node.id, direction="in"):
                if up.type == NodeType.MODULE:
                    mod_name = up.name
                elif up.type == NodeType.SIGNAL:
                    sig_name = up.name
            s.add(CoverageBinRecord(
                name=bin_node.name, metric=bin_node.props.get("metric", "register"),
                signal=sig_name, module=mod_name, hit=False, misses=0,
            ))

        await s.commit()
        return {"modules": len(module_id_map), "features": len(feature_id_map)}
    finally:
        await s.close()


async def load_graph_from_db(project_id: Optional[int] = None) -> VerificationGraph:
    """从持久化表载回图的设计时子图。"""
    from sqlalchemy import select
    from src.layers.l4_memory.persistence.connection import get_session
    from src.layers.l4_memory.persistence.models import (
        DesignModule, DesignFeature, ReqFeatureMap, FeatureTestpointMap,
    )

    g = VerificationGraph()
    s = await get_session()
    try:
        # module + signal
        module_id_map: Dict[int, str] = {}
        for m in (await s.execute(select(DesignModule))).scalars().all():
            mn = g.add_node(NodeType.MODULE, m.name, rtl_file=m.rtl_file or "")
            module_id_map[m.id] = mn.id
            for sig in (m.signals or []):
                if isinstance(sig, dict) and sig.get("name"):
                    sn = g.add_node(NodeType.SIGNAL, sig["name"],
                                    signal_type=sig.get("signal_type", ""),
                                    description=sig.get("description", ""))
                    g.link(mn, sn, EdgeType.SIGNAL)

        # feature + feature→module
        feature_id_map: Dict[int, str] = {}
        for f in (await s.execute(select(DesignFeature))).scalars().all():
            fn = g.add_node(NodeType.FEATURE, f.name, level=f.level or "",
                            description=f.description or "")
            feature_id_map[f.id] = fn.id
            if f.module_id in module_id_map:
                g.link(fn, g.get_node(module_id_map[f.module_id]), EdgeType.RTL)

        # requirement → feature
        for rm in (await s.execute(select(ReqFeatureMap))).scalars().all():
            rn = g.add_node(NodeType.REQUIREMENT, rm.req_id)
            if rm.feature_id in feature_id_map:
                g.link(rn, g.get_node(feature_id_map[rm.feature_id]), EdgeType.IMPLEMENTS)

        # feature → test
        for tp in (await s.execute(select(FeatureTestpointMap))).scalars().all():
            if tp.feature_id in feature_id_map:
                tn = g.add_node(NodeType.TEST, tp.testpoint_id)
                g.link(g.get_node(feature_id_map[tp.feature_id]), tn, EdgeType.TEST)

        # coverage bin（运行时语义，跨 run 沉淀）
        from src.layers.l4_memory.persistence.models import CoverageBinRecord
        for c in (await s.execute(select(CoverageBinRecord))).scalars().all():
            bn = g.add_node(NodeType.COVERAGE_BIN, c.name, metric=c.metric or "",
                            signal=c.signal or "", module=c.module or "", hit=bool(c.hit))
            # 挂回 signal / module（优先 signal）
            sig = g.find(NodeType.SIGNAL, c.signal) if c.signal else None
            if sig:
                g.link(sig, bn, EdgeType.COVERAGE)
            elif c.module:
                mod = g.find(NodeType.MODULE, c.module)
                if mod:
                    g.link(mod, bn, EdgeType.COVERAGE)

        # bug / fix（运行时语义）
        from src.layers.l4_memory.persistence.models import VerificationBug, VerificationFix
        for b in (await s.execute(select(VerificationBug))).scalars().all():
            bn = g.add_node(NodeType.BUG, b.bug_id, description=b.description or "",
                            affected_signal=b.affected_signal or "",
                            affected_feature=b.affected_feature or "", status=b.status or "")
            # bug → signal/feature（affects 边）
            if b.affected_signal:
                sig = g.find(NodeType.SIGNAL, b.affected_signal)
                if sig:
                    g.link(bn, sig, EdgeType.AFFECTS)
            elif b.affected_feature:
                feat = g.find(NodeType.FEATURE, b.affected_feature)
                if feat:
                    g.link(bn, feat, EdgeType.AFFECTS)
        for f in (await s.execute(select(VerificationFix))).scalars().all():
            fn = g.add_node(NodeType.FIX, f.fix_id, description=f.description or "")
            bug = g.find(NodeType.BUG, f.bug_id)
            if bug:
                g.link(fn, bug, EdgeType.RESOLVES)

        return g
    finally:
        await s.close()


async def record_coverage_bins(bins, run_id: str = "", project_id: Optional[int] = None) -> int:
    """记录覆盖率 bin 命中状态（coverage agent 调用，跨 run 跟踪进度）。

    bins: CoverageMap 的 bins 列表 [{name|location, metric, signal, hit, misses}]
    按 name 做 upsert：已有记录更新 hit/misses/run_id，否则插入。
    返回写入的 bin 数。
    """
    from sqlalchemy import select
    from src.layers.l4_memory.persistence.connection import get_session
    from src.layers.l4_memory.persistence.models import CoverageBinRecord

    s = await get_session()
    try:
        count = 0
        for b in bins or []:
            if not isinstance(b, dict):
                continue
            name = b.get("name") or b.get("location") or b.get("signal")
            if not name:
                continue
            rec = (await s.execute(
                select(CoverageBinRecord).where(CoverageBinRecord.name == name)
            )).scalar_one_or_none()
            if rec:
                rec.hit = bool(b.get("hit", False))
                rec.misses = int(b.get("misses", 0) or 0)
                rec.run_id = run_id
                if b.get("metric"):
                    rec.metric = b["metric"]
                if b.get("signal"):
                    rec.signal = b["signal"]
            else:
                s.add(CoverageBinRecord(
                    project_id=project_id, run_id=run_id, name=name,
                    metric=b.get("metric", ""), signal=b.get("signal", ""),
                    hit=bool(b.get("hit", False)),
                    misses=int(b.get("misses", 0) or 0),
                ))
            count += 1
        await s.commit()
        return count
    finally:
        await s.close()


async def record_bugs_and_fixes(bugs, fixes, run_id: str = "",
                                project_id: Optional[int] = None,
                                module: str = "",
                                rtl_version_no: Optional[int] = None) -> Dict[str, int]:
    """记录 debug agent 产出的 bug + fix（跨 run 沉淀）。

    bugs:  [{bug_id, description, affected_signal, affected_feature, severity}]
    fixes: [{bug_id, fix_id, description}]
    返回 {"bugs": n, "fixes": n}。

    ## 血缘：bug 挂在**哪个 RTL 版本**上

    `module` + `rtl_version_no` 给出"**在哪个版本发现的**"，会写进
    `database/lineage.db` 的 `bug_rtl_links`（bug 本体仍在本库的
    `VerificationBug` 里，用 `bug_id` 作 join 键）。

    为什么值得单独记：RTL 迭代之后"这个 bug 还成立吗"只能靠版本回答 ——
    同一段代码的 v1 有这个问题、v2 修掉了，那 v1 上跑出来的历史结论就不该再
    拿来评价 v2。没有这层关联，跨版本的 bug 清单会一直挂着已经修好的条目。

    `module`/`rtl_version_no` 缺省就**不写链接**（不是写个 0）——
    "不知道在哪个版本"与"版本 0"是两回事。
    """
    from src.layers.l4_memory.persistence.connection import get_session
    from src.layers.l4_memory.persistence.models import VerificationBug, VerificationFix

    s = await get_session()
    try:
        n_bug = n_fix = 0
        for b in bugs or []:
            if not isinstance(b, dict) or not b.get("bug_id"):
                continue
            s.add(VerificationBug(
                project_id=project_id, bug_id=b["bug_id"],
                description=b.get("description", ""),
                affected_signal=b.get("affected_signal", ""),
                affected_feature=b.get("affected_feature", ""),
                status="open", severity=b.get("severity", "P2"),
                found_run_id=run_id,
            ))
            n_bug += 1
        for f in fixes or []:
            if not isinstance(f, dict) or not f.get("bug_id"):
                continue
            s.add(VerificationFix(
                bug_id=f["bug_id"], fix_id=f.get("fix_id", ""),
                description=f.get("description", ""),
            ))
            n_fix += 1
        await s.commit()
    finally:
        await s.close()

    # 血缘链接（另一个库，同步 sqlite）—— 失败只记日志：它不该拖垮 bug 落库
    if module and rtl_version_no is not None:
        try:
            from src.layers.l4_memory.lineage import LineageStore

            store = LineageStore()
            try:
                for b in bugs or []:
                    if isinstance(b, dict) and b.get("bug_id"):
                        store.link_bug(str(b["bug_id"]), str(module),
                                       found_version_no=rtl_version_no,
                                       found_run_id=run_id)
            finally:
                store.close()                              # Windows 文件锁
        except Exception as e:                             # noqa: BLE001
            logger.warning(f"bug↔RTL 版本链接失败（bug 本体已落库）: {e}")
    return {"bugs": n_bug, "fixes": n_fix}

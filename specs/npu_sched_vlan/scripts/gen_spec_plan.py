#!/usr/bin/env python3
"""Generate the spec-derived CMD_SCH target plan from reviewed extraction inputs.

Inputs (human-reviewed): docs/specs/cmdsched_*.csv + cmdsched_spec_meta.json
Outputs: docs/verification/CMDSCHED_*.csv, CMDSCHED_matrix.md, CMDSCHED_impact.md

Usage:
  python scripts/gen_spec_plan.py              # write outputs (spec hash must match)
  python scripts/gen_spec_plan.py --check      # verify inputs/outputs/spec hash in sync
  python scripts/gen_spec_plan.py --allow-spec-drift  # preview despite spec change
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "docs" / "specs"
OUT_DIR = ROOT / "docs" / "verification"

SPEC = SPEC_DIR / "cmdsched.md"
REQ = SPEC_DIR / "cmdsched_requirements.csv"
FEAT = SPEC_DIR / "cmdsched_features.csv"
TOPIC = SPEC_DIR / "cmdsched_topics.csv"
CONTRACT = SPEC_DIR / "cmdsched_contracts.csv"
TP = SPEC_DIR / "cmdsched_testpoints.csv"
CASE = SPEC_DIR / "cmdsched_cases.csv"
META = SPEC_DIR / "cmdsched_spec_meta.json"

FEATURE_COLUMNS = [
    "feature_no", "feature_id", "feature_level", "parent_feature_id",
    "feature_l1", "feature_l2", "feature_l3", "description", "applicable_topics",
]
TOPIC_COLUMNS = ["topic", "applicability", "reason"]
CONTRACT_COLUMNS = ["contract_id", "category", "content", "check_method", "gate", "spec_ref", "status"]
TP_COLUMNS = [
    "tp_id", "feature_id", "topic", "spec_ref", "contract_id", "test_point",
    "stimulus", "expected", "check_method", "case_plan", "priority", "status", "notes",
]
TP_OUT_COLUMNS = [
    "tp_id", "feature_id", "feature_no", "feature_path", "topic", "spec_ref",
    "contract_id", "test_point", "stimulus", "expected", "check_method",
    "case_plan", "priority", "status", "notes",
]
CASE_COLUMNS = [
    "case_id", "test_name", "batch", "contract_ids", "covergroups",
    "checks", "owner", "status", "notes",
]
CASE_OUT_COLUMNS = [
    "case_id", "test_name", "batch", "contract_ids", "covergroups",
    "checks", "owner", "status", "tp_count", "tp_ids", "notes",
]
REQ_COLUMNS = ["req_id", "spec_section", "description", "feature_ids", "priority", "notes"]

STATUSES = {"covered", "planned", "exempt", "out_of_scope"}
PRIORITIES = {"P0", "P1", "P2"}
FEATURE_NO_RE = re.compile(r"^1(?:\.\d+)*$")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or [], list(reader)


def render_csv(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([row.get(column, "") for column in header])
    return buffer.getvalue()


def write_csv(path, header, rows):
    path.write_text(render_csv(header, rows), encoding="utf-8-sig", newline="")


def write_markdown(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


def split(value):
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def feature_labels(feature):
    return [
        value for value in (feature["feature_l1"], feature["feature_l2"], feature["feature_l3"])
        if value and value != "-"
    ]


def feature_no_key(value):
    return tuple(int(part) for part in value.split("."))


def spec_hash():
    return hashlib.sha256(SPEC.read_bytes()).hexdigest()


def build_children(features):
    children = {}
    for feature in features.values():
        parent = feature["parent_feature_id"]
        if parent in features:
            children.setdefault(parent, []).append(feature["feature_id"])
    for kids in children.values():
        kids.sort(key=lambda fid: feature_no_key(features[fid]["feature_no"]))
    return children


def descendants(feature_id, children):
    result = []
    for child in children.get(feature_id, []):
        result.append(child)
        result.extend(descendants(child, children))
    return result


def closure(feature_id, children):
    return [feature_id, *descendants(feature_id, children)]


def feature_label(feature):
    if feature["feature_level"] == "root":
        return f"**{feature['feature_l1']}** (root)"
    segment = feature["feature_l3"] if feature["feature_l3"] != "-" else feature["feature_l2"]
    suffix = " (branch)" if feature["feature_level"] == "branch" else ""
    return f"{segment}{suffix}"


def read_old_output(name):
    path = OUT_DIR / name
    if not path.exists():
        return []
    _, rows = read_csv(path)
    return rows


def diff_rows(old_rows, new_rows, key):
    old = {row[key]: row for row in old_rows}
    new = {row[key]: row for row in new_rows}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(key_value for key_value in old if key_value in new and old[key_value] != new[key_value])
    return added, removed, changed


def build_plan(allow_drift=False):
    errors = []
    warnings = []
    req_header, requirements = read_csv(REQ)
    feat_header, features_in = read_csv(FEAT)
    topic_header, topics_in = read_csv(TOPIC)
    contract_header, contracts = read_csv(CONTRACT)
    tp_header, tps_in = read_csv(TP)
    case_header, cases_in = read_csv(CASE)
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}

    actual_hash = spec_hash()
    expected_hash = meta.get("spec_hash", "")
    drift = actual_hash != expected_hash
    if drift:
        message = (
            f"spec hash mismatch: meta={expected_hash or '(missing)'} actual={actual_hash}. "
            "Update the extraction files and cmdsched_spec_meta.json, or use --allow-spec-drift."
        )
        if allow_drift:
            warnings.append(message)
        else:
            errors.append(message)

    if req_header != REQ_COLUMNS:
        errors.append(f"{REQ.name}: header {req_header}")
    if feat_header != FEATURE_COLUMNS:
        errors.append(f"{FEAT.name}: header {feat_header}")
    if topic_header != TOPIC_COLUMNS:
        errors.append(f"{TOPIC.name}: header {topic_header}")
    if contract_header != CONTRACT_COLUMNS:
        errors.append(f"{CONTRACT.name}: header {contract_header}")
    if tp_header != TP_COLUMNS:
        errors.append(f"{TP.name}: header {tp_header}")
    if case_header != CASE_COLUMNS:
        errors.append(f"{CASE.name}: header {case_header}")
    if errors:
        return None, errors, warnings

    topics = {}
    for row in topics_in:
        topic = row["topic"].strip()
        if not topic:
            errors.append("topic 为空")
            continue
        if topic in topics:
            errors.append(f"topic 重复: {topic}")
        if row["applicability"] not in ("applicable", "NA"):
            errors.append(f"{topic}: applicability={row['applicability']!r} 非法")
        if not row["reason"].strip():
            errors.append(f"{topic}: reason 为空")
        topics[topic] = row
    if len(topics) != 10:
        errors.append(f"专题数应为 10，实际 {len(topics)}")

    features = {}
    for row in features_in:
        fid = row["feature_id"].strip()
        if not fid:
            errors.append("feature_id 为空")
            continue
        if fid in features:
            errors.append(f"feature_id 重复: {fid}")
        if not FEATURE_NO_RE.match(row["feature_no"].strip()):
            errors.append(f"{fid}: feature_no={row['feature_no']!r} 非法")
        if row["feature_level"] not in ("root", "branch", "leaf"):
            errors.append(f"{fid}: feature_level 非法")
        applicable = split(row["applicable_topics"])
        if not applicable:
            errors.append(f"{fid}: applicable_topics 为空")
        for topic in applicable:
            if topic not in topics:
                errors.append(f"{fid}: 未知专题 {topic}")
            elif topics[topic]["applicability"] != "applicable":
                errors.append(f"{fid}: N/A 专题 {topic} 不能适用")
        features[fid] = dict(row)

    roots = [f for f in features.values() if f["feature_level"] == "root"]
    if len(roots) != 1:
        errors.append(f"root 数应为 1，实际 {len(roots)}")
    feature_nos = {}
    for feature in features.values():
        fid = feature["feature_id"]
        no = feature["feature_no"]
        if no in feature_nos:
            errors.append(f"feature_no 重复: {no} ({feature_nos[no]} / {fid})")
        feature_nos[no] = fid
        parent = feature["parent_feature_id"]
        if feature["feature_level"] == "root":
            if parent != "-":
                errors.append(f"{fid}: root parent 必须为 -")
            if no != "1":
                errors.append(f"{fid}: root feature_no 必须为 1")
        elif parent in ("", "-") or parent not in features:
            errors.append(f"{fid}: parent_feature_id={parent!r} 不存在")
        else:
            parent_feature = features[parent]
            if not no.startswith(parent_feature["feature_no"] + "."):
                errors.append(f"{fid}: feature_no {no} 不是父编号 {parent_feature['feature_no']} 的子编号")
            if feature_labels(feature)[:-1] != feature_labels(parent_feature):
                errors.append(f"{fid}: feature 路径与父 feature 不一致")

    children = build_children(features)
    for feature in features.values():
        fid = feature["feature_id"]
        kids = children.get(fid, [])
        if feature["feature_level"] == "leaf" and kids:
            errors.append(f"{fid}: leaf 不能有子 feature")
        if feature["feature_level"] in ("root", "branch") and not kids:
            errors.append(f"{fid}: {feature['feature_level']} 必须有子 feature")

    contracts_by_id = {}
    for row in contracts:
        cid = row["contract_id"].strip()
        if cid in contracts_by_id:
            errors.append(f"contract_id 重复: {cid}")
        if not cid or not row["content"].strip() or not row["check_method"].strip():
            errors.append(f"{cid or '?'}: 契约字段为空")
        contracts_by_id[cid] = row

    tps = []
    tp_ids = set()
    for row in tps_in:
        tp_id = row["tp_id"].strip()
        feature_id = row["feature_id"].strip()
        topic = row["topic"].strip()
        contract_id = row["contract_id"].strip()
        if tp_id in tp_ids:
            errors.append(f"tp_id 重复: {tp_id}")
        tp_ids.add(tp_id)
        feature = features.get(feature_id)
        if not feature:
            errors.append(f"{tp_id}: feature_id={feature_id} 不存在")
            continue
        if topic not in topics:
            errors.append(f"{tp_id}: topic={topic} 不存在")
        elif topic not in split(feature["applicable_topics"]):
            errors.append(f"{tp_id}: topic={topic} 不适用于 {feature_id}")
        if contract_id not in contracts_by_id:
            errors.append(f"{tp_id}: contract_id={contract_id} 不在候选契约中")
        if row["status"] not in STATUSES:
            errors.append(f"{tp_id}: status={row['status']!r} 非法")
        if row["priority"] not in PRIORITIES:
            errors.append(f"{tp_id}: priority={row['priority']!r} 非法")
        if not row["spec_ref"].strip():
            errors.append(f"{tp_id}: spec_ref 为空")
        tps.append(dict(row))

    tp_by_feature_topic = {}
    for tp in tps:
        tp_by_feature_topic.setdefault((tp["feature_id"], tp["topic"]), []).append(tp)

    for feature_id, feature in features.items():
        desc = set(descendants(feature_id, children))
        for topic in split(feature["applicable_topics"]):
            direct = tp_by_feature_topic.get((feature_id, topic), [])
            rolled = any(
                tp["topic"] == topic and tp["feature_id"] in desc
                for tp in tps
            )
            if not direct and not rolled:
                errors.append(f"{feature_id} x {topic}: 自身及子 feature 均无 TP")

    requirement_cover = set()
    for row in requirements:
        req_id = row["req_id"].strip()
        feature_ids = split(row["feature_ids"])
        if not feature_ids:
            errors.append(f"{req_id}: feature_ids 为空")
            continue
        req_features = set()
        for fid in feature_ids:
            if fid not in features:
                errors.append(f"{req_id}: feature {fid} 不存在")
            else:
                req_features.update(closure(fid, children))
        requirement_cover.update(req_features)
        req_tps = [tp for tp in tps if tp["feature_id"] in req_features]
        if not req_tps:
            errors.append(f"{req_id}: 没有任何 TP 覆盖其 feature 集合")
    for feature in features.values():
        if feature["feature_level"] == "leaf" and feature["feature_id"] not in requirement_cover:
            errors.append(f"{feature['feature_id']}: leaf 未被任何 spec requirement 引用")

    used_contracts = {tp["contract_id"] for tp in tps}
    orphan_contracts = sorted(set(contracts_by_id) - used_contracts)

    tp_out = []
    for tp in tps:
        feature = features[tp["feature_id"]]
        tp_out.append({
            **tp,
            "feature_no": feature["feature_no"],
            "feature_path": "/".join(feature_labels(feature)),
        })

    cases = {}
    for row in cases_in:
        case_id = row["case_id"].strip()
        if not case_id:
            errors.append("case_id 为空")
            continue
        if case_id in cases:
            errors.append(f"case_id 重复: {case_id}")
        contract_ids = split(row["contract_ids"])
        if not contract_ids:
            errors.append(f"{case_id}: contract_ids 为空")
        for cid in contract_ids:
            if cid not in contracts_by_id:
                errors.append(f"{case_id}: contract {cid} 不存在")
        for field in ("covergroups", "checks", "owner"):
            if not row[field].strip():
                errors.append(f"{case_id}: {field} 为空")
        if row["status"] not in ("planned", "implemented", "signed_off", "blocked"):
            errors.append(f"{case_id}: status={row['status']!r} 非法")
        cases[case_id] = dict(row)

    case_tp_ids = {}
    for tp in tps:
        case_plan = tp["case_plan"].strip()
        if case_plan not in cases:
            errors.append(f"{tp['tp_id']}: case_plan={case_plan} 不在 planned case 中")
        else:
            case_tp_ids.setdefault(case_plan, []).append(tp["tp_id"])
    for case_id in cases:
        if not case_tp_ids.get(case_id):
            errors.append(f"{case_id}: 没有 TP 指向该 case")

    case_contracts = set()
    for row in cases.values():
        case_contracts.update(split(row["contract_ids"]))
    orphan_case_contracts = sorted(set(contracts_by_id) - case_contracts)
    for cid in orphan_case_contracts:
        errors.append(f"{cid}: 没有被任何 planned case 引用")

    case_out = []
    for case_id, row in cases.items():
        ids = sorted(case_tp_ids.get(case_id, []))
        case_out.append({**row, "tp_count": str(len(ids)), "tp_ids": "|".join(ids)})

    topic_names = [row["topic"] for row in topics_in]
    lines = [
        "# CMD_SCH spec target plan — feature 拆分树 × 专题",
        "",
        f"> 来源：`{meta.get('source', 'docs/specs/cmdsched.md')}`",
        f"> spec_version: `{meta.get('spec_version', '?')}` · spec_hash: `{actual_hash[:16]}…` · "
        f"plan_version: `{meta.get('plan_version', '?')}`",
        "> 由 `scripts/gen_spec_plan.py` 从 `docs/specs/cmdsched_*.csv` 生成；不要手改。",
        "> 所有测试点状态来自输入；target plan 不参与执行门禁，当前没有可执行证据。",
    ]
    if drift:
        lines.append("> **SPEC DRIFT**：当前 spec 哈希与 meta 不一致，本计划已过期。")
    lines += [
        "",
        "| 编号 | feature | " + " | ".join(topic_names) + " |",
        "|---|" + "---|" * len(topic_names),
    ]

    def walk(feature_id):
        yield feature_id
        for child in children.get(feature_id, []):
            yield from walk(child)

    root_id = roots[0]["feature_id"] if roots else None
    for feature_id in (walk(root_id) if root_id else []):
        feature = features[feature_id]
        desc = set(descendants(feature_id, children))
        cells = []
        for topic in topic_names:
            if topic not in split(feature["applicable_topics"]):
                cells.append("N/A")
                continue
            direct = tp_by_feature_topic.get((feature_id, topic), [])
            if direct:
                labels = []
                for tp in direct:
                    suffix = "" if tp["status"] == "covered" else f" ({tp['status']})"
                    labels.append(f"`{tp['tp_id']}`{suffix}")
                cells.append("<br>".join(labels))
            elif any(tp["topic"] == topic and tp["feature_id"] in desc for tp in tps):
                cells.append("↳")
            else:
                cells.append("**GAP**")
        lines.append(
            f"| {feature['feature_no']} | {feature_label(feature)} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## 图例",
        "",
        "- 无后缀：`covered`",
        "- `(planned)` / `(exempt)` / `(out_of_scope)`：输入声明的状态",
        "- `↳`：父 feature 的专题由子 feature 汇总",
        "- `N/A`：该 feature 不适用该专题",
        "- `**GAP**`：适用但无测试点",
        "",
        "## 统计",
        "",
        f"- spec 需求：{len(requirements)}",
        f"- feature 节点：{len(features)}",
        f"- 测试点：{len(tps)}",
        f"- 专题：{len(topics)}",
        f"- spec 契约：{len(contracts_by_id)}（已推进）",
        f"- planned case：{len(cases)}",
        f"- 未被 TP 使用的 spec 契约：{len(orphan_contracts)}",
    ]
    if orphan_contracts:
        lines.append("")
        lines.append("未使用契约：" + "、".join(f"`{cid}`" for cid in orphan_contracts))
    matrix_text = "\n".join(lines) + "\n"

    case_lines = [
        "# CMD_SCH planned case layer",
        "",
        f"> 来源：`{meta.get('source', 'docs/specs/cmdsched.md')}`；由 `scripts/gen_spec_plan.py` 生成。",
        f"> spec_version: `{meta.get('spec_version', '?')}` · spec_hash: `{actual_hash[:16]}…` · "
        f"plan_version: `{meta.get('plan_version', '?')}`",
        "> case 全部为输入声明的状态；本层用于契约 → case → TP 的追溯，不参与执行门禁，当前无真实证据。",
        "",
        "## 汇总",
        "",
        f"- planned cases: {len(cases)}",
        f"- contracts covered: {len(case_contracts)}/{len(contracts_by_id)}",
        f"- TPs assigned: {sum(len(ids) for ids in case_tp_ids.values())}/{len(tps)}",
        "",
        "## Case 计划",
        "",
        "| case | batch | owner | status | contracts | TPs | covergroups | checks |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in case_out:
        covergroups = row["covergroups"].replace("|", " / ")
        checks = row["checks"].replace("|", " / ")
        case_lines.append(
            f"| `{row['case_id']}` | {row['batch']} | {row['owner']} | {row['status']} | "
            f"{len(split(row['contract_ids']))} | {row['tp_count']} | {covergroups} | {checks} |")
    case_lines += ["", "## Contract → case / TP", "",
                   "| contract | status | cases | TP count | TPs |",
                   "|---|---|---|---|---|"]
    for cid in sorted(contracts_by_id):
        related_cases = [row["case_id"] for row in case_out if cid in split(row["contract_ids"])]
        related_tps = [tp["tp_id"] for tp in tps if tp["contract_id"] == cid]
        tp_text = ", ".join(related_tps[:6]) + (" …" if len(related_tps) > 6 else "")
        case_lines.append(
            f"| `{cid}` | {contracts_by_id[cid]['status']} | "
            f"{', '.join(related_cases) or '-'} | {len(related_tps)} | {tp_text or '-'} |")
    case_trace_text = "\n".join(case_lines) + "\n"

    old_features = read_old_output("CMDSCHED_features.csv")
    old_tps = read_old_output("CMDSCHED_testpoints.csv")
    old_contracts = read_old_output("CMDSCHED_contracts.csv")
    old_cases = read_old_output("CMDSCHED_cases.csv")
    feat_added, feat_removed, feat_changed = diff_rows(old_features, features_in, "feature_id")
    tp_added, tp_removed, tp_changed = diff_rows(old_tps, tp_out, "tp_id")
    con_added, con_removed, con_changed = diff_rows(old_contracts, contracts, "contract_id")
    case_added, case_removed, case_changed = diff_rows(old_cases, case_out, "case_id")

    impact_lines = [
        "# CMDSCHED spec plan impact",
        "",
        f"- spec: `{meta.get('source', 'docs/specs/cmdsched.md')}`",
        f"- spec_version: `{meta.get('spec_version', '?')}`",
        f"- spec_hash: `{actual_hash}`",
        f"- plan_version: `{meta.get('plan_version', '?')}`",
        f"- requirements: {len(requirements)}",
        "",
        "| 对象 | 旧 | 新 | 新增 | 删除 | 变更 |",
        "|---|---|---|---|---|---|",
        f"| feature | {len(old_features)} | {len(features_in)} | {len(feat_added)} | {len(feat_removed)} | {len(feat_changed)} |",
        f"| testpoint | {len(old_tps)} | {len(tp_out)} | {len(tp_added)} | {len(tp_removed)} | {len(tp_changed)} |",
        f"| contract | {len(old_contracts)} | {len(contracts)} | {len(con_added)} | {len(con_removed)} | {len(con_changed)} |",
        f"| case | {len(old_cases)} | {len(case_out)} | {len(case_added)} | {len(case_removed)} | {len(case_changed)} |",
        "",
        "## 新增",
        "",
        f"- feature: {', '.join(feat_added) or '无'}",
        f"- testpoint: {', '.join(tp_added) or '无'}",
        f"- contract: {', '.join(con_added) or '无'}",
        f"- case: {', '.join(case_added) or '无'}",
        "",
        "## 删除",
        "",
        f"- feature: {', '.join(feat_removed) or '无'}",
        f"- testpoint: {', '.join(tp_removed) or '无'}",
        f"- contract: {', '.join(con_removed) or '无'}",
        f"- case: {', '.join(case_removed) or '无'}",
        "",
        "## 变更",
        "",
        f"- feature: {', '.join(feat_changed) or '无'}",
        f"- testpoint: {', '.join(tp_changed) or '无'}",
        f"- contract: {', '.join(con_changed) or '无'}",
        f"- case: {', '.join(case_changed) or '无'}",
        "",
        "## 未被 TP 使用的 spec 契约",
        "",
        "、".join(f"`{cid}`" for cid in orphan_contracts) if orphan_contracts else "无",
        "",
        "> 本报告只描述 target plan 的输入/输出变化，不产生执行证据。",
    ]
    impact_text = "\n".join(impact_lines) + "\n"
    has_changes = any([feat_added, feat_removed, feat_changed,
                       tp_added, tp_removed, tp_changed,
                       con_added, con_removed, con_changed,
                       case_added, case_removed, case_changed])

    outputs = {
        "CMDSCHED_features.csv": (FEATURE_COLUMNS, features_in, True),
        "CMDSCHED_topics.csv": (TOPIC_COLUMNS, topics_in, True),
        "CMDSCHED_testpoints.csv": (TP_OUT_COLUMNS, tp_out, True),
        "CMDSCHED_contracts.csv": (CONTRACT_COLUMNS, contracts, True),
        "CMDSCHED_cases.csv": (CASE_OUT_COLUMNS, case_out, True),
        "CMDSCHED_matrix.md": (matrix_text, None, False),
        "CMDSCHED_case_trace.md": (case_trace_text, None, False),
        "CMDSCHED_impact.md": (impact_text, None, False),
    }
    plan = {
        "requirements": requirements,
        "features": features,
        "topics": topics,
        "contracts": contracts_by_id,
        "tps": tps,
        "tp_out": tp_out,
        "cases": cases,
        "case_out": case_out,
        "case_trace": case_trace_text,
        "matrix": matrix_text,
        "impact": impact_text,
        "outputs": outputs,
        "orphan_contracts": orphan_contracts,
        "spec_hash": actual_hash,
        "meta": meta,
        "drift": drift,
        "has_changes": has_changes,
    }
    return plan, errors, warnings


def check_outputs(plan):
    errors = []
    for name in ("CMDSCHED_features.csv", "CMDSCHED_topics.csv",
                 "CMDSCHED_testpoints.csv", "CMDSCHED_contracts.csv",
                 "CMDSCHED_cases.csv"):
        header, rows, _ = plan["outputs"][name]
        expected = render_csv(header, rows)
        path = OUT_DIR / name
        actual = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        if actual != expected:
            errors.append(f"{name}: 生成结果 != 仓库文件")
    # CMDSCHED_impact.md is a change report, not a reproducible source; it is
    # regenerated on every write and deliberately excluded from the sync check.
    for name in ("CMDSCHED_matrix.md", "CMDSCHED_case_trace.md"):
        expected = plan["outputs"][name][0]
        path = OUT_DIR / name
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if actual != expected:
            errors.append(f"{name}: 生成结果 != 仓库文件")
    return errors


def main():
    args = sys.argv[1:]
    check = "--check" in args
    allow_drift = "--allow-spec-drift" in args
    plan, errors, warnings = build_plan(allow_drift=allow_drift)
    for warning in warnings:
        print(f"[WARN] {warning}")
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        sys.exit(1)
    if check:
        differences = check_outputs(plan)
        if differences:
            for difference in differences:
                print(f"[FAIL] {difference}")
            print("[FAIL] spec plan is stale; run python scripts/gen_spec_plan.py")
            sys.exit(1)
        print(f"[PASS] spec plan in sync: requirements={len(plan['requirements'])} "
              f"features={len(plan['features'])} tps={len(plan['tps'])} "
              f"contracts={len(plan['contracts'])} cases={len(plan['cases'])}")
        return
    for name, (header, rows, is_csv) in plan["outputs"].items():
        path = OUT_DIR / name
        # Preserve the last impact report when there is no new diff.
        if name == "CMDSCHED_impact.md" and not plan["has_changes"] and path.exists():
            continue
        if is_csv:
            write_csv(path, header, rows)
        else:
            write_markdown(path, header)
    print(f"[WRITE] CMDSCHED features={len(plan['features'])} tps={len(plan['tps'])} "
          f"contracts={len(plan['contracts'])} cases={len(plan['cases'])}")
    print(f"[WRITE] spec_version={plan['meta'].get('spec_version')} "
          f"spec_hash={plan['spec_hash'][:16]}…")
    if plan["orphan_contracts"]:
        print("[WARN] orphan contracts: " + ", ".join(plan["orphan_contracts"]))


if __name__ == "__main__":
    main()

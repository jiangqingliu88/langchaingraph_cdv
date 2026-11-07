#!/usr/bin/env python3
"""Lint spec extraction traceability and target-plan freshness.

Checks:
- docs/specs/cmdsched.md hash matches cmdsched_spec_meta.json;
- every requirement maps to existing features and at least one TP;
- every leaf feature is referenced by a requirement and has TP coverage;
- feature tree/topic/contract/TP references are valid;
- generated CMDSCHED_* CSVs and matrix match the reviewed inputs.

This script is intentionally NOT in run_demo: the target plan is not a V00 gate.
"""
from __future__ import annotations

import sys

import gen_spec_plan as gen


def main():
    plan, errors, warnings = gen.build_plan(allow_drift=False)
    for warning in warnings:
        print(f"[WARN] {warning}")
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        sys.exit(1)

    differences = gen.check_outputs(plan)
    if differences:
        for difference in differences:
            print(f"[FAIL] {difference}")
        print("[FAIL] generated CMDSCHED_* are stale; run python scripts/gen_spec_plan.py")
        sys.exit(1)

    print(f"[PASS] spec trace: requirements={len(plan['requirements'])} "
          f"features={len(plan['features'])} tps={len(plan['tps'])} "
          f"contracts={len(plan['contracts'])} cases={len(plan['cases'])}")
    print(f"[PASS] spec_version={plan['meta'].get('spec_version')} "
          f"spec_hash={plan['spec_hash'][:16]}… "
          f"plan_version={plan['meta'].get('plan_version')}")
    if plan["orphan_contracts"]:
        print("[WARN] orphan contracts: " + ", ".join(plan["orphan_contracts"]))
    print("[PASS] CMDSCHED_* in sync with docs/specs/cmdsched_*.csv")
    sys.exit(0)


if __name__ == "__main__":
    main()

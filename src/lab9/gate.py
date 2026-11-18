"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def _is_nan_or_inf(val) -> bool:
    return isinstance(val, float) and (math.isnan(val) or math.isinf(val))


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate."""
    problems: list[str] = []

    # 1. Check metric values in pr["metrics"] for NaN or inf
    pr_metrics = pr.get("metrics") or {}
    for k, v in pr_metrics.items():
        if _is_nan_or_inf(v):
            problems.append(f"metric {k} is NaN or inf")

    # 2. Check evaluator_failures non-empty
    if pr.get("evaluator_failures"):
        problems.append(f"evaluator_failures is non-empty ({len(pr['evaluator_failures'])})")

    # 3. Check row count matches manifest items x len(manifest seeds) and no duplicate (item_id, seed)
    pr_rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    manifest = pr.get("manifest") or {}
    expected_len = int(manifest.get("items") or 0) * len(manifest.get("seeds") or [])
    if len(pr_rows) != expected_len:
        problems.append(f"row count {len(pr_rows)} != manifest items*seeds ({expected_len})")

    pr_pairs = [(r.get("item_id"), r.get("seed")) for r in pr_rows]
    base_pairs = [(r.get("item_id"), r.get("seed")) for r in base_rows]
    if len(set(pr_pairs)) != len(pr_pairs):
        problems.append("duplicate (item_id, seed) rows in PR report")

    # 4. Check (item_id, seed) set of PR matches baseline
    if set(pr_pairs) != set(base_pairs) or len(pr_rows) != len(base_rows):
        problems.append("PR (item_id, seed) set differs from baseline")

    # 5. Check graded spec metrics in rows are not None / NaN
    row_keys = set(pr_rows[0].keys()) if pr_rows else set()
    graded_ids = [
        m["id"]
        for m in spec.get("metrics", [])
        if m["id"] in GRADERS or m["id"] in row_keys
    ]
    for r in pr_rows:
        for mid in graded_ids:
            val = r.get(mid)
            if val is None or _is_nan_or_inf(val):
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has missing/NaN value for {mid}")
                break
        if len(problems) > 10:
            break

    # 6. Check slice tags per item_id match between PR and baseline
    base_slices_by_item: dict[str, list[str]] = {}
    for r in base_rows:
        iid = r.get("item_id")
        if iid is not None:
            base_slices_by_item.setdefault(iid, sorted(r.get("slices") or []))
    for r in pr_rows:
        iid = r.get("item_id")
        pr_sl = sorted(r.get("slices") or [])
        if iid in base_slices_by_item and pr_sl != base_slices_by_item[iid]:
            problems.append(f"slice tags for {iid} differ from baseline ({pr_sl} vs {base_slices_by_item[iid]})")
            break

    # 7. Ratchet check when base_spec is given on the same eval_set_version
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        cur_metrics = {m["id"]: m for m in spec.get("metrics") or []}
        for bm in base_spec.get("metrics") or []:
            mid = bm["id"]
            if mid not in cur_metrics:
                problems.append(f"ratchet: metric {mid} removed from spec")
                continue
            cm = cur_metrics[mid]
            if bm.get("blocking") and not cm.get("blocking"):
                problems.append(f"ratchet: blocking metric {mid} became non-blocking")
            bth = bm.get("threshold") or {}
            cth = cm.get("threshold") or {}
            if "min" in bth:
                if "min" not in cth or cth["min"] < bth["min"]:
                    problems.append(f"ratchet: threshold min for {mid} lowered ({cth.get('min')} < {bth['min']})")
            if "max" in bth:
                if "max" not in cth or cth["max"] > bth["max"]:
                    problems.append(f"ratchet: threshold max for {mid} raised ({cth.get('max')} > {bth['max']})")
            if "max_increase" in bth:
                if "max_increase" not in cth or cth["max_increase"] > bth["max_increase"]:
                    problems.append(f"ratchet: max_increase for {mid} raised")
            if bth.get("no_significant_drop") and not cth.get("no_significant_drop"):
                problems.append(f"ratchet: no_significant_drop dropped for {mid}")

        cur_slices = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
        for bs in base_spec.get("slices") or []:
            key = (bs["name"], bs["metric"])
            if key not in cur_slices:
                problems.append(f"ratchet: slice {bs['name']}/{bs['metric']} removed from spec")
                continue
            cs = cur_slices[key]
            if bs.get("blocking") and not cs.get("blocking"):
                problems.append(f"ratchet: blocking slice {key} became non-blocking")
            if "min" in bs and ("min" not in cs or cs["min"] < bs["min"]):
                problems.append(f"ratchet: slice {key} min lowered ({cs.get('min')} < {bs['min']})")
            if bs.get("no_significant_drop") and not cs.get("no_significant_drop"):
                problems.append(f"ratchet: slice {key} dropped no_significant_drop")

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap") or {}
    for s in spec.get("slices") or []:
        sname = s["name"]
        metric = s["metric"]
        sid = f"slice:{sname}/{metric}"
        a = per_item(pr, metric, slice_name=sname)
        b = per_item(base, metric, slice_name=sname)
        val = round(sum(a.values()) / len(a), 4) if a else None
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "min" in s and val < s["min"]:
            verdict = "fail"
        if s.get("no_significant_drop") and val is not None:
            keys = sorted(set(a) & set(b))
            if keys:
                d, lo, hi = stats.paired_bootstrap(
                    [a[k] for k in keys],
                    [b[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                    confidence=bs.get("confidence", 0.95),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th_view = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th_view):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            if keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Diagnostics for designing the SWE-bench agent - DESIGN SET ONLY.

This reads the gold patches, so it must never touch the split that is reported (SWE-bench Lite) and is never imported
by the agent. It measures, on the design issues, what the agent's early steps got right:

    gold file among the candidates / picked   localisation
    reproduction kept / imports the package   the reproduction step
    reproduction valid                        it fails on the original code and passes once the gold patch is applied
    regression command / passes before        the tests that guard against breaking what worked
    neo4d variants tried / shipped, resolved  (resolved from the official harness's report)

    python scripts/swebench_design.py --run runs/design_v0_neo4d --report <harness report> [--validate]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from neo4d import swe_agent as S  # noqa: E402


def gold_files(patch):
    return re.findall(r"^diff --git a/(\S+)", patch, re.M)


def accepted_script(traj):
    """The reproduction the agent kept: the first `reproduce` entry that failed without being broken (older trajectories
    do not store the script: it is the code block of the model reply before the entry)."""
    last = ""
    for e in traj:
        if e["kind"] == "model":
            last = e["response"]
        if e["kind"] == "reproduce" and "code" in e:
            broken = any(s in e["output"] for s in ("SyntaxError", "ModuleNotFoundError", "ImportError: cannot import name"))
            if e["code"] != 0 and not broken:
                return e.get("script") or S.code_block(last)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--report")
    ap.add_argument("--dataset", default="SWE-bench/SWE-bench")
    ap.add_argument("--validate", action="store_true", help="run each kept reproduction with the gold patch applied")
    ap.add_argument("--image", default="swebench/sweb.eval.x86_64.{id}:latest")
    a = ap.parse_args()
    run = Path(a.run)
    ids = json.loads((run / "run.json").read_text())["instances"]
    insts = {x["instance_id"]: x for x in S.load_instances(a.dataset, "test") if x["instance_id"] in set(ids)}
    resolved = S.resolved(a.report) if a.report else set()
    rows = []
    for i in sorted(ids):
        tp = run / "trajs" / f"{i}.json"
        if not tp.exists():
            continue
        t, x = json.loads(tp.read_text()), insts[i]
        gold = gold_files(x["patch"])
        loc = next((e for e in t if e["kind"] == "localise"), {})
        cands = loc.get("candidates", [])
        reg = next((e for e in t if e["kind"] == "regression"), {})
        reps = [e for e in t if e["kind"] == "reproduce"]
        script = accepted_script(t)
        pick = None
        # the file the agent worked on: the one its diff touches, else the model's localisation answer
        end = next((e for e in t if e["kind"] == "end"), {})
        touched = re.findall(r"^diff --git a/(\S+)", end.get("diff", ""), re.M)
        model_calls = [e for e in t if e["kind"] == "model"]
        if model_calls:
            pick = next((p for p in cands if p in model_calls[0]["response"]), cands[0] if cands else None)
        test_files = gold_files(x["test_patch"])
        row = dict(id=i, repo=x["repo"], gold=gold, in_cands=any(g in cands for g in gold), rank=next(
            (k + 1 for k, p in enumerate(cands) if p in gold), None), picked=pick in gold if pick else False,
            touched=touched, reps=len(reps), rejected=sum("rejected" in e for e in reps), kept=script is not None,
            imports=S.imports(script, S.package_of(gold[0])) if script else False,
            regress=reg.get("command"), passes_before=reg.get("passes_before"),
            regress_hits_gold_tests=bool(reg.get("command")) and any(
                f in reg["command"] or (f.startswith("tests/") and f.split("/")[1] in reg["command"]) for f in test_files),
            tried=sum(e.get("tried", 0) for e in t if e["kind"] == "neo4d"),
            shipped=sum(bool(e.get("shipped")) for e in t if e["kind"] == "neo4d"),
            calls=t[-1].get("model_calls"), seconds=t[-1].get("seconds"), resolved=i in resolved)
        if a.validate and script:
            env = S.DockerEnv(S.image_of(i, a.image), f"design_validate_{i}")
            try:
                env.write(env.repro, script)
                before = env.py(env.repro)[0]
                env.write("/tmp/gold.patch", x["patch"])
                env.run("git apply /tmp/gold.patch", timeout=120)
                env.write(env.repro, script)
                after = env.py(env.repro)[0]
            finally:
                env.close()
            row.update(valid=before != 0 and after == 0)
        rows.append(row)
    out = run / "design_diag.json"
    out.write_text(json.dumps(rows, indent=1))
    n = len(rows)
    s = lambda k: sum(bool(r.get(k)) for r in rows)
    print(f"{run.name}: {n} issues | gold file in candidates {s('in_cands')} | picked {s('picked')} | "
          f"reproduction kept {s('kept')} (imports the package {s('imports')}"
          + (f", valid with the gold patch {s('valid')}" if a.validate else "") + f") | rejected tries "
          f"{sum(r['rejected'] for r in rows)} | regression set {s('regress')}, passes before {s('passes_before')}, "
          f"runs the gold test files {s('regress_hits_gold_tests')} | neo4d tried {sum(r['tried'] for r in rows)}, "
          f"shipped {s('shipped')} | resolved {s('resolved')} | model calls {sum(r['calls'] or 0 for r in rows)}, "
          f"hours {sum(r['seconds'] or 0 for r in rows) / 3600:.2f}")


if __name__ == "__main__":
    main()

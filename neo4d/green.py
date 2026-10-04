"""The green benchmark: energy per certified repair, fluidnet against an AI agent, on the same real bugs.

The bugs are fluidnet's own click race (docs/results/2026-09-25 in the fluidnet repo): click at 06b2a67, 2,240
tests, one real single-token bug planted per fault kind. The agent side is THEIR recorded run (race_agent.jsonl:
seconds and tokens per bug); the fluidnet side is re-run HERE, metered:

    power    the Mac's own whole-system power telemetry (AppleSmartBattery SystemLoad, mW), sampled every 0.5 s
             without sudo; energy = the integral, and the integral ABOVE the idle baseline measured just before
    cpu      CPU seconds of every child process (resource.getrusage)
    outcome  the file byte-exact to click's own line, the full suite green afterwards

    python3 green.py --pilot            one bug (6764, parser.py:437)
    python3 green.py --all              every reconstructed bug
"""
from __future__ import annotations

import argparse
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from neo4d import REPO as ROOT, KERNELS
CLICK = ROOT / "bench" / "click"
TPY = ROOT / "bench" / "tvenv" / "bin" / "python"
VBIN = ROOT / ".venv" / "bin"
FNREPO = ROOT / "bench" / "fluidnet" / "docs" / "results" / "2026-09-25"
NETS = [FNREPO / "nets" / n for n in ("A_corpus.py", "B_sibling.py", "C_real.py")]
OUT = ROOT / "results" / "green_runs.jsonl"
OUTS = {"alone": OUT, "lead": ROOT / "results" / "green_lead.jsonl", "live": ROOT / "results" / "green_live.jsonl"}
HYB = FNREPO / "data" / "hyb.jsonl"
# the AI locator for the live arm: Claude Code, print mode, EVERY tool denied - it sees only what fluidnet sends
BODY = ("claude -p --output-format json --no-session-persistence --permission-mode dontAsk --disallowedTools "
        "Bash Read Edit Write Glob Grep WebFetch WebSearch NotebookEdit Agent Task Skill TodoWrite")

# id -> (file, line, click's line, the planted line, how it is known)
BUGS = {
    6764: ("src/click/parser.py", 437, "if len(state.rargs) < nargs:", "if len(state.rargs) <= nargs:",
           "logged: CERTIFIED <= -> <"),
    7463: ("src/click/termui.py", 295, "err: bool = False,", "err: bool = True,", "logged: CERTIFIED True -> False"),
    1490: ("src/click/_termui_impl.py", 730, "args=shlex.split(editor) + list(filenames),",
           "args=shlex.split(editor) - list(filenames),", "logged: CERTIFIED - -> +"),
    2014: ("src/click/_textwrap.py", 168, "self.initial_indent += indent", "self.initial_indent -= indent",
           "op augassign on +="),
    1768: ("src/click/_termui_impl.py", 579, 'less_env = os.environ.get("LESS", "")', 'less_env = os.environ.get("LESS")',
           "logged: the oracle request shows the planted line"),
    3457: ("src/click/core.py", 1877, 'if self.command_class and kwargs.get("cls") is None:',
           'if self.command_class or kwargs.get("cls") is None:', "logged: CERTIFIED and <-> or"),
    3573: ("src/click/core.py", 2023, "limit = formatter.width - 6 - max(len(cmd[0]) for cmd in commands)",
           "limit = formatter.width - 6 - min(len(cmd[0]) for cmd in commands)", "op minmax on max("),
    9396: ("src/click/utils.py", 84, "words = words[: i + 1]", "words = words[: i + 2]", "logged: CERTIFIED 2 -> 1"),
    5292: ("src/click/core.py", 3396, "if not expose_value:", "if expose_value:", "INFERRED: op bareguard"),
}


def system_mw() -> int | None:
    out = subprocess.run(["ioreg", "-rw0", "-c", "AppleSmartBattery"], capture_output=True, text=True).stdout
    m = re.search(r'"SystemLoad"=(\d+)', out)
    return int(m.group(1)) if m else None


class Meter(threading.Thread):
    def __init__(self, period=0.5):
        super().__init__(daemon=True)
        self.period, self.samples, self.stop = period, [], threading.Event()

    def run(self):
        while not self.stop.is_set():
            mw = system_mw()
            if mw is not None:
                self.samples.append((time.time(), mw))
            self.stop.wait(self.period)

    def joules(self, idle_mw=0.0):
        e = 0.0
        for (t0, p0), (t1, _p1) in zip(self.samples, self.samples[1:]):
            e += max(0.0, p0 - idle_mw) / 1000.0 * (t1 - t0)
        return e


def idle_baseline(seconds=15) -> float:
    m = Meter()
    m.start()
    time.sleep(seconds)
    m.stop.set(); m.join()
    ps = [p for _, p in m.samples]
    ps.sort()
    return ps[len(ps) // 2] if ps else 0.0          # median: one stray spike does not move it


def plant(bid: int) -> Path:
    f, line, orig, bug, _ = BUGS[bid]
    d = ROOT / "bench" / "race" / str(bid)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    subprocess.run(f"git -C {CLICK} archive HEAD | tar -x -C {d}", shell=True, check=True)
    p = d / f
    L = p.read_text().split("\n")
    assert L[line - 1].strip() == orig, (bid, L[line - 1])
    L[line - 1] = L[line - 1].replace(orig, bug)
    p.write_text("\n".join(L))
    for c in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "click"]):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *c], cwd=d, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=d)
    subprocess.run(["git", "config", "user.name", "t"], cwd=d)
    return d


def recorded_lead(bid: int):
    for l in open(HYB):
        r = json.loads(l)
        if r["id"] == bid:
            return r["lead"], r["body_secs"], r["body_tokens"]
    return None, None, None


def run(bid: int, idle_mw: float, arm: str = "alone") -> dict:
    d = plant(bid)
    f, line, orig, bug, how = BUGS[bid]
    env = {k: v for k, v in os.environ.items() if not re.search(r"API_KEY|ANTHROPIC|OPENAI", k)}
    env["PYTHONPATH"] = str(d / "src")
    env["PATH"] = f"{VBIN}:{env['PATH']}"
    cmd = [str(VBIN / "fluidnet"), "watch", str(d)] + sum((["--net", str(n)] for n in NETS), []) + \
          ["--python", str(TPY), "-j", "1", "--commit"]
    lead_info = (None, None, None)
    if arm == "lead":
        lead_info = recorded_lead(bid)
        for l in lead_info[0]:
            cmd += ["--lead", l]
    elif arm == "live":
        cmd += ["--body", BODY, "--mode", "speed"]
    log = d.parent / f"{bid}.log"
    meter = Meter()
    ru0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.time()
    meter.start()
    with open(log, "w") as fo:
        p = subprocess.Popen(cmd, cwd=d, env=env, stdout=fo, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            p.wait(timeout=5400)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(p.pid, 9)
        except ProcessLookupError:
            pass
        p.wait()
    secs = time.time() - t0
    meter.stop.set(); meter.join()
    ru1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)
    now = (d / f).read_text().split("\n")[line - 1].strip()
    suite = subprocess.run([str(TPY), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-W", "default", "--tb=no"],
                           cwd=d, env=env, capture_output=True, text=True)
    text = log.read_text()
    win = re.search(r"^winner: (.+?)(?:\s{2}|$)", text, re.M)
    mean_w = sum(p for _, p in meter.samples) / max(1, len(meter.samples)) / 1000
    rec = {"id": bid, "at": f"{f[10:]}:{line}", "how_known": how, "secs": round(secs, 1), "cpu_s": round(cpu, 1),
           "joules_total": round(meter.joules(), 1), "joules_above_idle": round(meter.joules(idle_mw), 1),
           "idle_w": round(idle_mw / 1000, 2), "mean_w": round(mean_w, 2), "samples": len(meter.samples),
           "exact": now == orig, "line_now": now, "suite_green": suite.returncode == 0,
           "suite": (suite.stdout.strip().splitlines() or [""])[-1],
           "winner": win.group(1) if win else None,
           "stages": [l.strip() for l in text.splitlines() if re.match(r"^\s{2}\S", l) and re.search(r"\d+\.\ds\s", l)],
           "arm": arm}
    if arm == "lead":
        rec.update(lead=lead_info[0], ai_secs=lead_info[1], ai_tokens=lead_info[2], ai_source="the race's recorded run")
    if arm == "live":
        bt = [int(m.replace(",", "")) for m in re.findall(r"body: point at the fault.*?([\d,]+) tokens", text)]
        bs = [float(m) for m in re.findall(r"body: point at the fault\s+([\d.]+)s", text)]
        rec.update(ai_tokens=sum(bt) if bt else None, ai_secs=sum(bs) if bs else None,
                   lead=re.findall(r"LEAD: (\S+)", text)[:3], ai_source="live, this machine, tools denied")
    OUT.parent.mkdir(exist_ok=True)
    with open(OUTS[arm], "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--arm", choices=list(OUTS), default="alone")
    a = ap.parse_args(argv)
    ids = [6764] if a.pilot else list(BUGS)
    done = set()
    if a.all and OUTS[a.arm].exists():
        done = {json.loads(l)["id"] for l in open(OUTS[a.arm]) if l.strip()}
    for bid in ids:
        if bid in done:
            continue
        idle = idle_baseline()
        print(f"  bug {bid}: idle {idle/1000:.2f} W - running fluidnet watch ...", flush=True)
        r = run(bid, idle, a.arm)
        print("  " + json.dumps({k: r[k] for k in ("id", "at", "secs", "cpu_s", "joules_total", "joules_above_idle",
                                                   "mean_w", "exact", "suite_green", "winner")}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

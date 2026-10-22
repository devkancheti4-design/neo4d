"""neo4d_full on a local checkout with a scripted model: PICK orders the trials, SHIP decides the green ones, the memory
(RELATE v2) learns only single-line fixes and survives a restart."""
import subprocess

from neo4d import swe_agent as S
from neo4d import swe_full as F

BUGGY = "def gcd(a, b):\n    if b == 1:\n        return a\n    return gcd(b, a % b)\n"
TESTS = "import sys\nsys.path.insert(0, '.')\nfrom gcd import gcd\n\n\ndef test_same():\n    assert gcd(7, 7) == 7\n"
ISSUE = "`gcd(17, 0)` raises ZeroDivisionError instead of returning 17; `gcd` should stop when b is 0."
REPRO = ("import sys\nsys.path.insert(0, '.')\nfrom gcd import gcd\nassert gcd(17, 0) == 17\nassert gcd(35, 21) == 7\n"
         "assert gcd(5, 1) == 1\n")


def fake(model, prompt, temperature, seed, traj, predict=2048):
    if "Which ONE file" in prompt:
        reply = "gcd.py"
    elif "REPRODUCES" in prompt:
        reply = f"```python\n{REPRO}```"
    else:
        reply = "gcd.py\n<<<<<<< SEARCH\n    return gcd(b, a % b)\n=======\n    return gcd(b, a % b)  # unchanged\n>>>>>>> REPLACE"
    traj.append(dict(kind="model", prompt=prompt, response=reply))
    return reply


def checkout(tmp_path):
    (tmp_path / "gcd.py").write_text(BUGGY)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_gcd.py").write_text(TESTS)
    for cmd in ("git init -q", "git add .", "git -c user.email=t@t -c user.name=t commit -qm init"):
        subprocess.run(cmd, shell=True, cwd=tmp_path, check=True)
    return S.LocalEnv(tmp_path)


def test_laws_are_what_the_kernels_say():
    assert F.ship(F.WAS_RED | F.GREEN | F.STABLE | F.UNIQUE | F.ROUTED) == F.SHIP
    assert F.ship(F.WAS_RED | F.GREEN | F.STABLE | F.ROUTED) == F.ASK                 # two greens: ask
    assert F.ship(F.WAS_RED | F.GREEN | F.STABLE | F.UNIQUE | F.THIN | F.ROUTED) == F.ASK  # thin evidence: ask
    assert F.ship(F.GREEN | F.STABLE | F.UNIQUE | F.ROUTED) == F.REFUSE              # nothing to repair
    assert F.pick(1 | 1 << 1) >= 1 and F.pick(1) == 0                                 # a line never run is vetoed
    assert F.pick(1 | 1 << 1 | 1 << 3) > F.pick(1 | 1 << 1 | 1 << 4 | 1 << 5)        # one strong beats weak ones


def test_neo4d_full_fixes_a_one_token_bug_before_the_model(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "generate", fake)
    inst = dict(instance_id="t__gcd-2", repo="t/gcd", version="0", problem_statement=ISSUE)
    lessons = []
    diff, traj = S.solve(checkout(tmp_path), inst, "fake", "neo4d_full", rounds=2, memory=F.Memory(F.relate_v2()),
                         lessons=lessons)
    search = [e for e in traj if e["kind"] == "neo4d_search"]
    assert search and search[0]["tried"] > 0 and search[0]["executed_lines"] >= 2
    assert next(e for e in traj if e["kind"] == "regression")["passes_before"]
    assert "b == 0" in diff and "b == 1" not in diff.replace("-    if b == 1", "")
    assert sum(e["kind"] == "model" for e in traj) == 2             # localise + reproduce; no fix round was needed
    assert lessons and lessons[0][2].count("b == 0") == 1


def test_memory_learns_single_line_fixes_and_restarts(tmp_path):
    m = F.Memory(F.relate_v2())
    good = BUGGY.replace("b == 1", "b == 0")
    assert m.learn_fix("t/gcd", BUGGY, good)
    assert not m.learn_fix("t/gcd", BUGGY, good + "x = 1\n")         # two lines changed: not a pattern
    m.save(tmp_path / "memory.pkl")
    again = F.Memory.load(tmp_path / "memory.pkl")
    assert dict(again.level) == dict(m.level) and again.law is not None


def test_marks_go_on_numbered_lines():
    shown = "    1  def f():\n    2      return 1\n  ...\n"
    assert F.mark(shown, [1]).split("\n")[1].endswith(F.MARK) and F.MARK not in F.mark(shown, [1]).split("\n")[0]

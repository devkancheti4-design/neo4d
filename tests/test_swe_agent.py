"""The SWE-bench agent's control flow, on a local checkout with a scripted model: a near-miss patch is rescued by
neo4d's mutations and not by the model alone; edits with copied line numbers still apply."""
import subprocess

from neo4d import swe_agent as S

BUGGY = "def gcd(a, b):\n    if b == 0:\n        return a\n    else:\n        return gcd(a % b, b)\n"
ISSUE = "Calling `gcd(17, 0)` works but `gcd(35, 21)` raises RecursionError; `gcd_fix` should use (b, a % b)."
REPRO = "import sys\nsys.path.insert(0, '.')\nfrom gcd import gcd\nassert gcd(17, 0) == 17\nassert gcd(35, 21) == 7\n"
PATCH = ("gcd.py\n<<<<<<< SEARCH\n    if b == 0:\n        return a\n    else:\n        return gcd(a % b, b)\n=======\n"
         "    if b == 1:\n        return a\n    else:\n        return gcd(b, a % b)\n>>>>>>> REPLACE")


def fake(model, prompt, temperature, seed, traj, predict=2048):
    if "Which ONE file" in prompt:
        reply = "gcd.py"
    elif "REPRODUCES" in prompt:
        reply = f"```python\n{REPRO}```"
    else:
        reply = PATCH                      # right direction (argument order), one slip (b == 1)
    traj.append(dict(kind="model", prompt=prompt, response=reply))
    return reply


def checkout(tmp_path):
    (tmp_path / "gcd.py").write_text(BUGGY)
    for cmd in ("git init -q", "git add .", "git -c user.email=t@t -c user.name=t commit -qm init"):
        subprocess.run(cmd, shell=True, cwd=tmp_path, check=True)
    return S.LocalEnv(tmp_path)


def test_neo4d_rescues_a_near_miss_the_model_alone_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "generate", fake)
    inst = dict(instance_id="t__gcd-1", repo="t/gcd", version="0", problem_statement=ISSUE)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    diff_neo, traj = S.solve(checkout(a), inst, "fake", "neo4d", rounds=2)
    assert any(e["kind"] == "neo4d" and e["shipped"] for e in traj)
    assert "gcd(b, a % b)" in diff_neo and "b == 1" not in diff_neo
    env = checkout(b)
    diff_model, _ = S.solve(env, inst, "fake", "model", rounds=2)
    assert "b == 1" in diff_model                 # the slip stays: the reproduction still fails
    assert env.py(env.repro)[0] != 0


def test_edits_with_copied_line_numbers_still_apply():
    text = "x = 1\ny = 2\n"
    assert S.apply_edit(text, "    2  y = 2", "    2  y = 3") == "x = 1\ny = 3\n"
    assert S.edits_of("/testbed/pkg/m.py\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE")[0][0] == "pkg/m.py"
    assert S.image_of("django__django-11099", "swebench/sweb.eval.x86_64.{id}:latest") == \
        "swebench/sweb.eval.x86_64.django_1776_django-11099:latest"

"""The harnesses behind the local-model and Claude experiments: tasks are judged right, plans transfer, neo4d's
mutations find a fix around a model's attempt."""
import json
from collections import defaultdict

import pytest

from neo4d import local_agent as A
from neo4d import local_hints as H
from neo4d import local_model as LM

pytestmark = pytest.mark.skipif(not LM.QB.exists(), reason="needs bench/QuixBugs (scripts/fetch_bench.sh)")


@pytest.fixture(scope="module")
def tasks():
    meta = A.build_project()
    return A.make_tasks(meta)


def run(task, actions):
    sb = A.Sandbox(task)
    trace = [(a, sb.act(a), sb.files) for a in actions]
    ok = A.accepted(task, sb)
    sb.close()
    return trace, ok


def rename(f, g):
    return [{"tool": "replace", "path": f"qb/{f}.py", "old": f + "(", "new": g + "("},
            {"tool": "replace", "path": f"tests/test_{f}.py", "old": f"import {f}", "new": f"import {g}"},
            {"tool": "replace", "path": f"tests/test_{f}.py", "old": f + "(", "new": g + "("},
            {"tool": "test"}, {"tool": "done"}]


def test_no_task_is_accepted_before_any_work(tasks):
    for t in tasks:
        sb = A.Sandbox(t)
        assert not A.accepted(t, sb), t["text"]
        sb.close()


def test_a_learned_plan_transfers_to_other_tasks_phrased_the_same_way(tasks):
    renames = [t for t in tasks if t["kind"] == "rename function"]
    first = renames[0]
    trace, ok = run(first, rename(*A.slots_of(first["text"])))
    assert ok
    plan = A.abstract(trace, A.slots_of(first["text"]))
    assert any("⟨1⟩" in s for s in plan) and not any('"write": true' in s for s in plan)
    same = [t for t in renames[1:] if A.skeleton(t["text"]) == A.skeleton(first["text"])]
    assert same and all(A.replay(plan, t, None, defaultdict(int))[1] for t in same)


def test_names_are_templated_in_code_paths_and_patterns():
    assert A.abstract_str(r"\benumerate\(", ["qb/", "enumerate"], regex=True) == r"\b⟨2⟩\("
    assert A.abstract_str("tests/test_wrap.py", ["wrap"], path=True) == "tests/test_⟨1⟩.py"
    assert A.abstract_str("wrap(x) + wrap_impl", ["wrap", "wrap_impl"]) == "⟨1⟩(x) + ⟨2⟩"


def test_neo4d_finds_the_fix_one_change_from_a_models_attempt():
    expr = LM.json_programs()["gcd"]
    good = (LM.QB / "correct_python_programs" / "gcd.py").read_text()
    cases = [json.loads(l) for l in (LM.QB / "json_testcases" / "gcd.json").read_text().splitlines() if l.strip()]
    cases = [c for c in cases if LM.run(good, expr, [c], 1.5)[0]]
    attempt = "def gcd(a, b):\n    if b == 1:\n        return a\n    else:\n        return gcd(b, a % b)\n"
    bug = dict(name="gcd", expr=expr, src=attempt, cases=cases)
    assert not all(ok for ok, _ in H.run_all(attempt, expr, cases))
    var, base, _ = H.explore(bug, attempt)
    assert var and all(ok for ok, _ in H.run_all(var, expr, cases))

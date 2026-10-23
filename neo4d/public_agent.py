"""Public repositories: does neo4d cut a large model's calls on the everyday work of a coding agent?

THE PROJECTS. Three public, pure-Python repositories at fixed commits, each with its own pytest suite (bench/public,
fetched by `--fetch`): boltons, click and toolz. The one test that needs an installed package's metadata (click's
test_deprecations.py, toolz's test_has_version) is left out, so the suite passes on a plain checkout.

THE WORK. The six kinds of neo4d/local_agent.py, made from each repository's own code, accepted only by a check - the
repository's test suite, plus a check of the result itself:

    rename function     a top-level function whose name is used nowhere else; every reference in the package and tests
    rename parameter    the first parameter of a top-level function (never passed by keyword); every use inside it
    add parameter       a keyword parameter with a default, last
    count               how many of the package's modules use a keyword in code (docstrings and comments do not count)
    who calls           which of the package's modules call a built-in
    fix a bug           a top-level function broken by neo4d's mutation teacher, so that the suite fails

The tasks of the three repositories run as one seeded stream: a plan learned on one repository may be replayed on
another (the RELATE v2 law's NEWNET is a module or a repository it was not seen on).

THE SOLVERS
    model alone        the model is the agent: one JSON action per turn, at most 12 actions, one try
    neo4d + model      neo4d runs a trusted plan for this kind of task first (local_agent's plans and Brain, unchanged);
                       the model is asked only for the steps a plan cannot fill; otherwise the model works as above

Large models: an ollama model (`--model qwen2.5-coder:32b`, on a GPU), and Claude run as subagents through
`--agent-start` / `--agent-act`, scored afterwards with `--agent-score` (neo4d replays its plans in stream order; the
model's own recorded work counts for every other task).

    python -m neo4d.public_agent --fetch                                        clone the three repositories
    python -m neo4d.public_agent --model qwen2.5-coder:32b --solver "model alone"
    python -m neo4d.public_agent --model qwen2.5-coder:32b --solver "neo4d + model"
    python -m neo4d.public_agent --report qwen2.5-coder:32b                     -> results/PUBLIC_AGENT.md
"""
from __future__ import annotations

import ast
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

from neo4d import KERNELS, REPO
from neo4d import domain_mutation as D
from neo4d import local_agent as LA
from neo4d import local_model as LM
from neo4d import relate_live as RL
from neo4d import relations as R

PUBLIC = REPO / "bench" / "public"
BUILD = REPO / ".build"
RUNS = BUILD / "public_runs"
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/generate"
MAX_STEPS, PER, READ_LINES = 12, 6, 150
# name: (GitHub repository, commit, package directory, import root for PYTHONPATH, tests directory, extra pytest arguments)
REPOS = {
    "boltons": ("mahmoud/boltons", "4e5faa3", "boltons", ".", "tests", []),
    "click": ("pallets/click", "2247b35", "src/click", "src", "tests", ["--ignore=tests/test_deprecations.py"]),
    "toolz": ("pytoolz/toolz", "451af60", "toolz", ".", "toolz/tests",
              ["--deselect", "toolz/tests/test_package.py::test_has_version"]),
}

SYSTEM = """You are a coding agent working in a copy of the public Python repository {name}, using tools. Each turn, \
reply with exactly ONE JSON object - the next action - and nothing else.

Tools:
{{"tool": "ls", "path": "<directory>"}}                                list a directory
{{"tool": "read", "path": "<file>", "start": <line>}}                    show {lines} lines of a file from line <start> (default 1)
{{"tool": "grep", "pattern": "<regex>", "path": "<directory or file>"}}   search; path "." searches the whole project
{{"tool": "replace", "path": "<file>", "old": "<exact text>", "new": "<new text>"}}   replace every occurrence in that file
{{"tool": "write", "path": "<file>", "content": "<text>"}}             create or overwrite a file
{{"tool": "test"}}                                                     run the repository's test suite
{{"tool": "done"}}                                                     finish the task

The project: the package is in {pkg}/, its tests in {tests}/.
"""

PHRASES = {
    "rename function": ("Rename the function `{f}` (defined in `{path}`) to `{g}` everywhere in the project, and make "
                        "sure the tests still pass.",
                        "Change the name of `{f}` in `{path}` to `{g}` - its definition and every place that uses it - "
                        "keeping all tests passing."),
    "rename parameter": ("In the function `{f}` in `{path}`, rename the parameter `{p}` to `{q}`, including every use "
                         "inside the function.",
                         "The parameter `{p}` of `{f}` (in `{path}`) should be called `{q}`; rename it and all its uses."),
    "add parameter": ("Add a keyword parameter `{p}` with default value `{v}` as the last parameter of `{f}` in `{path}`.",
                      "Give `{f}` in `{path}` a new last parameter `{p}` that defaults to `{v}`; behaviour must not "
                      "change."),
    "count": ("How many modules directly in `{pkg}/` use the keyword `{k}` in their code (docstrings and comments do not "
              "count)? Write only the number to `answer.txt`.",
              "Count the modules directly under `{pkg}/` whose code contains the keyword `{k}` (ignore docstrings and "
              "comments) and write the count to `answer.txt`."),
    "who calls": ("Which modules directly in `{pkg}/` call the built-in `{b}`? Write their module names, one per line, "
                  "to `answer.txt`.",
                  "List every module directly under `{pkg}/` that calls `{b}` - one module name per line - in "
                  "`answer.txt`."),
    "fix a bug": ("A test fails because of a bug in the function `{f}` in `{path}`. Fix the bug so that all tests pass.",
                  "Something in `{f}` (in `{path}`) is broken and the test suite fails; find the bug and fix it."),
}


# ------------------------------------------------------------------------------------------------ the projects

def fetch():
    PUBLIC.mkdir(parents=True, exist_ok=True)
    for name, (gh, commit, *_ ) in REPOS.items():
        d = PUBLIC / name
        if not d.exists():
            subprocess.run(["git", "clone", "-q", f"https://github.com/{gh}.git", str(d)], check=True)
        subprocess.run(["git", "-C", str(d), "checkout", "-q", commit], check=True)
        print(name, subprocess.run(["git", "-C", str(d), "rev-parse", "--short", "HEAD"], capture_output=True,
                                   text=True).stdout.strip())


def modules(name, root=None):
    """The package's own modules, directly in its directory (not tests, not subpackages)."""
    root = Path(root or PUBLIC / name)
    pkg = root / REPOS[name][2]
    return sorted(p for p in pkg.glob("*.py") if p.name != "__init__.py")


def suite(name, root):
    """Run the repository's test suite on a working copy. -> (all pass, tail of the output)"""
    _, _, _, imp, tests, extra = REPOS[name]
    env = dict(os.environ, PYTHONPATH=str(Path(root) / imp), PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *extra], cwd=root,
                           capture_output=True, text=True, timeout=180, env=env)
        return r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    except subprocess.TimeoutExpired:
        return False, "the test suite timed out"


class Sandbox:
    """A fresh copy of one repository for one piece of work; the agent's tools act on it."""

    def __init__(self, task):
        self.name = task["repo"]
        self.dir = Path(tempfile.mkdtemp(prefix="public_")).resolve()
        shutil.copytree(PUBLIC / self.name, self.dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
        for rel, text in task.get("setup", {}).items():
            (self.dir / rel).write_text(text)
        self.files = None
        self.test_runs = 0

    @classmethod
    def attach(cls, path, name):
        sb = cls.__new__(cls)
        sb.dir, sb.name, sb.files, sb.test_runs = Path(path).resolve(), name, None, 0
        return sb

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def path(self, p):
        q = (self.dir / str(p).strip().lstrip("/")).resolve()
        if not str(q).startswith(str(self.dir)):
            raise ValueError("path outside the project")
        return q

    def act(self, a):
        t = a.get("tool")
        self.files = None
        try:
            if t == "ls":
                q = self.path(a.get("path", "."))
                return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in q.iterdir()
                                        if x.name not in ("__pycache__", ".git")))
            if t == "read":
                lines = self.path(a["path"]).read_text().split("\n")
                s = max(1, int(a.get("start", 1) or 1))
                part = lines[s - 1:s - 1 + READ_LINES]
                more = f"\n... ({len(lines)} lines in all)" if s - 1 + READ_LINES < len(lines) else ""
                return "\n".join(f"{s + i:5d}  {l}" for i, l in enumerate(part)) + more
            if t == "grep":
                rx = re.compile(a["pattern"])
                base = self.path(a.get("path") or ".")
                paths = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.suffix in (".py", ".txt")
                                                             and "__pycache__" not in p.parts and ".git" not in p.parts)
                out, files = [], []
                for p in paths:
                    rel = str(p.relative_to(self.dir))
                    for i, line in enumerate(p.read_text(errors="replace").split("\n"), 1):
                        if rx.search(line):
                            out.append(f"{rel}:{i}: {line.strip()[:120]}")
                            if rel not in files:
                                files.append(rel)
                self.files = files
                more = f"\n... {len(out) - 40} more lines" if len(out) > 40 else ""
                return "\n".join(out[:40]) + more if out else "no matches"
            if t == "replace":
                q = self.path(a["path"])
                s = q.read_text()
                n = s.count(a["old"]) if a.get("old") else 0
                if n:
                    q.write_text(s.replace(a["old"], a.get("new", "")))
                return f"replaced {n} occurrence(s)" if n else "not found: nothing replaced"
            if t == "write":
                q = self.path(a["path"])
                q.parent.mkdir(parents=True, exist_ok=True)
                q.write_text(str(a.get("content", "")))
                return "written"
            if t == "test":
                self.test_runs += 1
                return suite(self.name, self.dir)[1]
            if t == "done":
                return "done"
            return f"unknown tool {t!r}"
        except Exception as e:                                   # noqa: BLE001 - the agent sees whatever went wrong
            return f"error: {type(e).__name__}: {e}"[:300]

    def tests_pass(self):
        self.test_runs += 1
        return suite(self.name, self.dir)[0]


# ---------------------------------------------------------------------------------------------------- the tasks

def identifiers(root, name):
    """Every identifier occurrence in the repository's Python files (package and tests): name -> count."""
    out = defaultdict(int)
    for p in Path(root).rglob("*.py"):
        if ".git" in p.parts or "docs" in p.parts or "examples" in p.parts:
            continue
        try:
            for n in ast.walk(ast.parse(p.read_text())):
                if isinstance(n, ast.Name):
                    out[n.id] += 1
                elif isinstance(n, ast.Attribute):
                    out[n.attr] += 1
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    out[n.name] += 1
                elif isinstance(n, ast.alias):
                    out[n.asname or n.name.split(".")[-1]] += 1
                elif isinstance(n, ast.arg):
                    out[n.arg] += 1
        except SyntaxError:
            pass
    return out


def defs_of(root):
    """Every function, class and assignment target name defined anywhere: name -> count."""
    out = defaultdict(int)
    for p in Path(root).rglob("*.py"):
        if ".git" in p.parts:
            continue
        try:
            for n in ast.walk(ast.parse(p.read_text())):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    out[n.name] += 1
                elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    out[n.id] += 1
                elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store):
                    out[n.attr] += 1
        except SyntaxError:
            pass
    return out


def top_functions(path):
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return []
    return [n for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]


def tested_names(name):
    text = "\n".join(p.read_text(errors="replace") for p in (PUBLIC / name / REPOS[name][4]).rglob("*.py"))
    return set(re.findall(r"[A-Za-z_]\w*", text))


def make_tasks(seed=2026, per=PER):
    rng = random.Random(seed)
    tasks = []

    def add(kind, repo, net, check, setup=None, **kw):
        tasks.append(dict(kind=kind, repo=repo, net=f"{repo}/{net}", check=check, setup=setup or {},
                          text=rng.choice(PHRASES[kind]).format(**kw)))

    for name in REPOS:
        root = PUBLIC / name
        pkg = REPOS[name][2]
        mods = modules(name)
        ids, defs, tested = identifiers(root, name), defs_of(root), tested_names(name)
        funcs = []                       # (module path, function node) - a name defined once, used in the tests
        for m in mods:
            for f in top_functions(m):
                if defs[f.name] == 1 and len(f.name) >= 5 and f.name in tested:
                    funcs.append((m, f))
        rel = lambda m: str(m.relative_to(root))
        for m, f in rng.sample(funcs, min(per, len(funcs))):
            g = rng.choice(("compute_{f}", "{f}_impl", "run_{f}", "{f}_v2")).format(f=f.name)
            add("rename function", name, f.name, ("rename function", rel(m), f.name, g), f=f.name, g=g, path=rel(m))
        texts = {m: m.read_text() for m in mods}
        alltext = "\n".join(q.read_text(errors="replace") for q in root.rglob("*.py") if ".git" not in q.parts)
        params = []
        for m, f in funcs:
            args = [a.arg for a in f.args.args]
            # never passed by keyword: `p=` appears only in the function's own signature (its defaults)
            if args and args[0] not in ("self", "cls") and len(re.findall(rf"\b{args[0]}\s*=(?!=)", alltext)) <= 1:
                params.append((m, f, args[0]))
        for m, f, p in rng.sample(params, min(per, len(params))):
            q = rng.choice(("{p}_in", "input_{p}", "{p}_value")).format(p=p)
            add("rename parameter", name, f.name, ("rename parameter", rel(m), f.name, p, q), f=f.name, p=p, q=q, path=rel(m))
        plain = [(m, f) for m, f in funcs if not (f.args.vararg or f.args.kwarg or f.args.kwonlyargs or f.args.posonlyargs)]
        for m, f in rng.sample(plain, min(per, len(plain))):
            p, v = rng.choice((("verbose", "False"), ("debug", "False"), ("strict", "True"), ("limit", "None"),
                               ("trace", "False")))
            if p in [a.arg for a in f.args.args]:
                continue
            add("add parameter", name, f.name, ("add parameter", rel(m), f.name, p, v), f=f.name, p=p, v=v, path=rel(m))
        names = {m.stem: m for m in mods}
        counts = {k: sum(k in LA.code_names(texts[m]) for m in mods) for k in LA.KEYWORDS}
        usable = [k for k in LA.KEYWORDS if 0 < counts[k] < len(mods)]
        for k in rng.sample(usable, min(per, len(usable))):
            add("count", name, k, ("count", counts[k]), k=k, pkg=pkg)
        callers = {}
        for b in LA.BUILTINS:
            callers[b] = sorted(s for s, m in names.items() if b in calls_safe(texts[m]))
        usable = [b for b in LA.BUILTINS if 0 < len(callers[b]) < len(mods)]
        for b in rng.sample(usable, min(per, len(usable))):
            add("who calls", name, b, ("who calls", callers[b]), b=b, pkg=pkg)
        bugs = []
        cands = [(m, f) for m, f in funcs]
        rng.shuffle(cands)
        for m, f in cands:
            if len(bugs) >= per:
                break
            lines = texts[m].split("\n")
            body = [i for i in LM.code_lines(texts[m]) if f.lineno < i + 1 <= f.end_lineno]
            muts = [(li, LM.to_text(lines[li], list(mu))) for li in body for mu in D.mutants(R.toks(lines[li]))]
            rng.shuffle(muts)
            for li, bad in muts[:6]:
                if bad == lines[li]:
                    continue
                buggy = "\n".join(lines[:li] + [bad] + lines[li + 1:])
                try:
                    ast.parse(buggy)
                except SyntaxError:
                    continue
                sb = Sandbox(dict(repo=name, setup={rel(m): buggy}))
                ok = sb.tests_pass()
                sb.close()
                if not ok:
                    bugs.append((m, f, buggy))
                    break
        for m, f, buggy in bugs:
            add("fix a bug", name, f.name, ("fix a bug", rel(m), f.name), setup={rel(m): buggy}, f=f.name, path=rel(m))
    good = [t for t in tasks if solvable(t)]
    print(f"{len(tasks)} tasks made, {len(tasks) - len(good)} dropped: their gold solution was not accepted", flush=True)
    rng.shuffle(good)
    for i, t in enumerate(good):
        t["id"] = i
    return good


def gold(task, sb):
    """Apply a correct solution mechanically - every task must be solvable and its check must agree."""
    kind, root = task["check"][0], sb.dir
    if kind == "count":
        (root / "answer.txt").write_text(str(task["check"][1]))
    elif kind == "who calls":
        (root / "answer.txt").write_text("\n".join(task["check"][1]))
    elif kind == "fix a bug":
        path = task["check"][1]
        (root / path).write_text((PUBLIC / task["repo"] / path).read_text())
    elif kind == "rename function":
        f, g = task["check"][2], task["check"][3]
        for q in root.rglob("*.py"):
            t = q.read_text(errors="replace")
            new = re.sub(rf"\b{f}\b", g, t)
            if new != t:
                q.write_text(new)
    else:
        path, f = task["check"][1], task["check"][2]
        src = (root / path).read_text()
        fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == f)
        lines = src.split("\n")
        if kind == "rename parameter":
            p, q = task["check"][3:]
            for i in range(fn.lineno - 1, fn.end_lineno):
                lines[i] = re.sub(rf"\b{p}\b", q, lines[i])
        else:
            p, v = task["check"][3:]
            last = (fn.args.defaults or fn.args.args)[-1] if fn.args.args else None
            if last is None:
                i = fn.lineno - 1
                lines[i] = lines[i].replace(f"def {f}(", f"def {f}({p}={v}", 1)
            else:
                i, c = last.end_lineno - 1, last.end_col_offset
                lines[i] = lines[i][:c] + f", {p}={v}" + lines[i][c:]
        (root / path).write_text("\n".join(lines))


def solvable(task):
    sb = Sandbox(task)
    try:
        gold(task, sb)
        return accepted(task, sb)
    except Exception:                                           # noqa: BLE001 - a task that cannot be solved is dropped
        return False
    finally:
        sb.close()


def calls_safe(src):
    try:
        return LA.calls_of(src)
    except SyntaxError:
        return set()


def accepted(task, sb):
    kind = task["check"][0]
    try:
        if kind == "count":
            return (sb.dir / "answer.txt").read_text().strip() == str(task["check"][1])
        if kind == "who calls":
            got = {Path(l.strip()).stem for l in (sb.dir / "answer.txt").read_text().split("\n") if l.strip()}
            return got == set(task["check"][1])
        if not sb.tests_pass():
            return False
        if kind == "fix a bug":
            return True
        path, f = task["check"][1], task["check"][2]
        mod = (sb.dir / path).read_text()
        if kind == "rename function":
            g = task["check"][3]
            if identifiers(sb.dir, task["repo"]).get(f):
                return False
            return any(isinstance(n, ast.FunctionDef) and n.name == g for n in ast.parse(mod).body)
        fn = next(n for n in ast.parse(mod).body if isinstance(n, ast.FunctionDef) and n.name == f)
        orig = [a.arg for a in next(n for n in ast.parse((PUBLIC / task["repo"] / path).read_text()).body
                                    if isinstance(n, ast.FunctionDef) and n.name == f).args.args]
        names = [a.arg for a in fn.args.args]
        if kind == "rename parameter":
            p, q = task["check"][3:]
            uses = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            return names == [q if a == p else a for a in orig] and p not in uses
        if kind == "add parameter":
            p, v = task["check"][3:]
            d = fn.args.defaults
            return names == orig + [p] and bool(d) and isinstance(d[-1], ast.Constant) and d[-1].value == ast.literal_eval(v)
    except Exception:                                           # noqa: BLE001 - a broken result is not accepted
        return False
    return False


# -------------------------------------------------------------------------------------------------- the model

def generate(model, prompt, temperature, seed, stats):
    stats["model calls"] += 1
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": temperature, "seed": seed, "num_predict": 900, "num_ctx": 16384,
                                   "stop": ["\nResult"]}}).encode()
    for wait in (2, 5, 10, 30, None):
        try:
            req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=900) as r:
                d = json.loads(r.read())
            stats["prompt tokens"] += d.get("prompt_eval_count", 0)
            stats["output tokens"] += d.get("eval_count", 0)
            stats["model seconds"] += d.get("total_duration", 0) / 1e9
            return d["response"]
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if wait is None:
                stats["model errors"] += 1
                return ""
            time.sleep(wait)


def system(task):
    name = task["repo"]
    return SYSTEM.format(name=name, pkg=REPOS[name][2], tests=REPOS[name][4], lines=READ_LINES)


def episode(model, task, temperature, seed, stats):
    sb = Sandbox(task)
    trace = []
    try:
        for step in range(MAX_STEPS):
            prompt = (system(task) + f"\nTask: {task['text']}\n\n"
                      + "".join(f"Action: {json.dumps(a)}\nResult:\n{obs}\n\n" for a, obs, _ in trace) + "Action:")
            a = LA.parse_action(generate(model, prompt, temperature, seed + step, stats))
            stats["model actions"] += 1
            if a is None:
                trace.append(({"tool": "invalid"}, "Reply with exactly one JSON object.", None))
                continue
            obs = sb.act(a)
            trace.append((a, obs, sb.files))
            if a.get("tool") == "done":
                break
        ok = accepted(task, sb)
        stats["test runs"] += sb.test_runs
        return trace, ok
    finally:
        sb.close()


def write_step(model, task, step, sb, temperature, stats):
    """A step the plan cannot fill: the model writes it - it sees the task, the file, and the action to complete."""
    path = step["path"]
    shown = sb.act({"tool": "read", "path": path}) if step["tool"] == "replace" else ""
    test = sb.act({"tool": "test"}) if task["kind"] == "fix a bug" else ""
    form = ('{"tool": "replace", "path": "%s", "old": "exact text", "new": "new text"}' % path if step["tool"] == "replace"
            else '{"tool": "write", "path": "%s", "content": "text"}' % path)
    prompt = (system(task) + f"\nTask: {task['text']}\n\n"
              + (f"Action: {json.dumps({'tool': 'test'})}\nResult:\n{test}\n\n" if test else "")
              + (f"Action: {json.dumps({'tool': 'read', 'path': path})}\nResult:\n{shown}\n\n" if shown else "")
              + f"The next action is a {step['tool']} in {path}, of the form {form}.\nAction:")
    a = LA.parse_action(generate(model, prompt, temperature, 3000, stats)) or {}
    a.update(tool=step["tool"], path=path)
    return a


def replay(plan, task, model, stats, temperature=0.0):
    """Run a plan on a fresh copy (local_agent.replay on a public repository). -> (trace, accepted)"""
    slots = LA.slots_of(task["text"])
    sb = Sandbox(task)
    trace, files = [], None
    try:
        for s in plan:
            step = json.loads(s)
            if step.get("write"):
                if model is None:                      # scoring recorded runs: a plan that needs a model is not run
                    return trace, False
                paths = files if step["path"] == "⟨GREP⟩" else [LA.fill(step["path"], slots)]
                for p in (paths or [])[:3]:
                    a = write_step(model, task, dict(step, path=p), sb, temperature, stats)
                    trace.append((a, sb.act(a), None))
                continue
            stats["neo4d actions"] += 1
            a = {k: LA.fill(v, slots) for k, v in step.items()}
            if a.get("content") in LA.DERIVED:
                fs = files or []
                a["content"] = {"⟨GREPCOUNT⟩": str(len(fs)), "⟨GREPFILES⟩": "\n".join(fs),
                                "⟨GREPMODULES⟩": "\n".join(Path(f).stem for f in fs)}[a["content"]]
            if a.get("path") == "⟨GREP⟩":
                for p in files or []:
                    b = dict(a, path=p)
                    trace.append((b, sb.act(b), None))
                continue
            obs = sb.act(a)
            if a["tool"] == "grep":
                files = sb.files
            trace.append((a, obs, sb.files))
        ok = accepted(task, sb)
        stats["test runs"] += sb.test_runs
        return trace, ok
    finally:
        sb.close()


# ---------------------------------------------------------------------------------------------------- solvers

def solve(solver, model, tasks, law):
    stats = defaultdict(float)
    brain = LA.Brain(law)
    rows = []
    t0 = time.time()
    for n, task in enumerate(tasks):
        before = dict(stats)
        how, trace, tried, shadow = None, None, {}, {}
        if solver == "neo4d + model":
            for plan in brain.ranked(task["text"], 2, 3)[:2]:
                tr, ok = replay(plan, task, model, stats)
                tried[plan] = ok
                if ok:
                    how, trace = "neo4d", tr
                    break
        if how is None:
            tr, ok = episode(model, task, 0.0, 1000, stats)
            if ok:
                how, trace = "model", tr
        if solver == "neo4d + model":
            for plan in [p for p in brain.ranked(task["text"], 1, 1) if p not in tried][:2]:
                if '"write": true' not in "".join(plan):
                    shadow[plan] = replay(plan, task, model, defaultdict(float))[1]
            brain.learn(task, trace, tried, shadow)
        d = lambda k: stats[k] - before.get(k, 0)
        rows.append(dict(id=task["id"], kind=task["kind"], repo=task["repo"], ok=how is not None, how=how,
                         calls=d("model calls"), prompt_tokens=d("prompt tokens"), output_tokens=d("output tokens"),
                         model_seconds=round(d("model seconds"), 1), test_runs=d("test runs"),
                         neo_actions=d("neo4d actions"), model_actions=d("model actions")))
        if (n + 1) % 10 == 0:
            print(f"  {solver}: {n + 1}/{len(tasks)} accepted {sum(r['ok'] for r in rows)} calls {stats['model calls']:.0f} "
                  f"({time.time() - t0:.0f}s)", flush=True)
    return rows


def store(model, solver):
    return BUILD / f"public_{model.replace(':', '_').replace('/', '_')}_{solver.replace(' ', '_').replace('+', 'plus')}.json"


def report(model, tasks):
    res = {s: json.loads(store(model, s).read_text()) for s in ("model alone", "neo4d + model") if store(model, s).exists()}
    n, half = len(tasks), len(tasks) // 2
    tot = lambda rows, k: sum(r[k] for r in rows)
    out = [f"## {model}", "",
           f"{n} tasks on boltons, click and toolz in one seeded stream; one try per task; tools as in local_agent.py "
           f"(reading {READ_LINES} lines at a time), at most {MAX_STEPS} actions.", "",
           "| solver | accepted | second half | tasks the model was needed for | model calls | prompt tokens | output "
           "tokens | model seconds | test-suite runs |", "|---|---|---|---|---|---|---|---|---|"]
    for label, rows in res.items():
        need = sum(r["how"] != "neo4d" for r in rows)
        out.append(f"| {label} | **{tot(rows, 'ok')}/{n}** | {sum(r['ok'] for r in rows[half:])}/{n - half} | {need} | "
                   f"{tot(rows, 'calls'):.0f} | {tot(rows, 'prompt_tokens'):.0f} | {tot(rows, 'output_tokens'):.0f} | "
                   f"{tot(rows, 'model_seconds'):.0f} | {tot(rows, 'test_runs'):.0f} |")
    if len(res) == 2:
        a, b = res["model alone"], res["neo4d + model"]
        out += ["", "| kind | tasks | model alone | neo4d + model | done by neo4d's plan, no model call |", "|---|---|---|---|---|"]
        for kind in PHRASES:
            ks = [i for i, t in enumerate(tasks) if t["kind"] == kind]
            out.append(f"| {kind} | {len(ks)} | {sum(a[i]['ok'] for i in ks)} | {sum(b[i]['ok'] for i in ks)} | "
                       f"{sum(b[i]['how'] == 'neo4d' and b[i]['calls'] == 0 for i in ks)} |")
        out += ["", "| repository | tasks | model alone | neo4d + model | model calls alone / with neo4d |", "|---|---|---|---|---|"]
        for name in REPOS:
            ks = [i for i, t in enumerate(tasks) if t["repo"] == name]
            out.append(f"| {name} | {len(ks)} | {sum(a[i]['ok'] for i in ks)} | {sum(b[i]['ok'] for i in ks)} | "
                       f"{sum(a[i]['calls'] for i in ks):.0f} / {sum(b[i]['calls'] for i in ks):.0f} |")
        both = [(x["ok"], y["ok"]) for x, y in zip(a, b)]
        only_a, only_b = sum(x and not y for x, y in both), sum(y and not x for x, y in both)
        from math import comb
        m = only_a + only_b
        p = min(1.0, 2 * sum(comb(m, k) for k in range(min(only_a, only_b) + 1)) / 2 ** m) if m else 1.0
        out += ["", f"Accepted only with neo4d: {only_b}; only without: {only_a}; exact McNemar p = {p:.3f}."]
    return out


# --------------------------------------------------------------------------------- large models through commands

def agent_cli(args, tasks):
    """A large model as the agent, one action per command - the same tools, the same limit of actions, one try.

    --agent-start RUN ID          a fresh working copy for task ID; prints the task and the tools
    --agent-act RUN ID [ACTION]   one JSON action (argument or stdin) on that copy; prints the result
    """
    by = {t["id"]: t for t in tasks}
    flag = "--agent-start" if "--agent-start" in args else "--agent-act"
    i = args.index(flag)
    run, tid = args[i + 1], int(args[i + 2])
    d = RUNS / run / str(tid)
    task = by[tid]
    if flag == "--agent-start":
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        shutil.copytree(PUBLIC / task["repo"], d / "project", ignore=shutil.ignore_patterns(".git"))
        for rel, text in task["setup"].items():
            (d / "project" / rel).write_text(text)
        (d / "trace.json").write_text("[]")
        print(system(task) + f"\nTask {tid}: {task['text']}\n\nAt most {MAX_STEPS} actions; finish with "
              '{"tool": "done"}.')
        return 0
    trace = json.loads((d / "trace.json").read_text())
    if trace and trace[-1][0].get("tool") == "done":
        print("This task is finished.")
        return 0
    if len(trace) >= MAX_STEPS:
        print("Action limit reached: this task is over.")
        return 0
    raw = args[i + 3] if len(args) > i + 3 else sys.stdin.read()
    a = LA.parse_action(raw)
    if a is None:
        trace.append([{"tool": "invalid"}, "Not a JSON action.", None])
    else:
        sb = Sandbox.attach(d / "project", task["repo"])
        trace.append([a, sb.act(a), sb.files])
    (d / "trace.json").write_text(json.dumps(trace))
    print(trace[-1][1])
    return 0


def agent_score(runs, tasks, law):
    """Large models alone, and neo4d + each: in stream order neo4d runs its trusted plans that need no model call; the
    model's own recorded work counts for every other task, and neo4d learns from it."""
    out = ["## Claude as the agent", "",
           "Claude run as subagents through the same tools, one action per command, at most "
           f"{MAX_STEPS} actions a task, one try (prompt: docs/SUBAGENT_PROMPTS.md, public repositories). neo4d + model: "
           "in stream order, neo4d runs its trusted plans that need no model call; the model's own work counts for every "
           "other task, and neo4d learns from it.", "",
           "| solver | accepted | second half | tasks the large model was needed for | large-model actions |",
           "|---|---|---|---|---|"]
    for run in runs:
        ids = [t["id"] for t in tasks if (RUNS / run / str(t["id"]) / "trace.json").exists()]
        tr = {i: json.loads((RUNS / run / str(i) / "trace.json").read_text()) for i in ids}
        by = {t["id"]: t for t in tasks}
        ok = {i: accepted(by[i], Sandbox.attach(RUNS / run / str(i) / "project", by[i]["repo"])) for i in ids}
        stream = [t for t in tasks if t["id"] in tr]
        half = len(stream) // 2
        brain, stats, rows = LA.Brain(law), defaultdict(float), []
        for t in stream:
            tried, shadow, how, good = {}, {}, None, None
            for plan in [p for p in brain.ranked(t["text"], 2, 3) if '"write": true' not in "".join(p)][:2]:
                trace, a = replay(plan, t, None, stats)
                tried[plan] = a
                if a:
                    how, good = "neo4d", trace
                    break
            if how is None and ok[t["id"]]:
                how, good = "model", [tuple(x) for x in tr[t["id"]]]
            for plan in [p for p in brain.ranked(t["text"], 1, 1) if p not in tried and '"write": true' not in "".join(p)][:2]:
                shadow[plan] = replay(plan, t, None, stats)[1]
            brain.learn(t, good, tried, shadow)
            rows.append(dict(ok=how is not None, need=how != "neo4d", acts=0 if how == "neo4d" else len(tr[t["id"]])))
        alone = [ok[t["id"]] for t in stream]
        n = len(stream)
        out.append(f"| {run} alone | **{sum(alone)}/{n}** | {sum(alone[half:])}/{n - half} | {n} | "
                   f"{sum(len(tr[t['id']]) for t in stream)} |")
        out.append(f"| **neo4d + {run}** | **{sum(r['ok'] for r in rows)}/{n}** | {sum(r['ok'] for r in rows[half:])}/{n - half} | "
                   f"**{sum(r['need'] for r in rows)}** | **{sum(r['acts'] for r in rows)}** |")
    return out


def put(lines, heading):
    p = REPO / "results" / "PUBLIC_AGENT.md"
    head = ("# Public repositories: neo4d beside a large model on a coding agent's everyday work\n\n"
            "Generated by `neo4d/public_agent.py`. The repositories, tasks and checks are described there.")
    parts = p.read_text().rstrip("\n").split("\n## ") if p.exists() else [head]
    body = "\n".join(lines).strip("\n")
    parts = [x for x in parts if not x.startswith(heading)] + [body[3:] if body.startswith("## ") else body]
    p.write_text("\n\n## ".join(x.strip("\n") for x in parts) + "\n")


def main() -> int:
    args = sys.argv[1:]
    if "--fetch" in args:
        fetch()
        return 0
    law = RL.load_law(str(KERNELS / "relate_v2.c"))
    cache = BUILD / "public_tasks.json"
    if cache.exists():
        tasks = json.loads(cache.read_text())
    else:
        tasks = make_tasks()
        cache.write_text(json.dumps(tasks))
    if "--tasks" in args:
        from collections import Counter
        print(len(tasks), "tasks;", dict(Counter(t["kind"] for t in tasks)), dict(Counter(t["repo"] for t in tasks)))
        return 0
    if "--agent-start" in args or "--agent-act" in args:
        return agent_cli(args, tasks)
    if "--agent-score" in args:
        out = agent_score(args[args.index("--agent-score") + 1].split(","), tasks, law)
        put(out, "Claude as the agent")
        print("\n".join(out))
        return 0
    if "--report" in args:
        model = args[args.index("--report") + 1]
        out = report(model, tasks)
        put(out, model)
        print("\n".join(out))
        return 0
    model = args[args.index("--model") + 1]
    solver = args[args.index("--solver") + 1]
    rows = solve(solver, model, tasks, law)
    store(model, solver).write_text(json.dumps(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

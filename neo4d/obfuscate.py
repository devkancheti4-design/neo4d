"""Obfuscate a Python program while keeping its behaviour - for the obfuscation-resistance test.

    rename      every parameter and local variable of every function to a hash name (_0x7e3a9c...), stable per
                original name, so the buggy and correct versions of a program get the same names
    strip       docstrings, comments and formatting (the program is re-emitted from its syntax tree)
    dead code   after every statement in every function body, DEAD dead assignments to fresh hash names (never read)

Untouched, because the outside world calls them by name: module-level names (the function the tests import),
builtins, attribute names, keyword-argument names at call sites, and imported names.
"""
from __future__ import annotations

import ast
import builtins
import hashlib

DEAD = 3


def _hash(name: str, salt: str = "neo4d") -> str:
    return "_0x" + hashlib.sha256(f"{salt}:{name}".encode()).hexdigest()[:10]


class _Locals(ast.NodeVisitor):
    def __init__(self):
        self.names: set[str] = set()

    def visit_FunctionDef(self, node):
        for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
            self.names.add(a.arg)
        for a in (node.args.vararg, node.args.kwarg):
            if a:
                self.names.add(a.arg)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                self.names.add(sub.id)
            elif isinstance(sub, ast.arg) and sub is not node:
                self.names.add(sub.arg)
            elif isinstance(sub, (ast.FunctionDef, ast.Lambda)) and sub is not node:
                pass

    visit_AsyncFunctionDef = visit_FunctionDef


class _Rename(ast.NodeTransformer):
    def __init__(self, names):
        self.names = names

    def visit_Name(self, node):
        if node.id in self.names:
            node.id = _hash(node.id)
        return node

    def visit_arg(self, node):
        if node.arg in self.names:
            node.arg = _hash(node.arg)
        return node

    def visit_Expr(self, node):                      # drop docstrings and other bare string expressions
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        return self.generic_visit(node)


class _Dead(ast.NodeTransformer):
    def __init__(self):
        self.n = 0

    def _pad(self, body):
        out = []
        for stmt in body:
            out.append(stmt)
            for _ in range(DEAD):
                self.n += 1
                out.append(ast.Assign(targets=[ast.Name(id=_hash(f"dead{self.n}", "dead"), ctx=ast.Store())],
                                      value=ast.Constant(value=None), lineno=0))
        return out or [ast.Pass()]

    def generic_visit(self, node):
        super().generic_visit(node)
        for field in ("body", "orelse", "finalbody"):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.For, ast.While, ast.If, ast.With, ast.Try)) \
                    and isinstance(getattr(node, field, None), list) and getattr(node, field):
                setattr(node, field, self._pad(getattr(node, field)))
        return node


def obfuscate(src: str) -> tuple[str, dict]:
    tree = ast.parse(src)
    module_names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))}
    module_names |= {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    imported = {a.asname or a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names}
    loc = _Locals()
    loc.visit(tree)
    names = loc.names - module_names - imported - set(dir(builtins))
    tree = _Rename(names).visit(tree)
    dead = _Dead()
    tree = dead.visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n", {"renamed": len(names), "dead_statements": dead.n}

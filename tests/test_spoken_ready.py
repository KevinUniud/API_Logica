import os
import sys

# Ensure local `python/` package folder is on sys.path for tests
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PY_DIR = os.path.join(ROOT, "python")
sys.path.insert(0, PY_DIR)

from ast_logic import Var, Not, And, Or
import generator


class FakeBridge:
    def to_nnf(self, expr, timeout=10):
        return [expr]

    def expand_implications(self, expr, timeout=10):
        return [expr]


def test_flatten_associative_and():
    a = Var("a")
    b = Var("b")
    c = Var("c")
    expr = And(a, And(b, c))
    prolog, meta = generator.generate_spoken_ready_prolog(expr, bridge=FakeBridge())
    assert "and(" in prolog
    assert "imp(" not in prolog
    assert "flatten_associative" in meta.get("spoken_transformations", [])


def test_simple_factoring_imp():
    a = Var("a")
    b = Var("b")
    expr = Or(Not(a), b)
    prolog, meta = generator.generate_spoken_ready_prolog(expr, bridge=FakeBridge(), try_factor=True)
    assert prolog.strip() == "imp(a,b)"
    assert "factored_imp" in meta.get("spoken_transformations", [])

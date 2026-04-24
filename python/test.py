import unittest
from collections import Counter
import random
from typing import cast

from ast_logic import And, Iff, Imp, Not, Or, Var
from generator import build_ex_depth
from generator import build_logical_consequence_question
from generator import build_tvq
from generator import generate_formula_by_variable_count
from generator import generate_formula
from prolog_bridge import PrologBridge
from prolog_bridge import collect_variables, from_prolog


def _bridge(value):
    return cast(PrologBridge, value)


def _count_atoms(prolog_formula: str) -> int:
    """Conta gli atomi presenti in una formula Prolog."""
    ast = from_prolog(prolog_formula)

    def walk(node):
        if isinstance(node, Var):
            return 1
        if isinstance(node, Not):
            return walk(node.expr)
        if isinstance(node, (And, Or, Imp, Iff)):
            return walk(node.left) + walk(node.right)
        raise TypeError(f"Nodo non supportato: {type(node)!r}")

    return walk(ast)


def _count_atom_repetitions(prolog_formula: str) -> int:
    """Conta le occorrenze ripetute degli atomi in una formula Prolog."""
    ast = from_prolog(prolog_formula)
    counts = Counter()

    def walk(node):
        if isinstance(node, Var):
            counts[node.name] += 1
            return
        if isinstance(node, Not):
            walk(node.expr)
            return
        if isinstance(node, (And, Or, Imp, Iff)):
            walk(node.left)
            walk(node.right)
            return
        raise TypeError(f"Nodo non supportato: {type(node)!r}")

    walk(ast)
    return sum(count - 1 for count in counts.values() if count > 1)


class FakeBridge:
    def __init__(self):
        """Inizializza lo stato del double di test."""
        self.modified_map = {
            "and(and(p,q),and(r,s))": [
                "and(and(p,q),and(r,s))",
                "or(and(p,q),and(r,s))",
                "imp(and(p,q),and(r,s))",
            ],
            "or(and(p,q),and(r,s))": [
                "or(and(p,q),and(r,s))",
                "imp(and(p,q),and(r,s))",
                "not(and(p,q))",
            ],
        }
        self.distractor_map = {
            "and(and(p,q),and(r,s))": [
                "or(and(p,q),and(r,s))",
                "imp(and(p,q),and(r,s))",
                "iff(and(p,q),and(r,s))",
            ],
            "or(and(p,q),and(r,s))": [
                "and(and(p,q),and(r,s))",
                "imp(and(p,q),and(r,s))",
                "iff(and(p,q),and(r,s))",
            ],
        }

    def formula_of_depth(self, depth, variables, timeout=10):
        """Restituisce formule di test alla profondita richiesta."""
        return ["and(and(p,q),and(r,s))", "or(and(p,q),and(r,s))"]

    def all_depth(self, depth, variables, timeout=10):
        """Restituisce tutte le formule di test della profondita richiesta."""
        return self.formula_of_depth(depth, variables, timeout=timeout)

    def some_depth(self, depth, variables, limit, timeout=10):
        """Restituisce un sottoinsieme limitato di formule di test."""
        return self.formula_of_depth(depth, variables, timeout=timeout)[:limit]

    def rewrite_path(self, expr, timeout=10):
        """Restituisce un percorso di riscrittura simulato per la formula."""
        return list(self.modified_map.get(expr, [expr]))

    def rewrite_formula(self, expr, timeout=10):
        """Restituisce formule equivalenti riscritte in modo simulato."""
        return list(self.modified_map.get(expr, [expr]))

    def equiv(self, left, right, vars_list=None, timeout=10):
        """Simula il controllo di equivalenza logica tra due formule."""
        return right in self.modified_map.get(left, [])

    def all_step_neq(self, expr, timeout=10):
        """Restituisce distractor non equivalenti in un passo simulato."""
        return list(self.distractor_map.get(expr, []))

    def one_step_neq(self, expr, timeout=10):
        """Restituisce distractor non equivalenti a un passo."""
        return list(self.distractor_map.get(expr, []))

    def one_step_distraction(self, expr, timeout=10):
        """Restituisce distractor a un passo per la formula data."""
        return list(self.distractor_map.get(expr, []))

    def non_equivalent_distraction(self, expr, max_steps, timeout=10):
        """Restituisce distractor non equivalenti entro un numero di passi."""
        return list(self.distractor_map.get(expr, []))

    def not_equiv(self, left, right, vars_list=None, timeout=10):
        """Simula il controllo di non equivalenza tra due formule."""
        return right in self.distractor_map.get(left, [])


class RetryBridge(FakeBridge):
    def __init__(self):
        """Inizializza lo stato del double di test."""
        super().__init__()
        self.distractor_map["and(and(p,q),and(r,s))"] = []

    def not_equiv(self, left, right, vars_list=None, timeout=10):
        """Accetta i distractor generati nel percorso di retry."""
        return True


class GeneratorTests(unittest.TestCase):
    def test_tvq_true_false(self):
        """Verifica che le opzioni vero/falso siano distinte e coerenti."""
        class TruthValueQuestionBridge(FakeBridge):
            def assignment(self, vars_list, timeout=10):
                """Restituisce una valutazione deterministica per il test."""
                return [["p-true", "q-false"], ["p-false", "q-true"]]

            def some_depth(self, depth, variables, limit, timeout=10):
                """Fornisce formule campione per profondita nei test TVQ."""
                formulas_by_depth = {
                    1: ["and(p,q)", "or(p,q)", "imp(p,q)", "imp(q,p)", "iff(p,q)"],
                    2: ["iff(p,not(q))", "or(and(p,q),p)", "and(not(q),p)", "or(q,not(q))"],
                }
                return formulas_by_depth.get(depth, [])[:limit]

            def eval(self, expr, valuation, timeout=10):
                """Valuta la formula rispetto alla valutazione passata."""
                valuation_map = {
                    item.split("-", 1)[0]: item.split("-", 1)[1] == "true"
                    for item in valuation
                }
                ast = from_prolog(expr)

                def evaluate(node):
                    """Valuta ricorsivamente l AST della formula."""
                    if isinstance(node, Var):
                        return valuation_map[node.name]
                    if isinstance(node, Not):
                        return not evaluate(node.expr)
                    if isinstance(node, And):
                        return evaluate(node.left) and evaluate(node.right)
                    if isinstance(node, Or):
                        return evaluate(node.left) or evaluate(node.right)
                    if isinstance(node, Imp):
                        return (not evaluate(node.left)) or evaluate(node.right)
                    if isinstance(node, Iff):
                        return evaluate(node.left) == evaluate(node.right)
                    raise TypeError(f"Nodo non supportato: {type(node)!r}")

                return evaluate(ast)

        question = build_tvq(
            predicate_count=2,
            true_options_count=2,
            false_options_count=2,
            seed=11,
            bridge=_bridge(TruthValueQuestionBridge()),
        )

        self.assertEqual(question["information"], ["p-true", "q-false"])
        self.assertEqual(question["predicate_count"], 2)
        self.assertEqual(len(question["options"]), 4)
        self.assertEqual(len(question["true_options"]), 2)
        self.assertEqual(len(question["false_options"]), 2)
        self.assertEqual(len({entry["formula_prolog"] for entry in question["true_options"]}), 2)
        self.assertEqual(len({entry["formula_prolog"] for entry in question["false_options"]}), 2)
        self.assertTrue(all(entry["is_true"] for entry in question["true_options"]))
        self.assertTrue(all(not entry["is_true"] for entry in question["false_options"]))

    def test_ex_depth_defaults_to_allowed_variable_sets(self):
        """Verifica che build_ex_depth senza variables usi solo {p,q,r,s} o {p,q,r,s,t}."""

        class RandomVarDepthBridge(FakeBridge):
            def formula_of_depth(self, depth, variables, timeout=10):
                vars_tuple = tuple(variables)
                if vars_tuple == ("p", "q", "r", "s"):
                    return ["and(and(p,q),and(r,s))"]
                if vars_tuple == ("p", "q", "r", "s", "t"):
                    return ["and(and(p,q),and(r,and(s,t)))"]
                return []

            def some_depth(self, depth, variables, limit, timeout=10):
                return self.formula_of_depth(depth, variables, timeout=timeout)[:limit]

            def rewrite_path(self, expr, timeout=10):
                if expr == "and(and(p,q),and(r,s))":
                    return [expr, "or(and(p,q),and(r,s))", "imp(and(p,q),and(r,s))"]
                if expr == "and(and(p,q),and(r,and(s,t)))":
                    return [expr, "or(and(p,q),and(r,and(s,t)))", "imp(and(p,q),and(r,and(s,t)))"]
                return [expr]

            def rewrite_formula(self, expr, timeout=10):
                return self.rewrite_path(expr, timeout=timeout)

            def equiv(self, left, right, vars_list=None, timeout=10):
                return left != right and sorted(collect_variables(from_prolog(left))) == sorted(
                    collect_variables(from_prolog(right))
                )

            def all_step_neq(self, expr, timeout=10):
                if expr in {"and(and(p,q),and(r,s))", "or(and(p,q),and(r,s))"}:
                    return [
                        "or(and(p,q),and(r,s))",
                        "imp(and(p,q),and(r,s))",
                        "iff(and(p,q),and(r,s))",
                    ]
                if expr in {
                    "and(and(p,q),and(r,and(s,t)))",
                    "or(and(p,q),and(r,and(s,t)))",
                }:
                    return [
                        "or(and(p,q),and(r,and(s,t)))",
                        "imp(and(p,q),and(r,and(s,t)))",
                        "iff(and(p,q),and(r,and(s,t)))",
                    ]
                return []

            def one_step_neq(self, expr, timeout=10):
                return self.all_step_neq(expr, timeout=timeout)

            def non_equivalent_distraction(self, expr, max_steps, timeout=10):
                return self.all_step_neq(expr, timeout=timeout)

            def not_equiv(self, left, right, vars_list=None, timeout=10):
                return right in self.all_step_neq(left, timeout=timeout)

        bridge = RandomVarDepthBridge()
        random.seed(42)
        seen_sets: set[tuple[str, ...]] = set()

        for seed in range(20):
            exercise = build_ex_depth(
                wrong_answers_count=2,
                seed=seed,
                bridge=_bridge(bridge),
            )
            seen_sets.add(tuple(exercise["variables"]))

        allowed = {("p", "q", "r", "s"), ("p", "q", "r", "s", "t")}
        self.assertTrue(seen_sets.issubset(allowed))
        self.assertEqual(seen_sets, allowed)

    def test_tvq_defaults_to_allowed_variable_sets(self):
        """Verifica che build_tvq con predicate_count 4/5 usi set variabili ammessi."""

        class RandomVarTvqBridge(FakeBridge):
            def assignment(self, vars_list, timeout=10):
                return [[f"{name}-true" for name in vars_list]]

            def some_depth(self, depth, variables, limit, timeout=10):
                vars_tuple = tuple(variables)
                if vars_tuple == ("p", "q", "r", "s"):
                    return [
                        "and(and(p,q),and(r,s))",
                        "or(and(p,q),and(r,s))",
                    ][:limit]
                if vars_tuple == ("p", "q", "r", "s", "t"):
                    return [
                        "and(and(p,q),and(r,and(s,t)))",
                        "or(and(p,q),and(r,and(s,t)))",
                    ][:limit]
                return []

            def eval(self, expr, valuation, timeout=10):
                return expr.startswith("or(")

        bridge = RandomVarTvqBridge()
        random.seed(99)
        seen_sets: set[tuple[str, ...]] = set()

        for seed in range(20):
            question = build_tvq(
                predicate_count=4,
                true_options_count=1,
                false_options_count=1,
                seed=seed,
                bridge=_bridge(bridge),
            )
            seen_sets.add(tuple(question["variables"]))

        allowed = {("p", "q", "r", "s"), ("p", "q", "r", "s", "t")}
        self.assertTrue(seen_sets.issubset(allowed))
        self.assertEqual(seen_sets, allowed)

    def test_tvq_requires_operator_diversity_across_options(self):
        """Verifica che build_tvq rifiuti opzioni con solo un operatore principale."""

        class SameHeadTvqBridge(FakeBridge):
            def assignment(self, vars_list, timeout=10):
                return [["p-true", "q-false"]]

            def some_depth(self, depth, variables, limit, timeout=10):
                return [
                    "and(p,q)",
                    "and(q,p)",
                    "and(not(p),q)",
                    "and(p,not(q))",
                ][:limit]

            def eval(self, expr, valuation, timeout=10):
                return expr == "and(p,q)"

        with self.assertRaisesRegex(RuntimeError, "Impossibile trovare una assegnazione"):
            build_tvq(
                predicate_count=2,
                true_options_count=1,
                false_options_count=1,
                seed=3,
                bridge=_bridge(SameHeadTvqBridge()),
            )

    def test_generate_formula_by_variable_count_uses_requested_count(self):
        """Verifica che la formula generata usi esattamente il numero richiesto di variabili."""

        class VariableCountBridge(FakeBridge):
            def some_depth(self, depth, variables, limit, timeout=10):
                vars_tuple = tuple(variables)
                if vars_tuple == ("p", "q", "r"):
                    return [
                        "and(p,or(q,r))",
                        "or(p,and(q,r))",
                        "imp(and(p,q),r)",
                    ][:limit]
                return []

        formula = generate_formula_by_variable_count(
            variable_count=3,
            seed=5,
            bridge=_bridge(VariableCountBridge()),
        )
        self.assertEqual(collect_variables(from_prolog(formula)), {"p", "q", "r"})

    def test_logical_consequence_question_true_false_partition(self):
        """Verifica che il quiz di conseguenza separi correttamente opzioni implicate e non implicate."""

        class ConsequenceBridge(FakeBridge):
            def some_depth(self, depth, variables, limit, timeout=10):
                vars_tuple = tuple(variables)
                if vars_tuple != ("p", "q", "r"):
                    return []
                formulas = [
                    "and(p,or(q,r))",
                    "or(p,and(q,r))",
                    "imp(and(p,q),r)",
                    "iff(and(p,q),r)",
                    "and(p,and(q,r))",
                    "or(and(p,q),r)",
                    "imp(p,or(q,r))",
                    "iff(p,or(q,r))",
                ]
                return formulas[:limit]

            def implies_formula(self, left, right, vars_list=None, timeout=10):
                implied = {
                    "imp(and(p,q),r)",
                    "or(and(p,q),r)",
                    "imp(p,or(q,r))",
                }
                return right in implied

        question = build_logical_consequence_question(
            variable_count=3,
            correct_options_count=2,
            wrong_options_count=2,
            seed=7,
            bridge=_bridge(ConsequenceBridge()),
        )

        self.assertEqual(question["variable_count"], 3)
        self.assertNotIn("consequence_semantics", question)
        self.assertEqual(len(question["correct_options"]), 2)
        self.assertEqual(len(question["wrong_options"]), 2)
        self.assertTrue(all(entry["is_consequence"] for entry in question["correct_options"]))
        self.assertTrue(all(not entry["is_consequence"] for entry in question["wrong_options"]))
        option_heads = {entry["formula_prolog"].split("(", 1)[0] for entry in question["options"]}
        self.assertGreaterEqual(len(option_heads), 2)

    def test_logical_consequence_known_entailment_is_correct(self):
        """Verifica il caso noto: imp(and(p,q),and(r,s)) |= imp(and(p,q),or(r,s))."""

        class KnownEntailmentBridge(FakeBridge):
            def some_depth(self, depth, variables, limit, timeout=10):
                if tuple(variables) != ("p", "q", "r", "s"):
                    return []
                if depth == 2:
                    # Stabilizza la domanda generata dal builder.
                    return ["imp(and(p,q),and(r,s))"]
                formulas = [
                    "imp(and(p,q),or(r,s))",
                    "iff(and(p,q),or(r,s))",
                    "and(and(p,q),imp(r,s))",
                    "iff(and(p,q),imp(r,s))",
                ]
                return formulas[:limit]

            def implies_formula(self, left, right, vars_list=None, timeout=10):
                if left != "imp(and(p,q),and(r,s))":
                    return False
                return right == "imp(and(p,q),or(r,s))"

        question = build_logical_consequence_question(
            variable_count=4,
            correct_options_count=1,
            wrong_options_count=3,
            seed=13,
            bridge=_bridge(KnownEntailmentBridge()),
        )

        self.assertEqual(question["question_prolog"], "imp(and(p,q),and(r,s))")
        self.assertIn(
            "imp(and(p,q),or(r,s))",
            [entry["formula_prolog"] for entry in question["correct_options"]],
        )

    def test_logical_consequence_allows_simpler_consequence_and_rejects_commutative_duplicates(self):
        """Verifica che una conseguenza piu semplice sia ammessa, ma non le varianti duplicate per commutazione."""

        class SimpleConsequenceBridge(FakeBridge):
            def some_depth(self, depth, variables, limit, timeout=10):
                if tuple(variables) != ("p", "q"):
                    return []
                if depth == 2:
                    return ["and(p,q)"]
                formulas = [
                    "p",
                    "q",
                    "and(q,p)",
                    "or(p,q)",
                ]
                return formulas[:limit]

            def implies_formula(self, left, right, vars_list=None, timeout=10):
                # `and(p,q) |= p` è valido, mentre la variante commutativa della domanda va scartata.
                return right == "p"

        question = build_logical_consequence_question(
            variable_count=2,
            correct_options_count=1,
            wrong_options_count=1,
            seed=19,
            bridge=_bridge(SimpleConsequenceBridge()),
        )

        self.assertEqual(question["question_prolog"], "and(p,q)")
        self.assertEqual([entry["formula_prolog"] for entry in question["correct_options"]], ["p"])
        self.assertNotIn("and(q,p)", [entry["formula_prolog"] for entry in question["options"]])

    def test_ex_few_preds_distinct(self):
        """Verifica che la formula modificata resti distinta con pochi predicati."""
        class FewPredicatesBridge(FakeBridge):
            def formula_of_depth(self, depth, variables, timeout=10):
                """Restituisce una sola formula per simulare bassa varieta."""
                return ["and(and(p,q),and(r,s))"]

            def some_depth(self, depth, variables, limit, timeout=10):
                """Restituisce una lista limitata di formule campione."""
                return ["and(and(p,q),and(r,s))"][:limit]

            def rewrite_path(self, expr, timeout=10):
                """Simula un percorso di riscrittura minimale."""
                if expr == "and(and(p,q),and(r,s))":
                    return [
                        "and(and(p,q),and(r,s))",
                        "or(and(p,q),and(r,s))",
                        "imp(and(p,q),and(r,s))",
                    ]
                return [expr]

            def rewrite_formula(self, expr, timeout=10):
                """Restituisce formule riscritte per il caso di test."""
                return self.rewrite_path(expr, timeout=timeout)

            def equiv(self, left, right, vars_list=None, timeout=10):
                """Forza equivalenza per una coppia specifica nel test."""
                if left == "and(and(p,q),and(r,s))" and right in {
                    "or(and(p,q),and(r,s))",
                    "imp(and(p,q),and(r,s))",
                }:
                    return True
                return super().equiv(left, right, vars_list=vars_list, timeout=timeout)

        exercise = build_ex_depth(
            depth=2,
            wrong_answers_count=2,
            seed=3,
            bridge=_bridge(FewPredicatesBridge()),
        )

        self.assertNotEqual(
            exercise["modified_formula"]["formula_prolog"],
            exercise["original_formula"]["formula_prolog"],
        )

    def test_ex_depth_shape(self):
        """Verifica la struttura del payload esercizio generato."""
        exercise = build_ex_depth(
            depth=2,
            wrong_answers_count=3,
            seed=7,
            bridge=_bridge(FakeBridge()),
        )

        self.assertIn("original_formula", exercise)
        self.assertIn("modified_formula", exercise)
        self.assertIn("distraction_1", exercise)
        self.assertIn("distraction_2", exercise)
        self.assertIn("distraction_3", exercise)
        self.assertEqual(exercise["original_formula"]["label"], "formula originale")
        self.assertEqual(exercise["modified_formula"]["label"], "formula modificata")
        self.assertEqual(exercise["distraction_1"]["label"], "formula distrazione n1")
        self.assertEqual(exercise["distraction_2"]["label"], "formula distrazione n2")
        self.assertEqual(exercise["distraction_3"]["label"], "formula distrazione n3")
        self.assertEqual(len(exercise["wrong_answers_prolog"]), 3)
        self.assertIsInstance(exercise["modified_formula"]["steps"], int)
        self.assertGreaterEqual(exercise["modified_formula"]["steps"], 1)

    def test_ex_depth_retry_formula(self):
        """Con vincoli piu stretti, il retry puo esaurire i candidati e fallire in modo controllato."""
        with self.assertRaisesRegex(RuntimeError, "Impossibile costruire un esercizio completo"):
            build_ex_depth(
                depth=2,
                wrong_answers_count=1,
                seed=1,
                bridge=_bridge(RetryBridge()),
            )

    def test_ex_depth_uses_auto_selected_vars(self):
        """Verifica che l'esercizio usi il set variabili auto-selezionato."""
        class AllVarsBridge(FakeBridge):
            def formula_of_depth(self, depth, variables, timeout=10):
                """Fornisce formule che includono tutte le variabili target."""
                vars_tuple = tuple(variables)
                if vars_tuple == ("p", "q", "r", "s"):
                    return ["and(and(p,q),or(r,s))"]
                if vars_tuple == ("p", "q", "r", "s", "t"):
                    return ["and(and(p,q),and(r,and(s,t)))"]
                return []

            def some_depth(self, depth, variables, limit, timeout=10):
                """Restituisce un campione limitato delle formule disponibili."""
                return self.formula_of_depth(depth, variables, timeout=timeout)[:limit]

            def rewrite_path(self, expr, timeout=10):
                """Simula il percorso di riscrittura per la formula selezionata."""
                if expr == "and(and(p,q),or(r,s))":
                    return [
                        expr,
                        "or(and(p,q),or(r,s))",
                        "imp(and(p,q),or(r,s))",
                    ]
                if expr == "and(and(p,q),and(r,and(s,t)))":
                    return [
                        expr,
                        "or(and(p,q),and(r,and(s,t)))",
                        "imp(and(p,q),and(r,and(s,t)))",
                    ]
                return super().rewrite_path(expr, timeout=timeout)

            def rewrite_formula(self, expr, timeout=10):
                """Espone la riscrittura formula usando il path simulato."""
                return self.rewrite_path(expr, timeout=timeout)

            def equiv(self, left, right, vars_list=None, timeout=10):
                """Simula equivalenza solo per la coppia attesa dal test."""
                if left == "and(and(p,q),or(r,s))":
                    return right in {
                        "or(and(p,q),or(r,s))",
                        "imp(and(p,q),or(r,s))",
                    }
                if left == "and(and(p,q),and(r,and(s,t)))":
                    return right in {
                        "or(and(p,q),and(r,and(s,t)))",
                        "imp(and(p,q),and(r,and(s,t)))",
                    }
                return super().equiv(left, right, vars_list=vars_list, timeout=timeout)

            def all_step_neq(self, expr, timeout=10):
                """Restituisce distractor non equivalenti per il caso all-vars."""
                if expr == "and(and(p,q),or(r,s))":
                    return [
                        "and(and(p,q),and(r,s))",
                        "or(and(p,q),and(r,s))",
                        "iff(and(p,q),or(r,s))",
                    ]
                if expr == "and(and(p,q),and(r,and(s,t)))":
                    return [
                        "or(and(p,q),and(r,and(s,t)))",
                        "imp(and(p,q),and(r,and(s,t)))",
                        "iff(and(p,q),and(r,and(s,t)))",
                    ]
                return super().all_step_neq(expr, timeout=timeout)

            def one_step_neq(self, expr, timeout=10):
                """Riusa i distractor non equivalenti a un passo."""
                return self.all_step_neq(expr, timeout=timeout)

            def one_step_distraction(self, expr, timeout=10):
                """Riusa distractor a un passo per il caso in prova."""
                return self.all_step_neq(expr, timeout=timeout)

            def non_equivalent_distraction(self, expr, max_steps, timeout=10):
                """Riusa distractor non equivalenti per la profondita richiesta."""
                return self.all_step_neq(expr, timeout=timeout)

            def not_equiv(self, left, right, vars_list=None, timeout=10):
                """Valuta la non equivalenza con i distractor simulati."""
                return True

        exercise = build_ex_depth(
            depth=2,
            wrong_answers_count=1,
            seed=5,
            bridge=_bridge(AllVarsBridge()),
        )

        self.assertEqual(exercise["variables"], ["p", "q", "r", "s"])
        self.assertNotIn("variables", exercise["original_formula"])

    def test_ex_depth_auto_vars_respect_depth(self):
        """Verifica che la selezione automatica variabili rispetti i limiti di profondita."""
        with self.assertRaisesRegex(ValueError, "non consente il set automatico di variabili"):
            build_ex_depth(
                depth=1,
                wrong_answers_count=3,
                seed=5,
                bridge=_bridge(FakeBridge()),
            )

    def test_gen_formula_head_balance(self):
        """Verifica il bilanciamento degli operatori nella generazione formule."""
        class HeadBalancedBridge:
            def some_depth_head(self, depth, vars_list, head, limit, timeout=10):
                """Restituisce formule per singolo operatore principale."""
                # Formule deterministiche per operatore principale: il generatore
                # deve campionare tra gli head senza preferenze marcate.
                pool = {
                    "and": [
                        "and(p,or(q,r))",
                        "and(q,or(r,p))",
                        "and(r,or(p,q))",
                    ],
                    "or": [
                        "or(p,and(q,r))",
                        "or(q,and(r,p))",
                        "or(r,and(p,q))",
                    ],
                    "imp": [
                        "imp(p,and(q,r))",
                        "imp(q,and(r,p))",
                        "imp(r,and(p,q))",
                    ],
                    "iff": [
                        "iff(p,and(q,r))",
                        "iff(q,and(r,p))",
                        "iff(r,and(p,q))",
                    ],
                    "not": [
                        "not(and(p,or(q,r)))",
                        "not(and(q,or(r,p)))",
                        "not(and(r,or(p,q)))",
                    ],
                }
                return pool.get(head, [])[:limit]

            def some_depth_allvars(self, depth, vars_list, limit, timeout=10):
                """Aggrega formule per tutti gli operatori previsti."""
                formulas = []
                for head in ["and", "or", "imp", "iff", "not"]:
                    formulas.extend(self.some_depth_head(depth, vars_list, head, limit, timeout=timeout))
                return formulas[:limit]

            def all_depth_allvars(self, depth, vars_list, timeout=10):
                """Restituisce tutte le formule aggregate per il test."""
                return self.some_depth_allvars(depth, vars_list, limit=100, timeout=timeout)

        counts = Counter()
        bridge = HeadBalancedBridge()
        for seed in range(1, 101):
            formula = generate_formula(depth=2, variables=["p", "q", "r"], seed=seed, bridge=_bridge(bridge))
            head = formula.split("(", 1)[0] if "(" in formula else "var"
            counts[head] += 1

        observed = [counts[head] for head in ["and", "or", "imp", "iff", "not"]]
        self.assertTrue(all(value > 0 for value in observed))
        self.assertLessEqual(max(observed) - min(observed), 25)

    def test_generate_formula_uses_repetition_policy_with_budget(self):
        """Verifica che la generazione produca sia formule ripetute sia non ripetute, senza superare il budget."""

        class RepetitionPolicyBridge:
            def some_depth(self, depth, variables, limit, timeout=10):
                formulas = [
                    "and(p,q)",
                    "or(p,q)",
                    "and(p,p)",
                    "or(p,and(p,q))",
                ]
                return formulas[:limit]

        observed_repetitions = set()
        for seed in range(20):
            formula = generate_formula(
                depth=2,
                variables=["p", "q"],
                seed=seed,
                bridge=_bridge(RepetitionPolicyBridge()),
            )
            repetition_count = _count_atom_repetitions(formula)
            observed_repetitions.add(repetition_count)
            self.assertLessEqual(repetition_count, 3)

        self.assertIn(0, observed_repetitions)
        self.assertTrue(any(count > 0 for count in observed_repetitions))

    def test_wrong_answers_only_q_vars(self):
        """Verifica che i distractor usino solo le variabili della domanda."""
        class VarsLeakBridge(FakeBridge):
            def all_step_neq(self, expr, timeout=10):
                """Introduce volontariamente un distractor con variabile fuori set."""
                # Include un distractor non valido con variabile x (fuori domanda).
                return [
                    "or(and(p,q),and(r,s))",
                    "and(and(p,q),and(r,x))",
                    "imp(and(p,q),and(r,s))",
                    "iff(and(p,q),and(r,s))",
                ]

            def one_step_neq(self, expr, timeout=10):
                """Riusa la stessa sorgente di distractor per un passo."""
                return self.all_step_neq(expr, timeout=timeout)

            def non_equivalent_distraction(self, expr, max_steps, timeout=10):
                """Riusa la sorgente di distractor non equivalenti del test."""
                return self.all_step_neq(expr, timeout=timeout)

            def not_equiv(self, left, right, vars_list=None, timeout=10):
                """Considera non equivalenti le formule presenti nei distractor."""
                return right in self.all_step_neq(left, timeout=timeout)

        exercise = build_ex_depth(
            depth=2,
            wrong_answers_count=2,
            seed=7,
            bridge=_bridge(VarsLeakBridge()),
        )

        for wrong in exercise["wrong_answers_prolog"]:
            used = collect_variables(from_prolog(wrong))
            self.assertEqual(used, {"p", "q", "r", "s"}, msg=f"Distractor con variabili non valide: {wrong}")

    def test_ex_depth_atom_count_matches_question(self):
        """Verifica che domanda, corretta e distractor abbiano stesso numero di atomi."""
        exercise = build_ex_depth(
            depth=2,
            wrong_answers_count=3,
            seed=9,
            bridge=_bridge(FakeBridge()),
        )

        question_atoms = _count_atoms(exercise["question_prolog"])
        self.assertEqual(question_atoms, _count_atoms(exercise["correct_answer_prolog"]))
        self.assertTrue(
            all(_count_atoms(wrong) == question_atoms for wrong in exercise["wrong_answers_prolog"])
        )

    def test_wrong_from_correct_switches_source_formula(self):
        """Verifica che wrong_from_correct usi la risposta corretta come sorgente distractor."""
        class SourceSwitchBridge(FakeBridge):
            def __init__(self):
                """Inizializza lo stato del double di test."""
                super().__init__()
                self.called_sources: list[str] = []
                self.source_map = {
                    "and(and(p,q),and(r,s))": [
                        "or(and(p,q),and(r,s))",
                        "imp(and(p,q),and(r,s))",
                        "iff(and(p,q),and(r,s))",
                    ],
                    "or(and(p,q),and(r,s))": [
                        "and(and(p,q),and(r,s))",
                        "imp(and(p,q),and(r,s))",
                        "iff(and(p,q),and(r,s))",
                    ],
                    "imp(and(p,q),and(r,s))": [
                        "and(and(p,q),and(r,s))",
                        "or(and(p,q),and(r,s))",
                        "iff(and(p,q),and(r,s))",
                    ],
                }

            def formula_of_depth(self, depth, variables, timeout=10):
                """Restituisce una sola formula per rendere stabile la sorgente test."""
                return ["and(and(p,q),and(r,s))"]

            def some_depth(self, depth, variables, limit, timeout=10):
                """Restituisce campione limitato dalla formula fissa."""
                return self.formula_of_depth(depth, variables, timeout=timeout)[:limit]

            def rewrite_path(self, expr, timeout=10):
                """Forza una risposta corretta diversa ma equivalente nel test."""
                if expr == "and(and(p,q),and(r,s))":
                    return [
                        "and(and(p,q),and(r,s))",
                        "or(and(p,q),and(r,s))",
                        "imp(and(p,q),and(r,s))",
                    ]
                return [expr]

            def rewrite_formula(self, expr, timeout=10):
                """Riusa il path come fallback rewrite."""
                return self.rewrite_path(expr, timeout=timeout)

            def equiv(self, left, right, vars_list=None, timeout=10):
                """Simula equivalenza solo per la coppia attesa nel test."""
                if left == "and(and(p,q),and(r,s))" and right in {
                    "or(and(p,q),and(r,s))",
                    "imp(and(p,q),and(r,s))",
                }:
                    return True
                return super().equiv(left, right, vars_list=vars_list, timeout=timeout)

            def all_step_neq(self, expr, timeout=10):
                """Registra quale formula viene usata come sorgente dei distractor."""
                self.called_sources.append(expr)
                if expr == "and(and(q,p),and(r,s))":
                    expr = "and(and(p,q),and(r,s))"
                if expr == "or(and(q,p),and(r,s))":
                    expr = "or(and(p,q),and(r,s))"
                return list(self.source_map.get(expr, []))

            def one_step_neq(self, expr, timeout=10):
                """Riusa la stessa sorgente distractor tracciando la formula sorgente."""
                self.called_sources.append(expr)
                return list(self.source_map.get(expr, []))

            def non_equivalent_distraction(self, expr, max_steps, timeout=10):
                """Riusa la stessa sorgente distractor tracciando la formula sorgente."""
                self.called_sources.append(expr)
                return list(self.source_map.get(expr, []))

            def not_equiv(self, left, right, vars_list=None, timeout=10):
                """Valuta non-equivalenza rispetto alla sorgente passata nel test."""
                return True

        legacy_bridge = SourceSwitchBridge()
        build_ex_depth(
            depth=2,
            wrong_answers_count=2,
            seed=13,
            wrong_from_correct=False,
            bridge=_bridge(legacy_bridge),
        )
        self.assertIn("and(and(p,q),and(r,s))", legacy_bridge.called_sources)

        from_correct_bridge = SourceSwitchBridge()
        build_ex_depth(
            depth=2,
            wrong_answers_count=2,
            seed=13,
            wrong_from_correct=True,
            bridge=_bridge(from_correct_bridge),
        )
        self.assertTrue(
            "or(and(p,q),and(r,s))" in from_correct_bridge.called_sources
            or "or(and(q,p),and(r,s))" in from_correct_bridge.called_sources
            or "imp(and(p,q),and(r,s))" in from_correct_bridge.called_sources
        )

    def test_correct_answer_not_only_variable_reorder(self):
        """Verifica che la risposta corretta non sia solo uno scambio commutativo di variabili."""
        class ReorderOnlyBridge(FakeBridge):
            def formula_of_depth(self, depth, variables, timeout=10):
                """Restituisce una sola formula di base."""
                return ["and(and(p,q),and(r,s))"]

            def some_depth(self, depth, variables, limit, timeout=10):
                """Restituisce il campione limitato dalla formula base."""
                return self.formula_of_depth(depth, variables, timeout=timeout)[:limit]

            def rewrite_path(self, expr, timeout=10):
                """Restituisce solo una variante commutativa della domanda."""
                if expr == "and(and(p,q),and(r,s))":
                    return ["and(and(p,q),and(r,s))", "and(and(q,p),and(r,s))"]
                return [expr]

            def rewrite_formula(self, expr, timeout=10):
                """Riusa il percorso di rewrite commutativo."""
                return self.rewrite_path(expr, timeout=timeout)

            def equiv(self, left, right, vars_list=None, timeout=10):
                """Dichiara equivalenza tra formula e versione commutata."""
                if left == "and(and(p,q),and(r,s))" and right == "and(and(q,p),and(r,s))":
                    return True
                return super().equiv(left, right, vars_list=vars_list, timeout=timeout)

        with self.assertRaisesRegex(RuntimeError, "Impossibile costruire un esercizio completo"):
            build_ex_depth(
                depth=2,
                wrong_answers_count=2,
                seed=17,
                bridge=_bridge(ReorderOnlyBridge()),
            )

    def test_correct_answer_requires_min_two_non_trivial_steps(self):
        """Verifica che una sola trasformazione non banale non sia sufficiente."""

        class OneStepOnlyBridge(FakeBridge):
            def formula_of_depth(self, depth, variables, timeout=10):
                return ["and(and(p,q),and(r,s))"]

            def some_depth(self, depth, variables, limit, timeout=10):
                return self.formula_of_depth(depth, variables, timeout=timeout)[:limit]

            def rewrite_path(self, expr, timeout=10):
                if expr == "and(and(p,q),and(r,s))":
                    return [expr, "or(and(p,q),and(r,s))"]
                return [expr]

            def rewrite_formula(self, expr, timeout=10):
                return self.rewrite_path(expr, timeout=timeout)

            def equiv(self, left, right, vars_list=None, timeout=10):
                if left == "and(and(p,q),and(r,s))" and right == "or(and(p,q),and(r,s))":
                    return True
                return False

            def all_step_neq(self, expr, timeout=10):
                return [
                    "imp(and(p,q),and(r,s))",
                    "iff(and(p,q),and(r,s))",
                    "and(and(p,q),or(r,s))",
                ]

            def one_step_neq(self, expr, timeout=10):
                return self.all_step_neq(expr, timeout=timeout)

            def non_equivalent_distraction(self, expr, max_steps, timeout=10):
                return self.all_step_neq(expr, timeout=timeout)

            def not_equiv(self, left, right, vars_list=None, timeout=10):
                return True

        with self.assertRaisesRegex(RuntimeError, "Impossibile costruire un esercizio completo"):
            build_ex_depth(depth=2, wrong_answers_count=2, seed=23, bridge=_bridge(OneStepOnlyBridge()))

    def test_correct_answer_with_imp_gets_second_non_trivial_step(self):
        """Verifica che una trasformazione extra non banale consenta il superamento della soglia minima."""

        class TwoStepBridge(FakeBridge):
            def formula_of_depth(self, depth, variables, timeout=10):
                return ["and(and(p,q),and(r,s))"]

            def some_depth(self, depth, variables, limit, timeout=10):
                return self.formula_of_depth(depth, variables, timeout=timeout)[:limit]

            def rewrite_path(self, expr, timeout=10):
                if expr == "and(and(p,q),and(r,s))":
                    return [expr, "or(and(p,q),and(r,s))", "imp(and(p,q),and(r,s))"]
                return [expr]

            def rewrite_formula(self, expr, timeout=10):
                if expr == "and(and(p,q),and(r,s))":
                    return ["imp(and(and(p,q),and(r,s)),and(p,q))"]
                if expr == "imp(and(and(p,q),and(r,s)),and(p,q))":
                    return ["or(not(and(and(p,q),and(r,s))),and(p,q))"]
                return [expr]

            def equiv(self, left, right, vars_list=None, timeout=10):
                if left == "and(and(p,q),and(r,s))" and right in {
                    "or(and(p,q),and(r,s))",
                    "imp(and(and(p,q),and(r,s)),and(p,q))",
                    "or(not(and(and(p,q),and(r,s))),and(p,q))",
                    "imp(and(p,q),and(r,s))",
                }:
                    return True
                return False

            def all_step_neq(self, expr, timeout=10):
                return [
                    "imp(and(p,q),and(r,s))",
                    "iff(and(p,q),and(r,s))",
                    "and(and(p,q),or(r,s))",
                ]

            def one_step_neq(self, expr, timeout=10):
                return self.all_step_neq(expr, timeout=timeout)

            def non_equivalent_distraction(self, expr, max_steps, timeout=10):
                return self.all_step_neq(expr, timeout=timeout)

            def not_equiv(self, left, right, vars_list=None, timeout=10):
                return True

        exercise = build_ex_depth(depth=2, wrong_answers_count=2, seed=31, bridge=_bridge(TwoStepBridge()))
        self.assertGreaterEqual(exercise["rewrite_steps"], 2)


class PrologBridgeTests(unittest.TestCase):
    def test_assignment_serializes_terms(self):
        """Verifica che assignment serializzi i termini come stringhe Prolog."""
        class CaptureBridge(PrologBridge):
            def __init__(self):
                """Inizializza lo stato del double di test."""
                pass

            def run_json_query(self, goal, timeout=10):
                """Cattura la query e restituisce una risposta JSON simulata."""
                self.last_goal = goal
                return {"valuations": [["p-true", "q-false"]]}

        bridge = CaptureBridge()
        valuations = bridge.assignment(["p", "q"])

        self.assertEqual(valuations, [["p-true", "q-false"]])
        self.assertIn("term_string(Item, ItemStr)", bridge.last_goal)
        self.assertIn("assignment([p,q], V)", bridge.last_goal)


if __name__ == "__main__":
    unittest.main()
import unittest
from collections import Counter

from ast_logic import And, Iff, Imp, Not, Or, Var
from generator import build_ex_depth
from generator import build_tvq
from generator import generate_formula
from prolog_bridge import PrologBridge
from prolog_bridge import collect_variables, from_prolog


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


class FakeBridge:
    def __init__(self):
        """Inizializza lo stato del double di test."""
        self.modified_map = {
            "and(p,q)": ["and(p,q)", "or(p,q)", "imp(p,q)"],
            "or(p,q)": ["or(p,q)", "imp(p,q)", "not(p)"],
        }
        self.distractor_map = {
            "and(p,q)": ["and(p,not(q))", "or(not(p),q)", "imp(p,q)"],
            "or(p,q)": ["or(p,not(q))", "and(not(p),q)", "imp(q,p)"],
        }

    def formula_of_depth(self, depth, variables, timeout=10):
        """Restituisce formule di test alla profondita richiesta."""
        return ["and(p,q)", "or(p,q)"]

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
        self.distractor_map["and(p,q)"] = []


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
            bridge=TruthValueQuestionBridge(),
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

    def test_ex_few_preds_distinct(self):
        """Verifica che la formula modificata resti distinta con pochi predicati."""
        class FewPredicatesBridge(FakeBridge):
            def formula_of_depth(self, depth, variables, timeout=10):
                """Restituisce una sola formula per simulare bassa varieta."""
                return ["and(p,q)"]

            def some_depth(self, depth, variables, limit, timeout=10):
                """Restituisce una lista limitata di formule campione."""
                return ["and(p,q)"][:limit]

            def rewrite_path(self, expr, timeout=10):
                """Simula un percorso di riscrittura minimale."""
                if expr == "and(p,q)":
                    return ["and(p,q)", "or(p,q)"]
                return [expr]

            def rewrite_formula(self, expr, timeout=10):
                """Restituisce formule riscritte per il caso di test."""
                return self.rewrite_path(expr, timeout=timeout)

            def equiv(self, left, right, vars_list=None, timeout=10):
                """Forza equivalenza per una coppia specifica nel test."""
                if left == "and(p,q)" and right == "or(p,q)":
                    return True
                return super().equiv(left, right, vars_list=vars_list, timeout=timeout)

        exercise = build_ex_depth(
            depth=1,
            variables=["p", "q"],
            wrong_answers_count=2,
            max_steps=1,
            seed=3,
            bridge=FewPredicatesBridge(),
        )

        self.assertNotEqual(
            exercise["modified_formula"]["formula_prolog"],
            exercise["original_formula"]["formula_prolog"],
        )

    def test_ex_depth_shape(self):
        """Verifica la struttura del payload esercizio generato."""
        exercise = build_ex_depth(
            depth=2,
            variables=["p", "q"],
            wrong_answers_count=3,
            max_steps=2,
            seed=7,
            bridge=FakeBridge(),
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
        self.assertEqual(len(exercise["wrong_answers"]), 3)
        self.assertIsInstance(exercise["modified_formula"]["steps"], int)
        self.assertGreaterEqual(exercise["modified_formula"]["steps"], 1)

    def test_ex_depth_retry_formula(self):
        """Verifica il retry su formula alternativa quando mancano distractor."""
        exercise = build_ex_depth(
            depth=2,
            variables=["p", "q"],
            wrong_answers_count=3,
            max_steps=2,
            seed=1,
            bridge=RetryBridge(),
        )

        self.assertEqual(exercise["original_formula"]["formula_prolog"], "or(p,q)")
        self.assertEqual(len(exercise["wrong_answers_prolog"]), 3)

    def test_ex_depth_uses_all_vars(self):
        """Verifica che l'esercizio usi tutte le variabili richieste."""
        class AllVarsBridge(FakeBridge):
            def formula_of_depth(self, depth, variables, timeout=10):
                """Fornisce formule che includono tutte le variabili target."""
                return ["and(p,q)", "and(and(a,b),or(c,d))"]

            def some_depth(self, depth, variables, limit, timeout=10):
                """Restituisce un campione limitato delle formule disponibili."""
                return self.formula_of_depth(depth, variables, timeout=timeout)[:limit]

            def rewrite_path(self, expr, timeout=10):
                """Simula il percorso di riscrittura per la formula selezionata."""
                if expr == "and(and(a,b),or(c,d))":
                    return [expr, "or(and(a,b),or(c,d))"]
                return super().rewrite_path(expr, timeout=timeout)

            def rewrite_formula(self, expr, timeout=10):
                """Espone la riscrittura formula usando il path simulato."""
                return self.rewrite_path(expr, timeout=timeout)

            def equiv(self, left, right, vars_list=None, timeout=10):
                """Simula equivalenza solo per la coppia attesa dal test."""
                if left == "and(and(a,b),or(c,d))":
                    return right == "or(and(a,b),or(c,d))"
                return super().equiv(left, right, vars_list=vars_list, timeout=timeout)

            def all_step_neq(self, expr, timeout=10):
                """Restituisce distractor non equivalenti per il caso all-vars."""
                if expr == "and(and(a,b),or(c,d))":
                    return ["and(and(a,b),and(c,d))", "or(and(a,b),and(c,d))", "imp(and(a,b),or(c,d))"]
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
                if left == "and(and(a,b),or(c,d))":
                    return right in self.all_step_neq(left, timeout=timeout)
                return super().not_equiv(left, right, vars_list=vars_list, timeout=timeout)

        exercise = build_ex_depth(
            depth=3,
            variables=["a", "b", "c", "d"],
            wrong_answers_count=3,
            max_steps=2,
            seed=5,
            bridge=AllVarsBridge(),
        )

        self.assertEqual(exercise["variables"], ["a", "b", "c", "d"])
        self.assertEqual(exercise["original_formula"]["variables"], ["a", "b", "c", "d"])

    def test_ex_depth_rejects_var_count(self):
        """Verifica l'errore quando le variabili superano la profondita utile."""
        with self.assertRaisesRegex(ValueError, "non consente di usare tutte le variabili"):
            build_ex_depth(
                depth=1,
                variables=["a", "b", "c"],
                wrong_answers_count=3,
                max_steps=2,
                seed=5,
                bridge=FakeBridge(),
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
            formula = generate_formula(depth=2, variables=["p", "q", "r"], seed=seed, bridge=bridge)
            head = formula.split("(", 1)[0] if "(" in formula else "var"
            counts[head] += 1

        observed = [counts[head] for head in ["and", "or", "imp", "iff", "not"]]
        self.assertTrue(all(value > 0 for value in observed))
        self.assertLessEqual(max(observed) - min(observed), 25)

    def test_wrong_answers_only_q_vars(self):
        """Verifica che i distractor usino solo le variabili della domanda."""
        class VarsLeakBridge(FakeBridge):
            def all_step_neq(self, expr, timeout=10):
                """Introduce volontariamente un distractor con variabile fuori set."""
                # Include un distractor non valido con variabile x (fuori domanda).
                return ["or(p,q)", "and(p,x)", "imp(p,q)", "and(p,not(q))", "or(not(p),q)"]

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
            variables=["p", "q"],
            wrong_answers_count=2,
            max_steps=2,
            seed=7,
            bridge=VarsLeakBridge(),
        )

        for wrong in exercise["wrong_answers_prolog"]:
            used = collect_variables(from_prolog(wrong))
            self.assertEqual(used, {"p", "q"}, msg=f"Distractor con variabili non valide: {wrong}")

    def test_ex_depth_atom_count_matches_question(self):
        """Verifica che domanda, corretta e distractor abbiano stesso numero di atomi."""
        exercise = build_ex_depth(
            depth=2,
            variables=["p", "q"],
            wrong_answers_count=3,
            max_steps=2,
            seed=9,
            bridge=FakeBridge(),
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
                    "and(p,q)": ["and(p,not(q))", "or(not(p),q)", "imp(p,q)"],
                    "or(p,q)": ["or(p,not(q))", "and(not(p),q)", "imp(q,p)"],
                }

            def formula_of_depth(self, depth, variables, timeout=10):
                """Restituisce una sola formula per rendere stabile la sorgente test."""
                return ["and(p,q)"]

            def some_depth(self, depth, variables, limit, timeout=10):
                """Restituisce campione limitato dalla formula fissa."""
                return self.formula_of_depth(depth, variables, timeout=timeout)[:limit]

            def rewrite_path(self, expr, timeout=10):
                """Forza una risposta corretta diversa ma equivalente nel test."""
                if expr == "and(p,q)":
                    return ["and(p,q)", "or(p,q)"]
                return [expr]

            def rewrite_formula(self, expr, timeout=10):
                """Riusa il path come fallback rewrite."""
                return self.rewrite_path(expr, timeout=timeout)

            def equiv(self, left, right, vars_list=None, timeout=10):
                """Simula equivalenza solo per la coppia attesa nel test."""
                if left == "and(p,q)" and right == "or(p,q)":
                    return True
                return super().equiv(left, right, vars_list=vars_list, timeout=timeout)

            def all_step_neq(self, expr, timeout=10):
                """Registra quale formula viene usata come sorgente dei distractor."""
                self.called_sources.append(expr)
                if expr == "and(q,p)":
                    expr = "and(p,q)"
                if expr == "or(q,p)":
                    expr = "or(p,q)"
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
            variables=["p", "q"],
            wrong_answers_count=2,
            max_steps=2,
            seed=13,
            wrong_from_correct=False,
            bridge=legacy_bridge,
        )
        self.assertIn("and(p,q)", legacy_bridge.called_sources)

        from_correct_bridge = SourceSwitchBridge()
        build_ex_depth(
            depth=2,
            variables=["p", "q"],
            wrong_answers_count=2,
            max_steps=2,
            seed=13,
            wrong_from_correct=True,
            bridge=from_correct_bridge,
        )
        self.assertTrue(
            "or(p,q)" in from_correct_bridge.called_sources
            or "or(q,p)" in from_correct_bridge.called_sources
        )


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
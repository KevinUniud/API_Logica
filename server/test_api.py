import unittest
from unittest.mock import Mock, patch
import os

from fastapi.testclient import TestClient

from server import app


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Inizializza il client HTTP condiviso per i test API."""
        cls.client = TestClient(app)

    def test_openapi_paths(self):
        """Verifica che lo schema OpenAPI esponga i path principali attesi."""
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)

        schema = response.json()

        self.assertEqual(schema["openapi"], "3.1.0")
        self.assertIn("/api/generator/build-exercise-from-depth", schema["paths"])
        self.assertIn("/api/generator/generate-formula-by-variable-count", schema["paths"])
        self.assertIn("/api/generator/build-logical-consequence-question", schema["paths"])
        self.assertIn("/api/generator/build-translation-question", schema["paths"])
        self.assertIn("/api/prolog-bridge/logic/eval", schema["paths"])
        self.assertIn("/api/prolog-bridge/distractions/one-step-distraction", schema["paths"])

        request_body = schema["paths"]["/api/generator/build-exercise-from-depth"]["post"]["requestBody"]
        content = request_body["content"]["application/json"]
        self.assertIn("examples", content)

    def test_gen_endpoint(self):
        """Verifica il formato risposta dell'endpoint di generazione esercizi."""
        fake_result = {
            "original_formula": {"label": "formula originale"},
            "modified_formula": {"label": "formula modificata"},
            "wrong_answers_prolog": ["a", "b", "c"],
        }
        with patch("server.generator.build_ex_depth", return_value=fake_result):
            response = self.client.post(
                "/api/generator/build-exercise-from-depth",
                json={"seed": 42},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["operation"], "generator_build_ex_depth")
        self.assertEqual(payload["result"]["original_formula"]["label"], "formula originale")
        self.assertEqual(payload["result"]["modified_formula"]["label"], "formula modificata")
        self.assertEqual(len(payload["result"]["wrong_answers_prolog"]), 3)
        self.assertTrue(all(not key.startswith("distraction_") for key in payload["result"].keys()))

    def test_truth_options_endpoint(self):
        """Verifica l'endpoint che produce opzioni vero/falso."""
        fake_result = {
            "information": ["p-true", "q-false"],
            "options": [
                {"formula_prolog": "or(p,q)", "is_true": True},
                {"formula_prolog": "and(p,q)", "is_true": False},
            ],
            "true_options_count": 1,
            "false_options_count": 1,
        }
        with patch("server.generator.build_tvq", return_value=fake_result):
            response = self.client.post(
                "/api/generator/build-truth-value-options-question",
                json={"predicate_count": 4, "true_options_count": 1, "false_options_count": 1, "seed": 42},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["operation"], "generator_build_tvq")
        self.assertEqual(payload["result"]["information"], ["p-true", "q-false"])
        self.assertEqual(len(payload["result"]["options"]), 2)
        self.assertNotIn("true_options", payload["result"])
        self.assertNotIn("false_options", payload["result"])

    def test_formula_by_variable_count_endpoint(self):
        """Verifica l'endpoint che genera formula con numero variabili specifico."""
        fake_result = "and(p,or(q,r))"
        with patch("server.generator.generate_formula_by_variable_count", return_value=fake_result):
            response = self.client.post(
                "/api/generator/generate-formula-by-variable-count",
                json={"variable_count": 3, "seed": 42},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["operation"], "generator_generate_formula_by_variable_count")
        self.assertEqual(payload["result"], fake_result)

    def test_logical_consequence_endpoint(self):
        """Verifica l'endpoint per il quiz di conseguenza logica."""
        fake_result = {
            "question_prolog": "and(p,or(q,r))",
            "options": [
                {"formula_prolog": "imp(p,or(q,r))", "is_consequence": True},
                {"formula_prolog": "iff(p,q)", "is_consequence": False},
            ],
        }
        with patch("server.generator.build_logical_consequence_question", return_value=fake_result):
            response = self.client.post(
                "/api/generator/build-logical-consequence-question",
                json={
                    "variable_count": 3,
                    "correct_options_count": 1,
                    "wrong_options_count": 1,
                    "seed": 42,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["operation"], "generator_build_logical_consequence_question")
        self.assertEqual(payload["result"]["question_prolog"], "and(p,or(q,r))")
        self.assertEqual(len(payload["result"]["options"]), 2)
        self.assertNotIn("correct_options", payload["result"])
        self.assertNotIn("wrong_options", payload["result"])

    def test_logical_consequence_runtime_error_is_422(self):
        """Verifica che gli errori runtime del generatore vengano esposti come 422."""
        with patch(
            "server.generator.build_logical_consequence_question",
            side_effect=RuntimeError("Impossibile trovare abbastanza opzioni"),
        ):
            response = self.client.post(
                "/api/generator/build-logical-consequence-question",
                json={
                    "variable_count": 3,
                    "correct_options_count": 1,
                    "wrong_options_count": 3,
                    "seed": 42,
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("Impossibile trovare abbastanza opzioni", response.json()["detail"])

    def test_translation_question_endpoint(self):
        """Verifica l'endpoint per il quiz di traduzione italiano -> logica."""
        fake_result = {
            "type": "translation_question",
            "subtype": "propositional",
            "question_text": "Tradurre la seguente frase in linguaggio logico: \"Se Giulia corre allora Marco corre\"",
            "info": ["P = Giulia corre", "Q = Marco corre"],
            "options": [
                {"formula": "imp(P,Q)", "is_correct": True},
                {"formula": "imp(Q,P)", "is_correct": False},
                {"formula": "and(P,Q)", "is_correct": False},
                {"formula": "imp(not(P),Q)", "is_correct": False},
            ],
            "correct_options_count": 1,
            "wrong_options_count": 3,
            "metadata": {
                "quantifier_used": "none",
                "names_used": ["Giulia", "Marco"],
                "actions_used": ["corre"],
                "source": "rule_generator",
            },
        }
        with patch("server.generator.build_translation_question", return_value=fake_result):
            response = self.client.post(
                "/api/generator/build-translation-question",
                json={
                    "mode": "auto",
                    "quantifier_ratio": 0.5,
                    "wrong_options_count": 3,
                    "names_pool": ["Giulia", "Marco"],
                    "actions_pool": ["corre", "salta"],
                    "implied_person_predicate": True,
                    "allow_spoken_mode": False,
                    "seed": 42,
                    "timeout_seconds": 10,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["operation"], "generator_build_translation_question")
        self.assertEqual(payload["result"]["type"], "translation_question")
        self.assertEqual(payload["result"]["wrong_options_count"], 3)

    def test_template_endpoint(self):
        """Verifica l'endpoint template con bridge mockato."""
        fake_bridge = Mock()
        fake_bridge.formula_of_depth.return_value = ["and(p,q)"]
        with patch("server._build_bridge", return_value=fake_bridge):
            response = self.client.post(
                "/api/prolog-bridge/templates/formula-of-depth",
                json={"depth": 1, "variables": ["p", "q"]},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["operation"], "bridge_formula_of_depth")
        self.assertTrue(len(payload["result"]) > 0)

    def test_logic_eval_endpoint(self):
        """Verifica l'endpoint di valutazione logica sotto una valutazione."""
        fake_bridge = Mock()
        fake_bridge.eval.return_value = False
        with patch("server._build_bridge", return_value=fake_bridge):
            response = self.client.post(
                "/api/prolog-bridge/logic/eval",
                json={
                    "expr": "and(p,q)",
                    "valuation": [
                        {"name": "p", "value": True},
                        {"name": "q", "value": False},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["operation"], "bridge_eval")
        self.assertFalse(payload["result"])

    def test_bridge_override_is_rejected(self):
        """Verifica che il body non accetti piu il campo bridge."""
        response = self.client.post(
            "/api/prolog-bridge/logic/vars-in-formula",
            json={
                "expr": "and(p,q)",
                "bridge": {"entry_file": "templates.pl"},
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_unknown_field_is_rejected(self):
        """Verifica che i body con campi extra non previsti vengano rifiutati."""
        response = self.client.post(
            "/api/generator/build-exercise-from-depth",
            json={
                "seed": 42,
                "unexpected": True,
            },
        )

        self.assertEqual(response.status_code, 422)

    @unittest.skipUnless(os.getenv("RUN_INTEGRATION_TESTS") == "1", "Set RUN_INTEGRATION_TESTS=1")
    def test_integration_gen_endpoint(self):
        """Esegue un controllo integrazione reale sull'endpoint generatore."""
        response = self.client.post(
            "/api/generator/build-exercise-from-depth",
            json={"seed": 42},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["operation"], "generator_build_ex_depth")
        self.assertIn("original_formula", payload["result"])


if __name__ == "__main__":
    unittest.main()
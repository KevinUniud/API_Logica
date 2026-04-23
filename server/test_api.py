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
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))

from generator import (  # noqa: E402
    build_ex_depth,
    build_logical_consequence_question,
    build_tvq,
    generate_formula_by_variable_count,
)


OUTPUT_PATH = Path(__file__).resolve().parent / "dump.txt"


def _build_ex_depth_sample() -> dict:
    """Genera un esempio depth con fallback su seed/depth compatibili ai nuovi vincoli."""
    last_error: Exception | None = None
    for depth in (2, 3):
        for seed in (7, 11, 17, 23, 29):
            try:
                return build_ex_depth(
                    depth=depth,
                    use_all=False,
                    timeout=10,
                    seed=seed,
                    wrong_answers_count=2,
                )
            except RuntimeError as exc:
                last_error = exc
                continue
    raise RuntimeError("Impossibile generare sample build_ex_depth") from last_error


def _build_logical_consequence_sample() -> dict:
    """Genera un esempio di quiz conseguenza logica con fallback su seed alternativi."""
    last_error: Exception | None = None
    for seed in (7, 11, 17, 23, 29):
        try:
            return build_logical_consequence_question(
                variable_count=4,
                correct_options_count=1,
                wrong_options_count=3,
                timeout=10,
                seed=seed,
            )
        except RuntimeError as exc:
            last_error = exc
            continue
    raise RuntimeError("Impossibile generare sample build_logical_consequence_question") from last_error


def _only_formulas_ex_depth(payload: dict) -> dict:
    """Riduce l'output esercizio depth alle sole formule Prolog."""
    return {
        "question_prolog": payload["question_prolog"],
        "correct_answer_prolog": payload["correct_answer_prolog"],
        "wrong_answers_prolog": payload["wrong_answers_prolog"],
    }


def _only_formulas_tvq(payload: dict) -> dict:
    """Riduce l'output TVQ alle sole formule Prolog delle opzioni."""
    return {
        "true_options_prolog": [entry["formula_prolog"] for entry in payload["true_options"]],
        "false_options_prolog": [entry["formula_prolog"] for entry in payload["false_options"]],
        "options_prolog": [entry["formula_prolog"] for entry in payload["options"]],
    }


def _only_formulas_logical_consequence(payload: dict) -> dict:
    """Riduce l'output conseguenza logica alle sole formule Prolog."""
    return {
        "question_prolog": payload["question_prolog"],
        "correct_options_prolog": [entry["formula_prolog"] for entry in payload["correct_options"]],
        "wrong_options_prolog": [entry["formula_prolog"] for entry in payload["wrong_options"]],
        "options_prolog": [entry["formula_prolog"] for entry in payload["options"]],
    }


def main() -> None:
    ex_depth = _build_ex_depth_sample()
    tvq = build_tvq(
        predicate_count=4,
        true_options_count=1,
        false_options_count=3,
        timeout=10,
    )
    formula_by_count = generate_formula_by_variable_count(
        variable_count=4,
        timeout=10,
        seed=11,
    )
    consequence = _build_logical_consequence_sample()

    result = {
        "build_ex_depth": _only_formulas_ex_depth(ex_depth),
        "build_tvq": _only_formulas_tvq(tvq),
        "generate_formula_by_variable_count": formula_by_count,
        "build_logical_consequence_question": _only_formulas_logical_consequence(consequence),
    }

    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Scritto {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

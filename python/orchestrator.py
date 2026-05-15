"""Orchestrator module: thin wrappers that handle bridge/defaults/serialization
and delegate exercise construction to `generator.py`.

This file is a first-step scaffold: it centralizes JSON wrappers and bridge
resolution so we can later move orchestration logic out of `generator.py`.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence, cast
import random
import logging

from config import DEFAULT_TIMEOUT, configure_logging
from constants import JSON_INDENT

from prolog_bridge import get_default_bridge, PrologBridge
import generator


def _ensure_bridge(bridge: PrologBridge | None = None) -> PrologBridge:
    return bridge or get_default_bridge()


# module logger; server should call `config.configure_logging()` on startup
logger = logging.getLogger(__name__)


def generate_formula_json(
    depth: int | None = None,
    variables: list[str] | None = None,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> dict:
    """Wrapper: generate a formula and return JSON-serializable payload."""
    bridge = _ensure_bridge(bridge)
    variables_arg = variables if variables is not None else generator.DEFAULT_VARIABLES
    # Delegate to generator JSON wrapper which supports spoken rendering
    return generator.generate_formula_json(
        depth=depth,
        variables=variables_arg,
        use_all=use_all,
        timeout=timeout,
        seed=seed,
        bridge=bridge,
        allow_spoken_mode=allow_spoken_mode,
    )


def generate_formula_by_variable_count_json(
    variable_count: int,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> dict:
    bridge = _ensure_bridge(bridge)
    formula = generator.generate_formula_by_variable_count(
        variable_count=variable_count,
        use_all=use_all,
        timeout=timeout,
        seed=seed,
        bridge=bridge,
    )
    return generator.generate_formula_by_variable_count_json(
        variable_count=variable_count,
        use_all=use_all,
        timeout=timeout,
        seed=seed,
        bridge=bridge,
        allow_spoken_mode=allow_spoken_mode,
    )


def build_ex_json(
    expr: Any,
    bridge: PrologBridge | None = None,
    seed: int | None = None,
    wrong_answers_count: int = 3,
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    timeout: int = 10,
    allow_spoken_mode: bool = False,
) -> str:
    bridge = _ensure_bridge(bridge)
    return generator._to_json_string(
        generator.build_exercise(
            expr=expr,
            bridge=bridge,
            seed=seed,
            wrong_answers_count=wrong_answers_count,
            operator_cycles=operator_cycles,
            wrong_from_correct=wrong_from_correct,
            timeout=timeout,
            allow_spoken_mode=allow_spoken_mode,
        )
    )


def build_ex_depth_json(
    depth: int | None = None,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    wrong_answers_count: int = 3,
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> str:
    bridge = _ensure_bridge(bridge)
    return generator._to_json_string(
        generator.build_ex_depth(
            depth=depth,
            use_all=use_all,
            timeout=timeout,
            seed=seed,
            wrong_answers_count=wrong_answers_count,
            operator_cycles=operator_cycles,
            wrong_from_correct=wrong_from_correct,
            bridge=bridge,
            allow_spoken_mode=allow_spoken_mode,
        )
    )


def build_tvq_json(
    predicate_count: int,
    true_options_count: int,
    false_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
    allow_spoken_mode: bool = False,
) -> str:
    bridge = _ensure_bridge(bridge)
    return generator._to_json_string(
        generator.build_tvq(
            predicate_count=predicate_count,
            true_options_count=true_options_count,
            false_options_count=false_options_count,
            timeout=timeout,
            seed=seed,
            operator_cycles=operator_cycles,
            bridge=bridge,
            allow_spoken_mode=allow_spoken_mode,
        )
    )


def build_logical_consequence_question_json(
    variable_count: int,
    correct_options_count: int,
    wrong_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    allow_spoken_mode: bool = False,
    bridge: PrologBridge | None = None,
) -> str:
    bridge = _ensure_bridge(bridge)
    return generator._to_json_string(
        generator.build_logical_consequence_question(
            variable_count=variable_count,
            correct_options_count=correct_options_count,
            wrong_options_count=wrong_options_count,
            timeout=timeout,
            seed=seed,
            operator_cycles=operator_cycles,
            allow_spoken_mode=allow_spoken_mode,
            bridge=bridge,
            
        )
    )


def _transform_answer_candidates(
    *,
    formula: str,
    bridge: PrologBridge,
    rng: random.Random,
    operator_cycles: int | None,
    timeout_provider: Callable[[], int],
) -> list[str]:
    """Delegate transformation generation to Prolog via bridge with Python fallback.

    This was extracted from `generator` so orchestration of bridge calls
    remains in this module while reusing generator pure helpers.
    """
    transformed: list[str] = []

    answer_cycles_fn = getattr(bridge, "apply_answer_transform_cycles", None)
    if callable(answer_cycles_fn):
        cycles = generator._operator_cycle_count(formula, rng, operator_cycles)
        if cycles > 0:
            transformed = generator._safe_bridge_call(
                cast(Callable[..., object], answer_cycles_fn),
                formula,
                cycles=cycles,
                timeout=timeout_provider(),
            )

    if transformed:
        return list(dict.fromkeys([formula] + transformed))

    fallback = [formula, generator._maybe_swap_and_or(formula, rng)]
    if operator_cycles == 0:
        return list(dict.fromkeys(fallback))

    apply_cycles = getattr(bridge, "apply_operator_cycles", None)
    if not callable(apply_cycles):
        return list(dict.fromkeys(fallback))

    cycle_fn = cast(Callable[..., list[str]], apply_cycles)
    candidate_cycles = generator._operator_cycle_count(formula, rng, operator_cycles)
    if candidate_cycles <= 0:
        return list(dict.fromkeys(fallback))

    enriched_candidates = generator._safe_bridge_call(
        cast(Callable[..., object], cycle_fn),
        formula,
        cycles=candidate_cycles,
        timeout=timeout_provider(),
    )

    for enriched in enriched_candidates:
        fallback.append(enriched)
        fallback.append(generator._maybe_swap_and_or(enriched, rng))
        if generator._needs_extra_transformation(enriched):
            extra_candidates = generator._safe_bridge_call(
                cast(Callable[..., object], cycle_fn),
                enriched,
                cycles=1,
                timeout=timeout_provider(),
            )
            for extra in extra_candidates:
                fallback.append(extra)
                fallback.append(generator._maybe_swap_and_or(extra, rng))

    return list(dict.fromkeys(fallback))


def _collect_candidate_formulas(
    *,
    bridge: PrologBridge,
    variables: Sequence[str],
    required_options: int,
    rng: random.Random,
    timeout_provider: Callable[[int | None], int],
    operator_cycles: int | None,
    target_atom_count: int | None = None,
    excluded_formulas: Sequence[str] | None = None,
    dedupe_by_commutative_signature: bool = False,
    require_non_empty_vars: bool = False,
    forbid_adjacent_duplicate_atoms: bool = False,
    spoken_only: bool = False,
) -> list[str]:
    """Collect candidate formulas using bridge calls and generator helpers."""
    candidates: list[str] = []
    seen_candidates: set[str] = set(excluded_formulas or ())
    seen_signatures: set[str] = set()
    if dedupe_by_commutative_signature:
        seen_signatures = {generator._commutative_signature(formula) for formula in seen_candidates}

    allowed_variables = set(variables)

    def register_candidate(formula: str) -> None:
        if not formula or formula in seen_candidates:
            return
        used_variables = generator.collect_variables(generator._as_ast(formula))
        if require_non_empty_vars and not used_variables:
            return
        if not used_variables.issubset(allowed_variables):
            return
        if target_atom_count is not None and not generator._has_atom_count(formula, target_atom_count):
            return
        if forbid_adjacent_duplicate_atoms and generator._has_adjacent_duplicate_atoms(formula):
            return
        if not generator._has_valid_binary_operator_count(generator._as_ast(formula)):
            return
        if spoken_only and not generator._formula_is_spoken_friendly(formula):
            return

        if dedupe_by_commutative_signature:
            signature = generator._commutative_signature(formula)
            if signature in seen_signatures:
                return
            seen_signatures.add(signature)

        seen_candidates.add(formula)
        candidates.append(formula)

    def register_with_operator_cycles(formula: str) -> None:
        transformed = _transform_answer_candidates(
            formula=formula,
            bridge=bridge,
            rng=rng,
            operator_cycles=operator_cycles,
            timeout_provider=lambda: timeout_provider(2),
        )
        for candidate in transformed:
            register_candidate(candidate)

    for variable in variables:
        register_candidate(variable)
        register_with_operator_cycles(f"not({variable})")

    search_depth = max(2, generator._depth_from_var_count(len(variables)) + 2)
    target_candidate_count = max(required_options * generator.DISTRACTION_CANDIDATE_MULTIPLIER, 12)

    for depth in range(1, search_depth + 1):
        fetched = generator._get_formulas(
            bridge=bridge,
            depth=depth,
            variables=variables,
            use_all=False,
            timeout=timeout_provider(3),
            rng=rng,
        )
        for formula in fetched:
            register_candidate(formula)
        if len(candidates) >= target_candidate_count:
            break

    return candidates


def _pick_modified(
    question_prolog: str,
    variables,
    bridge: PrologBridge,
    filter_equiv_batch: Callable[[Sequence[str]], list[str]],
    target_atom_count: int | None = None,
    seed: int | None = None,
    timeout: int = 10,
    spoken_only: bool = False,
) -> tuple[str, int]:
    rng = random.Random(seed)

    def filter_candidates_batch(source: Sequence[str], seen: set[str]) -> list[str]:
        selected: list[str] = []
        for candidate in source:
            if not candidate or candidate == question_prolog or candidate in seen:
                continue
            if spoken_only and not generator._formula_is_spoken_friendly(candidate):
                continue
            if generator._has_adjacent_duplicate_atoms(candidate):
                continue
            if not generator._uses_vars(candidate, variables):
                continue
            if not generator._has_valid_binary_operator_count(generator._as_ast(candidate)):
                continue
            if not generator._has_atom_count(candidate, target_atom_count):
                continue
            if not generator._is_effective_transformation(question_prolog, candidate):
                continue
            seen.add(candidate)
            selected.append(candidate)
            if len(selected) >= generator.MAX_MODIFIED_EQUIV_CHECKS:
                break
        return selected

    def finalize_candidate(candidate: str, steps: int) -> tuple[str, int]:
        selected = generator._maybe_swap_and_or(candidate, rng)
        selected_steps = steps
        if generator._needs_extra_transformation(candidate):
            try:
                extra_raw = bridge.rewrite_formula(candidate, timeout=timeout)
            except Exception:
                extra_raw = []

            extra_candidates = [
                item
                for item in extra_raw
                if item
                and item != question_prolog
                and not generator._has_adjacent_duplicate_atoms(item)
                and generator._is_effective_transformation(candidate, item)
                and generator._uses_vars(item, variables)
                and generator._has_atom_count(item, target_atom_count)
            ]
            if extra_candidates:
                equivalent_extra = filter_equiv_batch(extra_candidates)
                if equivalent_extra:
                    selected = generator._maybe_swap_and_or(rng.choice(equivalent_extra), rng)
                    selected_steps += 1
        return selected, selected_steps

    def select_with_min_non_trivial(
        candidates: Sequence[str],
        base_steps: Callable[[int], int],
    ) -> tuple[str, int] | None:
        indexed = list(enumerate(candidates))
        rng.shuffle(indexed)
        for idx, candidate in indexed:
            selected, selected_steps = finalize_candidate(candidate, base_steps(idx))
            if generator._has_adjacent_duplicate_atoms(selected):
                continue
            if selected_steps < generator.MIN_NON_TRIVIAL_CORRECT_STEPS:
                continue
            if not generator._is_effective_transformation(question_prolog, selected):
                continue
            return selected, selected_steps
        return None

    try:
        path = bridge.rewrite_path(question_prolog, timeout=timeout)
    except Exception:
        path = []

    seen: set[str] = set()
    path_candidates = filter_candidates_batch(path, seen)

    ordered_candidates: list[str] = []
    if path_candidates:
        try:
            equivalent_set = set(filter_equiv_batch(path_candidates))
            ordered_candidates = [candidate for candidate in path_candidates if candidate in equivalent_set]
        except Exception:
            ordered_candidates = []

    if ordered_candidates:
        selected = select_with_min_non_trivial(ordered_candidates, lambda idx: idx + 1)
        if selected is not None:
            return selected

    fallback_raw = generator._safe_bridge_call(bridge.rewrite_formula, question_prolog, timeout=timeout)
    fallback_candidates = filter_candidates_batch(fallback_raw, seen)

    equivalent_fallbacks: list[str] = []
    if fallback_candidates:
        try:
            equivalent_set = set(filter_equiv_batch(fallback_candidates))
            equivalent_fallbacks = [candidate for candidate in fallback_candidates if candidate in equivalent_set]
        except Exception:
            equivalent_fallbacks = []

    if equivalent_fallbacks:
        selected = select_with_min_non_trivial(equivalent_fallbacks, lambda _idx: 1)
        if selected is not None:
            return selected

    raise RuntimeError("Nessuna formula modificata equivalente trovata")


def _pick_wrongs(
    question_prolog: str,
    correct_prolog: str,
    variables,
    target_atom_count: int | None,
    wrong_answers_count: int,
    operator_cycles: int | None,
    from_correct_answer: bool,
    bridge: PrologBridge,
    filter_wrong_batch: Callable[[Sequence[str]], list[str]],
    seed: int | None = None,
    timeout: int = 10,
    timeout_provider: Callable[[int], int] | None = None,
    spoken_only: bool = False,
) -> list[str]:
    rng = random.Random(seed)
    collected: list[str] = []
    seen = {question_prolog, correct_prolog}
    source_formula = correct_prolog if from_correct_answer else question_prolog
    distract_timeout = max(1, min(timeout, 3))
    candidate_limit = max(wrong_answers_count * generator.DISTRACTION_CANDIDATE_MULTIPLIER, 4)

    def current_timeout() -> int:
        if timeout_provider is None:
            return distract_timeout
        return max(1, min(distract_timeout, timeout_provider(distract_timeout)))

    def add_candidates(candidates) -> bool:
        unseen = [
            candidate
            for candidate in (candidates or [])
            if candidate
            and candidate not in seen
            and not generator._has_adjacent_duplicate_atoms(candidate)
            and generator._uses_vars(candidate, variables)
            and generator._has_valid_binary_operator_count(generator._as_ast(candidate))
            and generator._has_atom_count(candidate, target_atom_count)
        ]
        if spoken_only:
            unseen = [c for c in unseen if generator._formula_is_spoken_friendly(c)]
        if not unseen:
            return False

        expanded: list[str] = []
        for candidate in unseen:
            expanded.extend(
                _transform_answer_candidates(
                    formula=candidate,
                    bridge=bridge,
                    rng=rng,
                    operator_cycles=operator_cycles,
                    timeout_provider=current_timeout,
                )
            )

        expanded = [
            candidate
            for candidate in dict.fromkeys(expanded)
            if candidate
            and not generator._has_adjacent_duplicate_atoms(candidate)
            and generator._uses_vars(candidate, variables)
            and generator._has_valid_binary_operator_count(generator._as_ast(candidate))
            and generator._has_atom_count(candidate, target_atom_count)
        ]

        seen.update(expanded)
        wrong_candidates = filter_wrong_batch(expanded)
        for candidate in wrong_candidates:
            collected.append(candidate)

            if len(collected) >= wrong_answers_count:
                return True
        return False

    deterministic_sources: list[Callable[[], list[str]]] = []

    some_one_step = getattr(bridge, "some_step_neq", None)
    if callable(some_one_step):
        deterministic_sources.append(
            lambda: generator._safe_bridge_call(
                cast(Callable[..., object], some_one_step),
                source_formula,
                limit=candidate_limit,
                timeout=current_timeout(),
            )
        )
    else:
        deterministic_sources.append(
            lambda: generator._safe_bridge_call(
                bridge.all_step_neq,
                source_formula,
                timeout=current_timeout(),
            )
        )

    deterministic_sources.append(
        lambda: generator._safe_bridge_call(
            bridge.one_step_neq,
            source_formula,
            timeout=current_timeout(),
        )
    )

    some_multi_step = getattr(bridge, "some_neq", None)
    if callable(some_multi_step):
        deterministic_sources.append(
            lambda: generator._safe_bridge_call(
                cast(Callable[..., object], some_multi_step),
                source_formula,
                max_steps=generator.DEFAULT_DISTRACTOR_MAX_STEPS,
                limit=candidate_limit,
                timeout=current_timeout(),
            )
        )

    deterministic_sources.append(
        lambda: generator._safe_bridge_call(
            bridge.non_equivalent_distraction,
            source_formula,
            max_steps=generator.DEFAULT_DISTRACTOR_MAX_STEPS,
            timeout=current_timeout(),
        )
    )

    for source in deterministic_sources:
        if add_candidates(source()):
            rng.shuffle(collected)
            return collected[:wrong_answers_count]

    rng.shuffle(collected)

    if len(collected) >= wrong_answers_count:
        return collected[:wrong_answers_count]

    raise RuntimeError(
        f"Non ci sono abbastanza distractor errati: richiesti {wrong_answers_count}, trovati {len(collected)}"
    )


def multiple_questions(
    questions: Sequence[dict[str, Any]],
    seed: int | None = None,
    bridge: PrologBridge | None = None,
) -> dict[str, Any]:
    """Batch orchestration for multiple question generation.

    This delegates to functions in `generator` and handles retries, deduplication
    and envelope formatting. Kept here so `generator` only contains exercise
    building logic.
    """
    if not questions:
        raise ValueError("questions non può essere vuoto")

    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)
    logger.info("multiple_questions start: count=%d seed=%s", len(questions), seed)

    operation_aliases = {
        "build_exercise_from_depth": "build_ex_depth",
        "build_truth_value_options_question": "build_tvq",
    }

    supported_operations = {
        "build_exercise",
        "build_ex_depth",
        "build_tvq",
        "build_logical_consequence_question",
        "build_translation_question",
    }
    max_attempts = 4
    used_question_keys: set[str] = set()

    envelopes: list[dict[str, Any]] = []
    for index, item in enumerate(questions):
        envelope: dict[str, Any] = {"index": index}
        attempts = 0
        try:
            if not isinstance(item, dict):
                raise ValueError("Ogni elemento di questions deve essere un oggetto")

            operation = item.get("operation")
            if not isinstance(operation, str) or not operation:
                raise ValueError("Ogni elemento di questions deve contenere una stringa operation")

            normalized_operation = operation_aliases.get(operation, operation)
            if normalized_operation not in supported_operations:
                raise ValueError(
                    f"Operazione non supportata in multiple_questions: {operation}. "
                    f"Operazioni supportate: {sorted(supported_operations | set(operation_aliases))}"
                )

            payload = item.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("Ogni elemento di questions deve contenere un payload oggetto")

            normalized_payload = dict(payload)
            normalized_payload.pop("bridge", None)
            if seed is not None and "seed" not in normalized_payload:
                normalized_payload["seed"] = seed

            last_error: Exception | None = None
            used_payload: dict[str, Any] = dict(normalized_payload)
            result: Any = None
            question_key: str | None = None

            for attempt in range(1, max_attempts + 1):
                attempts = attempt
                attempt_payload = dict(normalized_payload)
                if isinstance(attempt_payload.get("seed"), int):
                    attempt_payload["seed"] = int(attempt_payload["seed"]) + (attempt - 1)

                try:
                    if normalized_operation == "build_exercise":
                        result = generator.build_exercise(bridge=bridge, **attempt_payload)
                    elif normalized_operation == "build_ex_depth":
                        result = generator.build_ex_depth(bridge=bridge, **attempt_payload)
                    elif normalized_operation == "build_tvq":
                        result = generator.build_tvq(bridge=bridge, **attempt_payload)
                    elif normalized_operation == "build_logical_consequence_question":
                        result = generator.build_logical_consequence_question(bridge=bridge, **attempt_payload)
                    else:
                        result = generator.build_translation_question(**attempt_payload)

                    question_key = generator._question_identity_key(normalized_operation, result)
                    if question_key in used_question_keys:
                        last_error = RuntimeError("Domanda duplicata nel batch")
                        continue

                    used_payload = attempt_payload
                    used_question_keys.add(question_key)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    logger.exception("attempt %d failed for operation %s: %s", attempt, normalized_operation, exc)
                    continue

            if last_error is not None:
                raise last_error

            envelope.update(
                {
                    "operation": normalized_operation,
                    "request": used_payload,
                    "status": "ok",
                    "attempts": attempts,
                    "result": result,
                }
            )
        except Exception as exc:
            logger.warning("question generation failed: operation=%s index=%d error=%s", item.get("operation") if isinstance(item, dict) else None, index, exc)
            envelope.update(
                {
                    "operation": item.get("operation") if isinstance(item, dict) else None,
                    "request": item.get("payload") if isinstance(item, dict) else None,
                    "status": "failed",
                    "attempts": attempts if attempts > 0 else 1,
                    "error": str(exc),
                    "result": None,
                }
            )

        envelopes.append(envelope)

    rng.shuffle(envelopes)
    success_count = sum(1 for envelope in envelopes if envelope.get("status") == "ok")
    failed_count = len(envelopes) - success_count
    batch = {
        "type": "multiple_questions",
        "seed": seed,
        "count": len(envelopes),
        "success_count": success_count,
        "failed_count": failed_count,
        "questions": envelopes,
    }
    # Ensure generator-level invariant checking is used
    generator._ensure_keys(batch, ["type", "count", "success_count", "failed_count", "questions"])
    # Register orchestrator implementations so generator can call them internally
    generator._transform_answer_candidates = _transform_answer_candidates
    generator._collect_candidate_formulas = _collect_candidate_formulas
    generator._pick_modified = _pick_modified
    generator._pick_wrongs = _pick_wrongs
    return batch


# Install the orchestrator helpers on import so the public generator entry points
# can work without requiring an extra bootstrap call.
generator._transform_answer_candidates = _transform_answer_candidates
generator._collect_candidate_formulas = _collect_candidate_formulas
generator._pick_modified = _pick_modified
generator._pick_wrongs = _pick_wrongs

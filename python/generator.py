from __future__ import annotations

# Serializzazione output e utilita numeriche/temporali per campionamento.
import json
import math
import random
import time
# Tipi usati nelle firme pubbliche e nei callback interni.
from typing import Any, Callable, Sequence, cast

# Nodi AST logici per trasformazioni e riscritture locali.
from ast_logic import And, Iff, Imp, Not, Or, Var
# Bridge Prolog e utility di conversione usate dal generatore.
from prolog_bridge import PrologBridge, collect_variables, formula_to_dict, from_prolog, get_default_bridge, to_prolog


DEFAULT_VARIABLES = ("p", "q", "r", "s", "t")
DEFAULT_FORMULA_SAMPLE_LIMIT = 24
DEFAULT_FORMULA_FETCH_MULTIPLIER = 8
FORMULA_HEADS = ("and", "or", "imp", "iff", "not")
MAX_MODIFIED_EQUIV_CHECKS = 8
DISTRACTION_CANDIDATE_MULTIPLIER = 4


def _req_int_ge(name: str, value: int, minimum: int) -> None:
    """Verifica che un valore numerico sia un intero sopra una soglia minima."""
    if not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} deve essere un intero >= {minimum}")


def _ensure_keys(payload: dict[str, Any], required: Sequence[str]) -> None:
    """Verifica che il payload generato contenga tutte le chiavi richieste."""
    missing = [key for key in required if key not in payload]
    if missing:
        raise RuntimeError(f"Output incompleto: chiavi mancanti {missing}")


def _default_vars(predicate_count: int) -> list[str]:
    """Restituisce una lista di variabili di default per la cardinalita richiesta."""
    if predicate_count <= 0:
        raise ValueError("predicate_count deve essere >= 1")

    if predicate_count <= len(DEFAULT_VARIABLES):
        return list(DEFAULT_VARIABLES[:predicate_count])

    variables: list[str] = list(DEFAULT_VARIABLES)
    next_index = 1
    while len(variables) < predicate_count:
        variables.append(f"p{next_index}")
        next_index += 1
    return variables


def _normalize_vars(variables: Sequence[str]) -> list[str]:
    """Rimuove duplicati e normalizza i nomi variabile forniti in input."""
    normalized = [variable for variable in dict.fromkeys(variables) if variable]
    if not normalized:
        raise ValueError("variables non può essere vuoto")
    return normalized


def _max_vars_for_depth(depth: int) -> int:
    """Calcola il numero teorico massimo di variabili distinte a una certa profondita."""
    return 2**depth


def _depth_from_var_count(variables_count: int) -> int:
    """Stima una profondita ragionevole a partire dal numero di variabili."""
    if variables_count <= 1:
        return 0
    # Mantiene la profondita automatica abbastanza espressiva da evitare
    # formule troppo banali (es. una sola connettiva binaria con due variabili).
    return max(2, math.ceil(math.log2(variables_count)))


def _validate_vars(depth: int, variables: Sequence[str]) -> list[str]:
    """Verifica che tutte le variabili possano comparire alla profondita selezionata."""
    normalized = _normalize_vars(variables)
    max_distinct_variables = _max_vars_for_depth(depth)

    if len(normalized) > max_distinct_variables:
        raise ValueError(
            "La profondita richiesta non consente di usare tutte le variabili fornite: "
            f"depth={depth}, variabili richieste={len(normalized)}, massimo utilizzabile={max_distinct_variables}"
        )

    return normalized


def _resolve_depth(depth: int | None, variables: Sequence[str]) -> tuple[int, list[str]]:
    """Risolve la profondita effettiva e restituisce le variabili validate."""
    normalized = _normalize_vars(variables)
    resolved_depth = _depth_from_var_count(len(normalized)) if depth is None else depth

    if resolved_depth < 0:
        raise ValueError("depth deve essere >= 0")

    validated = _validate_vars(resolved_depth, normalized)
    return resolved_depth, validated


def _uses_vars(formula: Any, variables: Sequence[str]) -> bool:
    """Controlla se la formula candidata usa esattamente le variabili richieste."""
    expr = _as_ast(formula)
    return sorted(collect_variables(expr)) == sorted(variables)


def _rename_vars(formula: Any, mapping: dict[str, str]) -> str:
    """Applica una mappa di rinomina variabili e restituisce testo Prolog."""
    expr = _as_ast(formula)

    def renamed(node):
        if isinstance(node, Var):
            return Var(mapping.get(node.name, node.name))
        if isinstance(node, Not):
            return Not(renamed(node.expr))
        if isinstance(node, And):
            return And(renamed(node.left), renamed(node.right))
        if isinstance(node, Or):
            return Or(renamed(node.left), renamed(node.right))
        if isinstance(node, Imp):
            return Imp(renamed(node.left), renamed(node.right))
        if isinstance(node, Iff):
            return Iff(renamed(node.left), renamed(node.right))
        return node

    return to_prolog(renamed(expr))


def _permute_vars(
    formulas: Sequence[str],
    variables: Sequence[str],
    rng: random.Random,
) -> list[str]:
    """Permuta casualmente i nomi variabile per ridurre bias di denominazione."""
    if len(variables) <= 1:
        return list(formulas)

    source = list(variables)
    target = list(variables)
    rng.shuffle(target)

    # Evita la mappatura identita per ridurre bias sistematici nei nomi variabile.
    if target == source:
        target = target[1:] + target[:1]

    mapping = dict(zip(source, target, strict=False))
    renamed = [_rename_vars(formula, mapping) for formula in formulas]
    return list(dict.fromkeys(renamed))


def _flatten_associative(node, op_cls):
    """Appiattisce operatori associativi annidati (and/or) in una lista di termini."""
    if isinstance(node, op_cls):
        return _flatten_associative(node.left, op_cls) + _flatten_associative(node.right, op_cls)
    return [node]


def _build_balanced(terms: list[Any], op_cls, rng: random.Random):
    """Ricostruisce un albero binario bilanciato da una lista di termini."""
    if len(terms) == 1:
        return terms[0]

    split = rng.randint(1, len(terms) - 1)
    left = _build_balanced(terms[:split], op_cls, rng)
    right = _build_balanced(terms[split:], op_cls, rng)
    return op_cls(left, right)


def _scatter_vars(formulas: Sequence[str], rng: random.Random) -> list[str]:
    """Mescola blocchi associativi per diversificare le strutture delle formule."""
    def transform(node):
        if isinstance(node, Var):
            return node
        if isinstance(node, Not):
            return Not(transform(node.expr))
        if isinstance(node, Imp):
            return Imp(transform(node.left), transform(node.right))
        if isinstance(node, Iff):
            left = transform(node.left)
            right = transform(node.right)
            if rng.random() < 0.5:
                left, right = right, left
            return Iff(left, right)
        if isinstance(node, (And, Or)):
            op_cls = type(node)
            terms = [transform(term) for term in _flatten_associative(node, op_cls)]
            rng.shuffle(terms)
            return _build_balanced(terms, op_cls, rng)
        return node

    scattered: list[str] = []
    for formula in formulas:
        ast = _as_ast(formula)
        scattered.append(to_prolog(transform(ast)))
    return list(dict.fromkeys(scattered))


def _formula_head(formula: Any) -> str:
    """Estrae l operatore principale di una formula."""
    prolog_formula = _as_prolog(formula).strip()
    if "(" not in prolog_formula:
        return "var"
    return prolog_formula.split("(", 1)[0]


def _pick_by_head(
    formulas: Sequence[str],
    rng: random.Random,
    *,
    prefer_or: bool = False,
) -> str:
    """Seleziona una formula con strategia casuale bilanciata per operatore."""
    buckets: dict[str, list[str]] = {}
    for formula in formulas:
        buckets.setdefault(_formula_head(formula), []).append(formula)

    available_heads = [head for head, items in buckets.items() if items]
    if not available_heads:
        raise RuntimeError("Nessuna formula disponibile")

    # Piccolo boost opzionale per OR su formule grandi, dove si percepisce
    # piu facilmente uno sbilanciamento verso AND.
    weighted_heads: list[str] = []
    for head in available_heads:
        weight = 2 if (prefer_or and head == "or") else 1
        weighted_heads.extend([head] * weight)

    selected_head = rng.choice(weighted_heads)
    return rng.choice(buckets[selected_head])


def _diversify_sample(formulas: Sequence[str], limit: int, rng: random.Random) -> list[str]:
    """Costruisce un campione diversificato bilanciato tra operatori principali."""
    unique_formulas = list(dict.fromkeys(formulas))
    buckets: dict[str, list[str]] = {}

    for formula in unique_formulas:
        head = _formula_head(formula)
        buckets.setdefault(head, []).append(formula)

    heads = list(buckets.keys())
    rng.shuffle(heads)

    for head in heads:
        rng.shuffle(buckets[head])

    balanced: list[str] = []
    while len(balanced) < limit:
        progressed = False
        for head in heads:
            if not buckets[head]:
                continue
            balanced.append(buckets[head].pop())
            progressed = True
            if len(balanced) >= limit:
                break
        if not progressed:
            break

    return balanced


def _get_formulas(
    *,
    bridge: PrologBridge,
    depth: int,
    variables: Sequence[str],
    use_all: bool,
    timeout: int,
    rng: random.Random,
) -> list[str]:
    """Recupera formule candidate per profondita/variabili con fallback progressivi."""
    def safe_fetch(callable_fn, *args, **kwargs):
        try:
            return callable_fn(*args, **kwargs)
        except Exception:
            return []

    if use_all:
        if hasattr(bridge, "all_depth_allvars"):
            formulas = bridge.all_depth_allvars(depth, list(variables), timeout=timeout)
        else:
            formulas = bridge.all_depth(depth, list(variables), timeout=timeout)
    else:
        formulas: list[str] = []
        per_head_limit = 4
        per_head_timeout = 1
        head_sampling_budget = max(1.0, min(float(timeout), 3.0))
        started = time.monotonic()

        # 1) Privilegia prima il campionamento per head, cosi da non fissarsi
        # sul prefisso iniziale dell'enumerazione Prolog (spesso tutto 'and').
        if hasattr(bridge, "some_depth_head"):
            heads = list(FORMULA_HEADS)
            rng.shuffle(heads)
            for head in heads:
                if (time.monotonic() - started) >= head_sampling_budget:
                    break
                formulas.extend(
                    safe_fetch(
                        bridge.some_depth_head,
                        depth,
                        list(variables),
                        head=head,
                        limit=per_head_limit,
                        timeout=per_head_timeout,
                    )
                )

        # Integra con formule bilanciate per or/and/iff in modo da includere
        # strutture piu ricche (es. or(and(p,q),and(r,or(s,t)))) oltre alle
        # forme tipiche con variabile isolata (or(p,blocco_grande)).
        if (
            depth >= 2
            and hasattr(bridge, "some_depth_hbal")
        ):
            balanced_heads = ["or", "and", "iff"]
            rng.shuffle(balanced_heads)
            for head in balanced_heads:
                if (time.monotonic() - started) >= head_sampling_budget:
                    break
                formulas.extend(
                    safe_fetch(
                        bridge.some_depth_hbal,
                        depth,
                        list(variables),
                        head=head,
                        limit=per_head_limit,
                        timeout=per_head_timeout,
                    )
                )

        # 2) Riempi la capacita residua con campionamento vincolato generico.
        target_pool_size = max(DEFAULT_FORMULA_SAMPLE_LIMIT * 2, len(FORMULA_HEADS) * 6)
        remaining = max(0, target_pool_size - len(formulas))
        if remaining > 0:
            if hasattr(bridge, "some_depth_allvars"):
                formulas.extend(
                    safe_fetch(
                        bridge.some_depth_allvars,
                        depth,
                        list(variables),
                        limit=remaining,
                        timeout=timeout,
                    )
                )
            elif hasattr(bridge, "some_depth"):
                formulas.extend(
                    safe_fetch(
                        bridge.some_depth,
                        depth,
                        list(variables),
                        limit=remaining,
                        timeout=timeout,
                    )
                )
            else:
                formulas.extend(safe_fetch(bridge.formula_of_depth, depth, list(variables), timeout=timeout))

    filtered_formulas = [formula for formula in formulas if _uses_vars(formula, variables)]

    # L'ordine di enumerazione Prolog e deterministico e puo introdurre bias
    # sui nomi (es. 'a' ricorre spesso sotto lo stesso operatore). Permuta
    # casualmente le etichette variabile prima della selezione finale.
    if isinstance(bridge, PrologBridge):
        filtered_formulas = _permute_vars(filtered_formulas, variables, rng)
        filtered_formulas = _scatter_vars(filtered_formulas, rng)

    if use_all:
        return filtered_formulas

    return _diversify_sample(filtered_formulas, DEFAULT_FORMULA_SAMPLE_LIMIT, rng)


def formula_depth(expr) -> int:
    """Calcola la profondita AST di una formula logica."""
    if hasattr(expr, "name") and not hasattr(expr, "expr") and not hasattr(expr, "left"):
        return 0
    if hasattr(expr, "expr"):
        return 1 + formula_depth(expr.expr)
    if hasattr(expr, "left") and hasattr(expr, "right"):
        return 1 + max(formula_depth(expr.left), formula_depth(expr.right))
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


def formula_size(expr) -> int:
    """Calcola il numero di nodi AST di una formula logica."""
    if hasattr(expr, "name") and not hasattr(expr, "expr") and not hasattr(expr, "left"):
        return 1
    if hasattr(expr, "expr"):
        return 1 + formula_size(expr.expr)
    if hasattr(expr, "left") and hasattr(expr, "right"):
        return 1 + formula_size(expr.left) + formula_size(expr.right)
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


def formula_atom_count(expr) -> int:
    """Calcola il numero di atomi presenti in una formula logica."""
    if hasattr(expr, "name") and not hasattr(expr, "expr") and not hasattr(expr, "left"):
        return 1
    if hasattr(expr, "expr"):
        return formula_atom_count(expr.expr)
    if hasattr(expr, "left") and hasattr(expr, "right"):
        return formula_atom_count(expr.left) + formula_atom_count(expr.right)
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


def formula_metadata(expr) -> dict:
    """Costruisce i metadati (variabili/profondita/dimensione/prolog) di una formula."""
    data = {
        "variables": sorted(collect_variables(expr)),
        "depth": formula_depth(expr),
        "size": formula_size(expr),
        "formula_prolog": to_prolog(expr),
    }
    _ensure_keys(data, ["variables", "depth", "size", "formula_prolog"])
    return data


def formula_payload(expr, **extra) -> dict:
    """Costruisce un payload serializzabile per una formula con campi extra opzionali."""
    payload = {
        "formula": formula_to_dict(expr),
        **formula_metadata(expr),
    }
    payload.update(extra)
    _ensure_keys(payload, ["formula", "variables", "depth", "size", "formula_prolog"])
    return payload


def _ensure_bridge(bridge: PrologBridge | None = None) -> PrologBridge:
    """Restituisce il bridge fornito o crea pigramente quello di default."""
    return bridge or get_default_bridge()


def _operator_cycle_count(formula: Any, rng: random.Random, max_cycles: int | None = None) -> int:
    """Sceglie un numero di cicli compreso tra meta e massimo degli atomi disponibili."""
    atom_count = formula_atom_count(_as_ast(formula))
    if atom_count <= 0:
        return 0

    upper_bound = atom_count if max_cycles is None else min(atom_count, max_cycles)
    upper_bound = max(1, upper_bound)
    lower_bound = max(1, math.ceil(upper_bound / 2))
    return rng.randint(lower_bound, upper_bound)


def _as_prolog(expr: Any) -> str:
    """Converte l input formula nel formato stringa Prolog."""
    return expr if isinstance(expr, str) else to_prolog(expr)


def _as_ast(expr: Any):
    """Converte l input formula in AST quando necessario."""
    return from_prolog(expr) if isinstance(expr, str) else expr


def _formula_entry(expr: Any, **extra) -> dict:
    """Crea una voce formula standardizzata per le risposte API."""
    return formula_payload(_as_ast(expr), **extra)


def generate_formula(
    depth: int | None = None,
    variables: Sequence[str] = DEFAULT_VARIABLES,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
):
    """Genera una formula rispettando vincoli di profondita e variabili."""
    _req_int_ge("timeout", int(timeout), 1)
    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)

    depth, variables = _resolve_depth(depth, variables)

    formulas = _get_formulas(
        bridge=bridge,
        depth=depth,
        variables=variables,
        use_all=use_all,
        timeout=timeout,
        rng=rng,
    )

    if not formulas:
        raise RuntimeError("Nessuna formula generata che usi tutte le variabili richieste")

    selected = _pick_by_head(formulas, rng, prefer_or=(len(variables) >= 5))
    if not selected:
        raise RuntimeError("Formula generata non valida")
    return selected


def generate_formula_json(
    depth: int | None = None,
    variables: Sequence[str] = DEFAULT_VARIABLES,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
) -> dict:
    """Genera una formula e restituisce un payload pronto per JSON."""
    _req_int_ge("timeout", int(timeout), 1)
    expr = _as_ast(generate_formula(
        depth=depth,
        variables=variables,
        use_all=use_all,
        timeout=timeout,
        seed=seed,
        bridge=bridge,
    ))
    result = formula_payload(expr, source="prolog_depth")
    _ensure_keys(result, ["formula", "variables", "depth", "size", "formula_prolog", "source"])
    return result


def _pick_modified(
    question_prolog: str,
    variables,
    bridge: PrologBridge,
    filter_equiv_batch: Callable[[Sequence[str]], list[str]],
    seed: int | None = None,
    timeout: int = 10,
) -> tuple[str, int]:
    """Seleziona una formula equivalente riscritta e stima i passi di rewrite."""
    rng = random.Random(seed)

    try:
        path = bridge.rewrite_path(question_prolog, timeout=timeout)
    except Exception:
        path = []

    seen: set[str] = set()
    path_candidates: list[str] = []
    for candidate in path:
        if not candidate or candidate == question_prolog or candidate in seen:
            continue
        if not _uses_vars(candidate, variables):
            continue
        seen.add(candidate)
        path_candidates.append(candidate)
        if len(path_candidates) >= MAX_MODIFIED_EQUIV_CHECKS:
            break

    ordered_candidates: list[str] = []
    if path_candidates:
        try:
            equivalent_set = set(filter_equiv_batch(path_candidates))
            ordered_candidates = [candidate for candidate in path_candidates if candidate in equivalent_set]
        except Exception:
            ordered_candidates = []

    if ordered_candidates:
        selected_steps = rng.randint(1, len(ordered_candidates))
        return ordered_candidates[selected_steps - 1], selected_steps

    candidates = bridge.rewrite_formula(question_prolog, timeout=timeout)
    fallback_candidates: list[str] = []
    for candidate in candidates:
        if not candidate or candidate == question_prolog or candidate in seen:
            continue
        if not _uses_vars(candidate, variables):
            continue
        seen.add(candidate)
        fallback_candidates.append(candidate)
        if len(fallback_candidates) >= MAX_MODIFIED_EQUIV_CHECKS:
            break

    equivalent_fallbacks: list[str] = []
    if fallback_candidates:
        try:
            equivalent_set = set(filter_equiv_batch(fallback_candidates))
            equivalent_fallbacks = [candidate for candidate in fallback_candidates if candidate in equivalent_set]
        except Exception:
            equivalent_fallbacks = []

    if equivalent_fallbacks:
        return rng.choice(equivalent_fallbacks), 1

    raise RuntimeError("Nessuna formula modificata equivalente trovata")


def _pick_wrongs(
    question_prolog: str,
    correct_prolog: str,
    variables,
    wrong_answers_count: int,
    max_steps: int,
    operator_cycles: int | None,
    bridge: PrologBridge,
    filter_wrong_batch: Callable[[Sequence[str]], list[str]],
    seed: int | None = None,
    timeout: int = 10,
    timeout_provider: Callable[[int], int] | None = None,
) -> list[str]:
    """Raccoglie distractor non equivalenti per una formula domanda."""
    rng = random.Random(seed)
    collected: list[str] = []
    seen = {question_prolog, correct_prolog}
    distract_timeout = max(1, min(timeout, 3))
    candidate_limit = max(wrong_answers_count * DISTRACTION_CANDIDATE_MULTIPLIER, 4)

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
            and _uses_vars(candidate, variables)
        ]
        if not unseen:
            return False

        expanded = list(unseen)
        if operator_cycles != 0:
            apply_cycles = getattr(bridge, "apply_operator_cycles", None)
            if callable(apply_cycles):
                cycle_fn = cast(Callable[..., list[str]], apply_cycles)
                for candidate in unseen:
                    candidate_cycles = _operator_cycle_count(candidate, rng, operator_cycles)
                    if candidate_cycles <= 0:
                        continue
                    enriched_candidates = safe_call(
                        cycle_fn,
                        candidate,
                        cycles=candidate_cycles,
                        timeout=current_timeout(),
                    )
                    for enriched in enriched_candidates:
                        if (
                            enriched
                            and enriched not in seen
                            and _uses_vars(enriched, variables)
                        ):
                            expanded.append(enriched)

        expanded = list(dict.fromkeys(expanded))

        seen.update(expanded)
        wrong_candidates = filter_wrong_batch(expanded)
        for candidate in wrong_candidates:
            collected.append(candidate)

            if len(collected) >= wrong_answers_count:
                return True
        return False

    def safe_call(fn: Callable[..., object], *args, **kwargs) -> list[str]:
        try:
            result = fn(*args, **kwargs)
        except Exception:
            return []
        return result if isinstance(result, list) else []

    # 1. Sorgenti deterministiche / elenco
    deterministic_sources: list[Callable[[], list[str]]] = []

    some_one_step = getattr(bridge, "some_step_neq", None)
    if callable(some_one_step):
        deterministic_sources.append(
            lambda: safe_call(
                some_one_step,
                question_prolog,
                limit=candidate_limit,
                timeout=current_timeout(),
            )
        )
    else:
        deterministic_sources.append(
            lambda: safe_call(
                bridge.all_step_neq,
                question_prolog,
                timeout=current_timeout(),
            )
        )

    deterministic_sources.append(
        lambda: safe_call(
            bridge.one_step_neq,
            question_prolog,
            timeout=current_timeout(),
        )
    )

    some_multi_step = getattr(bridge, "some_neq", None)
    if callable(some_multi_step):
        deterministic_sources.append(
            lambda: safe_call(
                some_multi_step,
                question_prolog,
                max_steps=max_steps,
                limit=candidate_limit,
                timeout=current_timeout(),
            )
        )

    deterministic_sources.append(
        lambda: safe_call(
            bridge.non_equivalent_distraction,
            question_prolog,
            max_steps=max_steps,
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


def build_tvq(
    predicate_count: int,
    true_options_count: int,
    false_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
) -> dict:
    """Costruisce una domanda vero/falso da informazioni sui predicati."""
    _req_int_ge("predicate_count", predicate_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    if true_options_count < 1:
        raise ValueError("true_options_count deve essere >= 1")
    if false_options_count < 1:
        raise ValueError("false_options_count deve essere >= 1")
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)

    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)
    total_timeout = max(1, int(timeout))
    deadline = time.monotonic() + total_timeout
    variables = _default_vars(predicate_count)
    required_options = true_options_count + false_options_count

    def remaining_timeout(cap: int | None = None) -> int:
        left = max(1, int(math.ceil(deadline - time.monotonic())))
        return min(left, cap) if cap is not None else left

    valuations = bridge.assignment(variables, timeout=remaining_timeout(total_timeout))
    if not valuations:
        raise RuntimeError("Nessuna assegnazione disponibile per i predicati richiesti")
    rng.shuffle(valuations)

    candidates: list[str] = []
    seen_candidates: set[str] = set()
    allowed_variables = set(variables)

    def register_candidate(formula: str) -> None:
        if not formula or formula in seen_candidates:
            return
        used_variables = collect_variables(_as_ast(formula))
        if not used_variables:
            return
        if not used_variables.issubset(allowed_variables):
            return
        seen_candidates.add(formula)
        candidates.append(formula)

    def register_with_operator_cycles(formula: str) -> None:
        register_candidate(formula)
        if operator_cycles == 0:
            return
        try:
            cycle_count = _operator_cycle_count(formula, rng, operator_cycles)
            enriched_candidates = bridge.apply_operator_cycles(
                formula,
                cycles=cycle_count,
                timeout=remaining_timeout(2),
            )
        except Exception:
            return

        for enriched in enriched_candidates:
            register_candidate(enriched)

    for variable in variables:
        register_candidate(variable)
        register_with_operator_cycles(f"not({variable})")

    search_depth = max(2, _depth_from_var_count(predicate_count) + 2)
    target_candidate_count = max(required_options * DISTRACTION_CANDIDATE_MULTIPLIER, 12)

    for depth in range(1, search_depth + 1):
        fetched = _get_formulas(
            bridge=bridge,
            depth=depth,
            variables=variables,
            use_all=False,
            timeout=remaining_timeout(3),
            rng=rng,
        )
        for formula in fetched:
            register_candidate(formula)
        if len(candidates) >= target_candidate_count:
            break

    if len(candidates) < required_options:
        raise RuntimeError(
            "Non ci sono abbastanza formule candidate per costruire le opzioni richieste"
        )

    for valuation in valuations:
        true_candidates: list[str] = []
        false_candidates: list[str] = []

        shuffled_candidates = list(candidates)
        rng.shuffle(shuffled_candidates)

        for candidate in shuffled_candidates:
            result = bridge.eval(candidate, valuation, timeout=remaining_timeout(2))
            if result:
                true_candidates.append(candidate)
            else:
                false_candidates.append(candidate)

            if len(true_candidates) >= true_options_count and len(false_candidates) >= false_options_count:
                break

        if len(true_candidates) < true_options_count or len(false_candidates) < false_options_count:
            continue

        selected_true = rng.sample(true_candidates, true_options_count)
        selected_false = rng.sample(false_candidates, false_options_count)

        true_entries = [
            _formula_entry(formula, label=f"opzione vera n{index}", is_true=True)
            for index, formula in enumerate(selected_true, start=1)
        ]
        false_entries = [
            _formula_entry(formula, label=f"opzione falsa n{index}", is_true=False)
            for index, formula in enumerate(selected_false, start=1)
        ]

        options = true_entries + false_entries
        rng.shuffle(options)

        result = {
            "type": "truth_value_options_question",
            "predicate_count": predicate_count,
            "true_options_count": true_options_count,
            "false_options_count": false_options_count,
            "variables": variables,
            "information": list(valuation),
            "options": options,
            "true_options": true_entries,
            "false_options": false_entries,
            "source": "prolog_assignment_and_eval",
        }

        for index, option in enumerate(options, start=1):
            result[f"option_{index}"] = option

        _ensure_keys(result, ["information", "options", "true_options", "false_options", "variables"])
        return result

    raise RuntimeError(
        "Impossibile trovare una assegnazione con abbastanza opzioni vere e false distinte"
    )


def build_exercise(
    expr,
    wrong_answers_count: int = 3,
    max_steps: int = 2,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
    seed: int | None = None,
    timeout: int = 10,
) -> dict:
    """Costruisce un esercizio con formula originale, modificata e distrazioni."""
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    _req_int_ge("max_steps", max_steps, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    _req_int_ge("timeout", int(timeout), 1)
    bridge = _ensure_bridge(bridge)

    question_prolog = to_prolog(expr) if not isinstance(expr, str) else expr
    question_expr = from_prolog(question_prolog)
    variables = sorted(collect_variables(question_expr))
    total_timeout = max(1, int(timeout))
    deadline = time.monotonic() + total_timeout
    check_timeout = max(1, min(total_timeout, 2))
    equiv_cache: dict[str, bool] = {}
    not_equiv_cache: dict[str, bool] = {}

    def remaining_timeout(cap: int | None = None) -> int:
        left = max(1, int(math.ceil(deadline - time.monotonic())))
        return min(left, cap) if cap is not None else left

    def filter_equiv_batch(candidates: Sequence[str]) -> list[str]:
        unresolved = [candidate for candidate in candidates if candidate not in equiv_cache]
        if unresolved:
            try:
                equivalent = bridge.filter_equivalent(
                    question_prolog,
                    unresolved,
                    vars_list=variables,
                    timeout=remaining_timeout(check_timeout),
                )
                equivalent_set = set(equivalent)
                for candidate in unresolved:
                    equiv_cache[candidate] = candidate in equivalent_set
            except Exception:
                for candidate in unresolved:
                    try:
                        equiv_cache[candidate] = bridge.equiv(
                            question_prolog,
                            candidate,
                            vars_list=variables,
                            timeout=remaining_timeout(check_timeout),
                        )
                    except Exception:
                        equiv_cache[candidate] = False

        return [candidate for candidate in candidates if equiv_cache.get(candidate, False)]

    def filter_wrong_batch(candidates: Sequence[str]) -> list[str]:
        unresolved = [candidate for candidate in candidates if candidate not in not_equiv_cache]
        if unresolved:
            try:
                wrong = bridge.filter_non_equivalent(
                    question_prolog,
                    unresolved,
                    vars_list=variables,
                    timeout=remaining_timeout(check_timeout),
                )
                wrong_set = set(wrong)
                for candidate in unresolved:
                    not_equiv_cache[candidate] = candidate in wrong_set
            except Exception:
                for candidate in unresolved:
                    try:
                        not_equiv_cache[candidate] = bridge.not_equiv(
                            question_prolog,
                            candidate,
                            vars_list=variables,
                            timeout=remaining_timeout(check_timeout),
                        )
                    except Exception:
                        not_equiv_cache[candidate] = False

        return [candidate for candidate in candidates if not_equiv_cache.get(candidate, False)]

    modified_prolog, rewrite_steps = _pick_modified(
        question_prolog=question_prolog,
        variables=variables,
        bridge=bridge,
        filter_equiv_batch=filter_equiv_batch,
        seed=seed,
        timeout=remaining_timeout(total_timeout),
    )

    if modified_prolog == question_prolog:
        raise RuntimeError("La formula modificata coincide con la formula originale")

    wrong_selected = _pick_wrongs(
        question_prolog=question_prolog,
        correct_prolog=modified_prolog,
        variables=variables,
        wrong_answers_count=wrong_answers_count,
        max_steps=max_steps,
        operator_cycles=operator_cycles,
        bridge=bridge,
        filter_wrong_batch=filter_wrong_batch,
        seed=seed,
        timeout=remaining_timeout(total_timeout),
        timeout_provider=remaining_timeout,
    )

    original_formula = _formula_entry(question_expr, label="formula originale")
    modified_formula = _formula_entry(
        modified_prolog,
        label="formula modificata",
        steps=rewrite_steps,
    )
    distractions = [
        _formula_entry(candidate, label=f"formula distrazione n{index}")
        for index, candidate in enumerate(wrong_selected, start=1)
    ]

    exercise = {
        "original_formula": original_formula,
        "modified_formula": modified_formula,
        "variables": variables,
        "depth": formula_depth(question_expr),
        "size": formula_size(question_expr),
        "max_steps": max_steps,
        "rewrite_steps": rewrite_steps,
        "source": "prolog_builder",
        "question": original_formula["formula"],
        "question_prolog": question_prolog,
        "correct_answer": modified_formula["formula"],
        "correct_answer_prolog": modified_prolog,
        "wrong_answers": [entry["formula"] for entry in distractions],
        "wrong_answers_prolog": wrong_selected,
    }

    for index, entry in enumerate(distractions, start=1):
        exercise[f"distraction_{index}"] = entry

    _ensure_keys(exercise, ["original_formula", "modified_formula", "wrong_answers", "wrong_answers_prolog"])
    if len(exercise["wrong_answers_prolog"]) < wrong_answers_count:
        raise RuntimeError("Postcondizione fallita: distractor insufficienti")
    return exercise


def build_ex_depth(
    depth: int | None = None,
    variables: Sequence[str] = DEFAULT_VARIABLES,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    wrong_answers_count: int = 3,
    max_steps: int = 2,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
) -> dict:
    """Costruisce un esercizio a partire da profondita e vincoli sulle variabili."""
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    _req_int_ge("max_steps", max_steps, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    _req_int_ge("timeout", int(timeout), 1)
    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)
    total_timeout = max(1, int(timeout))
    deadline = time.monotonic() + total_timeout

    def remaining_timeout(cap: int | None = None) -> int:
        left = max(1, int(math.ceil(deadline - time.monotonic())))
        return min(left, cap) if cap is not None else left

    depth, variables = _resolve_depth(depth, variables)
    formulas = _get_formulas(
        bridge=bridge,
        depth=depth,
        variables=variables,
        use_all=use_all,
        timeout=remaining_timeout(total_timeout),
        rng=rng,
    )

    if not formulas:
        raise RuntimeError("Nessuna formula generata che usi tutte le variabili richieste")

    candidates = list(dict.fromkeys(formulas))
    rng.shuffle(candidates)

    # Parte da una formula scelta uniformemente per operatore principale
    # per evitare di privilegiare sempre lo stesso operatore negli esercizi.
    first_candidate = _pick_by_head(candidates, rng, prefer_or=(len(variables) >= 5))
    candidates = [first_candidate] + [formula for formula in candidates if formula != first_candidate]

    max_attempts = min(len(candidates), max(8, wrong_answers_count * 4))

    last_error: Exception | None = None
    for formula in candidates[:max_attempts]:
        try:
            return build_exercise(
                expr=formula,
                bridge=bridge,
                seed=seed,
                wrong_answers_count=wrong_answers_count,
                max_steps=max_steps,
                operator_cycles=operator_cycles,
                timeout=remaining_timeout(total_timeout),
            )
        except RuntimeError as exc:
            last_error = exc
            continue

    raise RuntimeError(
        f"Impossibile costruire un esercizio completo con la profondita richiesta dopo {max_attempts} tentativi"
    ) from last_error


def build_ex_json(
    expr: Any,
    bridge: PrologBridge | None = None,
    seed: int | None = None,
    wrong_answers_count: int = 3,
    max_steps: int = 2,
    operator_cycles: int | None = None,
    timeout: int = 10,
) -> str:
    """Serializza l output di build_exercise come stringa JSON formattata."""
    _req_int_ge("timeout", int(timeout), 1)
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    _req_int_ge("max_steps", max_steps, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return json.dumps(
        build_exercise(
            expr=expr,
            bridge=bridge,
            seed=seed,
            wrong_answers_count=wrong_answers_count,
            max_steps=max_steps,
            operator_cycles=operator_cycles,
            timeout=timeout,
        ),
        ensure_ascii=False,
        indent=2,
    )


def build_ex_depth_json(
    depth: int | None = None,
    variables: Sequence[str] = DEFAULT_VARIABLES,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    wrong_answers_count: int = 3,
    max_steps: int = 2,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
) -> str:
    """Serializza l output di build_ex_depth come stringa JSON formattata."""
    _req_int_ge("timeout", int(timeout), 1)
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    _req_int_ge("max_steps", max_steps, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return json.dumps(
        build_ex_depth(
            depth=depth,
            variables=variables,
            use_all=use_all,
            timeout=timeout,
            seed=seed,
            wrong_answers_count=wrong_answers_count,
            max_steps=max_steps,
            operator_cycles=operator_cycles,
            bridge=bridge,
        ),
        ensure_ascii=False,
        indent=2,
    )


def build_tvq_json(
    predicate_count: int,
    true_options_count: int,
    false_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
) -> str:
    """Serializza l output di build_tvq come stringa JSON formattata."""
    _req_int_ge("predicate_count", predicate_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    _req_int_ge("true_options_count", true_options_count, 1)
    _req_int_ge("false_options_count", false_options_count, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return json.dumps(
        build_tvq(
            predicate_count=predicate_count,
            true_options_count=true_options_count,
            false_options_count=false_options_count,
            timeout=timeout,
            seed=seed,
            operator_cycles=operator_cycles,
            bridge=bridge,
        ),
        ensure_ascii=False,
        indent=2,
    )

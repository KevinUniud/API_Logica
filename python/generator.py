from __future__ import annotations

# Serializzazione output e utilita numeriche/temporali per campionamento.
from collections import Counter
import json
import math
import random
import time
# Tipi usati nelle firme pubbliche e nei callback interni.
from typing import Any, Callable, Sequence, cast

# Nodi AST logici per trasformazioni e riscritture locali.
from ast_logic import And, Iff, Imp, Not, Or, Var
# Bridge Prolog e utility di conversione usate dal generatore.
from prolog_bridge import PrologBridge, collect_variables, from_prolog, get_default_bridge, to_prolog


DEFAULT_VARIABLES = ("p", "q", "r", "s", "t")
VAR_SET_LARGE = ("p", "q", "r", "s", "t")
VAR_SET_SMALL = ("p", "q", "r", "s")
DEFAULT_FORMULA_SAMPLE_LIMIT = 24
DEFAULT_FORMULA_FETCH_MULTIPLIER = 8
FORMULA_HEADS = ("and", "or", "imp", "iff", "not")
FORMULA_FETCH_CACHE_MAX = 64
MAX_FORMULA_ATOM_REPETITIONS = 3
FORMULA_REPETITION_PROBABILITY = 0.5
MIN_FORMULA_ATOM_REPETITION_DISTANCE = 3
MAX_MODIFIED_EQUIV_CHECKS = 8
DISTRACTION_CANDIDATE_MULTIPLIER = 4
MAX_AUTOMATIC_TRANSFORM_CYCLES = 8
MIN_NON_TRIVIAL_CORRECT_STEPS = 2
DEFAULT_DISTRACTOR_MAX_STEPS = 2

# Cache leggera in-process per evitare round-trip Prolog ripetuti
# su stesse tuple (depth, vars, mode) durante piu generazioni consecutive.
_FORMULA_FETCH_CACHE: dict[tuple[str, int, tuple[str, ...], bool], tuple[str, ...]] = {}


def _req_int_ge(name: str, value: int, minimum: int) -> None:
    """Verifica che un valore numerico sia un intero sopra una soglia minima."""
    if not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} deve essere un intero >= {minimum}")


def _ensure_keys(payload: dict[str, Any], required: Sequence[str]) -> None:
    """Verifica che il payload generato contenga tutte le chiavi richieste."""
    missing = [key for key in required if key not in payload]
    if missing:
        raise RuntimeError(f"Output incompleto: chiavi mancanti {missing}")


def _make_timeout_provider(timeout: int) -> Callable[[int | None], int]:
    """Costruisce una funzione timeout residuo basata su deadline relativa."""
    total_timeout = max(1, int(timeout))
    deadline = time.monotonic() + total_timeout

    def remaining_timeout(cap: int | None = None) -> int:
        left = max(1, int(math.ceil(deadline - time.monotonic())))
        return min(left, cap) if cap is not None else left

    return remaining_timeout


def _to_json_string(payload: dict[str, Any]) -> str:
    """Serializza un payload come JSON leggibile con configurazione uniforme."""
    return json.dumps(payload, ensure_ascii=False, indent=2)


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


def _select_random_var_set(
    *,
    rng: random.Random,
    depth: int | None = None,
) -> tuple[str, ...]:
    """Seleziona casualmente un set variabili preconfigurato compatibile con la profondita."""
    candidates = [VAR_SET_LARGE, VAR_SET_SMALL]
    if depth is not None:
        max_vars = _max_vars_for_depth(depth)
        candidates = [item for item in candidates if len(item) <= max_vars]
    if not candidates:
        raise ValueError("La profondita richiesta non consente il set automatico di variabili")
    return rng.choice(candidates)


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


def _has_operator_diversity(formulas: Sequence[str], minimum_distinct_heads: int = 2) -> bool:
    """Verifica che l insieme di formule includa abbastanza operatori principali distinti."""
    if minimum_distinct_heads <= 1:
        return True
    heads = {_formula_head(formula) for formula in formulas}
    return len(heads) >= minimum_distinct_heads


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


def _pick_formula_with_repetition_policy(
    formulas: Sequence[str],
    rng: random.Random,
    *,
    variables: Sequence[str],
    prefer_or: bool = False,
    repetition_probability: float = FORMULA_REPETITION_PROBABILITY,
    max_repetitions: int = MAX_FORMULA_ATOM_REPETITIONS,
) -> str:
    """Seleziona una formula bilanciando il ramo con e senza ripetizioni."""
    filtered_formulas = [
        formula
        for formula in formulas
        if _formula_atom_repetition_count(formula) <= max_repetitions
    ]
    if not filtered_formulas:
        raise RuntimeError("Nessuna formula valida disponibile")

    matching_variables = [formula for formula in filtered_formulas if _uses_vars(formula, variables)]
    candidate_pool = matching_variables or filtered_formulas

    repeated_formulas = [
        formula
        for formula in candidate_pool
        if _formula_has_non_banal_repetitions(formula)
    ]
    unique_formulas = [
        formula
        for formula in candidate_pool
        if _formula_atom_repetition_count(formula) == 0
    ]

    wants_repetitions = rng.random() < repetition_probability

    if wants_repetitions:
        if repeated_formulas:
            return _pick_by_head(repeated_formulas, rng, prefer_or=prefer_or)

        if unique_formulas:
            base_formula = _pick_by_head(unique_formulas, rng, prefer_or=prefer_or)
            repeated_formula = _introduce_atom_repetitions(
                base_formula,
                rng,
                variables=variables,
                max_repetitions=max_repetitions,
            )
            if repeated_formula is not None and _formula_has_non_banal_repetitions(repeated_formula):
                return repeated_formula

    if unique_formulas:
        return _pick_by_head(unique_formulas, rng, prefer_or=prefer_or)

    return _pick_by_head(repeated_formulas, rng, prefer_or=prefer_or)


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
    cache_key: tuple[str, int, tuple[str, ...], bool] | None = None
    if isinstance(bridge, PrologBridge):
        cache_key = (bridge.__class__.__name__, depth, tuple(variables), use_all)
        cached = _FORMULA_FETCH_CACHE.get(cache_key)
        if cached is not None:
            filtered_formulas = list(cached)
            if use_all:
                return filtered_formulas
            return _diversify_sample(filtered_formulas, DEFAULT_FORMULA_SAMPLE_LIMIT, rng)

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
        generic_fetch_timeout = max(1, min(timeout, 2))
        target_pool_size = max(DEFAULT_FORMULA_SAMPLE_LIMIT * 2, len(FORMULA_HEADS) * 6)
        head_sampling_budget = max(1.0, min(float(timeout), 3.0))
        started = time.monotonic()

        # 1) Privilegia prima il campionamento per head, cosi da non fissarsi
        # sul prefisso iniziale dell'enumerazione Prolog (spesso tutto 'and').
        if hasattr(bridge, "some_depth_head"):
            heads = list(FORMULA_HEADS)
            rng.shuffle(heads)
            for head in heads:
                if (time.monotonic() - started) >= head_sampling_budget or len(formulas) >= target_pool_size:
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
                if (time.monotonic() - started) >= head_sampling_budget or len(formulas) >= target_pool_size:
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
        remaining = max(0, target_pool_size - len(formulas))
        if remaining > 0:
            if hasattr(bridge, "some_depth_allvars"):
                formulas.extend(
                    safe_fetch(
                        bridge.some_depth_allvars,
                        depth,
                        list(variables),
                        limit=remaining,
                        timeout=generic_fetch_timeout,
                    )
                )
            elif hasattr(bridge, "some_depth"):
                formulas.extend(
                    safe_fetch(
                        bridge.some_depth,
                        depth,
                        list(variables),
                        limit=remaining,
                        timeout=generic_fetch_timeout,
                    )
                )
            else:
                formulas.extend(
                    safe_fetch(bridge.formula_of_depth, depth, list(variables), timeout=generic_fetch_timeout)
                )

    filtered_formulas = [formula for formula in formulas if _uses_vars(formula, variables)]

    if cache_key is not None:
        if len(_FORMULA_FETCH_CACHE) >= FORMULA_FETCH_CACHE_MAX:
            _FORMULA_FETCH_CACHE.pop(next(iter(_FORMULA_FETCH_CACHE)))
        _FORMULA_FETCH_CACHE[cache_key] = tuple(filtered_formulas)

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


def _formula_atom_repetition_count(expr) -> int:
    """Conta quante occorrenze ripetute di atomi sono presenti nella formula."""
    atom_counts: Counter[str] = Counter()

    def walk(node) -> None:
        if isinstance(node, Var):
            atom_counts[node.name] += 1
            return
        if isinstance(node, Not):
            walk(node.expr)
            return
        if isinstance(node, (And, Or, Imp, Iff)):
            walk(node.left)
            walk(node.right)
            return
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    walk(_as_ast(expr))
    return sum(count - 1 for count in atom_counts.values() if count > 1)


def _leaf_path_distance(left_path: tuple[str, ...], right_path: tuple[str, ...]) -> int:
    """Calcola la distanza strutturale tra due foglie dell'albero AST."""
    shared_prefix = 0
    for left_step, right_step in zip(left_path, right_path):
        if left_step != right_step:
            break
        shared_prefix += 1
    return len(left_path) + len(right_path) - (2 * shared_prefix)


def _formula_has_non_banal_repetitions(
    expr,
    min_distance: int = MIN_FORMULA_ATOM_REPETITION_DISTANCE,
) -> bool:
    """Verifica che eventuali ripetizioni abbiano un distacco minimo nell'albero."""
    leaf_paths = _collect_variable_leaf_paths(expr)
    by_atom: dict[str, list[tuple[str, ...]]] = {}
    for path, atom_name in leaf_paths:
        by_atom.setdefault(atom_name, []).append(path)

    has_repetition = False
    for paths in by_atom.values():
        if len(paths) < 2:
            continue
        has_repetition = True
        for index, left_path in enumerate(paths):
            for right_path in paths[index + 1 :]:
                if _leaf_path_distance(left_path, right_path) < min_distance:
                    return False

    return has_repetition


def _collect_variable_leaf_paths(expr) -> list[tuple[tuple[str, ...], str]]:
    """Raccoglie i percorsi delle foglie variabile in una formula AST."""
    ast = _as_ast(expr)
    leaf_paths: list[tuple[tuple[str, ...], str]] = []

    def walk(node, path: tuple[str, ...]) -> None:
        if isinstance(node, Var):
            leaf_paths.append((path, node.name))
            return
        if isinstance(node, Not):
            walk(node.expr, path + ("expr",))
            return
        if isinstance(node, (And, Or, Imp, Iff)):
            walk(node.left, path + ("left",))
            walk(node.right, path + ("right",))
            return
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    walk(ast, ())
    return leaf_paths


def _rewrite_variable_leaves(expr, replacements: dict[tuple[str, ...], str]):
    """Sostituisce foglie variabile selezionate mantenendo invariata la struttura."""
    ast = _as_ast(expr)

    def walk(node, path: tuple[str, ...]):
        if isinstance(node, Var):
            target_name = replacements.get(path)
            return Var(target_name) if target_name is not None else node
        if isinstance(node, Not):
            return Not(walk(node.expr, path + ("expr",)))
        if isinstance(node, And):
            return And(walk(node.left, path + ("left",)), walk(node.right, path + ("right",)))
        if isinstance(node, Or):
            return Or(walk(node.left, path + ("left",)), walk(node.right, path + ("right",)))
        if isinstance(node, Imp):
            return Imp(walk(node.left, path + ("left",)), walk(node.right, path + ("right",)))
        if isinstance(node, Iff):
            return Iff(walk(node.left, path + ("left",)), walk(node.right, path + ("right",)))
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    return walk(ast, ())


def _introduce_atom_repetitions(
    formula: Any,
    rng: random.Random,
    variables: Sequence[str] | None = None,
    max_repetitions: int = MAX_FORMULA_ATOM_REPETITIONS,
):
    """Prova a introdurre ripetizioni controllate di atomi in una formula."""
    ast = _as_ast(formula)
    current_repetitions = _formula_atom_repetition_count(ast)
    if current_repetitions > max_repetitions:
        return None
    if current_repetitions > 0:
        return to_prolog(ast) if _formula_has_non_banal_repetitions(ast) else None

    leaf_paths = _collect_variable_leaf_paths(ast)
    if len(leaf_paths) < 2:
        return None

    unique_atom_names = list(dict.fromkeys(atom_name for _, atom_name in leaf_paths))
    if len(unique_atom_names) < 2:
        return None

    atom_counts = Counter(atom_name for _, atom_name in leaf_paths)
    rng.shuffle(unique_atom_names)
    budget = max_repetitions - current_repetitions

    for target_name in unique_atom_names:
        # Sostituiamo solo foglie di atomi che rimangono comunque presenti,
        # cosi non perdiamo variabili richieste.
        available_paths = [
            path
            for path, atom_name in leaf_paths
            if atom_name != target_name and atom_counts[atom_name] > 1
        ]
        if not available_paths:
            continue

        rng.shuffle(available_paths)
        selected_paths = available_paths[:budget]
        if not selected_paths:
            continue

        transformed = _rewrite_variable_leaves(
            ast,
            {path: target_name for path in selected_paths},
        )
        transformed_prolog = to_prolog(transformed)
        if variables is not None and not _uses_vars(transformed_prolog, variables):
            continue
        if _formula_atom_repetition_count(transformed) <= max_repetitions and _formula_has_non_banal_repetitions(transformed):
            return transformed_prolog

    return None


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
    """Costruisce un payload serializzabile minimale per una formula."""
    payload = {
        "formula_prolog": to_prolog(expr),
    }
    payload.update(extra)
    _ensure_keys(payload, ["formula_prolog"])
    return payload


def _ensure_bridge(bridge: PrologBridge | None = None) -> PrologBridge:
    """Restituisce il bridge fornito o crea pigramente quello di default."""
    return bridge or get_default_bridge()


def _safe_bridge_call(fn: Callable[..., object], *args, **kwargs) -> list[str]:
    """Esegue una chiamata bridge restituendo sempre una lista o fallback vuoto."""
    try:
        result = fn(*args, **kwargs)
    except Exception:
        return []
    return result if isinstance(result, list) else []


def _operator_cycle_count(formula: Any, rng: random.Random, max_cycles: int | None = None) -> int:
    """Sceglie un numero di cicli compreso tra meta e massimo delle trasformazioni disponibili."""
    atom_count = formula_atom_count(_as_ast(formula))
    if atom_count <= 0:
        return 0

    automatic_max = min(MAX_AUTOMATIC_TRANSFORM_CYCLES, max(1, atom_count * 2))
    upper_bound = automatic_max if max_cycles is None else min(automatic_max, max_cycles)
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


def _has_atom_count(formula: Any, target_atom_count: int | None) -> bool:
    """Verifica l uguaglianza del numero di atomi quando richiesto."""
    if target_atom_count is None:
        return True
    return formula_atom_count(_as_ast(formula)) == target_atom_count


def _swap_and_or_rec(node: Any, rng: random.Random, swap_probability: float = 0.5) -> Any:
    """FALLBACK IMPLEMENTATION: Scambia casualmente i figli di and/or mantenendo intatto il resto della formula.
    
    Note: Prolog swap_and_or_children è preferito quando disponibile. Questa implementazione Python
    esiste solo come fallback se il bridge Prolog non è disponibile o fallisce.
    """
    if isinstance(node, Var):
        return node
    if isinstance(node, Not):
        return Not(_swap_and_or_rec(node.expr, rng, swap_probability))
    if isinstance(node, And):
        left = _swap_and_or_rec(node.left, rng, swap_probability)
        right = _swap_and_or_rec(node.right, rng, swap_probability)
        if rng.random() < swap_probability:
            return And(right, left)
        return And(left, right)
    if isinstance(node, Or):
        left = _swap_and_or_rec(node.left, rng, swap_probability)
        right = _swap_and_or_rec(node.right, rng, swap_probability)
        if rng.random() < swap_probability:
            return Or(right, left)
        return Or(left, right)
    if isinstance(node, Imp):
        return Imp(
            _swap_and_or_rec(node.left, rng, swap_probability),
            _swap_and_or_rec(node.right, rng, swap_probability),
        )
    if isinstance(node, Iff):
        return Iff(
            _swap_and_or_rec(node.left, rng, swap_probability),
            _swap_and_or_rec(node.right, rng, swap_probability),
        )
    return node


def _maybe_swap_and_or(formula: str, rng: random.Random, swap_probability: float = 0.5) -> str:
    """FALLBACK IMPLEMENTATION: Applica opzionalmente swap ai nodi and/or della formula.
    
    Note: Prolog swap_and_or_children è preferito quando disponibile via _transform_answer_candidates.
    Questa implementazione Python esiste solo come fallback se il bridge Prolog non è disponibile.
    """
    swapped = _swap_and_or_rec(_as_ast(formula), rng, swap_probability)
    return to_prolog(swapped)


def _needs_extra_transformation(formula: str) -> bool:
    """Rileva se la formula richiede una trasformazione aggiuntiva."""
    return _formula_head(formula) in {"imp", "iff", "not"}


def _canonicalize_commutative(node: Any) -> Any:
    """Normalizza and/or/iff ordinando i figli per confronto strutturale."""
    if isinstance(node, Var):
        return node
    if isinstance(node, Not):
        return Not(_canonicalize_commutative(node.expr))
    if isinstance(node, Imp):
        return Imp(_canonicalize_commutative(node.left), _canonicalize_commutative(node.right))
    if isinstance(node, And):
        left = _canonicalize_commutative(node.left)
        right = _canonicalize_commutative(node.right)
        if to_prolog(right) < to_prolog(left):
            left, right = right, left
        return And(left, right)
    if isinstance(node, Or):
        left = _canonicalize_commutative(node.left)
        right = _canonicalize_commutative(node.right)
        if to_prolog(right) < to_prolog(left):
            left, right = right, left
        return Or(left, right)
    if isinstance(node, Iff):
        left = _canonicalize_commutative(node.left)
        right = _canonicalize_commutative(node.right)
        if to_prolog(right) < to_prolog(left):
            left, right = right, left
        return Iff(left, right)
    return node


def _commutative_signature(formula: Any) -> str:
    """Restituisce una firma canonica che collassa anche le inversioni commutative."""
    return to_prolog(_canonicalize_commutative(_as_ast(formula)))


def _same_formula_under_commutativity(left: Any, right: Any) -> bool:
    """Verifica se due formule coincidono anche dopo l'ordinamento commutativo dei figli."""
    return _commutative_signature(left) == _commutative_signature(right)


def _is_effective_transformation(original: Any, candidate: Any) -> bool:
    """Verifica che la differenza non sia solo riordinamento commutativo dei figli."""
    original_text = _normalize_formula_text(original)
    candidate_text = _normalize_formula_text(candidate)
    if original_text == candidate_text:
        return False

    original_canonical = to_prolog(_canonicalize_commutative(_as_ast(original)))
    candidate_canonical = to_prolog(_canonicalize_commutative(_as_ast(candidate)))
    return original_canonical != candidate_canonical


def _normalize_formula_text(formula: Any) -> str:
    """Normalizza una formula in testo Prolog senza spazi superflui."""
    return _as_prolog(formula).replace(" ", "")


def _require_pairwise_distinct(formulas: Sequence[Any], context: str) -> None:
    """Verifica che tutte le formule siano diverse tra loro."""
    normalized = [_normalize_formula_text(formula) for formula in formulas]
    if len(set(normalized)) != len(normalized):
        raise RuntimeError(f"Postcondizione fallita: formule non distinte in {context}")


def _transform_answer_candidates(
    *,
    formula: str,
    bridge: PrologBridge,
    rng: random.Random,
    operator_cycles: int | None,
    timeout_provider: Callable[[], int],
) -> list[str]:
    """Genera varianti risposta usando Prolog quando disponibile, con fallback Python.
    
    FLUSSO PRIMARIO (Prolog preferito):
    1. Se bridge.apply_answer_transform_cycles disponibile: tenta di usare Prolog
    2. Se successo: restituisce risultati Prolog
    3. Se fallisce: passa a FLUSSO FALLBACK
    
    FLUSSO FALLBACK (Python):
    1. Se nessun ciclo richiesto: restituisce [formula, swap_and_or(formula)]
    2. Se bridge.apply_operator_cycles disponibile: usa Python swap + cicli Prolog
    3. Applica extra trasformazioni se formula head è imp/iff/not
    
    In entrambi i casi: deduplicazione e normalizzazione finale.
    """
    transformed: list[str] = []
    
    # PRIMARY PATH: Tentativo Prolog apply_answer_transform_cycles
    answer_cycles_fn = getattr(bridge, "apply_answer_transform_cycles", None)
    if callable(answer_cycles_fn):
        cycles = _operator_cycle_count(formula, rng, operator_cycles)
        if cycles > 0:
            transformed = _safe_bridge_call(
                cast(Callable[..., object], answer_cycles_fn),
                formula,
                cycles=cycles,
                timeout=timeout_provider(),
            )

    if transformed:
        return list(dict.fromkeys([formula] + transformed))

    # FALLBACK PATH: Python swap + Prolog cycles (se disponibili)
    fallback = [formula, _maybe_swap_and_or(formula, rng)]
    if operator_cycles == 0:
        return list(dict.fromkeys(fallback))

    apply_cycles = getattr(bridge, "apply_operator_cycles", None)
    if not callable(apply_cycles):
        return list(dict.fromkeys(fallback))

    cycle_fn = cast(Callable[..., list[str]], apply_cycles)
    candidate_cycles = _operator_cycle_count(formula, rng, operator_cycles)
    if candidate_cycles <= 0:
        return list(dict.fromkeys(fallback))

    enriched_candidates = _safe_bridge_call(
        cast(Callable[..., object], cycle_fn),
        formula,
        cycles=candidate_cycles,
        timeout=timeout_provider(),
    )

    for enriched in enriched_candidates:
        fallback.append(enriched)
        fallback.append(_maybe_swap_and_or(enriched, rng))
        if _needs_extra_transformation(enriched):
            extra_candidates = _safe_bridge_call(
                cast(Callable[..., object], cycle_fn),
                enriched,
                cycles=1,
                timeout=timeout_provider(),
            )
            for extra in extra_candidates:
                fallback.append(extra)
                fallback.append(_maybe_swap_and_or(extra, rng))

    return list(dict.fromkeys(fallback))


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

    selected = _pick_formula_with_repetition_policy(
        formulas,
        rng,
        variables=variables,
        prefer_or=(len(variables) >= 5),
    )
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
    _ensure_keys(result, ["formula_prolog", "source"])
    return result


def generate_formula_by_variable_count(
    variable_count: int,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
) -> str:
    """Genera una formula che usa esattamente il numero di variabili richiesto."""
    _req_int_ge("variable_count", variable_count, 1)
    _req_int_ge("timeout", int(timeout), 1)

    variables = _default_vars(variable_count)
    depth = _depth_from_var_count(variable_count)
    return generate_formula(
        depth=depth,
        variables=variables,
        use_all=use_all,
        timeout=timeout,
        seed=seed,
        bridge=bridge,
    )


def generate_formula_by_variable_count_json(
    variable_count: int,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    bridge: PrologBridge | None = None,
) -> dict:
    """Genera una formula con N variabili e restituisce un payload pronto per JSON."""
    _req_int_ge("variable_count", variable_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    formula = generate_formula_by_variable_count(
        variable_count=variable_count,
        use_all=use_all,
        timeout=timeout,
        seed=seed,
        bridge=bridge,
    )
    result = formula_payload(
        _as_ast(formula),
        source="prolog_variable_count",
        variable_count=variable_count,
    )
    _ensure_keys(result, ["formula_prolog", "source", "variable_count"])
    return result


def _pick_modified(
    question_prolog: str,
    variables,
    bridge: PrologBridge,
    filter_equiv_batch: Callable[[Sequence[str]], list[str]],
    target_atom_count: int | None = None,
    seed: int | None = None,
    timeout: int = 10,
) -> tuple[str, int]:
    """Seleziona una formula equivalente con almeno due trasformazioni non banali."""
    rng = random.Random(seed)

    def filter_candidates_batch(source: Sequence[str], seen: set[str]) -> list[str]:
        """Filtra candidati con i vincoli comuni usati dai due percorsi di selezione."""
        selected: list[str] = []
        for candidate in source:
            if not candidate or candidate == question_prolog or candidate in seen:
                continue
            if not _uses_vars(candidate, variables):
                continue
            if not _has_atom_count(candidate, target_atom_count):
                continue
            if not _is_effective_transformation(question_prolog, candidate):
                continue
            seen.add(candidate)
            selected.append(candidate)
            if len(selected) >= MAX_MODIFIED_EQUIV_CHECKS:
                break
        return selected

    def finalize_candidate(candidate: str, steps: int) -> tuple[str, int]:
        selected = _maybe_swap_and_or(candidate, rng)
        selected_steps = steps
        if _needs_extra_transformation(candidate):
            try:
                extra_raw = bridge.rewrite_formula(candidate, timeout=timeout)
            except Exception:
                extra_raw = []

            extra_candidates = [
                item
                for item in extra_raw
                if item
                and item != question_prolog
                and _is_effective_transformation(candidate, item)
                and _uses_vars(item, variables)
                and _has_atom_count(item, target_atom_count)
            ]
            if extra_candidates:
                equivalent_extra = filter_equiv_batch(extra_candidates)
                if equivalent_extra:
                    selected = _maybe_swap_and_or(rng.choice(equivalent_extra), rng)
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
            if selected_steps < MIN_NON_TRIVIAL_CORRECT_STEPS:
                continue
            if not _is_effective_transformation(question_prolog, selected):
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

    fallback_raw = _safe_bridge_call(bridge.rewrite_formula, question_prolog, timeout=timeout)
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
) -> list[str]:
    """Raccoglie distractor non equivalenti per una formula domanda."""
    rng = random.Random(seed)
    collected: list[str] = []
    seen = {question_prolog, correct_prolog}
    source_formula = correct_prolog if from_correct_answer else question_prolog
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
            and _has_atom_count(candidate, target_atom_count)
        ]
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
            if candidate and _uses_vars(candidate, variables) and _has_atom_count(candidate, target_atom_count)
        ]

        seen.update(expanded)
        wrong_candidates = filter_wrong_batch(expanded)
        for candidate in wrong_candidates:
            collected.append(candidate)

            if len(collected) >= wrong_answers_count:
                return True
        return False

    # 1. Sorgenti deterministiche / elenco
    deterministic_sources: list[Callable[[], list[str]]] = []

    some_one_step = getattr(bridge, "some_step_neq", None)
    if callable(some_one_step):
        deterministic_sources.append(
            lambda: _safe_bridge_call(
                cast(Callable[..., object], some_one_step),
                source_formula,
                limit=candidate_limit,
                timeout=current_timeout(),
            )
        )
    else:
        deterministic_sources.append(
            lambda: _safe_bridge_call(
                bridge.all_step_neq,
                source_formula,
                timeout=current_timeout(),
            )
        )

    deterministic_sources.append(
        lambda: _safe_bridge_call(
            bridge.one_step_neq,
            source_formula,
            timeout=current_timeout(),
        )
    )

    some_multi_step = getattr(bridge, "some_neq", None)
    if callable(some_multi_step):
        deterministic_sources.append(
            lambda: _safe_bridge_call(
                cast(Callable[..., object], some_multi_step),
                source_formula,
                max_steps=DEFAULT_DISTRACTOR_MAX_STEPS,
                limit=candidate_limit,
                timeout=current_timeout(),
            )
        )

    deterministic_sources.append(
        lambda: _safe_bridge_call(
            bridge.non_equivalent_distraction,
            source_formula,
            max_steps=DEFAULT_DISTRACTOR_MAX_STEPS,
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
) -> list[str]:
    """Raccoglie un pool di formule candidate con vincoli condivisi tra builder quiz."""
    candidates: list[str] = []
    seen_candidates: set[str] = set(excluded_formulas or ())
    seen_signatures: set[str] = set()
    if dedupe_by_commutative_signature:
        seen_signatures = {_commutative_signature(formula) for formula in seen_candidates}

    allowed_variables = set(variables)

    def register_candidate(formula: str) -> None:
        if not formula or formula in seen_candidates:
            return
        used_variables = collect_variables(_as_ast(formula))
        if require_non_empty_vars and not used_variables:
            return
        if not used_variables.issubset(allowed_variables):
            return
        if target_atom_count is not None and not _has_atom_count(formula, target_atom_count):
            return

        if dedupe_by_commutative_signature:
            signature = _commutative_signature(formula)
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

    search_depth = max(2, _depth_from_var_count(len(variables)) + 2)
    target_candidate_count = max(required_options * DISTRACTION_CANDIDATE_MULTIPLIER, 12)

    for depth in range(1, search_depth + 1):
        fetched = _get_formulas(
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


def _sample_partitioned_options(
    *,
    rng: random.Random,
    left_candidates: Sequence[str],
    right_candidates: Sequence[str],
    left_count: int,
    right_count: int,
    max_attempts: int = 12,
    uniqueness_key: Callable[[str], str] | None = None,
    extra_validator: Callable[[Sequence[str], Sequence[str]], bool] | None = None,
) -> tuple[list[str], list[str]] | None:
    """Campiona due partizioni di opzioni rispettando i vincoli comuni di diversita."""
    for _ in range(max_attempts):
        trial_left = rng.sample(list(left_candidates), left_count)
        trial_right = rng.sample(list(right_candidates), right_count)
        trial_options = trial_left + trial_right

        if len(set(trial_options)) != len(trial_options):
            continue
        if uniqueness_key is not None:
            if len({uniqueness_key(option) for option in trial_options}) != len(trial_options):
                continue
        if not _has_operator_diversity(trial_options):
            continue
        if extra_validator is not None and not extra_validator(trial_left, trial_right):
            continue
        return trial_left, trial_right

    return None


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
    remaining_timeout = _make_timeout_provider(timeout)

    # Se predicate_count è 4 o 5, usa un set casuale; altrimenti genera dinamicamente
    if predicate_count in (4, 5):
        variables = list(_select_random_var_set(rng=rng))
    else:
        variables = _default_vars(predicate_count)

    effective_predicate_count = len(variables)
    required_options = true_options_count + false_options_count

    valuations = bridge.assignment(variables, timeout=remaining_timeout(None))
    if not valuations:
        raise RuntimeError("Nessuna assegnazione disponibile per i predicati richiesti")
    rng.shuffle(valuations)

    target_atom_count = effective_predicate_count
    candidates = _collect_candidate_formulas(
        bridge=bridge,
        variables=variables,
        required_options=required_options,
        rng=rng,
        timeout_provider=remaining_timeout,
        operator_cycles=operator_cycles,
        target_atom_count=target_atom_count,
        require_non_empty_vars=True,
    )

    if len(candidates) < required_options:
        raise RuntimeError(
            "Non ci sono abbastanza formule candidate con il numero di atomi richiesto"
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

        combined_candidates = true_candidates + false_candidates
        if not _has_operator_diversity(combined_candidates):
            continue

        selected = _sample_partitioned_options(
            rng=rng,
            left_candidates=true_candidates,
            right_candidates=false_candidates,
            left_count=true_options_count,
            right_count=false_options_count,
        )

        if selected is None:
            continue

        selected_true, selected_false = selected

        _require_pairwise_distinct(selected_true + selected_false, "build_tvq options")

        options = [
            _formula_entry(formula, is_true=True) for formula in selected_true
        ] + [
            _formula_entry(formula, is_true=False) for formula in selected_false
        ]
        rng.shuffle(options)

        result = {
            "type": "truth_value_options_question",
            "predicate_count": effective_predicate_count,
            "true_options_count": true_options_count,
            "false_options_count": false_options_count,
            "variables": variables,
            "information": list(valuation),
            "options": options,
            "true_options": [_formula_entry(formula, is_true=True) for formula in selected_true],
            "false_options": [_formula_entry(formula, is_true=False) for formula in selected_false],
            "source": "prolog_assignment_and_eval",
        }

        _ensure_keys(result, ["information", "options", "variables"])
        return result

    raise RuntimeError(
        "Impossibile trovare una assegnazione con abbastanza opzioni vere e false distinte"
    )


def build_logical_consequence_question(
    variable_count: int,
    correct_options_count: int,
    wrong_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
) -> dict:
    """Costruisce un quiz di conseguenza logica con opzioni corrette/errate.

    Semantica usata: `Q |= R` se ogni valutazione che rende vera la formula domanda `Q`
    rende vera anche l'opzione `R`.
    """
    _req_int_ge("variable_count", variable_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    if correct_options_count < 1:
        raise ValueError("correct_options_count deve essere >= 1")
    if wrong_options_count < 1:
        raise ValueError("wrong_options_count deve essere >= 1")
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)

    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)
    remaining_timeout = _make_timeout_provider(timeout)
    required_options = correct_options_count + wrong_options_count
    variables = _default_vars(variable_count)
    question_formula = generate_formula_by_variable_count(
        variable_count=variable_count,
        use_all=False,
        timeout=max(1, int(timeout)),
        seed=seed,
        bridge=bridge,
    )
    question_prolog = _as_prolog(question_formula)

    candidates = _collect_candidate_formulas(
        bridge=bridge,
        variables=variables,
        required_options=required_options,
        rng=rng,
        timeout_provider=remaining_timeout,
        operator_cycles=operator_cycles,
        excluded_formulas=[question_prolog],
        dedupe_by_commutative_signature=True,
    )

    if len(candidates) < required_options:
        raise RuntimeError("Non ci sono abbastanza formule candidate per il quiz di conseguenza logica")

    implication_cache: dict[str, bool] = {}

    def is_logical_consequence(candidate: str) -> bool:
        if candidate in implication_cache:
            return implication_cache[candidate]
        try:
            result = bool(
                bridge.implies_formula(
                    question_prolog,
                    candidate,
                    vars_list=variables,
                    timeout=remaining_timeout(2),
                )
            )
        except Exception:
            result = False
        implication_cache[candidate] = result
        return result

    consequence_candidates: list[str] = []
    non_consequence_candidates: list[str] = []

    shuffled_candidates = list(candidates)
    rng.shuffle(shuffled_candidates)
    for candidate in shuffled_candidates:
        if is_logical_consequence(candidate):
            consequence_candidates.append(candidate)
        else:
            non_consequence_candidates.append(candidate)
        if (
            len(consequence_candidates) >= correct_options_count
            and len(non_consequence_candidates) >= wrong_options_count
        ):
            break

    if len(consequence_candidates) < correct_options_count or len(non_consequence_candidates) < wrong_options_count:
        raise RuntimeError("Impossibile trovare abbastanza opzioni per il quiz di conseguenza logica")

    selected = _sample_partitioned_options(
        rng=rng,
        left_candidates=consequence_candidates,
        right_candidates=non_consequence_candidates,
        left_count=correct_options_count,
        right_count=wrong_options_count,
        uniqueness_key=_commutative_signature,
        # Validazione semantica esplicita per evitare mismatch tra classificazione
        # iniziale e set finale selezionato.
        extra_validator=lambda selected_left, selected_right: (
            all(is_logical_consequence(item) for item in selected_left)
            and not any(is_logical_consequence(item) for item in selected_right)
        ),
    )

    if selected is None:
        raise RuntimeError("Impossibile rispettare i vincoli di diversita nel quiz di conseguenza logica")

    selected_correct, selected_wrong = selected

    if len({_commutative_signature(option) for option in selected_correct + selected_wrong}) != len(
        selected_correct + selected_wrong
    ):
        raise RuntimeError("Postcondizione fallita: formule non distinte nel quiz di conseguenza logica")

    options = [
        _formula_entry(formula, is_consequence=True) for formula in selected_correct
    ] + [
        _formula_entry(formula, is_consequence=False) for formula in selected_wrong
    ]
    rng.shuffle(options)

    result = {
        "type": "logical_consequence_question",
        "variable_count": variable_count,
        "correct_options_count": correct_options_count,
        "wrong_options_count": wrong_options_count,
        "variables": variables,
        "question_prolog": question_prolog,
        "options": options,
        "correct_options": [_formula_entry(formula, is_consequence=True) for formula in selected_correct],
        "wrong_options": [_formula_entry(formula, is_consequence=False) for formula in selected_wrong],
        "source": "prolog_implies_formula",
    }

    _ensure_keys(
        result,
        ["question_prolog", "options", "variables"],
    )
    return result


def build_exercise(
    expr,
    wrong_answers_count: int = 3,
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    bridge: PrologBridge | None = None,
    seed: int | None = None,
    timeout: int = 10,
) -> dict:
    """Costruisce un esercizio con formula originale, modificata e distrazioni."""
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    _req_int_ge("timeout", int(timeout), 1)
    bridge = _ensure_bridge(bridge)

    question_prolog = to_prolog(expr) if not isinstance(expr, str) else expr
    question_expr = from_prolog(question_prolog)
    variables = sorted(collect_variables(question_expr))
    question_atom_count = formula_atom_count(question_expr)
    remaining_timeout = _make_timeout_provider(timeout)
    total_timeout = max(1, int(timeout))
    check_timeout = max(1, min(total_timeout, 2))
    equiv_cache: dict[str, bool] = {}
    not_equiv_cache: dict[str, bool] = {}

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
        target_atom_count=question_atom_count,
        seed=seed,
        timeout=remaining_timeout(total_timeout),
    )

    if modified_prolog == question_prolog:
        raise RuntimeError("La formula modificata coincide con la formula originale")

    wrong_selected = _pick_wrongs(
        question_prolog=question_prolog,
        correct_prolog=modified_prolog,
        variables=variables,
        target_atom_count=question_atom_count,
        wrong_answers_count=wrong_answers_count,
        operator_cycles=operator_cycles,
        from_correct_answer=wrong_from_correct,
        bridge=bridge,
        filter_wrong_batch=filter_wrong_batch,
        seed=seed,
        timeout=remaining_timeout(total_timeout),
        timeout_provider=remaining_timeout,
    )

    _require_pairwise_distinct(
        [question_prolog, modified_prolog, *wrong_selected],
        "build_exercise question/correct/wrongs",
    )

    original_formula = _formula_entry(question_expr, label="formula originale")
    modified_formula = _formula_entry(
        modified_prolog,
        label="formula modificata",
        steps=rewrite_steps,
    )
    exercise = {
        "original_formula": original_formula,
        "modified_formula": modified_formula,
        "variables": variables,
        "depth": formula_depth(question_expr),
        "size": formula_size(question_expr),
        "atom_count": question_atom_count,
        "rewrite_steps": rewrite_steps,
        "source": "prolog_builder",
        "question_prolog": question_prolog,
        "correct_answer_prolog": modified_prolog,
        "wrong_answers_prolog": wrong_selected,
    }

    for index, wrong_formula in enumerate(wrong_selected, start=1):
        exercise[f"distraction_{index}"] = _formula_entry(
            wrong_formula,
            label=f"formula distrazione n{index}",
        )

    _ensure_keys(exercise, ["original_formula", "modified_formula", "wrong_answers_prolog"])
    if len(exercise["wrong_answers_prolog"]) < wrong_answers_count:
        raise RuntimeError("Postcondizione fallita: distractor insufficienti")
    return exercise


def build_ex_depth(
    depth: int | None = None,
    use_all: bool = False,
    timeout: int = 10,
    seed: int | None = None,
    wrong_answers_count: int = 3,
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    bridge: PrologBridge | None = None,
) -> dict:
    """Costruisce un esercizio con variabili e trasformazioni completamente automatiche."""
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    _req_int_ge("timeout", int(timeout), 1)
    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)
    remaining_timeout = _make_timeout_provider(timeout)

    variables = _select_random_var_set(rng=rng, depth=depth)

    depth, variables = _resolve_depth(depth, variables)
    formulas = _get_formulas(
        bridge=bridge,
        depth=depth,
        variables=variables,
        use_all=use_all,
        timeout=remaining_timeout(None),
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
                operator_cycles=operator_cycles,
                wrong_from_correct=wrong_from_correct,
                timeout=remaining_timeout(None),
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
    operator_cycles: int | None = None,
    wrong_from_correct: bool = False,
    timeout: int = 10,
) -> str:
    """Serializza l output di build_exercise come stringa JSON formattata."""
    _req_int_ge("timeout", int(timeout), 1)
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return _to_json_string(
        build_exercise(
            expr=expr,
            bridge=bridge,
            seed=seed,
            wrong_answers_count=wrong_answers_count,
            operator_cycles=operator_cycles,
            wrong_from_correct=wrong_from_correct,
            timeout=timeout,
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
) -> str:
    """Serializza l output di build_ex_depth come stringa JSON formattata."""
    _req_int_ge("timeout", int(timeout), 1)
    _req_int_ge("wrong_answers_count", wrong_answers_count, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return _to_json_string(
        build_ex_depth(
            depth=depth,
            use_all=use_all,
            timeout=timeout,
            seed=seed,
            wrong_answers_count=wrong_answers_count,
            operator_cycles=operator_cycles,
            wrong_from_correct=wrong_from_correct,
            bridge=bridge,
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
) -> str:
    """Serializza l output di build_tvq come stringa JSON formattata."""
    _req_int_ge("predicate_count", predicate_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    _req_int_ge("true_options_count", true_options_count, 1)
    _req_int_ge("false_options_count", false_options_count, 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return _to_json_string(
        build_tvq(
            predicate_count=predicate_count,
            true_options_count=true_options_count,
            false_options_count=false_options_count,
            timeout=timeout,
            seed=seed,
            operator_cycles=operator_cycles,
            bridge=bridge,
        )
    )


def build_logical_consequence_question_json(
    variable_count: int,
    correct_options_count: int,
    wrong_options_count: int,
    timeout: int = 10,
    seed: int | None = None,
    operator_cycles: int | None = None,
    bridge: PrologBridge | None = None,
) -> str:
    """Serializza l output del quiz di conseguenza logica come stringa JSON."""
    _req_int_ge("variable_count", variable_count, 1)
    _req_int_ge("correct_options_count", correct_options_count, 1)
    _req_int_ge("wrong_options_count", wrong_options_count, 1)
    _req_int_ge("timeout", int(timeout), 1)
    if operator_cycles is not None:
        _req_int_ge("operator_cycles", operator_cycles, 0)
    return _to_json_string(
        build_logical_consequence_question(
            variable_count=variable_count,
            correct_options_count=correct_options_count,
            wrong_options_count=wrong_options_count,
            timeout=timeout,
            seed=seed,
            operator_cycles=operator_cycles,
            bridge=bridge,
        )
    )

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
    """Seleziona una formula applicando la policy di ripetizione su singolo trial."""
    selected = _select_formulas_with_repetition_policy(
        formulas,
        count=1,
        rng=rng,
        variables=variables,
        prefer_or=prefer_or,
        repetition_probability=repetition_probability,
        max_repetitions=max_repetitions,
    )
    return selected[0]


def _select_formulas_with_repetition_policy(
    formulas: Sequence[str],
    count: int,
    rng: random.Random,
    *,
    variables: Sequence[str] | None = None,
    prefer_or: bool = False,
    repetition_probability: float = FORMULA_REPETITION_PROBABILITY,
    max_repetitions: int = MAX_FORMULA_ATOM_REPETITIONS,
) -> list[str]:
    """Seleziona N formule con trial indipendenti sulla presenza di ripetizioni."""
    _req_int_ge("count", count, 1)

    filtered_formulas = [
        formula
        for formula in dict.fromkeys(formulas)
        if _formula_atom_repetition_count(formula) <= max_repetitions
    ]
    if variables is not None:
        matching_variables = [formula for formula in filtered_formulas if _uses_vars(formula, variables)]
        if matching_variables:
            filtered_formulas = matching_variables

    if len(filtered_formulas) < count:
        raise RuntimeError(
            f"Nessuna formula valida disponibile: richieste {count}, disponibili {len(filtered_formulas)}"
        )

    repeated_formulas = [
        formula
        for formula in filtered_formulas
        if _formula_has_non_banal_repetitions(formula)
    ]
    unique_formulas = [
        formula
        for formula in filtered_formulas
        if _formula_atom_repetition_count(formula) == 0
    ]

    selected: list[str] = []
    used: set[str] = set()

    def choose_from(pool: Sequence[str]) -> str | None:
        available = [item for item in pool if item not in used]
        if not available:
            return None
        return _pick_by_head(available, rng, prefer_or=prefer_or)

    for _ in range(count):
        wants_repetitions = rng.random() < repetition_probability
        primary_pool = repeated_formulas if wants_repetitions else unique_formulas
        secondary_pool = unique_formulas if wants_repetitions else repeated_formulas

        chosen = choose_from(primary_pool)
        if chosen is None:
            chosen = choose_from(secondary_pool)

        if chosen is None and wants_repetitions and variables is not None:
            base_formula = choose_from(unique_formulas)
            if base_formula is not None:
                repeated_formula = _introduce_atom_repetitions(
                    base_formula,
                    rng,
                    variables=variables,
                    max_repetitions=max_repetitions,
                )
                if repeated_formula is not None and repeated_formula not in used:
                    chosen = repeated_formula

        # Se nessuno dei due rami e disponibile, usa l'intero pool valido.
        if chosen is None:
            chosen = choose_from(filtered_formulas)

        if chosen is None:
            break

        used.add(chosen)
        selected.append(chosen)

    if len(selected) < count:
        raise RuntimeError(
            f"Nessuna formula valida disponibile: richieste {count}, selezionate {len(selected)}"
        )

    return selected


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


def _scramble_commutative_formula(expr: Any, rng: random.Random) -> Any:
    """Rimescola ricorsivamente i figli di and/or senza cambiare il significato."""
    ast = _as_ast(expr)

    def transform(node: Any) -> Any:
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

    return transform(ast)


def _scramble_formula_prolog(formula: Any, rng: random.Random) -> str:
    """Restituisce una formula Prolog con and/or rimescolati quando possibile."""
    return to_prolog(_scramble_commutative_formula(formula, rng))


def _formula_entry(expr: Any, *, rng: random.Random | None = None, **extra) -> dict:
    """Crea una voce formula standardizzata per le risposte API."""
    if rng is None:
        return formula_payload(_as_ast(expr), **extra)
    return formula_payload(_scramble_commutative_formula(expr, rng), **extra)


def _has_atom_count(formula: Any, target_atom_count: int | None) -> bool:
    """Verifica l uguaglianza del numero di atomi quando richiesto."""
    if target_atom_count is None:
        return True
    return formula_atom_count(_as_ast(formula)) == target_atom_count


def _has_adjacent_duplicate_atoms(formula: Any) -> bool:
    """Rileva occorrenze con due atomi uguali come figli diretti dello stesso connettivo binario."""
    ast = _as_ast(formula)

    def walk(node: Any) -> bool:
        if isinstance(node, Var):
            return False
        if isinstance(node, Not):
            return walk(node.expr)
        if isinstance(node, (And, Or, Imp, Iff)):
            if isinstance(node.left, Var) and isinstance(node.right, Var) and node.left.name == node.right.name:
                return True
            return walk(node.left) or walk(node.right)
        raise TypeError(f"Tipo formula non supportato: {type(node)!r}")

    return walk(ast)


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
            if _has_adjacent_duplicate_atoms(candidate):
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
                and not _has_adjacent_duplicate_atoms(item)
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
            if _has_adjacent_duplicate_atoms(selected):
                continue
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
            and not _has_adjacent_duplicate_atoms(candidate)
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
            if candidate
            and not _has_adjacent_duplicate_atoms(candidate)
            and _uses_vars(candidate, variables)
            and _has_atom_count(candidate, target_atom_count)
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
    forbid_adjacent_duplicate_atoms: bool = False,
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
        if forbid_adjacent_duplicate_atoms and _has_adjacent_duplicate_atoms(formula):
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
        try:
            trial_left = _select_formulas_with_repetition_policy(
                left_candidates,
                count=left_count,
                rng=rng,
            )
            trial_right = _select_formulas_with_repetition_policy(
                right_candidates,
                count=right_count,
                rng=rng,
            )
        except RuntimeError:
            if len(left_candidates) < left_count or len(right_candidates) < right_count:
                return None
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
        forbid_adjacent_duplicate_atoms=True,
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
            _formula_entry(formula, rng=rng, is_true=True) for formula in selected_true
        ] + [
            _formula_entry(formula, rng=rng, is_true=False) for formula in selected_false
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
            "true_options": [_formula_entry(formula, rng=rng, is_true=True) for formula in selected_true],
            "false_options": [_formula_entry(formula, rng=rng, is_true=False) for formula in selected_false],
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
    question_prolog_display = _scramble_formula_prolog(question_prolog, rng)

    candidates = _collect_candidate_formulas(
        bridge=bridge,
        variables=variables,
        required_options=required_options,
        rng=rng,
        timeout_provider=remaining_timeout,
        operator_cycles=operator_cycles,
        excluded_formulas=[question_prolog],
        dedupe_by_commutative_signature=True,
        forbid_adjacent_duplicate_atoms=True,
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
        _formula_entry(formula, rng=rng, is_consequence=True) for formula in selected_correct
    ] + [
        _formula_entry(formula, rng=rng, is_consequence=False) for formula in selected_wrong
    ]
    rng.shuffle(options)

    result = {
        "type": "logical_consequence_question",
        "variable_count": variable_count,
        "correct_options_count": correct_options_count,
        "wrong_options_count": wrong_options_count,
        "variables": variables,
        "question_prolog": question_prolog_display,
        "options": options,
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
    rng = random.Random(seed)

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

    original_formula = _formula_entry(question_expr, rng=rng, label="formula originale")
    modified_formula = _formula_entry(
        modified_prolog,
        rng=rng,
        label="formula modificata",
        steps=rewrite_steps,
    )
    question_prolog_display = _scramble_formula_prolog(question_prolog, rng)
    exercise = {
        "original_formula": original_formula,
        "modified_formula": modified_formula,
        "variables": variables,
        "depth": formula_depth(question_expr),
        "size": formula_size(question_expr),
        "atom_count": question_atom_count,
        "rewrite_steps": rewrite_steps,
        "source": "prolog_builder",
        "question_prolog": question_prolog_display,
        "correct_answer_prolog": _scramble_formula_prolog(modified_prolog, rng),
        "wrong_answers_prolog": [_scramble_formula_prolog(formula, rng) for formula in wrong_selected],
    }

    for index, wrong_formula in enumerate(wrong_selected, start=1):
        exercise[f"distraction_{index}"] = _formula_entry(
            wrong_formula,
            rng=rng,
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
    candidates = _diversify_sample(candidates, len(candidates), rng)
    initial_attempts = min(len(candidates), max(8, wrong_answers_count * 4))
    attempt_order = candidates[:initial_attempts] + candidates[initial_attempts:]

    last_error: Exception | None = None
    for formula in attempt_order:
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
        f"Impossibile costruire un esercizio completo con la profondita richiesta dopo aver provato {len(attempt_order)} candidati"
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


def _pick_translation_subtype(mode: str, quantifier_ratio: float, rng: random.Random) -> str:
    """Risolve il sottotipo del quiz di traduzione a partire dal mode richiesto."""
    if mode == "quantifier":
        return "quantifier"
    if mode == "propositional":
        return "propositional"
    if mode == "auto":
        return "quantifier" if rng.random() < quantifier_ratio else "propositional"
    raise ValueError("mode deve essere uno tra: auto, quantifier, propositional")


def _pick_symbol_sequence(
    *,
    symbols: Sequence[str],
    length: int,
    rng: random.Random,
    repetition_probability: float,
) -> list[str]:
    """Seleziona una sequenza di simboli, consentendo ripetizioni controllate."""
    if length <= 0:
        raise ValueError("length deve essere > 0")
    if not symbols:
        raise ValueError("symbols non puo essere vuoto")

    selected = [rng.choice(list(symbols)) for _ in range(length)]
    wants_repetition = rng.random() < repetition_probability
    if wants_repetition and len(selected) > 1:
        source_index = rng.randrange(len(selected))
        target_candidates = [idx for idx in range(len(selected)) if idx != source_index]
        target_index = rng.choice(target_candidates)
        selected[target_index] = selected[source_index]
    return selected


def _build_propositional_wrong_formulas(*, template_name: str, atoms: Sequence[str], correct_formula: str) -> list[str]:
    """Genera formule sbagliate robuste anche quando gli atomi si ripetono."""
    if template_name == "implication":
        left, right = atoms
        candidates = [
            f"imp({right},{left})",
            f"and({left},{right})",
            f"or({left},{right})",
            f"iff({left},{right})",
            f"imp(not({left}),{right})",
        ]
    elif template_name == "conjunction_chain":
        first, second, third = atoms
        candidates = [
            f"or(or({first},{second}),{third})",
            f"imp(and({first},{second}),{third})",
            f"imp({first},and({second},{third}))",
            f"and({first},or({second},{third}))",
            f"iff(and({first},{second}),{third})",
        ]
    elif template_name == "disjunction_chain":
        first, second, third = atoms
        candidates = [
            f"and(and({first},{second}),{third})",
            f"imp(or({first},{second}),{third})",
            f"imp({first},or({second},{third}))",
            f"or({first},and({second},{third}))",
            f"iff(or({first},{second}),{third})",
        ]
    else:
        raise RuntimeError(f"Template proposizionale non supportato: {template_name}")

    unique_candidates = list(dict.fromkeys(candidate for candidate in candidates if candidate != correct_formula))
    if len(unique_candidates) >= 3:
        return unique_candidates[:3]

    fallback = [
        "imp(P,Q)",
        "imp(Q,P)",
        "and(P,Q)",
        "or(P,Q)",
        "iff(P,Q)",
        "and(and(P,Q),R)",
        "or(or(P,Q),R)",
    ]
    for item in fallback:
        if item != correct_formula and item not in unique_candidates:
            unique_candidates.append(item)
        if len(unique_candidates) == 3:
            break

    if len(unique_candidates) < 3:
        raise RuntimeError("Impossibile generare 3 opzioni sbagliate distinte per il quiz proposizionale")
    return unique_candidates


def _build_translation_question_propositional(
    *,
    names_pool: Sequence[str],
    actions_pool: Sequence[str],
    rng: random.Random,
) -> dict[str, Any]:
    """Costruisce un quiz di traduzione in logica proposizionale."""
    if len(names_pool) < 1:
        raise ValueError("names_pool deve contenere almeno 1 nome")
    if len(actions_pool) < 1:
        raise ValueError("actions_pool deve contenere almeno 1 azione")

    action = rng.choice(list(actions_pool))

    template_name = rng.choice(["implication", "conjunction_chain", "disjunction_chain"])

    # Determine how many distinct symbol texts we need (2 for implication, 3 otherwise)
    symbols_needed = 2 if template_name == "implication" else 3

    # Build possible distinct texts from names x actions
    possible_texts = [f"{name} {act}" for name in names_pool for act in actions_pool]

    if len(possible_texts) >= symbols_needed:
        # Choose distinct texts when possible to avoid duplicate hypotheses
        chosen_texts = rng.sample(possible_texts, k=symbols_needed)
        # Fill symbol_to_text mapping ensuring all symbols exist
        all_symbols = ["P", "Q", "R"]
        symbol_to_text = {}
        for i, sym in enumerate(all_symbols):
            if i < symbols_needed:
                symbol_to_text[sym] = chosen_texts[i]
            else:
                # For unused extra symbols, pick a random (possibly duplicate) fallback
                symbol_to_text[sym] = f"{rng.choice(list(names_pool))} {action}"
    else:
        # Not enough distinct combos available: fall back to previous behavior (allow repetitions)
        symbol_to_text = {
            "P": f"{rng.choice(list(names_pool))} {action}",
            "Q": f"{rng.choice(list(names_pool))} {action}",
            "R": f"{rng.choice(list(names_pool))} {action}",
        }
    if template_name == "implication":
        atoms = _pick_symbol_sequence(
            symbols=["P", "Q", "R"],
            length=2,
            rng=rng,
            repetition_probability=FORMULA_REPETITION_PROBABILITY,
        )
        left, right = atoms
        sentence = f"Se {symbol_to_text[left]} allora {symbol_to_text[right]}"
        correct_formula = f"imp({left},{right})"
    elif template_name == "conjunction_chain":
        atoms = _pick_symbol_sequence(
            symbols=["P", "Q", "R"],
            length=3,
            rng=rng,
            repetition_probability=FORMULA_REPETITION_PROBABILITY,
        )
        first, second, third = atoms
        sentence = f"{symbol_to_text[first]} e {symbol_to_text[second]} e {symbol_to_text[third]}"
        correct_formula = f"and(and({first},{second}),{third})"
    else:
        atoms = _pick_symbol_sequence(
            symbols=["P", "Q", "R"],
            length=3,
            rng=rng,
            repetition_probability=FORMULA_REPETITION_PROBABILITY,
        )
        first, second, third = atoms
        sentence = f"{symbol_to_text[first]} o {symbol_to_text[second]} o {symbol_to_text[third]}"
        correct_formula = f"or(or({first},{second}),{third})"

    question_text = f'Tradurre la seguente frase in linguaggio logico: "{sentence}"'
    info = [f"{symbol} = {text}" for symbol, text in symbol_to_text.items()]
    wrong_formulas = _build_propositional_wrong_formulas(
        template_name=template_name,
        atoms=atoms,
        correct_formula=correct_formula,
    )
    options = [
        {"formula": correct_formula, "is_correct": True},
        *({"formula": item, "is_correct": False} for item in wrong_formulas),
    ]
    rng.shuffle(options)

    return {
        "type": "translation_question",
        "subtype": "propositional",
        "question_text": question_text,
        "info": info,
        "options": options,
        "correct_options_count": 1,
        "wrong_options_count": 3,
        "metadata": {
            "quantifier_used": "none",
            "names_used": [name for name in names_pool if any(name in text for text in symbol_to_text.values())],
            "actions_used": [action],
            "template_used": template_name,
            "repetition_used": len(set(atoms)) < len(atoms),
            "source": "rule_generator",
        },
    }


def _fold_binary_connective(connective: str, terms: Sequence[str]) -> str:
    """Combina termini in una catena binaria associativa (es. and(and(a,b),c))."""
    if not terms:
        raise ValueError("terms non puo essere vuoto")
    folded = terms[0]
    for term in terms[1:]:
        folded = f"{connective}({folded},{term})"
    return folded


def _predicate_symbols(count: int) -> list[str]:
    """Restituisce simboli predicato in stile A, B, C, ... per il quiz quantificato."""
    _req_int_ge("count", count, 1)
    base = [chr(code) for code in range(ord("A"), ord("Z") + 1)]
    if count <= len(base):
        return base[:count]

    extended = list(base)
    suffix = 1
    while len(extended) < count:
        for symbol in base:
            extended.append(f"{symbol}{suffix}")
            if len(extended) >= count:
                break
        suffix += 1
    return extended


def _build_translation_question_quantifier(
    *,
    actions_pool: Sequence[str],
    predicate_count: int,
    rng: random.Random,
) -> dict[str, Any]:
    """Costruisce un quiz di traduzione con quantificatori."""
    _req_int_ge("predicate_count", predicate_count, 1)
    if len(actions_pool) < predicate_count:
        raise ValueError("actions_pool deve contenere almeno people_count azioni per il subtype quantifier")

    selected_actions = rng.sample(list(actions_pool), predicate_count)
    symbols = _predicate_symbols(predicate_count)
    predicate_terms = [f"{symbol}(x)" for symbol in symbols]
    conjunction_body = _fold_binary_connective("and", predicate_terms)
    disjunction_body = _fold_binary_connective("or", predicate_terms)

    rest_terms = predicate_terms[1:]
    if rest_terms:
        implication_body = f"imp({predicate_terms[0]},{_fold_binary_connective('and', rest_terms)})"
    else:
        implication_body = f"imp({predicate_terms[0]},not({predicate_terms[0]}))"

    natural_text = " e ".join(f"x {action}" for action in selected_actions)
    quantifier_used = rng.choice(["per_ogni", "esiste"])

    if quantifier_used == "per_ogni":
        question_text = (
            "Tradurre la seguente frase in linguaggio logico: "
            f'"Per ogni x, {natural_text}"'
        )
        correct_formula = f"forall(x,{conjunction_body})"
        wrong_formulas = [
            f"exists(x,{conjunction_body})",
            f"forall(x,{disjunction_body})",
            f"forall(x,{implication_body})",
        ]
    else:
        question_text = (
            "Tradurre la seguente frase in linguaggio logico: "
            f'"Esiste un x tale che {natural_text}"'
        )
        correct_formula = f"exists(x,{conjunction_body})"
        wrong_formulas = [
            f"forall(x,{conjunction_body})",
            f"exists(x,{disjunction_body})",
            f"exists(x,{implication_body})",
        ]

    info = [f"{symbol}(x) = x {action}" for symbol, action in zip(symbols, selected_actions, strict=False)]

    options = [
        {"formula": correct_formula, "is_correct": True},
        *({"formula": item, "is_correct": False} for item in wrong_formulas),
    ]
    rng.shuffle(options)

    return {
        "type": "translation_question",
        "subtype": "quantifier",
        "question_text": question_text,
        "info": info,
        "options": options,
        "correct_options_count": 1,
        "wrong_options_count": 3,
        "metadata": {
            "quantifier_used": quantifier_used,
            "names_used": [],
            "actions_used": selected_actions,
            "predicate_symbols_used": symbols,
            "source": "rule_generator",
        },
    }


def build_translation_question(
    *,
    mode: str,
    quantifier_ratio: float,
    wrong_options_count: int = 3,
    names_pool: Sequence[str],
    people_count: int | None = None,
    actions_pool: Sequence[str],
    allow_spoken_mode: bool,
    seed: int | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    """Costruisce un quiz di traduzione italiano -> logica con 4 opzioni totali."""
    _req_int_ge("timeout", int(timeout), 1)
    if wrong_options_count != 3:
        raise ValueError("wrong_options_count deve essere 3")
    if not (0 <= quantifier_ratio <= 1):
        raise ValueError("quantifier_ratio deve essere compreso tra 0 e 1")
    if not names_pool:
        raise ValueError("names_pool non può essere vuoto")
    if people_count is not None:
        _req_int_ge("people_count", int(people_count), 1)
    if not actions_pool:
        raise ValueError("actions_pool non può essere vuoto")

    # Campo mantenuto nel contratto per compatibilita futura: al momento non altera la generazione.
    _ = allow_spoken_mode

    rng = random.Random(seed)
    subtype = _pick_translation_subtype(mode, quantifier_ratio, rng)
    if subtype == "quantifier":
        quantifier_predicate_count = people_count if people_count is not None else 2
        result = _build_translation_question_quantifier(
            actions_pool=actions_pool,
            predicate_count=quantifier_predicate_count,
            rng=rng,
        )
    else:
        normalized_names_pool = [name for name in dict.fromkeys(names_pool)]
        if people_count is not None and people_count > len(normalized_names_pool):
            raise ValueError("people_count non può superare il numero di nomi distinti in names_pool")
        selected_names_pool = (
            list(normalized_names_pool)
            if people_count is None
            else rng.sample(list(normalized_names_pool), people_count)
        )
        result = _build_translation_question_propositional(
            names_pool=selected_names_pool,
            actions_pool=actions_pool,
            rng=rng,
        )

    options = result["options"]
    if len(options) != 4:
        raise RuntimeError("Postcondizione fallita: le opzioni devono essere esattamente 4")
    if sum(1 for option in options if option["is_correct"]) != 1:
        raise RuntimeError("Postcondizione fallita: deve esserci esattamente 1 opzione corretta")
    if len({option["formula"] for option in options}) != len(options):
        raise RuntimeError("Postcondizione fallita: le opzioni devono essere tutte distinte")

    if subtype == "propositional":
        for option in options:
            formula = option["formula"]
            if "x" in formula or "forall(" in formula or "exists(" in formula:
                raise RuntimeError("Postcondizione fallita: formula proposizionale non valida")

    result["metadata"]["seed"] = seed
    result["metadata"]["people_count"] = people_count
    _ensure_keys(result, ["type", "subtype", "question_text", "info", "options", "metadata"])
    return result


def _question_identity_key(operation: str, result: Any) -> str:
    """Costruisce una chiave stabile per identificare domande duplicate nel batch."""
    if not isinstance(result, dict):
        return f"{operation}|{json.dumps(result, sort_keys=True, ensure_ascii=False)}"

    if "question_text" in result:
        identity = {
            "question_text": result.get("question_text"),
            "subtype": result.get("subtype"),
        }
    elif "question_prolog" in result:
        identity = {"question_prolog": result.get("question_prolog")}
    elif "information" in result:
        identity = {
            "information": result.get("information"),
            "predicate_count": result.get("predicate_count"),
        }
    else:
        identity = result

    return f"{operation}|{json.dumps(identity, sort_keys=True, ensure_ascii=False)}"


def multiple_questions(
    questions: Sequence[dict[str, Any]],
    seed: int | None = None,
    bridge: PrologBridge | None = None,
) -> dict[str, Any]:
    """Costruisce piu domande in una singola chiamata e mescola l'output finale.

    Il batch e fail-soft: un singolo errore viene catturato e restituito nel suo envelope
    senza interrompere la generazione degli altri elementi.
    """
    if not questions:
        raise ValueError("questions non può essere vuoto")

    bridge = _ensure_bridge(bridge)
    rng = random.Random(seed)

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
                        result = build_exercise(bridge=bridge, **attempt_payload)
                    elif normalized_operation == "build_ex_depth":
                        result = build_ex_depth(bridge=bridge, **attempt_payload)
                    elif normalized_operation == "build_tvq":
                        result = build_tvq(bridge=bridge, **attempt_payload)
                    elif normalized_operation == "build_logical_consequence_question":
                        result = build_logical_consequence_question(bridge=bridge, **attempt_payload)
                    else:
                        result = build_translation_question(**attempt_payload)

                    question_key = _question_identity_key(normalized_operation, result)
                    if question_key in used_question_keys:
                        last_error = RuntimeError("Domanda duplicata nel batch")
                        continue

                    used_payload = attempt_payload
                    used_question_keys.add(question_key)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
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
    _ensure_keys(batch, ["type", "count", "success_count", "failed_count", "questions"])
    return batch

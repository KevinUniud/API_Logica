from __future__ import annotations

import importlib
import inspect
# Gestione path runtime per includere il package Python locale.
import os
import sys
# Tipi usati nelle firme degli handler.
from collections.abc import Callable
from typing import Any

# Runtime ASGI locale.
import uvicorn
# Componenti FastAPI per endpoint, validazione input e gestione errori.
from fastapi import Body
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
# Modelli Pydantic per request/response schema.
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_DIR = os.path.join(BASE_DIR, "..", "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

generator = importlib.import_module("generator")
_prolog_bridge_module = importlib.import_module("prolog_bridge")

# Bridge Prolog e relative eccezioni esposte come HTTP error handlers.
PrologBridge = _prolog_bridge_module.PrologBridge
PrologBridgeError = _prolog_bridge_module.PrologBridgeError
PrologExecutionError = _prolog_bridge_module.PrologExecutionError
PrologNotFoundError = _prolog_bridge_module.PrologNotFoundError
from_prolog = _prolog_bridge_module.from_prolog
get_default_bridge = _prolog_bridge_module.get_default_bridge


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValuationEntry(ApiModel):
    name: str = Field(description="Nome della variabile proposizionale")
    value: bool = Field(description="Valore booleano della variabile")


class RequestBase(ApiModel):
    timeout: int = Field(default=10, ge=1, le=120, description="Timeout della chiamata in secondi")


class FormulaRequest(RequestBase):
    expr: str = Field(description="Formula in sintassi Prolog, per esempio and(p,q)")


class FormulaPayloadRequest(FormulaRequest):
    extra: dict[str, Any] | None = Field(default=None, description="Campi extra da includere nel payload")


class VarsRequest(RequestBase):
    vars_list: list[str] = Field(description="Lista di variabili proposizionali")


class FormulaVarsRequest(FormulaRequest):
    vars_list: list[str] | None = Field(default=None, description="Variabili da usare per l'operazione")


class EvalRequest(FormulaRequest):
    valuation: list[ValuationEntry | str] = Field(
        description="Valutazione come lista di oggetti {name, value} o stringhe gia in formato Prolog"
    )


class BinaryFormulaRequest(RequestBase):
    left: str = Field(description="Formula sinistra in sintassi Prolog")
    right: str = Field(description="Formula destra in sintassi Prolog")
    vars_list: list[str] | None = Field(default=None, description="Variabili da usare nel controllo")


class BinaryValuationRequest(RequestBase):
    left: str = Field(description="Formula sinistra in sintassi Prolog")
    right: str = Field(description="Formula destra in sintassi Prolog")
    valuation: list[ValuationEntry | str] = Field(
        description="Valutazione come lista di oggetti {name, value} o stringhe gia in formato Prolog"
    )


class DepthRequest(RequestBase):
    depth: int = Field(ge=0, description="Profondita della formula")
    variables: list[str] = Field(description="Variabili disponibili")
    use_all: bool = Field(default=False, description="Se vero, usa tutte le formule della profondita indicata")
    seed: int | None = Field(default=None, description="Seed casuale")


class DistractMaxStepsRequest(FormulaRequest):
    max_steps: int = Field(ge=1, description="Numero massimo di passi di distrazione")


class DistractExactRequest(FormulaRequest):
    steps: int = Field(ge=0, description="Numero esatto di passi di distrazione")


class DistractNRequest(FormulaRequest):
    max_steps: int = Field(ge=1, description="Numero massimo di passi di distrazione")
    n: int = Field(ge=0, description="Numero massimo di distractor da restituire")


class AutoDepthRequest(RequestBase):
    variables: list[str] = Field(description="Variabili disponibili")
    use_all: bool = Field(default=False, description="Se vero, usa tutte le formule candidate")
    seed: int | None = Field(default=None, description="Seed casuale")


class GeneratorAutoDepthRequest(RequestBase):
    use_all: bool = Field(default=False, description="Se vero, usa tutte le formule candidate")
    seed: int | None = Field(default=None, description="Seed casuale")
    wrong_answers_count: int = Field(default=3, ge=1, description="Numero di distrazioni errate")


class GeneratorExprRequest(FormulaRequest):
    wrong_answers_count: int = Field(default=3, ge=1, description="Numero di distrazioni errate")
    seed: int | None = Field(default=None, description="Seed casuale")


class TruthValueOptionsRequest(RequestBase):
    predicate_count: int = Field(
        ge=4,
        le=5,
        description="Numero di predicati atomici (solo 4 o 5, per usare set variabili automatici)",
    )
    true_options_count: int = Field(ge=1, description="Numero di opzioni che devono risultare vere")
    false_options_count: int = Field(ge=1, description="Numero di opzioni che devono risultare false")
    seed: int | None = Field(default=None, description="Seed casuale")


class FormulaByVariableCountRequest(RequestBase):
    variable_count: int = Field(ge=1, description="Numero esatto di variabili da usare nella formula")
    use_all: bool = Field(default=False, description="Se vero, usa il set completo di formule candidate")
    seed: int | None = Field(default=None, description="Seed casuale")


class LogicalConsequenceQuestionRequest(RequestBase):
    variable_count: int = Field(ge=1, description="Numero di variabili da usare nella formula domanda")
    correct_options_count: int = Field(ge=1, description="Numero di opzioni che devono essere conseguenze logiche")
    wrong_options_count: int = Field(ge=1, description="Numero di opzioni che non devono essere conseguenze logiche")
    seed: int | None = Field(default=None, description="Seed casuale")


class TranslationQuestionRequest(ApiModel):
    mode: str = Field(description="Modalita di generazione: auto, quantifier, propositional")
    quantifier_ratio: float = Field(ge=0, le=1, description="Probabilita subtype quantifier quando mode=auto")
    wrong_options_count: int = Field(default=3, ge=1, description="Numero di opzioni sbagliate")
    names_pool: list[str] = Field(description="Pool ufficiale nomi frontend")
    people_count: int | None = Field(
        default=None,
        ge=1,
        description="Numero di persone da usare (campionate dal names_pool)",
    )
    actions_pool: list[str] = Field(description="Pool ufficiale azioni frontend")
    allow_spoken_mode: bool = Field(
        default=False,
        description="Flag mantenuto per compatibilita del contratto",
    )
    seed: int | None = Field(default=None, description="Seed casuale")
    timeout_seconds: int = Field(default=10, ge=1, le=120, description="Timeout della chiamata in secondi")


class MultipleQuestionItemRequest(ApiModel):
    operation: str = Field(description="Nome della funzione generator da invocare")
    payload: dict[str, Any] = Field(description="Argomenti della funzione richiesta")


class MultipleQuestionsRequest(ApiModel):
    questions: list[MultipleQuestionItemRequest] = Field(
        min_length=1,
        description="Lista eterogenea di funzioni con le rispettive specifiche",
    )
    seed: int | None = Field(default=None, description="Seed casuale usato per il mescolamento finale")


class OperationResponse(ApiModel):
    operation: str
    result: Any


class ErrorResponse(ApiModel):
    detail: str


OPENAPI_TAGS = [
    {"name": "meta", "description": "Endpoint informativi e di stato del servizio."},
    {"name": "generator", "description": "Endpoint espliciti per ogni funzione pubblica di python/generator.py."},
    {"name": "prolog-bridge-logic", "description": "Endpoint espliciti per i metodi logic di PrologBridge."},
    {"name": "prolog-bridge-equivalence", "description": "Endpoint espliciti per i metodi equivalence di PrologBridge."},
    {"name": "prolog-bridge-rewrite", "description": "Endpoint espliciti per i metodi rewrite di PrologBridge."},
    {"name": "prolog-bridge-templates", "description": "Endpoint espliciti per i metodi templates di PrologBridge."},
    {"name": "prolog-bridge-distractions", "description": "Endpoint espliciti per i metodi distractions di PrologBridge."},
]


ERROR_RESPONSES = {
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


FORMULA_EXAMPLES = {
    "basic": {
        "summary": "Formula semplice",
        "value": {"expr": "and(p,q)", "timeout": 10},
    }
}

VARS_EXAMPLES = {
    "variables": {
        "summary": "Lista di variabili",
        "value": {"vars_list": ["p", "q", "r"], "timeout": 10},
    }
}

EVAL_EXAMPLES = {
    "valuation": {
        "summary": "Valutazione esplicita",
        "value": {
            "expr": "and(p,q)",
            "valuation": [{"name": "p", "value": True}, {"name": "q", "value": False}],
            "timeout": 10,
        },
    }
}

BINARY_EXAMPLES = {
    "equiv": {
        "summary": "Confronto tra due formule",
        "value": {
            "left": "imp(p,q)",
            "right": "or(not(p),q)",
            "vars_list": ["p", "q"],
            "timeout": 10,
        },
    }
}

BINARY_VALUATION_EXAMPLES = {
    "under-valuation": {
        "summary": "Confronto sotto una valutazione",
        "value": {
            "left": "and(p,q)",
            "right": "or(p,q)",
            "valuation": [{"name": "p", "value": True}, {"name": "q", "value": False}],
            "timeout": 10,
        },
    }
}

DEPTH_EXAMPLES = {
    "depth": {
        "summary": "Generazione per profondita",
        "value": {"depth": 2, "variables": ["p", "q"], "use_all": False, "seed": 42, "timeout": 10},
    }
}

DISTRACT_MAX_STEPS_EXAMPLES = {
    "max-steps": {
        "summary": "Distrazione con massimo numero di passi",
        "value": {"expr": "and(p,q)", "max_steps": 2, "timeout": 10},
    }
}

DISTRACT_EXACT_EXAMPLES = {
    "exact-steps": {
        "summary": "Distrazione con numero esatto di passi",
        "value": {"expr": "and(p,q)", "steps": 2, "timeout": 10},
    }
}

DISTRACT_N_EXAMPLES = {
    "bounded-list": {
        "summary": "Distrazioni limitate a N risultati",
        "value": {"expr": "and(p,q)", "max_steps": 2, "n": 3, "timeout": 10},
    }
}

FORMULA_PAYLOAD_EXAMPLES = {
    "payload": {
        "summary": "Payload formula con metadati extra",
        "value": {"expr": "and(p,q)", "extra": {"source": "manual"}, "timeout": 10},
    }
}

GENERATOR_EXPR_EXAMPLES = {
    "exercise-from-expr": {
        "summary": "Esercizio a partire da una formula",
        "value": {"expr": "or(p,imp(q,p))", "wrong_answers_count": 3, "seed": 42, "timeout": 10},
    }
}

GENERATOR_DEPTH_EXAMPLES = {
    "exercise-from-variables": {
        "summary": "Esercizio con variabili automatiche (profondita automatica)",
        "value": {
            "use_all": False,
            "seed": 42,
            "wrong_answers_count": 3,
            "timeout": 10,
        },
    }
}

AUTO_DEPTH_EXAMPLES = {
    "formula-from-variables": {
        "summary": "Generazione formula da variabili (profondita automatica)",
        "value": {
            "variables": ["p", "q", "r"],
            "use_all": False,
            "seed": 42,
            "timeout": 10,
        },
    }
}

TRUTH_VALUE_OPTIONS_EXAMPLES = {
    "truth-value-options": {
        "summary": "Domanda con informazioni sui predicati e opzioni vere/false",
        "value": {
            "predicate_count": 4,
            "true_options_count": 2,
            "false_options_count": 2,
            "seed": 42,
            "timeout": 10,
        },
    }
}

FORMULA_BY_VARIABLE_COUNT_EXAMPLES = {
    "formula-by-variable-count": {
        "summary": "Generazione formula con numero variabili esplicito",
        "value": {
            "variable_count": 4,
            "use_all": False,
            "seed": 42,
            "timeout": 10,
        },
    }
}

LOGICAL_CONSEQUENCE_QUESTION_EXAMPLES = {
    "logical-consequence-question": {
        "summary": "Quiz di conseguenza logica con opzioni corrette/errate",
        "value": {
            "variable_count": 4,
            "correct_options_count": 2,
            "wrong_options_count": 2,
            "seed": 42,
            "timeout": 10,
        },
    }
}

TRANSLATION_QUESTION_EXAMPLES = {
    "translation-question": {
        "summary": "Quiz di traduzione italiano -> logica",
        "value": {
            "mode": "auto",
            "quantifier_ratio": 0.5,
            "wrong_options_count": 3,
            "names_pool": ["Luca", "Matteo", "Alessandro", "Marco", "Davide", "Giulia", "Sofia", "Martina", "Chiara", "Elisa"],
            "people_count": 2,
            "actions_pool": ["nuota", "corre", "salta", "guarda", "parla", "apre", "chiude", "ascolta"],
            "allow_spoken_mode": False,
            "seed": 12345,
            "timeout_seconds": 10,
        },
    }
}

MULTIPLE_QUESTIONS_EXAMPLES = {
    "batch-mixed": {
        "summary": "Batch di domande miste",
        "value": {
            "seed": 42,
            "questions": [
                {
                    "operation": "build_tvq",
                    "payload": {
                        "predicate_count": 4,
                        "true_options_count": 1,
                        "false_options_count": 1,
                        "seed": 7,
                    },
                },
                {
                    "operation": "build_translation_question",
                    "payload": {
                        "mode": "auto",
                        "quantifier_ratio": 0.5,
                        "wrong_options_count": 3,
                        "names_pool": ["Luca", "Marco"],
                        "people_count": 2,
                        "actions_pool": ["corre", "salta"],
                        "allow_spoken_mode": False,
                        "seed": 11,
                        "timeout": 10,
                    },
                },
            ],
        },
    }
}


app = FastAPI(
    title="TestLogica API",
    summary="OpenAPI 3.1 per generator.py e PrologBridge",
    description=(
        "API HTTP che espone le funzioni pubbliche del generatore di esercizi logici e i metodi pubblici del bridge Prolog. "
        "La specifica OpenAPI e generata in formato 3.1.0 e documenta endpoint distinti per ogni funzione esposta."
    ),
    version="1.1.0",
    openapi_version="3.1.0",
    openapi_tags=OPENAPI_TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_bridge() -> PrologBridge:
    """Restituisce il bridge Prolog condiviso con configurazione fissa."""
    return get_default_bridge()


def _parse_formula(expr: str):
    """Parsa una formula Prolog e converte gli errori in risposta HTTP 422."""
    try:
        return from_prolog(expr)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Formula non valida: {exc}") from exc


def _normalize_valuation(valuation: list[ValuationEntry | str]) -> list[tuple[str, bool] | str]:
    """Normalizza la valutazione in tuple `(nome, valore)` o stringhe Prolog."""
    normalized: list[tuple[str, bool] | str] = []
    for item in valuation:
        if isinstance(item, str):
            normalized.append(item)
        else:
            normalized.append((item.name, item.value))
    return normalized


def _wrap(operation: str, result: Any) -> OperationResponse:
    """Impacchetta il risultato nel formato uniforme di risposta API."""
    return OperationResponse(operation=operation, result=result)


def _formula_handler(method_name: str, *, with_vars: bool = False) -> Callable[[Any], Any]:
    """Crea un handler generico per metodi bridge che accettano una formula."""
    def handler(payload):
        kwargs: dict[str, Any] = {"timeout": payload.timeout}
        if with_vars:
            kwargs["vars_list"] = payload.vars_list
        return getattr(_build_bridge(), method_name)(payload.expr, **kwargs)

    return handler


def _binary_handler(method_name: str) -> Callable[[Any], Any]:
    """Crea un handler per metodi bridge che confrontano due formule."""
    def handler(payload):
        return getattr(_build_bridge(), method_name)(
            payload.left,
            payload.right,
            vars_list=payload.vars_list,
            timeout=payload.timeout,
        )

    return handler


def _binary_val_handler(method_name: str) -> Callable[[Any], Any]:
    """Crea un handler per metodi bridge con due formule e valutazione esplicita."""
    def handler(payload):
        return getattr(_build_bridge(), method_name)(
            payload.left,
            payload.right,
            _normalize_valuation(payload.valuation),
            timeout=payload.timeout,
        )

    return handler


def _depth_handler(method_name: str) -> Callable[[Any], Any]:
    """Crea un handler per metodi bridge basati su profondita e variabili."""
    def handler(payload):
        return getattr(_build_bridge(), method_name)(
            payload.depth,
            payload.variables,
            timeout=payload.timeout,
        )

    return handler


def _steps_handler(method_name: str) -> Callable[[Any], Any]:
    """Crea un handler per metodi bridge con parametro `max_steps`."""
    def handler(payload):
        return getattr(_build_bridge(), method_name)(
            payload.expr,
            max_steps=payload.max_steps,
            timeout=payload.timeout,
        )

    return handler


def _add_post_route(
    *,
    path: str,
    operation_id: str,
    tag: str,
    summary: str,
    description: str,
    payload_model: type[BaseModel],
    examples: dict[str, Any],
    handler: Callable[[Any], Any],
) -> None:
    """Registra dinamicamente una route POST con metadati OpenAPI completi."""
    def endpoint(payload):
        return _wrap(operation_id, handler(payload))

    endpoint.__name__ = f"{operation_id}_endpoint"
    endpoint.__doc__ = description
    endpoint.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                "payload",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=Body(..., openapi_examples=examples),
                annotation=payload_model,
            )
        ]
    )
    app.add_api_route(
        path,
        endpoint,
        methods=["POST"],
        tags=[tag],
        summary=summary,
        description=description,
        operation_id=operation_id,
        response_model=OperationResponse,
        responses=ERROR_RESPONSES,
    )


@app.exception_handler(PrologNotFoundError)
def prolog_not_found(_, exc: PrologNotFoundError):
    """Converte errore di dipendenza SWI-Prolog mancante in HTTP 503."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(PrologExecutionError)
def prolog_exec(_, exc: PrologExecutionError):
    """Converte errori di esecuzione Prolog in HTTP 502."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(PrologBridgeError)
def prolog_bridge_err(_, exc: PrologBridgeError):
    """Converte errori generici del bridge in HTTP 500."""
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(ValueError)
def value_err(_, exc: ValueError):
    """Converte errori di validazione applicativa in HTTP 422."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(RuntimeError)
def runtime_err(_, exc: RuntimeError):
    """Converte errori runtime applicativi (es. generazione impossibile) in HTTP 422."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/", tags=["meta"], summary="Informazioni sul servizio")
def home() -> dict[str, Any]:
    """Restituisce metadati base e link di documentazione del servizio."""
    return {
        "message": "TestLogica API attiva",
        "openapi": "/openapi.json",
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi_version": app.openapi_version,
    }


@app.get("/health", tags=["meta"], summary="Stato del servizio")
def health() -> dict[str, str]:
    """Espone un controllo di salute minimale del backend."""
    return {"status": "ok"}


_add_post_route(
    path="/api/prolog-bridge/logic/assignment",
    operation_id="bridge_assignment",
    tag="prolog-bridge-logic",
    summary="Genera valutazioni per un insieme di variabili",
    description="Espone PrologBridge.assignment e restituisce tutte le valutazioni booleane possibili per la lista di variabili fornita.",
    payload_model=VarsRequest,
    examples=VARS_EXAMPLES,
    handler=lambda payload: _build_bridge().assignment(payload.vars_list, timeout=payload.timeout),
)

_add_post_route(
    path="/api/prolog-bridge/logic/eval",
    operation_id="bridge_eval",
    tag="prolog-bridge-logic",
    summary="Valuta una formula sotto una valutazione",
    description="Espone PrologBridge.eval e restituisce il valore booleano della formula sotto la valutazione fornita.",
    payload_model=EvalRequest,
    examples=EVAL_EXAMPLES,
    handler=lambda payload: _build_bridge().eval(
        payload.expr,
        _normalize_valuation(payload.valuation),
        timeout=payload.timeout,
    ),
)

_add_post_route(
    path="/api/prolog-bridge/logic/vars-in-formula",
    operation_id="bridge_vars_in_formula",
    tag="prolog-bridge-logic",
    summary="Estrae le variabili di una formula",
    description="Espone PrologBridge.vars_in_formula e restituisce la lista ordinata delle variabili presenti nella formula.",
    payload_model=FormulaRequest,
    examples=FORMULA_EXAMPLES,
    handler=_formula_handler("vars_in_formula"),
)

_add_post_route(
    path="/api/prolog-bridge/logic/truth-table-auto",
    operation_id="bridge_truth_table_auto",
    tag="prolog-bridge-logic",
    summary="Costruisce la tabella di verita con variabili auto-rilevate",
    description="Espone PrologBridge.truth_table_auto e restituisce variabili e righe della tabella di verita.",
    payload_model=FormulaRequest,
    examples=FORMULA_EXAMPLES,
    handler=_formula_handler("truth_table_auto"),
)

_add_post_route(
    path="/api/prolog-bridge/equivalence/equiv",
    operation_id="bridge_equiv",
    tag="prolog-bridge-equivalence",
    summary="Verifica equivalenza logica",
    description="Espone PrologBridge.equiv e restituisce true se le due formule sono logicamente equivalenti sulle variabili fornite.",
    payload_model=BinaryFormulaRequest,
    examples=BINARY_EXAMPLES,
    handler=_binary_handler("equiv"),
)

_add_post_route(
    path="/api/prolog-bridge/equivalence/not-equiv",
    operation_id="bridge_not_equiv",
    tag="prolog-bridge-equivalence",
    summary="Verifica non equivalenza logica",
    description="Espone PrologBridge.not_equiv e restituisce true se esiste almeno una valutazione che distingue le due formule.",
    payload_model=BinaryFormulaRequest,
    examples=BINARY_EXAMPLES,
    handler=_binary_handler("not_equiv"),
)

_add_post_route(
    path="/api/prolog-bridge/equivalence/counterexample-equiv",
    operation_id="bridge_counterexample_equiv",
    tag="prolog-bridge-equivalence",
    summary="Restituisce controesempi di equivalenza",
    description="Espone PrologBridge.counterexample_equiv e restituisce le valutazioni che mostrano la non equivalenza.",
    payload_model=BinaryFormulaRequest,
    examples=BINARY_EXAMPLES,
    handler=_binary_handler("counterexample_equiv"),
)

for path_suffix, operation_id, summary in [
    ("all-models", "bridge_all_models", "Restituisce tutti i modelli"),
    ("all-countermodels", "bridge_all_countermodels", "Restituisce tutti i contromodelli"),
    ("model", "bridge_model", "Restituisce un modello"),
    ("countermodel", "bridge_countermodel", "Restituisce un contromodello"),
    ("tautology", "bridge_tautology", "Verifica se la formula e una tautologia"),
    ("contradiction", "bridge_contradiction", "Verifica se la formula e una contraddizione"),
    ("satisfiable", "bridge_satisfiable", "Verifica se la formula e soddisfacibile"),
    ("unsatisfiable", "bridge_unsatisfiable", "Verifica se la formula e insoddisfacibile"),
    ("satisfying-assignment", "bridge_satisfying_assignment", "Restituisce una assegnazione soddisfacente"),
    ("falsifying-assignment", "bridge_falsifying_assignment", "Restituisce una assegnazione falsificante"),
]:
    method_name = operation_id.removeprefix("bridge_").replace("-", "_")
    _add_post_route(
        path=f"/api/prolog-bridge/equivalence/{path_suffix}",
        operation_id=operation_id,
        tag="prolog-bridge-equivalence",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per una singola formula.",
        payload_model=FormulaVarsRequest,
        examples=FORMULA_EXAMPLES,
        handler=_formula_handler(method_name, with_vars=True),
    )

for path_suffix, method_name, summary in [
    ("implies-formula", "implies_formula", "Verifica implicazione logica"),
    ("mutually-exclusive", "mutually_exclusive", "Verifica mutua esclusione"),
    ("jointly-satisfiable", "jointly_satisfiable", "Verifica soddisfacibilita congiunta"),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/equivalence/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-equivalence",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per due formule con una lista opzionale di variabili.",
        payload_model=BinaryFormulaRequest,
        examples=BINARY_EXAMPLES,
        handler=_binary_handler(method_name),
    )

for path_suffix, method_name, summary in [
    ("same-value-under", "same_value_under", "Confronta due formule sotto una valutazione"),
    ("different-value-under", "different_value_under", "Verifica se due formule differiscono sotto una valutazione"),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/equivalence/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-equivalence",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per due formule sotto una valutazione esplicita.",
        payload_model=BinaryValuationRequest,
        examples=BINARY_VALUATION_EXAMPLES,
        handler=_binary_val_handler(method_name),
    )

for path_suffix, method_name, summary in [
    ("rewrite-formula", "rewrite_formula", "Restituisce formule equivalenti ottenute con rewrite"),
    ("expand-implications", "expand_implications", "Espande le implicazioni"),
    ("to-nnf", "to_nnf", "Converte una formula in NNF"),
    ("to-cnf", "to_cnf", "Converte una formula in CNF"),
    ("to-dnf", "to_dnf", "Converte una formula in DNF"),
    ("rewrite-path", "rewrite_path", "Restituisce un percorso di rewrite"),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/rewrite/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-rewrite",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per una formula in sintassi Prolog.",
        payload_model=FormulaRequest,
        examples=FORMULA_EXAMPLES,
        handler=_formula_handler(method_name),
    )

for path_suffix, method_name, summary in [
    ("formula-of-depth", "formula_of_depth", "Genera formule di profondita esatta"),
    ("all-formulas-of-depth", "all_depth", "Restituisce tutte le formule della profondita richiesta"),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/templates/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-templates",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} usando profondita e variabili come input.",
        payload_model=DepthRequest,
        examples=DEPTH_EXAMPLES,
        handler=_depth_handler(method_name),
    )

for path_suffix, method_name, summary, payload_model, examples in [
    ("distract-formula", "distract_formula", "Genera distractor fino a un numero massimo di passi", DistractMaxStepsRequest, DISTRACT_MAX_STEPS_EXAMPLES),
    ("distract-formula-with-trace", "distract_trace", "Genera distractor con traccia", DistractMaxStepsRequest, DISTRACT_MAX_STEPS_EXAMPLES),
    ("all-distractions", "all_distractions", "Restituisce tutti i distractor fino a max_steps", DistractMaxStepsRequest, DISTRACT_MAX_STEPS_EXAMPLES),
    ("non-equivalent-distraction", "non_equivalent_distraction", "Genera distractor non equivalenti", DistractMaxStepsRequest, DISTRACT_MAX_STEPS_EXAMPLES),
    ("all-non-equivalent-distractions", "all_neq", "Restituisce tutti i distractor non equivalenti", DistractMaxStepsRequest, DISTRACT_MAX_STEPS_EXAMPLES),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/distractions/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-distractions",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per una formula con limite di passi.",
        payload_model=payload_model,
        examples=examples,
        handler=_steps_handler(method_name),
    )

_add_post_route(
    path="/api/prolog-bridge/distractions/distract-exactly",
    operation_id="bridge_distract_exactly",
    tag="prolog-bridge-distractions",
    summary="Genera distractor con numero esatto di passi",
    description="Espone PrologBridge.distract_exactly per una formula e un numero esatto di passi.",
    payload_model=DistractExactRequest,
    examples=DISTRACT_EXACT_EXAMPLES,
    handler=lambda payload: _build_bridge().distract_exactly(
        payload.expr,
        steps=payload.steps,
        timeout=payload.timeout,
    ),
)

_add_post_route(
    path="/api/prolog-bridge/distractions/distract-n",
    operation_id="bridge_distract_n",
    tag="prolog-bridge-distractions",
    summary="Restituisce al piu N distractor",
    description="Espone PrologBridge.distract_n per una formula, un massimo di passi e un limite N.",
    payload_model=DistractNRequest,
    examples=DISTRACT_N_EXAMPLES,
    handler=lambda payload: _build_bridge().distract_n(
        payload.expr,
        max_steps=payload.max_steps,
        n=payload.n,
        timeout=payload.timeout,
    ),
)

for path_suffix, method_name, summary in [
    ("one-step-distraction", "one_step_distraction", "Restituisce distractor in un solo passo"),
    ("one-step-non-equivalent-distraction", "one_step_neq", "Restituisce distractor non equivalenti in un solo passo"),
    ("all-one-step-non-equivalent-distractions", "all_step_neq", "Restituisce tutti i distractor non equivalenti in un solo passo"),
]:
    _add_post_route(
        path=f"/api/prolog-bridge/distractions/{path_suffix}",
        operation_id=f"bridge_{method_name}",
        tag="prolog-bridge-distractions",
        summary=summary,
        description=f"Espone PrologBridge.{method_name} per una formula con un solo passo di mutazione.",
        payload_model=FormulaRequest,
        examples=FORMULA_EXAMPLES,
        handler=_formula_handler(method_name),
    )

for path_suffix, operation_id, summary, payload_model, examples, handler in [
    ("formula-depth", "generator_formula_depth", "Calcola la profondita di una formula", FormulaRequest, FORMULA_EXAMPLES, lambda payload: generator.formula_depth(_parse_formula(payload.expr))),
    ("formula-size", "generator_formula_size", "Calcola la dimensione di una formula", FormulaRequest, FORMULA_EXAMPLES, lambda payload: generator.formula_size(_parse_formula(payload.expr))),
    ("formula-metadata", "generator_formula_metadata", "Restituisce i metadati di una formula", FormulaRequest, FORMULA_EXAMPLES, lambda payload: generator.formula_metadata(_parse_formula(payload.expr))),
    ("formula-payload", "generator_formula_payload", "Restituisce payload JSON di una formula", FormulaPayloadRequest, FORMULA_PAYLOAD_EXAMPLES, lambda payload: generator.formula_payload(_parse_formula(payload.expr), **(payload.extra or {}))),
    ("generate-formula", "generator_generate_formula", "Genera una formula in sintassi Prolog (profondita automatica)", AutoDepthRequest, AUTO_DEPTH_EXAMPLES, lambda payload: generator.generate_formula(variables=payload.variables, use_all=payload.use_all, timeout=payload.timeout, seed=payload.seed, bridge=_build_bridge())),
    ("generate-formula-json", "generator_generate_formula_json", "Genera una formula come JSON (profondita automatica)", AutoDepthRequest, AUTO_DEPTH_EXAMPLES, lambda payload: generator.generate_formula_json(variables=payload.variables, use_all=payload.use_all, timeout=payload.timeout, seed=payload.seed, bridge=_build_bridge())),
    ("generate-formula-by-variable-count", "generator_generate_formula_by_variable_count", "Genera una formula in sintassi Prolog con un numero specifico di variabili", FormulaByVariableCountRequest, FORMULA_BY_VARIABLE_COUNT_EXAMPLES, lambda payload: generator.generate_formula_by_variable_count(variable_count=payload.variable_count, use_all=payload.use_all, timeout=payload.timeout, seed=payload.seed, bridge=_build_bridge())),
    ("generate-formula-by-variable-count-json", "generator_generate_formula_by_variable_count_json", "Genera una formula con numero variabili esplicito e la restituisce come payload JSON", FormulaByVariableCountRequest, FORMULA_BY_VARIABLE_COUNT_EXAMPLES, lambda payload: generator.generate_formula_by_variable_count_json(variable_count=payload.variable_count, use_all=payload.use_all, timeout=payload.timeout, seed=payload.seed, bridge=_build_bridge())),
    ("build-exercise", "generator_build_exercise", "Costruisce un esercizio a partire da una formula", GeneratorExprRequest, GENERATOR_EXPR_EXAMPLES, lambda payload: generator.build_exercise(expr=payload.expr, wrong_answers_count=payload.wrong_answers_count, bridge=_build_bridge(), seed=payload.seed, timeout=payload.timeout)),
    ("build-exercise-from-depth", "generator_build_ex_depth", "Costruisce un esercizio con variabili automatiche (profondita automatica)", GeneratorAutoDepthRequest, GENERATOR_DEPTH_EXAMPLES, lambda payload: generator.build_ex_depth(use_all=payload.use_all, timeout=payload.timeout, seed=payload.seed, wrong_answers_count=payload.wrong_answers_count, bridge=_build_bridge())),
    ("build-truth-value-options-question", "generator_build_tvq", "Costruisce una domanda da informazioni booleane sui predicati e opzioni vere/false", TruthValueOptionsRequest, TRUTH_VALUE_OPTIONS_EXAMPLES, lambda payload: generator.build_tvq(predicate_count=payload.predicate_count, true_options_count=payload.true_options_count, false_options_count=payload.false_options_count, timeout=payload.timeout, seed=payload.seed, bridge=_build_bridge())),
    ("build-logical-consequence-question", "generator_build_logical_consequence_question", "Costruisce un quiz di conseguenza logica con opzioni corrette e errate", LogicalConsequenceQuestionRequest, LOGICAL_CONSEQUENCE_QUESTION_EXAMPLES, lambda payload: generator.build_logical_consequence_question(variable_count=payload.variable_count, correct_options_count=payload.correct_options_count, wrong_options_count=payload.wrong_options_count, timeout=payload.timeout, seed=payload.seed, bridge=_build_bridge())),
    ("build-translation-question", "generator_build_translation_question", "Costruisce un quiz di traduzione italiano -> logica", TranslationQuestionRequest, TRANSLATION_QUESTION_EXAMPLES, lambda payload: generator.build_translation_question(mode=payload.mode, quantifier_ratio=payload.quantifier_ratio, wrong_options_count=payload.wrong_options_count, names_pool=payload.names_pool, people_count=payload.people_count, actions_pool=payload.actions_pool, allow_spoken_mode=payload.allow_spoken_mode, seed=payload.seed, timeout=payload.timeout_seconds)),
    ("multiple-questions", "generator_multiple_questions", "Costruisce piu domande in una singola chiamata e le mescola", MultipleQuestionsRequest, MULTIPLE_QUESTIONS_EXAMPLES, lambda payload: generator.multiple_questions([item.model_dump() for item in payload.questions], seed=payload.seed, bridge=_build_bridge())),
    ("build-exercise-json-string", "generator_build_ex_json", "Costruisce un esercizio e lo serializza come stringa JSON", GeneratorExprRequest, GENERATOR_EXPR_EXAMPLES, lambda payload: generator.build_ex_json(expr=payload.expr, bridge=_build_bridge(), seed=payload.seed, wrong_answers_count=payload.wrong_answers_count, timeout=payload.timeout)),
    ("build-exercise-from-depth-json-string", "generator_build_ex_depth_json", "Costruisce un esercizio con variabili automatiche e lo serializza come stringa JSON", GeneratorAutoDepthRequest, GENERATOR_DEPTH_EXAMPLES, lambda payload: generator.build_ex_depth_json(use_all=payload.use_all, timeout=payload.timeout, seed=payload.seed, wrong_answers_count=payload.wrong_answers_count, bridge=_build_bridge())),
    ("build-truth-value-options-question-json-string", "generator_build_tvq_json", "Costruisce la domanda con opzioni vere/false e la serializza come JSON", TruthValueOptionsRequest, TRUTH_VALUE_OPTIONS_EXAMPLES, lambda payload: generator.build_tvq_json(predicate_count=payload.predicate_count, true_options_count=payload.true_options_count, false_options_count=payload.false_options_count, timeout=payload.timeout, seed=payload.seed, bridge=_build_bridge())),
    ("build-logical-consequence-question-json-string", "generator_build_logical_consequence_question_json", "Costruisce il quiz di conseguenza logica e lo serializza come JSON", LogicalConsequenceQuestionRequest, LOGICAL_CONSEQUENCE_QUESTION_EXAMPLES, lambda payload: generator.build_logical_consequence_question_json(variable_count=payload.variable_count, correct_options_count=payload.correct_options_count, wrong_options_count=payload.wrong_options_count, timeout=payload.timeout, seed=payload.seed, bridge=_build_bridge())),
]:
    _add_post_route(
        path=f"/api/generator/{path_suffix}",
        operation_id=operation_id,
        tag="generator",
        summary=summary,
        description=summary,
        payload_model=payload_model,
        examples=examples,
        handler=handler,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)
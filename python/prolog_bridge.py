from __future__ import annotations

# Gestione ciclo vita bridge e serializzazione richieste/risposte RPC.
import atexit
import json
# I/O non bloccante sul processo Prolog persistente.
import select
import shutil
import subprocess
import threading
# Cache locale per liste variabili gia normalizzate.
from functools import lru_cache
from pathlib import Path
# Tipi usati nelle firme pubbliche del bridge.
from typing import Iterable, Sequence

# Nodi AST logici usati nella conversione Python <-> Prolog.
from ast_logic import And, Iff, Imp, Not, Or, Var


# ============================================================
# Conversione AST <-> Prolog
# ============================================================


def to_prolog(expr):
    """Utility interna per conversione/validazione: to_prolog."""
    if isinstance(expr, Var):
        return expr.name
    if isinstance(expr, Not):
        return f"not({to_prolog(expr.expr)})"
    if isinstance(expr, And):
        return f"and({to_prolog(expr.left)},{to_prolog(expr.right)})"
    if isinstance(expr, Or):
        return f"or({to_prolog(expr.left)},{to_prolog(expr.right)})"
    if isinstance(expr, Imp):
        return f"imp({to_prolog(expr.left)},{to_prolog(expr.right)})"
    if isinstance(expr, Iff):
        return f"iff({to_prolog(expr.left)},{to_prolog(expr.right)})"
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


class PrologTermParser:
    def __init__(self, text: str):
        """Inizializza il parser per un termine Prolog serializzato."""
        self.text = text.strip()
        self.i = 0

    def parse(self):
        """Converte l'intera stringa Prolog in AST e verifica input consumato."""
        expr = self._parse_expr()
        self._skip_ws()
        if self.i != len(self.text):
            raise ValueError(f"Input Prolog non consumato completamente: {self.text!r}")
        return expr

    def _skip_ws(self):
        """Avanza l'indice ignorando gli spazi bianchi."""
        while self.i < len(self.text) and self.text[self.i].isspace():
            self.i += 1

    def _peek(self):
        """Restituisce il prossimo carattere non-spazio senza consumarlo."""
        self._skip_ws()
        if self.i >= len(self.text):
            return None
        return self.text[self.i]

    def _consume(self, token: str):
        """Consuma un token atteso o solleva errore di parsing."""
        self._skip_ws()
        if not self.text.startswith(token, self.i):
            found = self.text[self.i:self.i + 20]
            raise ValueError(f"Atteso {token!r} in posizione {self.i}, trovato: {found!r}")
        self.i += len(token)

    def _parse_ident(self):
        """Legge un identificatore Prolog (variabile/funtore)."""
        self._skip_ws()
        start = self.i
        while self.i < len(self.text):
            ch = self.text[self.i]
            if ch.isalnum() or ch == "_":
                self.i += 1
            else:
                break
        if start == self.i:
            raise ValueError(f"Identificatore atteso in posizione {self.i}")
        return self.text[start:self.i]

    def _parse_expr(self):
        """Parsa ricorsivamente una formula Prolog in nodi AST."""
        ident = self._parse_ident()
        self._skip_ws()

        if self._peek() != "(":
            return Var(ident)

        self._consume("(")

        if ident == "not":
            child = self._parse_expr()
            self._consume(")")
            return Not(child)

        left = self._parse_expr()
        self._consume(",")
        right = self._parse_expr()
        self._consume(")")

        if ident == "and":
            return And(left, right)
        if ident == "or":
            return Or(left, right)
        if ident == "imp":
            return Imp(left, right)
        if ident == "iff":
            return Iff(left, right)

        raise ValueError(f"Functore Prolog non supportato: {ident!r}")


def from_prolog(term: str):
    """Utility interna per conversione/validazione: from_prolog."""
    return PrologTermParser(term).parse()


# ============================================================
# Utility formule e valori
# ============================================================


def collect_variables(expr):
    """Utility interna per conversione/validazione: collect_variables."""
    if isinstance(expr, Var):
        return {expr.name}
    if isinstance(expr, Not):
        return collect_variables(expr.expr)
    if isinstance(expr, (And, Or, Imp, Iff)):
        return collect_variables(expr.left) | collect_variables(expr.right)
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


@lru_cache(maxsize=4096)
def _cached_var_list(vars_sorted: tuple[str, ...]):
    """Utility interna per conversione/validazione: _cached_var_list."""
    return "[" + ",".join(vars_sorted) + "]"


def prolog_var_list(expr_or_vars):
    """Utility interna per conversione/validazione: prolog_var_list."""
    if isinstance(expr_or_vars, (set, list, tuple)):
        vars_sorted = tuple(sorted(expr_or_vars))
    else:
        vars_sorted = tuple(sorted(collect_variables(expr_or_vars)))
    return _cached_var_list(vars_sorted)


def valuation_to_prolog(valuation: Sequence[tuple[str, bool] | str]):
    """Utility interna per conversione/validazione: valuation_to_prolog."""
    parts: list[str] = []
    for item in valuation:
        if isinstance(item, str):
            parts.append(item)
            continue
        name, value = item
        value_atom = "true" if value else "false"
        parts.append(f"{name}-{value_atom}")
    return "[" + ",".join(parts) + "]"


def prolog_term_list(terms: Sequence[str]):
    """Utility interna per conversione/validazione: prolog_term_list."""
    return "[" + ",".join(terms) + "]"


def formula_to_dict(expr):
    """Utility interna per conversione/validazione: formula_to_dict."""
    if isinstance(expr, Var):
        return {"type": "var", "name": expr.name}
    if isinstance(expr, Not):
        return {"type": "not", "expr": formula_to_dict(expr.expr)}
    if isinstance(expr, And):
        return {"type": "and", "left": formula_to_dict(expr.left), "right": formula_to_dict(expr.right)}
    if isinstance(expr, Or):
        return {"type": "or", "left": formula_to_dict(expr.left), "right": formula_to_dict(expr.right)}
    if isinstance(expr, Imp):
        return {"type": "imp", "left": formula_to_dict(expr.left), "right": formula_to_dict(expr.right)}
    if isinstance(expr, Iff):
        return {"type": "iff", "left": formula_to_dict(expr.left), "right": formula_to_dict(expr.right)}
    raise TypeError(f"Tipo formula non supportato: {type(expr)!r}")


def _req_int_ge(name: str, value: int, minimum: int):
    """Utility interna per conversione/validazione: _req_int_ge."""
    if not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} deve essere un intero >= {minimum}")


def _ensure_list_result(value, name: str):
    """Utility interna per conversione/validazione: _ensure_list_result."""
    if not isinstance(value, list):
        raise RuntimeError(f"Postcondizione fallita: {name} non e una lista")
    return value


# ============================================================
# Errori specifici
# ============================================================


class PrologBridgeError(Exception):
    pass


class PrologNotFoundError(PrologBridgeError):
    pass


class PrologExecutionError(PrologBridgeError):
    pass


class _PersistentPrologSession:
    def __init__(self, *, swipl_path: str, prolog_dir: Path, entry_file: Path, rpc_file: Path):
        """Configura una sessione SWI-Prolog persistente con lock thread-safe."""
        self.swipl_path = swipl_path
        self.prolog_dir = prolog_dir
        self.entry_file = entry_file
        self.rpc_file = rpc_file
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def _spawn(self):
        """Avvia il processo SWI-Prolog in modalita RPC."""
        cmd = [
            self.swipl_path,
            "-q",
            "-s",
            str(self.entry_file),
            "-s",
            str(self.rpc_file),
            "-g",
            "bridge_rpc_loop",
        ]
        self._process = subprocess.Popen(
            cmd,
            cwd=self.prolog_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def _ensure_process(self):
        """Ritorna un processo attivo, avviandolo se necessario."""
        if self._process is None or self._process.poll() is not None:
            self._spawn()
        assert self._process is not None
        return self._process

    def query(self, goal: str, timeout: int):
        """Invia una query RPC e restituisce l'output serializzato."""
        payload = json.dumps({"goal": goal, "timeout": timeout}, ensure_ascii=True)

        with self._lock:
            process = self._ensure_process()
            if process.stdin is None or process.stdout is None:
                raise PrologExecutionError("Sessione Prolog non disponibile")

            try:
                process.stdin.write(payload + "\n")
                process.stdin.flush()
            except OSError as exc:
                self.close()
                raise PrologExecutionError(f"Errore scrittura verso SWI-Prolog: {exc}") from exc

            ready, _, _ = select.select([process.stdout], [], [], max(1, timeout + 1))
            if not ready:
                self._close_unlocked()
                raise PrologExecutionError(f"Timeout durante l'esecuzione della query Prolog: {goal}")

            line = process.stdout.readline()
            if not line:
                stderr_out = ""
                if process.stderr is not None:
                    try:
                        stderr_out = process.stderr.read().strip()
                    except OSError:
                        stderr_out = ""
                self._close_unlocked()
                raise PrologExecutionError(f"SWI-Prolog ha terminato la sessione. STDERR: {stderr_out}")

            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PrologExecutionError(f"Risposta RPC Prolog non valida: {line!r}") from exc

            if not response.get("ok", False):
                error = response.get("error", "Errore Prolog sconosciuto")
                raise PrologExecutionError(f"Errore Prolog. Goal: {goal}\nDettagli: {error}")

            return str(response.get("out", "")).strip()

    def _close_unlocked(self):
        """Chiude il processo Prolog senza acquisire il lock esterno."""
        process = self._process
        self._process = None

        if process is None:
            return

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

    def close(self):
        """Chiude in modo sicuro la sessione persistente."""
        with self._lock:
            self._close_unlocked()


# ============================================================
# Bridge principale
# ============================================================


class PrologBridge:
    def __init__(
        self,
        prolog_dir: str | Path | None = None,
        entry_file: str = "templates.pl",
        swipl_path: str = "swipl",
        persistent: bool = True,
    ):
        """Wrapper bridge per la routine Prolog: __init__."""
        self.swipl_path = swipl_path
        self.persistent = persistent
        if prolog_dir is None:
            self.prolog_dir = Path(__file__).resolve().parent.parent / "prolog"
        else:
            self.prolog_dir = Path(prolog_dir).resolve()
        self.entry_file = self.prolog_dir / entry_file
        self.rpc_file = self.prolog_dir / "rpc_server.pl"
        self._session: _PersistentPrologSession | None = None

    def close(self):
        """Wrapper bridge per la routine Prolog: close."""
        if self._session is not None:
            self._session.close()
            self._session = None

    def _session_query(self, goal: str, timeout: int):
        """Wrapper bridge per la routine Prolog: _session_query."""
        if self._session is None:
            self._session = _PersistentPrologSession(
                swipl_path=self.swipl_path,
                prolog_dir=self.prolog_dir,
                entry_file=self.entry_file,
                rpc_file=self.rpc_file,
            )
        return self._session.query(goal, timeout)

    def ensure_available(self):
        """Wrapper bridge per la routine Prolog: ensure_available."""
        if shutil.which(self.swipl_path) is None:
            raise PrologNotFoundError(f"SWI-Prolog non trovato. Comando atteso: {self.swipl_path!r}")
        if not self.prolog_dir.exists():
            raise PrologBridgeError(f"Directory Prolog non trovata: {self.prolog_dir}")
        if not self.entry_file.exists():
            raise PrologBridgeError(f"File Prolog principale non trovato: {self.entry_file}")
        if self.persistent and not self.rpc_file.exists():
            raise PrologBridgeError(f"File Prolog RPC non trovato: {self.rpc_file}")

    def run_query(self, goal: str, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: run_query."""
        self.ensure_available()
        wrapped_goal = (
            "use_module(library(http/json)), "
            "set_prolog_flag(answer_write_options,[max_depth(0)]), "
            f"({goal})"
        )

        if self.persistent:
            return self._session_query(wrapped_goal, timeout)

        cmd = [
            self.swipl_path,
            "-q",
            "-s",
            str(self.entry_file),
            "-g",
            wrapped_goal,
            "-t",
            "halt",
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=self.prolog_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PrologExecutionError(f"Timeout durante l'esecuzione della query Prolog: {goal}") from exc
        except OSError as exc:
            raise PrologExecutionError(f"Impossibile eseguire SWI-Prolog: {exc}") from exc

        if result.returncode != 0:
            raise PrologExecutionError(
                "Errore Prolog.\n"
                f"Goal: {goal}\n"
                f"Return code: {result.returncode}\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}"
            )
        return result.stdout.strip()

    def run_json_query(self, goal: str, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: run_json_query."""
        out = self.run_query(goal, timeout=timeout)
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise PrologExecutionError(f"Output JSON non valido da Prolog: {out!r}") from exc

    def ask_bool(self, predicate_call: str, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: ask_bool."""
        out = self.run_query(f"(({predicate_call}) -> write(true) ; write(false))", timeout=timeout).strip().lower()
        if out == "true":
            return True
        if out == "false":
            return False
        raise PrologExecutionError(f"Output booleano non riconosciuto: {out!r} per query {predicate_call!r}")

    def _findall_terms(self, generator_goal: str, key: str = "items", timeout: int = 10):
        """Wrapper bridge per la routine Prolog: _findall_terms."""
        goal = (
            f"findall(OutStr, ({generator_goal}, term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{{key}:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return list(data[key])

    def _valuation_strings_expr(self, valuation_var: str, output_var: str = "ValuationStrs"):
        """Wrapper bridge per la routine Prolog: _valuation_strings_expr."""
        return (
            f"findall(ItemStr, (member(Item, {valuation_var}), term_string(Item, ItemStr)), {output_var})"
        )

    # ========================================================
    # logic.pl
    # ========================================================

    def assignment(self, vars_list: Iterable[str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: assignment."""
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"findall(ValuationStrs, (assignment({vars_str}, V), {self._valuation_strings_expr('V')}), Vs), "
            f"json_write_dict(current_output, _{{valuations:Vs}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        vals = data["valuations"]
        if not isinstance(vals, list):
            raise RuntimeError("Postcondizione fallita: valuations non e una lista")
        return list(vals)

    def eval(self, expr, valuation: Sequence[tuple[str, bool] | str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: eval."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        valuation_str = valuation_to_prolog(valuation)
        goal = f"eval({formula}, {valuation_str}, B), write(B)"
        out = self.run_query(goal, timeout=timeout).strip().lower()
        if out == "true":
            return True
        if out == "false":
            return False
        raise PrologExecutionError(f"Output eval non riconosciuto: {out!r}")

    def vars_in_formula(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: vars_in_formula."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"vars_in_formula({formula}, Vars), json_write_dict(current_output, _{{vars:Vars}})"
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["vars"]), "vars")

    def truth_table_auto(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: truth_table_auto."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = (
            f"truth_table_auto({formula}, Vars, Rows), "
            f"findall(_{{valuation:ValuationStrs, result:Result}}, "
            f"(member(row(V, Result), Rows), {self._valuation_strings_expr('V')}), JsonRows), "
            f"json_write_dict(current_output, _{{vars:Vars, rows:JsonRows}})"
        )
        out = self.run_json_query(goal, timeout=timeout)
        if not isinstance(out, dict) or "vars" not in out or "rows" not in out:
            raise RuntimeError("Postcondizione fallita: truth_table_auto output non valido")
        return out

    # ========================================================
    # equivalence.pl
    # ========================================================

    def equiv(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: equiv."""
        _req_int_ge("timeout", timeout, 1)
        left_str = to_prolog(left) if not isinstance(left, str) else left
        right_str = to_prolog(right) if not isinstance(right, str) else right
        if vars_list is None:
            vars_list = collect_variables(left) | collect_variables(right)
        return self.ask_bool(f"equiv({left_str}, {right_str}, {prolog_var_list(list(vars_list))})", timeout=timeout)

    def not_equiv(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: not_equiv."""
        _req_int_ge("timeout", timeout, 1)
        left_str = to_prolog(left) if not isinstance(left, str) else left
        right_str = to_prolog(right) if not isinstance(right, str) else right
        if vars_list is None:
            vars_list = collect_variables(left) | collect_variables(right)
        return self.ask_bool(f"not_equiv({left_str}, {right_str}, {prolog_var_list(list(vars_list))})", timeout=timeout)

    def counterexample_equiv(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: counterexample_equiv."""
        _req_int_ge("timeout", timeout, 1)
        left_str = to_prolog(left) if not isinstance(left, str) else left
        right_str = to_prolog(right) if not isinstance(right, str) else right
        if vars_list is None:
            vars_list = collect_variables(left) | collect_variables(right)
        goal = (
            f"findall(ValuationStrs, (counterexample_equiv({left_str}, {right_str}, {prolog_var_list(list(vars_list))}, V), "
            f"{self._valuation_strings_expr('V')}), Vs), json_write_dict(current_output, _{{valuations:Vs}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["valuations"]), "valuations")

    def filter_non_equivalent(
        self,
        expr,
        candidates: Sequence[str],
        vars_list: Iterable[str] | None = None,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: filter_non_equivalent."""
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        if vars_list is None:
            raise ValueError("vars_list e obbligatorio quando expr e una stringa Prolog")
        candidates_str = prolog_term_list(list(candidates))
        goal = (
            f"filter_non_equivalent({formula}, {candidates_str}, {prolog_var_list(list(vars_list))}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return list(data["formulas"])

    def filter_equivalent(
        self,
        expr,
        candidates: Sequence[str],
        vars_list: Iterable[str] | None = None,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: filter_equivalent."""
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        if vars_list is None:
            raise ValueError("vars_list e obbligatorio quando expr e una stringa Prolog")
        candidates_str = prolog_term_list(list(candidates))
        goal = (
            f"filter_equivalent({formula}, {candidates_str}, {prolog_var_list(list(vars_list))}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return list(data["formulas"])

    def all_models(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_models."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        goal = (
            f"all_models({formula}, {prolog_var_list(list(vars_list))}, Models), "
            f"findall(ValuationStrs, (member(V, Models), {self._valuation_strings_expr('V')}), JsonModels), "
            f"json_write_dict(current_output, _{{models:JsonModels}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["models"]), "models")

    def all_countermodels(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_countermodels."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        goal = (
            f"all_countermodels({formula}, {prolog_var_list(list(vars_list))}, Models), "
            f"findall(ValuationStrs, (member(V, Models), {self._valuation_strings_expr('V')}), JsonModels), "
            f"json_write_dict(current_output, _{{models:JsonModels}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["models"]), "models")

    def model(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: model."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        goal = (
            f"findall(ValuationStrs, (model({formula}, {prolog_var_list(list(vars_list))}, V), {self._valuation_strings_expr('V')}), Vs), "
            f"json_write_dict(current_output, _{{valuations:Vs}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["valuations"]), "valuations")

    def countermodel(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: countermodel."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        goal = (
            f"findall(ValuationStrs, (countermodel({formula}, {prolog_var_list(list(vars_list))}, V), {self._valuation_strings_expr('V')}), Vs), "
            f"json_write_dict(current_output, _{{valuations:Vs}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["valuations"]), "valuations")

    def tautology(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: tautology."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        return self.ask_bool(f"tautology({formula}, {prolog_var_list(list(vars_list))})", timeout=timeout)

    def contradiction(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: contradiction."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        return self.ask_bool(f"contradiction({formula}, {prolog_var_list(list(vars_list))})", timeout=timeout)

    def satisfiable(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: satisfiable."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        return self.ask_bool(f"satisfiable({formula}, {prolog_var_list(list(vars_list))})", timeout=timeout)

    def unsatisfiable(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: unsatisfiable."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        if vars_list is None and not isinstance(expr, str):
            vars_list = collect_variables(expr)
        return self.ask_bool(f"unsatisfiable({formula}, {prolog_var_list(list(vars_list))})", timeout=timeout)

    def satisfying_assignment(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: satisfying_assignment."""
        return self.model(expr, vars_list=vars_list, timeout=timeout)

    def falsifying_assignment(self, expr, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: falsifying_assignment."""
        return self.countermodel(expr, vars_list=vars_list, timeout=timeout)

    def implies_formula(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: implies_formula."""
        _req_int_ge("timeout", timeout, 1)
        left_str = to_prolog(left) if not isinstance(left, str) else left
        right_str = to_prolog(right) if not isinstance(right, str) else right
        if vars_list is None:
            vars_list = collect_variables(left) | collect_variables(right)
        return self.ask_bool(f"implies_formula({left_str}, {right_str}, {prolog_var_list(list(vars_list))})", timeout=timeout)

    def mutually_exclusive(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: mutually_exclusive."""
        _req_int_ge("timeout", timeout, 1)
        left_str = to_prolog(left) if not isinstance(left, str) else left
        right_str = to_prolog(right) if not isinstance(right, str) else right
        if vars_list is None:
            vars_list = collect_variables(left) | collect_variables(right)
        return self.ask_bool(f"mutually_exclusive({left_str}, {right_str}, {prolog_var_list(list(vars_list))})", timeout=timeout)

    def jointly_satisfiable(self, left, right, vars_list: Iterable[str] | None = None, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: jointly_satisfiable."""
        _req_int_ge("timeout", timeout, 1)
        left_str = to_prolog(left) if not isinstance(left, str) else left
        right_str = to_prolog(right) if not isinstance(right, str) else right
        if vars_list is None:
            vars_list = collect_variables(left) | collect_variables(right)
        return self.ask_bool(f"jointly_satisfiable({left_str}, {right_str}, {prolog_var_list(list(vars_list))})", timeout=timeout)

    def same_value_under(self, left, right, valuation: Sequence[tuple[str, bool] | str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: same_value_under."""
        _req_int_ge("timeout", timeout, 1)
        left_str = to_prolog(left) if not isinstance(left, str) else left
        right_str = to_prolog(right) if not isinstance(right, str) else right
        val_str = valuation_to_prolog(valuation)
        return self.ask_bool(f"same_value_under({left_str}, {right_str}, {val_str})", timeout=timeout)

    def different_value_under(self, left, right, valuation: Sequence[tuple[str, bool] | str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: different_value_under."""
        _req_int_ge("timeout", timeout, 1)
        left_str = to_prolog(left) if not isinstance(left, str) else left
        right_str = to_prolog(right) if not isinstance(right, str) else right
        val_str = valuation_to_prolog(valuation)
        return self.ask_bool(f"different_value_under({left_str}, {right_str}, {val_str})", timeout=timeout)

    # ========================================================
    # rewrite.pl
    # ========================================================

    def rewrite_formula(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: rewrite_formula."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"rewrite_formula({formula}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def expand_implications(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: expand_implications."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"expand_implications({formula}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def to_nnf(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: to_nnf."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"to_nnf({formula}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def to_cnf(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: to_cnf."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"to_cnf({formula}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def to_dnf(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: to_dnf."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"to_dnf({formula}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def rewrite_path(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: rewrite_path."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = (
            f"findall(PathStrs, ("
            f"rewrite_path({formula}, Path), "
            f"findall(StepStr, (member(Step, Path), term_string(Step, StepStr)), PathStrs)"
            f"), Paths), "
            f"json_write_dict(current_output, _{{paths:Paths}})"
        )
        data = self.run_json_query(goal, timeout=timeout)

        flattened: list[str] = []
        seen: set[str] = set()
        for path in data.get("paths", []):
            for step in path or []:
                if step in seen:
                    continue
                seen.add(step)
                flattened.append(step)
        return _ensure_list_result(flattened, "paths")

    # ========================================================
    # templates.pl
    # ========================================================
    
    def formula_of_depth(self, depth: int, vars_list: Iterable[str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: formula_of_depth."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = f"formula_of_depth({depth}, {vars_str}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def all_depth(self, depth: int, vars_list: Iterable[str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_depth."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"all_formulas_of_depth({depth}, {vars_str}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["formulas"]), "formulas")

    def all_depth_allvars(self, depth: int, vars_list: Iterable[str], timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_depth_allvars."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"all_formulas_of_depth_using_all_vars({depth}, {vars_str}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["formulas"]), "formulas")

    def some_depth(self, depth: int, vars_list: Iterable[str], limit: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: some_depth."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"some_formulas_of_depth({depth}, {vars_str}, {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        out = _ensure_list_result(list(data["formulas"]), "formulas")
        if len(out) > limit:
            raise RuntimeError("Postcondizione fallita: troppi risultati")
        return out

    def some_depth_allvars(
        self,
        depth: int,
        vars_list: Iterable[str],
        limit: int,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: some_depth_allvars."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"some_formulas_of_depth_using_all_vars({depth}, {vars_str}, {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        out = _ensure_list_result(list(data["formulas"]), "formulas")
        if len(out) > limit:
            raise RuntimeError("Postcondizione fallita: troppi risultati")
        return out

    def some_depth_head(
        self,
        depth: int,
        vars_list: Iterable[str],
        head: str,
        limit: int,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: some_depth_head."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"some_formulas_of_depth_using_all_vars_with_head({depth}, {vars_str}, '{head}', {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        out = _ensure_list_result(list(data["formulas"]), "formulas")
        if len(out) > limit:
            raise RuntimeError("Postcondizione fallita: troppi risultati")
        return out

    def some_depth_hbal(
        self,
        depth: int,
        vars_list: Iterable[str],
        head: str,
        limit: int,
        timeout: int = 10,
    ) -> list[str]:
        """Wrapper bridge per la routine Prolog: some_depth_hbal."""
        _req_int_ge("depth", depth, 0)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        vars_str = prolog_var_list(list(vars_list))
        goal = (
            f"some_formulas_of_depth_using_all_vars_with_head_balanced({depth}, {vars_str}, '{head}', {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        out = _ensure_list_result(list(data["formulas"]), "formulas")
        if len(out) > limit:
            raise RuntimeError("Postcondizione fallita: troppi risultati")
        return out
    
    # ========================================================
    # distractions.pl
    # ========================================================

    def distract_formula(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: distract_formula."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"distract_formula({formula}, {max_steps}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def distract_exactly(self, expr, steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: distract_exactly."""
        _req_int_ge("steps", steps, 0)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"distract_exactly({formula}, {steps}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def distract_trace(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: distract_trace."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = (
            f"findall(_{{formula:OutStr, trace:Trace}}, "
            f"(distract_formula_with_trace({formula}, {max_steps}, Out, Trace), "
            f"term_string(Out, OutStr)), "
            f"Items), "
            f"json_write_dict(current_output, _{{items:Items}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        items = list(data["items"])
        if not isinstance(items, list):
            raise RuntimeError("Postcondizione fallita: items non e una lista")
        return items

    def all_distractions(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_distractions."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"all_distractions({formula}, {max_steps}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def distract_n(self, expr, max_steps: int, n: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: distract_n."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("n", n, 0)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = (
            f"distract_n({formula}, {max_steps}, {n}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        out = _ensure_list_result(list(data["formulas"]), "formulas")
        if len(out) > n:
            raise RuntimeError("Postcondizione fallita: troppi risultati")
        return out

    def one_step_distraction(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: one_step_distraction."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"one_step_distraction({formula}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def apply_operator_cycles(self, expr, cycles: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: apply_operator_cycles."""
        _req_int_ge("cycles", cycles, 0)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"apply_operator_cycles({formula}, {cycles}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def swap_and_or_children(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: swap_and_or_children."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"swap_and_or_children({formula}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def apply_answer_transform_cycles(self, expr, cycles: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: apply_answer_transform_cycles."""
        _req_int_ge("cycles", cycles, 0)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"apply_answer_transform_cycles({formula}, {cycles}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def one_step_neq(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: one_step_neq."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"one_step_non_equivalent_distraction({formula}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def all_step_neq(self, expr, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_step_neq."""
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = (
            f"all_one_step_non_equivalent_distractions({formula}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["formulas"]), "formulas")

    def some_step_neq(self, expr, limit: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: some_step_neq."""
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = (
            f"some_one_step_non_equivalent_distractions({formula}, {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        out = _ensure_list_result(list(data["formulas"]), "formulas")
        if len(out) > limit:
            raise RuntimeError("Postcondizione fallita: troppi risultati")
        return out

    def non_equivalent_distraction(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: non_equivalent_distraction."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = f"non_equivalent_distraction({formula}, {max_steps}, Out)"
        return _ensure_list_result(self._findall_terms(goal, key="formulas", timeout=timeout), "formulas")

    def all_neq(self, expr, max_steps: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: all_neq."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = (
            f"all_non_equivalent_distractions({formula}, {max_steps}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        return _ensure_list_result(list(data["formulas"]), "formulas")

    def some_neq(self, expr, max_steps: int, limit: int, timeout: int = 10):
        """Wrapper bridge per la routine Prolog: some_neq."""
        _req_int_ge("max_steps", max_steps, 1)
        _req_int_ge("limit", limit, 1)
        _req_int_ge("timeout", timeout, 1)
        formula = to_prolog(expr) if not isinstance(expr, str) else expr
        goal = (
            f"some_non_equivalent_distractions({formula}, {max_steps}, {limit}, L), "
            f"findall(OutStr, (member(Out, L), term_string(Out, OutStr)), Raw), "
            f"json_write_dict(current_output, _{{formulas:Raw}})"
        )
        data = self.run_json_query(goal, timeout=timeout)
        out = _ensure_list_result(list(data["formulas"]), "formulas")
        if len(out) > limit:
            raise RuntimeError("Postcondizione fallita: troppi risultati")
        return out


_default_bridge: PrologBridge | None = None


def get_default_bridge():
    """Utility interna per conversione/validazione: get_default_bridge."""
    global _default_bridge
    if _default_bridge is None:
        _default_bridge = PrologBridge(entry_file="templates.pl", persistent=True)
    return _default_bridge


def _close_default_bridge():
    """Utility interna per conversione/validazione: _close_default_bridge."""
    global _default_bridge
    if _default_bridge is not None:
        _default_bridge.close()


atexit.register(_close_default_bridge)
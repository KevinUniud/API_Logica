# TestLogica API

Base URL locale: `http://127.0.0.1:5000`

Documentazione runtime:
- OpenAPI JSON: `GET /openapi.json`
- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`

## Nota tecnica: chiamata Python -> Prolog

Il backend non genera file temporanei a ogni richiesta.
La chiamata avviene cosi:

- Python costruisce una `goal` Prolog (stringa).
- Il bridge invia la richiesta al processo SWI-Prolog via `stdin` (payload JSON).
- Prolog esegue `goal` e risponde via `stdout` (JSON/stringa).
- Python legge e converte la risposta nel tipo atteso.

I file `.pl` del progetto vengono caricati dal processo Prolog, ma non viene creato un nuovo file di query per singola chiamata.

## Tabella endpoint

| Area | Metodo | Path | Body JSON di esempio |
| --- | --- | --- | --- |
| Meta | GET | `/` | Nessuno |
| Meta | GET | `/health` | Nessuno |
| Meta | GET | `/openapi.json` | Nessuno |
| Meta | GET | `/docs` | Nessuno |
| Meta | GET | `/redoc` | Nessuno |
| Prolog Bridge Logic | POST | `/api/prolog-bridge/logic/assignment` | `{"vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Logic | POST | `/api/prolog-bridge/logic/eval` | `{"expr":"and(p,q)","valuation":[{"name":"p","value":true},{"name":"q","value":false}],"timeout":10}` |
| Prolog Bridge Logic | POST | `/api/prolog-bridge/logic/vars-in-formula` | `{"expr":"and(p,q)","timeout":10}` |
| Prolog Bridge Logic | POST | `/api/prolog-bridge/logic/truth-table-auto` | `{"expr":"and(p,q)","timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/equiv` | `{"left":"imp(p,q)","right":"or(not(p),q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/not-equiv` | `{"left":"imp(p,q)","right":"or(not(p),q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/counterexample-equiv` | `{"left":"imp(p,q)","right":"or(not(p),q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/all-models` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/all-countermodels` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/model` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/countermodel` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/tautology` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/contradiction` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/satisfiable` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/unsatisfiable` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/satisfying-assignment` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/falsifying-assignment` | `{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/implies-formula` | `{"left":"p","right":"q","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/mutually-exclusive` | `{"left":"p","right":"not(p)","vars_list":["p"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/jointly-satisfiable` | `{"left":"p","right":"q","vars_list":["p","q"],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/same-value-under` | `{"left":"and(p,q)","right":"or(p,q)","valuation":[{"name":"p","value":true},{"name":"q","value":false}],"timeout":10}` |
| Prolog Bridge Equivalence | POST | `/api/prolog-bridge/equivalence/different-value-under` | `{"left":"and(p,q)","right":"or(p,q)","valuation":[{"name":"p","value":true},{"name":"q","value":false}],"timeout":10}` |
| Prolog Bridge Rewrite | POST | `/api/prolog-bridge/rewrite/rewrite-formula` | `{"expr":"imp(p,q)","timeout":10}` |
| Prolog Bridge Rewrite | POST | `/api/prolog-bridge/rewrite/expand-implications` | `{"expr":"imp(p,q)","timeout":10}` |
| Prolog Bridge Rewrite | POST | `/api/prolog-bridge/rewrite/to-nnf` | `{"expr":"imp(p,q)","timeout":10}` |
| Prolog Bridge Rewrite | POST | `/api/prolog-bridge/rewrite/to-cnf` | `{"expr":"imp(p,q)","timeout":10}` |
| Prolog Bridge Rewrite | POST | `/api/prolog-bridge/rewrite/to-dnf` | `{"expr":"imp(p,q)","timeout":10}` |
| Prolog Bridge Rewrite | POST | `/api/prolog-bridge/rewrite/rewrite-path` | `{"expr":"imp(p,q)","timeout":10}` |
| Prolog Bridge Templates | POST | `/api/prolog-bridge/templates/formula-of-depth` | `{"depth":2,"variables":["p","q"],"timeout":10}` |
| Prolog Bridge Templates | POST | `/api/prolog-bridge/templates/all-formulas-of-depth` | `{"depth":2,"variables":["p","q"],"timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/distract-formula` | `{"expr":"and(p,q)","max_steps":2,"timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/distract-formula-with-trace` | `{"expr":"and(p,q)","max_steps":2,"timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/all-distractions` | `{"expr":"and(p,q)","max_steps":2,"timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/non-equivalent-distraction` | `{"expr":"and(p,q)","max_steps":2,"timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/all-non-equivalent-distractions` | `{"expr":"and(p,q)","max_steps":2,"timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/distract-exactly` | `{"expr":"and(p,q)","steps":2,"timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/distract-n` | `{"expr":"and(p,q)","max_steps":2,"n":3,"timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/one-step-distraction` | `{"expr":"and(p,q)","timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/one-step-non-equivalent-distraction` | `{"expr":"and(p,q)","timeout":10}` |
| Prolog Bridge Distractions | POST | `/api/prolog-bridge/distractions/all-one-step-non-equivalent-distractions` | `{"expr":"and(p,q)","timeout":10}` |
| Generator | POST | `/api/generator/formula-depth` | `{"expr":"and(p,q)","timeout":10}` |
| Generator | POST | `/api/generator/formula-size` | `{"expr":"and(p,q)","timeout":10}` |
| Generator | POST | `/api/generator/formula-metadata` | `{"expr":"and(p,q)","timeout":10}` |
| Generator | POST | `/api/generator/formula-payload` | `{"expr":"and(p,q)","extra":{"source":"manual"},"timeout":10}` |
| Generator | POST | `/api/generator/generate-formula` | `{"variables":["p","q"],"use_all":false,"seed":42,"timeout":10}` |
| Generator | POST | `/api/generator/generate-formula-json` | `{"variables":["p","q"],"use_all":false,"seed":42,"timeout":10}` |
| Generator | POST | `/api/generator/build-exercise` | `{"expr":"or(p,imp(q,p))","wrong_answers_count":3,"max_steps":2,"seed":42,"timeout":10}` |
| Generator | POST | `/api/generator/build-exercise-from-depth` | `{"variables":["p","q"],"use_all":false,"seed":42,"wrong_answers_count":3,"max_steps":2,"timeout":10}` |
| Generator | POST | `/api/generator/build-truth-value-options-question` | `{"predicate_count":2,"true_options_count":2,"false_options_count":2,"seed":42,"timeout":10}` |
| Generator | POST | `/api/generator/build-exercise-json-string` | `{"expr":"or(p,imp(q,p))","wrong_answers_count":3,"max_steps":2,"seed":42,"timeout":10}` |
| Generator | POST | `/api/generator/build-exercise-from-depth-json-string` | `{"variables":["p","q"],"use_all":false,"seed":42,"wrong_answers_count":3,"max_steps":2,"timeout":10}` |
| Generator | POST | `/api/generator/build-truth-value-options-question-json-string` | `{"predicate_count":2,"true_options_count":2,"false_options_count":2,"seed":42,"timeout":10}` |

## Lista curl

### Meta

```bash
curl http://127.0.0.1:5000/
curl http://127.0.0.1:5000/health
curl http://127.0.0.1:5000/openapi.json
curl http://127.0.0.1:5000/docs
curl http://127.0.0.1:5000/redoc
```

### Prolog Bridge Logic

```bash
curl -X POST http://127.0.0.1:5000/api/prolog-bridge/logic/assignment \
  -H 'Content-Type: application/json' \
  -d '{"vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/logic/eval \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","valuation":[{"name":"p","value":true},{"name":"q","value":false}],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/logic/vars-in-formula \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/logic/truth-table-auto \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","timeout":10}'
```

### Prolog Bridge Equivalence

```bash
curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/equiv \
  -H 'Content-Type: application/json' \
  -d '{"left":"imp(p,q)","right":"or(not(p),q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/not-equiv \
  -H 'Content-Type: application/json' \
  -d '{"left":"imp(p,q)","right":"or(not(p),q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/counterexample-equiv \
  -H 'Content-Type: application/json' \
  -d '{"left":"imp(p,q)","right":"or(not(p),q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/all-models \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/all-countermodels \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/model \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/countermodel \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/tautology \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/contradiction \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/satisfiable \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/unsatisfiable \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/satisfying-assignment \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/falsifying-assignment \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/implies-formula \
  -H 'Content-Type: application/json' \
  -d '{"left":"p","right":"q","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/mutually-exclusive \
  -H 'Content-Type: application/json' \
  -d '{"left":"p","right":"not(p)","vars_list":["p"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/jointly-satisfiable \
  -H 'Content-Type: application/json' \
  -d '{"left":"p","right":"q","vars_list":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/same-value-under \
  -H 'Content-Type: application/json' \
  -d '{"left":"and(p,q)","right":"or(p,q)","valuation":[{"name":"p","value":true},{"name":"q","value":false}],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/different-value-under \
  -H 'Content-Type: application/json' \
  -d '{"left":"and(p,q)","right":"or(p,q)","valuation":[{"name":"p","value":true},{"name":"q","value":false}],"timeout":10}'
```

### Prolog Bridge Rewrite

```bash
curl -X POST http://127.0.0.1:5000/api/prolog-bridge/rewrite/rewrite-formula \
  -H 'Content-Type: application/json' \
  -d '{"expr":"imp(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/rewrite/expand-implications \
  -H 'Content-Type: application/json' \
  -d '{"expr":"imp(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/rewrite/to-nnf \
  -H 'Content-Type: application/json' \
  -d '{"expr":"imp(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/rewrite/to-cnf \
  -H 'Content-Type: application/json' \
  -d '{"expr":"imp(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/rewrite/to-dnf \
  -H 'Content-Type: application/json' \
  -d '{"expr":"imp(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/rewrite/rewrite-path \
  -H 'Content-Type: application/json' \
  -d '{"expr":"imp(p,q)","timeout":10}'
```

### Prolog Bridge Templates

```bash
curl -X POST http://127.0.0.1:5000/api/prolog-bridge/templates/formula-of-depth \
  -H 'Content-Type: application/json' \
  -d '{"depth":2,"variables":["p","q"],"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/templates/all-formulas-of-depth \
  -H 'Content-Type: application/json' \
  -d '{"depth":2,"variables":["p","q"],"timeout":10}'
```

### Prolog Bridge Distractions

```bash
curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/distract-formula \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","max_steps":2,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/distract-formula-with-trace \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","max_steps":2,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/all-distractions \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","max_steps":2,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/non-equivalent-distraction \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","max_steps":2,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/all-non-equivalent-distractions \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","max_steps":2,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/distract-exactly \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","steps":2,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/distract-n \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","max_steps":2,"n":3,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/one-step-distraction \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/one-step-non-equivalent-distraction \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/prolog-bridge/distractions/all-one-step-non-equivalent-distractions \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","timeout":10}'
```

### Generator

```bash
curl -X POST http://127.0.0.1:5000/api/generator/formula-depth \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/formula-size \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/formula-metadata \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/formula-payload \
  -H 'Content-Type: application/json' \
  -d '{"expr":"and(p,q)","extra":{"source":"manual"},"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/generate-formula \
  -H 'Content-Type: application/json' \
  -d '{"variables":["p","q"],"use_all":false,"seed":42,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/generate-formula-json \
  -H 'Content-Type: application/json' \
  -d '{"variables":["p","q"],"use_all":false,"seed":42,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/build-exercise \
  -H 'Content-Type: application/json' \
  -d '{"expr":"or(p,imp(q,p))","wrong_answers_count":3,"max_steps":2,"seed":42,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/build-exercise-from-depth \
  -H 'Content-Type: application/json' \
  -d '{"variables":["p","q"],"use_all":false,"seed":42,"wrong_answers_count":3,"max_steps":2,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/build-truth-value-options-question \
  -H 'Content-Type: application/json' \
  -d '{"predicate_count":2,"true_options_count":2,"false_options_count":2,"seed":42,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/build-exercise-json-string \
  -H 'Content-Type: application/json' \
  -d '{"expr":"or(p,imp(q,p))","wrong_answers_count":3,"max_steps":2,"seed":42,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/build-exercise-from-depth-json-string \
  -H 'Content-Type: application/json' \
  -d '{"variables":["p","q"],"use_all":false,"seed":42,"wrong_answers_count":3,"max_steps":2,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/build-truth-value-options-question-json-string \
  -H 'Content-Type: application/json' \
  -d '{"predicate_count":2,"true_options_count":2,"false_options_count":2,"seed":42,"timeout":10}'
```
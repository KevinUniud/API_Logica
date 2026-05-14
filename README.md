# TestLogica

TestLogica e un progetto per la generazione e manipolazione di formule di logica proposizionale. 

Il repository combina:
- predicati Prolog per valutazione, equivalenza, rewrite, template e distractor
- moduli Python per parsing, serializzazione e costruzione di esercizi
- un servizio FastAPI che espone le funzionalita via HTTP

## Struttura del progetto

```text
testLogica/
|- prolog/      # predicati SWI-Prolog
|- python/      # bridge Prolog e logica applicativa Python
|- server/      # API FastAPI e test HTTP
|- Dockerfile
|- docker-compose.yml
|- Funzioni.md  # catalogo delle funzioni/predicati
|- doc.md       # tabella endpoint e curl pronti
```

## Requisiti

- Python 3.11 o compatibile
- SWI-Prolog disponibile come `swipl`
- pacchetti Python usati dal server: `fastapi`, `uvicorn`, `pydantic`

## Avvio rapido

Dalla radice del progetto:

```bash
source .venv/bin/activate
cd server
python server.py
```

Il servizio parte in locale su:

```text
http://127.0.0.1:5000
```

## Esecuzione con Docker

Dalla radice del progetto:

```bash
docker build -t testlogica-api .
docker run --rm -p 5000:5000 testlogica-api
```

Il container espone il servizio su:

```text
http://127.0.0.1:5000
```

Per esecuzione in background su server:

```bash
docker run -d --name testlogica-api -p 5000:5000 --restart unless-stopped testlogica-api
```

## Esecuzione con Docker Compose

Dalla radice del progetto:

```bash
docker compose up -d --build
```

Verifica stato:

```bash
docker compose ps
docker compose logs -f testlogica-api
```

Stop del servizio:

```bash
docker compose down
```

Punti di accesso principali:

- Swagger UI: `http://127.0.0.1:5000/docs`
- ReDoc: `http://127.0.0.1:5000/redoc`
- OpenAPI JSON: `http://127.0.0.1:5000/openapi.json`

## Esecuzione test API

Dalla cartella `server`:

```bash
source ../.venv/bin/activate
python -m unittest test_api.py
```

I test coprono la generazione dello schema OpenAPI e alcune chiamate rappresentative agli endpoint.

## Aree funzionali

### Prolog

La cartella `prolog/` contiene i predicati di base per:

- valutazione di formule e tabelle di verità
- verifica di equivalenza e ricerca di modelli/contromodelli
- rewrite verso NNF, CNF, DNF e percorsi di trasformazione
- generazione di formule per profondità
- generazione di distractor equivalenti o non equivalenti

### Python

La cartella `python/` include:

- `prolog_bridge.py`: ponte tra Python e SWI-Prolog
- `ast_logic.py`: rappresentazione AST delle formule
- `generator.py`: costruzione di formule, metadati, esercizi e domande basate su valutazioni booleane dei predicati

## Flusso Python-Prolog

Nel progetto la comunicazione tra Python e Prolog avviene tramite processo SWI-Prolog e stream standard:

- Python prepara una query (`goal`) in forma testuale Prolog.
- Il bridge la invia al processo Prolog via `stdin`, in formato JSON (RPC leggero).
- Prolog esegue la query e scrive la risposta su `stdout`.
- Python legge la risposta e la converte nel risultato atteso (booleano, lista, JSON, ecc.).

### API HTTP

La cartella `server/` espone endpoint FastAPI organizzati in gruppi:

- `prolog-bridge/logic`
- `prolog-bridge/equivalence`
- `prolog-bridge/rewrite`
- `prolog-bridge/templates`
- `prolog-bridge/distractions`
- `generator`

Per l'elenco completo degli endpoint e dei payload di esempio, vedi [doc.md](doc.md).

## Documentazione disponibile

- [doc.md](doc.md): tabella completa degli endpoint e lista di chiamate `curl`
- [Funzioni.md](Funzioni.md): descrizione dettagliata di predicati e funzioni del progetto

## Note operative

- Gli endpoint `POST` accettano normalmente body JSON con `timeout` opzionale.
- Il file di ingresso Prolog usato dal bridge è `templates.pl`.
- Le chiamate a `build-exercise` e `build-exercise-from-depth` garantiscono che la formula corretta riscritta sia diversa da quella iniziale.

## API Quick Reference — Esempio rapido esteso

Qui sotto trovi un riassunto compatto di tutti gli endpoint principali esposti dal servizio
e dei campi che puoi inviare nel body JSON quando fai `POST`.

Nota: tutti i body ereditano un campo `timeout` (int, secondi) opzionale.

- Gruppo: Prolog Bridge — Logic
  - POST /api/prolog-bridge/logic/assignment
    - payload: `{ "vars_list": ["p","q","r"], "timeout": 10 }`
  - POST /api/prolog-bridge/logic/eval
    - payload: `{ "expr": "and(p,q)", "valuation": [{"name":"p","value":true}], "timeout": 10 }`
  - POST /api/prolog-bridge/logic/vars-in-formula
    - payload: `{ "expr": "imp(p,q)" }`

- Gruppo: Prolog Bridge — Equivalence (esempi rappresentativi)
  - POST /api/prolog-bridge/equivalence/equiv
    - payload: `{ "left": "and(p,q)", "right": "or(p,q)", "vars_list": ["p","q"] }`
  - POST /api/prolog-bridge/equivalence/not-equiv
  - POST /api/prolog-bridge/equivalence/counterexample-equiv
  - POST /api/prolog-bridge/equivalence/implies-formula
    - payload (binary): `{ "left": "p", "right": "q", "vars_list": ["p","q"] }`

- Gruppo: Prolog Bridge — Rewrite
  - POST /api/prolog-bridge/rewrite/rewrite-formula
    - payload: `{ "expr": "imp(p,or(q,r))" }` → restituisce formule equivalenti
  - POST /api/prolog-bridge/rewrite/to-nnf | to-cnf | to-dnf

- Gruppo: Prolog Bridge — Templates
  - POST /api/prolog-bridge/templates/formula-of-depth
    - payload: `{ "depth": 2, "variables": ["p","q","r"], "use_all": false }`

- Gruppo: Prolog Bridge — Distractions
  - POST /api/prolog-bridge/distractions/one-step-distraction
    - payload: `{ "expr": "and(p,q)", "timeout": 5 }`
  - POST /api/prolog-bridge/distractions/distract-n
    - payload: `{ "expr": "and(p,q)", "max_steps": 2, "n": 3 }`

- Gruppo: Generator (question builders)
  - POST /api/generator/generate-formula
    - payload: `{ "variables": ["p","q","r"], "use_all": false, "seed": 11, "timeout": 10 }`
  - POST /api/generator/generate-formula-json
    - payload: come sopra; restituisce payload JSON con metadati
  - POST /api/generator/generate-formula-by-variable-count
    - payload: `{ "variable_count": 3, "use_all": false, "seed": 5 }`

  - POST /api/generator/build-exercise
    - payload: `{ "expr": "or(p,imp(q,p))", "wrong_answers_count": 3, "seed": 42, "allow_spoken_mode": false }`
  - POST /api/generator/build-exercise-from-depth
    - payload: `{ "use_all": false, "seed": 42, "wrong_answers_count": 3, "allow_spoken_mode": false }`
  - POST /api/generator/build-truth-value-options-question
    - payload: `{ "predicate_count": 4, "true_options_count": 2, "false_options_count": 2, "seed": 42 }`
  - POST /api/generator/build-logical-consequence-question
    - payload: `{ "variable_count": 4, "correct_options_count": 2, "wrong_options_count": 2, "allow_spoken_mode": false, "seed": 42 }`
  - POST /api/generator/build-translation-question
    - payload example (mode=auto):
      ```json
      {
        "mode": "auto",
        "quantifier_ratio": 0.5,
        "wrong_options_count": 3,
        "names_pool": ["Luca","Marco"],
        "people_count": 2,
        "actions_pool": ["corre","salta"],
        "allow_spoken_mode": false,
        "seed": 7,
        "timeout_seconds": 10
      }
      ```

  - POST /api/generator/multiple-questions
    - payload: `{ "questions": [ { "operation": "build_tvq", "payload": { ... } }, ... ], "seed": 42 }`
    - il campo `operation` deve corrispondere a una delle funzioni pubbliche (es. `build_ex_depth`, `build_tvq`, `build_logical_consequence_question`, `build_translation_question`)

Esempi curl rapidi:

```bash
curl -sS -X POST http://127.0.0.1:5000/api/generator/build-exercise \
  -H 'Content-Type: application/json' \
  -d '{"expr":"or(p,imp(q,p))","wrong_answers_count":3,"seed":42}'

curl -sS -X POST http://127.0.0.1:5000/api/prolog-bridge/equivalence/equiv \
  -H 'Content-Type: application/json' \
  -d '{"left":"and(p,q)","right":"or(p,q)","vars_list":["p","q"]}'

curl -sS -X POST http://127.0.0.1:5000/api/generator/multiple-questions \
  -H 'Content-Type: application/json' \
  -d '{"seed":42, "questions":[{"operation":"build_tvq","payload":{"predicate_count":4,"true_options_count":1,"false_options_count":1}}]}'
```

Per la lista completa di esempi con `curl` e dettagli OpenAPI usa `http://127.0.0.1:5000/docs` o guarda `doc.md`.
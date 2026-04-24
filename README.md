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

## Esempio rapido

```bash
curl -X POST http://127.0.0.1:5000/api/generator/build-exercise \
  -H 'Content-Type: application/json' \
  -d '{"expr":"or(p,imp(q,p))","wrong_answers_count":3,"seed":42,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/build-exercise-from-depth \
  -H 'Content-Type: application/json' \
  -d '{"use_all":false,"seed":42,"wrong_answers_count":3,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/build-truth-value-options-question \
  -H 'Content-Type: application/json' \
  -d '{"predicate_count":4,"true_options_count":2,"false_options_count":2,"seed":42,"timeout":10}'

curl -X POST http://127.0.0.1:5000/api/generator/build-logical-consequence-question \
  -H 'Content-Type: application/json' \
  -d '{"variable_count":4,"correct_options_count":2,"wrong_options_count":2,"seed":42,"timeout":10}'
```

Risposta attesa: oggetti JSON con strutture standardizzate, ciascuno con il proprio payload `result` in base all'endpoint chiamato.
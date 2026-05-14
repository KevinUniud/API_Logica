# Riepilogo delle Modifiche - Limite di 2 Operatori Binari

## Obiettivo
Ridurre il numero di operatori logici (and, or, imp, iff) a massimo 2 nelle formule generate, mantenendo la possibilità di aggiungere operatori `not` senza conteggio.

## Modifiche Implementate

### 1. Aggiunta Costante e Nuove Funzioni (generator.py)

**Costante:**
- `MAX_BINARY_OPERATORS = 2` (linea ~20)

**Nuove Funzioni:**
- `formula_binary_operator_count(expr) -> int` 
  - Conta solo gli operatori binari (and, or, imp, iff)
  - Esclude `not` dal conteggio
  
- `_has_valid_binary_operator_count(expr, max_operators=MAX_BINARY_OPERATORS) -> bool`
  - Verifica che una formula non superi il limite di operatori binari

### 2. Filtri Applicati

Il filtro è stato applicato in tutti i punti critici della generazione:

#### a) `_get_formulas()` (linea ~560)
```python
filtered_formulas = [
    formula
    for formula in formulas
    if _uses_vars(formula, variables) and _has_valid_binary_operator_count(_as_ast(formula))
]
```
- Filtra le formule recuperate da Prolog
- Scarta formule con più di 2 operatori binari

#### b) `_pick_modified()` (linea ~1240)
```python
if not _has_valid_binary_operator_count(_as_ast(candidate)):
    continue
```
- Filtra i candidati per le risposte equivalenti

#### c) `_pick_wrongs()` (linea ~1375)
```python
if not _has_valid_binary_operator_count(_as_ast(candidate)):
    continue
```
- Filtra i candidati per i distrattori (due volte: unseen e expanded)

#### d) `_collect_candidate_formulas()` (linea ~1510)
```python
def register_candidate(formula: str) -> None:
    ...
    if not _has_valid_binary_operator_count(_as_ast(formula)):
        return
```
- Filtra i candidati durante la raccolta

## Comportamento del Filtro

### Formule Valide (≤ 2 operatori binari)
- `p` (0 operatori)
- `and(p, q)` (1 operatore)
- `or(p, and(q, r))` (2 operatori)
- `not(and(p, or(q, r)))` (2 operatori binari + NOT, valido)

### Formule Non Valide (> 2 operatori binari)
- `and(or(imp(p, q), r), s)` (3 operatori binari, scartata)
- `or(and(iff(p, q), r), s)` (3 operatori binari, scartata)

## Test Eseguiti

### Test Unitari: `test_binary_operator_limit.py`
- ✓ Conteggio corretto degli operatori binari
- ✓ Esclusione del NOT dal conteggio
- ✓ Validazione dei limiti

### Test di Integrazione: `test_integration_operator_limit.py`
- ✓ `generate_formula()` rispetta il limite
- ✓ `generate_formula_json()` rispetta il limite
- ✓ `generate_formula_by_variable_count()` rispetta il limite
- ✓ Tutte le formule generate hanno ≤ 2 operatori binari

## Impatto

### Funzioni Pubbliche Interessate
1. `generate_formula()` - Genera formule base
2. `generate_formula_json()` - Genera formule in formato JSON
3. `generate_formula_by_variable_count()` - Genera formule per numero di variabili
4. `build_logical_consequence_question()` - Genera quiz di conseguenza logica
5. `build_exercise()` - Genera esercizi completi
6. `_pick_modified()` - Seleziona formule equivalenti
7. `_pick_wrongs()` - Seleziona distrattori

### Effetto sulla Generazione
- Le formule generate saranno significativamente più semplici
- Massimo 2 livelli di annidamento di operatori binari
- Possibilità di aggiungere NOT senza limiti (per negazioni)
- Riduzione della complessità per chi risolve i quiz

## Verifica della Validità

Il file è stato compilato senza errori di sintassi:
```bash
python -m py_compile python/generator.py
✓ Sintassi corretta
```

Tutti i test hanno avuto esito positivo:
- 6/6 test unitari passati
- 3/3 suite di test di integrazione passate

# Riferimento Funzioni Prolog e Python

Questo documento raccoglie i predicati pubblici presenti in:
- `prolog/logic.pl`
- `prolog/equivalence.pl`
- `prolog/rewrite.pl`
- `prolog/templates.pl`
- `prolog/distractions.pl`

e le principali funzioni pubbliche di:
- `python/generator.py`

Convenzione formule proposizionali:
- `not(F)`
- `and(F1,F2)`
- `or(F1,F2)`
- `imp(F1,F2)`
- `iff(F1,F2)`

Convenzione valutazioni:
- Lista di coppie `Var-Bool`, ad esempio `[p-true, q-false]`.

## logic.pl

### bool(+B)
Valori booleani supportati.

```prolog
?- bool(X).
X = true ;
X = false.
```

### neg(+In, -Out)
Negazione booleana.

```prolog
?- neg(true, X).
X = false.
```

### bool_and(+A, +B, -Out)
Congiunzione booleana.

```prolog
?- bool_and(true, false, X).
X = false.
```

### bool_or(+A, +B, -Out)
Disgiunzione booleana.

```prolog
?- bool_or(false, true, X).
X = true.
```

### bool_imp(+A, +B, -Out)
Implicazione booleana.

```prolog
?- bool_imp(true, false, X).
X = false.
```

### bool_iff(+A, +B, -Out)
Bicondizionale booleana.

```prolog
?- bool_iff(false, false, X).
X = true.
```

### lookup(+Var, +Valuation, -Bool)
Cerca il valore booleano associato a `Var` nella valutazione.

```prolog
?- lookup(y, [x-true, y-false], X).
X = false.
```

### assignment(+Vars, -Valuation)
Genera tutte le valutazioni possibili per l'elenco `Vars`.

```prolog
?- assignment([a,b], X).
X = [a-true, b-true] ;
X = [a-true, b-false] ;
X = [a-false, b-true] ;
X = [a-false, b-false].
```

### eval(+Formula, +Valuation, -Bool)
Valuta una formula proposizionale.

```prolog
?- eval(or(and(a,b),c), [a-true, b-true, c-false], X).
X = true.
```

### vars_in_formula(+Formula, -Vars)
Raccoglie le variabili della formula, senza duplicati e ordinate.

```prolog
?- vars_in_formula(and(or(a,b),a), X).
X = [a,b].
```

### truth_row(+Formula, +Vars, -row(Valuation, Result))
Genera una riga della tabella di verita.

```prolog
?- truth_row(and(or(a,b),c), [a,b,c], X).
X = row([a-true, b-true, c-true], true) ;
...
```

### truth_table(+Formula, +Vars, -Rows)
Costruisce tutta la tabella di verita.

```prolog
?- truth_table(and(or(a,b),c), [a,b,c], Rows).
Rows = [row([a-true,b-true,c-true],true), ..., row([a-false,b-false,c-false],false)].
```

### truth_table_auto(+Formula, -Vars, -Rows)
Estrae automaticamente le variabili e costruisce la tabella.

```prolog
?- truth_table_auto(and(or(a,b),c), Vars, Rows).
Vars = [a,b,c],
Rows = [...].
```

## equivalence.pl

### equiv(+F1, +F2, +Vars)
Vero se `F1` e `F2` hanno sempre lo stesso valore.

```prolog
?- equiv(imp(a,b), or(not(a),b), [a,b]).
true.
```

### not_equiv(+F1, +F2, +Vars)
Vero se esiste almeno una valutazione che li distingue.

```prolog
?- not_equiv(and(a,b), or(a,b), [a,b]).
true.
```

### counterexample_equiv(+F1, +F2, +Vars, -Val)
Restituisce un controesempio alla equivalenza.

```prolog
?- counterexample_equiv(and(a,b), or(a,b), [a,b], Val).
Val = [a-true,b-false] ;
Val = [a-false,b-true].
```

### model(+Formula, +Vars, -Valuation)
Restituisce una valutazione che rende vera la formula.

```prolog
?- model(and(or(a,b),c), [a,b,c], X).
X = [a-true, b-true, c-true] ;
...
```

### countermodel(+Formula, +Vars, -Valuation)
Restituisce una valutazione che rende falsa la formula.

```prolog
?- countermodel(and(or(a,b),c), [a,b,c], X).
X = [a-true, b-true, c-false] ;
...
```

### all_models(+Formula, +Vars, -Models)
Restituisce tutti i modelli che rendono vera la formula.

```prolog
?- all_models(and(or(a,b),c), [a,b,c], X).
X = [[a-true,b-true,c-true], [a-true,b-false,c-true], [a-false,b-true,c-true]].
```

### all_countermodels(+Formula, +Vars, -CounterModels)
Restituisce tutti i modelli che rendono falsa la formula.

```prolog
?- all_countermodels(and(or(a,b),c), [a,b,c], X).
X = [[a-true,b-true,c-false], [a-true,b-false,c-false], [a-false,b-true,c-false], [a-false,b-false,c-true], [a-false,b-false,c-false]].
```

### satisfiable(+Formula, +Vars)
Vero se esiste almeno una valutazione che rende vera la formula.

```prolog
?- satisfiable(and(a, not(b)), [a,b]).
true.
```

### unsatisfiable(+Formula, +Vars)
Vero se non esiste alcuna valutazione che rende vera la formula.

```prolog
?- unsatisfiable(and(a, not(a)), [a]).
true.
```

### tautology(+Formula, +Vars)
Vero se la formula e vera per tutte le valutazioni.

```prolog
?- tautology(or(a, not(a)), [a]).
true.
```

### contradiction(+Formula, +Vars)
Vero se la formula e falsa per tutte le valutazioni.

```prolog
?- contradiction(and(a, not(a)), [a]).
true.
```

### satisfying_assignment(+F, +Vars, -Val)
Restituisce una assegnazione che rende vera `F`.

```prolog
?- satisfying_assignment(and(a, not(b)), [a,b], Val).
Val = [a-true,b-false].
```

### falsifying_assignment(+F, +Vars, -Val)
Restituisce una assegnazione che rende falsa `F`.

```prolog
?- falsifying_assignment(and(a,b), [a,b], Val).
Val = [a-true,b-false] ;
...
```

### implies_formula(+F1, +F2, +Vars)
Vero se `F1` implica logicamente `F2`.

```prolog
?- implies_formula(and(a,b), a, [a,b]).
true.
```

### mutually_exclusive(+F1, +F2, +Vars)
Vero se non possono essere entrambe vere.

```prolog
?- mutually_exclusive(a, not(a), [a]).
true.
```

### jointly_satisfiable(+F1, +F2, +Vars)
Vero se esiste una valutazione che le rende entrambe vere.

```prolog
?- jointly_satisfiable(a, b, [a,b]).
true.
```

### same_value_under(+F1, +F2, +Valuation)
Vero se `F1` e `F2` hanno lo stesso valore sotto una valutazione.

```prolog
?- same_value_under(imp(a,b), or(not(a),b), [a-true,b-false]).
true.
```

### different_value_under(+F1, +F2, +Valuation)
Vero se `F1` e `F2` hanno valori diversi sotto una valutazione.

```prolog
?- different_value_under(and(a,b), or(a,b), [a-true,b-false]).
true.
```

### filter_non_equivalent(+Fixed, +Candidates, +Vars, -Filtered)
Filtra la lista tenendo solo formule non equivalenti a `Fixed`.

```prolog
?- filter_non_equivalent(a, [a,not(a),or(a,b)], [a,b], X).
X = [not(a)].
```

### filter_equivalent(+Fixed, +Candidates, +Vars, -Filtered)
Filtra la lista tenendo solo formule equivalenti a `Fixed`.

```prolog
?- filter_equivalent(or(not(a),b), [imp(a,b), and(a,b)], [a,b], X).
X = [imp(a,b)].
```

## rewrite.pl

### rewrite_formula(+In, -Out)
Una singola riscrittura equivalente (anche in sottoformule).

```prolog
?- rewrite_formula(not(not(a)), Out).
Out = a.
```

### expand_implications(+In, -Out)
Elimina ricorsivamente `imp` e `iff`.

```prolog
?- expand_implications(iff(a,b), Out).
Out = and(or(not(a),b), or(not(b),a)).
```

### to_nnf(+In, -Out)
Converte la formula in Negation Normal Form.

```prolog
?- to_nnf(or(not(imp(p,q)),and(r,or(s,t))), X).
X = or(and(p, not(q)), and(r, or(s, t))).
```

### to_cnf(+In, -Out)
Porta la formula in forma congiuntiva (CNF).

```prolog
?- to_cnf(or(not(imp(p,q)),and(r,or(s,t))), X).
X = ...
```

### to_dnf(+In, -Out)
Porta la formula in forma disgiuntiva (DNF).

```prolog
?- to_dnf(or(not(imp(p,q)),and(r,or(s,t))), X).
X = ...
```

### rewrite_path(+In, -Path)
Restituisce una sequenza di riscritture fino a una forma stabile.

```prolog
?- rewrite_path(and(true, not(not(p))), X).
X = [and(true, not(not(p))), not(not(p)), p].
```

## templates.pl

### formula_of_depth(+Depth, +Vars, -Formula)
Genera formule (una alla volta) con profondita esatta `Depth`.

```prolog
?- formula_of_depth(2, [p], F).
F = not(not(p)) ;
...
```

### all_formulas_of_depth(+Depth, +Vars, -Formulas)
Restituisce tutte le formule di profondita `Depth`.

```prolog
?- all_formulas_of_depth(2, [p], Fs).
Fs = [not(not(p)), and(p, not(p)), iff(p, not(p)), imp(p, not(p)), imp(not(p), p), or(p, not(p))].
```

### all_formulas_of_depth_using_all_vars(+Depth, +Vars, -Formulas)
Come sopra, ma mantiene solo formule che usano tutte le variabili date.

```prolog
?- all_formulas_of_depth_using_all_vars(2, [p,q], Fs).
Fs = [...].
```

### some_formulas_of_depth(+Depth, +Vars, +Limit, -Formulas)
Campiona fino a `Limit` formule distinte di profondita `Depth`.

```prolog
?- some_formulas_of_depth(3, [p,q], 5, Fs).
Fs = [...].
```

### some_formulas_of_depth_using_all_vars(+Depth, +Vars, +Limit, -Formulas)
Campiona fino a `Limit` formule distinte che usano tutte le variabili.

```prolog
?- some_formulas_of_depth_using_all_vars(3, [p,q], 5, Fs).
Fs = [...].
```

### some_formulas_of_depth_using_all_vars_with_head(+Depth, +Vars, +Head, +Limit, -Formulas)
Come sopra, vincolando l'operatore principale (`Head`), ad esempio `and` o `or`.

```prolog
?- some_formulas_of_depth_using_all_vars_with_head(3, [p,q], and, 5, Fs).
Fs = [...].
```

### some_formulas_of_depth_using_all_vars_with_head_balanced(+Depth, +Vars, +Head, +Limit, -Formulas)
Variante che privilegia strutture piu bilanciate.

```prolog
?- some_formulas_of_depth_using_all_vars_with_head_balanced(3, [p,q,r], or, 5, Fs).
Fs = [...].
```

## distractions.pl

### distract_formula(+Formula, +MaxSteps, -Distracted)
Genera un singolo offuscamento casuale applicando da `1` a `MaxSteps` mutazioni.

```prolog
?- distract_formula(and(p,q), 2, X).
X = imp(p, imp(q, q)).
```

### distract_exactly(+Formula, +Steps, -Distracted)
Applica esattamente `Steps` mutazioni, evitando cicli sulla stessa formula.

```prolog
?- distract_exactly(and(p,q), 2, X).
X = or(p, q) ;
...
```

### distract_formula_with_trace(+Formula, +MaxSteps, -Distracted, -Trace)
Variante casuale che restituisce anche la traccia dei passi.

```prolog
?- distract_formula_with_trace(and(p,q), 2, X, T).
X = or(p, q),
T = [mutate(...), mutate(...)].
```

### all_distractions(+Formula, +MaxSteps, -List)
Raccoglie tutti gli offuscamenti distinti ottenibili in `1..MaxSteps` passi.

```prolog
?- all_distractions(and(p,q), 2, X).
X = [...].
```

### distract_n(+Formula, +MaxSteps, +N, -List)
Restituisce fino a `N` offuscamenti distinti.

```prolog
?- distract_n(and(p,q), 2, 3, X).
X = [...].
```

### one_step_distraction(+Formula, -Distracted)
Elenca tutte le mutazioni possibili in un solo passo.

```prolog
?- one_step_distraction(and(p,q), X).
X = not(p) ;
X = or(p, q) ;
...
```

### non_equivalent_distraction(+Formula, +MaxSteps, -Distracted)
Genera solo offuscamenti non equivalenti alla formula originale.

```prolog
?- non_equivalent_distraction(and(p,q), 2, X).
X = not(p) ;
...
```

### all_non_equivalent_distractions(+Formula, +MaxSteps, -Ds)
Restituisce tutti gli offuscamenti non equivalenti entro `MaxSteps`.

```prolog
?- all_non_equivalent_distractions(and(p,q), 2, X).
X = [...].
```

### one_step_non_equivalent_distraction(+Formula, -Distracted)
Versione a un passo che mantiene solo risultati non equivalenti.

```prolog
?- one_step_non_equivalent_distraction(and(p,q), X).
X = not(p) ;
...
```

### all_one_step_non_equivalent_distractions(+Formula, -Ds)
Lista completa dei distractor non equivalenti a un passo.

```prolog
?- all_one_step_non_equivalent_distractions(and(p,q), Ds).
Ds = [...].
```

### some_one_step_non_equivalent_distractions(+Formula, +Limit, -Ds)
Restituisce al massimo `Limit` distractor non equivalenti a un passo.

```prolog
?- some_one_step_non_equivalent_distractions(and(p,q), 5, Ds).
Ds = [...].
```

### some_non_equivalent_distractions(+Formula, +MaxSteps, +Limit, -Ds)
Restituisce al massimo `Limit` distractor non equivalenti entro `MaxSteps`.

```prolog
?- some_non_equivalent_distractions(and(p,q), 2, 10, Ds).
Ds = [...].
```

## python/generator.py

### build_exercise(expr, wrong_answers_count=3, max_steps=2, bridge=None, seed=None, timeout=10)
Costruisce un esercizio a partire da una formula data, con una formula corretta riscritta equivalente e un insieme di distractor errati.

Note:
- la formula corretta riscritta e garantita diversa dalla formula iniziale
- i distractor vengono filtrati per mantenere solo formule non equivalenti e con le variabili richieste

### build_ex_depth(depth=None, variables=DEFAULT_VARIABLES, use_all=False, timeout=10, seed=None, wrong_answers_count=3, max_steps=2, bridge=None)
Genera prima una formula che usa le variabili richieste, poi costruisce un esercizio completo come sopra.

### build_tvq(predicate_count, true_options_count, false_options_count, timeout=10, seed=None, bridge=None)
Costruisce una domanda del tipo:

- Informazione 1
- Informazione 2
- ...

dove le informazioni derivano da una valutazione booleana di predicati in formato Prolog, ma nell'output HTTP/Python vengono serializzate come array di stringhe, ad esempio `["p-true", "q-false"]`, e un insieme di opzioni formato da formule vere e false sotto quella valutazione.

Vincoli del risultato:
- `predicate_count` decide quanti atomi proposizionali vengono usati nell'informazione
- `true_options_count` decide quante opzioni devono risultare vere
- `false_options_count` decide quante opzioni devono risultare false
- le opzioni vere sono distinte tra loro
- le opzioni false sono distinte tra loro

Campi principali restituiti:
- `information`: valutazione scelta, serializzata come array JSON di stringhe, ad esempio `["p-true", "q-false"]`
- `options`: lista mista di opzioni con flag `is_true`
- `true_options`: sole opzioni vere
- `false_options`: sole opzioni false

### build_tvq_json(...)
Serializza come stringa JSON il risultato di `build_tvq`.

### build_ex_json(...)
Serializza come stringa JSON il risultato di `build_exercise`.

### build_ex_depth_json(...)
Serializza come stringa JSON il risultato di `build_ex_depth`.

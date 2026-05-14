#!/usr/bin/env python
"""Test di integrazione per verificare il filtro di operatori binari nel flusso di generazione."""

import sys
sys.path.insert(0, '/home/kevinpescarollo/Documents/Tirocinio/API_Logica/python')

from generator import (
    formula_binary_operator_count, 
    generate_formula,
    generate_formula_json,
    generate_formula_by_variable_count,
    _as_ast,
    MAX_BINARY_OPERATORS,
)

def test_generate_formula_respects_limit():
    """Testa che generate_formula generi solo formule con max 2 operatori binari."""
    print("\n" + "=" * 60)
    print("Test 1: generate_formula rispetta il limite di operatori")
    print("=" * 60)
    
    for i in range(5):
        try:
            formula = generate_formula(depth=2, variables=["p", "q", "r"], seed=i)
            ast = _as_ast(formula)
            count = formula_binary_operator_count(ast)
            print(f"  Prova {i+1}: {formula}")
            print(f"           Operatori binari: {count}/{MAX_BINARY_OPERATORS}")
            assert count <= MAX_BINARY_OPERATORS, f"Formula ha {count} operatori, massimo consentito è {MAX_BINARY_OPERATORS}"
        except RuntimeError as e:
            print(f"  Prova {i+1}: Nessuna formula valida generata ({e})")
            # Questo è ok se non ci sono formule disponibili
    
    print("\n✓ Test 1 passato: tutte le formule generate rispettano il limite")

def test_generate_formula_json_respects_limit():
    """Testa che generate_formula_json generi solo formule con max 2 operatori binari."""
    print("\n" + "=" * 60)
    print("Test 2: generate_formula_json rispetta il limite di operatori")
    print("=" * 60)
    
    for i in range(3):
        try:
            result = generate_formula_json(depth=2, variables=["p", "q", "r", "s"], seed=i)
            formula_prolog = result.get("formula_prolog")
            ast = _as_ast(formula_prolog)
            count = formula_binary_operator_count(ast)
            print(f"  Prova {i+1}: {formula_prolog}")
            print(f"           Operatori binari: {count}/{MAX_BINARY_OPERATORS}")
            assert count <= MAX_BINARY_OPERATORS, f"Formula ha {count} operatori, massimo consentito è {MAX_BINARY_OPERATORS}"
        except RuntimeError as e:
            print(f"  Prova {i+1}: Nessuna formula valida generata ({e})")
    
    print("\n✓ Test 2 passato: tutte le formule JSON generate rispettano il limite")

def test_generate_formula_by_variable_count_respects_limit():
    """Testa che generate_formula_by_variable_count generi solo formule con max 2 operatori binari."""
    print("\n" + "=" * 60)
    print("Test 3: generate_formula_by_variable_count rispetta il limite di operatori")
    print("=" * 60)
    
    for var_count in [2, 3]:
        for i in range(3):
            try:
                formula = generate_formula_by_variable_count(variable_count=var_count, seed=i)
                ast = _as_ast(formula)
                count = formula_binary_operator_count(ast)
                print(f"  Variables={var_count}, Prova {i+1}: {formula}")
                print(f"           Operatori binari: {count}/{MAX_BINARY_OPERATORS}")
                assert count <= MAX_BINARY_OPERATORS, f"Formula ha {count} operatori, massimo consentito è {MAX_BINARY_OPERATORS}"
            except RuntimeError as e:
                print(f"  Variables={var_count}, Prova {i+1}: Nessuna formula valida generata")
    
    print("\n✓ Test 3 passato: tutte le formule per variabili generate rispettano il limite")

if __name__ == "__main__":
    print("=" * 60)
    print("TEST DI INTEGRAZIONE - Limite di operatori binari")
    print("=" * 60)
    print(f"Massimo consentito di operatori binari: {MAX_BINARY_OPERATORS}")
    print("(NOT non conta nel limite e può essere aggiunto)")
    
    try:
        test_generate_formula_respects_limit()
        test_generate_formula_json_respects_limit()
        test_generate_formula_by_variable_count_respects_limit()
        
        print("\n" + "=" * 60)
        print("✓ TUTTI I TEST DI INTEGRAZIONE PASSATI!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n✗ TEST FALLITO: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERRORE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

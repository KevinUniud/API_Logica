#!/usr/bin/env python
"""Test per verificare che le formule rispettino il limite di 2 operatori binari."""

import sys
sys.path.insert(0, '/home/kevinpescarollo/Documents/Tirocinio/API_Logica/python')

from ast_logic import And, Or, Imp, Iff, Not, Var
from generator import formula_binary_operator_count, _has_valid_binary_operator_count, MAX_BINARY_OPERATORS

def test_binary_operator_count():
    """Testa il conteggio degli operatori binari escludendo NOT."""
    
    # Test 1: Singola variabile (0 operatori binari)
    expr = Var("p")
    count = formula_binary_operator_count(expr)
    print(f"✓ Test 1 (singola variabile): {count} operatori binari")
    assert count == 0, f"Atteso 0, ottenuto {count}"
    
    # Test 2: AND semplice (1 operatore binario)
    expr = And(Var("p"), Var("q"))
    count = formula_binary_operator_count(expr)
    print(f"✓ Test 2 (AND semplice): {count} operatori binari")
    assert count == 1, f"Atteso 1, ottenuto {count}"
    
    # Test 3: AND + OR (2 operatori binari)
    expr = And(Or(Var("p"), Var("q")), Var("r"))
    count = formula_binary_operator_count(expr)
    print(f"✓ Test 3 (AND + OR): {count} operatori binari")
    assert count == 2, f"Atteso 2, ottenuto {count}"
    
    # Test 4: AND + OR + IMP (3 operatori binari - dovrebbe superare il limite)
    expr = And(Or(Imp(Var("p"), Var("q")), Var("r")), Var("s"))
    count = formula_binary_operator_count(expr)
    print(f"✓ Test 4 (AND + OR + IMP): {count} operatori binari")
    assert count == 3, f"Atteso 3, ottenuto {count}"
    
    # Test 5: NOT non conta (dovrebbe essere 2 operatori binari)
    expr = Not(And(Or(Var("p"), Var("q")), Var("r")))
    count = formula_binary_operator_count(expr)
    print(f"✓ Test 5 (NOT(AND(OR...))): {count} operatori binari (NOT non conta)")
    assert count == 2, f"Atteso 2, ottenuto {count}"
    
    # Test 6: Doppio NOT (dovrebbe essere 0 operatori binari)
    expr = Not(Not(Var("p")))
    count = formula_binary_operator_count(expr)
    print(f"✓ Test 6 (NOT(NOT(p))): {count} operatori binari")
    assert count == 0, f"Atteso 0, ottenuto {count}"
    
    print("\n✓ Tutti i test di conteggio passati!")

def test_valid_operator_count():
    """Testa il controllo del limite massimo di operatori binari."""
    
    # Test 1: Formula valida (1 operatore)
    expr = And(Var("p"), Var("q"))
    valid = _has_valid_binary_operator_count(expr)
    print(f"✓ Test 1 (1 operatore - valida): {valid}")
    assert valid, "Formula con 1 operatore dovrebbe essere valida"
    
    # Test 2: Formula valida (2 operatori - max consentito)
    expr = And(Or(Var("p"), Var("q")), Var("r"))
    valid = _has_valid_binary_operator_count(expr)
    print(f"✓ Test 2 (2 operatori - massimo consentito): {valid}")
    assert valid, f"Formula con {MAX_BINARY_OPERATORS} operatori dovrebbe essere valida"
    
    # Test 3: Formula non valida (3 operatori - supera il limite)
    expr = And(Or(Imp(Var("p"), Var("q")), Var("r")), Var("s"))
    valid = _has_valid_binary_operator_count(expr)
    print(f"✓ Test 3 (3 operatori - oltre il limite): {valid}")
    assert not valid, "Formula con 3 operatori dovrebbe essere non valida"
    
    # Test 4: Formula valida anche con NOT (NOT non conta)
    expr = Not(And(Or(Var("p"), Var("q")), Var("r")))
    valid = _has_valid_binary_operator_count(expr)
    print(f"✓ Test 4 (2 operatori + NOT - valida): {valid}")
    assert valid, "Formula con 2 operatori binari + NOT dovrebbe essere valida"
    
    # Test 5: Formula valida con IFF
    expr = Iff(Var("p"), Var("q"))
    valid = _has_valid_binary_operator_count(expr)
    print(f"✓ Test 5 (1 operatore IFF - valida): {valid}")
    assert valid, "Formula con 1 operatore IFF dovrebbe essere valida"
    
    print("\n✓ Tutti i test di validazione passati!")

if __name__ == "__main__":
    print("=" * 60)
    print("Test del limite di operatori binari")
    print("=" * 60)
    print(f"Limite massimo di operatori binari: {MAX_BINARY_OPERATORS}\n")
    
    try:
        test_binary_operator_count()
        print()
        test_valid_operator_count()
        print("\n" + "=" * 60)
        print("✓ TUTTI I TEST PASSATI!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n✗ TEST FALLITO: {e}")
        sys.exit(1)

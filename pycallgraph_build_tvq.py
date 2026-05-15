from pycallgraph2 import PyCallGraph
from pycallgraph2.output import GraphvizOutput
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'python')))
from generator import build_tvq

if __name__ == '__main__':
    # Parametri di esempio (modifica se necessario)
    predicate_count = 2
    true_options_count = 2
    false_options_count = 2
    timeout = 10
    seed = 42
    bridge = None  # O imposta un bridge valido se necessario

    graphviz = GraphvizOutput()
    graphviz.output_file = 'build_tvq.png'

    with PyCallGraph(output=graphviz):
        build_tvq(
            predicate_count=predicate_count,
            true_options_count=true_options_count,
            false_options_count=false_options_count,
            timeout=timeout,
            seed=seed,
            bridge=bridge
        )
    print('Chiamate tracciate e salvate in build_tvq.png')

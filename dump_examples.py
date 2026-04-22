from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))

from generator import build_ex_depth, build_tvq  # noqa: E402


OUTPUT_PATH = Path(__file__).resolve().parent / "dump.txt"


def main() -> None:
    result = {
        "build_ex_depth": build_ex_depth(
            depth=2,
            variables=("p", "q", "s", "t"),
            use_all=False,
            timeout=10,
            wrong_answers_count=3,
            max_steps=2,
        ),
        "build_tvq": build_tvq(
            predicate_count=4,
            true_options_count=2,
            false_options_count=2,
            timeout=10,
        ),
    }

    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Scritto {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))

from generator import build_ex_depth, build_tvq  # noqa: E402


OUTPUT_PATH = Path(__file__).resolve().parent / "dump.txt"


def _build_ex_depth_sample() -> dict:
    """Genera un esempio depth con fallback su seed/depth compatibili ai nuovi vincoli."""
    last_error: Exception | None = None
    for depth in (2, 3):
        for seed in (7, 11, 17, 23, 29):
            try:
                return build_ex_depth(
                    depth=depth,
                    use_all=False,
                    timeout=10,
                    seed=seed,
                    wrong_answers_count=2,
                )
            except RuntimeError as exc:
                last_error = exc
                continue
    raise RuntimeError("Impossibile generare sample build_ex_depth") from last_error


def main() -> None:
    result = {
        "build_ex_depth": _build_ex_depth_sample(),
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

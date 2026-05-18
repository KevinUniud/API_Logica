import os
import sys
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PY_DIR = os.path.join(ROOT, "python")
sys.path.insert(0, PY_DIR)
import generator
from prolog_bridge import get_default_bridge


DUMP = os.path.join(ROOT, "dump.txt")


def process_value(val, bridge):
    # If string, treat as formula
    if isinstance(val, str):
        spoken, meta = generator.generate_spoken_ready_prolog(val, bridge=bridge)
        return spoken, meta
    if isinstance(val, list):
        spoken_list = []
        meta_list = []
        for item in val:
            if isinstance(item, str):
                s, m = generator.generate_spoken_ready_prolog(item, bridge=bridge)
                spoken_list.append(s)
                meta_list.append(m)
            else:
                spoken_list.append(item)
                meta_list.append({})
        return spoken_list, meta_list
    if isinstance(val, dict):
        # process recursively
        new = {}
        metas = {}
        for k, v in val.items():
            # skip keys that already represent spoken-ready outputs or metadata
            if "spoken_ready" in k or k.endswith("_meta"):
                continue
            s, m = process_value(v, bridge)
            if s is not None:
                # store alongside with modified key name
                if k.endswith("_prolog"):
                    new_key = k[:-7] + "_spoken_ready_prolog"
                else:
                    new_key = k + "_spoken_ready_prolog"
                new[new_key] = s
                metas[new_key + "_meta"] = m
        return new, metas
    return None, None


def main():
    with open(DUMP, "r", encoding="utf-8") as f:
        data = json.load(f)

    updated = dict(data)

    # initialize real Prolog bridge
    bridge = get_default_bridge()
    try:
        bridge.ensure_available()
    except Exception as exc:
        print("SWI-Prolog non disponibile o configurazione Prolog mancante:", exc)
        raise

    # For each top-level key, find prolog strings inside and add spoken fields
    for k, v in list(data.items()):
        if isinstance(v, dict):
            new_entries, metas = process_value(v, bridge)
            if new_entries:
                updated[k].update(new_entries)
            if metas:
                updated[k].update(metas)
        elif isinstance(v, str):
            s, m = process_value(v, bridge)
            if s is not None:
                updated[k + "_spoken_ready_prolog"] = s
                updated[k + "_spoken_meta"] = m
        elif isinstance(v, list):
            s, m = process_value(v, bridge)
            if s is not None:
                updated[k + "_spoken_ready_prolog"] = s
                updated[k + "_spoken_meta"] = m

    with open(DUMP, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)

    print("dump.txt aggiornato con campi spoken_ready_prolog (via Prolog)")


if __name__ == "__main__":
    main()

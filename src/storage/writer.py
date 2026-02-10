"""Writers for policy JSONL and batch index outputs."""
import json
import os
from typing import Dict, Iterable


def write_policies_jsonl(policies: Iterable[Dict], output_path: str) -> None:
    """Persist policies to JSONL file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for pol in policies:
            f.write(json.dumps(pol, ensure_ascii=False))
            f.write("\n")


def write_index(index: Dict, output_path: str) -> None:
    """Persist batch index JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .jsonio import read_jsonl


def output_contract(task: Dict[str, Any]) -> Dict[str, Any]:
    contract = task.get("output_contract")
    return contract if isinstance(contract, dict) else {}


class OutputContractEvaluator:
    def evaluate(self, task: Dict[str, Any]) -> Dict[str, Any]:
        contract = output_contract(task)
        output_file = contract.get("output_file", "")
        id_field = contract.get("id_field", "line_id")
        expected_ids = [str(item) for item in (
            contract.get("expected_ids")
            or contract.get("expected_line_ids")
            or task.get("line_ids")
            or [task.get("id", "")]
        ) if str(item)]

        rows, parse_errors = read_jsonl(output_file) if output_file else ([], ["missing output_contract.output_file"])
        actual_ids = [str(row.get(id_field, "")) for row in rows]
        actual_set = set(actual_ids)
        expected_set = set(expected_ids)
        duplicate_ids = sorted({item_id for item_id in actual_ids if item_id and actual_ids.count(item_id) > 1})
        missing_ids = sorted(expected_set - actual_set)
        extra_ids = sorted(actual_set - expected_set)
        blank_ids = sum(1 for item_id in actual_ids if not item_id)

        errors: List[str] = list(parse_errors)
        if duplicate_ids:
            errors.append(f"duplicate {id_field}: {', '.join(duplicate_ids)}")
        if missing_ids:
            errors.append(f"missing {id_field}: {', '.join(missing_ids)}")
        if extra_ids:
            errors.append(f"extra {id_field}: {', '.join(extra_ids)}")
        if blank_ids:
            errors.append(f"blank {id_field} rows: {blank_ids}")

        return {
            "status": "PASS" if not errors else "FAIL",
            "passed": not errors,
            "summary": "output contract passed" if not errors else "; ".join(errors),
            "output_file": str(Path(output_file)) if output_file else "",
            "expected_count": len(expected_ids),
            "actual_count": len(rows),
            "errors": errors,
        }

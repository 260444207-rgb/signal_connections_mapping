#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse

from common import iter_jsonl, write_jsonl, make_net_name


def load_candidates(path):
    return {row["line_id"]: row for row in iter_jsonl(path)}


def choose_high_confidence_candidate(candidate_mapping):
    candidates = candidate_mapping.get("candidates", [])
    if not candidates:
        return None
    top = candidates[0]
    second_score = candidates[1].get("score", 0) if len(candidates) > 1 else 0
    if top.get("score", 0) >= 0.92 and top.get("score", 0) - second_score >= 0.20:
        return top.get("pin", "")
    return None


def pre_resolve_candidates(normalized_path, candidate_path, decisions_out, needs_model_out):
    """
    自动预裁决阶段。

    这里只允许使用非常保守的候选分数兜底；不承载器件特殊语义。
    复杂硬件语义必须进入 semantic_mapping_resolver subagent。
    """
    candidates_by_id = load_candidates(candidate_path)
    decisions = []
    needs_model = []

    for row in iter_jsonl(normalized_path):
        line_id = row["line_id"]
        candidate_mapping = candidates_by_id.get(line_id, {"line_id": line_id, "candidates": []})
        pin = choose_high_confidence_candidate(candidate_mapping)
        if pin:
            decisions.append({
                "line_id": line_id,
                "selected_pin": pin,
                "decision_type": "project_rule_applied",
                "confidence": "Medium",
                "analysis": "候选 pin 分数高且明显领先，作为脚本预裁决结果；复杂语义仍建议由模型抽查。",
                "net_name": make_net_name(row.get("source_port", ""), "TO", pin),
                "needs_human_review": False,
            })
        else:
            decisions.append({
                "line_id": line_id,
                "selected_pin": "",
                "decision_type": "unresolved",
                "confidence": "Low",
                "analysis": "未找到唯一可信的自动候选结果，需进入隔离语义模型分析。",
                "net_name": "",
                "needs_human_review": True,
            })
            needs_model.append({
                "line_id": line_id,
                "reason": "needs_semantic_model_resolution",
                "normalized_connection": row,
                "candidate_mapping": candidate_mapping,
            })

    write_jsonl(decisions_out, decisions)
    write_jsonl(needs_model_out, needs_model)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--decisions-out", required=True)
    parser.add_argument("--needs-model-out", required=True)
    args = parser.parse_args()
    pre_resolve_candidates(args.normalized, args.candidates, args.decisions_out, args.needs_model_out)
    print("[OK] semantic pre-resolution finished")


if __name__ == "__main__":
    main()

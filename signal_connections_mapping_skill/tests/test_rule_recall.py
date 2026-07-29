from __future__ import annotations

import sys
import tempfile
import unittest
import os
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from build_model_resolution_tasks import extract_rule_blocks, match_rule_sections
from check_subagent_outputs import check_subagent_outputs
from generate_net_name import generate_net_name
from render_template_sheets import final_net_name
from infer_signal_shapes import iter_rule_sections, matching_rule_hint
from route_model_resolution import route_model_resolution
from build_model_resolution_tasks import (
    PIN_GROUP_THRESHOLD,
    build_diagram_link_context,
    build_pin_allocation_context,
    build_pin_group_catalog,
    compact_normalized_connection,
    pins_for_groups,
    render_shared_prompt,
)
from run_pipeline import (
    append_rule_path,
    build_combined_rules,
    combined_rules_are_current,
    discover_external_device_rules,
)
from run_pipeline import resolve_signal_interface_task_dir


def make_group(part: str, link_family: str, mapping_family: str, source: str, target: str) -> dict:
    return {
        "source_device_signature": f"DEVICE_INFO:{part}",
        "link_family_ids": [link_family],
        "mapping_families": [mapping_family],
        "target_device_signatures": [f"TARGET_CONTEXT:{target}"],
        "source_device_instances": [source],
        "target_device_instances": [target],
        "user_link_infos": [],
        "device_role_infos": [],
    }


def make_row(
    part: str,
    source_port: str,
    target: str,
    target_port: str,
    link_family: str = "",
    source: str = "SRC",
    shape: str = "scalar",
) -> dict:
    return {
        "source_part_id": part,
        "source_block_name": source,
        "source_block_id": source,
        "source_port": source_port,
        "target_block_name": target,
        "target_port": target_port,
        "connection_name": "LINE_1",
        "link_family_id": link_family,
        "link_instance_id": "",
        "user_link_info": "",
        "device_role_info": "",
        "signal_shape": shape,
        "signal_shape_info": {"shape": shape},
    }


class LayeredRuleRecallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.temp_dir.name)
        self.combined_path = build_combined_rules(self.task_dir)
        self.rule_text = self.combined_path.read_text(encoding="utf-8")
        self.blocks = extract_rule_blocks(self.rule_text)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_collects_all_layered_rule_files_with_metadata(self) -> None:
        self.assertEqual(18, len(self.blocks))
        by_id = {block["rule_id"]: block for block in self.blocks}
        self.assertEqual("device", by_id["0302078562"]["layer"])
        self.assertEqual("link", by_id["LINK_RF_TX"]["layer"])
        self.assertEqual("signal", by_id["SIGNAL_DIFF"]["layer"])
        self.assertEqual("global", by_id["GLOBAL_MAPPING"]["layer"])
        self.assertNotIn("rf_tx_chain.md", by_id["LINK_POWER"]["text"].lower())

    def test_shape_rule_sections_are_not_truncated(self) -> None:
        sections = iter_rule_sections(self.rule_text)
        self.assertEqual(18, len(sections))
        self.assertTrue(all(section.startswith("### RULE:") for section in sections))
        self.assertTrue(all(len(section) > 20 for section in sections))

    def test_shape_hint_is_local_to_matching_subsection(self) -> None:
        control_row = make_row(
            "302078562", "TX_SW0", "TXVGA00", "EN_CHA", "RF_TX_CHAIN", "SROC"
        )
        control_hint = matching_rule_hint(control_row, self.rule_text)
        self.assertNotIn("differential", control_hint.get("shape_hints", []))
        self.assertFalse(control_hint.get("strong_shape_hint", False))

        differential_row = make_row(
            "47151290", "RFIN0", "SROC", "DAC00", "RF_TX_CHAIN", "TXVGA"
        )
        differential_hint = matching_rule_hint(differential_row, self.rule_text)
        self.assertIn("differential", differential_hint["shape_hints"])
        self.assertTrue(differential_hint["strong_shape_hint"])

    def test_recall_obeys_link_device_signal_global_layers(self) -> None:
        group = make_group("47151290", "RF_TX_CHAIN", "RF_CHAIN", "TXVGA", "SROC")
        row = make_row(
            "47151290", "RFIN0", "SROC", "DAC00", "RF_TX_CHAIN", "TXVGA", "differential"
        )
        matches = match_rule_sections(self.blocks, group, [row])
        ids = [match["rule_id"] for match in matches]
        self.assertEqual(
            ["LINK_RF_TX", "47151290", "SIGNAL_DIFF", "SIGNAL_SPECIAL", "GLOBAL_MAPPING"],
            ids,
        )
        self.assertEqual("exact_link_family", matches[0]["match_type"])
        self.assertEqual("exact_source_part", matches[1]["match_type"])

    def test_sroc_part_id_exact_match_ignores_leading_zero(self) -> None:
        group = make_group("302078562", "RF_TX_CHAIN", "RF_CHAIN", "SROC", "TXVGA00")
        row = make_row(
            "302078562", "TX_SW0", "TXVGA00", "EN_CHA", "RF_TX_CHAIN", "SROC"
        )
        matches = match_rule_sections(self.blocks, group, [row])
        sroc = next(match for match in matches if match["rule_id"] == "0302078562")
        self.assertEqual("exact_source_part", sroc["match_type"])
        self.assertNotIn("AMC7964", [match["rule_id"] for match in matches])
        self.assertNotIn("TXCAL_RXCAL", [match["rule_id"] for match in matches])

    def test_general_rules_are_deterministically_recalled(self) -> None:
        power_group = make_group("999999", "POWER_CHAIN", "POWER_ENABLE", "MYSTERY", "PMU")
        power_row = make_row("999999", "VDD_3V3", "PMU", "VOUT", "POWER_CHAIN", "MYSTERY")
        power_ids = [
            match["rule_id"]
            for match in match_rule_sections(self.blocks, power_group, [power_row])
        ]
        self.assertIn("LINK_POWER", power_ids)
        self.assertIn("SIGNAL_POWER", power_ids)
        self.assertIn("SIGNAL_SPECIAL", power_ids)
        self.assertIn("GLOBAL_MAPPING", power_ids)
        self.assertNotIn("47151290", power_ids)

        diff_group = make_group(
            "999999", "LOCAL_DEVICE_MAPPING", "DIFFERENTIAL_PAIR", "MYSTERY", "ADC"
        )
        diff_row = make_row("999999", "ADC0", "ADC", "RFIN0", source="MYSTERY", shape="differential")
        diff_ids = [
            match["rule_id"]
            for match in match_rule_sections(self.blocks, diff_group, [diff_row])
        ]
        self.assertEqual(["SIGNAL_DIFF", "SIGNAL_SPECIAL", "GLOBAL_MAPPING"], diff_ids)

    def test_rule_snapshot_detects_external_rule_changes(self) -> None:
        user_rule = self.task_dir / "user_rules.md"
        user_rule.write_text("### RULE: USER_A 用户规则\n适用条件：\n通用\n", encoding="utf-8")
        build_combined_rules(self.task_dir, user_rules=str(user_rule))
        self.assertTrue(combined_rules_are_current(self.task_dir, user_rules=str(user_rule)))
        user_rule.write_text("### RULE: USER_B 更新规则\n适用条件：\n通用\n", encoding="utf-8")
        self.assertFalse(combined_rules_are_current(self.task_dir, user_rules=str(user_rule)))

    def test_auto_discovers_external_device_rules_file(self) -> None:
        external_rule = self.task_dir / "design" / "external_device_rules.md"
        external_rule.parent.mkdir()
        external_rule.write_text(
            "### RULE: EXT_DEVICE_API 接口器件规则\n"
            "适用条件：\n"
            "源端器件：EXT_DEV / 12345\n"
            "规则摘要：接口返回规则。\n",
            encoding="utf-8",
        )
        discovered = discover_external_device_rules(self.task_dir, "")
        self.assertEqual(external_rule, discovered)

        project_rules = append_rule_path("", discovered)
        combined = build_combined_rules(self.task_dir, project_rules=project_rules)
        text = combined.read_text(encoding="utf-8")
        self.assertIn("EXT_DEVICE_API", text)
        self.assertIn("接口返回规则", text)

    def test_project_rules_accept_multiple_paths(self) -> None:
        rule_a = self.task_dir / "rule_a.md"
        rule_b = self.task_dir / "rule_b.md"
        rule_a.write_text("### RULE: EXT_A 外部规则A\n适用条件：\n通用\n", encoding="utf-8")
        rule_b.write_text("### RULE: EXT_B 外部规则B\n适用条件：\n通用\n", encoding="utf-8")

        project_rules = append_rule_path(str(rule_a), rule_b)
        self.assertIn(os.pathsep, project_rules)

        combined = build_combined_rules(self.task_dir, project_rules=project_rules)
        text = combined.read_text(encoding="utf-8")
        self.assertIn("EXT_A", text)
        self.assertIn("EXT_B", text)

        project_rules_again = append_rule_path(project_rules, rule_b)
        self.assertEqual(project_rules, project_rules_again)

    def test_resolves_signal_interface_task_subdir(self) -> None:
        root = self.task_dir / "data_uuid"
        self.assertEqual(root / "signal_interface", resolve_signal_interface_task_dir(root))
        already = root / "signal_interface"
        self.assertEqual(already, resolve_signal_interface_task_dir(already))

    def test_external_rule_overrides_same_builtin_rule_id(self) -> None:
        user_rule = self.task_dir / "rules" / "user_rules.md"
        user_rule.parent.mkdir()
        user_rule.write_text(
            "### RULE: 47151290 用户覆盖 TXVGA\n"
            "适用条件：\n"
            "源端器件：TXVGA / 47151290\n"
            "规则摘要：用户覆盖内容。\n",
            encoding="utf-8",
        )
        combined = build_combined_rules(self.task_dir, user_rules=str(user_rule))
        blocks = extract_rule_blocks(combined.read_text(encoding="utf-8"))
        group = make_group("47151290", "RF_TX_CHAIN", "RF_CHAIN", "TXVGA", "SROC")
        row = make_row("47151290", "RFIN0", "SROC", "DAC00", "RF_TX_CHAIN", "TXVGA")
        matches = match_rule_sections(blocks, group, [row])
        device_rule = next(match for match in matches if match["rule_id"] == "47151290")
        self.assertEqual("custom", device_rule["layer"])
        self.assertIn("用户覆盖内容", device_rule["text"])

    def test_spi_rule_uses_sequential_unallocated_pin_policy(self) -> None:
        spi_rule = (ROOT / "rules" / "signal_rules" / "spi_bus.md").read_text(encoding="utf-8")
        self.assertIn("尚未使用的合法 SPI pin 顺序分配", spi_rule)
        self.assertNotIn("不能唯一映射到具体 pin，需要人工确认", spi_rule)

    def test_model_routing_uses_pin_info_gate_without_pin_candidates(self) -> None:
        normalized = self.task_dir / "normalized.jsonl"
        pins = self.task_dir / "pins.json"
        decisions = self.task_dir / "decisions.jsonl"
        needs_model = self.task_dir / "needs_model.jsonl"
        rows = [
            {"line_id": "L1", "source_part_id": "1", "signal_shape": "scalar"},
            {"line_id": "L2", "source_part_id": "MISSING", "signal_shape": "scalar"},
        ]
        normalized.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
        pins.write_text(
            json.dumps({"001": ["PIN_A"]}, ensure_ascii=False),
            encoding="utf-8",
        )

        route_model_resolution(normalized, pins, decisions, needs_model)

        routed = [
            json.loads(line)
            for line in needs_model.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        routed_decisions = [
            json.loads(line)
            for line in decisions.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(["L1"], [row["line_id"] for row in routed])
        self.assertEqual(2, len(routed_decisions))
        self.assertTrue(all(row["selected_pin"] == "" for row in routed_decisions))

    def test_subagent_payload_helpers_do_not_emit_pin_candidates(self) -> None:
        row = {
            "line_id": "L1",
            "source_sheet_name": "DEV0",
            "source_part_id": "001",
            "source_block_id": "B1",
            "source_block_name": "DEV",
            "source_port": "CTRL",
            "target_block_name": "LOAD",
            "target_port": "EN",
            "connection_id": "C1",
            "connection_name": "CTRL_NET",
            "signal_shape_info": {"shape": "scalar"},
        }
        payload = build_pin_allocation_context([row])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("candidate", serialized.lower())
        self.assertNotIn("rough_pin_search_hints", serialized)
        self.assertNotIn("line_pin_domains", serialized)
        self.assertNotIn("candidate_mappings", render_shared_prompt())
        self.assertNotIn("网络命名依据", render_shared_prompt())

    def test_task_context_uses_one_canonical_per_line_record(self) -> None:
        row = {
            "line_id": "L1",
            "base_line_id": "L1",
            "source_sheet_name": "DEV0",
            "output_sheet_name": "DEV0",
            "source_part_id": "001",
            "source_block_id": "B1",
            "source_block_name": "DEV",
            "source_port": "CTRL",
            "raw_source_port": "CTRL",
            "target_block_id": "B2",
            "target_block_name": "LOAD",
            "target_port": "EN",
            "raw_target_port": "EN",
            "connection_id": "C1",
            "base_connection_id": "C1",
            "connection_name": "CTRL_NET",
            "direction": "OUTPUT",
            "signal_shape_info": {
                "shape": "scalar",
                "expected_physical_pin_count": 1,
                "parent_line_id": "L1",
                "member_index": 1,
                "member_count": 1,
                "is_expanded_member": False,
                "confidence": "auto_high",
                "needs_model_shape_review": False,
                "evidence": {"source_pins_available": True},
            },
        }
        compact = compact_normalized_connection(row)
        self.assertNotIn("base_line_id", compact)
        self.assertNotIn("output_sheet_name", compact)
        self.assertNotIn("raw_source_port", compact)
        self.assertNotIn("raw_target_port", compact)
        self.assertEqual(
            {"shape": "scalar", "expected_physical_pin_count": 1},
            compact["signal_shape_info"],
        )

        diagram = build_diagram_link_context(
            {
                "link_family_ids": ["CONTROL"],
                "link_family_sources": ["explicit_link_info"],
            },
            [row],
        )
        self.assertNotIn("line_link_contexts", diagram)

    def test_finish_checker_accepts_minimal_task_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_file = root / "outputs" / "TASK_01.jsonl"
            output_file.parent.mkdir()
            output_file.write_text(
                json.dumps(
                    {
                        "line_id": "L1",
                        "selected_pin": "",
                        "decision_type": "unresolved",
                        "confidence": "Low",
                        "analysis": "insufficient information",
                        "net_name": "",
                        "needs_human_review": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            plan = root / "model_resolution_tasks" / "subagent_task_plan.json"
            plan.parent.mkdir()
            plan.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "TASK_01",
                                "line_ids": ["L1"],
                                "output_file": str(output_file),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = check_subagent_outputs(
                plan,
                root / "model_resolved_decisions.jsonl",
                root / "subagent_output_check.json",
                root / "failed_subagent_rerun_plan.md",
            )
            self.assertEqual("PASS", report["status"])

    def test_large_pin_group_catalog_is_lossless_multilabel_and_unranked(self) -> None:
        pins = ["RFIN0_P", "RFIN0_N", "SPI1_CLK", "VDD_1V8", "SPECIAL_X"]
        catalog = build_pin_group_catalog("PART_A", pins)

        self.assertEqual(PIN_GROUP_THRESHOLD, catalog["grouping_threshold"])
        self.assertTrue(catalog["lossless"])
        self.assertTrue(catalog["multi_label"])
        self.assertFalse(catalog["ranked"])
        self.assertEqual(pins, catalog["all_pins"])
        self.assertIn("RFIN0_P", catalog["groups"]["ANALOG_RF"])
        self.assertIn("RFIN0_P", catalog["groups"]["DIFFERENTIAL"])
        self.assertEqual(["SPECIAL_X"], catalog["groups"]["UNCLASSIFIED"])

        grouped_pins = {
            pin
            for group_pins in catalog["groups"].values()
            for pin in group_pins
        }
        self.assertEqual(set(pins), grouped_pins)
        self.assertEqual(
            ["RFIN0_P", "RFIN0_N"],
            pins_for_groups(catalog, ["DIFFERENTIAL"]),
        )


    def test_net_name_uses_meaningful_port_over_placeholder(self) -> None:
        nc = {
            "connection_name": "OLD_VALID_NAME",
            "source_block_name": "SROC",
            "target_block_name": "功放模组00_00-01",
            "source_port": "default",
            "target_port": "PA_SW_AB",
        }
        self.assertEqual("SROC_PAM_PA_SW_AB", generate_net_name(nc, "PIN1"))

    def test_net_name_prefers_numeric_port_when_both_ports_are_meaningful(self) -> None:
        nc = {
            "source_block_name": "集成驱动0",
            "target_block_name": "SROC",
            "source_port": "告警1",
            "target_port": "ALERT",
        }
        self.assertEqual("DRV0_SROC_ALERT1", generate_net_name(nc, "PIN1"))

    def test_final_net_name_ignores_model_and_connection_name_override(self) -> None:
        decision = {"net_name": "MODEL_NAME", "net_names": ["MODEL_LIST_NAME"]}
        normalized = {
            "connection_name": "OLD_VALID_NAME",
            "source_block_name": "SROC",
            "target_block_name": "AMC7964",
            "source_port": "SPI1",
            "target_port": "SPI",
        }
        self.assertEqual(
            "SROC_AMC_SPI1",
            final_net_name(decision, normalized, 0, "HAC_SPI1_CLK"),
        )


if __name__ == "__main__":
    unittest.main()

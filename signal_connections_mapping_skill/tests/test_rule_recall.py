from __future__ import annotations

import sys
import tempfile
import unittest
import os
import json
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_model_resolution_tasks import extract_rule_blocks, match_rule_sections
from check_subagent_outputs import check_subagent_outputs
from common import extract_component_uuid, load_pin_catalog, normalize_component_reference, pins_for_part
from generate_net_name import generate_net_name
from render_template_sheets import final_net_name
from validate_mapping import validate_mapping
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
    PIPELINE_CONFIG_FILENAME,
    FINISH_COMMAND_FILENAME,
    append_rule_path,
    build_combined_rules,
    combined_rules_are_current,
    discover_external_device_rules,
    load_pipeline_run_config,
    run_finish,
    save_pipeline_run_config,
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

    def test_extracts_component_uuid_from_block_info_metadata(self) -> None:
        component_uuid = "6c33dd64-9afd-4e31-87c4-5023b323be7f"
        samples = [
            json.dumps({"componentName": "SROC", "componentUuid": component_uuid}),
            rf'prefix {{\"componentUuid\":\"{component_uuid}\",\"name\":\"SROC\"}} suffix',
            f"componentUuid={component_uuid};componentName=SROC",
            json.dumps(json.dumps({"componentUuid": component_uuid})),
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(component_uuid, extract_component_uuid(sample))
                self.assertEqual(component_uuid, normalize_component_reference(sample))

    def test_loads_component_uuid_pin_catalog_record_format(self) -> None:
        component_uuid = "6c33dd64-9afd-4e31-87c4-5023b323be7f"
        pins_path = self.task_dir / "component_pins.json"
        pins_path.write_text(
            json.dumps({
                "components": [
                    {
                        "componentUuid": component_uuid,
                        "pins": [
                            {"pinName": "PA_SW0"},
                            {"name": "FEM_TDDSW00"},
                        ],
                    }
                ]
            }),
            encoding="utf-8",
        )

        catalog = load_pin_catalog(pins_path)

        self.assertEqual(["PA_SW0", "FEM_TDDSW00"], catalog[component_uuid])
        long_block_info_value = json.dumps({"componentUuid": component_uuid, "other": "metadata"})
        self.assertEqual(["PA_SW0", "FEM_TDDSW00"], pins_for_part(catalog, long_block_info_value))

    def test_loads_component_uuid_one_pin_per_record_format(self) -> None:
        component_uuid = "6c33dd64-9afd-4e31-87c4-5023b323be7f"
        pins_path = self.task_dir / "component_pin_rows.json"
        pins_path.write_text(
            json.dumps([
                {"componentUuid": component_uuid, "pinName": "PIN_A"},
                {"componentUuid": component_uuid, "pinInfo": {"pinName": "PIN_B"}},
            ]),
            encoding="utf-8",
        )

        catalog = load_pin_catalog(pins_path)

        self.assertEqual(["PIN_A", "PIN_B"], catalog[component_uuid])

    def test_preserves_legacy_part_number_pin_catalog(self) -> None:
        pins_path = self.task_dir / "legacy_pins.json"
        pins_path.write_text(
            json.dumps({"0302078562": ["PIN_A", "PIN_B"]}),
            encoding="utf-8",
        )

        catalog = load_pin_catalog(pins_path)

        self.assertEqual(["PIN_A", "PIN_B"], pins_for_part(catalog, "302078562"))

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

    def test_exact_source_port_pin_is_pre_resolved_without_subagent_task(self) -> None:
        normalized = self.task_dir / "normalized.jsonl"
        pins = self.task_dir / "pins.json"
        decisions = self.task_dir / "decisions.jsonl"
        needs_model = self.task_dir / "needs_model.jsonl"
        rows = [
            {
                "line_id": "L_DIRECT",
                "source_part_id": "001",
                "source_port": "PA_SW0",
                "signal_shape_info": {"shape": "scalar", "needs_model_shape_review": False},
            },
            {
                "line_id": "L_SEMANTIC",
                "source_part_id": "001",
                "source_port": "LOGICAL_CTRL",
                "signal_shape_info": {"shape": "scalar", "needs_model_shape_review": False},
            },
        ]
        normalized.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
        pins.write_text(
            json.dumps({"001": ["PA_SW0", "PA_PD_SW0"]}, ensure_ascii=False),
            encoding="utf-8",
        )

        route_model_resolution(normalized, pins, decisions, needs_model)

        routed = [json.loads(line) for line in needs_model.read_text(encoding="utf-8").splitlines() if line]
        by_line = {
            row["line_id"]: row
            for row in (json.loads(line) for line in decisions.read_text(encoding="utf-8").splitlines() if line)
        }
        self.assertEqual(["L_SEMANTIC"], [row["line_id"] for row in routed])
        self.assertEqual("PA_SW0", by_line["L_DIRECT"]["selected_pin"])
        self.assertEqual("pre_resolved", by_line["L_DIRECT"]["decision_type"])
        self.assertEqual("High", by_line["L_DIRECT"]["confidence"])

    def test_validation_rejects_second_mapping_of_exact_source_port_pin(self) -> None:
        normalized = self.task_dir / "normalized.jsonl"
        decisions = self.task_dir / "decisions.jsonl"
        pins = self.task_dir / "pins.json"
        report = self.task_dir / "validation.json"
        normalized.write_text(
            json.dumps({
                "line_id": "L1",
                "source_part_id": "001",
                "source_sheet_name": "SROC",
                "source_port": "PA_SW0",
                "signal_shape_info": {"shape": "scalar", "needs_model_shape_review": False},
            }) + "\n",
            encoding="utf-8",
        )
        decisions.write_text(
            json.dumps({
                "line_id": "L1",
                "selected_pin": "PA_PD_SW0",
                "decision_type": "model_resolved",
                "confidence": "High",
                "analysis": "incorrect second mapping",
                "net_name": "",
            }) + "\n",
            encoding="utf-8",
        )
        pins.write_text(json.dumps({"001": ["PA_SW0", "PA_PD_SW0"]}), encoding="utf-8")

        result = validate_mapping(normalized, decisions, pins, report)

        self.assertEqual("ERROR", result["status"])
        self.assertTrue(any("must equal source_port" in error["message"] for error in result["errors"]))

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

    def test_shared_prompt_requires_model_subagent_with_30_minute_timeout(self) -> None:
        prompt = render_shared_prompt()
        self.assertIn("模型 subagent", prompt)
        self.assertIn("sessions_spawn", prompt)
        self.assertIn("30 分钟", prompt)
        self.assertIn("1800000 ms", prompt)
        self.assertIn("禁止编写 Python / PowerShell / JavaScript 等脚本", prompt)
        self.assertIn("selected_pin 的语义裁决必须由模型完成", prompt)
        self.assertIn("selected_pin 必须直接等于 source_port", prompt)

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

    def test_finish_checker_blocks_missing_session_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_file = root / "outputs" / "TASK_01.jsonl"
            output_file.parent.mkdir()
            output_file.write_text(json.dumps({"line_id": "L1"}) + "\n", encoding="utf-8")
            plan = root / "model_resolution_tasks" / "subagent_task_plan.json"
            plan.parent.mkdir()
            plan.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_id": "TASK_01",
                                "subagent_session_id": "SESSION_A",
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

            self.assertEqual("FAIL", report["status"])
            self.assertEqual("FAIL", report["session_status"]["status"])
            self.assertIn("missing subagent session status file", report["session_status"]["errors"][0])

    def test_finish_checker_requires_completed_session_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_file = root / "outputs" / "TASK_01.jsonl"
            output_file.parent.mkdir()
            output_file.write_text(json.dumps({"line_id": "L1"}) + "\n", encoding="utf-8")
            plan_dir = root / "model_resolution_tasks"
            plan_dir.mkdir()
            status_file = plan_dir / "subagent_session_status.json"
            plan = plan_dir / "subagent_task_plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "subagent_session_status_json": str(status_file),
                        "tasks": [
                            {
                                "task_id": "TASK_01",
                                "subagent_session_id": "SESSION_A",
                                "line_ids": ["L1"],
                                "output_file": str(output_file),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            status_file.write_text(
                json.dumps(
                    {
                        "sessions": [
                            {
                                "subagent_session_id": "SESSION_A",
                                "spawned": True,
                                "completed": True,
                                "failed": False,
                                "timed_out": False,
                                "rerun_required": False,
                                "completed_task_ids": ["TASK_01"],
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
            self.assertEqual("PASS", report["session_status"]["status"])

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

    def test_model_tasks_persist_canonical_finish_contract(self) -> None:
        connections = self.task_dir / "design" / "aggregated_connections.xlsx"
        pins = self.task_dir / "pin_info.json"
        config_path = save_pipeline_run_config(self.task_dir, str(connections), str(pins))

        self.assertEqual(self.task_dir / "intermediate" / PIPELINE_CONFIG_FILENAME, config_path)
        config = load_pipeline_run_config(self.task_dir)
        self.assertEqual(str(connections.resolve()), config["connections"])
        self.assertEqual(str(connections.resolve()), config["template_excel"])
        self.assertEqual(str((ROOT / "scripts" / "run_pipeline.py").resolve()), config["script_path"])
        command = (self.task_dir / "intermediate" / FINISH_COMMAND_FILENAME).read_text(encoding="utf-8")
        self.assertNotIn("Set-Location", command)
        self.assertIn(str((ROOT / "scripts" / "run_pipeline.py").resolve()), command)
        self.assertIn("--stage finish", command)
        self.assertNotIn("--normalized", command)
        self.assertNotIn("--decisions", command)

    def test_finish_never_renders_when_validation_fails(self) -> None:
        with (
            mock.patch("run_pipeline.run_apply"),
            mock.patch("run_pipeline.merge_decisions"),
            mock.patch("run_pipeline.validate_mapping", return_value={"status": "ERROR"}),
            mock.patch("run_pipeline.render_template_sheets") as render,
        ):
            with self.assertRaisesRegex(RuntimeError, "validation_report.json is not PASS"):
                run_finish(
                    self.task_dir,
                    "connections.xlsx",
                    "pin_info.json",
                    "connections.xlsx",
                    "template_sheets",
                )
            render.assert_not_called()


if __name__ == "__main__":
    unittest.main()

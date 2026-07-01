from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from build_model_resolution_tasks import extract_rule_blocks, match_rule_sections
from infer_signal_shapes import iter_rule_sections, matching_rule_hint
from run_pipeline import build_combined_rules, combined_rules_are_current


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


if __name__ == "__main__":
    unittest.main()

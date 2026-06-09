#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华为原理图网络命名生成器

功能：给定 normalized_connection 和 selected_pin，生成符合华为规范的网络名。

使用方式
--------
    from generate_net_name import generate_net_name, abbreviate_block

    net_name = generate_net_name(normalized_connection_dict, selected_pin)
    # selected_pin 可选，电源类网络会用到

华为规范
--------
1. 连线名称优先：connection_name 非空且不包含 'line'（不区分大小写）
   → 直接使用连线名称（清洗后），不额外处理
2. 按规范生成：其余情况按信号类型走对应格式
   - 射频信号（RF_CHAIN）：类型_源端_目的端_通道_频率_极性（6部分）
   - 电源信号（POWER_ENABLE）：电源类型_电压值_通道_负载_管脚（6部分）
   - 数字控制信号（SPI/I2C/GPIO）：总线_编号_发送端_接收端_信号_频率_电平_后缀（9部分）
   - DAC：DAC通道_源端_目的端_AFE_频率
   - ADC：ADC通道_目的端_反馈_源端_频率
   - 差分信号：TX/RX_源端_目的端_通道_频率_P/N

字符集约束（所有输出强制满足）
------------------------------
- SCREAMING_SNAKE_CASE（全大写，下划线分割）
- 必须以字母开头（数字开头自动加前缀 N）
- 长度 ≤ 31 字符
- 中划线 - 自动替换为下划线 _
"""

from __future__ import annotations

import re
from typing import Any, Dict

# ============================================================================
# ① Block 名称 → 简称映射
# ============================================================================
# 华为规范：只能使用大写字母和数字，禁止体现芯片型号（脱敏要求）
# 来源：框图 Excel 的 source_block_name / target_block_name

BLOCK_ABBR: Dict[str, str] = {
    # SROC
    "SROC": "SROC",
    "SROC城堡板": "SROC",
    "SROC城堡版": "SROC",
    "sroc": "SROC",
    # TXVGA
    "TX VGA00_00-01": "TXVGA",
    "TX VGA01_02-03": "TXVGA",
    "TX VGA02_04-05": "TXVGA",
    "TX VGA03_06-07": "TXVGA",
    "TXVGA00": "TXVGA",
    "TXVGA01": "TXVGA",
    "TXVGA02": "TXVGA",
    "TXVGA03": "TXVGA",
    "TX VGA00_00-01": "TXVGA",
    "TXVGA*4": "TXVGA",
    "TXVGA-0607": "TXVGA",
    "TXVGA*4": "TXVGA",
    # PA
    "PA0": "PA0",
    "PA1": "PA1",
    "PA3": "PA3",
    "PA_DET": "PADET",
    # AMC
    "AMC7964_00-03": "AMC",
    "AMC7964": "AMC",
    # RF Filter
    "RF Filter0": "FILTER",
    "RF Filter1": "FILTER",
    "RF Filter2": "FILTER",
    "RF Filter3": "FILTER",
    "RF Filter4": "FILTER",
    "RF Filter5": "FILTER",
    "RF Filter6": "FILTER",
    "RF Filter7": "FILTER",
    # 功放模组
    "功放模组00_00-01": "PAM",
    "功放模组01_02-03": "PAM",
    "功放模组02_04-05": "PAM",
    "功放模组03_06-07": "PAM",
    "功放模组*8": "PAM",
    "功放模组-0607": "PAM",
    # HBF
    "HBF-0003": "HBF",
    "HBF-0407": "HBF",
    "HBF0003": "HBF",
    "HBF0811": "HBF",
    "HBF1619": "HBF",
    "HBF2427": "HBF",
    # 滤波器/LNA/限幅器
    "Filter0_Ch32": "FILTER",
    "Filter1_Ch32": "FILTER",
    "Filter2_Ch32": "FILTER",
    "LNA0_Ch32": "LNA",
    "LNA1_Ch32": "LNA",
    "限幅器32": "LMT",
    # Balun
    "RX balun 07": "BALUN",
    "balun01": "BALUN",
    "balun04": "BALUN",
    # 反馈开关
    "反馈九选一开关": "FB",
    "反馈九选一开关*2": "FB",
    "反馈九选一开关*4": "FB",
    # 比邻星/天狼星
    "比邻星0": "PULSAR",
    "比邻星1": "PULSAR",
    "比邻星2": "PULSAR",
    "比邻星3": "PULSAR",
    "比邻星4": "PULSAR",
    "比邻星5": "PULSAR",
    "比邻星6": "PULSAR",
    "比邻星7": "PULSAR",
    "天狼星0": "SIRIUS",
    # 集成驱动
    "集成驱动0": "DRV0",
    "集成驱动1": "DRV1",
    # 校准/检测
    "633-9112": "CAL1",
    "633-9108": "CAL2",
    "633_9112_": "CAL1",
    "633_9108_": "CAL2",
    "633_9036_TXCAL_1": "TXCAL",
    "633_9029_RXCAL_1": "RXCAL",
    "TXCAL_1": "TXCAL",
    "RXCAL_1": "RXCAL",
    # 电源/连接器
    "TRX电源连接器0": "PWR",
    "连接器": "CONN",
    "高低速连接器": "CONN",
    # 温度/Link
    "温度传感器IC": "TEMP",
    "link": "LINK",
}


def abbreviate_block(block: str) -> str:
    """将 block 名称转换为华为规范简称。"""
    if not block:
        return block
    if block in BLOCK_ABBR:
        return BLOCK_ABBR[block]
    # 通用规则：去特殊字符、去掉末尾数字、用前6位
    clean = re.sub(r"[^A-Za-z0-9]", "", block)
    s = re.sub(r"\d+$", "", clean)  # 去掉末尾数字
    result = s[:6].upper() if s else clean[:6].upper()
    return result


# ============================================================================
# ② 文本提取工具
# ============================================================================

_FREQ_RE = re.compile(r"(\d+)M(\d+)?")
_PORT_NUM_RE = re.compile(r"[_\-](\d+)")
_CH_RE = re.compile(r"[_\-]?Ch?(\d+)", re.I)


def extract_freq(conn_name: str) -> str:
    """从 connection_name 中提取频率，格式：800M / 1M5 等。"""
    m = _FREQ_RE.search(conn_name or "")
    if m:
        return f"{m.group(1)}M{m.group(2) or ''}"
    m2 = re.search(r"_(\d+)M\b", conn_name or "")
    if m2:
        return m2.group(1) + "M"
    return ""


def extract_port_num(source_port: str) -> str:
    """从 source_port 提取端口编号，如 _00 / _01。"""
    m = _PORT_NUM_RE.search(source_port or "")
    return m.group(1) if m else ""


def extract_ch(conn_name: str) -> str:
    """从 connection_name 提取通道标识，格式：CH0 / CH7。"""
    m = _CH_RE.search(conn_name or "")
    return f"CH{m.group(1)}" if m else ""


def extract_pol(source_port: str, conn_name: str) -> str:
    """提取极性后缀：_P（正端）或 _N（负端）。"""
    sp = source_port.upper()
    cn = conn_name.upper()
    if "_P" in sp or "_P" in cn:
        return "_P"
    if "_N" in sp or "_N" in cn:
        return "_N"
    return ""


def extract_voltage(source_port: str) -> str:
    """从 source_port 中提取电压值，如 0V65 / 1V8 / 3V3。"""
    m = re.search(r"VDD[_\-]?(\d+V\d*)", source_port.upper())
    if m:
        return m.group(1)
    m2 = re.search(r"(\d+V\d*)", source_port)
    if m2:
        return m2.group(1)
    return "V"


# ============================================================================
# ③ 信号类型分类
# ============================================================================

SignalType = str  # "POWER" | "CTRL" | "DIFF" | "RF" | "DAC" | "ADC" | "GENERAL"


def classify_signal(nc: Dict[str, Any]) -> SignalType:
    """
    根据 normalized_connection 的 connection_name 和 source_port 判断信号类型。
    分类顺序：电源 > 控制 > 差分 > 射频 > DAC/ADC > 通用
    """
    sp = (nc.get("source_port", "") or "").upper()
    cn = (nc.get("connection_name", "") or "").upper()

    # 电源
    if any(k in cn for k in ["VDD", "PWR", "POWER", "VIN", "VOUT"]) or \
       any(k in sp for k in ["VDD", "VIN", "VOUT", "AVS", "EN_"]):
        return "POWER"

    # 数字控制：SPI/I2C/GPIO/UART
    if any(k in cn for k in ["SPI", "I2C", "IIC", "GPIO", "UART", "SCL", "SDA", "MOSI", "MISO", "SCK", "CS", "RESET"]):
        return "CTRL"

    # 差分
    if "_P" in sp or "_N" in sp or "_P" in cn or "_N" in cn:
        return "DIFF"

    # 射频（TX/RX/FB/CAL/EQU/PD + 开关/滤波器/balun）
    if any(k in cn for k in ["TX", "RX", "FB", "CAL", "EQU", "PD"]) or \
       any(k in sp for k in ["TX_", "RX_", "FB_", "RFIN", "RFOUT", "SW", "CAL_SW", "TXSW", "FB_SW", "HBF", "BALUN", "SP9T", "FEM"]):
        return "RF"

    # DAC
    if "DAC" in sp:
        return "DAC"

    # ADC
    if "ADC" in sp:
        return "ADC"

    return "GENERAL"


# ============================================================================
# ④ 网络名清洗（强制满足华为规范）
# ============================================================================

def clean_net_name(name: str) -> str:
    """
    将网络名强制清洗为华为规范格式：
    - 全大写 + 下划线分割
    - 中划线 - → 下划线 _
    - 数字开头 → 加前缀 N
    - 截断到 31 字符
    """
    if not name:
        return name
    name = name.replace("-", "_")
    name = re.sub(r"_+/", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    name = name.upper()
    if name and name[0].isdigit():
        name = "N" + name
    return name[:31]


# ============================================================================
# ⑤ 网络名生成核心
# ============================================================================

_BUS_MAP = {
    "SPI": "SPI",
    "I2C": "I2C",
    "IIC": "I2C",
    "GPIO": "GPIO",
    "UART": "UART",
    "SCL": "I2C",
    "SDA": "I2C",
    "MOSI": "SPI",
    "MISO": "SPI",
    "SCK": "SPI",
    "CS": "SPI",
    "RESET": "RST",
}


def generate_net_name(nc: Dict[str, Any], selected_pin: str = "") -> str:
    """
    生成华为规范网络名。

    参数
    ----
    nc : Dict[str, Any]
        normalized_connection 对象，至少包含：
        - connection_name: 连线名称
        - source_block_name / source_block_id: 源器件名称
        - target_block_name / target_block_id: 目的器件名称
        - source_port: 源端口名
        - direction: 方向（可选）
    selected_pin : str
        原理图 pin 脚名称（电源类网络会用到）

    返回
    ----
    str : 华为规范网络名（已清洗，满足全部约束）
    """
    conn_name = nc.get("connection_name", "") or ""

    # ===== 规则 1：连线名称优先 =====
    # connection_name 非空 且 不包含 'line'（不区分大小写）→ 直接使用连线名称
    if conn_name and "line" not in conn_name.lower():
        return clean_net_name(conn_name)

    # ===== 规则 2：按华为规范生成 =====
    src_block = nc.get("source_block_name", "") or nc.get("source_block_id", "")
    tgt_block = nc.get("target_block_name", "") or nc.get("target_block_id", "")
    src_port = nc.get("source_port", "") or ""

    src = abbreviate_block(src_block)
    tgt = abbreviate_block(tgt_block)
    sp = src_port.upper()
    cn = conn_name.upper()
    sig_type = classify_signal(nc)
    pol = extract_pol(src_port, conn_name)
    freq = extract_freq(conn_name)
    pnum = extract_port_num(src_port)
    ch = extract_ch(conn_name)

    # --- 电源网络（6部分）: PWR_电压_通道_负载_管脚 ---
    if sig_type == "POWER":
        voltage = extract_voltage(sp)
        pin_abbr = re.sub(r"[^A-Z0-9]", "_", (selected_pin or "").upper())[:8]
        parts = [p for p in ["PWR", voltage, ch, tgt, pin_abbr] if p]
        return clean_net_name("_".join(parts))

    # --- 数字控制（9部分）: 总线_编号_发送端_接收端_信号_频率_串联_电平_极性 ---
    if sig_type == "CTRL":
        bus = next((v for k, v in _BUS_MAP.items() if k in cn or k in sp), "SIG")
        sig_name = re.sub(r"[^A-Z0-9]", "_", src_port.upper())[:6]
        parts = [p for p in [bus, pnum, src, tgt, sig_name, freq, "", "", pol] if p]
        return clean_net_name("_".join(parts))

    # --- DAC ---
    if sig_type == "DAC":
        net = f"DAC{pnum or ch}_{src}_{tgt}_AFE{freq}{pol}"
        return clean_net_name(net)

    # --- ADC ---
    if sig_type == "ADC":
        net = f"ADC{pnum or ch}_{tgt}_FB_{src}{freq}{pol}"
        return clean_net_name(net)

    # --- 差分（RF 格式，末尾带 _P / _N）---
    if sig_type == "DIFF":
        f2 = "TX" if "TX" in cn or "TX" in sp else "RX" if "RX" in cn or "RX" in sp else src
        net = f"{f2}_{src}_{tgt}_CH{pnum or ch}{freq}{pol}"
        return clean_net_name(net)

    # --- 射频 / 通用：优先用去掉频率后缀的 connection_name（若含规范关键词）---
    base = re.sub(r"_\d+M\d*$", "", conn_name) if conn_name else ""
    base = re.sub(r"_\d+M$", "", base)
    VALID_FUNCS = ["TX", "RX", "FB", "CAL", "TRX", "PD", "EQU"]
    if base and len(base) <= 31 and any(f in base.upper() for f in VALID_FUNCS):
        return clean_net_name(base)

    # 按 RF 6 部分格式生成：类型_源端_目的端_通道_频率_极性
    func = next((v for k, v in {"TX": "TX", "RX": "RX", "FB": "FB", "CAL": "CAL"}.items()
                  if k in cn or k in sp), "SIG")
    if func in VALID_FUNCS:
        parts = [p for p in [func, src, tgt, f"CH{ch}" if ch else pnum, freq, pol] if p]
    else:
        parts = [p for p in [func, src, tgt, pnum, freq, pol] if p]
    return clean_net_name("_".join(parts))


# ============================================================================
# ⑥ CLI（用于单独测试）
# ============================================================================

def main():
    import json, sys
    from pathlib import Path

    if len(sys.argv) > 1:
        # 单独文件测试模式：python generate_net_name.py normalized.jsonl
        path = Path(sys.argv[1])
        if path.suffix == ".jsonl":
            with open(path, encoding="utf-8") as f:
                norm = {json.loads(l)["line_id"]: json.loads(l) for l in f}
            for nc in norm.values():
                net = generate_net_name(nc)
                print(f"{nc.get('line_id', ''):40s}  {net}")
        elif path.suffix == ".json":
            with open(path, encoding="utf-8") as f:
                nc = json.load(f)
            print(generate_net_name(nc))
        return

    # 内置测试用例
    test_cases = [
        # (nc, selected_pin, expected_pattern)
        ({"connection_name": "SW0007_SROC0_SP9T_FBV0_1M_LC18"}, "", "SW0007"),
        ({"connection_name": "LINE_1", "source_port": "DAC00", "source_block_name": "SROC", "target_block_name": "TXVGA"}, "", "DAC"),
        ({"connection_name": "VDD_5V0_PMU_PA0007_2431_VA_2A2"}, "", "PWR_5V0"),
        ({"connection_name": "HBF_PS0_CTRL_120V_BIT0_0001"}, "", "HBF_PS0_CTRL"),
        ({"connection_name": "line", "source_port": "SPI", "source_block_name": "SROC", "target_block_name": "AMC"}, "", "SPI"),
        ({"connection_name": "", "source_port": "TX_AFE0_00_N", "source_block_name": "SROC", "target_block_name": "TXVGA"}, "", "TX_SROC_TXVGA"),
    ]

    print("=== generate_net_name 测试 ===")
    all_pass = True
    for i, (nc, pin, pattern) in enumerate(test_cases, 1):
        result = generate_net_name(nc, pin)
        ok = pattern in result
        all_pass = all_pass and ok
        status = "✓" if ok else "✗"
        print(f"  [{status}] #{i}: {result}")
    print(f"\n  结果: {'全部通过' if all_pass else '存在失败'}")


if __name__ == "__main__":
    main()
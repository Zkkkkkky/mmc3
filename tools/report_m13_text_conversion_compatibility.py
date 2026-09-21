from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from dc_modifier.legacy_tools import TextConverterDialog
from fc_editor.dc_text import reference_dc_text_table
from fc_rom_editor_core import RomProject

REFERENCE_TABLE = (
    ROOT / "references" / "legacy_modifier" / "默认配置文件" / "码表.ini"
)
ACTIVE_TABLE = ROOT / "src" / "resources" / "default_config" / "码表.ini"
DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_REPORT = ROOT / "output" / "verification" / "m13-text-conversion.json"
REFERENCE_CONTROLS = (
    ROOT
    / "output"
    / "verification"
    / "legacy-ui-probe"
    / "controls"
    / "C04_文字转换.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _table_rows(path: Path) -> tuple[list[str], list[tuple[int, bytes, str, str]]]:
    lines = path.read_text(encoding="gbk").splitlines()
    rows: list[tuple[int, bytes, str, str]] = []
    for line_number, line in enumerate(lines, 1):
        parts = line.split("=", 2)
        if len(parts) != 3:
            raise ValueError(f"码表第 {line_number} 行不是地址=代码=文字格式。")
        address, code_text, value = parts
        if code_text and value:
            rows.append((line_number, bytes.fromhex(code_text), value, address))
    return lines, rows


def _expected_canonical_codes(
    rows: Iterable[tuple[int, bytes, str, str]],
) -> dict[str, bytes]:
    candidates: dict[str, list[tuple[int, bytes]]] = defaultdict(list)
    for line_number, code, value, _address in rows:
        candidates[value].append((line_number, code))
    return {
        value: min(items, key=lambda item: (len(item[1]), item[0]))[1]
        for value, items in candidates.items()
    }


def analyze(rom_path: Path = DEFAULT_ROM) -> dict[str, object]:
    reference_lines, reference_rows = _table_rows(REFERENCE_TABLE)
    active_lines, active_rows = _table_rows(ACTIVE_TABLE)
    table = reference_dc_text_table()
    by_value: dict[str, list[bytes]] = defaultdict(list)
    for _line_number, code, value, _address in reference_rows:
        by_value[value].append(code)
    canonical = _expected_canonical_codes(reference_rows)

    controls = json.loads(REFERENCE_CONTROLS.read_text(encoding="utf-8"))
    reference_children = controls["tree"]["children"]
    reference_ids = sorted(child["ctrl_id"] for child in reference_children)

    application = QApplication.instance() or QApplication([])
    project = RomProject.load(rom_path)
    before = bytes(project.working)
    project.replace_font_character_overrides({bytes.fromhex("BAE3"): "龘"})
    dialog = TextConverterDialog(project=project)
    dialog.show()
    application.processEvents()
    product_direct_children = [
        widget
        for widget in dialog.findChildren(QWidget)
        if widget.parent() is dialog and widget.isVisible()
    ]

    sample_text = "机体@\\】【龘"
    dialog.text_edit.setPlainText(sample_text)
    dialog.encode_text()
    sample_code = dialog.code_edit.toPlainText()
    dialog.text_edit.clear()
    dialog.decode_code()
    sample_roundtrip = dialog.text_edit.toPlainText()

    previous_code = dialog.code_edit.toPlainText()
    dialog.text_edit.setPlainText("🙂")
    dialog.encode_text()
    unknown_rejected = (
        dialog.code_edit.toPlainText() == previous_code
        and dialog.last_status.startswith("转换失败：")
    )
    previous_text = dialog.text_edit.toPlainText()
    dialog.code_edit.setPlainText("123")
    dialog.decode_code()
    invalid_hex_rejected = (
        dialog.text_edit.toPlainText() == previous_text
        and dialog.last_status.startswith("转换失败：")
    )

    dialog.text_edit.clear()
    dialog.encode_text()
    empty_encode = dialog.code_edit.toPlainText()
    dialog.code_edit.clear()
    dialog.decode_code()
    empty_decode = dialog.text_edit.toPlainText()

    long_text = "机" * 1024
    dialog.text_edit.setPlainText(long_text)
    dialog.encode_text()
    long_code_size = len(TextConverterDialog.parse_code(dialog.code_edit.toPlainText()))
    dialog.text_edit.clear()
    dialog.decode_code()
    long_roundtrip = dialog.text_edit.toPlainText()
    dialog.close()
    application.processEvents()

    expected_sample_raw = dialog.text_table.encode(sample_text)
    checks = {
        "reference_and_active_table_hash_match": (
            _sha256(REFERENCE_TABLE) == _sha256(ACTIVE_TABLE)
        ),
        "table_shape_is_3328_lines_2713_nonempty": (
            len(reference_lines) == len(active_lines) == 3328
            and len(reference_rows) == len(active_rows) == 2713
        ),
        "all_reference_codes_are_unique": (
            len({row[1] for row in reference_rows}) == len(reference_rows)
        ),
        "all_reference_rows_decode_exactly": (
            len(table.byte_to_text) == len(reference_rows)
            and all(table.byte_to_text.get(code) == value for _, code, value, _ in reference_rows)
        ),
        "duplicate_values_use_first_shortest_reference_code": all(
            table.encode(value) == code for value, code in canonical.items()
        ),
        "legacy_control_tokens_are_exact": (
            table.decode(bytes.fromhex("F0 F1 F2 F5 F6 F9")) == "&@\\*】【"
        ),
        "reference_visible_control_inventory_is_exact": (
            controls["tree"]["class"] == "WTWindow"
            and len(reference_children) == 6
            and reference_ids == [100, 110, 120, 130, 140, 150]
        ),
        "product_visible_control_inventory_matches_reference": (
            len(product_direct_children) == 6
            and sorted(type(widget).__name__ for widget in product_direct_children)
            == [
                "QLabel",
                "QLabel",
                "QPlainTextEdit",
                "QPlainTextEdit",
                "QPushButton",
                "QPushButton",
            ]
            and not dialog.text_edit.placeholderText()
            and not dialog.code_edit.placeholderText()
        ),
        "product_sample_roundtrip_and_format": (
            sample_code == expected_sample_raw.hex(" ").upper()
            and sample_roundtrip == sample_text
        ),
        "product_unknown_character_is_atomic_rejection": unknown_rejected,
        "product_invalid_hex_is_atomic_rejection": invalid_hex_rejected,
        "product_empty_inputs_are_empty_outputs": empty_encode == empty_decode == "",
        "product_1024_character_roundtrip": (
            long_code_size == 2048 and long_roundtrip == long_text
        ),
        "project_local_character_roundtrip": (
            sample_code.endswith("BA E3") and sample_roundtrip == sample_text
        ),
        "conversion_does_not_modify_rom": bytes(project.working) == before,
    }
    duplicate_groups = [codes for codes in by_value.values() if len(codes) > 1]
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "reference_table": {
            "path": REFERENCE_TABLE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(REFERENCE_TABLE),
            "line_count": len(reference_lines),
            "nonempty_mapping_count": len(reference_rows),
            "unique_code_count": len({row[1] for row in reference_rows}),
            "unique_value_count": len(by_value),
            "duplicate_value_groups": len(duplicate_groups),
            "duplicate_alias_count": sum(len(codes) - 1 for codes in duplicate_groups),
            "maximum_aliases_for_one_value": max(map(len, duplicate_groups)),
        },
        "active_table": {
            "path": ACTIVE_TABLE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(ACTIVE_TABLE),
        },
        "reference_ui": {
            "path": REFERENCE_CONTROLS.relative_to(ROOT).as_posix(),
            "window_class": controls["tree"]["class"],
            "visible_child_count": len(reference_children),
            "control_ids": reference_ids,
        },
        "product": {
            "visible_direct_child_count": len(product_direct_children),
            "initial_size": [dialog.width(), dialog.height()],
            "sample_text": sample_text,
            "sample_code": sample_code,
            "long_text_characters": len(long_text),
            "long_text_encoded_bytes": long_code_size,
            "rom_sha256_before": hashlib.sha256(before).hexdigest().upper(),
            "rom_sha256_after": hashlib.sha256(bytes(project.working)).hexdigest().upper(),
        },
        "checks": checks,
        "limitations": [
            "参考程序当前停留在提权模态字库子窗；Computer Use 可读取截图但无法激活该子窗，因此本报告没有把参考按钮动态输出记为已通过。",
            "大写/分隔符、未知字符、非法十六进制、空串和超长输入仍需在参考程序中逐项重放；当前报告只证明产品行为确定、原子且不改 ROM。",
            "实现侧报告和自动测试不等于用户验收；M13 签收表必须由用户明确填写。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 M13 文字转换码表、界面结构和只读边界。")
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    arguments = parser.parse_args()
    report = analyze(arguments.rom)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

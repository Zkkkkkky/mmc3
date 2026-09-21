from __future__ import annotations

import struct
import unittest

from tools.report_legacy_pe_dialogs import DialogParseError, parse_dialog_template


def _utf16(value: str) -> bytes:
    return value.encode("utf-16le") + b"\0\0"


def _align4(payload: bytearray) -> None:
    payload.extend(b"\0" * ((-len(payload)) % 4))


class LegacyPeDialogTests(unittest.TestCase):
    def test_parses_standard_dialog_and_button(self) -> None:
        payload = bytearray(
            struct.pack("<LLHhhhh", 0, 0, 1, 1, 2, 120, 60)
        )
        payload.extend(b"\0\0")  # no menu
        payload.extend(b"\0\0")  # default dialog class
        payload.extend(_utf16("技能"))
        _align4(payload)
        payload.extend(struct.pack("<LLhhhhH", 0x50010000, 0, 4, 5, 40, 14, 2600))
        payload.extend(struct.pack("<HH", 0xFFFF, 0x0080))
        payload.extend(_utf16("确定"))
        payload.extend(b"\0\0")

        result = parse_dialog_template(bytes(payload))

        self.assertFalse(result["extended"])
        self.assertEqual(result["title"], "技能")
        self.assertEqual(result["declared_control_count"], 1)
        self.assertEqual(result["controls"][0]["control_id"], 2600)
        self.assertEqual(result["controls"][0]["class"], "Button")
        self.assertEqual(result["controls"][0]["title"], "确定")

    def test_rejects_truncated_template(self) -> None:
        with self.assertRaises(DialogParseError):
            parse_dialog_template(b"short")


if __name__ == "__main__":
    unittest.main()

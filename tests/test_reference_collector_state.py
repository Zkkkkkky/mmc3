from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.research import collect_m03_all_reference_fields as m03
from tools.research import collect_m04_all_reference_fields as m04
from tools.research import collect_m14_all_reference_fields as m14


class ReferenceCollectorStateTests(unittest.TestCase):
    def test_all_collectors_replace_complete_state_json_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            work = root / "work.nes"
            work.write_bytes(b"reference-state-probe")

            m03_state = root / "m03-state.json"
            with patch.object(m03, "STATE", m03_state), patch.object(m03, "WORK", work):
                m03.state(7, 1380)
            self.assertEqual(
                json.loads(m03_state.read_text(encoding="utf-8")),
                {
                    "completed": 7,
                    "total": 1380,
                    "current_sha256": m03.sha(work.read_bytes()),
                },
            )
            self.assertFalse((root / "m03-state.json.tmp").exists())

            m04_state = root / "m04-state.json"
            with patch.object(m04, "STATE", m04_state):
                m04.state(8, 103)
            self.assertEqual(
                json.loads(m04_state.read_text(encoding="utf-8")),
                {"completed": 8, "total": 103},
            )
            self.assertFalse((root / "m04-state.json.tmp").exists())

            m14_state = root / "m14-state.json"
            with patch.object(m14, "STATE", m14_state), patch.object(m14, "WORK", work):
                m14.save_state(9, 3217)
            self.assertEqual(
                json.loads(m14_state.read_text(encoding="utf-8")),
                {
                    "completed": 9,
                    "total": 3217,
                    "current_sha256": m14.sha(work.read_bytes()),
                },
            )
            self.assertFalse((root / "m14-state.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()

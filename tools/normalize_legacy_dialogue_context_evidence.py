"""Normalize volatile dialogue-button text in validated legacy UI evidence.

The three dialogue buttons expose the dialogue itself as their window text.
That text changes with the selected ROM record, while class/id/index and the
popup command remain the same control identity.  This tool never invents an
execution: it emits aliases only when the validated 44-action run contains the
exact control/command observation and the discovery snapshot contains the
matching origin.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research.legacy_ui_probe import stable_context_interaction_id


REPO = Path(__file__).resolve().parents[1]
RAW = (
    REPO / "output/verification/legacy-ui-probe-recursive-dbremainingcontext-01"
    / "interaction-discovery/database-remaining-context-actions.json"
)
DISCOVERY = (
    REPO / "output/verification/legacy-ui-probe-recursive-dbctx-06"
    / "interaction-discovery/database-context-menus.json"
)
OUT = (
    REPO / "output/verification/legacy-ui-probe-recursive-dbcontextdialoguenormalization-01"
    / "interaction-discovery/database-dialogue-context-normalization.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    discovery = json.loads(DISCOVERY.read_text(encoding="utf-8"))
    targets = {1420: 20, 1430: 19, 1440: 18}
    observations = [
        item
        for item in raw.get("observations", [])
        if int(item.get("control_id") or 0) in targets
        and int(item.get("command_id") or 0) in (20029, 20030)
    ]
    records = []
    mappings = []
    for observed in observations:
        control_id = int(observed["control_id"])
        command_id = int(observed["command_id"])
        control_index = targets[control_id]
        origin_row = next(
            (
                row
                for row in discovery.get("records", [])
                if row.get("state") == "人物修改"
                and row.get("class") == "Button"
                and int(row.get("control_id") or 0) == control_id
                and int(row.get("control_index") or 0) == control_index
                and any(
                    int(menu_item.get("id") or -1) == command_id
                    for menu in row.get("menus", [])
                    for menu_item in menu
                    if isinstance(menu_item, dict)
                )
            ),
            None,
        )
        if origin_row is None:
            continue
        caption = str(observed.get("caption", "")).strip()
        origin = (
            "人物修改", "Button", control_id, control_index,
            str(origin_row.get("text", "")),
        )
        action_id = stable_context_interaction_id(origin, (caption,), command_id)
        records.append(
            {
                "action_id": action_id,
                "status": "passed",
                "result": (
                    "已由 44 项真实执行批次验证；仅把随 ROM 记录变化的对话正文"
                    "归一化为发现快照中的同一 Button class/id/index 身份。"
                ),
            }
        )
        mappings.append(
            {
                "control_id": control_id,
                "control_index": control_index,
                "command_id": command_id,
                "caption": caption,
                "discovery_text": origin[4],
                "executed_descendants": observed.get("descendants", []),
                "action_id": action_id,
            }
        )
    unique = {item["action_id"]: item for item in records}
    validated = bool(raw.get("validated")) and len(unique) == 6
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "validated": validated,
                "normalization": "volatile dialogue text excluded from control identity",
                "source_evidence": RAW.relative_to(REPO).as_posix(),
                "source_evidence_sha256": sha256(RAW),
                "source_discovery": DISCOVERY.relative_to(REPO).as_posix(),
                "source_discovery_sha256": sha256(DISCOVERY),
                "execution_record_count": len(unique),
                "mappings": mappings,
                "execution_records": list(unique.values()) if validated else [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not validated:
        raise RuntimeError(f"dialogue normalization did not validate: {len(unique)}/6")
    print(f"dialogue context normalization: {len(unique)}/6 -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build a machine-readable inventory from preserved reference UI dumps.

The legacy probe deliberately keeps every raw JSON snapshot.  This report
turns those snapshots into a stable index without pretending that repeated or
hidden controls are separate editable ROM fields.  The field denominator is
maintained independently by the golden pipeline.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


INTERACTIVE_CLASSES = {
    "Button",
    "ComboBox",
    "Edit",
    "ListBox",
    "ScrollBar",
    "SysListView32",
    "msctls_updown32",
}
DIAGNOSTIC_PREFIXES = ("CLEAN", "DIAG", "TABPOP")
ROM_TITLE_SUFFIX_RE = re.compile(r"^(SRW2扩容版修改器V1\.0)(?:[:：].*)?$")


def normalize_window_title(title: str) -> str:
    """Remove the loaded-ROM path from the main-window identity."""

    match = ROM_TITLE_SUFFIX_RE.match(title)
    return match.group(1) if match else title


def control_signature(snapshot: dict[str, Any], control: dict[str, Any]) -> tuple[Any, ...]:
    """Return a stable identity for one enumerated Win32 control.

    A control can occur in many tab/page snapshots.  The title, class, numeric
    ID and tree path together preserve ID collisions while coalescing the same
    HWND role across repeated captures.  Text, visibility, and enabled state
    are deliberately observations rather than identity components because
    edit/combo contents change with the selected record.
    """

    return (
        normalize_window_title(snapshot["title"]),
        control["class"],
        control["control_id"],
        tuple(control["tree_path"]),
    )


def flatten_tree(node: dict[str, Any], path: tuple[int, ...] = ()) -> Iterable[dict[str, Any]]:
    current = dict(node)
    current.pop("children", None)
    current["tree_path"] = list(path)
    yield current
    for index, child in enumerate(node.get("children", [])):
        yield from flatten_tree(child, path + (index,))


def load_snapshots(controls_dir: Path) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for path in sorted(controls_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("tree"), dict):
            continue
        tag = str(payload.get("tag") or path.stem)
        controls = list(flatten_tree(payload["tree"]))
        interactive = [
            control
            for control in controls
            if control.get("class") in INTERACTIVE_CLASSES
        ]
        snapshots.append(
            {
                "tag": tag,
                "source": path.as_posix(),
                "title": str(payload.get("title", "")),
                "class": str(payload.get("class", "")),
                "diagnostic": tag.startswith(DIAGNOSTIC_PREFIXES),
                "control_count": len(controls),
                "interactive_count": len(interactive),
                "interactive_controls": [
                    {
                        "class": str(control.get("class", "")),
                        "control_id": int(control.get("ctrl_id") or 0),
                        "text": str(control.get("text", "")),
                        "visible": bool(control.get("visible", False)),
                        "enabled": bool(control.get("enabled", False)),
                        "tree_path": control["tree_path"],
                    }
                    for control in interactive
                ],
            }
        )
    return snapshots


def build_report(controls_dir: Path) -> dict[str, Any]:
    snapshots = load_snapshots(controls_dir)
    canonical = [item for item in snapshots if not item["diagnostic"]]
    class_counts: Counter[str] = Counter()
    visible_class_counts: Counter[str] = Counter()
    signatures: dict[tuple[Any, ...], dict[str, Any]] = {}
    for snapshot in canonical:
        for control in snapshot["interactive_controls"]:
            class_counts[control["class"]] += 1
            if control["visible"]:
                visible_class_counts[control["class"]] += 1
            signature = control_signature(snapshot, control)
            entry = signatures.setdefault(
                signature,
                {
                    "window_title": signature[0],
                    "class": control["class"],
                    "control_id": control["control_id"],
                    "tree_path": control["tree_path"],
                    "observed_texts": [],
                    "observed_visible": False,
                    "observed_enabled": False,
                    "snapshot_tags": [],
                },
            )
            entry["observed_visible"] |= control["visible"]
            entry["observed_enabled"] |= control["enabled"]
            if control["text"] not in entry["observed_texts"]:
                entry["observed_texts"].append(control["text"])
            entry["snapshot_tags"].append(snapshot["tag"])
    unique_controls = sorted(
        signatures.values(),
        key=lambda item: (
            item["window_title"],
            item["class"],
            item["control_id"],
            item["tree_path"],
        ),
    )
    return {
        "schema_version": 1,
        "source_directory": controls_dir.as_posix(),
        "scope_note": (
            "控件枚举统计窗口/控件证据；同一控件会因页签、显隐和复查多次出现，"
            "不得直接作为黄金对照字段分母。"
        ),
        "counts": {
            "snapshot_files": len(snapshots),
            "canonical_snapshots": len(canonical),
            "diagnostic_snapshots": len(snapshots) - len(canonical),
            "canonical_control_occurrences": sum(
                item["control_count"] for item in canonical
            ),
            "canonical_interactive_occurrences": sum(
                item["interactive_count"] for item in canonical
            ),
            "unique_window_titles": len(
                {normalize_window_title(item["title"]) for item in canonical}
            ),
            "unique_interactive_signatures": len(unique_controls),
            "unique_visible_interactive_signatures": sum(
                1 for item in unique_controls if item["observed_visible"]
            ),
        },
        "interactive_class_occurrences": dict(sorted(class_counts.items())),
        "visible_interactive_class_occurrences": dict(
            sorted(visible_class_counts.items())
        ),
        "unique_interactive_controls": unique_controls,
        "snapshots": snapshots,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# 参考版控件枚举索引",
        "",
        f"- 原始窗口转储：{counts['snapshot_files']}",
        f"- 正式证据窗口：{counts['canonical_snapshots']}",
        f"- 诊断/清理窗口：{counts['diagnostic_snapshots']}",
        f"- 正式证据控件出现次数：{counts['canonical_control_occurrences']}",
        f"- 正式证据交互控件出现次数：{counts['canonical_interactive_occurrences']}",
        f"- 去重窗口标题：{counts['unique_window_titles']}",
        f"- 去重交互控件签名：{counts['unique_interactive_signatures']}",
        f"- 曾可见的去重交互控件签名：{counts['unique_visible_interactive_signatures']}",
        "",
        f"> {report['scope_note']}",
        "",
        "## 交互控件类型",
        "",
        "| 控件类 | 全部出现次数 | 可见出现次数 |",
        "|---|---:|---:|",
    ]
    visible = report["visible_interactive_class_occurrences"]
    for class_name, count in report["interactive_class_occurrences"].items():
        lines.append(f"| `{class_name}` | {count} | {visible.get(class_name, 0)} |")
    lines.extend(
        [
            "",
            "## 窗口转储",
            "",
            "| 标签 | 标题 | 控件 | 交互控件 | 口径 |",
            "|---|---|---:|---:|---|",
        ]
    )
    for snapshot in report["snapshots"]:
        title = snapshot["title"].replace("|", "\\|").replace("\n", " ")
        scope = "诊断" if snapshot["diagnostic"] else "正式证据"
        lines.append(
            f"| `{snapshot['tag']}` | {title} | {snapshot['control_count']} | "
            f"{snapshot['interactive_count']} | {scope} |"
        )
    lines.extend(
        [
            "",
            "## 去重交互控件目录",
            "",
            "| 窗口 | 类 | ID | 文本 | 曾可见 | 曾启用 | 快照数 |",
            "|---|---|---:|---|---|---|---:|",
        ]
    )
    for control in report["unique_interactive_controls"]:
        values = [
            control["window_title"],
            f"`{control['class']}`",
            str(control["control_id"]),
            " / ".join(control["observed_texts"][:3])
            + (" / …" if len(control["observed_texts"]) > 3 else ""),
            "是" if control["observed_visible"] else "否",
            "是" if control["observed_enabled"] else "否",
            str(len(control["snapshot_tags"])),
        ]
        values = [value.replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--controls-dir",
        default="output/verification/legacy-ui-probe/controls",
    )
    parser.add_argument(
        "--json-out",
        default="output/reports/legacy-control-inventory.json",
    )
    parser.add_argument(
        "--markdown-out",
        default="output/reports/legacy-control-inventory.md",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    controls_dir = (repo / args.controls_dir).resolve()
    report = build_report(controls_dir)
    if not report["counts"]["snapshot_files"]:
        raise SystemExit(f"no control snapshots found: {controls_dir}")
    json_out = repo / args.json_out
    markdown_out = repo / args.markdown_out
    json_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_out.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    counts = report["counts"]
    print(
        "reference UI inventory: "
        f"{counts['snapshot_files']} snapshots, "
        f"{counts['canonical_interactive_occurrences']} interactive occurrences"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

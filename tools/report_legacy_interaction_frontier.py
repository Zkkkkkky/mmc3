"""Build the recursive interaction frontier for the legacy modifier.

The older control inventory counts HWNDs.  It is useful evidence, but an HWND
is not a function: one list can expose selection, double-click and context-menu
behaviour, and a custom-drawn panel may not have a standard control class at
all.  This report converts every preserved reference snapshot into explicit
interaction probes.  A probe remains ``pending`` until a separate execution
record names its stable ``action_id`` and supplies an observed result.

This tool is deliberately read-only.  It does not click the reference program
and it never treats generated candidates as completed evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


STANDARD_ACTIONS: dict[str, tuple[str, ...]] = {
    "Button": ("left_click", "keyboard_activate", "right_click"),
    "ComboBox": ("open_dropdown", "select_each_item", "keyboard_cycle", "right_click"),
    "Edit": ("focus", "replace_value", "boundary_values", "right_click", "keyboard_shortcuts"),
    "ListBox": ("select_each_item", "double_click_each_item", "right_click_each_item", "keyboard_navigation"),
    "SysListView32": ("select_each_item", "double_click_each_item", "right_click_each_item", "keyboard_navigation"),
    "ScrollBar": ("line_step", "page_step", "drag_thumb"),
    "msctls_updown32": ("increment", "decrement", "boundary_values"),
}

CUSTOM_ACTIONS: dict[str, tuple[str, ...]] = {
    "_EL_DrawPanel": ("left_click_grid", "double_click_grid", "right_click_grid", "drag_grid"),
    "_EL_PicBox": ("left_click_regions", "double_click_regions", "right_click_regions", "drag_regions"),
    "AfxWnd42s": ("left_click_regions", "double_click_regions", "right_click_regions", "drag_regions"),
    "CPageControl": ("select_each_tab", "keyboard_tab_cycle", "right_click_tabs"),
}


def _normalized_window_title(title: str) -> str:
    """Collapse data-bearing title suffixes that do not identify a function.

    The legacy main window appends the currently opened ROM path.  Treating
    that path as part of the window identity makes every isolated golden run
    manufacture another copy of the same 143 actions, so the denominator
    grows merely because evidence was collected.  Record-state differences
    remain represented by observed control states and their snapshots.
    """

    prefix = "SRW2扩容版修改器V1.0："
    if title.startswith(prefix):
        return prefix + "<ROM>"
    return title


def _custom_actions_for_control(
    title: str, class_name: str, control_id: int, visible: bool
) -> tuple[str, ...] | None:
    """Return interaction probes for legacy owner-drawn controls.

    Most owner-drawn panels keep a stable class name.  The movement
    simulator is the exception: its real canvas is an MFC-generated ``Afx``
    class whose suffix changes with the runtime, while the hidden template
    panel still reports ``_EL_DrawPanel``.  Keying this one surface by dialog
    title and control id prevents us from accidentally treating every generic
    MFC pane as a canvas, and makes the visible ID 100 surface part of the
    functional denominator.
    """

    # In this one dialog ID 280 is an invisible Easy Language design-time
    # template.  The live input surface is the visible Afx/ID 100 sibling.
    # Counting both would create four permanently unreachable requirements.
    if (
        title == "运行规律模拟"
        and class_name == "_EL_DrawPanel"
        and control_id == 280
        and not visible
    ):
        return ()
    actions = CUSTOM_ACTIONS.get(class_name)
    if actions:
        return actions
    if (
        title == "运行规律模拟"
        and control_id == 100
        and visible
        and class_name.startswith("Afx:")
    ):
        return (
            "left_click_regions",
            "double_click_regions",
            "right_click_regions",
            "drag_regions",
        )
    return None


def _flatten(node: dict[str, Any], path: tuple[int, ...] = ()) -> Iterable[dict[str, Any]]:
    current = dict(node)
    current.pop("children", None)
    current["tree_path"] = list(path)
    yield current
    for index, child in enumerate(node.get("children", [])):
        if isinstance(child, dict):
            yield from _flatten(child, path + (index,))


def _stable_id(parts: Iterable[Any]) -> str:
    raw = json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _canonical_control_identity(
    title: str, class_name: str, control_id: int
) -> tuple[str, int]:
    """Collapse runtime aliases that the legacy main page recreates.

    The Easy-Language main page publishes the same semantic controls under
    different numeric IDs depending on which hidden page was constructed
    first.  MFC also embeds its image base in generated Afx class names.
    These variations are HWND implementation details, not extra user-facing
    functions.  Canonical IDs below are the IDs exposed by the current golden
    reference process after loading a ROM.
    """

    if title == "SRW2扩容版修改器V1.0：<ROM>":
        if class_name == "Jy_iext1_05" and control_id in {
            400, 410, 420, 450, 470, 600, 610, 620, 650,
        }:
            class_name = "Afx:400000:b:10003:900015:0"
            control_id = {600: 610, 610: 620, 620: 630, 650: 670}.get(
                control_id, control_id
            )
        if class_name.startswith("Afx:") and control_id in (130, 150, 170):
            suffix = class_name.split(":", 2)[2] if class_name.count(":") >= 2 else ""
            class_name = f"Afx:400000:{suffix}" if suffix else "Afx:400000"
        if class_name == "ComboBox" and control_id == 660:
            control_id = 680
        elif class_name == "Button" and control_id == 640:
            control_id = 660
    return class_name, control_id


def _snapshot_files(root: Path) -> list[Path]:
    paths = list(root.glob("legacy-ui-probe*/controls/*.json"))
    return sorted({path.resolve() for path in paths})


def _interaction_discovery_files(root: Path) -> list[Path]:
    paths = list(root.glob("legacy-ui-probe*/interaction-discovery/*.json"))
    return sorted({path.resolve() for path in paths})


def _session_discovery_is_valid(snapshot_path: Path) -> bool:
    """Reject controls captured by failed command-recursion experiments."""

    discovery = snapshot_path.parent.parent / "interaction-discovery"
    guarded = (
        discovery / "database-command-descendants.json",
        discovery / "weapon-instruction-descendants.json",
    )
    existing = [path for path in guarded if path.exists()]
    if not existing:
        return True
    for path in existing:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or payload.get("validated") is not True:
            return False
    return True


def _load_execution_records(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", []) if isinstance(payload, dict) else []
    return {
        str(item["action_id"]): item
        for item in records
        if isinstance(item, dict) and item.get("action_id")
    }


def build_report(root: Path, execution_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    if execution_path is not None:
        execution_path = execution_path.resolve()
    records = _load_execution_records(execution_path)
    actions: dict[str, dict[str, Any]] = {}
    observed_states: dict[tuple[Any, ...], dict[str, set[Any]]] = defaultdict(
        lambda: {"visible": set(), "enabled": set(), "texts": set(), "snapshots": set()}
    )
    snapshot_count = 0
    menu_files = 0
    discovery_files = 0
    rejected_discovery_files = 0
    embedded_execution_records = 0
    platform_context_origins: set[tuple[Any, ...]] = set()

    # A child HWND's sibling index is not a semantic identity.  The legacy
    # framework can enumerate the same control at a different tree path after
    # recreating a page, even though its non-zero dialog ID remains unique in
    # that window.  Canonicalise only identities that occur at most once per
    # snapshot.  Reused IDs stay path-sensitive, so genuinely distinct
    # controls are never merged.
    canonical_control_paths: dict[tuple[str, str, int], tuple[int, ...]] = {}
    ambiguous_control_identities: set[tuple[str, str, int]] = set()
    for snapshot_path in _snapshot_files(root):
        if not _session_discovery_is_valid(snapshot_path):
            continue
        try:
            snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(snapshot_payload, dict) or not isinstance(
            snapshot_payload.get("tree"), dict
        ):
            continue
        snapshot_title = _normalized_window_title(
            str(snapshot_payload.get("title", ""))
        )
        snapshot_controls = list(_flatten(snapshot_payload["tree"]))
        identity_counts = Counter(
            (snapshot_title, *_canonical_control_identity(
                snapshot_title,
                str(control.get("class", "")),
                int(control.get("ctrl_id") or 0),
            ))
            for control in snapshot_controls
            if int(control.get("ctrl_id") or 0) != 0
        )
        ambiguous_control_identities.update(
            identity for identity, count in identity_counts.items() if count > 1
        )
        for control in snapshot_controls:
            control_id = int(control.get("ctrl_id") or 0)
            if control_id == 0:
                continue
            canonical_class, canonical_id = _canonical_control_identity(
                snapshot_title, str(control.get("class", "")), control_id,
            )
            identity = (snapshot_title, canonical_class, canonical_id)
            canonical_control_paths.setdefault(
                identity, tuple(control.get("tree_path", ()))
            )
    for identity in ambiguous_control_identities:
        canonical_control_paths.pop(identity, None)

    for path in _snapshot_files(root):
        if not _session_discovery_is_valid(path):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        relative = path.relative_to(root.parent).as_posix()
        if isinstance(payload, list):
            menu_files += 1

            def walk_menu(items: list[dict[str, Any]], trail: tuple[str, ...] = ()) -> None:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("text", "")).strip()
                    current = trail + ((text or "<separator>"),)
                    command_id = item.get("id")
                    children = item.get("items")
                    if command_id is not None and text:
                        action_id = _stable_id(("menu", current, command_id, "activate"))
                        entry = {
                            "action_id": action_id,
                            "window": "menu",
                            "control_class": "MenuItem",
                            "control_id": command_id,
                            "tree_path": list(current),
                            "observed_text": text,
                            "action": "activate",
                            "source_snapshots": [relative],
                        }
                        actions.setdefault(action_id, entry)
                    if isinstance(children, list):
                        walk_menu(children, current)

            walk_menu(payload)
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("tree"), dict):
            continue
        snapshot_count += 1
        title = _normalized_window_title(str(payload.get("title", "")))
        tag = str(payload.get("tag", path.stem))
        for control in _flatten(payload["tree"]):
            class_name = str(control.get("class", ""))
            control_id = int(control.get("ctrl_id") or 0)
            class_name, control_id = _canonical_control_identity(
                title, class_name, control_id,
            )
            observed_tree_path = tuple(control.get("tree_path", ()))
            identity = (title, class_name, control_id)
            tree_path = canonical_control_paths.get(identity, observed_tree_path)
            state_key = (title, class_name, control_id, tree_path)
            state = observed_states[state_key]
            state["visible"].add(bool(control.get("visible", False)))
            state["enabled"].add(bool(control.get("enabled", False)))
            state["texts"].add(str(control.get("text", "")))
            state["snapshots"].add(tag)
            state.setdefault("tree_paths", set()).add(observed_tree_path)
            # MFC/Easy-Language templates retain hidden or disabled child
            # HWNDs.  Keep them for state-transition discovery, but do not
            # manufacture click/key actions until a snapshot proves the same
            # stable control is both visible and enabled.
            if not bool(control.get("visible", False)) or not bool(
                control.get("enabled", False)
            ):
                continue
            action_names = STANDARD_ACTIONS.get(class_name) or _custom_actions_for_control(
                title,
                class_name,
                control_id,
                bool(control.get("visible", False)),
            )
            if not action_names:
                continue
            for action_name in action_names:
                action_id = _stable_id(
                    (title, class_name, control_id, tree_path, action_name)
                )
                entry = actions.setdefault(
                    action_id,
                    {
                        "action_id": action_id,
                        "window": title,
                        "control_class": class_name,
                        "control_id": control_id,
                        "tree_path": list(tree_path),
                        "observed_text": str(control.get("text", "")),
                        "action": action_name,
                        "source_snapshots": [],
                        "source_tree_paths": [],
                    },
                )
                if relative not in entry["source_snapshots"]:
                    entry["source_snapshots"].append(relative)
                observed_path_list = list(observed_tree_path)
                if observed_path_list not in entry["source_tree_paths"]:
                    entry["source_tree_paths"].append(observed_path_list)

    for path in _interaction_discovery_files(root):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        embedded = payload.get("execution_records")
        if payload.get("validated") is True and isinstance(embedded, list):
            for item in embedded:
                if not isinstance(item, dict) or not item.get("action_id"):
                    continue
                records.setdefault(str(item["action_id"]), item)
                embedded_execution_records += 1
        guarded_name = path.name in {
            "database-command-descendants.json",
            "weapon-instruction-descendants.json",
        }
        if guarded_name and payload.get("validated") is not True:
            rejected_discovery_files += 1
            continue
        tabs = payload.get("tabs")
        if isinstance(tabs, list) and tabs and not all(
            item.get("phase2_signature_match") is True
            for item in tabs
            if isinstance(item, dict)
        ):
            rejected_discovery_files += 1
            continue
        records_payload = payload.get("records")
        if not isinstance(records_payload, list):
            continue
        discovery_files += 1
        relative = path.relative_to(root.parent).as_posix()
        discovery_probes: list[dict[str, Any]] = []
        for record in records_payload:
            if not isinstance(record, dict):
                continue
            nested = record.get("context_probes")
            if isinstance(nested, list):
                discovery_probes.extend(
                    item for item in nested if isinstance(item, dict)
                )
            else:
                discovery_probes.append(record)
        for probe in discovery_probes:
            if not isinstance(probe, dict) or not probe.get("menus"):
                continue
            origin = (
                str(probe.get("state", "")),
                str(probe.get("class", "")),
                int(probe.get("control_id") or 0),
                int(probe.get("control_index") or 0),
                str(probe.get("text", "")),
            )

            def walk_context_menu(
                items: list[dict[str, Any]],
                trail: tuple[str, ...] = (),
                *,
                platform_menu: bool = False,
            ) -> None:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_text = str(item.get("text", "")).strip()
                    current = trail + ((item_text or "<separator>"),)
                    command_id = item.get("id")
                    children = item.get("items")
                    if command_id is not None and item_text:
                        action_id = _stable_id(
                            ("context_menu", origin, current, command_id, "activate")
                        )
                        entry = actions.setdefault(
                            action_id,
                            {
                                "action_id": action_id,
                                "window": origin[0],
                                "control_class": "ContextMenuItem",
                                "control_id": command_id,
                                "tree_path": [origin[1], origin[2], origin[3], *current],
                                "observed_text": item_text,
                                "action": (
                                    "activate_platform_context_command"
                                    if platform_menu
                                    else "activate_context_command"
                                ),
                                "context_kind": (
                                    "platform" if platform_menu else "product"
                                ),
                                "context_origin": {
                                    "control_class": origin[1],
                                    "control_id": origin[2],
                                    "control_index": origin[3],
                                    "observed_text": origin[4],
                                },
                                "source_snapshots": [],
                            },
                        )
                        if relative not in entry["source_snapshots"]:
                            entry["source_snapshots"].append(relative)
                    if isinstance(children, list):
                        walk_context_menu(
                            children, current, platform_menu=platform_menu
                        )

            for menu in probe.get("menus", []):
                if isinstance(menu, list):
                    menu_texts = {
                        str(item.get("text", "")).strip()
                        for item in menu
                        if isinstance(item, dict)
                    }
                    platform_menu = {
                        "撤消(&U)", "剪切(&T)", "复制(&C)", "粘贴(&P)", "全选(&A)"
                    }.issubset(menu_texts)
                    if platform_menu:
                        # This is the operating system's stock Edit menu, not
                        # an application-defined command surface.  Its
                        # reachability is already represented by the origin
                        # control's right_click and keyboard_shortcuts actions;
                        # expanding 27 Unicode/IME commands per edit would
                        # multiply the product-function denominator by the OS
                        # language configuration.
                        platform_context_origins.add(origin)
                        continue
                    walk_context_menu(menu, platform_menu=platform_menu)

    for (title, class_name, control_id, tree_path), state in observed_states.items():
        if len(state["visible"]) > 1 or len(state["enabled"]) > 1:
            action_id = _stable_id(
                (title, class_name, control_id, tree_path, "discover_state_triggers")
            )
            actions.setdefault(
                action_id,
                {
                    "action_id": action_id,
                    "window": title,
                    "control_class": class_name,
                    "control_id": control_id,
                    "tree_path": list(tree_path),
                    "observed_text": " / ".join(sorted(state["texts"])[:3]),
                    "action": "discover_state_triggers",
                    "source_snapshots": sorted(state["snapshots"]),
                    "source_tree_paths": [
                        list(path) for path in sorted(state.get("tree_paths", set()))
                    ],
                },
            )

    status_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    result_actions: list[dict[str, Any]] = []
    for action in sorted(
        actions.values(),
        key=lambda item: (
            item["window"], item["control_class"], item["control_id"],
            item["tree_path"], item["action"],
        ),
    ):
        evidence = records.get(action["action_id"])
        status = str(evidence.get("status", "pending")) if evidence else "pending"
        action["status"] = status
        if evidence:
            action["evidence"] = evidence
        status_counts[status] += 1
        class_counts[action["control_class"]] += 1
        action_counts[action["action"]] += 1
        result_actions.append(action)

    return {
        "schema_version": 1,
        "scope_note": (
            "This is an exploration frontier, not proof of completion. Pending actions, "
            "untriggered conditional states and newly discovered windows keep the gate open."
        ),
        "sources": {
            "root": root.as_posix(),
            "snapshot_files": snapshot_count,
            "menu_files": menu_files,
            "interaction_discovery_files": discovery_files,
            "rejected_interaction_discovery_files": rejected_discovery_files,
            "embedded_execution_records": embedded_execution_records,
            "platform_context_menu_origins": len(platform_context_origins),
            "execution_records": execution_path.as_posix() if execution_path else None,
        },
        "counts": {
            "actions": len(result_actions),
            "by_status": dict(sorted(status_counts.items())),
            "by_control_class": dict(sorted(class_counts.items())),
            "by_action": dict(sorted(action_counts.items())),
        },
        "closed": bool(result_actions) and status_counts.get("pending", 0) == 0,
        "actions": result_actions,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# 旧修改器递归交互探索前沿",
        "",
        f"- 输入窗口快照：{report['sources']['snapshot_files']}",
        f"- 菜单快照：{report['sources']['menu_files']}",
        f"- 实跑交互发现文件：{report['sources']['interaction_discovery_files']}",
        f"- 因状态验证不足被拒绝的发现文件：{report['sources']['rejected_interaction_discovery_files']}",
        f"- 待探索动作总数：{counts['actions']}",
        f"- 状态：{', '.join(f'{key}={value}' for key, value in counts['by_status'].items())}",
        f"- 探索闭合：{'是' if report['closed'] else '否'}",
        "",
        "> 该表是递归探索队列，不是完成证明。只有动作具有执行证据、条件状态已触发且不再产生新窗口/新动作，分母才可闭合。",
        "",
        "## 动作类型",
        "",
        "| 动作 | 数量 |",
        "|---|---:|",
    ]
    for name, count in counts["by_action"].items():
        lines.append(f"| `{name}` | {count} |")
    lines.extend(["", "## 控件类型", "", "| 控件类 | 动作数 |", "|---|---:|"])
    for name, count in counts["by_control_class"].items():
        lines.append(f"| `{name}` | {count} |")
    lines.extend([
        "", "## 待执行动作（前 500 项）", "",
        "| ID | 窗口 | 控件 | 文本 | 动作 | 状态 |",
        "|---|---|---|---|---|---|",
    ])
    for action in report["actions"][:500]:
        values = [
            f"`{action['action_id']}`", action["window"],
            f"`{action['control_class']}#{action['control_id']}`",
            action["observed_text"], f"`{action['action']}`", action["status"],
        ]
        values = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification-root", type=Path, default=Path("output/verification"))
    parser.add_argument("--execution-records", type=Path)
    parser.add_argument("--json-output", type=Path, default=Path("output/reports/legacy-interaction-frontier.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("output/reports/legacy-interaction-frontier.md"))
    args = parser.parse_args()
    report = build_report(args.verification_root, args.execution_records)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

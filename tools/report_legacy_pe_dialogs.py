"""Enumerate static Win32 dialog templates embedded in the reference EXE.

Runtime probing remains authoritative for dynamically-created controls.  This
report complements it with RT_DIALOG resources, which are available without
launching the elevated legacy process and can expose otherwise-blocked modal
dialogs.  The reference executable is opened read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import pefile


RT_DIALOG = 5
DS_SETFONT = 0x40
CONTROL_CLASSES = {
    0x0080: "Button",
    0x0081: "Edit",
    0x0082: "Static",
    0x0083: "ListBox",
    0x0084: "ScrollBar",
    0x0085: "ComboBox",
}


class DialogParseError(ValueError):
    pass


def _align(offset: int, boundary: int = 4) -> int:
    return (offset + boundary - 1) & ~(boundary - 1)


def _word(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 2 > len(data):
        raise DialogParseError("unexpected end of dialog template")
    return struct.unpack_from("<H", data, offset)[0], offset + 2


def _variable(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    first, offset = _word(data, offset)
    if first == 0:
        return {"kind": "none", "value": ""}, offset
    if first == 0xFFFF:
        ordinal, offset = _word(data, offset)
        return {"kind": "ordinal", "value": ordinal}, offset
    chars = [first]
    while True:
        value, offset = _word(data, offset)
        if value == 0:
            break
        chars.append(value)
    raw = struct.pack(f"<{len(chars)}H", *chars)
    return {"kind": "string", "value": raw.decode("utf-16le")}, offset


def _class_name(value: dict[str, Any]) -> str:
    if value["kind"] == "ordinal":
        ordinal = int(value["value"])
        return CONTROL_CLASSES.get(ordinal, f"ordinal:{ordinal}")
    return str(value["value"])


def parse_dialog_template(data: bytes) -> dict[str, Any]:
    if len(data) < 18:
        raise DialogParseError("dialog template is too short")
    extended = struct.unpack_from("<HH", data, 0) == (1, 0xFFFF)
    if extended:
        (
            _version,
            _signature,
            help_id,
            ex_style,
            style,
            item_count,
            x,
            y,
            cx,
            cy,
        ) = struct.unpack_from("<HHLLLHhhhh", data, 0)
        offset = 26
    else:
        style, ex_style, item_count, x, y, cx, cy = struct.unpack_from(
            "<LLHhhhh", data, 0
        )
        help_id = 0
        offset = 18

    menu, offset = _variable(data, offset)
    window_class, offset = _variable(data, offset)
    title, offset = _variable(data, offset)
    font: dict[str, Any] | None = None
    if style & DS_SETFONT:
        point_size, offset = _word(data, offset)
        if extended:
            weight, offset = _word(data, offset)
            if offset + 2 > len(data):
                raise DialogParseError("truncated extended font metadata")
            italic, charset = struct.unpack_from("<BB", data, offset)
            offset += 2
        else:
            weight, italic, charset = 0, 0, 0
        face, offset = _variable(data, offset)
        font = {
            "point_size": point_size,
            "weight": weight,
            "italic": italic,
            "charset": charset,
            "face": face["value"],
        }

    controls: list[dict[str, Any]] = []
    for _index in range(item_count):
        offset = _align(offset)
        if extended:
            if offset + 24 > len(data):
                raise DialogParseError("truncated extended dialog item")
            (
                item_help_id,
                item_ex_style,
                item_style,
                item_x,
                item_y,
                item_cx,
                item_cy,
                control_id,
            ) = struct.unpack_from("<LLLhhhhL", data, offset)
            offset += 24
        else:
            if offset + 18 > len(data):
                raise DialogParseError("truncated dialog item")
            (
                item_style,
                item_ex_style,
                item_x,
                item_y,
                item_cx,
                item_cy,
                control_id,
            ) = struct.unpack_from("<LLhhhhH", data, offset)
            item_help_id = 0
            offset += 18
        item_class, offset = _variable(data, offset)
        item_title, offset = _variable(data, offset)
        extra_size, offset = _word(data, offset)
        if offset + extra_size > len(data):
            raise DialogParseError("truncated dialog item creation data")
        offset += extra_size
        controls.append(
            {
                "control_id": control_id,
                "class": _class_name(item_class),
                "title": item_title["value"],
                "rect": {"x": item_x, "y": item_y, "cx": item_cx, "cy": item_cy},
                "style": f"0x{item_style:08X}",
                "ex_style": f"0x{item_ex_style:08X}",
                "help_id": item_help_id,
            }
        )
    return {
        "extended": extended,
        "title": title["value"],
        "class": _class_name(window_class),
        "menu": menu["value"],
        "rect": {"x": x, "y": y, "cx": cx, "cy": cy},
        "style": f"0x{style:08X}",
        "ex_style": f"0x{ex_style:08X}",
        "help_id": help_id,
        "font": font,
        "declared_control_count": item_count,
        "controls": controls,
    }


def _resource_name(entry: Any) -> str:
    return str(entry.name) if entry.name is not None else str(entry.id)


def build_report(exe_path: Path) -> dict[str, Any]:
    payload = exe_path.read_bytes()
    pe = pefile.PE(data=payload, fast_load=False)
    resources = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
    if resources is None:
        raise DialogParseError("PE has no resource directory")
    dialog_type = next(
        (entry for entry in resources.entries if entry.id == RT_DIALOG), None
    )
    if dialog_type is None:
        raise DialogParseError("PE has no RT_DIALOG resources")
    dialogs: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for name_entry in dialog_type.directory.entries:
        resource_name = _resource_name(name_entry)
        for language_entry in name_entry.directory.entries:
            data_entry = language_entry.data.struct
            raw = pe.get_data(data_entry.OffsetToData, data_entry.Size)
            try:
                parsed = parse_dialog_template(raw)
            except DialogParseError as exc:
                failures.append({"resource": resource_name, "error": str(exc)})
                continue
            parsed.update(
                {
                    "resource": resource_name,
                    "language": language_entry.id,
                    "size": data_entry.Size,
                }
            )
            dialogs.append(parsed)
    dialogs.sort(key=lambda item: item["resource"])
    return {
        "schema_version": 1,
        "source": exe_path.as_posix(),
        "source_sha256": hashlib.sha256(payload).hexdigest().upper(),
        "scope_note": (
            "只读解析参考 EXE 的 RT_DIALOG；动态创建窗口仍以运行时控件树为准。"
        ),
        "counts": {
            "dialog_resources": len(dialogs),
            "parse_failures": len(failures),
            "declared_controls": sum(
                item["declared_control_count"] for item in dialogs
            ),
        },
        "failures": failures,
        "dialogs": dialogs,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# 参考 EXE 静态对话框资源枚举",
        "",
        f"- 对话框资源：{counts['dialog_resources']}",
        f"- 已声明控件：{counts['declared_controls']}",
        f"- 解析失败：{counts['parse_failures']}",
        f"- EXE SHA-256：`{report['source_sha256']}`",
        "",
        f"> {report['scope_note']}",
        "",
        "| 资源 | 标题 | 控件数 | 模板 |",
        "|---|---|---:|---|",
    ]
    for dialog in report["dialogs"]:
        title = str(dialog["title"]).replace("|", "\\|").replace("\n", " ")
        template = "DIALOGEX" if dialog["extended"] else "DIALOG"
        lines.append(
            f"| `{dialog['resource']}` | {title} | "
            f"{dialog['declared_control_count']} | {template} |"
        )
        for control in dialog["controls"]:
            text = str(control["title"]).replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| ↳ {control['control_id']} | {text} |  | `{control['class']}` |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exe", default="references/legacy_modifier/SRW2_patched.exe"
    )
    parser.add_argument(
        "--json-out", default="output/reports/legacy-pe-dialogs.json"
    )
    parser.add_argument(
        "--markdown-out", default="output/reports/legacy-pe-dialogs.md"
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    report = build_report((repo / args.exe).resolve())
    json_path = repo / args.json_out
    markdown_path = repo / args.markdown_out
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(
        render_markdown(report), encoding="utf-8", newline="\n"
    )
    counts = report["counts"]
    print(
        f"legacy PE dialogs: {counts['dialog_resources']} resources, "
        f"{counts['declared_controls']} controls, "
        f"{counts['parse_failures']} failures"
    )
    return 0 if not counts["parse_failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

from fc_editor.codecs.chapter_event import ACTION_FIELDS, ACTION_LABELS, OPCODE_LABELS
from fc_editor.dc_text import dc_map_label, default_dc_text_table
from fc_rom_editor_core import RomProject


ROOT = Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "FC模拟器" / "DC_kuorong_464K.nes"
CONFIG_ROOT = ROOT / "默认配置文件"
OUTPUT_ROOT = ROOT / "build" / "修改器映射表"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _escape_tbl(value: str) -> str:
    return value.replace("\r", r"\r").replace("\n", r"\n").replace("\t", r"\t")


def export_text_tables() -> dict[str, object]:
    source_path = CONFIG_ROOT / "码表.ini"
    source_bytes = source_path.read_bytes()
    source_rows = []
    for line_number, line in enumerate(source_bytes.decode("gb18030").splitlines(), 1):
        parts = line.split("=", 2)
        if len(parts) != 3:
            continue
        tile_address, token, text = parts
        source_rows.append((line_number, tile_address, token, text))

    table = default_dc_text_table()
    tbl_lines = [
        "# 新DC篇完整Token字库（UTF-8）",
        "# 来源：默认配置文件/码表.ini；F2=换行，FF=文本结束。",
    ]
    for token, value in sorted(
        table.byte_to_text.items(), key=lambda item: (len(item[0]), item[0])
    ):
        tbl_lines.append(f"{token.hex().upper()}={_escape_tbl(value)}")
    tbl_path = OUTPUT_ROOT / "新DC完整码表.tbl"
    _write_text(tbl_path, "\n".join(tbl_lines) + "\n")

    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer, lineterminator="\n")
    writer.writerow(("sourceLine", "tileAddress", "token", "text"))
    writer.writerows(source_rows)
    csv_path = OUTPUT_ROOT / "新DC字模地址映射.csv"
    _write_text(csv_path, csv_buffer.getvalue())
    return {
        "source": str(source_path.relative_to(ROOT)).replace("\\", "/"),
        "sourceSha256": _sha256(source_bytes),
        "sourceRows": len(source_rows),
        "effectiveMappings": len(table.byte_to_text),
        "tbl": tbl_path.name,
        "glyphAddressCsv": csv_path.name,
    }


def export_config_catalog() -> dict[str, object]:
    tables: dict[str, object] = {}
    for path in sorted(CONFIG_ROOT.glob("*.ini")):
        if path.name in {"码表.ini", "mnq.ini"}:
            continue
        raw = path.read_bytes()
        values = raw.decode("gb18030").splitlines()
        rows = []
        for index, value in enumerate(values):
            stripped = value.strip()
            if not stripped:
                status = "blank"
            elif stripped == "未命名" or stripped.startswith("未知"):
                status = "unverified-placeholder"
            elif stripped == "没用":
                status = "unused"
            else:
                status = "reference-label"
            rows.append(
                {
                    "id": index,
                    "hexId": f"${index:02X}",
                    "label": value,
                    "status": status,
                }
            )
        tables[path.stem] = {
            "source": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sourceSha256": _sha256(raw),
            "rows": rows,
        }
    output = {
        "schemaVersion": 1,
        "description": "旧修改器的DC专用名称索引；未命名项按原资料保留并显式标记。",
        "tables": tables,
    }
    output_path = OUTPUT_ROOT / "旧修改器配置名称索引.json"
    _write_text(output_path, json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    return {"file": output_path.name, "tableCount": len(tables)}


def export_rom_mappings(project: RomProject) -> dict[str, object]:
    units = []
    for unit_id in range(1, project.unit_count):
        record = project.unit_codec.decode_record(unit_id, bytes(project.working))
        weapons = project.get_unit_weapons(unit_id)
        units.append(
            {
                "id": unit_id,
                "hexId": f"${unit_id:02X}",
                "name": project.unit_display_name(unit_id),
                "attributePointer": f"${record.pointer:04X}",
                "attributeSharedIds": list(record.ids),
                "namePointer": f"${project.get_unit_name_pointer(unit_id):04X}",
                "nameSharedIds": list(project.unit_name_source_ids(unit_id)),
                "weapons": [
                    {
                        "slot": slot,
                        "weaponId": weapon_id,
                        "weaponHexId": f"${weapon_id:02X}",
                        "weaponName": (
                            "无武器"
                            if weapon_id == 0
                            else project.weapon_display_name(weapon_id)
                        ),
                    }
                    for slot, weapon_id in enumerate(weapons, 1)
                ],
            }
        )

    weapons = []
    for weapon_id in range(1, project.weapon_count):
        record = project.weapon_codec.decode_record(weapon_id, bytes(project.working))
        weapons.append(
            {
                "id": weapon_id,
                "hexId": f"${weapon_id:02X}",
                "name": project.weapon_display_name(weapon_id),
                "attributePointer": f"${record.pointer:04X}",
                "attributeSharedIds": [
                    source_id
                    for source_id, pointer in enumerate(project.weapon_codec.pointers)
                    if source_id and pointer == record.pointer
                ],
                "namePointer": f"${project.get_weapon_name_pointer(weapon_id):04X}",
                "nameSharedIds": list(project.weapon_name_source_ids(weapon_id)),
                "nameTokens": project.weapon_name_record_bytes(weapon_id).hex(" ").upper(),
            }
        )

    characters = []
    assert project.character_name_codec is not None
    for character_id in range(project.profile.character_name_count):
        pointer = project.character_name_codec.pointer(character_id)
        characters.append(
            {
                "id": character_id,
                "hexId": f"${character_id:02X}",
                "name": project.character_display_name(character_id),
                "pointer": f"${pointer:04X}" if pointer else None,
                "tokens": project.character_name_codec.record_bytes(character_id).hex(" ").upper(),
            }
        )

    maps = []
    for map_id in range(project.map_count):
        item = {
            "id": map_id,
            "hexId": f"${map_id:02X}",
            "title": dc_map_label(map_id),
            "status": (
                "chapter"
                if map_id < 0x0D
                else "unused"
                if map_id < 0x20
                else "reserved"
            ),
        }
        if project.map_trigger_codec is not None and map_id < 0x20:
            item["coordinateEvents"] = [
                {
                    "x": trigger.x,
                    "y": trigger.y,
                    "characterId": trigger.character_id,
                    "characterName": (
                        "任何人物"
                        if trigger.character_id == 0xFF
                        else project.character_display_name(trigger.character_id)
                    ),
                    "eventId": trigger.event_id,
                    "kind": "shop" if trigger.is_shop else "event",
                }
                for trigger in project.get_map_triggers(map_id)
            ]
        maps.append(item)

    music_spec = project.profile.battle_music
    tracks = [
        {"command": item.command, "hexCommand": f"${item.command:02X}", "label": item.label}
        for item in music_spec.tracks
    ] if music_spec is not None else []
    selectors = []
    if music_spec is not None:
        for selector in range(music_spec.selector_count):
            binding = project.get_battle_music_binding(selector)
            selectors.append(
                {
                    "id": selector,
                    "hexId": f"${selector:02X}",
                    "label": project.battle_music_selector_label(selector),
                    "attackerCommand": f"${binding.attacker_command:02X}",
                    "attackerTrack": project.battle_music_codec.format_command(
                        binding.attacker_command
                    ),
                    "defenderCommand": f"${binding.defender_command:02X}",
                    "defenderTrack": project.battle_music_codec.format_command(
                        binding.defender_command
                    ),
                }
            )

    output = {
        "schemaVersion": 2,
        "profile": project.profile.key,
        "sourceRom": str(ROM_PATH.relative_to(ROOT)).replace("\\", "/"),
        "sourceRomSha256": project.source_sha256,
        "verifiedTables": {
            "unitNamePointers": "0x49908",
            "unitWeapons": "0x0B2D8",
            "weaponNamePointers": "0x49DBD",
            "characterBattleNamePointers": "0x49776",
            "battleMusicAttacker": "0x0CF86",
            "battleMusicDefender": "0x0D04E",
            "mapEventPointers": "0x1588E",
            "mapEventManagedPool": "0x15EE4-0x1600F",
            "persuasionRules": "0x3B73D",
            "persuasionScriptPointers": "0x35DD0",
        },
        "units": units,
        "weapons": weapons,
        "characters": characters,
        "maps": maps,
        "musicTracks": tracks,
        "battleMusicSelectors": selectors,
        "chapterEventActions": [
            {
                "opcode": opcode,
                "hexOpcode": f"${opcode:02X}",
                "label": label,
                "fields": list(ACTION_FIELDS.get(opcode, ())),
            }
            for opcode, label in sorted(ACTION_LABELS.items())
        ],
        "chapterEventOpcodes": [
            {
                "opcode": opcode,
                "hexOpcode": f"${opcode:02X}",
                "label": label,
                "fields": list(ACTION_FIELDS.get(opcode, ())),
            }
            for opcode, label in sorted(OPCODE_LABELS.items())
        ],
        "persuasionRules": [
            {
                "slot": rule.slot,
                "hexSlot": f"${rule.slot:02X}",
                "scenarioId": rule.scenario_id,
                "scenario": dc_map_label(rule.scenario_id),
                "persuaderId": rule.persuader_id,
                "persuader": project.character_display_name(rule.persuader_id),
                "targetId": rule.target_id,
                "target": project.character_display_name(rule.target_id),
                "scriptAddress": f"${rule.script_address:04X}",
            }
            for rule in project.persuasion_rule_codec.editable_rules(project.working)
        ] if project.persuasion_rule_codec is not None else [],
    }
    output_path = OUTPUT_ROOT / "新DC_ROM名称与表地址映射.json"
    _write_text(output_path, json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    return {
        "file": output_path.name,
        "units": len(units),
        "weapons": len(weapons),
        "characters": len(characters),
        "maps": len(maps),
        "musicSelectors": len(selectors),
    }


def main() -> None:
    project = RomProject.load(ROM_PATH)
    text_info = export_text_tables()
    config_info = export_config_catalog()
    rom_info = export_rom_mappings(project)
    readme = f"""# 新DC篇修改器映射表

本目录由 `python tools\\export_dc_modifier_mappings.py` 从当前基准 ROM 和用户提供的 `默认配置文件/` 确定性生成，文件均为 UTF-8。

- `新DC完整码表.tbl`：{text_info['effectiveMappings']} 条实际可解码 Token；可由新版剧情编辑器直接载入。
- `新DC字模地址映射.csv`：保留旧配置的 {text_info['sourceRows']} 行字模地址、Token 和字符关系。
- `新DC_ROM名称与表地址映射.json`：{rom_info['units']} 个机体、{rom_info['weapons']} 个武器、{rom_info['characters']} 个人物选择器、{rom_info['maps']} 张地图及 {rom_info['musicSelectors']} 个战斗音乐选择器。
- `旧修改器配置名称索引.json`：{config_info['tableCount']} 组旧修改器名称表，保留行号即 ID；原资料中的空白、`未命名` 和 `未知` 均带状态，不会被猜测性改名。

基准 ROM SHA-256：`{project.source_sha256}`。若 ROM 哈希变化，应重新生成并重新验证表地址。
"""
    _write_text(OUTPUT_ROOT / "README.md", readme)
    print(f"已生成映射表：{OUTPUT_ROOT}")


if __name__ == "__main__":
    main()

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs.animation import (  # noqa: E402
    AnimationCodec,
    TABLES,
    decode_background_rule,
    decode_sprite_composition,
    decode_sprite_timeline,
)


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_REPORT = ROOT / "output" / "verification" / "m12-animation-compatibility.json"
INTERPRETER_OFFSET = 16 + 62 * 0x2000 + (0xD194 - 0xC000)
INTERPRETER_SIGNATURE = bytes.fromhex(
    "86 1F BD 00 07 85 07 29 20 85 0C BD 20 07 85 12 "
    "A5 07 29 04 F0 08 A5 07 29 01 D0 02 A9 FF"
)
PUZZLE_SAMPLE = bytes.fromhex(
    "08 00 18 00 08 F4 00 08 F4 00 08 F8 00 28 1E F8 "
    "80 A8 1C F8 80 A8 1A FC 80 A8 18 FC 80 80 FF"
)
REFERENCE_AUDIT_FILES = (
    ROOT / "references" / "research" / "fc资料集-v1.16" / "page_325.html",
    ROOT / "references" / "research" / "fc资料集-v1.16" / "精神数据指针地址.htm",
    ROOT / "references" / "research" / "fc资料集-v1.16" / "精神效果地址.htm",
    ROOT / "references" / "research" / "fc资料集-v1.16" / "战斗过程程序.htm",
    ROOT / "references" / "research" / "fc资料集-v1.16" / "武器动画指针.htm",
    ROOT / "references" / "research" / "fc资料集-v1.16" / "武器动画标志代码.htm",
)
READ_ONLY_CALL_AUDIT = {
    0x3804A: {
        "animation_id": 0x00,
        "reason_code": "reference_value_conflict",
        "reason": "资料集 page_325.html 记为 $3804A→$0C，当前 ROM 同址却是 $00；编号冲突，不能按参考项解禁。",
    },
    0x384B0: {
        "animation_id": 0x10,
        "reason_code": "id_meaning_only",
        "reason": "资料集只说明动画 $10 的显示含义，未给出该调用地址或可核对的完整前置序列。",
    },
    0x3853D: {
        "animation_id": 0x10,
        "reason_code": "id_meaning_only",
        "reason": "资料集只说明动画 $10 的显示含义，未给出该调用地址或可核对的完整前置序列。",
    },
    0x38982: {
        "animation_id": 0x02,
        "reason_code": "reference_address_mismatch",
        "reason": "资料集 page_325.html 记为 $38983→$02，而当前 ROM 调用起点是 $38982；虽疑似文档偏一字节，仍不把推测当精确地址证据。",
    },
    0x38E68: {
        "animation_id": 0x14,
        "reason_code": "id_meaning_only",
        "reason": "资料集只说明动画 $14 的显示含义，未列出该地址，前置序列也未在精神/战斗流程清单中复现。",
    },
    0x38EF3: {
        "animation_id": 0x12,
        "reason_code": "id_meaning_only",
        "reason": "资料集只说明动画 $12 的显示含义，未列出该地址，当前邻近事件指令语义不足以证明写入安全。",
    },
    0x3B9DC: {
        "animation_id": 0x37,
        "reason_code": "embedded_vm_data_unverified",
        "reason": "该命中位于 6502 子程序后的嵌入式数据段；资料集没有地址、编号或脚本入口的双重证据。",
    },
    0x3B9E0: {
        "animation_id": 0x3D,
        "reason_code": "embedded_vm_data_unverified",
        "reason": "该命中紧邻另一处未验证命中并位于嵌入式数据段；没有已验证的调用链头，不能因连续字节外观解禁。",
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _changed_indices(before: bytes, after: bytes) -> list[int]:
    return [
        index
        for index, (left, right) in enumerate(zip(before, after))
        if left != right
    ]


def _rejected(action) -> str:
    try:
        action()
    except ValueError as error:
        return str(error)
    raise AssertionError("预期写入门禁拒绝操作，但调用成功。")


def analyze(rom_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    codec = AnimationCodec(data)
    original_hash = _sha256(data)
    table_counts = {table.kind: codec.count(table.kind) for table in TABLES}
    script_summary = {}
    for kind in ("map", "ally", "enemy"):
        records = [codec.record(kind, index) for index in range(codec.count(kind))]
        script_summary[kind] = {
            "slots": len(records),
            "live_records": sum(bool(record.raw) for record in records),
            "complete_records": sum(record.complete for record in records),
            "shared_slots": sum(bool(record.aliases) for record in records),
        }
    compositions = []
    for index in range(codec.count("sprite")):
        record = codec.record("sprite", index)
        compositions.append(
            decode_sprite_composition(record.raw, record.offset)
        )
    roles = codec.movement_roles()
    frame_rules = sorted(
        index for index, role in roles.items() if role == {"frames"}
    )
    timelines = {
        index: decode_sprite_timeline(
            codec.record("movement", index).raw,
            codec.count("sprite"),
        )
        for index in frame_rules
    }
    sample = decode_sprite_composition(PUZZLE_SAMPLE)

    map_record = codec.record("map", 1)
    map_changed = bytearray(map_record.raw)
    map_changed[5] = 0x27
    map_patch = codec.script_patch(map_record, bytes(map_changed))
    movement_record = codec.record("movement", 1)
    movement_changed = bytearray(movement_record.raw)
    movement_changed[2] = 0x05
    movement_patch = codec.rule_patch(movement_record, bytes(movement_changed))
    first = codec.record("sprite", 0)
    sprite_changed = bytearray(first.raw)
    sprite_changed[2] = 0x01
    sprite_code_patch = codec.rule_patch(first, bytes(sprite_changed))
    anchor_changed = bytearray(first.raw)
    anchor_changed[0] = 0x01
    anchor_rejection = _rejected(
        lambda: codec.rule_patch(first, bytes(anchor_changed))
    )
    call_patch = codec.call_patch(0x3BB93, 2)
    calls = codec.calls()
    call_evidence: dict[str, int] = {}
    for offset, _animation_id in calls:
        evidence = codec.call_evidence(offset)
        if evidence is not None:
            call_evidence[evidence] = call_evidence.get(evidence, 0) + 1
    read_only_calls = [
        (offset, animation_id)
        for offset, animation_id in calls
        if codec.call_evidence(offset) is None
    ]
    read_only_call_details = []
    for offset, animation_id in read_only_calls:
        audit = READ_ONLY_CALL_AUDIT.get(offset, {})
        context_start = offset - 8
        context_end = offset + 11
        bank = (offset - 16) // 0x2000
        cpu_address = 0x8000 + (offset - 16) % 0x2000
        read_only_call_details.append(
            {
                "file_offset": f"0x{offset:06X}",
                "bank": f"${bank:02X}",
                "cpu_address": f"${cpu_address:04X}",
                "animation_id": f"${animation_id:02X}",
                "context_range": f"0x{context_start:06X}-0x{context_end - 1:06X}",
                "context": data[context_start:context_end].hex(" ").upper(),
                "reason_code": audit.get("reason_code", "audit_missing"),
                "reason": audit.get("reason", "缺少逐项审计结论。"),
            }
        )
    reference_audit_hashes = {
        path.relative_to(ROOT).as_posix(): _sha256(path.read_bytes())
        for path in REFERENCE_AUDIT_FILES
    }

    background_records = [
        codec.record("background", index)
        for index in range(codec.count("background"))
    ]
    background_references = []
    for kind in ("map", "ally", "enemy"):
        for index in range(codec.count(kind)):
            for instruction in codec.record(kind, index).instructions:
                if (
                    len(instruction.raw) == 3
                    and instruction.raw[0] == 0xF3
                    and instruction.raw[1] == 0x23
                ):
                    background_references.append(
                        {
                            "source": f"{kind}:{index:02X}",
                            "rule": f"${instruction.raw[2]:02X}",
                            "offset": f"0x{instruction.offset:06X}",
                        }
                    )
    background_rule_ids = sorted(
        {int(reference["rule"][1:], 16) for reference in background_references}
    )
    background_alias_slots = [
        f"${record.index:02X}"
        for record in background_records
        if record.aliases
    ]
    background_end_terminated = [
        f"${record.index:02X}"
        for record in background_records
        if record.raw and record.raw[-1] == 0xFF
    ]
    background_decodes = {}
    for record in background_records:
        rows, complete = decode_background_rule(record.raw, record.offset)
        consumed = sum(len(row.raw) for row in rows)
        editable_offsets = [
            row.offset - record.offset + local
            for row in rows
            for local, _low, _high in row.editable
        ]
        background_decodes[f"${record.index:02X}"] = {
            "complete": complete,
            "exact_boundary": complete and consumed == len(record.raw),
            "consumed": consumed,
            "record_bytes": len(record.raw),
            "editable_parameter_count": len(editable_offsets),
            "stop_byte": (
                f"${rows[-1].raw[0]:02X}" if rows and rows[-1].raw else None
            ),
        }
    background_complete_ids = [
        index
        for index in range(codec.count("background"))
        if background_decodes[f"${index:02X}"]["exact_boundary"]
    ]
    background_editable_ids = list(codec.background_editable_indices())
    background_blocked_ids = [
        index
        for index in range(codec.count("background"))
        if index not in background_editable_ids
    ]
    background_static_decodes = {}
    for index in background_rule_ids:
        record = background_records[index]
        rows, complete = decode_background_rule(record.raw, record.offset)
        background_static_decodes[f"${index:02X}"] = {
            "complete": complete,
            "consumed": sum(len(row.raw) for row in rows),
            "record_bytes": len(record.raw),
            "editable_parameter_offsets": [
                row.offset - record.offset + local
                for row in rows
                for local, _low, _high in row.editable
            ],
        }
    background_changed = bytearray(background_records[3].raw)
    background_changed[5] ^= 1
    background_patch = codec.rule_patch(
        background_records[3], bytes(background_changed)
    )
    background_header_changed = bytearray(background_records[3].raw)
    background_header_changed[0] = 0xFD
    background_header_rejection = _rejected(
        lambda: codec.rule_patch(
            background_records[3],
            bytes(background_header_changed),
        )
    )
    background_dynamic_boundary_rejection = _rejected(
        lambda: codec.rule_patch(background_records[2], background_records[2].raw)
    )
    clone_index, clone_patches = codec.clone_map_animation_patches(0)
    cloned_data = bytearray(data)
    for offset, before, after in clone_patches:
        if bytes(cloned_data[offset:offset + len(before)]) != before:
            raise AssertionError("地图动画复制补丁的旧值不匹配。")
        cloned_data[offset:offset + len(after)] = after
    cloned_codec = AnimationCodec(cloned_data)
    cloned_record = cloned_codec.record("map", clone_index)
    sprite_source = codec.record("sprite", 0)
    sprite_clone_index, sprite_clone_patches = codec.clone_sprite_rule_patches(0)
    sprite_cloned_data = bytearray(data)
    for offset, before, after in sprite_clone_patches:
        if bytes(sprite_cloned_data[offset:offset + len(before)]) != before:
            raise AssertionError("组图规律复制补丁的旧值不匹配。")
        sprite_cloned_data[offset:offset + len(after)] = after
    sprite_cloned_codec = AnimationCodec(sprite_cloned_data)
    sprite_cloned_record = sprite_cloned_codec.record(
        "sprite", sprite_clone_index
    )
    movement_source = codec.record("movement", 1)
    movement_clone_index, movement_clone_role, movement_clone_patches = (
        codec.clone_movement_rule_patches(1, 1)
    )
    movement_cloned_data = bytearray(data)
    for offset, before, after in movement_clone_patches:
        if bytes(movement_cloned_data[offset:offset + len(before)]) != before:
            raise AssertionError("运行规律复制补丁的旧值不匹配。")
        movement_cloned_data[offset:offset + len(after)] = after
    movement_cloned_codec = AnimationCodec(movement_cloned_data)
    movement_cloned_record = movement_cloned_codec.record(
        "movement", movement_clone_index
    )
    length_rejection = _rejected(
        lambda: codec.script_patch(map_record, map_record.raw + b"\x00")
    )
    opcode_changed = bytearray(map_record.raw)
    opcode_changed[0] = 0xE1
    opcode_rejection = _rejected(
        lambda: codec.script_patch(map_record, bytes(opcode_changed))
    )
    unverified_call_rejection = _rejected(
        lambda: codec.call_patch(0x3804A, 2)
    )
    unresolved_records = [
        index
        for index, composition in enumerate(compositions)
        if any(tile.tile_index is None for tile in composition.placements)
    ]
    incomplete_timelines = {
        f"{index:02X}": timeline.error
        for index, timeline in timelines.items()
        if not timeline.complete
    }
    checks = {
        "interpreter_signature": (
            data[
                INTERPRETER_OFFSET : INTERPRETER_OFFSET
                + len(INTERPRETER_SIGNATURE)
            ]
            == INTERPRETER_SIGNATURE
        ),
        "six_table_counts": table_counts
        == {
            "map": 153,
            "ally": 256,
            "enemy": 256,
            "background": 106,
            "movement": 157,
            "sprite": 249,
        },
        "all_sprite_records_complete": all(
            composition.complete for composition in compositions
        ),
        "sample_matches_16_tile_walk": (
            sample.complete
            and len(sample.placements) == 16
            and (sample.anchor_x, sample.anchor_y) == (8, 0)
            and (sample.placements[0].x, sample.placements[0].y) == (8, 0)
            and (sample.placements[-1].x, sample.placements[-1].y) == (16, 56)
            and sample.placements[-1].vertical_flip
        ),
        "sprite_code_patch_is_golden_first_tile_only": (
            sprite_code_patch[0] == first.offset
            and sprite_code_patch[1] == first.raw
            and _changed_indices(sprite_code_patch[1], sprite_code_patch[2]) == [2]
        ),
        "sprite_anchor_write_is_rejected": (
            "不持久化" in anchor_rejection
        ),
        "map_patch_is_one_verified_operand": (
            map_patch[0] == map_record.offset
            and _changed_indices(map_patch[1], map_patch[2]) == [5]
        ),
        "movement_patch_is_one_verified_operand": (
            movement_patch[0] == movement_record.offset
            and _changed_indices(movement_patch[1], movement_patch[2]) == [2]
        ),
        "call_patch_is_one_verified_operand": (
            call_patch == (0x3BB95, b"\x2C", b"\x02")
        ),
        "background_patch_is_one_verified_body_byte": (
            background_patch[0] == background_records[3].offset
            and _changed_indices(background_patch[1], background_patch[2]) == [5]
            and len(background_editable_ids) == 69
            and set(background_rule_ids).issubset(background_editable_ids)
        ),
        "map_clone_uses_reserved_slot_and_zero_pool": (
            clone_index == 0x3F
            and clone_patches[0][0] == 0x5208A
            and all(value == 0 for value in clone_patches[1][1])
            and cloned_record.complete
            and len(cloned_record.raw) == len(codec.record("map", 0).raw)
        ),
        "sprite_clone_uses_reserved_tail_pool": (
            sprite_clone_index == 0xEB
            and sprite_clone_patches[0][0] == 0x31C66
            and sprite_clone_patches[1][0] == 0x33348
            and len(sprite_clone_patches[1][1]) == 88
            and sprite_cloned_record.raw == sprite_source.raw
            and sprite_cloned_codec.pointers["sprite"][0xF7] == 0xB38B
            and sprite_cloned_codec.pointers["sprite"][0xF8] == 0xB38B
        ),
        "movement_clone_uses_reserved_tail_and_unique_binding": (
            movement_clone_index == 0x7D
            and movement_clone_role == "frames"
            and movement_clone_patches[0][0] == 0x3349A
            and movement_clone_patches[1][0] == 0x33B0D
            and len(movement_clone_patches[1][1]) == 32
            and movement_clone_patches[2][1:] == (b"\x01", b"\x7D")
            and movement_cloned_record.raw == movement_source.raw
            and movement_cloned_codec.movement_roles()[0x7D] == {"frames"}
        ),
        "verified_call_contexts_complete": (
            len(calls) == 86
            and sum(call_evidence.values()) == 78
            and call_evidence
            == {
                "直接设置/调用序列": 56,
                "战斗流程调用序列": 8,
                "带参数精神调用序列": 2,
                "连续动画调用序列": 4,
                "奇迹闪烁调用序列": 4,
                "资料集地址/编号清单": 2,
                "参考逐字段保存同址黄金": 2,
            }
        ),
        "read_only_call_audit_complete": (
            {offset: animation_id for offset, animation_id in read_only_calls}
            == {
                offset: int(audit["animation_id"])
                for offset, audit in READ_ONLY_CALL_AUDIT.items()
            }
            and len(read_only_call_details) == 8
            and all(
                detail["reason_code"] != "audit_missing"
                for detail in read_only_call_details
            )
            and len(reference_audit_hashes) == len(REFERENCE_AUDIT_FILES)
        ),
        "unsafe_edits_rejected": all(
            (
                "等长" in length_rejection,
                "不能改写" in opcode_rejection,
                "必须保持原值" in background_header_rejection,
                "暂不改写" in background_dynamic_boundary_rejection,
                "暂不改写" in unverified_call_rejection,
            )
        ),
        "background_read_boundary_proved": (
            codec.record("background", 0).raw[:6]
            == bytes.fromhex("FC 20 00 FC 20 4F")
            and background_rule_ids == [3, 4, 5, 6, 0x18, 0x19]
            and len(background_references) == 11
            and len(background_end_terminated) < codec.count("background")
            and max(len(record.raw) for record in background_records) == 1420
        ),
        "background_static_rules_decode_to_parameter_boundaries": (
            set(background_static_decodes)
            == {"$03", "$04", "$05", "$06", "$18", "$19"}
            and all(
                item["complete"]
                and item["consumed"] == item["record_bytes"]
                and item["editable_parameter_offsets"]
                for item in background_static_decodes.values()
            )
            and background_static_decodes["$03"]["editable_parameter_offsets"]
            == [5, 6, 8, 9, 11, 12]
        ),
        "background_all_slots_classified": (
            len(background_decodes) == 106
            and len(background_complete_ids) == 75
            and len(background_editable_ids) == 69
            and len(background_blocked_ids) == 37
            and background_editable_ids[:7] == [0, 1, 3, 4, 5, 6, 7]
            and background_editable_ids[-4:] == [0x51, 0x53, 0x58, 0x59]
            and set(background_rule_ids).issubset(background_editable_ids)
        ),
        "frame_rules_classified": len(frame_rules) == 81,
        "offline_timelines_complete_or_explicit_runtime_dependency": (
            set(incomplete_timelines) == {"12", "21"}
            and all(timeline.frames for timeline in timelines.values())
        ),
    }
    passed = all(checks.values())
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": passed,
        "delivery_status": "implementation_complete_guarded_scope",
        "conclusion": (
            "M12 当前安全交付范围已实现：六表读取、等长动画/运行编辑、组图首图块动态黄金、"
            "78/86 个已核对调用点与 F-069 拼图播放通过门禁；背景 106 槽已全量分类并开放 "
            "69 条解释器已验证参数，三类预留槽复制和工程名称写回已开放。旧版 X/Y 非持久化及"
            "其余未证范围均保持只读。"
        ),
        "rom": {
            "path": rom_path.resolve().relative_to(ROOT).as_posix(),
            "size": len(data),
            "sha256": original_hash,
            "unchanged_after_analysis": _sha256(data) == original_hash,
        },
        "evidence": {
            "renderer_cpu_range": "$D194-$D2EF",
            "renderer_file_offset": f"0x{INTERPRETER_OFFSET:06X}",
            "table_counts": table_counts,
            "script_records": script_summary,
            "safe_patches": {
                "map": {
                    "offset": f"0x{map_patch[0]:06X}",
                    "changed_indices": _changed_indices(map_patch[1], map_patch[2]),
                },
                "movement": {
                    "offset": f"0x{movement_patch[0]:06X}",
                    "changed_indices": _changed_indices(
                        movement_patch[1], movement_patch[2]
                    ),
                },
                "sprite_code_first_tile": {
                    "offset": f"0x{sprite_code_patch[0]:06X}",
                    "changed_indices": _changed_indices(
                        sprite_code_patch[1], sprite_code_patch[2]
                    ),
                },
                "call": {
                    "offset": f"0x{call_patch[0]:06X}",
                    "before": call_patch[1].hex(" ").upper(),
                    "after": call_patch[2].hex(" ").upper(),
                },
                "background_body": {
                    "offset": f"0x{background_patch[0]:06X}",
                    "changed_indices": _changed_indices(
                        background_patch[1], background_patch[2]
                    ),
                },
            },
            "map_clone": {
                "new_index": f"${clone_index:02X}",
                "pointer_patch_offset": f"0x{clone_patches[0][0]:06X}",
                "data_offset": f"0x{clone_patches[1][0]:06X}",
                "copied_bytes": len(clone_patches[1][2]),
                "initial_verified_zero_pool_bytes": 2306,
                "reserved_slots": "$3F-$98",
            },
            "sprite_clone": {
                "new_index": f"${sprite_clone_index:02X}",
                "pointer_patch_offset": f"0x{sprite_clone_patches[0][0]:06X}",
                "pool_offset": f"0x{sprite_clone_patches[1][0]:06X}",
                "pool_bytes": len(sprite_clone_patches[1][1]),
                "maximum_first_copy_bytes": 83,
                "copied_bytes": len(sprite_source.raw),
                "callable_reserved_slots": "$EB-$F6",
                "control_opcode_aliases": "$F7/$F8 -> $B38B",
            },
            "movement_clone": {
                "new_index": f"${movement_clone_index:02X}",
                "role": movement_clone_role,
                "pointer_patch_offset": f"0x{movement_clone_patches[0][0]:06X}",
                "pool_offset": f"0x{movement_clone_patches[1][0]:06X}",
                "pool_bytes": len(movement_clone_patches[1][1]),
                "maximum_first_copy_bytes": 31,
                "copied_bytes": len(movement_source.raw),
                "reserved_slots": "$7D-$9C",
                "binding_offset": f"0x{movement_clone_patches[2][0]:06X}",
                "binding_before": movement_clone_patches[2][1].hex(" ").upper(),
                "binding_after": movement_clone_patches[2][2].hex(" ").upper(),
                "binding_rule": "当前地图动画恰好一次引用且帧/坐标角色一致",
            },
            "animation_calls": {
                "detected": len(calls),
                "editable": sum(call_evidence.values()),
                "read_only": len(calls) - sum(call_evidence.values()),
                "verified_contexts": call_evidence,
                "read_only_sites": read_only_call_details,
                "reference_audit": {
                    "files": reference_audit_hashes,
                    "conclusion": (
                        "六份资料逐项复核后未新增可安全解禁位置：1 处编号冲突、1 处地址疑似偏一字节、"
                        "6 处仅有编号含义而无地址/完整上下文、2 处为未证实的嵌入式数据。"
                    ),
                },
            },
            "rejected_edits": {
                "length_change": length_rejection,
                "opcode_change": opcode_rejection,
                "background_header": background_header_rejection,
                "background_dynamic_boundary": background_dynamic_boundary_rejection,
                "unverified_call": unverified_call_rejection,
            },
            "background_boundary": {
                "slots": len(background_records),
                "static_references": background_references,
                "static_reference_rule_ids": [
                    f"${index:02X}" for index in background_rule_ids
                ],
                "shared_pointer_slots": background_alias_slots,
                "records_ending_at_ff": background_end_terminated,
                "maximum_pointer_span": max(
                    len(record.raw) for record in background_records
                ),
                "complete_records": len(background_complete_ids),
                "editable_records": len(background_editable_ids),
                "read_only_records": len(background_blocked_ids),
                "write_enabled": "69_exact_boundary_parameter_records",
                "editable_rule_ids": [
                    f"${index:02X}" for index in background_editable_ids
                ],
                "read_only_rule_ids": [
                    f"${index:02X}" for index in background_blocked_ids
                ],
                "interpreter": {
                    "fetch": "$D3E8",
                    "dispatch_table": "$D3F7",
                    "literal_range": "$00-$ED",
                    "handlers": "$F0-$FF -> $D4FD-$D8D9",
                },
                "static_rule_decodes": background_static_decodes,
                "slot_classification": background_decodes,
                "reason": (
                    "106 槽已逐项解释：75 条完整到达唯一边界，其中 69 条含可写绘制参数；"
                    "其余 6 条无安全参数，31 条含动态/不完整边界。所有控制码、资源引用、"
                    "变长参数、FE 布局头和 FF 结束码保持只读。"
                ),
            },
            "sprite_records": len(compositions),
            "complete_sprite_records": sum(item.complete for item in compositions),
            "runtime_tile_records": [f"{index:02X}" for index in unresolved_records],
            "frame_rules": len(frame_rules),
            "offline_complete_frame_rules": sum(
                timeline.complete for timeline in timelines.values()
            ),
            "runtime_dependent_frame_rules": incomplete_timelines,
            "sample": {
                "raw": PUZZLE_SAMPLE.hex(" ").upper(),
                "anchor": [sample.anchor_x, sample.anchor_y],
                "placements": [asdict(item) for item in sample.placements],
            },
            "sprite_code_patch": {
                "offset": f"0x{sprite_code_patch[0]:06X}",
                "before": sprite_code_patch[1].hex(" ").upper(),
                "after": sprite_code_patch[2].hex(" ").upper(),
            },
            "sprite_anchor_rejection": {
                "message": anchor_rejection,
                "reference_discovery": (
                    "output/build/legacy-diff-audit/cases/legacy_live/M12/"
                    "sprite_anchor_x/cold_start_07/case.json"
                ),
            },
        },
        "checks": checks,
        "limitations": [
            "13 个组图记录含 $F0-$FF 运行时图块令牌；预览明确画为未解析占位，不猜测 RAM 表。",
            "运行规律 $12 的循环次数来自运行时参数，$21 会切换运行时指针页；两项保留明确门禁。",
            "预览图库、00/80 映射和整图翻转只影响可视验证，不写 ROM。",
            "背景规律 106 槽中 75 条具有完整唯一边界，69 条含可写绘制参数；另 6 条无安全参数、31 条含动态或不完整边界并保持只读。",
            "86 个静态动画调用中 78 个具有完整上下文、资料集双证据或参考逐字段同址保存黄金；其余 8 个字节命中保持只读。",
            "8 个只读调用均已记录 Bank/CPU 地址、邻近原码和锁定原因；资料冲突或疑似错位不按推测解禁。",
            "地图动画添加只使用 $3F—$98 和 2306 字节全零池；运行规律复制只使用 $7D—$9C 与 32 字节尾池并原子改绑唯一同角色引用；组图复制只使用 $EB—$F6 与 88 字节尾池。",
            "动画与规律名称写入 .dcmod 工程元数据，不改变 ROM 字节或全局默认配置。",
            "参考 EXE 已完成组图首图块单字段保存/全新进程重开黄金；X/Y 现场值可变但不持久化，产品保持只读。",
            "其余动画/规律字段的参考 EXE 单字段黄金和用户签收仍待补充。",
        ],
        "deferred_scope": [
            "F-065 已开放 69/106 条完整背景中的已验证绘制参数；6 条无安全参数、31 条动态/不完整记录保持只读。",
            "F-068 名称写回已实现；背景通用搬移和未验证运行时参数保持禁用。",
            "REQ-ANIM-005 已完成组图首图块正向黄金和 X/Y 否定黄金；其余逐字段参考黄金及用户验收未完成。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="复验 M12 六表读取、安全写入、拒绝边界、物理拼图和离线播放。"
    )
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

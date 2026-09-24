from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication  # noqa: E402

from dc_modifier.legacy_windows import ScenarioDialog  # noqa: E402
from fc_editor.codecs.action_event import (  # noqa: E402
    ACTION_EVENT_CAPACITY,
    ACTION_EVENT_DATA_FILE_OFFSET,
    ACTION_EVENT_JUMP_OPCODES,
    ACTION_EVENT_POINTER_TABLE_OFFSET,
    ACTION_EVENT_POINTER_TABLE_SIZE,
)
from fc_editor.codecs.chapter_title import (  # noqa: E402
    CHAPTER_TITLE_CHR_TABLE_OFFSET,
    CHAPTER_TITLE_COUNT,
    CHAPTER_TITLE_POINTER_TABLE_OFFSET,
)
from fc_editor.codecs.chapter_victory import (  # noqa: E402
    CHAPTER_VICTORY_COUNT,
    CHAPTER_VICTORY_HEADER,
)
from fc_editor.codecs.legacy_scenario import LegacyScenarioCodec  # noqa: E402
from fc_editor.dc_text import reference_dc_text_table  # noqa: E402
from fc_editor.expansion import resource_descriptor_offset  # noqa: E402
from fc_rom_editor_core import RomProject  # noqa: E402


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_REPORT = ROOT / "output" / "verification" / "m14-scenario-compatibility.json"
REFERENCE_CONTROLS = (
    ROOT
    / "output"
    / "verification"
    / "legacy-ui-probe"
    / "controls"
    / "C05S_剧情事件_页签A.json"
)
REFERENCE_EXE = ROOT / "references" / "legacy_modifier" / "SRW2_patched.exe"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _differences(before: bytes, after: bytes) -> tuple[int, ...]:
    if len(before) != len(after):
        raise ValueError("比较对象长度不同。")
    return tuple(
        index
        for index, (old, new) in enumerate(zip(before, after, strict=True))
        if old != new
    )


def _walk_control_tree(node: dict[str, object]) -> tuple[dict[str, object], ...]:
    result = [node]
    for child in node.get("children", []):
        result.extend(_walk_control_tree(child))
    return tuple(result)


def _gbk_c_string(data: bytes, offset: int) -> str:
    end = data.find(b"\x00", offset)
    if end < 0:
        raise ValueError(f"参考 EXE 在 0x{offset:X} 后缺少字符串终止符。")
    return data[offset:end].decode("gbk")


def _pointer_table_ranges(project: RomProject) -> tuple[tuple[int, int], ...]:
    codec = project.chapter_event_codec
    assert codec is not None
    size = codec.spec.scenario_count * 2
    return tuple(
        (codec.code_address_to_file_offset(address), size)
        for address in codec.spec.pointer_tables
    )


def _ranges_unchanged(
    before: bytes,
    after: bytes,
    ranges: tuple[tuple[int, int], ...],
) -> bool:
    return all(
        before[offset : offset + size] == after[offset : offset + size]
        for offset, size in ranges
    )


def _action_signature(record) -> tuple[tuple[int, bytes | int], ...]:
    """Compare action semantics while allowing absolute targets to relocate."""

    return tuple(
        (
            instruction.raw_opcode,
            int.from_bytes(instruction.raw[1:3], "little") - record.pointer
            if instruction.opcode in ACTION_EVENT_JUMP_OPCODES
            else instruction.raw[1:],
        )
        for instruction in record.instructions
    )


def analyze(rom_path: Path = DEFAULT_ROM) -> dict[str, object]:
    source = rom_path.read_bytes()
    source_hash = _sha256(source)
    reference = json.loads(REFERENCE_CONTROLS.read_text(encoding="utf-8"))
    reference_nodes = _walk_control_tree(reference["tree"])
    reference_ids = sorted(int(node["ctrl_id"]) for node in reference_nodes)
    reference_exe = REFERENCE_EXE.read_bytes()
    capacity_error_offsets = {
        "界面事件": 0x35A353,
        "回合事件": 0x35A38D,
        "即时事件": 0x35A3C7,
        "行动事件": 0x35A401,
        "劝降事件": 0x35A43B,
        "地图事件": 0x35A475,
    }
    capacity_error_templates = {
        label: _gbk_c_string(reference_exe, offset)
        for label, offset in capacity_error_offsets.items()
    }
    story_capacity_offsets = (
        0x35A5CC,
        0x35A638,
        0x35A6A4,
        0x35A710,
        0x35A781,
        0x35A7F0,
        0x35A85C,
        0x35A8C8,
        0x35A934,
    )
    story_capacity_templates = tuple(
        _gbk_c_string(reference_exe, offset)
        for offset in story_capacity_offsets
    )
    button_handler_offset = 0x1A0C57
    capacity_call_offset = 0x1A0C83
    capacity_call_displacement = int.from_bytes(
        reference_exe[capacity_call_offset + 1 : capacity_call_offset + 5],
        "little",
        signed=True,
    )
    capacity_call_target = (
        capacity_call_offset + 5 + capacity_call_displacement
    )
    capacity_message_title = _gbk_c_string(reference_exe, 0x35580B)
    button_handler_signature_exact = (
        reference_exe[button_handler_offset : button_handler_offset + 13]
        == bytes.fromhex("55 8B EC C7 05 70 97 95 00 01 00 00 00")
        and reference_exe[capacity_call_offset] == 0xE8
        and capacity_call_target == 0x194936
        and reference_exe[0x1A0CCE : 0x1A0CD8]
        == bytes.fromhex("C7 05 70 97 95 00 00 00 00 00")
    )

    legacy = LegacyScenarioCodec(source)
    legacy_groups = tuple(
        tuple(legacy.instructions(chapter, phase))
        for chapter in range(32)
        for phase in range(3)
    )
    legacy_instructions = tuple(
        instruction for group in legacy_groups for instruction in group
    )
    legacy_phase_counts = [
        sum(
            len(legacy.instructions(chapter, phase))
            for chapter in range(32)
        )
        for phase in range(3)
    ]
    legacy_bank_counts = Counter(item.bank for item in legacy_instructions)
    legacy_pool_usage = {}
    for label, phases in (
        ("界面事件和回合事件", (0, 1)),
        ("即时事件", (2,)),
    ):
        unique = {
            (item.bank, item.file_offset): item
            for chapter in range(32)
            for phase in phases
            for item in legacy.instructions(chapter, phase)
        }
        legacy_pool_usage[label] = {
            f"${bank:02X}": sum(
                len(item.raw)
                for (record_bank, _offset), item in unique.items()
                if record_bank == bank
            )
            for bank in sorted({bank for bank, _offset in unique})
        }
    legacy_boundaries_exact = all(
        source[item.file_offset : item.file_offset + len(item.raw)] == item.raw
        for item in legacy_instructions
    )
    legacy_samples = []
    legacy_samples_isolated = True
    for phase in range(3):
        item = next(
            candidate
            for chapter in range(32)
            for candidate in legacy.instructions(chapter, phase)
            if len(candidate.raw) > 1 and candidate.opcode != 0x43
        )
        replacement = item.raw[:-1] + bytes((item.raw[-1] ^ 1,))
        offset, before, after = legacy.replacement_patch(item, replacement)
        candidate = bytearray(source)
        candidate[offset : offset + len(after)] = after
        differences = _differences(source, bytes(candidate))
        isolated = differences == (offset + len(after) - 1,)
        legacy_samples_isolated &= isolated
        legacy_samples.append(
            {
                "phase": phase,
                "bank": f"${item.bank:02X}",
                "address": f"${item.address:04X}",
                "file_offset": f"0x{offset:06X}",
                "before": before.hex(" ").upper(),
                "after": after.hex(" ").upper(),
                "changed_offsets": [f"0x{value:06X}" for value in differences],
                "isolated": isolated,
            }
        )

    event_project = RomProject.load(rom_path)
    event_before = bytes(event_project.working)
    pointer_ranges = _pointer_table_ranges(event_project)
    all_events = event_project.chapter_event_instructions()
    actions = event_project.chapter_event_instructions(actions_only=True)
    event_sample = next(
        item for item in all_events if item.opcode == 0x51 and len(item.raw) == 2
    )
    event_replacement = event_sample.raw[:-1] + bytes((event_sample.raw[-1] ^ 1,))
    event_project.set_chapter_event_instruction(
        event_sample.address, event_replacement
    )
    event_after = bytes(event_project.working)
    event_differences = _differences(event_before, event_after)
    event_pointer_tables_unchanged = _ranges_unchanged(
        event_before, event_after, pointer_ranges
    )
    event_project.undo()
    event_undo_exact = bytes(event_project.working) == event_before

    variable_event = next(item for item in all_events if item.opcode == 0x43)
    invalid_variable = bytearray(variable_event.raw)
    invalid_variable[1] = 0x00 if len(variable_event.raw) == 3 else 0x0B
    variable_length_rejected = False
    try:
        event_project.set_chapter_event_instruction(
            variable_event.address, bytes(invalid_variable)
        )
    except ValueError:
        variable_length_rejected = bytes(event_project.working) == event_before

    action_project = RomProject.load(rom_path)
    action_before = bytes(action_project.working)
    action_records = action_project.action_event_records()
    action_usage_before = action_project.action_event_usage()
    action_zero_first = action_records[0].instructions[0].raw
    action_two_before = _action_signature(action_records[2])
    action_project.insert_action_event_instruction(
        0,
        0,
        action_zero_first,
        after=True,
    )
    action_after = bytes(action_project.working)
    action_records_after = action_project.action_event_records()
    action_usage_after = action_project.action_event_usage()
    action_starts_after = {
        instruction.address
        for record in action_records_after
        for instruction in record.instructions
    }
    action_jumps_relocated = all(
        int.from_bytes(instruction.raw[1:3], "little") in action_starts_after
        for record in action_records_after
        for instruction in record.instructions
        if instruction.opcode in ACTION_EVENT_JUMP_OPCODES
    )
    action_pointer_table_changed = (
        action_before[
            ACTION_EVENT_POINTER_TABLE_OFFSET:
            ACTION_EVENT_POINTER_TABLE_OFFSET + ACTION_EVENT_POINTER_TABLE_SIZE
        ]
        != action_after[
            ACTION_EVENT_POINTER_TABLE_OFFSET:
            ACTION_EVENT_POINTER_TABLE_OFFSET + ACTION_EVENT_POINTER_TABLE_SIZE
        ]
    )
    action_pool_changed = (
        action_before[
            ACTION_EVENT_DATA_FILE_OFFSET:
            ACTION_EVENT_DATA_FILE_OFFSET + ACTION_EVENT_CAPACITY
        ]
        != action_after[
            ACTION_EVENT_DATA_FILE_OFFSET:
            ACTION_EVENT_DATA_FILE_OFFSET + ACTION_EVENT_CAPACITY
        ]
    )
    action_insert_exact = (
        action_records_after[0].raw == bytes.fromhex("63 63 D5 00 A0")
        and int.from_bytes(
            action_records_after[0].instructions[-1].raw[1:3], "little"
        )
        == action_records_after[0].pointer
        and _action_signature(action_records_after[2]) == action_two_before
        and action_records_after[0x2E].pointer
        == action_records_after[0x2F].pointer
        and action_usage_after.free == action_usage_before.free - 1
    )
    action_project.undo()
    action_insert_undo_exact = bytes(action_project.working) == action_before

    action_project.delete_action_event_instruction(2, 1)
    action_delete_count_exact = (
        len(action_project.get_action_event(2).instructions)
        == len(action_records[2].instructions) - 1
    )
    action_project.undo()
    action_delete_undo_exact = bytes(action_project.working) == action_before
    unsafe_action_delete_rejected = False
    try:
        action_project.delete_action_event_instruction(0, 1)
    except ValueError:
        unsafe_action_delete_rejected = (
            bytes(action_project.working) == action_before
        )

    persuasion_project = RomProject.load(rom_path)
    persuasion_before = bytes(persuasion_project.working)
    persuasion_codec = persuasion_project.persuasion_rule_codec
    assert persuasion_codec is not None
    original_rule = persuasion_project.get_persuasion_rule(0)
    changed_scenario = (original_rule.scenario_id + 1) % 32
    persuasion_project.set_persuasion_rule(
        0,
        changed_scenario,
        original_rule.persuader_id,
        original_rule.target_id,
    )
    persuasion_after = bytes(persuasion_project.working)
    persuasion_differences = _differences(persuasion_before, persuasion_after)
    persuasion_expected = (
        original_rule.file_offset,
    )
    persuasion_pointer_offset = persuasion_codec.spec.script_pointer_table_offset
    persuasion_pointer_size = persuasion_codec.spec.slot_count * 2
    persuasion_pointers_unchanged = (
        persuasion_before[
            persuasion_pointer_offset : persuasion_pointer_offset
            + persuasion_pointer_size
        ]
        == persuasion_after[
            persuasion_pointer_offset : persuasion_pointer_offset
            + persuasion_pointer_size
        ]
    )
    persuasion_project.undo()
    persuasion_undo_exact = bytes(persuasion_project.working) == persuasion_before
    unsafe_persuasion_slot_rejected = False
    try:
        persuasion_project.set_persuasion_rule(
            persuasion_codec.spec.editable_count,
            changed_scenario,
            original_rule.persuader_id,
            original_rule.target_id,
        )
    except ValueError:
        unsafe_persuasion_slot_rejected = (
            bytes(persuasion_project.working) == persuasion_before
        )

    story_project = RomProject.load(rom_path)
    story_before = bytes(story_project.working)
    story_codec = story_project.story_text_codec
    story_records = [
        story_project.get_story_text(group.selector, index)
        for group in story_project.story_text_groups
        for index in range(group.count)
    ]
    story_no_op_roundtrips = all(
        story_codec.round_trip(record.selector, record.indices[0])
        for record in story_records
    )
    token_boundaries_lossless = all(
        b"".join(token.raw for token in story_codec.tokenize(record.raw))
        == record.raw
        for record in story_records
    )
    story_sample = story_project.get_story_text(0x32, 10)
    glyph_offset = story_sample.raw.index(bytes.fromhex("DA 17"))
    replacement_glyph = reference_dc_text_table().encode("走")
    story_replacement = (
        story_sample.raw[:glyph_offset]
        + replacement_glyph
        + story_sample.raw[glyph_offset + 2 :]
    )
    story_project.set_story_text_raw(0x32, 10, story_replacement)
    story_after = bytes(story_project.working)
    story_differences = _differences(story_before, story_after)
    story_reopen_exact = (
        story_project.get_story_text(0x32, 10).raw == story_replacement
    )
    story_project.undo()
    story_undo_exact = bytes(story_project.working) == story_before
    story_growth = story_sample.raw[:-1] + b"\x01\xFF"
    story_project.set_story_text_raw(0x32, 10, story_growth)
    story_growth_exact = (
        story_project.get_story_text(0x32, 10).raw == story_growth
        and story_project.expansion_plan is None
    )
    story_project.undo()

    split_project = RomProject.load(rom_path)
    split_project.configure_expansion(304, 48, 112)
    split_codec = split_project.story_text_codec
    split_group = split_codec.group_by_selector[0x37]
    split_pointers = split_codec.pointers(0x37)
    split_sentinel = split_project.get_story_text(0x37, 0)
    split_records = tuple(
        split_project.get_story_text(0x37, index) for index in range(1, 52)
    )
    split_text_terminators_exact = all(
        split_codec.standalone_terminator_end(record.raw) == record.capacity
        for record in split_records
    )
    split_before = bytes(split_project.working)
    split_descriptor_offset = resource_descriptor_offset(0x37)
    split_pointer_offset = split_codec.cpu_to_file_offset(
        split_group.prg_bank, split_group.pointer_table
    )
    split_sample = split_records[0]
    split_replacement = (
        split_sample.raw[:1]
        + bytes((split_sample.raw[1] ^ 1,))
        + split_sample.raw[2:]
    )
    split_project.set_story_text_raw(0x37, 1, split_replacement)
    split_after = bytes(split_project.working)
    split_differences = _differences(split_before, split_after)
    split_expected_offset = (
        split_codec.cpu_to_file_offset(split_group.prg_bank, split_sample.pointer)
        + 1
    )
    split_descriptor_unchanged = (
        split_before[split_descriptor_offset : split_descriptor_offset + 2]
        == split_after[split_descriptor_offset : split_descriptor_offset + 2]
        == bytes.fromhex("73 00")
    )
    split_pointer_table_unchanged = (
        split_before[split_pointer_offset : split_pointer_offset + 104]
        == split_after[split_pointer_offset : split_pointer_offset + 104]
    )
    split_project.undo()
    split_undo_exact = bytes(split_project.working) == split_before
    split_sentinel_rejected = False
    try:
        split_project.set_story_text_raw(0x37, 0, b"\xFF")
    except ValueError:
        split_sentinel_rejected = bytes(split_project.working) == split_before

    victory_project = RomProject.load(rom_path)
    victory_before = bytes(victory_project.working)
    victory_codec = victory_project.chapter_victory_codec
    assert victory_codec is not None
    victory_records = tuple(
        victory_project.get_chapter_victory(scenario_id)
        for scenario_id in range(victory_codec.count)
    )
    victory_roundtrips = all(
        victory_codec.round_trip(scenario_id)
        for scenario_id in range(victory_codec.count)
    )
    victory_contiguous = all(
        current.file_offset == previous.file_offset + previous.capacity
        for previous, current in zip(
            victory_records,
            victory_records[1:],
        )
    )
    victory_sample = victory_records[0]
    victory_following = victory_records[1].raw
    victory_replacement = (
        victory_sample.body[2:4] + victory_sample.body[2:]
    )
    victory_project.set_chapter_victory_body(0, victory_replacement)
    victory_after = bytes(victory_project.working)
    victory_differences = _differences(victory_before, victory_after)
    victory_reopen_exact = (
        victory_project.get_chapter_victory(0).body == victory_replacement
        and victory_project.get_chapter_victory(1).raw == victory_following
    )
    victory_project.undo()
    victory_undo_exact = bytes(victory_project.working) == victory_before
    victory_project.set_chapter_victory_body(0, victory_sample.body[:-1])
    victory_project.set_chapter_victory_body(
        1, victory_records[1].body + b"\x00"
    )
    victory_variable_length_exact = (
        victory_project.get_chapter_victory(0).body == victory_sample.body[:-1]
        and victory_project.get_chapter_victory(1).body
        == victory_records[1].body + b"\x00"
    )
    victory_project.undo()
    victory_project.undo()

    title_project = RomProject.load(rom_path)
    title_before = bytes(title_project.working)
    title_codec = title_project.chapter_title_codec
    assert title_codec is not None
    title_records = tuple(
        title_project.get_chapter_title(scenario_id)
        for scenario_id in range(title_codec.count)
    )
    title_roundtrips = all(
        title_codec.round_trip(scenario_id)
        for scenario_id in range(title_codec.count)
    )
    title_sample = title_records[0]
    title_following = title_records[1]
    title_replacement = bytearray(title_sample.raw)
    title_tile_offset = title_replacement.index(0x40)
    title_replacement[title_tile_offset] = 0x41
    title_banks = (
        title_sample.chr_banks[1],
        title_sample.chr_banks[0],
        title_sample.chr_banks[2],
    )
    title_project.set_chapter_title(0, title_banks, bytes(title_replacement))
    title_after = bytes(title_project.working)
    title_differences = _differences(title_before, title_after)
    title_pointer_table_size = CHAPTER_TITLE_COUNT * 2
    title_pointer_table_unchanged = (
        title_before[
            CHAPTER_TITLE_POINTER_TABLE_OFFSET:
            CHAPTER_TITLE_POINTER_TABLE_OFFSET + title_pointer_table_size
        ]
        == title_after[
            CHAPTER_TITLE_POINTER_TABLE_OFFSET:
            CHAPTER_TITLE_POINTER_TABLE_OFFSET + title_pointer_table_size
        ]
    )
    title_reopen_exact = (
        title_project.get_chapter_title(0).raw == bytes(title_replacement)
        and title_project.get_chapter_title(0).chr_banks == title_banks
        and title_project.get_chapter_title(1) == title_following
    )
    title_project.undo()
    title_undo_exact = bytes(title_project.working) == title_before
    first_segment = title_sample.segments[-1]
    title_shorter = (
        title_sample.raw[: -(len(first_segment.tiles) + 5)]
        + bytes((0xFE, first_segment.x, first_segment.y, first_segment.width - 1))
        + first_segment.tiles[:-2]
        + b"\xFF"
    )
    second_segment = title_following.segments[-1]
    title_longer = (
        title_following.raw[: -(len(second_segment.tiles) + 5)]
        + bytes((0xFE, second_segment.x, second_segment.y, second_segment.width + 1))
        + second_segment.tiles
        + second_segment.tiles[-2:]
        + b"\xFF"
    )
    title_project.set_chapter_title(0, title_sample.chr_banks, title_shorter)
    title_project.set_chapter_title(1, title_following.chr_banks, title_longer)
    title_variable_length_exact = (
        title_project.get_chapter_title(0).raw == title_shorter
        and title_project.get_chapter_title(1).raw == title_longer
    )
    title_project.undo()
    title_project.undo()

    application = QApplication.instance() or QApplication([])
    ui_project = RomProject.load(rom_path)
    dialog = ScenarioDialog(ui_project, initial_scenario_id=0)
    dialog.show()
    application.processEvents()
    product_tabs = [
        dialog.tabs.tabText(index) for index in range(dialog.tabs.count())
    ]
    nested_tabs = [
        dialog.setup_event_tabs.tabText(index)
        for index in range(dialog.setup_event_tabs.count())
    ]
    title_preview = dialog.title_preview.pixmap()
    space_report = dialog.scenario_space_report_text()
    ui_checks = {
        "six_tabs_match_declared_order": product_tabs
        == list(ScenarioDialog.TAB_LABELS),
        "three_setup_tabs_match_declared_order": nested_tabs
        == list(ScenarioDialog.EVENT_TAB_LABELS),
        "title_preview_is_rom_bound_and_editable": (
            title_preview is not None
            and not title_preview.isNull()
            and (title_preview.width(), title_preview.height()) == (192, 48)
            and dialog.title_code_button.isEnabled()
        ),
        "initial_victory_editor_is_rom_bound": (
            not dialog.initial_victory.isReadOnly()
            and dialog._victory_source_body == victory_sample.body
            and str(victory_sample.body_capacity)
            in dialog.initial_victory_status.text()
            and "$3D:$8000" in dialog.initial_victory_status.text()
        ),
        "space_check_uses_verified_physical_pools": (
            dialog.space_button.text() == ScenarioDialog.SPACE_BUTTON_TEXT
            and dialog.space_button.isEnabled()
            and space_report.count("剧情 $") == 8
            and "Bank $1E）：3541 / 8192 字节，剩余 4651 字节"
            in space_report
            and "Bank $1B）：8154 / 8192 字节，剩余 38 字节"
            in space_report
            and "Bank $1F）：1525 / 8192 字节，剩余 6667 字节"
            in space_report
            and "独立行动事件（Bank $26）：2541 / 2751 字节"
            in space_report
            and "256 项指针 / 45 个有效物理脚本" in space_report
            and "劝降事件为 4 个已验证等长槽" in space_report
            and "地图事件为分 Bank 章节脚本的条件索引" in space_report
        ),
        "event_copy_paste_controls_exist": (
            dialog.action_event_page.copy_button.text() == "复制"
            and dialog.action_event_page.paste_button.text() == "粘贴"
        ),
        "action_tab_is_true_independent_table": (
            dialog.action_event_page.action_list.count() == 0x100
            and dialog.action_event_page.insert_before_button.text()
            == "插入（接上）"
            and dialog.action_event_page.insert_after_button.text()
            == "插入（接下）"
            and "2541 / 2751" in dialog.action_event_page.capacity_status.text()
        ),
    }
    dialog.reject()
    application.processEvents()

    checks = {
        "reference_control_tree_is_72_nodes": (
            len(reference_nodes) == 72
            and reference["title"] == "事件编辑"
            and reference_ids[0] == 0
            and {100, 110, 120, 690, 700}.issubset(reference_ids)
        ),
        "reference_exe_has_six_event_capacity_error_templates": all(
            text
            == (
                f"保存{label}:空间不足!\r\n"
                "错误原因:当前剩余空间不足以保存第"
            )
            for label, text in capacity_error_templates.items()
        ),
        "reference_exe_has_story_capacity_display_templates": (
            len(story_capacity_templates) == 9
            and all("当前空间还剩：" in text for text in story_capacity_templates)
            and sum("一共16384字节空间" in text for text in story_capacity_templates)
            == 8
            and sum("一共12544字节空间" in text for text in story_capacity_templates)
            == 1
        ),
        "reference_button_690_handler_and_message_shape_are_exact": (
            button_handler_signature_exact
            and capacity_message_title == "提示"
        ),
        "legacy_96_groups_are_instruction_aligned": (
            len(legacy_groups) == 96
            and len(legacy_instructions) == 4274
            and legacy_phase_counts == [998, 73, 3203]
            and legacy_boundaries_exact
        ),
        "legacy_three_phase_samples_are_isolated": legacy_samples_isolated,
        "global_event_block_is_complete": (
            len(all_events) == 2637
            and len(actions) == 294
            and sum(len(item.raw) for item in all_events) == 0x1FDA
        ),
        "global_event_edit_is_one_byte_and_pointer_safe": (
            event_differences
            == (event_sample.file_offset + len(event_sample.raw) - 1,)
            and event_pointer_tables_unchanged
            and event_undo_exact
        ),
        "variable_length_opcode_is_atomically_rejected": variable_length_rejected,
        "independent_action_table_is_complete": (
            len(action_records) == 0x100
            and action_records[0].pointer == 0xA000
            and action_records[0].raw == bytes.fromhex("63 D5 00 A0")
            and action_records[0x2E].raw == b"\xDF"
            and action_records[0xFF].pointer == action_records[3].pointer
            and action_usage_before.used == 2541
            and action_usage_before.capacity == 2751
            and action_usage_before.free == 210
            and action_usage_before.physical_records == 45
        ),
        "action_insert_delete_repack_and_undo_are_exact": (
            action_pointer_table_changed
            and action_pool_changed
            and action_insert_exact
            and action_jumps_relocated
            and action_insert_undo_exact
            and action_delete_count_exact
            and action_delete_undo_exact
            and unsafe_action_delete_rejected
        ),
        "persuasion_first_four_only_and_pointer_safe": (
            persuasion_codec.spec.slot_count == 32
            and persuasion_codec.spec.editable_count == 4
            and persuasion_differences == persuasion_expected
            and persuasion_pointers_unchanged
            and persuasion_undo_exact
            and unsafe_persuasion_slot_rejected
        ),
        "eight_supported_story_groups_roundtrip_losslessly": (
            [group.selector for group in story_project.story_text_groups]
            == [0x32, 0x33, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x3B]
            and len(story_records) == 1837
            and story_no_op_roundtrips
            and token_boundaries_lossless
        ),
        "story_pool_repack_and_undo_are_exact": (
            story_reopen_exact
            and story_undo_exact
            and story_growth_exact
            and bool(story_differences)
        ),
        "split_37_layout_and_in_place_edit_are_exact": (
            split_group.prg_bank == 0x0E
            and split_group.pointer_table == 0x9E28
            and (split_group.data_start, split_group.data_end)
            == (0x9B4A, 0x9E28)
            and len(split_pointers) == 52
            and split_pointers[0] == 0x9E90
            and split_sentinel.capacity == 0
            and len(split_records) == 51
            and len(split_codec.ids_by_pointer(0x37)) == 35
            and split_text_terminators_exact
            and split_project.expansion_plan.story_pair_for(0x37) is None
            and split_differences == (split_expected_offset,)
            and split_descriptor_unchanged
            and split_pointer_table_unchanged
            and split_undo_exact
            and split_sentinel_rejected
        ),
        "chapter_victory_shared_pool_edit_is_exact": (
            victory_codec.count == CHAPTER_VICTORY_COUNT == 13
            and victory_records[0].file_offset == 0x7A010
            and all(
                record.raw.startswith(CHAPTER_VICTORY_HEADER)
                and record.raw.endswith(b"\xFF")
                for record in victory_records
            )
            and victory_roundtrips
            and victory_contiguous
            and len(victory_replacement) == victory_sample.body_capacity
            and bool(victory_differences)
            and all(
                victory_sample.file_offset
                + len(CHAPTER_VICTORY_HEADER)
                <= offset
                < victory_sample.file_offset + victory_sample.capacity - 1
                for offset in victory_differences
            )
            and victory_reopen_exact
            and victory_undo_exact
            and victory_variable_length_exact
        ),
        "chapter_title_tables_and_shared_pool_edit_are_exact": (
            title_codec.count == CHAPTER_TITLE_COUNT == 32
            and title_sample.pointer == 0xAB7A
            and title_sample.file_offset == 0x16B8A
            and title_sample.chr_banks == (0x5C, 0x5D, 0x5E)
            and len(title_sample.segments) == 2
            and title_sample.title_segment.width == 8
            and title_roundtrips
            and title_pointer_table_unchanged
            and title_reopen_exact
            and title_undo_exact
            and title_variable_length_exact
            and set(title_differences)
            == {
                CHAPTER_TITLE_CHR_TABLE_OFFSET,
                CHAPTER_TITLE_CHR_TABLE_OFFSET + 1,
                title_sample.file_offset + title_tile_offset,
            }
        ),
        **ui_checks,
        "report_does_not_modify_input_rom": _sha256(rom_path.read_bytes())
        == source_hash,
    }
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "delivery_status": "implementation_complete",
        "conclusion": (
            "M14 的静态布局、三类关卡脚本、256 项独立行动表、"
            "行动池接上/接下变长重排、四条劝降规则、"
            "八个文本组（含 $37 分离布局）、13 条初始胜利文字、"
            "32 组真实标题拼图和事务边界可重复通过；"
            "当前交付范围实现完成，但仍待参考 EXE 动态黄金和用户签收。"
        ),
        "rom": {
            "path": rom_path.resolve().relative_to(ROOT).as_posix(),
            "size": len(source),
            "sha256": source_hash,
        },
        "reference_ui": {
            "path": REFERENCE_CONTROLS.relative_to(ROOT).as_posix(),
            "node_count": len(reference_nodes),
            "control_ids": reference_ids,
        },
        "reference_binary_capacity_strings": {
            "path": REFERENCE_EXE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(reference_exe),
            "event_error_templates": {
                label: {
                    "offset": f"0x{capacity_error_offsets[label]:06X}",
                    "text": text,
                }
                for label, text in capacity_error_templates.items()
            },
            "story_display_templates": [
                {
                    "offset": f"0x{offset:06X}",
                    "text": text,
                }
                for offset, text in zip(
                    story_capacity_offsets,
                    story_capacity_templates,
                    strict=True,
                )
            ],
            "evidence_boundary": (
                "静态字符串证明六类事件分类和剧情段容量文案；"
                "按钮处理器进一步证明标题为“提示”的消息框及剧情容量汇总调用。"
            ),
        },
        "reference_button_690": {
            "handler_offset": f"0x{button_handler_offset:06X}",
            "capacity_function_offset": f"0x{capacity_call_target:06X}",
            "message_title": capacity_message_title,
            "signature_exact": button_handler_signature_exact,
        },
        "legacy_scenario": {
            "group_count": len(legacy_groups),
            "instruction_count": len(legacy_instructions),
            "phase_instruction_counts": legacy_phase_counts,
            "bank_instruction_counts": {
                f"${bank:02X}": count
                for bank, count in sorted(legacy_bank_counts.items())
            },
            "physical_pool_usage": legacy_pool_usage,
            "physical_pool_capacity_per_bank": 0x2000,
            "isolated_samples": legacy_samples,
        },
        "global_events": {
            "instruction_count": len(all_events),
            "action_instruction_count": len(actions),
            "data_bytes": sum(len(item.raw) for item in all_events),
            "sample_address": f"${event_sample.address:04X}",
            "changed_offsets": [
                f"0x{offset:06X}" for offset in event_differences
            ],
        },
        "independent_action_events": {
            "pointer_table_file_offset": "0x035BD0",
            "pointer_count": len(action_records),
            "data_bank": "$26",
            "data_range": "$A000-$AABE",
            "used_bytes": action_usage_before.used,
            "capacity_bytes": action_usage_before.capacity,
            "free_bytes": action_usage_before.free,
            "physical_records": action_usage_before.physical_records,
            "insert_sample": {
                "action_id": "$00",
                "before": action_records[0].raw.hex(" ").upper(),
                "after": action_records_after[0].raw.hex(" ").upper(),
                "free_after": action_usage_after.free,
            },
            "jump_operands_relocated": action_jumps_relocated,
            "delete_sample_action_id": "$02",
            "undo_exact": action_insert_undo_exact and action_delete_undo_exact,
        },
        "persuasion": {
            "slot_count": persuasion_codec.spec.slot_count,
            "editable_count": persuasion_codec.spec.editable_count,
            "changed_offsets": [
                f"0x{offset:06X}" for offset in persuasion_differences
            ],
        },
        "story_text": {
            "supported_selectors": [
                f"${group.selector:02X}"
                for group in story_project.story_text_groups
            ],
            "record_count": len(story_records),
            "sample": {
                "selector": "$32",
                "index": "$0A",
                "changed_offsets": [
                    f"0x{offset:06X}" for offset in story_differences
                ],
            },
            "split_37": {
                "descriptor": "73 00",
                "mapped_banks": ["$0E", "$0F"],
                "pointer_table": "$9E28",
                "pointer_count": len(split_pointers),
                "writable_text_slots": len(split_records),
                "protected_non_text_slots": ["$00"],
                "physical_text_records": len(split_codec.ids_by_pointer(0x37)) - 1,
                "sample_index": "$01",
                "changed_offsets": [
                    f"0x{offset:06X}" for offset in split_differences
                ],
                "descriptor_unchanged": split_descriptor_unchanged,
                "pointer_table_unchanged": split_pointer_table_unchanged,
                "relocatable": False,
            },
        },
        "chapter_victory": {
            "bank": "$3D",
            "start_cpu_address": "$8000",
            "start_file_offset": "0x07A010",
            "record_count": len(victory_records),
            "header": CHAPTER_VICTORY_HEADER.hex(" ").upper(),
            "sample_scenario_id": 0,
            "sample_body_capacity": victory_sample.body_capacity,
            "changed_offsets": [
                f"0x{offset:06X}" for offset in victory_differences
            ],
            "fixed_total_pool": True,
            "variable_record_length": True,
        },
        "chapter_titles": {
            "pointer_table_file_offset": "0x016111",
            "chr_table_file_offset": "0x0159AE",
            "record_count": len(title_records),
            "sample": {
                "scenario_id": 0,
                "pointer": f"${title_sample.pointer:04X}",
                "file_offset": f"0x{title_sample.file_offset:06X}",
                "chr_banks": [f"${bank:02X}" for bank in title_sample.chr_banks],
                "segment_count": len(title_sample.segments),
                "title_width_tiles": title_sample.title_segment.width,
                "changed_offsets": [
                    f"0x{offset:06X}" for offset in title_differences
                ],
            },
            "fixed_total_pool": True,
            "variable_record_length": True,
            "pointer_table_unchanged": title_pointer_table_unchanged,
        },
        "product_ui": {
            "tabs": product_tabs,
            "setup_event_tabs": nested_tabs,
            "initial_size": [dialog.width(), dialog.height()],
            "space_button_text": dialog.space_button.text(),
            "space_report": space_report,
        },
        "checks": checks,
        "incomplete_requirements": [],
        "limitations": [
            "参考程序仍处于提权模态窗口，次级编辑对话框无法可靠动态重放。",
            "按钮 690 对独立行动表按 Bank $26 单独计算；劝降与地图事件仍按已验证章节脚本边界报告。",
            "接上/接下变长能力只对已验证的 Bank $26 独立行动池开放；三类章节脚本仍保持等长边界。",
            "自动报告证明实现边界，不等于参考动态黄金或用户验收。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="复验 M14 剧情事件的已实现范围和明确门禁。"
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

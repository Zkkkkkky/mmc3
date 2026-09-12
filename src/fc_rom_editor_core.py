from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from collections.abc import Iterable, Iterator

from fc_editor.codecs import (
    BattleMusicCodec,
    CharacterNameCodec,
    ChapterEventCodec,
    ChrCodec,
    CustomMusicCodec,
    LegacyGlobalDataCodec,
    MapCodec,
    MapTileAttributeCodec,
    MapTilesetAttributes,
    MapTrigger,
    MapTriggerCodec,
    PersuasionRule,
    PersuasionRuleCodec,
    ScenarioLayoutCodec,
    StoryTextCodec,
    UnitCodec,
    UnitNameReferenceCodec,
    UnitWeaponCodec,
    WeaponCodec,
    WeaponNameReferenceCodec,
)
from fc_editor.constants import (
    EXPECTED_BASE_SHA256,
    PRG_BANK_SIZE,
    UNIT_RECORD_SIZE,
    UNIT_WEAPON_SLOT_COUNT,
    WEAPON_RECORD_SIZE,
)
from fc_editor.errors import ProjectFormatError, RomFormatError
from fc_editor.dc_text import concise_dc_text, default_dc_text_table
from fc_editor.expansion import (
    AUTO_ALLOCATION_PREFIX,
    EXPANSION_METADATA_OFFSET,
    FLAG_MAPS,
    FLAG_MAP_TRIGGERS,
    FLAG_SCENARIOS,
    FLAG_UNITS,
    PARTITION_ALLOCATION_PREFIX,
    REOPEN_GUARD_PREFIX,
    STORY_SELECTORS,
    ExpansionPlan,
    bank_file_offset,
    consecutive_bank_segments,
    resource_descriptor_offset,
)
from fc_editor.expansion_map import (
    TERRAIN_BANK_DIRECTORY_OFFSET,
    link_map_resources,
    pack_map_resources,
    read_expanded_map_layout,
    read_expanded_map_payloads,
)
from fc_editor.expansion_story import (
    STORY_DATA_CAPACITY,
    STORY_DATA_START,
    build_story_group,
    extract_story_group,
    pack_story_group,
)
from fc_editor.expansion_unit import (
    ATTRIBUTE_TABLE,
    CORE_CAVE_END,
    CORE_CAVE_START,
    NAME_TABLE,
    SINGLE_RESOURCE_TABLE,
    SOURCE_CONFIGURATION_PAIR,
    SOURCE_CORE_PAIR,
    UNIT_ATTRIBUTE_SELECTOR,
    UNIT_BODY_SELECTOR,
    UNIT_CONFIGURATION_SELECTOR,
    UNIT_FRAGMENT_SELECTOR,
    UNIT_NAME_SELECTOR,
    UnitExpansionRecords,
    extract_unit_expansion_records,
    pack_unit_expansion,
)
from fc_editor.models import (
    FieldSpec,
    UNIT_FIELD_BY_KEY,
    UNIT_FIELDS,
    WEAPON_FIELD_BY_KEY as MODEL_WEAPON_FIELD_BY_KEY,
    WEAPON_FIELDS,
    MapRecord,
    ScenarioLayout,
    StoryTextRecord,
)
from fc_editor.project import ProjectDocument
from fc_editor.resources import Allocation, BankAllocator
from fc_editor.rom_image import RomImage
from fc_editor.services.validation import ValidationIssue, validate_project

FIELDS = UNIT_FIELDS
FIELD_BY_KEY = UNIT_FIELD_BY_KEY
WEAPON_FIELD_BY_KEY = MODEL_WEAPON_FIELD_BY_KEY


@dataclass(frozen=True)
class EditPatch:
    offset: int
    before: bytes
    after: bytes


@dataclass(frozen=True)
class EditHistoryEntry:
    description: str
    patches: tuple[EditPatch, ...]
    allocations_before: tuple[Allocation, ...] = ()
    allocations_after: tuple[Allocation, ...] = ()


@dataclass(frozen=True)
class ProjectSnapshot:
    data: bytes
    allocations: tuple[Allocation, ...]


@dataclass(frozen=True)
class BuildArtifacts:
    rom: Path
    ips: Path
    project: Path
    report: Path
    output_sha256: str
    changed_bytes: int


# Names used by the original Chinese localization.  Several IDs deliberately
# repeat because they represent transformed/story variants or share one record.
CONFIRMED_UNIT_ALIASES: dict[int, str] = {
    0x01: "盖塔",
    0x02: "盖塔1",
    0x03: "盖塔2",
    0x04: "盖塔3",
    0x05: "盖塔",
    0x06: "盖塔1",
    0x07: "盖塔2",
    0x08: "盖塔3",
    0x09: "刚达",
    0x0A: "刚达（MA）",
    0x0B: "刚达Ⅱ",
    0x0C: "刚达Ⅱ（MA）",
    0x0D: "西马（MA）",
    0x0E: "西马",
    0x0F: "刚克",
    0x10: "刚克",
    0x11: "卡扎C",
    0x12: "卡扎C",
    0x13: "麦萨拉（MA）",
    0x14: "麦萨拉",
    0x15: "拉比",
    0x16: "拉比",
    0x17: "巴斯塔",
    0x18: "巴得",
    0x19: "巴斯塔",
    0x1A: "巴得",
    0x1B: "巴斯塔",
    0x1C: "巴得",
    0x1D: "金Z",
    0x1E: "魔神Z",
    0x1F: "金",
    0x20: "金",
    0x21: "金",
    0x22: "阿波罗A",
    0x23: "太勒",
    0x24: "道尔",
    0x25: "道尔",
    0x26: "盖塔Q",
    0x27: "博思",
    0x28: "博思",
    0x29: "博思",
    0x2A: "布达MZ",
    0x2B: "拉达K7",
    0x2C: "米巴",
    0x2D: "拉英X",
    0x2E: "诺巴M9",
    0x2F: "古塔",
    0x30: "撞击器",
    0x31: "布X1",
    0x32: "切克",
    0x33: "格尔",
    0x34: "邦巴",
    0x35: "基尔",
    0x36: "乍克",
    0x37: "古夫",
    0x38: "德姆",
    0x39: "加恩",
    0x3A: "雷克",
    0x3B: "比克",
    0x3C: "艾文",
    0x3D: "吉恩",
    0x3E: "吉恩（首）",
    0x3F: "斯特",
    0x40: "哈衣",
    0x41: "吉伯",
    0x42: "基奥",
    0x43: "马登",
    0x44: "帕拉",
    0x45: "巴依",
    0x46: "巴勒",
    0x47: "吉米",
    0x48: "盖马",
    0x49: "伯希",
    0x4A: "巴乌",
    0x4B: "加姆",
    0x4C: "希卡",
    0x4D: "伯利",
    0x4E: "基格",
    0x4F: "亚克托",
    0x50: "扎比",
    0x51: "阿尔",
    0x52: "比纳",
    0x53: "兹",
    0x54: "巴得",
    0x55: "扎依",
    0x56: "宰恩Ⅱ",
    0x57: "达衣",
    0x58: "希古",
    0x59: "麦卡",
    0x5A: "麦乔",
    0x5B: "科顿",
    0x5C: "坎普",
    0x5D: "埃尔",
    0x5E: "埃尔",
    0x5F: "导弹",
    0x60: "米巴X",
    0x61: "艾文",
    0x62: "古连",
    0x63: "斯帕",
    0x64: "古连",
    0x65: "双帕",
    0x66: "古连",
    0x67: "双帕",
    0x68: "钻帕",
    0x69: "德帕",
    0x6A: "麦塔斯",
    0x6B: "麦塔斯（MA）",
    0x6C: "麦塔斯",
    0x6D: "麦塔斯（MA）",
    0x6E: "麦塔斯",
    0x6F: "麦塔斯（MA）",
    0x70: "麦塔斯",
    0x71: "麦塔斯（MA）",
    0x72: "盖塔",
    0x73: "盖塔龙",
    0x74: "盖塔虎",
    0x75: "盖塔海神",
    0x76: "盖塔",
    0x77: "盖塔龙",
    0x78: "盖塔虎",
    0x79: "盖塔海神",
    0x7A: "盖塔",
    0x7B: "盖塔龙",
    0x7C: "盖塔虎",
    0x7D: "盖塔海神",
    0x7E: "刚达",
    0x7F: "阿马G",
}


# The DC ROM uses a different, expanded unit-name table.  These labels were
# cross-checked against the bundled expansion editor while it was reading the
# repository's reference ROM.  IDs omitted here intentionally point at the
# ROM's blank "-" name.
_DC_UNIT_ALIAS_GROUPS: dict[str, tuple[int, ...]] = {
    "盖塔": (0x01, 0x05, 0x48),
    "盖塔龙": (0x02, 0x06, 0x49, 0x93, 0x98, 0xB7),
    "盖塔虎": (0x03, 0x07, 0x4A, 0x94, 0x99, 0xB8),
    "盖塔海神": (0x04, 0x08, 0x4B, 0x95, 0x9A, 0xB9),
    "西奥妮": (0x09, 0x0A),
    "巴尔西昂修复型": (0x0B, 0x0C),
    "古兰森": (0x0D, 0x0E, 0xBE, 0xBF, 0xC0, 0xC1),
    "夏亚专用·扎古": (0x0F,),
    "吉恩号": (0x10,),
    "亚古特·多加": (0x11, 0x12),
    "帕拉斯": (0x13, 0x14),
    "玛拉塞": (0x15, 0x16),
    "卡扎C": (0x17, 0x19),
    "卡扎C（MA）": (0x18, 0x1A),
    "艾尔美斯": (0x1B, 0x1C, 0x68),
    "莱茵X1": (0x1D, 0x1E),
    "扎古III改": (0x1F, 0x8C),
    "扎古III": (0x20,),
    "龙飞": (0x21,),
    "精神力高达MK2": (0x22, 0x23, 0xA1),
    "大扎姆": (0x24, 0x80, 0xA7),
    "睿智之神": (0x25,),
    "量产型高达": (0x51,),
    "量产型魔神": (0x52, 0x6C),
    "量产型盖塔1": (0x53,),
    "量产型盖塔2": (0x54,),
    "量产型盖塔3": (0x55,),
    "盖塔Q": (0x56, 0x70),
    "德州牛仔": (0x57, 0x71),
    "阿弗洛蒂A": (0x58, 0x6E),
    "盖塔1": (0x59, 0x5E),
    "盖塔2": (0x5A, 0x5F),
    "盖塔3": (0x5B, 0x60),
    "机械蝴蝶鬼": (0x5C, 0x61),
    "白色要塞": (0x63,),
    "全装甲高达": (0x64,),
    "超级高达": (0x65, 0x7D),
    "高达MK-2": (0x66, 0x88),
    "高达MK-2·修理型": (0x67,),
    "魔神Z": (0x69, 0x6F),
    "波士机器人": (0x6A, 0x6D, 0xB6),
    "亚加玛": (0x73,),
    "新·亚加玛": (0x74,),
    "量产型F91": (0x75, 0x87),
    "量产型百式": (0x76, 0x7E),
    "古莲泰沙": (0x77, 0x7B),
    "斯佩沙": (0x78, 0x7C, 0xB3),
    "里克·大魔": (0x79, 0x86),
    "魔神Z（JS）": (0x81,),
    "BEAUDRIFER": (0x83,),
    "萨兰斯": (0x84,),
    "炮台": (0x8A,),
    "维基纳·基娜": (0x8B, 0xAD),
    "F91·觉醒": (0x8D, 0xAC),
    "巴德": (0x8E, 0x90),
    "杰诺巴": (0x92,),
    "塞巴斯塔": (0x96,),
    "米涅鲁巴X": (0x9C,),
    "大扎姆X": (0x9E, 0x9F),
    "梅坦加": (0xA2,),
    "尼伯龙根": (0xA3, 0xBC),
    "布拉格S1": (0xA4,),
    "吉姆特装型": (0xA5, 0xA8),
    "拉·凯拉姆": (0xAA,),
    "HIV高达": (0xAB,),
    "美塔斯": (0xAE,),
    "Z高达": (0xAF,),
    "ZZ高达（FA）": (0xB0,),
    "卡碧尼MKII": (0xB1, 0xB2),
    "精神高达": (0xB4,),
    "大魔神": (0xB5,),
    "普罗同": (0xBA,),
    "巴尔西昂": (0xC9,),
    "240以下NPC母舰备用": (0xF0,),
    "萨德兰": (0xF1, 0xF2),
}
CONFIRMED_DC_UNIT_ALIASES: dict[int, str] = {
    unit_id: name
    for name, unit_ids in _DC_UNIT_ALIAS_GROUPS.items()
    for unit_id in unit_ids
}
DC_UNIT_NAME_PROFILE_KEYS = frozenset(
    {"dc-famistudio-mmc5-v1", "dc-kuorong-mmc3-v1", "dc-kuorong-mmc3-v2"}
)


def mapper_number(header: bytes) -> int:
    return (header[6] >> 4) | (header[7] & 0xF0)


def compact_ids(ids: tuple[int, ...]) -> str:
    if not ids:
        return ""
    ranges: list[str] = []
    start = previous = ids[0]
    for value in ids[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(f"{start:02X}" if start == previous else f"{start:02X}–{previous:02X}")
        start = previous = value
    ranges.append(f"{start:02X}" if start == previous else f"{start:02X}–{previous:02X}")
    return ", ".join(ranges)


def make_ips(original: bytes, modified: bytes) -> bytes:
    if len(original) != len(modified):
        raise ValueError("IPS generation requires equal-sized ROM images")
    patch = bytearray(b"PATCH")
    position = 0
    while position < len(original):
        if original[position] == modified[position]:
            position += 1
            continue
        start = position
        while (
            position < len(original)
            and original[position] != modified[position]
            and position - start < 0xFFFF
        ):
            position += 1
        data = modified[start:position]
        patch.extend(start.to_bytes(3, "big"))
        patch.extend(len(data).to_bytes(2, "big"))
        patch.extend(data)
    patch.extend(b"EOF")
    return bytes(patch)


def apply_ips(original: bytes, patch: bytes) -> bytes:
    if not patch.startswith(b"PATCH"):
        raise ValueError("Invalid IPS header")
    result = bytearray(original)
    position = 5
    while patch[position : position + 3] != b"EOF":
        if position + 5 > len(patch):
            raise ValueError("Truncated IPS record")
        offset = int.from_bytes(patch[position : position + 3], "big")
        size = int.from_bytes(patch[position + 3 : position + 5], "big")
        position += 5
        if size:
            if position + size > len(patch):
                raise ValueError("Truncated IPS data")
            result[offset : offset + size] = patch[position : position + size]
            position += size
        else:
            if position + 3 > len(patch):
                raise ValueError("Truncated IPS RLE data")
            run_size = int.from_bytes(patch[position : position + 2], "big")
            value = patch[position + 2]
            position += 3
            result[offset : offset + run_size] = bytes((value,)) * run_size
    return bytes(result)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(path)
    finally:
        if temporary_name is not None:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


class RomProject:
    def __init__(self, path: Path, data: bytes) -> None:
        self.path = path
        self.rom_image = RomImage(data, path)
        self.original = self.rom_image.data
        self.working = bytearray(self.original)
        initial_plan = ExpansionPlan.from_bytes(self.working)
        self._initial_expansion_plan = initial_plan
        self._unit_name_baseline_pointers: tuple[int, ...] | None = None
        if initial_plan is not None and initial_plan.flags & FLAG_UNITS:
            if len(initial_plan.unit_banks) < 6:
                raise RomFormatError("机体扩展标志存在，但配额不足 48 KiB。")
            initial_core_bank = initial_plan.unit_banks[0]
            initial_name_bank = (
                initial_plan.unit_banks[8]
                if len(initial_plan.unit_banks) == 10
                else initial_core_bank
            )
            initial_name_table = (
                SINGLE_RESOURCE_TABLE
                if len(initial_plan.unit_banks) == 10
                else NAME_TABLE
            )
            self.base_unit_codec = UnitCodec(
                self.rom_image,
                self.original,
                pointer_table_offset=(
                    bank_file_offset(initial_core_bank) + ATTRIBUTE_TABLE - 0x8000
                ),
                pair_first_bank=initial_core_bank,
            )
            self.base_unit_name_codec = UnitNameReferenceCodec(
                self.rom_image,
                self.original,
                pointer_table_offset=(
                    bank_file_offset(initial_name_bank) + initial_name_table - 0x8000
                ),
                pair_first_bank=initial_name_bank,
            )
        else:
            self.base_unit_codec = UnitCodec(self.rom_image)
            self.base_unit_name_codec = UnitNameReferenceCodec(self.rom_image)
        if initial_plan is not None and initial_plan.flags & FLAG_UNITS:
            self._unit_name_baseline_pointers = (
                self._derive_unit_name_baseline_pointers(initial_plan)
            )
        self.unit_codec = self.base_unit_codec
        self.unit_name_codec = self.base_unit_name_codec
        self.base_unit_weapon_codec = (
            UnitWeaponCodec(
                self.rom_image,
                self.original,
                table_offset=(
                    self._expanded_unit_weapon_table_offset(initial_plan)
                    if initial_plan is not None and initial_plan.flags & FLAG_UNITS
                    else self.profile.unit_weapon_table_offset
                ),
            )
            if self.rom_image.profile.unit_weapon_table_offset is not None
            else None
        )
        self.unit_weapon_codec = self.base_unit_weapon_codec
        self.weapon_codec = WeaponCodec(self.rom_image)
        self.weapon_name_codec = (
            WeaponNameReferenceCodec(self.rom_image)
            if self.rom_image.profile.weapon_name_pointer_table_offset is not None
            else None
        )
        self.character_name_codec = (
            CharacterNameCodec(self.rom_image)
            if self.rom_image.profile.character_name_pointer_table_offset is not None
            else None
        )
        self.legacy_global_data_codec = (
            LegacyGlobalDataCodec(self.rom_image)
            if self.rom_image.profile.legacy_global_data is not None
            else None
        )
        self.map_tile_attribute_codec = (
            MapTileAttributeCodec
            if MapTileAttributeCodec.supports(self.original)
            else None
        )
        if initial_plan is not None and initial_plan.flags & FLAG_MAPS:
            initial_layout = read_expanded_map_layout(self.original)
            self.base_map_codec = MapCodec(
                self.rom_image,
                self.original,
                bank_table_offset=TERRAIN_BANK_DIRECTORY_OFFSET,
                record_locations=initial_layout.terrain,
            )
            self.base_scenario_layout_codec = ScenarioLayoutCodec(
                self.rom_image,
                self.original,
                record_locations=initial_layout.scenarios,
            )
            self.base_map_trigger_codec = MapTriggerCodec(
                self.rom_image,
                self.original,
                record_locations=initial_layout.triggers,
                expanded_capacity=len(initial_plan.map_banks) * PRG_BANK_SIZE,
            )
        else:
            self.base_map_codec = MapCodec(self.rom_image)
            self.base_scenario_layout_codec = ScenarioLayoutCodec(self.rom_image)
            self.base_map_trigger_codec = (
                MapTriggerCodec(self.rom_image)
                if self.rom_image.profile.map_triggers is not None
                else None
            )
        self.map_codec = self.base_map_codec
        self.scenario_layout_codec = self.base_scenario_layout_codec
        self.map_trigger_codec = self.base_map_trigger_codec
        self.chapter_event_codec = (
            ChapterEventCodec(self.rom_image)
            if self.rom_image.profile.chapter_events is not None
            else None
        )
        self.persuasion_rule_codec = (
            PersuasionRuleCodec(self.rom_image)
            if self.rom_image.profile.persuasion_rules is not None
            else None
        )
        initial_story_overrides = (
            {
                selector: pair[0]
                for selector in initial_plan.expanded_story_selectors
                if (pair := initial_plan.story_pair_for(selector)) is not None
            }
            if initial_plan is not None
            else {}
        )
        self.base_story_text_codec = StoryTextCodec(
            self.rom_image,
            self.original,
            group_bank_overrides=initial_story_overrides,
        )
        self.story_text_codec = self.base_story_text_codec
        self.battle_music_codec = (
            BattleMusicCodec(self.rom_image)
            if self.rom_image.profile.battle_music is not None
            else None
        )
        self.chr_codec = ChrCodec(self.rom_image)
        self.custom_music_codec = (
            CustomMusicCodec(self.rom_image)
            if self.rom_image.profile.custom_music_slots
            else None
        )
        self.resource_allocator = BankAllocator(self.rom_image.profile, self.original)
        if initial_plan is not None:
            self._reserve_plan_partitions(initial_plan)
            self._reserve_direct_reopen_guards(initial_plan)
        self.pointer_by_id = self.unit_codec.pointers
        self.ids_by_pointer = self.unit_codec.ids_by_pointer
        self._refresh_dynamic_codecs()
        self._undo_stack: list[EditHistoryEntry] = []
        self._redo_stack: list[EditHistoryEntry] = []
        self._transaction_depth = 0
        self._transaction_before: ProjectSnapshot | None = None
        self._transaction_description = ""
        self._read_only_output_roots: tuple[Path, ...] = ()

    def set_read_only_output_roots(self, roots: Iterable[str | Path]) -> None:
        self._read_only_output_roots = tuple(
            Path(root).expanduser().resolve() for root in roots
        )

    def _resolve_output_path(self, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve()
        for root in self._read_only_output_roots:
            if destination == root or root in destination.parents:
                raise ValueError(f"只读参考目录不能作为输出目标：{root}")
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "RomProject":
        resolved = Path(path).expanduser().resolve()
        return cls(resolved, resolved.read_bytes())

    @classmethod
    def load_project(
        cls,
        project_path: str | Path,
        base_rom_path: str | Path,
    ) -> "RomProject":
        document = ProjectDocument.load(project_path)
        project = cls.load(base_rom_path)
        project.working[:] = document.materialize(project.rom_image)
        project.resource_allocator = BankAllocator(
            project.profile,
            project.original,
            document.resource_allocations(project.rom_image),
        )
        plan = project.expansion_plan
        if plan is None and any(
            allocation.resource_id.startswith(PARTITION_ALLOCATION_PREFIX)
            for allocation in project.expansion_allocations
        ):
            raise ProjectFormatError("工程含自动分区，但 ROM 中没有容量规划表。")
        if plan is not None:
            project._reserve_plan_partitions(plan)
            if project._initial_expansion_plan is not None:
                project._reserve_direct_reopen_guards(plan)
        project._refresh_dynamic_codecs()
        errors = [issue for issue in project.validate() if issue.severity == "error"]
        if errors:
            raise ProjectFormatError(
                "工程完整性检查失败：\n"
                + "\n".join(issue.message for issue in errors)
            )
        return project

    @staticmethod
    def _diff_patches(before: bytes, after: bytes) -> tuple[EditPatch, ...]:
        if len(before) != len(after):
            raise ValueError("撤销快照大小不一致。")
        patches: list[EditPatch] = []
        position = 0
        while position < len(before):
            if before[position] == after[position]:
                position += 1
                continue
            start = position
            while position < len(before) and before[position] != after[position]:
                position += 1
            patches.append(EditPatch(start, before[start:position], after[start:position]))
        return tuple(patches)

    def _mutation_snapshot(self) -> ProjectSnapshot | None:
        if self._transaction_depth:
            return None
        return ProjectSnapshot(bytes(self.working), self.resource_allocator.allocations)

    def _finish_mutation(self, before: ProjectSnapshot | None, description: str) -> None:
        if before is None:
            return
        allocations_after = self.resource_allocator.allocations
        patches = self._diff_patches(before.data, bytes(self.working))
        if not patches and before.allocations == allocations_after:
            return
        self._undo_stack.append(
            EditHistoryEntry(
                description,
                patches,
                before.allocations,
                allocations_after,
            )
        )
        self._redo_stack.clear()

    @contextmanager
    def transaction(self, description: str) -> Iterator[None]:
        outermost = self._transaction_depth == 0
        if outermost:
            self._transaction_before = ProjectSnapshot(
                bytes(self.working), self.resource_allocator.allocations
            )
            self._transaction_description = description
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            if outermost and self._transaction_before is not None:
                self.working[:] = self._transaction_before.data
                self.resource_allocator = BankAllocator(
                    self.profile,
                    self.original,
                    self._transaction_before.allocations,
                )
                self._refresh_dynamic_codecs()
            raise
        finally:
            self._transaction_depth -= 1
            if outermost:
                before = self._transaction_before
                transaction_description = self._transaction_description
                self._transaction_before = None
                self._transaction_description = ""
                if before is not None:
                    self._finish_mutation(before, transaction_description)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    @property
    def undo_description(self) -> str:
        return self._undo_stack[-1].description if self._undo_stack else ""

    @property
    def redo_description(self) -> str:
        return self._redo_stack[-1].description if self._redo_stack else ""

    def undo(self) -> str:
        if not self._undo_stack:
            raise ValueError("没有可以撤销的操作。")
        entry = self._undo_stack.pop()
        for patch in entry.patches:
            self.working[patch.offset : patch.offset + len(patch.before)] = patch.before
        self.resource_allocator = BankAllocator(
            self.profile, self.original, entry.allocations_before
        )
        self._refresh_dynamic_codecs()
        self._redo_stack.append(entry)
        return entry.description

    def redo(self) -> str:
        if not self._redo_stack:
            raise ValueError("没有可以重做的操作。")
        entry = self._redo_stack.pop()
        for patch in entry.patches:
            self.working[patch.offset : patch.offset + len(patch.after)] = patch.after
        self.resource_allocator = BankAllocator(
            self.profile, self.original, entry.allocations_after
        )
        self._refresh_dynamic_codecs()
        self._undo_stack.append(entry)
        return entry.description

    @staticmethod
    def _validate_and_read_pointers(data: bytes) -> tuple[int, ...]:
        return UnitCodec(RomImage(data)).pointers

    @property
    def source_sha256(self) -> str:
        return self.rom_image.sha256

    @property
    def profile(self):
        return self.rom_image.profile

    @property
    def expansion_plan(self) -> ExpansionPlan | None:
        return ExpansionPlan.from_bytes(self.working)

    def _unit_pairs(self, plan: ExpansionPlan) -> tuple[tuple[int, int], ...]:
        banks = plan.unit_banks
        return tuple(
            (banks[index], banks[index + 1])
            for index in range(0, len(banks), 2)
        )

    def _expanded_unit_weapon_table_offset(self, plan: ExpansionPlan) -> int:
        if self.profile.unit_weapon_table_offset is None:
            raise RomFormatError("当前ROM没有机体武器表。")
        source_pair_offset = bank_file_offset(SOURCE_CONFIGURATION_PAIR)
        relative = self.profile.unit_weapon_table_offset - source_pair_offset
        if not 0 <= relative < PRG_BANK_SIZE * 2:
            raise RomFormatError("机体武器表不在已验证的配置 Bank 对。")
        return bank_file_offset(plan.unit_banks[2]) + relative

    def _derive_unit_name_baseline_pointers(
        self, plan: ExpansionPlan
    ) -> tuple[int, ...]:
        """Rebuild immutable reset targets from the retained stock resources."""

        template = bytearray(self.original)
        cave_start = bank_file_offset(SOURCE_CORE_PAIR) + CORE_CAVE_START - 0x8000
        cave_end = bank_file_offset(SOURCE_CORE_PAIR) + CORE_CAVE_END - 0x8000
        template[cave_start:cave_end] = bytes(cave_end - cave_start)
        records = extract_unit_expansion_records(template)
        packed = pack_unit_expansion(
            template,
            self._unit_pairs(plan),
            records=records,
        )
        return packed.name_baseline_pointers

    def _refresh_dynamic_codecs(self) -> None:
        """Rebind decoders after linker metadata, pointers, or undo state changes."""

        plan = ExpansionPlan.from_bytes(self.working)
        if plan is None:
            self.unit_codec = self.base_unit_codec
            self.unit_name_codec = self.base_unit_name_codec
            self.unit_weapon_codec = self.base_unit_weapon_codec
            self.map_codec = self.base_map_codec
            self.scenario_layout_codec = self.base_scenario_layout_codec
            self.map_trigger_codec = self.base_map_trigger_codec
            self.story_text_codec = self.base_story_text_codec
        else:
            if plan.flags & FLAG_UNITS:
                if len(plan.unit_banks) < 6:
                    raise RomFormatError("机体扩展标志存在，但配额不足 48 KiB。")
                if self._unit_name_baseline_pointers is None:
                    self._unit_name_baseline_pointers = (
                        self._derive_unit_name_baseline_pointers(plan)
                    )
                core_bank = plan.unit_banks[0]
                name_bank = (
                    plan.unit_banks[8]
                    if len(plan.unit_banks) == 10
                    else core_bank
                )
                name_table = (
                    SINGLE_RESOURCE_TABLE
                    if len(plan.unit_banks) == 10
                    else NAME_TABLE
                )
                self.unit_codec = UnitCodec(
                    self.rom_image,
                    self.working,
                    pointer_table_offset=(
                        bank_file_offset(core_bank) + ATTRIBUTE_TABLE - 0x8000
                    ),
                    pair_first_bank=core_bank,
                )
                self.unit_name_codec = UnitNameReferenceCodec(
                    self.rom_image,
                    self.working,
                    pointer_table_offset=(
                        bank_file_offset(name_bank) + name_table - 0x8000
                    ),
                    pair_first_bank=name_bank,
                    original_pointers=self._unit_name_baseline_pointers,
                )
                if self.profile.unit_weapon_table_offset is not None:
                    self.unit_weapon_codec = UnitWeaponCodec(
                        self.rom_image,
                        self.working,
                        table_offset=self._expanded_unit_weapon_table_offset(plan),
                    )
                else:
                    self.unit_weapon_codec = None
            else:
                self.unit_codec = self.base_unit_codec
                self.unit_name_codec = self.base_unit_name_codec
                self.unit_weapon_codec = self.base_unit_weapon_codec
            if plan.flags & FLAG_MAPS:
                required_flags = FLAG_MAPS | FLAG_SCENARIOS | FLAG_MAP_TRIGGERS
                if (plan.flags & required_flags) != required_flags:
                    raise RomFormatError("地图扩展状态不完整，缺少部署或事件绑定。")
                layout = read_expanded_map_layout(self.working)
                self.map_codec = MapCodec(
                    self.rom_image,
                    self.working,
                    bank_table_offset=TERRAIN_BANK_DIRECTORY_OFFSET,
                    record_locations=layout.terrain,
                )
                self.scenario_layout_codec = ScenarioLayoutCodec(
                    self.rom_image,
                    self.working,
                    record_locations=layout.scenarios,
                )
                self.map_trigger_codec = MapTriggerCodec(
                    self.rom_image,
                    self.working,
                    record_locations=layout.triggers,
                    expanded_capacity=len(plan.map_banks) * PRG_BANK_SIZE,
                )
            else:
                self.map_codec = self.base_map_codec
                self.scenario_layout_codec = self.base_scenario_layout_codec
                self.map_trigger_codec = self.base_map_trigger_codec
            overrides = {
                selector: pair[0]
                for selector in plan.expanded_story_selectors
                if (pair := plan.story_pair_for(selector)) is not None
            }
            self.story_text_codec = StoryTextCodec(
                self.rom_image,
                self.working,
                group_bank_overrides=overrides,
            )
        self.pointer_by_id = self.unit_codec.pointers
        self.ids_by_pointer = self.unit_codec.ids_by_pointer

    @property
    def unit_count(self) -> int:
        return self.profile.unit_count

    @property
    def weapon_count(self) -> int:
        return self.profile.weapon_count

    @property
    def map_count(self) -> int:
        return self.profile.map_count

    @property
    def scenario_count(self) -> int:
        return self.profile.scenario_count

    @property
    def story_text_groups(self):
        return self.story_text_codec.groups

    @property
    def supports_battle_music(self) -> bool:
        return self.battle_music_codec is not None

    @property
    def supports_legacy_global_data(self) -> bool:
        return self.legacy_global_data_codec is not None

    def _require_legacy_global_data_codec(self) -> LegacyGlobalDataCodec:
        if self.legacy_global_data_codec is None:
            raise ValueError("当前 ROM 的全局参数表尚未验证。")
        return self.legacy_global_data_codec

    def _apply_legacy_global_patches(
        self,
        patches: Iterable[tuple[int, bytes, bytes]],
        description: str,
    ) -> None:
        normalized = tuple(patches)
        with self.transaction(description):
            for offset, before, _after in normalized:
                current = bytes(self.working[offset : offset + len(before)])
                if current != before:
                    raise RomFormatError(f"{description}的 ROM 操作数已变化。")
            for offset, _before, after in normalized:
                self.working[offset : offset + len(after)] = after

    def get_double_hit_values(
        self, *, original: bool = False
    ) -> tuple[int, int, int]:
        codec = self._require_legacy_global_data_codec()
        source = self.original if original else self.working
        return codec.double_hit_values(source)

    def set_double_hit_values(self, values: Iterable[int]) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.double_hit_patches(self.working, values)
        self._apply_legacy_global_patches(patches, "双击公式")

    def reset_double_hit_values(self) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.double_hit_patches(
            self.working, self.get_double_hit_values(original=True)
        )
        self._apply_legacy_global_patches(patches, "双击公式 · 还原")

    def get_damage_formula_values(
        self, *, original: bool = False
    ) -> tuple[int, int, int, int, int]:
        codec = self._require_legacy_global_data_codec()
        source = self.original if original else self.working
        return codec.damage_formula_values(source)

    def set_damage_formula_values(self, values: Iterable[int]) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.damage_formula_patches(self.working, values)
        self._apply_legacy_global_patches(patches, "伤害公式")

    def reset_damage_formula_values(self) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.damage_formula_patches(
            self.working, self.get_damage_formula_values(original=True)
        )
        self._apply_legacy_global_patches(patches, "伤害公式 · 还原")

    def get_hit_threshold(self, *, original: bool = False) -> int:
        codec = self._require_legacy_global_data_codec()
        source = self.original if original else self.working
        return codec.hit_threshold(source)

    def set_hit_threshold(self, value: int) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.hit_threshold_patches(self.working, value)
        self._apply_legacy_global_patches(patches, "命中阈值")

    def reset_hit_threshold(self) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.hit_threshold_patches(
            self.working, self.get_hit_threshold(original=True)
        )
        self._apply_legacy_global_patches(patches, "命中阈值 · 还原")

    def get_item_effect_values(self, *, original: bool = False) -> tuple[int, ...]:
        codec = self._require_legacy_global_data_codec()
        source = self.original if original else self.working
        return codec.item_effect_values(source)

    def set_item_effect_values(self, values: Iterable[int]) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.item_effect_patches(self.working, values)
        self._apply_legacy_global_patches(patches, "道具效果")

    def reset_item_effect_values(self) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.item_effect_patches(
            self.working, self.get_item_effect_values(original=True)
        )
        self._apply_legacy_global_patches(patches, "道具效果 · 还原")

    def get_item_name_records(
        self, *, original: bool = False
    ) -> tuple[bytes, ...]:
        codec = self._require_legacy_global_data_codec()
        source = self.original if original else self.working
        return codec.item_name_records(source)

    def set_item_name_records(self, records: Iterable[bytes]) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.item_name_record_patches(self.working, records)
        self._apply_legacy_global_patches(patches, "道具名称")

    def reset_item_name_records(self) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.item_name_storage_copy_patches(self.working, self.original)
        self._apply_legacy_global_patches(patches, "道具名称 · 还原")

    def get_item_prices(self, *, original: bool = False) -> tuple[int, ...]:
        codec = self._require_legacy_global_data_codec()
        source = self.original if original else self.working
        return codec.item_prices(source)

    def set_item_prices(self, values: Iterable[int]) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.item_price_patches(self.working, values)
        self._apply_legacy_global_patches(patches, "道具价格")

    def reset_item_prices(self) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.item_price_patches(
            self.working, self.get_item_prices(original=True)
        )
        self._apply_legacy_global_patches(patches, "道具价格 · 还原")

    @property
    def supports_map_tile_attributes(self) -> bool:
        return self.map_tile_attribute_codec is not None

    def _require_map_tile_attribute_codec(self) -> type[MapTileAttributeCodec]:
        if self.map_tile_attribute_codec is None:
            raise ValueError("当前 ROM 的图块属性表尚未完成差分验证。")
        return self.map_tile_attribute_codec

    def get_map_tileset_attributes(
        self, key: str, *, original: bool = False
    ) -> MapTilesetAttributes:
        codec = self._require_map_tile_attribute_codec()
        return codec.decode(self.original if original else self.working, key)

    def set_map_tileset_attributes(
        self, key: str, value: MapTilesetAttributes
    ) -> None:
        codec = self._require_map_tile_attribute_codec()
        patches = codec.patches(self.working, key, value)
        self._apply_legacy_global_patches(patches, f"图库 {key.upper()} 图块属性")

    def reset_map_tileset_attributes(self, key: str) -> None:
        original = self.get_map_tileset_attributes(key, original=True)
        codec = self._require_map_tile_attribute_codec()
        patches = codec.patches(self.working, key, original)
        self._apply_legacy_global_patches(
            patches, f"图库 {key.upper()} 图块属性 · 还原"
        )

    def get_initial_roster(
        self, *, original: bool = False
    ) -> tuple[tuple[int, int], ...]:
        codec = self._require_legacy_global_data_codec()
        source = self.original if original else self.working
        return codec.initial_roster(source)

    def set_initial_roster(self, roster: Iterable[tuple[int, int]]) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.initial_roster_patches(self.working, roster)
        self._apply_legacy_global_patches(patches, "初始人物/机体")

    def reset_initial_roster(self) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.initial_roster_patches(
            self.working, self.get_initial_roster(original=True)
        )
        self._apply_legacy_global_patches(patches, "初始人物/机体 · 还原")

    def get_distance_hit_corrections(
        self, *, original: bool = False
    ) -> tuple[tuple[int, ...], ...]:
        codec = self._require_legacy_global_data_codec()
        source = self.original if original else self.working
        return codec.distance_hit_corrections(source)

    def set_distance_hit_corrections(
        self, rows: Iterable[Iterable[int]]
    ) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.distance_hit_correction_patches(self.working, rows)
        self._apply_legacy_global_patches(patches, "距离命中修正表")

    def reset_distance_hit_corrections(self) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.distance_hit_correction_patches(
            self.working, self.get_distance_hit_corrections(original=True)
        )
        self._apply_legacy_global_patches(patches, "距离命中修正表 · 还原")

    def get_experience_totals(self, *, original: bool = False) -> tuple[int, ...]:
        codec = self._require_legacy_global_data_codec()
        source = self.original if original else self.working
        return codec.experience_totals(source)

    def set_experience_totals(self, values: Iterable[int]) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.experience_total_patches(self.working, values)
        self._apply_legacy_global_patches(patches, "累计经验表")

    def reset_experience_totals(self) -> None:
        codec = self._require_legacy_global_data_codec()
        patches = codec.experience_total_patches(
            self.working, self.get_experience_totals(original=True)
        )
        self._apply_legacy_global_patches(patches, "累计经验表 · 还原")

    @property
    def expansion_capacity(self) -> int:
        return sum(region.size for region in self.profile.free_prg_regions)

    @property
    def expansion_allocations(self) -> tuple[Allocation, ...]:
        return self.resource_allocator.allocations

    @property
    def expansion_used(self) -> int:
        return self.resource_allocator.used

    @property
    def expansion_available(self) -> int:
        return self.resource_allocator.available

    def _write_expansion_plan(self, plan: ExpansionPlan) -> None:
        payload = plan.to_bytes()
        self.working[
            EXPANSION_METADATA_OFFSET : EXPANSION_METADATA_OFFSET + len(payload)
        ] = payload

    @staticmethod
    def _partition_definitions(
        plan: ExpansionPlan,
    ) -> tuple[tuple[str, str, tuple[int, ...]], ...]:
        return (
            ("unit", "机体自动扩展配额", plan.unit_banks),
            ("map", "地图自动扩展配额", plan.map_banks),
            ("story", "剧情文本自动扩展配额", plan.story_banks),
        )

    def _reserve_plan_partitions(self, plan: ExpansionPlan) -> None:
        """Reserve every quota Bank so no other importer can overlap it."""

        existing = {item.resource_id for item in self.expansion_allocations}
        for category, label, banks in self._partition_definitions(plan):
            for index, segment in enumerate(consecutive_bank_segments(banks)):
                resource_id = f"{PARTITION_ALLOCATION_PREFIX}{category}.{index}"
                if resource_id in existing:
                    continue
                self.resource_allocator.reserve(
                    Allocation(
                        resource_id,
                        label,
                        bank_file_offset(segment[0]),
                        len(segment) * PRG_BANK_SIZE,
                        1,
                    )
                )

    def _reserve_direct_reopen_guards(self, plan: ExpansionPlan) -> None:
        """Lock unregistered bytes when an already-built ROM is the base.

        Expansion metadata persists the three automatic partitions, but an
        output ROM cannot persist arbitrary allocator records.  Guard every
        uncovered byte outside the partitions so a later import cannot
        silently overwrite data whose ownership is unknown.  A ``.dcmod``
        remains the editable source of truth for those manual allocations.
        """

        guard_index = 0
        for bank in plan.unassigned_banks:
            bank_start = bank_file_offset(bank)
            bank_end = bank_start + PRG_BANK_SIZE
            overlaps = sorted(
                (
                    item
                    for item in self.expansion_allocations
                    if item.offset < bank_end and bank_start < item.end
                ),
                key=lambda item: item.offset,
            )
            cursor = bank_start
            for item in overlaps:
                if cursor < item.offset:
                    self.resource_allocator.reserve(
                        Allocation(
                            f"{REOPEN_GUARD_PREFIX}{guard_index}",
                            "输出ROM未登记区（请用.dcmod续改）",
                            cursor,
                            item.offset - cursor,
                            1,
                        )
                    )
                    guard_index += 1
                cursor = max(cursor, item.end)
            if cursor < bank_end:
                self.resource_allocator.reserve(
                    Allocation(
                        f"{REOPEN_GUARD_PREFIX}{guard_index}",
                        "输出ROM未登记区（请用.dcmod续改）",
                        cursor,
                        bank_end - cursor,
                        1,
                    )
                )
                guard_index += 1

    def _relink_map_resources(
        self,
        terrain_records: tuple[bytes, ...] | list[bytes],
        scenario_records: tuple[bytes, ...] | list[bytes],
        trigger_records: tuple[bytes, ...] | list[bytes],
        plan: ExpansionPlan,
        *,
        source_data: bytes | bytearray | None = None,
    ) -> ExpansionPlan:
        source = self.working if source_data is None else source_data
        linked, _packed, _patches = link_map_resources(
            source,
            terrain_records,
            scenario_records,
            trigger_records,
            plan.map_banks,
            clear_banks=plan.map_banks,
        )
        self.working[:] = linked
        result = plan.with_flags(
            plan.flags | FLAG_MAPS | FLAG_SCENARIOS | FLAG_MAP_TRIGGERS
        )
        self._write_expansion_plan(result)
        return result

    def _link_unit_resources(
        self,
        plan: ExpansionPlan,
        *,
        source_data: bytes | bytearray | None = None,
        records: UnitExpansionRecords | None = None,
        name_source_ids: tuple[int, ...] | None = None,
    ) -> ExpansionPlan:
        if len(plan.unit_banks) not in (6, 8, 10):
            raise ValueError("完整机体自动绑定只支持 48、64 或 80 KiB。")
        banks = plan.unit_banks
        pairs = self._unit_pairs(plan)
        # The deployment hook intentionally occupies a verified cave in source
        # Bank $25.  Capture the current project before installing that hook so
        # edits made before capacity planning survive the relocation.
        source = self.original if source_data is None else bytes(source_data)
        packed = pack_unit_expansion(
            source,
            pairs,
            records=records,
            name_source_ids=name_source_ids,
        )
        self.working[:] = packed.apply(self.working)
        self._unit_name_baseline_pointers = packed.name_baseline_pointers
        result = plan.with_flags(plan.flags | FLAG_UNITS)
        self._write_expansion_plan(result)
        return result

    def configure_expansion(
        self,
        map_kib: int,
        unit_kib: int,
        story_kib: int,
    ) -> ExpansionPlan:
        """Split the safe PRG pool and install the verified automatic linkers."""

        if self.profile.key != "dc-kuorong-mmc3-v2":
            raise ValueError("自动容量规划仅支持 464 KiB 扩容基准 ROM。")
        if self.expansion_plan is not None:
            raise ValueError("容量区已分配；请先使用撤销恢复到分配前。")
        if self.expansion_allocations:
            raise ValueError("请先删除已手工导入的扩展二进制资源再分区。")
        plan = ExpansionPlan.from_kib(map_kib, unit_kib, story_kib)
        if len(plan.map_banks) < 2:
            raise ValueError("地图自动绑定至少需要 16 KiB。")
        if len(plan.unit_banks) not in (6, 8, 10):
            raise ValueError("完整机体自动绑定只支持 48、64 或 80 KiB。")
        if len(plan.story_banks) < 2:
            raise ValueError("剧情文本配额至少需要 16 KiB。")
        source_before_link = bytes(self.working)
        current_unit_records = extract_unit_expansion_records(source_before_link)
        original_unit_records = extract_unit_expansion_records(self.original)
        name_source_ids: list[int] = []
        for unit_id in range(1, self.unit_count):
            pointer = self.unit_name_codec.pointer(unit_id, source_before_link)
            source_ids = self.unit_name_codec.source_ids(pointer)
            if not source_ids:
                raise RomFormatError(
                    f"机体 ${unit_id:02X} 的名称引用 ${pointer:04X} 无法识别。"
                )
            name_source_ids.append(source_ids[0])
        unit_records = UnitExpansionRecords(
            attributes=current_unit_records.attributes,
            names=original_unit_records.names,
            configurations=current_unit_records.configurations,
            body_scripts=current_unit_records.body_scripts,
            fragment_scripts=current_unit_records.fragment_scripts,
        )
        map_records = tuple(
            self.map_codec.encode(record.width, record.height, record.tiles)
            for map_id in range(self.map_count)
            for record in (self.map_codec.decode(map_id, source_before_link),)
        )
        scenario_records = tuple(
            self.scenario_layout_codec.encode(
                self.scenario_layout_codec.decode(map_id, source_before_link)
            )
            for map_id in range(self.scenario_count)
        )
        if self.map_trigger_codec is None:
            raise ValueError("当前ROM缺少已验证的地图事件表。")
        trigger_records = tuple(
            self.map_trigger_codec.encode_entries(
                self.map_trigger_codec.decode(map_id, source_before_link).entries
            )
            for map_id in range(self.map_trigger_codec.spec.scenario_count)
        )
        # Before automatic planning, trigger edits are repacked into the old
        # Bank $0A cave at $9ED4.  The new runtime hook deliberately occupies
        # that same cave.  We already captured every current trigger above, so
        # restore only the obsolete pool bytes before installing the hook.
        link_source = bytearray(source_before_link)
        if not self.map_trigger_codec.is_expanded:
            trigger_pool_start = self.map_trigger_codec.pool_offset
            trigger_pool_end = trigger_pool_start + self.map_trigger_codec.pool_capacity
            link_source[trigger_pool_start:trigger_pool_end] = self.original[
                trigger_pool_start:trigger_pool_end
            ]
        before = self._mutation_snapshot()
        try:
            self._reserve_plan_partitions(plan)
            self._write_expansion_plan(plan)
            plan = self._relink_map_resources(
                map_records,
                scenario_records,
                trigger_records,
                plan,
                source_data=link_source,
            )
            plan = self._link_unit_resources(
                plan,
                source_data=source_before_link,
                records=unit_records,
                name_source_ids=tuple(name_source_ids),
            )
            # The old pointer table is no longer runtime-visible.  Keeping its
            # canonical copy lets a directly reopened output reconstruct stable
            # reset/name identities without an external project file.
            old_name_table = self.profile.unit_name_pointer_table_offset
            if old_name_table is not None:
                old_name_end = old_name_table + self.profile.unit_name_count * 2
                self.working[old_name_table:old_name_end] = self.original[
                    old_name_table:old_name_end
                ]
            self._write_expansion_plan(plan)
            self._refresh_dynamic_codecs()
        except Exception:
            if before is not None:
                self.working[:] = before.data
                self.resource_allocator = BankAllocator(
                    self.profile, self.original, before.allocations
                )
                self._refresh_dynamic_codecs()
            raise
        self._finish_mutation(before, "自动分配并接通扩展容量")
        return plan

    def expansion_resource_data(self, resource_id: str) -> bytes:
        allocation = self.resource_allocator.allocation(resource_id)
        return bytes(self.working[allocation.offset : allocation.end])

    def import_expansion_resource(
        self,
        resource_id: str,
        label: str,
        payload: bytes,
        *,
        alignment: int = 0x10,
        single_bank: bool | None = None,
    ) -> Allocation:
        normalized_id = resource_id.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", normalized_id):
            raise ValueError("资源ID只能包含小写字母、数字、点、横线和下划线。")
        if normalized_id.startswith(AUTO_ALLOCATION_PREFIX):
            raise ValueError("资源ID不能使用修改器保留的 auto. 前缀。")
        normalized_label = label.strip()
        if not normalized_label:
            raise ValueError("资源名称不能为空。")
        data = bytes(payload)
        if not data:
            raise ValueError("导入资源不能为空。")
        if single_bank is None:
            single_bank = len(data) <= 0x2000
        before = self._mutation_snapshot()
        allocation = self.resource_allocator.allocate(
            normalized_id,
            normalized_label,
            len(data),
            alignment=alignment,
            single_bank=single_bank,
        )
        self.working[allocation.offset : allocation.end] = data
        self._finish_mutation(before, f"导入扩展资源 · {normalized_label}")
        return allocation

    def remove_expansion_resource(self, resource_id: str) -> Allocation:
        if resource_id.startswith(AUTO_ALLOCATION_PREFIX):
            raise ValueError("内部容量分区由链接器管理，不能作为普通资源删除。")
        allocation = self.resource_allocator.allocation(resource_id)
        before = self._mutation_snapshot()
        self.working[allocation.offset : allocation.end] = self.original[
            allocation.offset : allocation.end
        ]
        self.resource_allocator.release(resource_id)
        self._finish_mutation(before, f"删除扩展资源 · {allocation.label}")
        return allocation

    @property
    def supports_unit_weapons(self) -> bool:
        return self.unit_weapon_codec is not None

    @property
    def supports_weapon_names(self) -> bool:
        return self.weapon_name_codec is not None

    @property
    def supports_character_names(self) -> bool:
        return self.character_name_codec is not None

    @property
    def supports_map_triggers(self) -> bool:
        return self.map_trigger_codec is not None

    @property
    def chr_tile_count(self) -> int:
        return self.chr_codec.tile_count

    def chr_tile_pixels(
        self,
        tile_index: int,
        *,
        original: bool = False,
    ) -> tuple[int, ...]:
        source = self.original if original else bytes(self.working)
        return self.chr_codec.decode_tile(tile_index, source)

    def set_font_glyphs(self, glyphs: dict[bytes, bytes]) -> None:
        """Replace verified fixed glyph slots atomically, never row padding."""
        from fc_editor.codecs.dc_font import SUPPORTED_PROFILES, glyph_file_offset

        if self.profile.key not in SUPPORTED_PROFILES:
            raise ValueError("当前 ROM 的 12×12 字模写入布局尚未验证。")
        patches: list[tuple[int, bytes]] = []
        for token, raw in glyphs.items():
            offset = glyph_file_offset(token, writable=True)
            if len(raw) != 18 or offset + 18 > len(self.working):
                raise ValueError("字模必须恰好为 18 字节且位于有效 ROM 内。")
            patches.append((offset, bytes(raw)))
        with self.transaction(f"替换 {len(patches)} 个 ROM 字模"):
            for offset, raw in patches:
                self.working[offset : offset + 18] = raw

    def set_chr_tile_pixels(
        self,
        tile_index: int,
        pixels: tuple[int, ...] | list[int],
    ) -> None:
        before = self._mutation_snapshot()
        offset = self.chr_codec.tile_offset(tile_index)
        self.working[offset : offset + 16] = self.chr_codec.encode_tile(pixels)
        self._finish_mutation(before, f"CHR图块 ${tile_index:04X}")

    def set_chr_range(self, first_tile: int, payload: bytes) -> int:
        if not payload or len(payload) % 16:
            raise ValueError("CHR数据必须是非空且长度为16字节的整数倍。")
        tile_count = len(payload) // 16
        self.chr_codec.range_bytes(first_tile, tile_count, bytes(self.working))
        before = self._mutation_snapshot()
        offset = self.chr_codec.tile_offset(first_tile)
        self.working[offset : offset + len(payload)] = payload
        self._finish_mutation(
            before,
            f"导入CHR图块 ${first_tile:04X}—${first_tile + tile_count - 1:04X}",
        )
        return tile_count

    def reset_chr_range(self, first_tile: int, tile_count: int = 1) -> None:
        self.chr_codec.range_bytes(first_tile, tile_count, self.original)
        before = self._mutation_snapshot()
        offset = self.chr_codec.tile_offset(first_tile)
        size = tile_count * 16
        self.working[offset : offset + size] = self.original[offset : offset + size]
        self._finish_mutation(
            before,
            f"还原CHR图块 ${first_tile:04X}—${first_tile + tile_count - 1:04X}",
        )

    @property
    def supports_custom_music_import(self) -> bool:
        return self.custom_music_codec is not None

    def custom_music_bank(self, command: int, *, original: bool = False) -> bytes:
        if self.custom_music_codec is None:
            raise ValueError("当前ROM没有可替换的扩展音乐槽。")
        source = self.original if original else bytes(self.working)
        return self.custom_music_codec.bank_bytes(command, source)

    def set_custom_music_bank(self, command: int, payload: bytes) -> None:
        if self.custom_music_codec is None:
            raise ValueError("当前ROM没有可替换的扩展音乐槽。")
        slot = self.custom_music_codec.slot_by_command[command]
        self.custom_music_codec.validate_bank(payload, slot=slot)
        before = self._mutation_snapshot()
        offset = self.custom_music_codec.bank_offset(slot)
        self.working[offset : offset + len(payload)] = payload
        self._finish_mutation(before, f"替换扩展曲 ${command:02X} · {slot.label}")

    def reset_custom_music_bank(self, command: int) -> None:
        if self.custom_music_codec is None:
            raise ValueError("当前ROM没有可替换的扩展音乐槽。")
        slot = self.custom_music_codec.slot_by_command[command]
        offset = self.custom_music_codec.bank_offset(slot)
        before = self._mutation_snapshot()
        self.working[offset : offset + 0x2000] = self.original[offset : offset + 0x2000]
        self._finish_mutation(before, f"还原扩展曲 ${command:02X} · {slot.label}")

    def unit_field(self, field_key: str) -> FieldSpec:
        field = FIELD_BY_KEY[field_key]
        if field_key.endswith("_growth") and field.maximum != self.profile.growth_curve_max:
            return FieldSpec(
                field.key,
                field.label,
                field.record_offset,
                field.width,
                field.minimum,
                self.profile.growth_curve_max,
                field.description,
                field.byte_order,
                field.mask,
                field.shift,
                field.display_scale,
                field.choices,
                field.evidence,
            )
        return field

    @property
    def is_dirty(self) -> bool:
        return self.working != self.original or any(
            not allocation.resource_id.startswith(AUTO_ALLOCATION_PREFIX)
            for allocation in self.expansion_allocations
        )

    def record_file_offset_from_pointer(self, pointer: int) -> int:
        return self.unit_codec.record_offset_from_pointer(pointer)

    def record_file_offset(self, unit_id: int) -> int:
        return self.unit_codec.record_offset(unit_id)

    def record_bytes(self, unit_id: int, *, original: bool = False) -> bytes:
        if original:
            return self.base_unit_codec.decode_record(unit_id, self.original).raw
        offset = self.record_file_offset(unit_id)
        return bytes(self.working[offset : offset + UNIT_RECORD_SIZE])

    def get_value(self, unit_id: int, field_key: str, *, original: bool = False) -> int:
        field = self.unit_field(field_key)
        record = self.record_bytes(unit_id, original=original)
        return field.decode(record)

    def set_value(self, unit_id: int, field_key: str, value: int) -> None:
        field = self.unit_field(field_key)
        if not field.minimum <= value <= field.maximum:
            raise ValueError(
                f"{field.label}必须在 {field.minimum}—{field.maximum} 之间。"
            )
        before = self._mutation_snapshot()
        offset = self.record_file_offset(unit_id) + field.record_offset
        record = self.record_bytes(unit_id)
        encoded = field.encode_into(record, value)
        self.working[offset : offset + field.width] = encoded[
            field.record_offset : field.record_offset + field.width
        ]
        self._finish_mutation(before, f"机体 {unit_id:02X} · {field.label}")

    def set_record_hex(self, unit_id: int, text: str) -> None:
        compact = "".join(character for character in text if character not in " \t\r\n,-_")
        if len(compact) != UNIT_RECORD_SIZE * 2:
            raise ValueError("高级记录必须正好包含 16 个十六进制字节。")
        try:
            record = bytes.fromhex(compact)
        except ValueError as error:
            raise ValueError("记录中含有无效的十六进制字符。") from error
        before = self._mutation_snapshot()
        offset = self.record_file_offset(unit_id)
        self.working[offset : offset + UNIT_RECORD_SIZE] = record
        self._finish_mutation(before, f"机体 {unit_id:02X} · 高级记录")

    def reset_record(self, unit_id: int) -> None:
        before = self._mutation_snapshot()
        offset = self.record_file_offset(unit_id)
        self.working[offset : offset + UNIT_RECORD_SIZE] = self.record_bytes(
            unit_id, original=True
        )
        self._finish_mutation(before, f"机体 {unit_id:02X} · 还原记录")

    def weapon_record_file_offset(self, weapon_id: int) -> int:
        return self.weapon_codec.record_offset(weapon_id)

    def weapon_record_bytes(self, weapon_id: int, *, original: bool = False) -> bytes:
        offset = self.weapon_record_file_offset(weapon_id)
        source = self.original if original else self.working
        return bytes(source[offset : offset + WEAPON_RECORD_SIZE])

    def get_weapon_value(
        self,
        weapon_id: int,
        field_key: str,
        *,
        original: bool = False,
    ) -> int:
        field = WEAPON_FIELD_BY_KEY[field_key]
        return field.decode(self.weapon_record_bytes(weapon_id, original=original))

    def set_weapon_value(self, weapon_id: int, field_key: str, value: int) -> None:
        field = WEAPON_FIELD_BY_KEY[field_key]
        if field.evidence != "confirmed":
            raise ValueError(f"{field.label}尚未确认，不能从稳定界面写入。")
        if not field.minimum <= value <= field.maximum:
            raise ValueError(
                f"{field.label}必须在 {field.minimum}—{field.maximum} 之间。"
            )
        before = self._mutation_snapshot()
        offset, _old, after = self.weapon_codec.field_patch(
            bytes(self.working), weapon_id, field_key, value
        )
        self.working[offset : offset + len(after)] = after
        self._finish_mutation(before, f"武器 {weapon_id:02X} · {field.label}")

    def reset_weapon_record(self, weapon_id: int) -> None:
        before = self._mutation_snapshot()
        offset = self.weapon_record_file_offset(weapon_id)
        self.working[offset : offset + WEAPON_RECORD_SIZE] = self.original[
            offset : offset + WEAPON_RECORD_SIZE
        ]
        self._finish_mutation(before, f"武器 {weapon_id:02X} · 还原记录")

    def get_weapon_name_pointer(
        self,
        weapon_id: int,
        *,
        original: bool = False,
    ) -> int:
        if self.weapon_name_codec is None:
            raise ValueError("当前 ROM 的武器名称表尚未验证。")
        source = self.original if original else bytes(self.working)
        return self.weapon_name_codec.pointer(weapon_id, source)

    def weapon_name_source_ids(
        self,
        weapon_id: int,
        *,
        original: bool = False,
    ) -> tuple[int, ...]:
        if self.weapon_name_codec is None:
            raise ValueError("当前 ROM 的武器名称表尚未验证。")
        return self.weapon_name_codec.source_ids(
            self.get_weapon_name_pointer(weapon_id, original=original)
        )

    def weapon_name_record_bytes(
        self,
        weapon_id: int,
        *,
        original: bool = False,
    ) -> bytes:
        if self.weapon_name_codec is None:
            raise ValueError("当前 ROM 的武器名称表尚未验证。")
        source = self.original if original else bytes(self.working)
        return self.weapon_name_codec.record_bytes(weapon_id, source)

    def _replace_terminated_name(
        self,
        offset: int,
        capacity: int,
        text: str,
        description: str,
    ) -> None:
        """Replace one name without moving its pointer or crossing its slot."""

        value = text.strip()
        if not value:
            raise ValueError("名称不能为空。")
        encoded = default_dc_text_table().encode(value) + b"\xFF"
        if len(encoded) > capacity:
            raise ValueError(
                f"名称编码需要 {len(encoded)} 字节，当前原槽只有 {capacity} 字节；"
                "请缩短名称。"
            )
        before_snapshot = self._mutation_snapshot()
        self.working[offset : offset + capacity] = encoded + b"\xFF" * (
            capacity - len(encoded)
        )
        self._finish_mutation(before_snapshot, description)

    @staticmethod
    def _terminated_capacity(raw: bytes, label: str) -> int:
        terminator = raw.find(b"\xFF")
        if terminator < 0:
            raise RomFormatError(f"{label}没有 $FF 结束码。")
        return terminator + 1

    def set_weapon_name_text(self, weapon_id: int, text: str) -> None:
        if self.weapon_name_codec is None:
            raise ValueError("当前 ROM 的武器名称表尚未验证。")
        pointer = self.weapon_name_codec.pointer(weapon_id, bytes(self.working))
        offset = self.weapon_name_codec.pointer_to_file_offset(pointer)
        raw = self.weapon_name_codec.record_bytes(weapon_id, bytes(self.working))
        self._replace_terminated_name(
            offset,
            self._terminated_capacity(raw, "武器名称"),
            text,
            f"武器 {weapon_id:02X} · 直接修改名称",
        )

    def weapon_display_name(self, weapon_id: int) -> str:
        if self.weapon_name_codec is None:
            return f"武器记录 ${weapon_id:02X}"
        label = concise_dc_text(self.weapon_name_record_bytes(weapon_id))
        if not label or not label.strip("-_"):
            return "空白/未分配武器槽"
        return label

    def character_display_name(self, character_id: int) -> str:
        """Return the verified in-battle name for a character byte ID."""
        if character_id == 0:
            return "无人物/特殊上下文"
        if (
            self.character_name_codec is None
            or not 0 <= character_id < self.profile.character_name_count
        ):
            return "超出已验证人物表"
        label = concise_dc_text(
            self.character_name_codec.record_bytes(character_id, self.working)
        )
        if not label or not label.strip("-_ "):
            return "空白/未分配人物槽"
        if label and all(character in "?？" for character in label):
            return f"占位/未命名人物槽（原ROM“{label}”）"
        return label

    def get_character_name_pointer(
        self,
        character_id: int,
        *,
        original: bool = False,
    ) -> int:
        if self.character_name_codec is None:
            raise ValueError("当前 ROM 的人物名称表尚未验证。")
        source = self.original if original else self.working
        return self.character_name_codec.pointer(character_id, source)

    def character_name_source_ids(
        self,
        character_id: int,
        *,
        original: bool = False,
    ) -> tuple[int, ...]:
        if self.character_name_codec is None:
            raise ValueError("当前 ROM 的人物名称表尚未验证。")
        return self.character_name_codec.source_ids(
            self.get_character_name_pointer(character_id, original=original)
        )

    def character_name_record_bytes(
        self,
        character_id: int,
        *,
        original: bool = False,
    ) -> bytes:
        if self.character_name_codec is None:
            raise ValueError("当前 ROM 的人物名称表尚未验证。")
        source = self.original if original else self.working
        return self.character_name_codec.record_bytes(character_id, source)

    def set_character_name_text(self, character_id: int, text: str) -> None:
        if self.character_name_codec is None:
            raise ValueError("当前 ROM 的人物名称表尚未验证。")
        pointer = self.character_name_codec.pointer(character_id, self.working)
        if not pointer:
            raise ValueError("空人物名称槽没有可安全写入的原记录。")
        offset = self.character_name_codec.pointer_to_file_offset(pointer)
        raw = self.character_name_codec.record_bytes(character_id, self.working)
        self._replace_terminated_name(
            offset,
            self._terminated_capacity(raw, "人物名称"),
            text,
            f"人物 {character_id:02X} · 直接修改名称",
        )

    def character_name_reference_options(
        self,
    ) -> tuple[tuple[int, int, str, tuple[int, ...]], ...]:
        if self.character_name_codec is None:
            return ()
        options: list[tuple[int, int, str, tuple[int, ...]]] = []
        for pointer in sorted(self.character_name_codec.ids_by_pointer):
            source_ids = self.character_name_codec.source_ids(pointer)
            if not source_ids:
                continue
            source_id = source_ids[0]
            options.append(
                (
                    source_id,
                    pointer,
                    self.character_display_name(source_id),
                    source_ids,
                )
            )
        return tuple(options)

    def set_character_name_reference(
        self,
        character_id: int,
        source_name_id: int,
    ) -> None:
        if self.character_name_codec is None:
            raise ValueError("当前 ROM 的人物名称表尚未验证。")
        before = self._mutation_snapshot()
        offset, _old, after = self.character_name_codec.reference_patch(
            self.working, character_id, source_name_id
        )
        self.working[offset : offset + 2] = after
        self._finish_mutation(
            before,
            f"人物 {character_id:02X} · 名称引用 {source_name_id:02X}",
        )

    def reset_character_name(self, character_id: int) -> None:
        if self.character_name_codec is None:
            raise ValueError("当前 ROM 的人物名称表尚未验证。")
        if not 1 <= character_id < self.profile.character_name_count:
            raise ValueError(
                f"人物 ID 必须在 01—{self.profile.character_name_count - 1:02X} 之间。"
            )
        before = self._mutation_snapshot()
        offset = self.character_name_codec.pointer_offset(character_id)
        self.working[offset : offset + 2] = self.original[offset : offset + 2]
        self._finish_mutation(before, f"人物 {character_id:02X} · 还原名称")

    def battle_music_selector_label(self, selector: int) -> str:
        spec = self.profile.battle_music
        if spec is None:
            return self.character_display_name(selector)
        named = spec.selector_label(selector)
        if named != "未命名选择器":
            return named
        return self.character_display_name(selector)

    def weapon_name_reference_options(
        self,
    ) -> tuple[tuple[int, int, str, tuple[int, ...]], ...]:
        if self.weapon_name_codec is None:
            return ()
        options: list[tuple[int, int, str, tuple[int, ...]]] = []
        for pointer in sorted(self.weapon_name_codec.ids_by_pointer):
            source_ids = self.weapon_name_codec.source_ids(pointer)
            if not source_ids:
                continue
            source_id = source_ids[0]
            options.append(
                (
                    source_id,
                    pointer,
                    self.weapon_display_name(source_id),
                    source_ids,
                )
            )
        return tuple(options)

    def set_weapon_name_reference(self, weapon_id: int, source_name_id: int) -> None:
        if self.weapon_name_codec is None:
            raise ValueError("当前 ROM 的武器名称表尚未验证。")
        before = self._mutation_snapshot()
        offset, _old, after = self.weapon_name_codec.reference_patch(
            bytes(self.working), weapon_id, source_name_id
        )
        self.working[offset : offset + 2] = after
        self._finish_mutation(before, f"武器 {weapon_id:02X} · 名称引用")

    def reset_weapon_name(self, weapon_id: int) -> None:
        if self.weapon_name_codec is None:
            raise ValueError("当前 ROM 的武器名称表尚未验证。")
        before = self._mutation_snapshot()
        offset = self.weapon_name_codec.pointer_offset(weapon_id)
        self.working[offset : offset + 2] = self.original[offset : offset + 2]
        self._finish_mutation(before, f"武器 {weapon_id:02X} · 还原名称")

    def get_unit_weapons(
        self,
        unit_id: int,
        *,
        original: bool = False,
    ) -> tuple[int, int]:
        codec = self.base_unit_weapon_codec if original else self.unit_weapon_codec
        if codec is None:
            raise ValueError("当前 ROM 的机体武器关系表尚未验证。")
        source = self.original if original else bytes(self.working)
        return codec.decode(unit_id, source).weapon_ids

    def set_unit_weapon(self, unit_id: int, slot: int, weapon_id: int) -> None:
        if self.unit_weapon_codec is None:
            raise ValueError("当前 ROM 的机体武器关系表尚未验证。")
        before = self._mutation_snapshot()
        offset, _before, after = self.unit_weapon_codec.slot_patch(
            bytes(self.working), unit_id, slot, weapon_id
        )
        self.working[offset] = after[0]
        self._finish_mutation(before, f"机体 {unit_id:02X} · 武器槽 {slot + 1}")

    def reset_unit_weapons(self, unit_id: int) -> None:
        if self.unit_weapon_codec is None or self.base_unit_weapon_codec is None:
            raise ValueError("当前 ROM 的机体武器关系表尚未验证。")
        before = self._mutation_snapshot()
        offset = self.unit_weapon_codec.record_offset(unit_id)
        original_config = self.base_unit_weapon_codec.decode(
            unit_id, self.original
        ).weapon_ids
        self.working[offset : offset + UNIT_WEAPON_SLOT_COUNT] = bytes(original_config)
        self._finish_mutation(before, f"机体 {unit_id:02X} · 还原武器配置")

    def get_unit_name_pointer(self, unit_id: int, *, original: bool = False) -> int:
        if original:
            return self.base_unit_name_codec.pointer(unit_id, self.original)
        return self.unit_name_codec.pointer(unit_id, bytes(self.working))

    def unit_name_source_ids(
        self,
        unit_id: int,
        *,
        original: bool = False,
    ) -> tuple[int, ...]:
        codec = self.base_unit_name_codec if original else self.unit_name_codec
        return codec.source_ids(self.get_unit_name_pointer(unit_id, original=original))

    def unit_alias_table(self) -> dict[int, str]:
        if self.profile.key in DC_UNIT_NAME_PROFILE_KEYS:
            return CONFIRMED_DC_UNIT_ALIASES
        if self.profile.uses_original_name_aliases:
            return CONFIRMED_UNIT_ALIASES
        return {}

    def unit_name_pointer_display_name(self, pointer: int) -> str:
        source_ids = self.unit_name_codec.source_ids(pointer)
        if not source_ids:
            return f"未知原生名称 ${pointer:04X}"
        aliases = self.unit_alias_table()
        if self.profile.key in DC_UNIT_NAME_PROFILE_KEYS:
            names = tuple(
                dict.fromkeys(
                    aliases[source_id]
                    for source_id in source_ids
                    if source_id in aliases
                )
            )
            return " / ".join(names) if names else "空白/未分配机体槽"
        if self.profile.uses_original_name_aliases:
            names = tuple(
                dict.fromkeys(
                    aliases.get(source_id, f"名称 {source_id:02X}")
                    for source_id in source_ids
                )
            )
            return " / ".join(names)
        return " / ".join(f"原生名称 {source_id:02X}" for source_id in source_ids)

    def unit_name_record_bytes(
        self,
        unit_id: int,
        *,
        original: bool = False,
    ) -> bytes:
        codec = self.base_unit_name_codec if original else self.unit_name_codec
        source = self.original if original else bytes(self.working)
        pointer = codec.pointer(unit_id, source)
        bank = (
            codec.pair_first_bank
            if codec.pair_first_bank is not None
            else (codec.pointer_table_offset - 16) // PRG_BANK_SIZE
        )
        offset = bank_file_offset(bank) + pointer - 0x8000
        limit = min(len(source), bank_file_offset(bank) + 2 * PRG_BANK_SIZE)
        terminator = source.find(b"\xFF", offset, limit)
        if terminator < 0:
            raise RomFormatError(f"机体 ${unit_id:02X} 名称没有 $FF 结束码。")
        return bytes(source[offset : terminator + 1])

    def unit_display_name(self, unit_id: int) -> str:
        label = concise_dc_text(self.unit_name_record_bytes(unit_id))
        if label and label.strip("-_ "):
            return label
        return "空白/未分配机体槽"

    def set_unit_name_text(self, unit_id: int, text: str) -> None:
        codec = self.unit_name_codec
        pointer = codec.pointer(unit_id, bytes(self.working))
        bank = (
            codec.pair_first_bank
            if codec.pair_first_bank is not None
            else (codec.pointer_table_offset - 16) // PRG_BANK_SIZE
        )
        offset = bank_file_offset(bank) + pointer - 0x8000
        raw = self.unit_name_record_bytes(unit_id)
        self._replace_terminated_name(
            offset,
            len(raw),
            text,
            f"机体 {unit_id:02X} · 直接修改名称",
        )

    def unit_name_reference_options(
        self,
    ) -> tuple[tuple[int, int, str, tuple[int, ...]], ...]:
        options: list[tuple[int, int, str, tuple[int, ...]]] = []
        seen_pointers: set[int] = set()
        for source_id in range(1, self.unit_count):
            pointer = self.unit_name_codec.original_pointers[source_id]
            if pointer in seen_pointers:
                continue
            seen_pointers.add(pointer)
            options.append(
                (
                    source_id,
                    pointer,
                    self.unit_name_pointer_display_name(pointer),
                    self.unit_name_codec.source_ids(pointer),
                )
            )
        return tuple(options)

    def set_unit_name_reference(self, unit_id: int, source_name_id: int) -> None:
        before_snapshot = self._mutation_snapshot()
        offset, _before, after = self.unit_name_codec.reference_patch(
            bytes(self.working), unit_id, source_name_id
        )
        self.working[offset : offset + len(after)] = after
        self._finish_mutation(
            before_snapshot,
            f"机体 {unit_id:02X} · 名称改为 "
            f"{self.unit_name_pointer_display_name(int.from_bytes(after, 'little'))}",
        )

    def reset_unit_name(self, unit_id: int) -> None:
        if not 1 <= unit_id < self.unit_count:
            raise ValueError(f"机体 ID 必须在 01—{self.unit_count - 1:02X} 之间。")
        original_pointer = self.base_unit_name_codec.pointer(unit_id, self.original)
        if (
            self._initial_expansion_plan is not None
            and self._initial_expansion_plan.flags & FLAG_UNITS
        ):
            source_ids = self.unit_name_codec.source_ids(original_pointer)
        else:
            source_ids = self.base_unit_name_codec.source_ids(original_pointer)
        if not source_ids:
            raise RomFormatError(
                f"机体 ${unit_id:02X} 的原始名称引用 "
                f"${original_pointer:04X} 无法映射到已验证名称。"
            )
        before_snapshot = self._mutation_snapshot()
        offset, _old, after = self.unit_name_codec.reference_patch(
            bytes(self.working), unit_id, source_ids[0]
        )
        self.working[offset : offset + 2] = after
        self._finish_mutation(before_snapshot, f"机体 {unit_id:02X} · 还原名称")

    def get_map(self, map_id: int, *, original: bool = False) -> MapRecord:
        if original:
            return self.base_map_codec.decode(map_id, self.original)
        return self.map_codec.decode(map_id, bytes(self.working))

    def _commit_expanded_map_resources(
        self,
        terrain_records: list[bytes],
        scenario_records: list[bytes],
        trigger_records: list[bytes],
        description: str,
    ) -> None:
        plan = self.expansion_plan
        if plan is None or not plan.flags & FLAG_MAPS:
            raise ValueError("地图扩展池尚未接通。")
        before = self._mutation_snapshot()
        try:
            plan = self._relink_map_resources(
                terrain_records, scenario_records, trigger_records, plan
            )
            self._write_expansion_plan(plan)
            self._refresh_dynamic_codecs()
        except Exception:
            if before is not None:
                self.working[:] = before.data
                self.resource_allocator = BankAllocator(
                    self.profile, self.original, before.allocations
                )
                self._refresh_dynamic_codecs()
            raise
        self._finish_mutation(before, description)

    def map_resource_replacement_usage(
        self,
        map_id: int,
        width: int,
        height: int,
        tiles: tuple[int, ...],
        layout: ScenarioLayout | None = None,
        triggers: tuple[MapTrigger, ...] | None = None,
    ) -> tuple[int, int]:
        """Dry-run the shared map linker for UI capacity feedback."""

        plan = self.expansion_plan
        if plan is None or not plan.flags & FLAG_MAPS:
            encoded = self.map_codec.encode(width, height, tiles)
            return len(encoded), self.map_codec.capacities[map_id]
        payloads = read_expanded_map_payloads(self.working)
        terrain_records = list(payloads.terrain)
        scenario_records = list(payloads.scenarios)
        trigger_records = list(payloads.triggers)
        terrain_records[map_id] = self.map_codec.encode(width, height, tiles)
        if layout is not None:
            scenario_records[map_id] = self.scenario_layout_codec.encode(layout)
        if triggers is not None:
            trigger_records[map_id] = self.map_trigger_codec.encode_entries(triggers)
        packed = pack_map_resources(
            terrain_records, scenario_records, trigger_records, plan.map_banks
        )
        return packed.used_bytes, packed.capacity

    def set_map_tiles(
        self,
        map_id: int,
        width: int,
        height: int,
        tiles: tuple[int, ...],
    ) -> None:
        plan = self.expansion_plan
        if plan is not None and plan.flags & FLAG_MAPS:
            payloads = read_expanded_map_payloads(self.working)
            terrain = list(payloads.terrain)
            terrain[map_id] = self.map_codec.encode(width, height, tiles)
            self._commit_expanded_map_resources(
                terrain,
                list(payloads.scenarios),
                list(payloads.triggers),
                f"地图 {map_id:02X} · 地形",
            )
            return
        before = self._mutation_snapshot()
        offset, _before, after = self.map_codec.replacement_patch(
            bytes(self.working), map_id, width, height, tiles
        )
        self.working[offset : offset + len(after)] = after
        self._finish_mutation(before, f"地图 {map_id:02X} · 地形")

    def reset_map(self, map_id: int) -> None:
        plan = self.expansion_plan
        if plan is not None and plan.flags & FLAG_MAPS:
            original = self.get_map(map_id, original=True)
            self.set_map_tiles(
                map_id, original.width, original.height, original.tiles
            )
            return
        before = self._mutation_snapshot()
        offset = self.map_codec.record_offset(map_id)
        capacity = self.map_codec.capacities[map_id]
        self.working[offset : offset + capacity] = self.original[
            offset : offset + capacity
        ]
        self._finish_mutation(before, f"地图 {map_id:02X} · 还原地形")

    def get_scenario_layout(
        self,
        map_id: int,
        *,
        original: bool = False,
    ) -> ScenarioLayout:
        if original:
            return self.base_scenario_layout_codec.decode(map_id, self.original)
        return self.scenario_layout_codec.decode(map_id, bytes(self.working))

    def set_scenario_layout(self, layout: ScenarioLayout) -> None:
        map_record = self.get_map(layout.map_id)
        self.scenario_layout_codec.validate_layout(
            layout, map_record.width, map_record.height
        )
        plan = self.expansion_plan
        if plan is not None and plan.flags & FLAG_SCENARIOS:
            payloads = read_expanded_map_payloads(self.working)
            scenarios = list(payloads.scenarios)
            scenarios[layout.map_id] = self.scenario_layout_codec.encode(layout)
            self._commit_expanded_map_resources(
                list(payloads.terrain),
                scenarios,
                list(payloads.triggers),
                f"场景 {layout.map_id:02X} · 部署",
            )
            return
        before = self._mutation_snapshot()
        offset, _before, after = self.scenario_layout_codec.replacement_patch(
            bytes(self.working), layout
        )
        self.working[offset : offset + len(after)] = after
        self._finish_mutation(before, f"场景 {layout.map_id:02X} · 部署")

    def reset_scenario_layout(self, map_id: int) -> None:
        plan = self.expansion_plan
        if plan is not None and plan.flags & FLAG_SCENARIOS:
            self.set_scenario_layout(self.get_scenario_layout(map_id, original=True))
            return
        before = self._mutation_snapshot()
        offset = self.scenario_layout_codec.record_offset(map_id)
        capacity = self.scenario_layout_codec.capacities[map_id]
        self.working[offset : offset + capacity] = self.original[
            offset : offset + capacity
        ]
        self._finish_mutation(before, f"场景 {map_id:02X} · 还原部署")

    def get_map_triggers(
        self,
        map_id: int,
        *,
        original: bool = False,
    ) -> tuple[MapTrigger, ...]:
        if self.map_trigger_codec is None:
            raise ValueError("当前 ROM 没有已验证的地图事件表。")
        if original:
            if self.base_map_trigger_codec is None:
                raise ValueError("当前 ROM 没有已验证的地图事件表。")
            return self.base_map_trigger_codec.decode(map_id, self.original).entries
        return self.map_trigger_codec.decode(map_id, bytes(self.working)).entries

    def _replace_map_triggers(
        self,
        map_id: int,
        entries: tuple[MapTrigger, ...],
        description: str,
    ) -> None:
        if self.map_trigger_codec is None:
            raise ValueError("当前 ROM 没有已验证的地图事件表。")
        record = self.get_map(map_id)
        self.map_trigger_codec.validate_entries(entries, record.width, record.height)
        plan = self.expansion_plan
        if plan is not None and plan.flags & FLAG_MAP_TRIGGERS:
            payloads = read_expanded_map_payloads(self.working)
            triggers = list(payloads.triggers)
            triggers[map_id] = self.map_trigger_codec.encode_entries(entries)
            self._commit_expanded_map_resources(
                list(payloads.terrain),
                list(payloads.scenarios),
                triggers,
                description,
            )
            return
        before_snapshot = self._mutation_snapshot()
        for offset, _before, after in self.map_trigger_codec.repack_patches(
            bytes(self.working), map_id, entries
        ):
            self.working[offset : offset + len(after)] = after
        self._finish_mutation(before_snapshot, description)

    def set_map_triggers(
        self,
        map_id: int,
        entries: tuple[MapTrigger, ...],
    ) -> None:
        self._replace_map_triggers(
            map_id, tuple(entries), f"地图 {map_id:02X} · 事件与商店"
        )

    def reset_map_triggers(self, map_id: int) -> None:
        self._replace_map_triggers(
            map_id,
            self.get_map_triggers(map_id, original=True),
            f"地图 {map_id:02X} · 还原事件与商店",
        )

    @property
    def supports_persuasion_rules(self) -> bool:
        return self.persuasion_rule_codec is not None

    def get_persuasion_rule(
        self,
        slot: int,
        *,
        original: bool = False,
    ) -> PersuasionRule:
        if self.persuasion_rule_codec is None:
            raise ValueError("当前 ROM 没有已验证的劝降规则表。")
        source = self.original if original else bytes(self.working)
        return self.persuasion_rule_codec.decode(slot, source)

    def set_persuasion_rule(
        self,
        slot: int,
        scenario_id: int,
        persuader_id: int,
        target_id: int,
    ) -> None:
        if self.persuasion_rule_codec is None:
            raise ValueError("当前 ROM 没有已验证的劝降规则表。")
        before = self._mutation_snapshot()
        offset, _old, after = self.persuasion_rule_codec.replacement_patch(
            self.working,
            slot,
            scenario_id,
            persuader_id,
            target_id,
        )
        self.working[offset : offset + len(after)] = after
        self._finish_mutation(before, f"劝降规则 ${slot:02X}")

    def reset_persuasion_rule(self, slot: int) -> None:
        if self.persuasion_rule_codec is None:
            raise ValueError("当前 ROM 没有已验证的劝降规则表。")
        before = self._mutation_snapshot()
        offset = self.persuasion_rule_codec.record_offset(slot)
        self.working[offset : offset + 3] = self.original[offset : offset + 3]
        self._finish_mutation(before, f"劝降规则 ${slot:02X} · 还原")

    @property
    def supports_chapter_events(self) -> bool:
        return self.chapter_event_codec is not None

    def chapter_event_instructions(self, *, actions_only: bool = False):
        if self.chapter_event_codec is None:
            return ()
        source = bytes(self.working)
        if actions_only:
            return self.chapter_event_codec.actions(source)
        return self.chapter_event_codec.instructions(source)

    def set_chapter_event_instruction(self, address: int, replacement: bytes) -> None:
        if self.chapter_event_codec is None:
            raise ValueError("当前ROM不支持章节事件编辑。")
        before = self._mutation_snapshot()
        offset, _old, after = self.chapter_event_codec.replacement_patch(
            bytes(self.working), address, replacement
        )
        self.working[offset : offset + len(after)] = after
        self._finish_mutation(before, f"章节事件 ${address:04X}")

    def reset_chapter_event_instruction(self, address: int) -> None:
        if self.chapter_event_codec is None:
            raise ValueError("当前ROM不支持章节事件编辑。")
        current = self.chapter_event_codec.instruction_at(address, bytes(self.working))
        original = self.chapter_event_codec.instruction_at(address, self.original)
        if len(current.raw) != len(original.raw):
            raise ValueError("当前事件指令边界与基准ROM不一致，无法单独还原。")
        before = self._mutation_snapshot()
        self.working[current.file_offset : current.file_offset + len(current.raw)] = original.raw
        self._finish_mutation(before, f"还原章节事件 ${address:04X}")

    def get_story_text(
        self,
        selector: int,
        index: int,
        *,
        original: bool = False,
    ) -> StoryTextRecord:
        if original:
            return self.base_story_text_codec.decode(selector, index, self.original)
        return self.story_text_codec.decode(selector, index, bytes(self.working))

    def story_text_replacement_usage(
        self,
        selector: int,
        index: int,
        data: bytes,
    ) -> tuple[int, int]:
        """Dry-run a text replacement and return used/available group bytes."""

        plan = self.expansion_plan
        if plan is None:
            record = self.get_story_text(selector, index)
            if len(data) != record.capacity:
                raise ValueError(f"当前记录必须保持 {record.capacity} 字节。")
            return len(data), record.capacity
        candidate = plan if plan.story_pair_for(selector) else plan.with_story_selector(selector)
        pair = candidate.story_pair_for(selector)
        if pair is None:
            raise ValueError("剧情文本组没有可用的 16 KiB Bank pair。")
        records = extract_story_group(self.story_text_codec, selector, self.working)
        packed = pack_story_group(records.with_replacement(index, bytes(data)), pair[0])
        text_used = packed.used_bytes - (STORY_DATA_START - 0x8000)
        return text_used, STORY_DATA_CAPACITY

    def set_story_text_raw(self, selector: int, index: int, data: bytes) -> None:
        plan = self.expansion_plan
        if plan is not None:
            records = extract_story_group(
                self.story_text_codec, selector, self.working
            )
            if records.record_for_index(index).raw == bytes(data):
                return
            target_plan = (
                plan if plan.story_pair_for(selector) else plan.with_story_selector(selector)
            )
            pair = target_plan.story_pair_for(selector)
            if pair is None:
                raise ValueError("剧情文本组没有可用的 16 KiB Bank pair。")
            packed = pack_story_group(
                records.with_replacement(index, bytes(data)), pair[0]
            )
            descriptor_before = bytes(
                self.working[
                    packed.descriptor_file_offset : packed.descriptor_file_offset + 2
                ]
            )
            allowed_descriptors = {
                bytes(
                    self.original[
                        packed.descriptor_file_offset : packed.descriptor_file_offset + 2
                    ]
                ),
                packed.descriptor,
            }
            if descriptor_before not in allowed_descriptors:
                raise RomFormatError(
                    f"剧情文本组 ${selector:02X} 的资源描述符已被其他修改占用。"
                )
            before_snapshot = self._mutation_snapshot()
            try:
                start = packed.pair_file_offset
                self.working[start : start + len(packed.pair_image)] = packed.pair_image
                self.working[
                    packed.descriptor_file_offset : packed.descriptor_file_offset + 2
                ] = packed.descriptor
                self._write_expansion_plan(target_plan)
                self._refresh_dynamic_codecs()
            except Exception:
                if before_snapshot is not None:
                    self.working[:] = before_snapshot.data
                    self.resource_allocator = BankAllocator(
                        self.profile, self.original, before_snapshot.allocations
                    )
                    self._refresh_dynamic_codecs()
                raise
            self._finish_mutation(
                before_snapshot,
                f"剧情文本 ${selector:02X}:{index:02X} · 自动扩容",
            )
            return
        before_snapshot = self._mutation_snapshot()
        offset, _before, after = self.story_text_codec.replacement_patch(
            bytes(self.working), selector, index, data
        )
        self.working[offset : offset + len(after)] = after
        self._finish_mutation(
            before_snapshot,
            f"剧情文本 ${selector:02X}:{index:02X}",
        )

    def reset_story_text(self, selector: int, index: int) -> None:
        if self.expansion_plan is not None:
            original = extract_story_group(
                self.base_story_text_codec, selector, self.original
            ).record_for_index(index)
            self.set_story_text_raw(selector, index, original.raw)
            return
        before_snapshot = self._mutation_snapshot()
        record = self.story_text_codec.decode(selector, index, bytes(self.working))
        if not record.capacity:
            return
        group = next(item for item in self.story_text_groups if item.selector == selector)
        offset = self.story_text_codec.cpu_to_file_offset(group.prg_bank, record.pointer)
        self.working[offset : offset + record.capacity] = self.original[
            offset : offset + record.capacity
        ]
        self._finish_mutation(
            before_snapshot,
            f"剧情文本 ${selector:02X}:{index:02X} · 还原",
        )

    def get_battle_music_binding(
        self,
        selector: int,
        *,
        original: bool = False,
    ):
        if self.battle_music_codec is None:
            raise ValueError("当前 ROM 没有已验证的战斗音乐表。")
        source = self.original if original else self.working
        return self.battle_music_codec.decode(selector, source)

    def set_battle_music_binding(
        self,
        selector: int,
        attacker_command: int,
        defender_command: int,
    ) -> None:
        if self.battle_music_codec is None:
            raise ValueError("当前 ROM 没有已验证的战斗音乐表。")
        before_snapshot = self._mutation_snapshot()
        patches = self.battle_music_codec.replacement_patches(
            self.working,
            selector,
            attacker_command,
            defender_command,
        )
        for offset, _before, after in patches:
            self.working[offset : offset + len(after)] = after
        label = self.battle_music_selector_label(selector)
        self._finish_mutation(
            before_snapshot,
            f"人物战斗音乐 ${selector:02X} · {label}",
        )

    def reset_battle_music_binding(self, selector: int) -> None:
        original = self.get_battle_music_binding(selector, original=True)
        self.set_battle_music_binding(
            selector,
            original.attacker_command,
            original.defender_command,
        )

    def reset_all(self) -> None:
        before = self._mutation_snapshot()
        self.working[:] = self.original
        self.resource_allocator = BankAllocator(self.profile, self.original)
        if (plan := ExpansionPlan.from_bytes(self.working)) is not None:
            self._reserve_plan_partitions(plan)
            if self._initial_expansion_plan is not None:
                self._reserve_direct_reopen_guards(plan)
        self._refresh_dynamic_codecs()
        self._finish_mutation(before, "还原全部修改")

    def aliases_for_ids(self, ids: tuple[int, ...]) -> str:
        alias_table = self.unit_alias_table()
        aliases = tuple(
            dict.fromkeys(alias_table[unit_id] for unit_id in ids if unit_id in alias_table)
        )
        if aliases:
            return " / ".join(aliases)
        if self.profile.uses_original_name_aliases:
            return "空白/未分配机体记录"
        return f"机体记录 {compact_ids(ids)}"

    def change_rows(self) -> list[tuple[int, int, int]]:
        rows: list[tuple[int, int, int]] = []
        # Skip equal blocks with native comparison. A normal form edit changes
        # only a few bytes in a 1.25 MiB ROM; Python need not visit every byte.
        for start in range(0, len(self.original), 4096):
            before = self.original[start : start + 4096]
            after = self.working[start : start + 4096]
            if before == after:
                continue
            rows.extend(
                (start + index, old, new)
                for index, (old, new) in enumerate(zip(before, after))
                if old != new
            )
        return rows

    def change_ranges(self) -> tuple[tuple[int, int], ...]:
        rows = self.change_rows()
        if not rows:
            return ()
        ranges: list[tuple[int, int]] = []
        start = previous = rows[0][0]
        for offset, _old, _new in rows[1:]:
            if offset == previous + 1:
                previous = offset
                continue
            ranges.append((start, previous + 1))
            start = previous = offset
        ranges.append((start, previous + 1))
        return tuple(ranges)

    def validate(self) -> tuple[ValidationIssue, ...]:
        return validate_project(self)

    def _require_valid_output(self, action: str) -> tuple[ValidationIssue, ...]:
        issues = self.validate()
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError(
                f"{action}前完整性检查失败：\n"
                + "\n".join(
                    f"[{issue.module}] {issue.message}" for issue in errors
                )
            )
        return issues

    def change_description(self, offset: int) -> str:
        for allocation in self.expansion_allocations:
            if allocation.offset <= offset < allocation.end:
                return f"扩展资源 · {allocation.label}（{allocation.resource_id}）"
        if self.chr_codec.offset <= offset < self.chr_codec.offset + self.chr_codec.size:
            tile_index = (offset - self.chr_codec.offset) // 16
            return f"CHR图块 ${tile_index:04X}"
        if self.custom_music_codec is not None:
            for slot in self.custom_music_codec.slots:
                start = self.custom_music_codec.bank_offset(slot)
                if start <= offset < start + 0x2000:
                    return f"扩展曲 ${slot.command:02X} · {slot.label}"
        if self.map_trigger_codec is not None:
            pointer_start = self.map_trigger_codec.pointer_table_offset
            pointer_end = pointer_start + self.map_trigger_codec.spec.scenario_count * 2
            if pointer_start <= offset < pointer_end:
                return f"地图 {(offset - pointer_start) // 2:02X} · 事件指针"
            pool_start = self.map_trigger_codec.pool_offset
            if pool_start <= offset < pool_start + self.map_trigger_codec.pool_capacity:
                return "地图事件与商店托管数据"
        if self.chapter_event_codec is not None:
            spec = self.chapter_event_codec.spec
            start = self.chapter_event_codec.data_address_to_file_offset(spec.data_start)
            end = start + spec.data_end - spec.data_start
            if start <= offset < end:
                instruction = next(
                    (
                        item
                        for item in self.chapter_event_codec.instructions(bytes(self.working))
                        if item.file_offset <= offset < item.file_offset + len(item.raw)
                    ),
                    None,
                )
                return (
                    f"章节事件 ${instruction.address:04X} · {instruction.action_label}"
                    if instruction is not None
                    else "章节事件脚本"
                )
        if self.persuasion_rule_codec is not None:
            start = self.persuasion_rule_codec.spec.table_offset
            end = start + self.persuasion_rule_codec.spec.slot_count * 3
            if start <= offset < end:
                slot = (offset - start) // 3
                return f"劝降规则 ${slot:02X} · 章节/劝说者/目标"
        if self.profile.battle_music is not None:
            spec = self.profile.battle_music
            for label, start in (
                ("主动攻击", spec.attacker_table_offset),
                ("被攻击", spec.defender_table_offset),
            ):
                if start <= offset < start + spec.selector_count:
                    selector = offset - start
                    return (
                        f"人物战斗音乐 ${selector:02X} · "
                        f"{spec.selector_label(selector)} · {label}"
                    )
        if (
            self.profile.unit_name_pointer_table_offset + 2
            <= offset
            < self.profile.unit_name_pointer_table_offset + self.unit_count * 2
        ):
            unit_id = (offset - self.profile.unit_name_pointer_table_offset) // 2
            return f"机体 {unit_id:02X} · 名称指针"
        if (
            self.character_name_codec is not None
            and self.profile.character_name_pointer_table_offset is not None
            and self.profile.character_name_pointer_table_offset + 2
            <= offset
            < self.profile.character_name_pointer_table_offset
            + self.profile.character_name_count * 2
        ):
            character_id = (
                offset - self.profile.character_name_pointer_table_offset
            ) // 2
            return f"人物 {character_id:02X} · 名称指针"
        for group in self.story_text_groups:
            for pointer, ids in self.story_text_codec.ids_by_pointer(group.selector).items():
                if not group.data_start <= pointer < group.data_end:
                    continue
                record = self.story_text_codec.decode(group.selector, ids[0])
                record_offset = self.story_text_codec.cpu_to_file_offset(
                    group.prg_bank, pointer
                )
                if record_offset <= offset < record_offset + record.capacity:
                    return (
                        f"剧情文本 ${group.selector:02X}:"
                        f"{compact_ids(ids)} · Token 数据"
                    )
        for map_id in range(self.scenario_count):
            layout_offset = self.scenario_layout_codec.record_offset(map_id)
            capacity = self.scenario_layout_codec.capacities[map_id]
            if layout_offset <= offset < layout_offset + capacity:
                return f"场景 {map_id:02X} · 部署数据"
        for map_id in range(self.map_count):
            map_offset = self.map_codec.record_offset(map_id)
            capacity = self.map_codec.capacities[map_id]
            if map_offset <= offset < map_offset + capacity:
                return f"地图 {map_id:02X} · 压缩地形数据"
        if self.unit_weapon_codec is not None:
            for unit_id in range(1, self.unit_count):
                config_offset = self.unit_weapon_codec.record_offset(unit_id)
                if config_offset <= offset < config_offset + UNIT_WEAPON_SLOT_COUNT:
                    return f"机体 {unit_id:02X} · 武器槽 {offset - config_offset + 1}"
        for pointer, ids in self.ids_by_pointer.items():
            record_offset = self.record_file_offset_from_pointer(pointer)
            if record_offset <= offset < record_offset + UNIT_RECORD_SIZE:
                relative = offset - record_offset
                for field in FIELDS:
                    if field.record_offset <= relative < field.record_offset + field.width:
                        return f"机体 {compact_ids(ids)} · {field.label}"
                return f"机体 {compact_ids(ids)} · 高级字节 +{relative:02X}"
        seen_weapon_pointers: set[int] = set()
        for weapon_id in range(1, self.weapon_count):
            pointer = self.weapon_codec.pointers[weapon_id]
            if pointer in seen_weapon_pointers:
                continue
            seen_weapon_pointers.add(pointer)
            record_offset = self.weapon_record_file_offset(weapon_id)
            if record_offset <= offset < record_offset + WEAPON_RECORD_SIZE:
                relative = offset - record_offset
                for field in WEAPON_FIELDS:
                    if field.record_offset == relative:
                        return f"武器 {weapon_id:02X} · {field.label}"
                return f"武器 {weapon_id:02X} · 候选字节 +{relative:02X}"
        return "ROM 数据"

    def save_as(self, path: str | Path, *, make_backup: bool = True) -> Path:
        self._require_valid_output("输出 ROM")
        destination = self._resolve_output_path(path)
        if destination == self.path.resolve():
            raise ValueError("不能覆盖当前载入的基准 ROM，请使用新文件名。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if make_backup and destination.exists():
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = destination.with_name(destination.name + f".{timestamp}.bak")
            shutil.copy2(destination, backup)
        atomic_write_bytes(destination, bytes(self.working))
        return destination

    def export_ips(self, path: str | Path) -> Path:
        self._require_valid_output("导出 IPS")
        destination = self._resolve_output_path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(destination, make_ips(self.original, bytes(self.working)))
        return destination

    @staticmethod
    def _backup_existing(path: Path) -> Path | None:
        if not path.exists():
            return None
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(path.name + f".{timestamp}.bak")
        shutil.copy2(path, backup)
        return backup

    def build_release(self, output_dir: str | Path, name: str) -> BuildArtifacts:
        if not name.strip() or Path(name).name != name:
            raise ValueError("构建名称不能为空，也不能包含路径。")
        issues = self._require_valid_output("一键构建")

        directory = self._resolve_output_path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        rom_path = directory / f"{name}.nes"
        ips_path = directory / f"{name}.ips"
        project_path = directory / f"{name}.dcmod"
        report_path = directory / f"{name}.build-report.json"
        if rom_path == self.path:
            raise ValueError("一键构建不能覆盖当前载入的基准 ROM。")

        for path in (rom_path, ips_path, project_path, report_path):
            self._backup_existing(path)

        output = bytes(self.working)
        output_sha256 = hashlib.sha256(output).hexdigest().upper()
        rows = self.change_rows()
        ranges = []
        for start, end in self.change_ranges():
            descriptions = sorted(
                {
                    self.change_description(offset)
                    for offset in range(start, end)
                    if self.original[offset] != self.working[offset]
                }
            )
            ranges.append(
                {
                    "start": start,
                    "endExclusive": end,
                    "length": end - start,
                    "descriptions": descriptions,
                }
            )
        plan = self.expansion_plan
        managed_descriptor_selectors: set[int] = set()
        if plan is not None:
            if plan.flags & FLAG_UNITS:
                managed_descriptor_selectors.update(
                    (
                        UNIT_NAME_SELECTOR,
                        UNIT_BODY_SELECTOR,
                        UNIT_FRAGMENT_SELECTOR,
                        UNIT_ATTRIBUTE_SELECTOR,
                        UNIT_CONFIGURATION_SELECTOR,
                    )
                )
            managed_descriptor_selectors.update(plan.expanded_story_selectors)
        managed_protected_offsets: set[int] = set()
        for selector in managed_descriptor_selectors:
            start = resource_descriptor_offset(selector)
            managed_protected_offsets.update((start, start + 1))
        report = {
            "toolVersion": "2.2.0",
            "base": {
                "path": str(self.path),
                "profile": self.profile.key,
                "profileLabel": self.profile.label,
                "sha256": self.source_sha256,
                "mapper": self.rom_image.mapper,
                "size": len(self.original),
            },
            "output": {
                "rom": str(rom_path),
                "ips": str(ips_path),
                "project": str(project_path),
                "sha256": output_sha256,
                "size": len(output),
            },
            "changedBytes": len(rows),
            "changedRanges": ranges,
            "romLayout": {
                "protectedRegions": [
                    {
                        "banks": region.display,
                        "label": region.label,
                        "bytes": region.size,
                        "unmanagedBytesUnchanged": all(
                            self.original[offset] == output[offset]
                            or offset in managed_protected_offsets
                            for offset in range(
                                16 + region.first_bank * 0x2000,
                                16 + region.end_bank * 0x2000,
                            )
                        ),
                    }
                    for region in self.profile.protected_prg_regions
                ],
                "freeRegions": [
                    {
                        "banks": region.display,
                        "label": region.label,
                        "capacityBytes": region.size,
                        "unchanged": all(
                            self.original[16 + bank * 0x2000 : 16 + (bank + 1) * 0x2000]
                            == output[16 + bank * 0x2000 : 16 + (bank + 1) * 0x2000]
                            for bank in range(region.first_bank, region.end_bank)
                        ),
                    }
                    for region in self.profile.free_prg_regions
                ],
                "managedAllocations": [
                    {
                        "resourceId": allocation.resource_id,
                        "label": allocation.label,
                        "offset": allocation.offset,
                        "size": allocation.size,
                        "alignment": allocation.alignment,
                    }
                    for allocation in self.expansion_allocations
                ],
                "managedCapacityBytes": self.expansion_capacity,
                "managedUsedBytes": self.expansion_used,
                "managedAvailableBytes": self.expansion_available,
            },
            "validation": [
                {
                    "severity": issue.severity,
                    "module": issue.module,
                    "message": issue.message,
                }
                for issue in issues
            ],
        }
        atomic_write_bytes(rom_path, output)
        atomic_write_bytes(ips_path, make_ips(self.original, output))
        atomic_write_text(
            project_path,
            json.dumps(self.to_project_document().to_dict(), ensure_ascii=False, indent=2)
            + "\n",
        )
        atomic_write_text(
            report_path,
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        return BuildArtifacts(
            rom_path,
            ips_path,
            project_path,
            report_path,
            output_sha256,
            len(rows),
        )

    def to_project_document(self) -> ProjectDocument:
        document = ProjectDocument.create(self.rom_image)
        covered_offsets: set[int] = set()
        plan = self.expansion_plan
        units_are_linked = bool(plan is not None and plan.flags & FLAG_UNITS)
        maps_are_linked = bool(plan is not None and plan.flags & FLAG_MAPS)
        for allocation in self.expansion_allocations:
            if allocation.resource_id.startswith(REOPEN_GUARD_PREFIX):
                continue
            document.add_resource_allocation(
                allocation,
                bytes(self.working[allocation.offset : allocation.end]),
            )
            covered_offsets.update(range(allocation.offset, allocation.end))
        for pointer, ids in (() if units_are_linked else self.ids_by_pointer.items()):
            unit_id = ids[0]
            record_offset = self.record_file_offset_from_pointer(pointer)
            for field in FIELDS:
                if field.mask is not None:
                    before_record = self.record_bytes(unit_id, original=True)
                    after_record = self.record_bytes(unit_id)
                    if ((before_record[field.record_offset] ^ after_record[field.record_offset])
                            & ~field.mask):
                        # Preserve simultaneous raw edits to the other bits.
                        # The generic raw patch below owns the whole byte.
                        continue
                original_value = self.get_value(unit_id, field.key, original=True)
                current_value = self.get_value(unit_id, field.key)
                if original_value == current_value:
                    continue
                document.add_unit_field(
                    unit_id,
                    field.key,
                    current_value,
                    original_value,
                )
                covered_offsets.update(
                    range(
                        record_offset + field.record_offset,
                        record_offset + field.record_offset + field.width,
                    )
                )

        seen_weapon_pointers = set()
        for weapon_id in range(1, self.weapon_count):
            pointer = self.weapon_codec.pointers[weapon_id]
            if pointer in seen_weapon_pointers:
                continue
            seen_weapon_pointers.add(pointer)
            record_offset = self.weapon_record_file_offset(weapon_id)
            for field in WEAPON_FIELDS:
                if field.mask is not None:
                    before_record = self.weapon_record_bytes(weapon_id, original=True)
                    after_record = self.weapon_record_bytes(weapon_id)
                    if ((before_record[field.record_offset] ^ after_record[field.record_offset])
                            & ~field.mask):
                        # Range and skill share a byte. Preserve both with
                        # a raw patch when bits outside this field also change.
                        continue
                original_value = self.get_weapon_value(
                    weapon_id, field.key, original=True
                )
                current_value = self.get_weapon_value(weapon_id, field.key)
                if original_value == current_value:
                    continue
                document.add_weapon_field(
                    weapon_id,
                    field.key,
                    current_value,
                    original_value,
                )
                covered_offsets.add(record_offset + field.record_offset)

        if self.weapon_name_codec is not None:
            for weapon_id in range(1, self.weapon_count):
                original_pointer = self.get_weapon_name_pointer(
                    weapon_id, original=True
                )
                current_pointer = self.get_weapon_name_pointer(weapon_id)
                if original_pointer == current_pointer:
                    continue
                source_ids = self.weapon_name_codec.source_ids(current_pointer)
                if not source_ids:
                    continue
                document.add_weapon_name_reference(
                    weapon_id,
                    source_ids[0],
                    original_pointer,
                )
                offset = self.weapon_name_codec.pointer_offset(weapon_id)
                covered_offsets.update(range(offset, offset + 2))

        if self.unit_weapon_codec is not None and not units_are_linked:
            for unit_id in range(1, self.unit_count):
                original_ids = self.get_unit_weapons(unit_id, original=True)
                current_ids = self.get_unit_weapons(unit_id)
                config_offset = self.unit_weapon_codec.record_offset(unit_id)
                for slot, (original_id, current_id) in enumerate(
                    zip(original_ids, current_ids)
                ):
                    if original_id == current_id:
                        continue
                    document.add_unit_weapon_slot(
                        unit_id,
                        slot,
                        current_id,
                        original_id,
                    )
                    covered_offsets.add(config_offset + slot)

        for unit_id in (() if units_are_linked else range(1, self.unit_count)):
            original_pointer = self.get_unit_name_pointer(unit_id, original=True)
            current_pointer = self.get_unit_name_pointer(unit_id)
            if original_pointer == current_pointer:
                continue
            source_ids = self.unit_name_codec.source_ids(current_pointer)
            if not source_ids:
                continue
            document.add_unit_name_reference(
                unit_id,
                source_ids[0],
                original_pointer,
            )
            offset = self.unit_name_codec.pointer_offset(unit_id)
            covered_offsets.update(range(offset, offset + 2))

        if self.character_name_codec is not None:
            for character_id in range(1, self.profile.character_name_count):
                original_pointer = self.get_character_name_pointer(
                    character_id, original=True
                )
                current_pointer = self.get_character_name_pointer(character_id)
                if original_pointer == current_pointer:
                    continue
                source_ids = self.character_name_codec.source_ids(current_pointer)
                if not source_ids:
                    continue
                document.add_character_name_reference(
                    character_id,
                    source_ids[0],
                    original_pointer,
                )
                offset = self.character_name_codec.pointer_offset(character_id)
                covered_offsets.update(range(offset, offset + 2))

        for map_id in (() if maps_are_linked else range(self.map_count)):
            original_map = self.get_map(map_id, original=True)
            current_map = self.get_map(map_id)
            if (
                original_map.width == current_map.width
                and original_map.height == current_map.height
                and original_map.tiles == current_map.tiles
            ):
                continue
            document.add_map_replace(
                map_id,
                current_map.width,
                current_map.height,
                current_map.tiles,
                self.map_codec.semantic_digest(original_map),
            )
            offset = self.map_codec.record_offset(map_id)
            covered_offsets.update(range(offset, offset + self.map_codec.capacities[map_id]))

        seen_scenario_pointers: set[int] = set()
        for map_id in (() if maps_are_linked else range(self.scenario_count)):
            pointer = self.scenario_layout_codec.pointers[map_id]
            if pointer in seen_scenario_pointers:
                continue
            seen_scenario_pointers.add(pointer)
            original_layout = self.get_scenario_layout(map_id, original=True)
            current_layout = self.get_scenario_layout(map_id)
            if (
                self.scenario_layout_codec.encode(original_layout)
                == self.scenario_layout_codec.encode(current_layout)
            ):
                continue
            document.add_scenario_layout_replace(
                current_layout,
                self.scenario_layout_codec.semantic_digest(original_layout),
            )
            offset = self.scenario_layout_codec.record_offset(map_id)
            covered_offsets.update(
                range(offset, offset + self.scenario_layout_codec.capacities[map_id])
            )

        if self.map_trigger_codec is not None and not maps_are_linked:
            triggers_changed = False
            for map_id in range(self.map_trigger_codec.spec.scenario_count):
                original_layout = self.map_trigger_codec.decode(map_id, self.original)
                current_layout = self.map_trigger_codec.decode(
                    map_id, bytes(self.working)
                )
                if original_layout.entries == current_layout.entries:
                    continue
                triggers_changed = True
                document.add_map_trigger_replace(
                    map_id,
                    current_layout.entries,
                    self.map_trigger_codec.semantic_digest(original_layout),
                )
            if triggers_changed:
                pointer_start = self.map_trigger_codec.pointer_table_offset
                pointer_size = self.map_trigger_codec.spec.scenario_count * 2
                covered_offsets.update(range(pointer_start, pointer_start + pointer_size))
                pool_start = self.map_trigger_codec.pool_offset
                covered_offsets.update(
                    range(pool_start, pool_start + self.map_trigger_codec.pool_capacity)
                )

        for group in self.story_text_groups:
            if plan is not None and plan.story_pair_for(group.selector) is not None:
                continue
            for pointer, indices in self.story_text_codec.ids_by_pointer(
                group.selector
            ).items():
                if not group.data_start <= pointer < group.data_end:
                    continue
                text_index = indices[0]
                original_record = self.get_story_text(
                    group.selector, text_index, original=True
                )
                current_record = self.get_story_text(group.selector, text_index)
                if original_record.raw == current_record.raw:
                    continue
                document.add_story_text_replace(
                    group.selector,
                    text_index,
                    current_record.raw,
                    self.story_text_codec.semantic_digest(original_record),
                )
                offset = self.story_text_codec.cpu_to_file_offset(
                    group.prg_bank, pointer
                )
                covered_offsets.update(range(offset, offset + current_record.capacity))

        if self.battle_music_codec is not None:
            spec = self.profile.battle_music
            for selector in range(spec.selector_count):
                original_binding = self.get_battle_music_binding(
                    selector, original=True
                )
                current_binding = self.get_battle_music_binding(selector)
                if (
                    original_binding.attacker_command
                    == current_binding.attacker_command
                    and original_binding.defender_command
                    == current_binding.defender_command
                ):
                    continue
                document.add_battle_music_binding(
                    selector,
                    current_binding.attacker_command,
                    current_binding.defender_command,
                    original_binding.attacker_command,
                    original_binding.defender_command,
                )
                covered_offsets.add(current_binding.attacker_offset)
                covered_offsets.add(current_binding.defender_offset)

        remaining = [
            row for row in self.change_rows() if row[0] not in covered_offsets
        ]
        index = 0
        while index < len(remaining):
            start = remaining[index][0]
            before = bytearray((remaining[index][1],))
            after = bytearray((remaining[index][2],))
            index += 1
            while index < len(remaining) and remaining[index][0] == start + len(before):
                before.append(remaining[index][1])
                after.append(remaining[index][2])
                index += 1
            document.add_raw_patch(start, bytes(before), bytes(after))
        return document

    def save_project(self, path: str | Path) -> Path:
        destination = self._resolve_output_path(path)
        atomic_write_text(
            destination,
            json.dumps(
                self.to_project_document().to_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        return destination

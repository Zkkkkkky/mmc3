from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ..constants import UNIT_WEAPON_SLOT_COUNT
from ..errors import RomFormatError
from ..expansion import (
    FLAG_MAPS,
    FLAG_MAP_TRIGGERS,
    FLAG_SCENARIOS,
    FLAG_UNITS,
    STORY_SELECTORS,
    bank_file_offset,
    resource_descriptor_offset,
)
from ..expansion_map import (
    pack_map_resources,
    read_expanded_map_layout,
    read_expanded_map_payloads,
)
from ..expansion_story import story_descriptor_offset
from ..expansion_unit import (
    CONFIGURATION_CAVE_END,
    CONFIGURATION_CAVE_START,
    CONFIGURATION_OLD_DATA_END,
    CONFIGURATION_TABLE,
    SOURCE_CONFIGURATION_PAIR,
    SOURCE_CORE_PAIR,
    UNIT_ATTRIBUTE_SELECTOR,
    UNIT_BODY_SELECTOR,
    UNIT_CONFIGURATION_SELECTOR,
    UNIT_FRAGMENT_SELECTOR,
    UNIT_NAME_SELECTOR,
    validate_unit_expansion_payload,
)
from ..profiles import (
    DC_EXPANDED_MMC3_PROFILE,
    dc_expanded_mmc3_protected_signature_is_valid,
)

Severity = Literal["error", "warning", "info"]

CORE_LOADER_RANGES = (
    (0x8064, 0x8098),
    (0x8290, 0x82B2),
)


def _first_range_difference(
    source: bytes | bytearray,
    source_bank: int,
    target_bank: int,
    ranges: tuple[tuple[int, int], ...],
) -> int | None:
    source_start = bank_file_offset(source_bank)
    target_start = bank_file_offset(target_bank)
    for range_start, range_end in ranges:
        for cpu_address in range(range_start, range_end):
            relative = cpu_address - 0x8000
            if source[source_start + relative] != source[target_start + relative]:
                return cpu_address
    return None


def _first_difference_excluding(
    source: bytes | bytearray,
    source_bank: int,
    target_bank: int,
    excluded_ranges: tuple[tuple[int, int], ...],
) -> int | None:
    """Compare a full 16 KiB pair except explicitly mutable data pools."""

    source_start = bank_file_offset(source_bank)
    target_start = bank_file_offset(target_bank)
    for cpu_address in range(0x8000, 0xC000):
        if any(start <= cpu_address < end for start, end in excluded_ranges):
            continue
        relative = cpu_address - 0x8000
        if source[source_start + relative] != source[target_start + relative]:
            return cpu_address
    return None


@dataclass(frozen=True)
class ValidationIssue:
    severity: Severity
    module: str
    message: str


class ProjectView(Protocol):
    original: bytes
    working: bytearray
    map_codec: object
    scenario_layout_codec: object
    map_trigger_codec: object | None
    story_text_codec: object
    unit_name_codec: object
    unit_count: int
    weapon_count: int
    map_count: int
    scenario_count: int
    story_text_groups: tuple
    profile: object
    battle_music_codec: object | None
    character_name_codec: object | None
    custom_music_codec: object | None
    chapter_event_codec: object | None
    persuasion_rule_codec: object | None
    unit_weapon_codec: object | None
    weapon_name_codec: object | None
    expansion_allocations: tuple
    expansion_capacity: int
    expansion_used: int
    expansion_available: int
    expansion_plan: object | None

    def get_map(self, map_id: int, *, original: bool = False): ...

    def get_scenario_layout(self, map_id: int, *, original: bool = False): ...

    def get_map_triggers(self, map_id: int, *, original: bool = False): ...

    def get_story_text(self, selector: int, index: int, *, original: bool = False): ...

    def record_bytes(self, unit_id: int, *, original: bool = False) -> bytes: ...

    def weapon_record_bytes(self, weapon_id: int, *, original: bool = False) -> bytes: ...

    def get_unit_name_pointer(self, unit_id: int, *, original: bool = False) -> int: ...

    def get_unit_weapons(self, unit_id: int, *, original: bool = False): ...

    def get_weapon_name_pointer(self, weapon_id: int, *, original: bool = False) -> int: ...

    def get_character_name_pointer(self, character_id: int, *, original: bool = False) -> int: ...

    def get_persuasion_rule(self, slot: int, *, original: bool = False): ...


def validate_project(project: ProjectView) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    allowed_protected_offsets: set[int] = set()
    expanded_map_usage: tuple[int, int] | None = None
    if len(project.working) != len(project.original):
        issues.append(ValidationIssue("error", "ROM", "输出 ROM 大小发生变化。"))
    if bytes(project.working[:16]) != bytes(project.original[:16]):
        issues.append(
            ValidationIssue(
                "error",
                "ROM",
                "iNES 头被修改；当前修改器不允许改变 ROM 容量、Mapper 或镜像标志。",
            )
        )
    if project.profile is DC_EXPANDED_MMC3_PROFILE:
        try:
            protected_signature_valid = (
                dc_expanded_mmc3_protected_signature_is_valid(project.working)
            )
        except ValueError:
            protected_signature_valid = False
        if not protected_signature_valid:
            issues.append(
                ValidationIssue(
                    "error",
                    "安全",
                    "认证固定代码签名不匹配；iNES 头或 "
                    "Bank $64/$7E/$7F 含未经验证的修改。",
                )
            )

    try:
        plan = project.expansion_plan
    except ValueError as error:
        plan = None
        issues.append(ValidationIssue("error", "容量规划", str(error)))

    if plan is not None:
        expected_flags = FLAG_MAPS | FLAG_SCENARIOS | FLAG_MAP_TRIGGERS | FLAG_UNITS
        if (plan.flags & expected_flags) != expected_flags:
            issues.append(
                ValidationIssue("error", "容量规划", "自动链接状态不完整。")
            )

        expected_by_category = {
            "unit": set(plan.unit_banks),
            "map": set(plan.map_banks),
            "story": set(plan.story_banks),
        }
        actual_by_category = {key: set() for key in expected_by_category}
        for allocation in project.expansion_allocations:
            prefix = "auto.partition."
            if not allocation.resource_id.startswith(prefix):
                continue
            category = allocation.resource_id[len(prefix) :].split(".", 1)[0]
            if category not in actual_by_category:
                issues.append(
                    ValidationIssue(
                        "error",
                        "容量规划",
                        f"未知自动分区：{allocation.resource_id}。",
                    )
                )
                continue
            relative = allocation.offset - 16
            if relative < 0 or relative % 0x2000 or allocation.size % 0x2000:
                issues.append(
                    ValidationIssue(
                        "error", "容量规划", f"{allocation.resource_id} 未按 Bank 对齐。"
                    )
                )
                continue
            first = relative // 0x2000
            actual_by_category[category].update(
                range(first, first + allocation.size // 0x2000)
            )
        for category, expected in expected_by_category.items():
            if actual_by_category[category] != expected:
                issues.append(
                    ValidationIssue(
                        "error",
                        "容量规划",
                        f"{category} 分区登记与容量表不一致。",
                    )
                )

        if plan.flags & FLAG_MAPS:
            try:
                map_layout = read_expanded_map_layout(project.working)
                referenced = {
                    item.bank
                    for group in (
                        map_layout.terrain,
                        map_layout.scenarios,
                        map_layout.triggers,
                    )
                    for item in group
                }
                outside = referenced - set(plan.map_banks)
                if outside:
                    labels = "、".join(f"${bank:02X}" for bank in sorted(outside))
                    issues.append(
                        ValidationIssue(
                            "error", "地图扩展", f"地图资源越过地图分区：{labels}。"
                        )
                    )
                payloads = read_expanded_map_payloads(project.working)
                packed = pack_map_resources(
                    payloads.terrain,
                    payloads.scenarios,
                    payloads.triggers,
                    plan.map_banks,
                )
                expanded_map_usage = (packed.used_bytes, packed.capacity)
            except (ValueError, RomFormatError) as error:
                issues.append(ValidationIssue("error", "地图扩展", str(error)))

        if plan.flags & FLAG_UNITS:
            if len(plan.unit_banks) not in (6, 8, 10):
                issues.append(
                    ValidationIssue(
                        "error", "机体扩展", "机体分区必须为 48、64 或 80 KiB。"
                    )
                )
            else:
                core, configuration, body = (
                    plan.unit_banks[0],
                    plan.unit_banks[2],
                    plan.unit_banks[4],
                )
                fragment = (
                    plan.unit_banks[6]
                    if len(plan.unit_banks) >= 8
                    else body
                )
                name = (
                    plan.unit_banks[8]
                    if len(plan.unit_banks) == 10
                    else core
                )
                expected_descriptors = {
                    UNIT_NAME_SELECTOR: bytes((0xF6, name)),
                    UNIT_BODY_SELECTOR: bytes((0xF0, body)),
                    UNIT_FRAGMENT_SELECTOR: bytes((0xF1, fragment)),
                    UNIT_ATTRIBUTE_SELECTOR: bytes((0xF2, core)),
                    UNIT_CONFIGURATION_SELECTOR: bytes((0xF6, configuration)),
                }
                for selector, expected in expected_descriptors.items():
                    offset = resource_descriptor_offset(selector)
                    allowed_protected_offsets.update((offset, offset + 1))
                    if bytes(project.working[offset : offset + 2]) != expected:
                        issues.append(
                            ValidationIssue(
                                "error",
                                "机体扩展",
                                f"资源选择器 ${selector:02X} 未绑定到机体分区。",
                            )
                        )
                core_difference = _first_range_difference(
                    project.working,
                    SOURCE_CORE_PAIR,
                    core,
                    CORE_LOADER_RANGES,
                )
                configuration_difference = _first_difference_excluding(
                    project.working,
                    SOURCE_CONFIGURATION_PAIR,
                    configuration,
                    (
                        (
                            CONFIGURATION_TABLE,
                            CONFIGURATION_OLD_DATA_END
                            + project.unit_count * UNIT_WEAPON_SLOT_COUNT,
                        ),
                        (CONFIGURATION_CAVE_START, CONFIGURATION_CAVE_END),
                    ),
                )
                for label, difference in (
                    ("核心", core_difference),
                    ("战斗配置", configuration_difference),
                ):
                    if difference is not None:
                        issues.append(
                            ValidationIssue(
                                "error",
                                "机体扩展",
                                f"{label}代码镜像在 CPU ${difference:04X} 与保留源代码不一致。",
                            )
                        )
                unit_pairs = tuple(
                    (plan.unit_banks[index], plan.unit_banks[index + 1])
                    for index in range(0, len(plan.unit_banks), 2)
                )
                try:
                    validate_unit_expansion_payload(project.working, unit_pairs)
                except ValueError as error:
                    issues.append(
                        ValidationIssue("error", "机体扩展", str(error))
                    )

        for selector in STORY_SELECTORS:
            pair = plan.story_pair_for(selector)
            if pair is None:
                continue
            offset = story_descriptor_offset(selector)
            allowed_protected_offsets.update((offset, offset + 1))
            expected = bytes((0xF0, pair[0]))
            if bytes(project.working[offset : offset + 2]) != expected:
                issues.append(
                    ValidationIssue(
                        "error",
                        "剧情扩展",
                        f"剧情组 ${selector:02X} 未绑定到分配的 Bank pair。",
                    )
                )

    for unit_id in range(1, project.unit_count):
        if len(project.record_bytes(unit_id)) != 16:
            issues.append(
                ValidationIssue("error", "机体", f"机体 {unit_id:02X} 记录长度错误。")
            )
        name_pointer = project.get_unit_name_pointer(unit_id)
        if not project.unit_name_codec.source_ids(name_pointer):
            issues.append(
                ValidationIssue(
                    "error",
                    "名称",
                    f"机体 {unit_id:02X} 的名称指针 ${name_pointer:04X} "
                    "未指向已验证的原生名称。",
                )
            )
    for weapon_id in range(1, project.weapon_count):
        if len(project.weapon_record_bytes(weapon_id)) != 6:
            issues.append(
                ValidationIssue("error", "武器", f"武器 {weapon_id:02X} 记录长度错误。")
            )

    if project.unit_weapon_codec is not None:
        for unit_id in range(1, project.unit_count):
            for slot, weapon_id in enumerate(project.get_unit_weapons(unit_id), 1):
                if not 0 <= weapon_id < project.weapon_count:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "机体武器",
                            f"机体 {unit_id:02X} 的武器槽 {slot} 引用了越界武器 "
                            f"${weapon_id:02X}。",
                        )
                    )

    if project.weapon_name_codec is not None:
        valid_pointers = set(project.weapon_name_codec.original_pointers)
        for weapon_id in range(1, project.weapon_count):
            pointer = project.get_weapon_name_pointer(weapon_id)
            if pointer not in valid_pointers:
                issues.append(
                    ValidationIssue(
                        "error",
                        "武器名称",
                        f"武器 {weapon_id:02X} 的名称指针 ${pointer:04X} "
                        "未指向已验证的原生名称。",
                    )
                )

    if project.character_name_codec is not None:
        for character_id in range(project.profile.character_name_count):
            pointer = project.get_character_name_pointer(character_id)
            if character_id and not project.character_name_codec.source_ids(pointer):
                issues.append(
                    ValidationIssue(
                        "error",
                        "人物名称",
                        f"人物 {character_id:02X} 的名称指针 ${pointer:04X} "
                        "未指向已验证的原生名称。",
                    )
                )
            if not project.character_name_codec.round_trip(
                character_id, project.working
            ):
                issues.append(
                    ValidationIssue(
                        "error",
                        "人物名称",
                        f"人物 {character_id:02X} 的战斗名称记录边界错误。",
                    )
                )

    for map_id in range(project.map_count):
        record = project.get_map(map_id)
        encoded = project.map_codec.encode(record.width, record.height, record.tiles)
        if len(encoded) > record.capacity:
            issues.append(
                ValidationIssue(
                    "error",
                    "地图",
                    f"地图 {map_id:02X} 压缩后 {len(encoded)} 字节，容量仅 {record.capacity}。",
                )
            )
    for map_id in range(project.scenario_count):
        record = project.get_map(map_id)
        layout = project.get_scenario_layout(map_id)
        try:
            project.scenario_layout_codec.validate_layout(
                layout, record.width, record.height
            )
            layout_size = len(project.scenario_layout_codec.encode(layout))
        except ValueError as error:
            issues.append(
                ValidationIssue("error", "部署", f"场景 {map_id:02X}：{error}")
            )
            layout_size = (
                len(layout.prelude)
                + 4
                + len(layout.enemies) * 6
                + len(layout.guests) * 6
                + len(layout.player_placements) * 4
            )
        if layout_size > layout.capacity:
            issues.append(
                ValidationIssue(
                    "error",
                    "部署",
                    f"场景 {map_id:02X} 部署数据 {layout_size} 字节，容量仅 {layout.capacity}。",
                )
            )
    if project.map_trigger_codec is not None:
        total_triggers = 0
        for map_id in range(project.map_trigger_codec.spec.scenario_count):
            record = project.get_map(map_id)
            entries = project.get_map_triggers(map_id)
            total_triggers += len(entries)
            try:
                project.map_trigger_codec.validate_entries(
                    entries, record.width, record.height
                )
            except ValueError as error:
                issues.append(
                    ValidationIssue(
                        "error", "地图事件", f"地图 {map_id:02X}：{error}"
                    )
                )
        try:
            trigger_used = project.map_trigger_codec.storage_used(project.working)
            used, capacity = (
                expanded_map_usage
                if expanded_map_usage is not None
                else (trigger_used, project.map_trigger_codec.pool_capacity)
            )
            if used > capacity:
                issues.append(
                    ValidationIssue(
                        "error",
                        "地图事件",
                        f"地图共享池需要 {used} 字节，容量仅 {capacity} 字节。",
                    )
                )
            else:
                issues.append(
                    ValidationIssue(
                        "info",
                        "地图事件",
                        f"32 关共有 {total_triggers} 个事件/商店；"
                        + (
                            f"地形/部署/事件共享池占用 {used} / {capacity} 字节。"
                            if expanded_map_usage is not None
                            else f"事件托管池占用 {used} / {capacity} 字节。"
                        ),
                    )
                )
        except (ValueError, RomFormatError) as error:
            issues.append(ValidationIssue("error", "地图事件", str(error)))
    for group in project.story_text_groups:
        for pointer, indices in project.story_text_codec.ids_by_pointer(
            group.selector
        ).items():
            if not group.data_start <= pointer < group.data_end:
                continue
            record = project.get_story_text(group.selector, indices[0])
            if len(record.raw) != record.capacity:
                issues.append(
                    ValidationIssue(
                        "error",
                        "剧情",
                        f"剧情文本 ${group.selector:02X}:{indices[0]:02X} 长度改变。",
                    )
                )
            terminator_end = (
                project.story_text_codec.standalone_terminator_end(record.raw)
            )
            if terminator_end is None:
                issues.append(
                    ValidationIssue(
                        "error",
                        "剧情",
                        f"剧情文本 ${group.selector:02X}:{indices[0]:02X} "
                        "缺少独立 FF 结束码。",
                    )
                )
            elif terminator_end != len(record.raw):
                issues.append(
                    ValidationIssue(
                        "error",
                        "剧情",
                        f"剧情文本 ${group.selector:02X}:{indices[0]:02X} "
                        "在独立 FF 结束码后仍有数据。",
                    )
                )

    if project.battle_music_codec is not None:
        spec = project.profile.battle_music
        supported = {track.command for track in spec.tracks}
        for selector in range(spec.selector_count):
            binding = project.battle_music_codec.decode(selector, project.working)
            for side, command in (
                ("主动攻击", binding.attacker_command),
                ("被攻击", binding.defender_command),
            ):
                if command not in supported:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "音乐",
                            f"选择器 {selector:02X} 的{side}音乐命令 "
                            f"${command:02X} 不受当前音频引擎支持。",
                        )
                    )

    if project.custom_music_codec is not None:
        for slot in project.custom_music_codec.slots:
            try:
                song_count = project.custom_music_codec.validate_bank(
                    project.custom_music_codec.bank_bytes(slot.command, project.working),
                    slot=slot,
                )
                issues.append(
                    ValidationIssue(
                        "info",
                        "音乐导入",
                        f"扩展曲槽 ${slot.command:02X} Bank ${slot.prg_bank:02X} "
                        f"含 {song_count} 首有效FamiStudio数据。",
                    )
                )
            except ValueError as error:
                issues.append(ValidationIssue("error", "音乐导入", str(error)))

    if project.chapter_event_codec is not None:
        try:
            instructions = project.chapter_event_codec.instructions(project.working)
            actions = project.chapter_event_codec.actions(project.working)
            issues.append(
                ValidationIssue(
                    "info",
                    "章节事件",
                    f"章节脚本含 {len(instructions)} 条对齐指令，其中 {len(actions)} 条为可视化动作。",
                )
            )
        except (ValueError, RomFormatError) as error:
            issues.append(ValidationIssue("error", "章节事件", str(error)))

    if project.persuasion_rule_codec is not None:
        seen: set[tuple[int, int, int]] = set()
        for slot in range(project.persuasion_rule_codec.spec.editable_count):
            try:
                rule = project.get_persuasion_rule(slot)
                project.persuasion_rule_codec.validate_rule(
                    rule, project.scenario_count
                )
                identity = (rule.scenario_id, rule.persuader_id, rule.target_id)
                if identity in seen:
                    raise ValueError(
                        f"劝降规则 ${slot:02X} 与前面规则重复。"
                    )
                seen.add(identity)
            except (ValueError, RomFormatError) as error:
                issues.append(ValidationIssue("error", "劝降", str(error)))
        issues.append(
            ValidationIssue(
                "info",
                "劝降",
                f"已验证 {len(seen)} 条章节/劝说者/目标匹配规则。",
            )
        )

    for region in project.profile.protected_prg_regions:
        start = 16 + region.first_bank * 0x2000
        end = 16 + region.end_bank * 0x2000
        if any(
            project.working[offset] != project.original[offset]
            and offset not in allowed_protected_offsets
            for offset in range(start, end)
        ):
            issues.append(
                ValidationIssue(
                    "error",
                    "安全",
                    f"受保护区域 {region.display}（{region.label}）被修改。",
                )
            )

    if project.profile.free_prg_regions:
        for region in project.profile.free_prg_regions:
            start = 16 + region.first_bank * 0x2000
            end = 16 + region.end_bank * 0x2000
            cursor = start
            unmanaged_change = False
            allocations = tuple(
                allocation
                for allocation in project.expansion_allocations
                if start <= allocation.offset and allocation.end <= end
            )
            for allocation in allocations:
                if project.working[cursor : allocation.offset] != project.original[
                    cursor : allocation.offset
                ]:
                    unmanaged_change = True
                    break
                cursor = allocation.end
            if not unmanaged_change and project.working[cursor:end] != project.original[cursor:end]:
                unmanaged_change = True
            if unmanaged_change:
                issues.append(
                    ValidationIssue(
                        "error",
                        "安全",
                        f"预留区域 {region.display}（{region.label}）被直接修改；"
                        "该写入没有登记为受管理的资源分配。",
                    )
                )
        issues.append(
            ValidationIssue(
                "info",
                "空间",
                f"托管扩展空间 {project.expansion_capacity // 1024} KiB；"
                f"已分配 {project.expansion_used} 字节，"
                f"剩余 {project.expansion_available} 字节。",
            )
        )

    if not issues:
        issues.append(ValidationIssue("info", "构建", "结构检查全部通过。"))
    return tuple(issues)

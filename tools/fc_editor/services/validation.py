from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ..errors import RomFormatError

Severity = Literal["error", "warning", "info"]


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
    unit_weapon_codec: object | None
    weapon_name_codec: object | None

    def get_map(self, map_id: int, *, original: bool = False): ...

    def get_scenario_layout(self, map_id: int, *, original: bool = False): ...

    def get_story_text(self, selector: int, index: int, *, original: bool = False): ...

    def record_bytes(self, unit_id: int, *, original: bool = False) -> bytes: ...

    def weapon_record_bytes(self, weapon_id: int, *, original: bool = False) -> bytes: ...

    def get_unit_name_pointer(self, unit_id: int, *, original: bool = False) -> int: ...

    def get_unit_weapons(self, unit_id: int, *, original: bool = False): ...

    def get_weapon_name_pointer(self, weapon_id: int, *, original: bool = False) -> int: ...


def validate_project(project: ProjectView) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if len(project.working) != len(project.original):
        issues.append(ValidationIssue("error", "ROM", "输出 ROM 大小发生变化。"))

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
            if not project.character_name_codec.round_trip(character_id):
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
        layout_size = len(project.scenario_layout_codec.encode(layout))
        if layout_size > layout.capacity:
            issues.append(
                ValidationIssue(
                    "error",
                    "部署",
                    f"场景 {map_id:02X} 部署数据 {layout_size} 字节，容量仅 {layout.capacity}。",
                )
            )
        for layer, entries in (
            ("敌军", layout.enemies),
            ("客军", layout.guests),
            ("我方", layout.player_placements),
        ):
            for index, entry in enumerate(entries):
                if not 0 <= entry.x < record.width or not 0 <= entry.y < record.height:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "部署",
                            f"场景 {map_id:02X} {layer} #{index} 坐标 "
                            f"({entry.x},{entry.y}) 超出 {record.width}×{record.height}。",
                        )
                    )

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

    for region in project.profile.protected_prg_regions:
        start = 16 + region.first_bank * 0x2000
        end = 16 + region.end_bank * 0x2000
        if project.working[start:end] != project.original[start:end]:
            issues.append(
                ValidationIssue(
                    "error",
                    "安全",
                    f"受保护区域 {region.display}（{region.label}）被修改。",
                )
            )

    if project.profile.free_prg_regions:
        capacity = sum(region.size for region in project.profile.free_prg_regions)
        for region in project.profile.free_prg_regions:
            start = 16 + region.first_bank * 0x2000
            end = 16 + region.end_bank * 0x2000
            if project.working[start:end] != project.original[start:end]:
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
                f"预留扩展空间 {capacity // 1024} KiB；当前尚未分配资源。",
            )
        )

    if not issues:
        issues.append(ValidationIssue("info", "构建", "结构检查全部通过。"))
    return tuple(issues)

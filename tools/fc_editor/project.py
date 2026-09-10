from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .changes import ChangeSet
from .codecs.battle_music import BattleMusicCodec
from .codecs.character_name import CharacterNameCodec
from .codecs.map import MapCodec
from .codecs.map_trigger import MapTrigger, MapTriggerCodec
from .codecs.scenario_layout import ScenarioLayoutCodec
from .codecs.story_text import StoryTextCodec
from .codecs.unit import UnitCodec
from .codecs.unit_name import UnitNameReferenceCodec
from .codecs.unit_weapon import UnitWeaponCodec
from .codecs.weapon import WeaponCodec
from .codecs.weapon_name import WeaponNameReferenceCodec
from .constants import PROJECT_SCHEMA_VERSION
from .errors import ProjectFormatError
from .expansion import (
    AUTO_ALLOCATION_PREFIX,
    FLAG_MAPS,
    FLAG_UNITS,
    PARTITION_ALLOCATION_PREFIX,
    ExpansionPlan,
    bank_file_offset,
)
from .expansion_map import TERRAIN_BANK_DIRECTORY_OFFSET, read_expanded_map_layout
from .expansion_unit import (
    ATTRIBUTE_TABLE,
    NAME_TABLE,
    SINGLE_RESOURCE_TABLE,
    SOURCE_CONFIGURATION_PAIR,
)
from .models import (
    PlayerPlacement,
    ScenarioEntity,
    ScenarioLayout,
    UNIT_FIELD_BY_KEY,
    WEAPON_FIELD_BY_KEY,
)
from .resources import Allocation, BankAllocator
from .rom_image import RomImage


@dataclass
class ProjectDocument:
    base_sha256: str
    base_mapper: int
    base_size: int
    tool_version: str = "2.2.0"
    operations: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(cls, rom: RomImage) -> "ProjectDocument":
        return cls(rom.sha256, rom.mapper, rom.size)

    @classmethod
    def load(cls, path: str | Path) -> "ProjectDocument":
        resolved = Path(path).expanduser().resolve()
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectFormatError(f"无法读取项目文件：{error}") from error
        payload = cls._migrate_payload(payload)
        base = payload.get("base")
        operations = payload.get("operations")
        if not isinstance(base, dict) or not isinstance(operations, list):
            raise ProjectFormatError("项目文件缺少 base 或 operations。")
        try:
            return cls(
                base_sha256=str(base["sha256"]).upper(),
                base_mapper=int(base["mapper"]),
                base_size=int(base["size"]),
                tool_version=str(payload.get("toolVersion", "unknown")),
                operations=operations,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProjectFormatError("项目文件的基准 ROM 信息无效。") from error

    @staticmethod
    def _migrate_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProjectFormatError("项目文件根节点必须是对象。")
        try:
            version = int(payload.get("schemaVersion", 0))
        except (TypeError, ValueError) as error:
            raise ProjectFormatError("项目文件版本无效。") from error
        if version == 1:
            migrated = dict(payload)
            migrated["schemaVersion"] = 2
            migrated.setdefault("toolVersion", "0.3-migrated")
            return migrated
        if version != PROJECT_SCHEMA_VERSION:
            raise ProjectFormatError(
                f"项目文件版本 {version} 不受支持；当前版本为 {PROJECT_SCHEMA_VERSION}。"
            )
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": PROJECT_SCHEMA_VERSION,
            "toolVersion": self.tool_version,
            "base": {
                "sha256": self.base_sha256,
                "mapper": self.base_mapper,
                "size": self.base_size,
            },
            "operations": self.operations,
        }

    def save(self, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return destination

    def add_unit_field(
        self,
        unit_id: int,
        field_key: str,
        value: int,
        expected_old_value: int,
    ) -> None:
        if field_key not in UNIT_FIELD_BY_KEY:
            raise ValueError(f"未知机体字段：{field_key}")
        if UNIT_FIELD_BY_KEY[field_key].evidence != "confirmed":
            raise ValueError(f"机体字段 {field_key} 尚未确认，不能写入稳定项目。")
        operation = {
            "kind": "unit.set_field",
            "unitId": unit_id,
            "field": field_key,
            "value": value,
            "expectedOldValue": expected_old_value,
        }
        self.operations.append(operation)

    def add_raw_patch(
        self,
        offset: int,
        before: bytes,
        after: bytes,
        description: str = "高级原始补丁",
    ) -> None:
        if len(before) != len(after) or not before:
            raise ValueError("原始补丁的新旧数据必须等长且不能为空。")
        self.operations.append(
            {
                "kind": "raw.patch",
                "offset": offset,
                "before": before.hex().upper(),
                "after": after.hex().upper(),
                "description": description,
            }
        )

    def add_weapon_field(
        self,
        weapon_id: int,
        field_key: str,
        value: int,
        expected_old_value: int,
    ) -> None:
        if field_key not in WEAPON_FIELD_BY_KEY:
            raise ValueError(f"未知武器字段：{field_key}")
        if WEAPON_FIELD_BY_KEY[field_key].evidence != "confirmed":
            raise ValueError(f"武器字段 {field_key} 尚未确认，不能写入稳定项目。")
        self.operations.append(
            {
                "kind": "weapon.set_field",
                "weaponId": weapon_id,
                "field": field_key,
                "value": value,
                "expectedOldValue": expected_old_value,
            }
        )

    def add_unit_weapon_slot(
        self,
        unit_id: int,
        slot: int,
        weapon_id: int,
        expected_old_weapon_id: int,
    ) -> None:
        if not 1 <= unit_id <= 0xFF:
            raise ValueError("机体 ID 必须在 01—FF 之间。")
        if slot not in (0, 1):
            raise ValueError("武器槽位必须为 0 或 1。")
        if not 0 <= weapon_id <= 0xFF:
            raise ValueError("武器 ID 必须在 00—FF 之间。")
        self.operations.append(
            {
                "kind": "unit.set_weapon_slot",
                "unitId": unit_id,
                "slot": slot,
                "weaponId": weapon_id,
                "expectedOldWeaponId": expected_old_weapon_id,
            }
        )

    def add_unit_name_reference(
        self,
        unit_id: int,
        source_name_id: int,
        expected_old_pointer: int,
    ) -> None:
        if not 1 <= unit_id <= 0xFF or not 1 <= source_name_id <= 0xFF:
            raise ValueError("机体 ID 或名称来源 ID 必须在 01—FF 之间。")
        if not 0x8000 <= expected_old_pointer <= 0xBFFF:
            raise ValueError("原名称指针必须在 $8000—$BFFF 之间。")
        self.operations.append(
            {
                "kind": "unit.set_name_reference",
                "unitId": unit_id,
                "sourceNameId": source_name_id,
                "expectedOldPointer": expected_old_pointer,
            }
        )

    def add_resource_allocation(
        self,
        allocation: Allocation,
        data: bytes,
    ) -> None:
        if len(data) != allocation.size:
            raise ValueError("资源数据长度与分配大小不一致。")
        self.operations.append(
            {
                "kind": "resource.allocate",
                "resourceId": allocation.resource_id,
                "label": allocation.label,
                "offset": allocation.offset,
                "size": allocation.size,
                "alignment": allocation.alignment,
                "data": data.hex().upper(),
            }
        )

    @staticmethod
    def _decode_resource_allocation(
        operation: dict[str, Any],
    ) -> tuple[Allocation, bytes]:
        data = bytes.fromhex(str(operation["data"]))
        allocation = Allocation(
            str(operation["resourceId"]),
            str(operation["label"]),
            int(operation["offset"]),
            int(operation["size"]),
            int(operation.get("alignment", 1)),
        )
        if not allocation.label.strip():
            raise ValueError("资源名称不能为空。")
        if len(data) != allocation.size:
            raise ValueError("资源数据长度与分配大小不一致。")
        return allocation, data

    def add_weapon_name_reference(
        self,
        weapon_id: int,
        source_name_id: int,
        expected_old_pointer: int,
    ) -> None:
        if not 1 <= weapon_id <= 0xFF or not 1 <= source_name_id <= 0xFF:
            raise ValueError("武器 ID 或名称来源 ID 必须在 01—FF 之间。")
        if not 0x8000 <= expected_old_pointer <= 0xBFFF:
            raise ValueError("原武器名称指针必须在 $8000—$BFFF 之间。")
        self.operations.append(
            {
                "kind": "weapon.set_name_reference",
                "weaponId": weapon_id,
                "sourceNameId": source_name_id,
                "expectedOldPointer": expected_old_pointer,
            }
        )

    def add_character_name_reference(
        self,
        character_id: int,
        source_name_id: int,
        expected_old_pointer: int,
    ) -> None:
        if not 1 <= character_id <= 0xFF or not 1 <= source_name_id <= 0xFF:
            raise ValueError("人物 ID 或名称来源 ID 必须在 01—FF 之间。")
        if not 0x8000 <= expected_old_pointer <= 0xBFFF:
            raise ValueError("原人物名称指针必须在 $8000—$BFFF 之间。")
        self.operations.append(
            {
                "kind": "character.set_name_reference",
                "characterId": character_id,
                "sourceNameId": source_name_id,
                "expectedOldPointer": expected_old_pointer,
            }
        )

    def add_map_replace(
        self,
        map_id: int,
        width: int,
        height: int,
        tiles: tuple[int, ...],
        expected_old_digest: str,
    ) -> None:
        if not 0 <= map_id <= 0xFF:
            raise ValueError("地图 ID 必须在 00—FF 之间。")
        if len(tiles) != width * height:
            raise ValueError("地图图块数量与宽高不一致。")
        self.operations.append(
            {
                "kind": "map.replace",
                "mapId": map_id,
                "width": width,
                "height": height,
                "tiles": list(tiles),
                "expectedOldDigest": expected_old_digest.upper(),
            }
        )

    def add_scenario_layout_replace(
        self,
        layout: ScenarioLayout,
        expected_old_digest: str,
    ) -> None:
        self.operations.append(
            {
                "kind": "scenario.replace_layout",
                "mapId": layout.map_id,
                "prelude": list(layout.prelude),
                "enemies": [list(entity.to_bytes()) for entity in layout.enemies],
                "guests": [list(entity.to_bytes()) for entity in layout.guests],
                "playerPlacements": [
                    list(placement.to_bytes()) for placement in layout.player_placements
                ],
                "expectedOldDigest": expected_old_digest.upper(),
            }
        )

    def add_story_text_replace(
        self,
        selector: int,
        index: int,
        data: bytes,
        expected_old_digest: str,
    ) -> None:
        if not data:
            raise ValueError("剧情文本记录不能为空。")
        self.operations.append(
            {
                "kind": "story.replace_text_record",
                "selector": selector,
                "index": index,
                "data": data.hex().upper(),
                "expectedOldDigest": expected_old_digest.upper(),
            }
        )

    def add_battle_music_binding(
        self,
        selector: int,
        attacker_command: int,
        defender_command: int,
        expected_old_attacker: int,
        expected_old_defender: int,
    ) -> None:
        if not 0 <= selector <= 0xFF:
            raise ValueError("战斗音乐选择器必须是一个字节。")
        self.operations.append(
            {
                "kind": "battle_music.set_binding",
                "selector": selector,
                "attackerCommand": attacker_command,
                "defenderCommand": defender_command,
                "expectedOldAttacker": expected_old_attacker,
                "expectedOldDefender": expected_old_defender,
            }
        )

    def add_map_trigger_replace(
        self,
        map_id: int,
        entries: tuple[MapTrigger, ...],
        expected_old_digest: str,
    ) -> None:
        if not 0 <= map_id < 0x20:
            raise ValueError("地图事件关卡 ID 必须在 00—1F 之间。")
        MapTriggerCodec.validate_entries(entries)
        self.operations.append(
            {
                "kind": "map_triggers.replace",
                "mapId": map_id,
                "entries": [list(entry.to_bytes()) for entry in entries],
                "expectedOldDigest": expected_old_digest.upper(),
            }
        )

    def _validate_base(self, rom: RomImage) -> None:
        if (
            rom.sha256 != self.base_sha256
            or rom.mapper != self.base_mapper
            or rom.size != self.base_size
        ):
            raise ProjectFormatError("项目文件与当前基准 ROM 的哈希、Mapper 或大小不匹配。")

    def resource_allocations(self, rom: RomImage) -> tuple[Allocation, ...]:
        self._validate_base(rom)
        allocator = BankAllocator(rom.profile, rom.data)
        for index, operation in enumerate(self.operations):
            if not isinstance(operation, dict) or operation.get("kind") != "resource.allocate":
                continue
            try:
                allocation, _data = self._decode_resource_allocation(operation)
                if allocation.resource_id.startswith(AUTO_ALLOCATION_PREFIX) and not (
                    allocation.resource_id.startswith(PARTITION_ALLOCATION_PREFIX)
                ):
                    raise ValueError("auto. 前缀仅供修改器内部分区使用。")
                if (
                    any(rom.data[allocation.offset : allocation.end])
                    and not allocation.resource_id.startswith(
                        PARTITION_ALLOCATION_PREFIX
                    )
                ):
                    raise ValueError("资源分配的基准区域不是全零。")
                allocator.reserve(allocation)
            except (KeyError, TypeError, ValueError) as error:
                raise ProjectFormatError(
                    f"第 {index + 1} 条资源分配操作无效：{error}"
                ) from error
        return allocator.allocations

    def materialize(self, rom: RomImage) -> bytes:
        self._validate_base(rom)
        initial_plan = ExpansionPlan.from_bytes(rom.data)
        if initial_plan is not None and initial_plan.flags & FLAG_UNITS:
            core_bank = initial_plan.unit_banks[0]
            name_bank = (
                initial_plan.unit_banks[8]
                if len(initial_plan.unit_banks) == 10
                else core_bank
            )
            name_table = (
                SINGLE_RESOURCE_TABLE
                if len(initial_plan.unit_banks) == 10
                else NAME_TABLE
            )
            unit_codec = UnitCodec(
                rom,
                rom.data,
                pointer_table_offset=(
                    bank_file_offset(core_bank) + ATTRIBUTE_TABLE - 0x8000
                ),
                pair_first_bank=core_bank,
            )
            unit_name_codec = UnitNameReferenceCodec(
                rom,
                rom.data,
                pointer_table_offset=(
                    bank_file_offset(name_bank) + name_table - 0x8000
                ),
                pair_first_bank=name_bank,
            )
        else:
            unit_codec = UnitCodec(rom)
            unit_name_codec = UnitNameReferenceCodec(rom)
        unit_weapon_codec = (
            UnitWeaponCodec(
                rom,
                rom.data,
                table_offset=(
                    bank_file_offset(initial_plan.unit_banks[2])
                    + rom.profile.unit_weapon_table_offset
                    - bank_file_offset(SOURCE_CONFIGURATION_PAIR)
                    if initial_plan is not None and initial_plan.flags & FLAG_UNITS
                    else rom.profile.unit_weapon_table_offset
                ),
            )
            if rom.profile.unit_weapon_table_offset is not None
            else None
        )
        weapon_codec = WeaponCodec(rom)
        weapon_name_codec = (
            WeaponNameReferenceCodec(rom)
            if rom.profile.weapon_name_pointer_table_offset is not None
            else None
        )

        character_name_codec = (
            CharacterNameCodec(rom)
            if rom.profile.character_name_pointer_table_offset is not None
            else None
        )
        if initial_plan is not None and initial_plan.flags & FLAG_MAPS:
            initial_layout = read_expanded_map_layout(rom.data)
            map_codec = MapCodec(
                rom,
                rom.data,
                bank_table_offset=TERRAIN_BANK_DIRECTORY_OFFSET,
                record_locations=initial_layout.terrain,
            )
            scenario_codec = ScenarioLayoutCodec(
                rom, rom.data, record_locations=initial_layout.scenarios
            )
            map_trigger_codec = MapTriggerCodec(
                rom,
                rom.data,
                record_locations=initial_layout.triggers,
                expanded_capacity=len(initial_plan.map_banks) * 0x2000,
            )
        else:
            map_codec = MapCodec(rom)
            scenario_codec = ScenarioLayoutCodec(rom)
            map_trigger_codec = (
                MapTriggerCodec(rom) if rom.profile.map_triggers is not None else None
            )
        story_overrides = (
            {
                selector: pair[0]
                for selector in initial_plan.expanded_story_selectors
                if (pair := initial_plan.story_pair_for(selector)) is not None
            }
            if initial_plan is not None
            else {}
        )
        story_text_codec = StoryTextCodec(
            rom, rom.data, group_bank_overrides=story_overrides
        )
        battle_music_codec = (
            BattleMusicCodec(rom) if rom.profile.battle_music is not None else None
        )
        resource_allocator = BankAllocator(rom.profile, rom.data)
        changes = ChangeSet(rom.data)
        for index, operation in enumerate(self.operations):
            if not isinstance(operation, dict):
                raise ProjectFormatError(f"第 {index + 1} 条项目操作不是对象。")
            kind = operation.get("kind")
            try:
                if kind == "unit.set_field":
                    unit_id = int(operation["unitId"])
                    field_key = str(operation["field"])
                    if field_key not in UNIT_FIELD_BY_KEY:
                        raise ProjectFormatError(f"未知机体字段：{field_key}")
                    if UNIT_FIELD_BY_KEY[field_key].evidence != "confirmed":
                        raise ProjectFormatError(
                            f"机体字段 {field_key} 尚未确认，不能写入稳定项目。"
                        )
                    value = int(operation["value"])
                    expected_value = int(operation["expectedOldValue"])
                    current_data = changes.materialize()
                    record = unit_codec.decode_record(unit_id, current_data)
                    current_value = record.get(field_key)
                    if current_value != expected_value:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作原值不匹配：需要 {expected_value}，"
                            f"实际 {current_value}。"
                        )
                    offset, before, after = unit_codec.field_patch(
                        current_data, unit_id, field_key, value
                    )
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"unit:{unit_codec.pointers[unit_id]:04X}",
                        description=f"机体 {unit_id:02X} · {UNIT_FIELD_BY_KEY[field_key].label}",
                        expected=before,
                    )
                elif kind == "weapon.set_field":
                    weapon_id = int(operation["weaponId"])
                    field_key = str(operation["field"])
                    if field_key not in WEAPON_FIELD_BY_KEY:
                        raise ProjectFormatError(f"未知武器字段：{field_key}")
                    if WEAPON_FIELD_BY_KEY[field_key].evidence != "confirmed":
                        raise ProjectFormatError(
                            f"武器字段 {field_key} 尚未确认，不能写入稳定项目。"
                        )
                    value = int(operation["value"])
                    expected_value = int(operation["expectedOldValue"])
                    current_data = changes.materialize()
                    record = weapon_codec.decode_record(weapon_id, current_data)
                    current_value = record.get(field_key)
                    if current_value != expected_value:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作原值不匹配：需要 {expected_value}，"
                            f"实际 {current_value}。"
                        )
                    offset, before, after = weapon_codec.field_patch(
                        current_data, weapon_id, field_key, value
                    )
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"weapon:{weapon_id:02X}",
                        description=(
                            f"武器 {weapon_id:02X} · {WEAPON_FIELD_BY_KEY[field_key].label}"
                        ),
                        expected=before,
                    )
                elif kind == "unit.set_weapon_slot":
                    if unit_weapon_codec is None:
                        raise ProjectFormatError(
                            "当前基准 ROM 没有已验证的机体武器关系表。"
                        )
                    unit_id = int(operation["unitId"])
                    slot = int(operation["slot"])
                    weapon_id = int(operation["weaponId"])
                    expected_weapon_id = int(operation["expectedOldWeaponId"])
                    current_data = changes.materialize()
                    current = unit_weapon_codec.decode(unit_id, current_data)
                    if current.weapon_ids[slot] != expected_weapon_id:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作原武器不匹配：需要 "
                            f"{expected_weapon_id:02X}，实际 {current.weapon_ids[slot]:02X}。"
                        )
                    offset, before, after = unit_weapon_codec.slot_patch(
                        current_data, unit_id, slot, weapon_id
                    )
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"unit-weapons:{unit_id:02X}",
                        description=f"机体 {unit_id:02X} · 武器槽 {slot + 1}",
                        expected=before,
                    )
                elif kind == "weapon.set_name_reference":
                    if weapon_name_codec is None:
                        raise ProjectFormatError(
                            "当前基准 ROM 没有已验证的武器名称表。"
                        )
                    weapon_id = int(operation["weaponId"])
                    source_name_id = int(operation["sourceNameId"])
                    expected_pointer = int(operation["expectedOldPointer"])
                    current_data = changes.materialize()
                    current_pointer = weapon_name_codec.pointer(weapon_id, current_data)
                    if current_pointer != expected_pointer:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作原武器名称指针不匹配：需要 "
                            f"${expected_pointer:04X}，实际 ${current_pointer:04X}。"
                        )
                    offset, before, after = weapon_name_codec.reference_patch(
                        current_data, weapon_id, source_name_id
                    )
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"weapon-name:{weapon_id:02X}",
                        description=(
                            f"武器 {weapon_id:02X} · 名称引用 {source_name_id:02X}"
                        ),
                        expected=before,
                    )
                elif kind == "unit.set_name_reference":
                    unit_id = int(operation["unitId"])
                    source_name_id = int(operation["sourceNameId"])
                    expected_pointer = int(operation["expectedOldPointer"])
                    current_data = changes.materialize()
                    current_pointer = unit_name_codec.pointer(unit_id, current_data)
                    if current_pointer != expected_pointer:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作原名称指针不匹配：需要 "
                            f"${expected_pointer:04X}，实际 ${current_pointer:04X}。"
                        )
                    offset, before, after = unit_name_codec.reference_patch(
                        current_data, unit_id, source_name_id
                    )
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"unit-name:{unit_id:02X}",
                        description=(
                            f"机体 {unit_id:02X} · 名称引用 {source_name_id:02X}"
                        ),
                        expected=before,
                    )
                elif kind == "character.set_name_reference":
                    if character_name_codec is None:
                        raise ProjectFormatError(
                            "当前基准 ROM 没有已验证的人物名称表。"
                        )
                    character_id = int(operation["characterId"])
                    source_name_id = int(operation["sourceNameId"])
                    expected_pointer = int(operation["expectedOldPointer"])
                    current_data = changes.materialize()
                    current_pointer = character_name_codec.pointer(
                        character_id, current_data
                    )
                    if current_pointer != expected_pointer:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作原人物名称指针不匹配：需要 "
                            f"${expected_pointer:04X}，实际 ${current_pointer:04X}。"
                        )
                    offset, before, after = character_name_codec.reference_patch(
                        current_data, character_id, source_name_id
                    )
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"character-name:{character_id:02X}",
                        description=(
                            f"人物 {character_id:02X} · 名称引用 {source_name_id:02X}"
                        ),
                        expected=before,
                    )
                elif kind == "map.replace":
                    map_id = int(operation["mapId"])
                    width = int(operation["width"])
                    height = int(operation["height"])
                    tiles_value = operation["tiles"]
                    if not isinstance(tiles_value, list):
                        raise ProjectFormatError("地图 tiles 必须是数组。")
                    tiles = tuple(int(tile) for tile in tiles_value)
                    expected_digest = str(operation["expectedOldDigest"]).upper()
                    current_data = changes.materialize()
                    current = map_codec.decode(map_id, current_data)
                    actual_digest = map_codec.semantic_digest(current)
                    if actual_digest != expected_digest:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作的地图原值摘要不匹配。"
                        )
                    offset, before, after = map_codec.replacement_patch(
                        current_data,
                        map_id,
                        width,
                        height,
                        tiles,
                    )
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"map:{map_id:02X}",
                        description=f"地图 {map_id:02X} · {width}×{height} 地形",
                        expected=before,
                    )
                elif kind == "scenario.replace_layout":
                    map_id = int(operation["mapId"])
                    current_data = changes.materialize()
                    current = scenario_codec.decode(map_id, current_data)
                    expected_digest = str(operation["expectedOldDigest"]).upper()
                    if scenario_codec.semantic_digest(current) != expected_digest:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作的场景部署摘要不匹配。"
                        )

                    def parse_rows(name: str, width: int) -> list[list[int]]:
                        value = operation[name]
                        if not isinstance(value, list):
                            raise ProjectFormatError(f"场景 {name} 必须是数组。")
                        rows: list[list[int]] = []
                        for row in value:
                            if not isinstance(row, list) or len(row) != width:
                                raise ProjectFormatError(
                                    f"场景 {name} 的每项必须包含 {width} 个字节。"
                                )
                            values = [int(item) for item in row]
                            if any(not 0 <= item <= 255 for item in values):
                                raise ProjectFormatError(f"场景 {name} 含越界字节。")
                            rows.append(values)
                        return rows

                    prelude_value = operation["prelude"]
                    if not isinstance(prelude_value, list):
                        raise ProjectFormatError("场景 prelude 必须是数组。")
                    prelude = tuple(int(item) for item in prelude_value)
                    enemies = tuple(ScenarioEntity(*row) for row in parse_rows("enemies", 6))
                    guests = tuple(ScenarioEntity(*row) for row in parse_rows("guests", 6))
                    placements = tuple(
                        PlayerPlacement(*row) for row in parse_rows("playerPlacements", 4)
                    )
                    changed_layout = ScenarioLayout(
                        map_id,
                        current.pointer,
                        prelude,
                        enemies,
                        guests,
                        placements,
                        current.raw,
                        current.capacity,
                    )
                    map_record = map_codec.decode(map_id, current_data)
                    scenario_codec.validate_layout(
                        changed_layout, map_record.width, map_record.height
                    )
                    offset, before, after = scenario_codec.replacement_patch(
                        current_data, changed_layout
                    )
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"scenario:{map_id:02X}",
                        description=f"场景 {map_id:02X} · 部署数据",
                        expected=before,
                    )
                elif kind == "map_triggers.replace":
                    if map_trigger_codec is None:
                        raise ProjectFormatError(
                            "当前基准 ROM 没有已验证的地图事件表。"
                        )
                    map_id = int(operation["mapId"])
                    rows_value = operation["entries"]
                    if not isinstance(rows_value, list):
                        raise ProjectFormatError("地图事件 entries 必须是数组。")
                    rows: list[MapTrigger] = []
                    for row in rows_value:
                        if not isinstance(row, list) or len(row) != 4:
                            raise ProjectFormatError(
                                "每条地图事件必须包含 X、Y、限定人物、事件编号四个字节。"
                            )
                        values = [int(item) for item in row]
                        if any(not 0 <= item <= 0xFF for item in values):
                            raise ProjectFormatError("地图事件含越界字节。")
                        rows.append(MapTrigger(*values))
                    entries = tuple(rows)
                    current_data = changes.materialize()
                    current = map_trigger_codec.decode(map_id, current_data)
                    expected_digest = str(operation["expectedOldDigest"]).upper()
                    if map_trigger_codec.semantic_digest(current) != expected_digest:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作的地图事件摘要不匹配。"
                        )
                    map_record = map_codec.decode(map_id, current_data)
                    map_trigger_codec.validate_entries(
                        entries, map_record.width, map_record.height
                    )
                    for offset, before, after in map_trigger_codec.repack_patches(
                        current_data, map_id, entries
                    ):
                        changes.apply_patch(
                            offset,
                            after,
                            source=f"map-triggers:{map_id:02X}",
                            description=f"地图 {map_id:02X} · 事件与商店",
                            expected=before,
                        )
                elif kind == "story.replace_text_record":
                    selector = int(operation["selector"])
                    text_index = int(operation["index"])
                    replacement = bytes.fromhex(str(operation["data"]))
                    expected_digest = str(operation["expectedOldDigest"]).upper()
                    current_data = changes.materialize()
                    current = story_text_codec.decode(selector, text_index, current_data)
                    if story_text_codec.semantic_digest(current) != expected_digest:
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作的剧情文本原值摘要不匹配。"
                        )
                    offset, before, after = story_text_codec.replacement_patch(
                        current_data, selector, text_index, replacement
                    )
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"story:{selector:02X}:{text_index:02X}",
                        description=(
                            f"剧情文本 ${selector:02X}:{text_index:02X} · 等长 Token 数据"
                        ),
                        expected=before,
                    )
                elif kind == "battle_music.set_binding":
                    if battle_music_codec is None:
                        raise ProjectFormatError(
                            "当前基准 ROM 没有已验证的战斗音乐表。"
                        )
                    selector = int(operation["selector"])
                    attacker_command = int(operation["attackerCommand"])
                    defender_command = int(operation["defenderCommand"])
                    expected_attacker = int(operation["expectedOldAttacker"])
                    expected_defender = int(operation["expectedOldDefender"])
                    current_data = changes.materialize()
                    current = battle_music_codec.decode(selector, current_data)
                    if (
                        current.attacker_command != expected_attacker
                        or current.defender_command != expected_defender
                    ):
                        raise ProjectFormatError(
                            f"第 {index + 1} 条操作的战斗音乐原值不匹配。"
                        )
                    for offset, before, after in battle_music_codec.replacement_patches(
                        current_data,
                        selector,
                        attacker_command,
                        defender_command,
                    ):
                        changes.apply_patch(
                            offset,
                            after,
                            source=f"battle-music:{selector:02X}",
                            description=(
                                f"战斗音乐选择器 {selector:02X} · 人物战斗曲"
                            ),
                            expected=before,
                        )
                elif kind == "resource.allocate":
                    allocation, payload = self._decode_resource_allocation(operation)
                    if allocation.resource_id.startswith(AUTO_ALLOCATION_PREFIX) and not (
                        allocation.resource_id.startswith(PARTITION_ALLOCATION_PREFIX)
                    ):
                        raise ProjectFormatError(
                            "auto. 前缀仅供修改器内部分区使用。"
                        )
                    if (
                        any(rom.data[allocation.offset : allocation.end])
                        and not allocation.resource_id.startswith(
                            PARTITION_ALLOCATION_PREFIX
                        )
                    ):
                        raise ProjectFormatError("资源分配的基准区域不是全零。")
                    resource_allocator.reserve(allocation)
                    changes.apply_patch(
                        allocation.offset,
                        payload,
                        source=f"resource:{allocation.resource_id}",
                        description=f"扩展资源 · {allocation.label}",
                        expected=rom.data[allocation.offset : allocation.end],
                    )
                elif kind == "raw.patch":
                    offset = int(operation["offset"])
                    before = bytes.fromhex(str(operation["before"]))
                    after = bytes.fromhex(str(operation["after"]))
                    changes.apply_patch(
                        offset,
                        after,
                        source=f"raw:{index}",
                        description=str(operation.get("description", "高级原始补丁")),
                        expected=before,
                    )
                else:
                    raise ProjectFormatError(f"不支持的项目操作：{kind!r}")
            except ProjectFormatError:
                raise
            except (KeyError, TypeError, ValueError) as error:
                raise ProjectFormatError(f"第 {index + 1} 条项目操作无效：{error}") from error
        return changes.materialize()

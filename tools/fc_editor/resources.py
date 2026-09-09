from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from .constants import INES_HEADER_SIZE, PRG_BANK_SIZE
from .profiles import RomProfile


ResourceKind = Literal["table", "data", "code", "audio", "graphics", "free", "metadata"]


@dataclass(frozen=True)
class ResourceNode:
    """One named ROM resource and its physical byte range."""

    resource_id: str
    label: str
    kind: ResourceKind
    offset: int
    size: int
    writable: bool = False

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("资源 ID 不能为空。")
        if self.offset < 0 or self.size <= 0:
            raise ValueError("资源范围无效。")

    @property
    def end(self) -> int:
        return self.offset + self.size

    def contains(self, offset: int, size: int = 1) -> bool:
        return size >= 0 and self.offset <= offset and offset + size <= self.end


@dataclass(frozen=True)
class ResourceReference:
    source_id: str
    target_id: str
    label: str
    pointer_offset: int | None = None


class ResourceGraph:
    """Named resources plus cross-resource references used by editor modules."""

    def __init__(self) -> None:
        self._nodes: dict[str, ResourceNode] = {}
        self._references: list[ResourceReference] = []

    @property
    def nodes(self) -> tuple[ResourceNode, ...]:
        return tuple(self._nodes.values())

    @property
    def references(self) -> tuple[ResourceReference, ...]:
        return tuple(self._references)

    def add_node(self, node: ResourceNode) -> None:
        if node.resource_id in self._nodes:
            raise ValueError(f"资源 ID 重复：{node.resource_id}")
        self._nodes[node.resource_id] = node

    def add_reference(self, reference: ResourceReference) -> None:
        if reference.source_id not in self._nodes:
            raise KeyError(f"引用来源不存在：{reference.source_id}")
        if reference.target_id not in self._nodes:
            raise KeyError(f"引用目标不存在：{reference.target_id}")
        self._references.append(reference)

    def node(self, resource_id: str) -> ResourceNode:
        return self._nodes[resource_id]

    def references_to(self, resource_id: str) -> tuple[ResourceReference, ...]:
        return tuple(item for item in self._references if item.target_id == resource_id)

    @classmethod
    def from_profile(cls, profile: RomProfile, rom_data: bytes) -> "ResourceGraph":
        graph = cls()
        graph.add_node(ResourceNode("ines.header", "iNES 文件头", "metadata", 0, 16))
        graph.add_node(
            ResourceNode(
                "units.pointer_table",
                "机体指针表",
                "table",
                profile.unit_pointer_table_offset,
                profile.unit_count * 2,
                True,
            )
        )
        graph.add_node(
            ResourceNode(
                "weapons.pointer_table",
                "武器指针表",
                "table",
                profile.weapon_pointer_table_offset,
                profile.weapon_pointer_count * 2,
                True,
            )
        )
        if profile.unit_weapon_table_offset is not None:
            graph.add_node(
                ResourceNode(
                    "units.weapon_table",
                    "机体武器关系表",
                    "table",
                    profile.unit_weapon_table_offset,
                    profile.unit_count * 2,
                    True,
                )
            )
        if profile.weapon_name_pointer_table_offset is not None:
            graph.add_node(
                ResourceNode(
                    "weapons.name_pointer_table",
                    "武器名称指针表",
                    "table",
                    profile.weapon_name_pointer_table_offset,
                    profile.weapon_name_pointer_count * 2,
                    True,
                )
            )
        if profile.character_name_pointer_table_offset is not None:
            graph.add_node(
                ResourceNode(
                    "characters.battle_name_pointer_table",
                    "人物战斗名称指针表",
                    "table",
                    profile.character_name_pointer_table_offset,
                    profile.character_name_count * 2,
                )
            )
        graph.add_node(
            ResourceNode(
                "maps.pointer_table",
                "地图指针表",
                "table",
                profile.map_pointer_table_offset,
                profile.map_count * 2,
                True,
            )
        )
        graph.add_node(
            ResourceNode(
                "scenarios.pointer_table",
                "部署指针表",
                "table",
                profile.scenario_pointer_table_offset,
                profile.scenario_count * 2,
                True,
            )
        )
        if profile.map_triggers is not None:
            spec = profile.map_triggers
            bank_offset = INES_HEADER_SIZE + spec.prg_bank * PRG_BANK_SIZE
            graph.add_node(
                ResourceNode(
                    "map_triggers.pointer_table",
                    "地图事件/商店指针表",
                    "table",
                    bank_offset + spec.pointer_table - spec.window_base,
                    spec.scenario_count * 2,
                    True,
                )
            )
            graph.add_node(
                ResourceNode(
                    "map_triggers.managed_pool",
                    "地图事件/商店托管池",
                    "data",
                    bank_offset + spec.managed_data_start - spec.window_base,
                    spec.managed_data_end - spec.managed_data_start,
                    True,
                )
            )
        if profile.chapter_events is not None:
            spec = profile.chapter_events
            graph.add_node(
                ResourceNode(
                    "events.chapter_data",
                    "章节事件脚本",
                    "data",
                    INES_HEADER_SIZE
                    + spec.data_prg_bank * PRG_BANK_SIZE
                    + spec.data_start
                    - spec.data_window_base,
                    spec.data_end - spec.data_start,
                    True,
                )
            )
        if profile.persuasion_rules is not None:
            spec = profile.persuasion_rules
            graph.add_node(
                ResourceNode(
                    "events.persuasion_rules",
                    "劝降匹配规则表",
                    "table",
                    spec.table_offset,
                    spec.slot_count * 3 + 1,
                    True,
                )
            )
            graph.add_node(
                ResourceNode(
                    "events.persuasion_pointers",
                    "劝降事件脚本指针表",
                    "table",
                    spec.script_pointer_table_offset,
                    spec.slot_count * 2,
                )
            )
        for index, region in enumerate(profile.protected_prg_regions):
            graph.add_node(
                ResourceNode(
                    f"prg.protected.{index}",
                    region.label,
                    "code" if region.first_bank >= 0x7E else "audio",
                    INES_HEADER_SIZE + region.first_bank * PRG_BANK_SIZE,
                    region.size,
                )
            )
        for slot in profile.custom_music_slots:
            graph.add_node(
                ResourceNode(
                    f"audio.custom.{slot.command:02X}",
                    f"扩展曲槽 ${slot.command:02X} · {slot.label}",
                    "audio",
                    INES_HEADER_SIZE + slot.prg_bank * PRG_BANK_SIZE,
                    PRG_BANK_SIZE,
                    True,
                )
            )
        for index, region in enumerate(profile.free_prg_regions):
            graph.add_node(
                ResourceNode(
                    f"prg.free.{index}",
                    region.label,
                    "free",
                    INES_HEADER_SIZE + region.first_bank * PRG_BANK_SIZE,
                    region.size,
                    True,
                )
            )
        prg_size = rom_data[4] * 0x4000
        chr_size = rom_data[5] * 0x2000
        if chr_size:
            graph.add_node(
                ResourceNode(
                    "chr.active",
                    "活动 CHR 图像区",
                    "graphics",
                    INES_HEADER_SIZE + prg_size,
                    chr_size,
                    True,
                )
            )
        return graph


@dataclass(frozen=True)
class Allocation:
    resource_id: str
    label: str
    offset: int
    size: int
    alignment: int

    @property
    def end(self) -> int:
        return self.offset + self.size

    @property
    def first_bank(self) -> int:
        return (self.offset - INES_HEADER_SIZE) // PRG_BANK_SIZE


class BankAllocator:
    """Deterministic first-fit allocator for profile-declared free PRG banks."""

    def __init__(
        self,
        profile: RomProfile,
        rom_data: bytes,
        allocations: Iterable[Allocation] = (),
    ) -> None:
        self.profile = profile
        self.rom_data = bytes(rom_data)
        self._allocations: list[Allocation] = []
        for allocation in allocations:
            self.reserve(allocation)

    @property
    def allocations(self) -> tuple[Allocation, ...]:
        return tuple(sorted(self._allocations, key=lambda item: item.offset))

    @property
    def capacity(self) -> int:
        return sum(region.size for region in self.profile.free_prg_regions)

    @property
    def used(self) -> int:
        return sum(item.size for item in self._allocations)

    @property
    def available(self) -> int:
        return self.capacity - self.used

    @staticmethod
    def _align(value: int, alignment: int) -> int:
        return (value + alignment - 1) // alignment * alignment

    def _is_in_free_region(self, offset: int, size: int) -> bool:
        for region in self.profile.free_prg_regions:
            start = INES_HEADER_SIZE + region.first_bank * PRG_BANK_SIZE
            end = INES_HEADER_SIZE + region.end_bank * PRG_BANK_SIZE
            if start <= offset and offset + size <= end:
                return True
        return False

    def _overlap(self, offset: int, size: int) -> Allocation | None:
        end = offset + size
        return next(
            (
                item
                for item in self._allocations
                if offset < item.end and item.offset < end
            ),
            None,
        )

    def reserve(self, allocation: Allocation) -> None:
        if any(item.resource_id == allocation.resource_id for item in self._allocations):
            raise ValueError(f"资源已分配：{allocation.resource_id}")
        if allocation.size <= 0 or allocation.alignment <= 0:
            raise ValueError("分配大小和对齐值必须大于零。")
        if allocation.offset % allocation.alignment:
            raise ValueError("分配起始位置没有满足对齐要求。")
        if not self._is_in_free_region(allocation.offset, allocation.size):
            raise ValueError("分配范围不在可用 PRG 区域内。")
        conflict = self._overlap(allocation.offset, allocation.size)
        if conflict is not None:
            raise ValueError(f"分配与资源 {conflict.resource_id} 重叠。")
        self._allocations.append(allocation)

    def allocate(
        self,
        resource_id: str,
        label: str,
        size: int,
        *,
        alignment: int = 1,
        single_bank: bool = True,
        require_zero_fill: bool = True,
    ) -> Allocation:
        if size <= 0:
            raise ValueError("申请大小必须大于零。")
        if alignment <= 0 or alignment & (alignment - 1):
            raise ValueError("对齐值必须是 2 的幂。")
        if any(item.resource_id == resource_id for item in self._allocations):
            raise ValueError(f"资源已分配：{resource_id}")
        for region in self.profile.free_prg_regions:
            start = INES_HEADER_SIZE + region.first_bank * PRG_BANK_SIZE
            region_end = INES_HEADER_SIZE + region.end_bank * PRG_BANK_SIZE
            cursor = self._align(start, alignment)
            while cursor + size <= region_end:
                if single_bank:
                    bank_end = (
                        INES_HEADER_SIZE
                        + ((cursor - INES_HEADER_SIZE) // PRG_BANK_SIZE + 1) * PRG_BANK_SIZE
                    )
                    if cursor + size > bank_end:
                        cursor = self._align(bank_end, alignment)
                        continue
                conflict = self._overlap(cursor, size)
                if conflict is not None:
                    cursor = self._align(conflict.end, alignment)
                    continue
                if require_zero_fill and any(self.rom_data[cursor : cursor + size]):
                    cursor = self._align(cursor + alignment, alignment)
                    continue
                allocation = Allocation(resource_id, label, cursor, size, alignment)
                self._allocations.append(allocation)
                return allocation
        mode = "单 Bank" if single_bank else "连续"
        raise ValueError(f"没有足够的{mode}空闲 PRG 空间容纳 {size} 字节。")

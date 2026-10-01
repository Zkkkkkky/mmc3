from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any
from weakref import WeakKeyDictionary

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fc_editor.codecs.character_attributes import CharacterAttributesCodec
from fc_editor.codecs.legacy_text import LegacyTextCodec, TEXT_GROUPS
from fc_editor.codecs.legacy_text_growth import LegacyGrowthCodec
from fc_editor.codecs.legacy_text_shop import LegacyShopCodec
from fc_editor.constants import UNIT_RECORD_SIZE, WEAPON_RECORD_SIZE
from fc_editor.expansion_unit import (
    CONFIGURATION_CAVE_END,
    CONFIGURATION_CAVE_START,
    LEGACY_UNIT_NAME_GROWTH_BUDGET,
    STANDALONE_UNIT_NAME_DATA_START,
    source_configuration_table,
    standalone_unit_attribute_bank,
    standalone_unit_name_bank,
)


@dataclass(frozen=True)
class DatabaseMemoryRegion:
    module: str
    resource: str
    address: str
    kind: str
    shared_with: str
    used: int
    capacity: int
    pool_key: str | None
    note: str
    growth_enabled: bool = True

    @property
    def remaining(self) -> int:
        return max(0, self.capacity - self.used)

    @property
    def is_repackable(self) -> bool:
        return self.pool_key is not None and self.growth_enabled

    @property
    def is_observed_pool(self) -> bool:
        """A measured pool whose free bytes are not yet writable by this UI."""

        return self.pool_key is not None and not self.growth_enabled


@dataclass(frozen=True)
class DatabaseMemoryReport:
    regions: tuple[DatabaseMemoryRegion, ...]

    @property
    def repackable_regions(self) -> tuple[DatabaseMemoryRegion, ...]:
        seen: set[str] = set()
        result: list[DatabaseMemoryRegion] = []
        for region in self.regions:
            if not region.is_repackable or region.pool_key in seen:
                continue
            assert region.pool_key is not None
            seen.add(region.pool_key)
            result.append(region)
        return tuple(result)

    @property
    def pool_used(self) -> int:
        return sum(region.used for region in self.repackable_regions)

    @property
    def pool_capacity(self) -> int:
        return sum(region.capacity for region in self.repackable_regions)

    @property
    def pool_remaining(self) -> int:
        return self.pool_capacity - self.pool_used

    @property
    def fixed_bytes(self) -> int:
        return sum(region.capacity for region in self.regions if region.pool_key is None)

    def for_module(self, module: str) -> "DatabaseMemoryReport":
        return DatabaseMemoryReport(
            tuple(region for region in self.regions if region.module == module)
        )


def _file_range(start: int, end: int) -> str:
    if end <= start:
        return f"0x{start:06X}"
    first_bank = (start - 16) // 0x2000 if start >= 16 else 0
    last_bank = (end - 1 - 16) // 0x2000 if end > 16 else 0
    bank_text = f"Bank ${first_bank:02X}" if first_bank == last_bank else f"Bank ${first_bank:02X}—${last_bank:02X}"
    return f"0x{start:06X}—0x{end - 1:06X}（{bank_text}）"


def _cpu_pool(project: Any, bank: int, start: int, end: int) -> str:
    file_start = 16 + bank * 0x2000 + start - 0x8000
    file_end = file_start + end - start
    return f"${bank:02X}:${start:04X}—${end - 1:04X} / {_file_range(file_start, file_end)}"


def _fixed(
    module: str,
    resource: str,
    start: int,
    size: int,
    *,
    shared: str = "独立（不与其他数据区共用）",
    note: str = "固定结构，只能在原位等长修改",
) -> DatabaseMemoryRegion:
    return DatabaseMemoryRegion(
        module, resource, _file_range(start, start + size), "固定结构（可改值）", shared,
        size, size, None, note,
    )


def _pool(
    module: str,
    resource: str,
    address: str,
    used: int,
    capacity: int,
    key: str,
    shared: str,
    note: str = "池内记录可自动重排；总量不得越过已验证池尾",
) -> DatabaseMemoryRegion:
    return DatabaseMemoryRegion(
        module, resource, address, "可重排池", shared, used, capacity, key, note
    )


def _portrait_configuration_tail(source: bytes | bytearray) -> tuple[int, int, int]:
    """Measure the verified Bank $04 portrait/configuration composite tail."""

    pair_base = 16 + 0x04 * 0x2000
    portrait_root = struct.unpack_from("<H", source, pair_base + 4)[0]
    configuration_root = struct.unpack_from("<H", source, pair_base + 12)[0]
    if not 0x8000 <= portrait_root < configuration_root < 0xB5E6:
        raise ValueError("Bank $04 的头像/战斗外观目录无效。")
    table = pair_base + configuration_root - 0x8000
    pointers = struct.unpack_from("<256H", source, table)
    valid_pointer = lambda item: (
        configuration_root < item < CONFIGURATION_CAVE_START
        or CONFIGURATION_CAVE_START <= item <= CONFIGURATION_CAVE_END - 10
    )
    if pointers[0] or any(not valid_pointer(item) for item in pointers[1:]):
        raise ValueError("机体战斗外观指针超出已验证尾区。")
    legacy_pointers = tuple(
        pointer for pointer in pointers[1:] if pointer < CONFIGURATION_CAVE_START
    )
    used_end = max(
        pointer + (10 if source[pair_base + pointer - 0x8000] & 0x80 else 9)
        for pointer in legacy_pointers
    )
    if used_end > CONFIGURATION_CAVE_START:
        raise ValueError("头像/战斗外观数据越过固定尾界。")
    return portrait_root, used_end, CONFIGURATION_CAVE_START


def _bank24_composite_usage(
    source: bytes | bytearray,
) -> tuple[int, int, int, tuple[int, ...]]:
    """Measure the original eight-resource Bank $24 composite block.

    The final resource is the 32-stage initial-configuration table, so the
    greatest decoded scenario end is also the physical used end of the whole
    ordered block.
    """

    pair_base = 16 + 0x24 * 0x2000
    root_start = 0x83F0
    fixed_code_start = 0xBF40
    roots = tuple(struct.unpack_from("<8H", source, pair_base + 2))
    if roots[0] != root_start or roots != tuple(sorted(roots)):
        raise ValueError("Bank $24 的八资源目录无效。")
    if roots[-1] >= fixed_code_start:
        raise ValueError("Bank $24 的资源目录越过固定代码。")

    scenario_table = pair_base + roots[-1] - 0x8000
    pointers = tuple(struct.unpack_from("<32H", source, scenario_table))
    if any(not roots[-1] <= pointer < fixed_code_start for pointer in pointers):
        raise ValueError("Bank $24 的初始配置指针越过复合块边界。")

    def scenario_end(pointer: int) -> int:
        cursor = pair_base + pointer - 0x8000
        limit = pair_base + fixed_code_start - 0x8000
        for step in (1, 6, 6, 4):
            while cursor < limit and source[cursor] != 0xFF:
                cursor += step
            if cursor >= limit:
                raise ValueError(f"初始配置 ${pointer:04X} 缺少结束码。")
            cursor += 1
        return 0x8000 + cursor - pair_base

    used_end = max(scenario_end(pointer) for pointer in set(pointers))
    return root_start, used_end, fixed_code_start, roots


def build_database_memory_report(project: Any) -> DatabaseMemoryReport:
    """Measure every storage area surfaced by the six-page database dialog.

    Only regions whose linker/repacker has a proven hard boundary receive a
    ``pool_key`` and contribute to the available-byte total.  Fixed tables are
    deliberately reported as fully occupied even if their payload contains
    zeroes or duplicate pointers: those bytes are not evidence of free space.
    """

    profile = project.profile
    source = project.working
    rows: list[DatabaseMemoryRegion] = []

    # 机体修改
    rows.append(_fixed("机体修改", "机体属性指针表", project.unit_codec.pointer_table_offset, profile.unit_count * 2))
    unit_unique = sorted({pointer for pointer in project.unit_codec.pointers[1:] if pointer})
    unit_offsets = [project.unit_codec.record_offset_from_pointer(pointer) for pointer in unit_unique]
    if unit_offsets:
        independent_attributes = (
            standalone_unit_attribute_bank(source) is not None
            or len(unit_unique) == profile.unit_count - 1
        )
        rows.append(_fixed("机体修改", "机体属性记录", min(unit_offsets), len(unit_offsets) * UNIT_RECORD_SIZE,
                           shared=(
                               "每个机体ID拥有独立的16字节属性记录"
                               if independent_attributes
                               else "当前ROM含重复属性指针；直接编辑时自动拆分目标ID"
                           ),
                           note=(
                               f"{len(unit_unique)} 条物理记录；每条固定 {UNIT_RECORD_SIZE} 字节；"
                               "重复指针只是当前ROM的压缩布局，不作为联动修改限制"
                           )))
    name_codec = project.unit_name_codec
    standalone_names = name_codec.canonical_pointer_table_offset is not None
    rows.append(_fixed(
        "机体修改",
        "机体名称指针表",
        name_codec.pointer_table_offset,
        profile.unit_name_count * 2,
        shared=(
            "每个机体ID可独立改名；名称引用仍可主动共用"
            if standalone_names
            else "当前ROM含重复名称指针；直接改名按机体ID自动拆分"
        ),
        note=(
            "重复指针是当前ROM的数据布局，不代表旧修改器采用共用名称规则；"
            "直接改名不会连带改写其他机体ID"
        ),
    ))
    if name_codec.pool_spans:
        lazy_legacy_capacity = (
            profile.key == "dc-kuorong-mmc3-v2"
            and standalone_unit_name_bank(source) is None
            and not standalone_names
            and len(name_codec.pool_spans) == 1
        )
        if lazy_legacy_capacity:
            used = sum(
                len(name_codec.record_bytes(index, source))
                for index in range(1, profile.unit_name_count)
            )
            capacity = used + LEGACY_UNIT_NAME_GROWTH_BUDGET
            address = (
                f"按需独立名称池（正文 CPU ${STANDALONE_UNIT_NAME_DATA_START:04X} 起；"
                "原生池放不下时才分配）"
            )
        else:
            pointers = sorted({name_codec.pointer(index, source) for index in range(1, profile.unit_name_count) if name_codec.pointer(index, source)})
            used = sum(len(name_codec._record_for_pointer(source, pointer)) for pointer in pointers)
            capacity = sum(end - start for start, end in name_codec.pool_spans)
            address = "；".join(f"CPU ${start:04X}—${end - 1:04X}" for start, end in name_codec.pool_spans)
        rows.append(_pool(
            "机体修改",
            "机体名称",
            address,
            used,
            capacity,
            "unit-names",
            (
                "独立扩展池；每个逻辑机体ID保留自己的名称记录"
                if standalone_names
                else (
                    "旧实验格式：原生名称池与部署池尾部；下次改名自动迁入独立扩展池"
                    if len(name_codec.pool_spans) > 1
                    else (
                        f"按旧修改器保留 {LEGACY_UNIT_NAME_GROWTH_BUDGET} B 净增长；"
                        "原生池不足时才分配"
                    )
                )
            ),
            "可变长重排；当前ROM若有重复指针，修改其中一个ID时自动拆分，不影响其他ID；"
            "机体名称不再借用初始配置容量；旧实验格式会在下次改名时自动迁移",
        ))
    if profile.unit_weapon_table_offset is not None:
        rows.append(_fixed("机体修改", "机体武器配置", profile.unit_weapon_table_offset, profile.unit_count * 2,
                           shared="机体页面与武器页面共同引用武器 ID"))
    try:
        composition = project.unit_composition_pool_status()
    except ValueError:
        composition = None
    if composition is not None:
        if composition.shared:
            rows.append(_pool(
                "机体修改",
                "主体＋碎片拼图脚本",
                "运行时目录定位的 Bank 对（含两张256项指针表）",
                composition.total_used,
                composition.total_capacity,
                "unit-composition-shared",
                "主体与碎片共用同一脚本容量；不与机体名称、属性或初始配置共用",
                "按旧修改器动态移动碎片目录和池尾；重复指针修改时只拆分目标机体",
            ))
        else:
            rows.append(_pool(
                "机体修改", "主体拼图脚本", "运行时主体目录",
                composition.body_used, composition.body_capacity,
                "unit-body-composition", "独立扩展池，不与碎片脚本共用",
            ))
            rows.append(_pool(
                "机体修改", "碎片拼图脚本", "运行时碎片目录",
                composition.fragment_used, composition.fragment_capacity,
                "unit-fragment-composition", "独立扩展池，不与主体脚本共用",
            ))
    configuration_pair = 16 + 0x04 * 0x2000
    configuration_table = source_configuration_table(source)
    configuration_pointers = struct.unpack_from(
        "<256H", source, configuration_pair + configuration_table - 0x8000
    )
    detached_configurations = {
        pointer
        for pointer in configuration_pointers[1:]
        if CONFIGURATION_CAVE_START <= pointer <= CONFIGURATION_CAVE_END - 10
    }
    if detached_configurations:
        rows.append(_pool(
            "机体修改",
            "战斗外观独立记录",
            _cpu_pool(
                project, 0x04, CONFIGURATION_CAVE_START, CONFIGURATION_CAVE_END
            ),
            len(detached_configurations) * 10,
            CONFIGURATION_CAVE_END - CONFIGURATION_CAVE_START,
            "unit-appearance-detached",
            "小型/大型类别、两组三色和图库地址按机体 ID 独立拆分",
            "复制或修改共用外观时只拆分目标 ID，不联动其他机体",
        ))

    # 人物修改
    pair_base = 16 + 0x24 * 0x2000
    try:
        bank24_directory_roots = tuple(struct.unpack_from("<8H", source, pair_base + 2))
        if (
            bank24_directory_roots[0] != 0x83F0
            or bank24_directory_roots != tuple(sorted(bank24_directory_roots))
        ):
            raise ValueError("Bank $24 的八资源目录无效。")
    except (IndexError, struct.error, ValueError):
        bank24_directory_roots = ()
    try:
        bank24_start, bank24_used_end, bank24_end, bank24_usage_roots = (
            _bank24_composite_usage(source)
        )
    except (IndexError, struct.error, ValueError):
        bank24_start = bank24_used_end = bank24_end = 0
        bank24_usage_roots = ()
    if bank24_usage_roots:
        rows.append(DatabaseMemoryRegion(
            "人物修改",
            "Bank $24 八资源物理共享块",
            _cpu_pool(project, 0x24, bank24_start, bank24_end),
            "可重排共享池（旧版八资源重排已接通）",
            (
                "人物属性、机体属性、武器属性、普通名称、战斗名称、机体名称、"
                "武器名称、32关初始配置共同占用"
            ),
            bank24_used_end - bank24_start,
            bank24_end - bank24_start,
            "bank24-eight-resource-composite",
            (
                "人物普通名、战斗名与人物属性保存均已接通旧版八资源整体重排，"
                "后续七项入口和内部指针会随增长同步后移。"
                f"八项入口：{'/'.join(f'${item:04X}' for item in bank24_usage_roots)}"
            ),
            True,
        ))
    character_name = project.character_name_codec
    if character_name is not None and len(bank24_directory_roots) >= 5:
        if profile.character_normal_name_pointer_table_offset is not None:
            normal_table_offset = pair_base + bank24_directory_roots[3] - 0x8000 + 2
            rows.append(_fixed("人物修改", "普通名称指针表", normal_table_offset,
                               profile.character_normal_name_count * 2,
                               shared="与战斗名称同属 Bank $24；逻辑记录独立、正文可去重"))
        battle_table_offset = pair_base + bank24_directory_roots[4] - 0x8000
        rows.append(_fixed("人物修改", "战斗名称指针表", battle_table_offset,
                           profile.character_name_count * 2,
                           shared="与普通名称同属 Bank $24；相同正文跨表去重"))
    try:
        attributes = CharacterAttributesCodec(project)
    except Exception:
        attributes = None
    if attributes is not None and bank24_directory_roots:
        attribute_table = pair_base + bank24_directory_roots[0] - 0x8000
        rows.append(_fixed("人物修改", "人物属性指针表", attribute_table, attributes.COUNT * 2,
                           shared="相同指针的人物共用属性记录"))
        rows.append(_fixed("人物修改", "头像指针表", attributes.PORTRAIT_TABLE, attributes.COUNT * 2,
                           shared="重复指针只表示存储压缩；人物头像按ID独立修改"))
        portrait_offsets = {attributes.record_offset(index, portrait=True) for index in range(1, attributes.COUNT)}
        portrait_root, portrait_tail_used_end, portrait_tail_end = _portrait_configuration_tail(source)
        rows.append(DatabaseMemoryRegion(
            "人物修改",
            "头像配置＋机体战斗外观共享尾区",
            _cpu_pool(project, 0x04, portrait_root, portrait_tail_end),
            "可重排共享尾区",
            (
                f"头像当前 {len(portrait_offsets)} 条唯一记录、{len(portrait_offsets) * 7} B；"
                "按人物ID独立修改，后接机体战斗外观并共同后移"
            ),
            portrait_tail_used_end - portrait_root,
            portrait_tail_end - portrait_root,
            "portrait-unit-configuration-tail",
            (
                "剩余量已按旧版 9/10 B 战斗外观记录边界动态计算；"
                "头像保存按目标人物自动拆分并同步后移机体战斗外观；"
                "剩余量只供这组复合尾区使用"
            ),
        ))
        rows.append(_fixed("人物修改", "精神消耗", attributes.COSTS, 24,
                           note="24 项固定字节表，不与名称或头像池共用"))
    dialogue = project.character_dialogue_codec
    if dialogue is not None:
        assert profile.character_dialogue_pointer_table_offset is not None
        rows.append(_fixed("人物修改", "人物台词绑定指针表", profile.character_dialogue_pointer_table_offset,
                           profile.character_dialogue_count * 2,
                           shared="重复指针仅作存储压缩；编辑时按人物 ID 自动拆分"))
        pointers = sorted(set(dialogue._pointers(source)))
        dialogue_used = sum(len(dialogue._record_bytes(dialogue._pointers(source).index(pointer) + 1, source))
                            for pointer in pointers)
        assert profile.character_dialogue_data_end_pointer is not None
        rows.append(_pool("人物修改", "人物台词绑定记录",
                          _cpu_pool(project, profile.character_dialogue_data_prg_bank or 0,
                                    dialogue._pool_start, profile.character_dialogue_data_end_pointer),
                          dialogue_used, profile.character_dialogue_data_end_pointer - dialogue._pool_start,
                          "character-dialogue", "200 个逻辑人物独立编辑；相同结果自动去重"))
        if profile.character_transform_table_offset is not None:
            bindings = dialogue.transform_bindings(source)
            used = (len(bindings) + 1) * 4
            capacity = profile.character_transform_capacity * 4
            rows.append(_pool("人物修改", "变形台词绑定", _file_range(profile.character_transform_table_offset,
                                                                     profile.character_transform_table_offset + capacity),
                              used, capacity, "character-transform", "最多 15 项，另保留 1 项结束标记",
                              "顺序表可增删；必须保留结束标记"))

    # 武器修改
    rows.append(_fixed("武器修改", "武器属性指针表", project.weapon_codec.pointer_table_offset,
                       profile.weapon_pointer_count * 2))
    weapon_unique = sorted({pointer for pointer in project.weapon_codec.pointers[1:] if pointer})
    weapon_offsets = [project.weapon_codec.record_offset_from_pointer(pointer) for pointer in weapon_unique]
    if weapon_offsets:
        rows.append(_fixed("武器修改", "武器属性记录", min(weapon_offsets), len(weapon_offsets) * WEAPON_RECORD_SIZE,
                           shared="相同指针的武器共用一条属性记录",
                           note=f"{len(weapon_unique)} 条物理记录；每条固定 {WEAPON_RECORD_SIZE} 字节"))
    weapon_names = project.weapon_name_codec
    if weapon_names is not None:
        rows.append(_fixed("武器修改", "武器名称指针表", weapon_names.pointer_table_offset,
                           profile.weapon_name_pointer_count * 2,
                           shared="全部武器名称与别名共用名称池"))
        pointers = weapon_names._sorted_pointers(source)
        used = sum(len(weapon_names._terminated_record(weapon_names.record_bytes(
            next(index for index in range(profile.weapon_name_pointer_count)
                 if weapon_names.pointer(index, source) == pointer), source))) for pointer in pointers)
        rows.append(_pool("武器修改", "武器名称",
                          _cpu_pool(project, profile.weapon_name_data_prg_bank or 0,
                                    weapon_names.data_first_pointer, weapon_names.data_end_pointer),
                          used, weapon_names.data_end_pointer - weapon_names.data_first_pointer,
                          "weapon-names", "全部武器名称及名称别名共用"))

    # 战斗对话、系统文字和道具说明使用同一经过验证的文字对象分配器。
    text = LegacyTextCodec(source, capacity_data=project.original)
    for bank, label in ((0x2A, "进攻战斗对话"), (0x0E, "防御战斗对话")):
        usage = text.battle_usage(bank)
        rows.append(_pool("战斗对话", label, f"Bank ${bank:02X} 的多个安全段",
                          usage.used, usage.capacity, f"battle-text-{bank:02x}",
                          f"该 Bank 内普通对话、特殊对话、随机目录共用；不与 Bank ${0x0E if bank == 0x2A else 0x2A:02X} 共用"))

    system = text.simple_group_usage("system")
    group = next(item for item in TEXT_GROUPS if item.key == "system")
    rows.append(_pool("其他修改1", "系统文字", _cpu_pool(project, group.bank, group.pool_start, group.pool_end),
                      system.used, system.capacity, "system-text", "221 项系统文字共用"))
    rows.append(_fixed("其他修改1", "成长方式指针表", LegacyGrowthCodec.POINTER_TABLE,
                       LegacyGrowthCodec.COUNT * 2,
                       shared="53 个逻辑编号可共用固定成长记录"))
    growth = LegacyGrowthCodec(source)
    growth_offsets = set(growth.offsets)
    rows.append(_fixed("其他修改1", "成长方式记录", min(growth_offsets),
                       len(growth_offsets) * LegacyGrowthCodec.RECORD_SIZE,
                       shared="共用指针的成长方式共享同一 50 字节记录",
                       note="每条固定 50 字节；不能把池内间隙作为可增长容量"))
    global_spec = profile.legacy_global_data
    if global_spec is not None:
        rows.append(_fixed("其他修改1", "累计经验表", global_spec.experience_totals_offset, 99 * 2))
        rows.append(_fixed("其他修改1", "距离命中补正", global_spec.distance_hit_table_offset, 4 * 16))
        rows.append(_fixed("其他修改1", "初始人物/机体", global_spec.initial_roster_offset, 6 * 2 + 1))
        formula_offsets = tuple(offset for group_offsets in global_spec.double_hit_operand_groups for offset in group_offsets)
        formula_offsets += tuple(global_spec.damage_formula_operand_offsets)
        formula_offsets += (global_spec.hit_threshold_operand_offset, *global_spec.item_effect_operand_offsets)
        rows.append(DatabaseMemoryRegion("其他修改1", "公式与道具效果操作数", "、".join(f"0x{x:06X}" for x in formula_offsets),
                                         "固定散点（可改值）", "多处运行时代码副本需同步", len(formula_offsets), len(formula_offsets), None,
                                         "离散固定操作数字节；不能扩展或借用相邻代码"))

        # 其他修改2
        item_records = project.get_item_name_records()
        item_used = sum(len(record) + 1 for record in item_records)
        item_capacity = global_spec.item_name_pool_end_offset - global_spec.item_name_pool_start_offset
        rows.append(_fixed("其他修改2", "道具名称指针表", global_spec.item_name_pointer_table_offset,
                           global_spec.item_count * 2, shared="与道具名称池配套"))
        rows.append(_pool("其他修改2", "道具名称",
                          _file_range(global_spec.item_name_pool_start_offset, global_spec.item_name_pool_end_offset),
                          item_used, item_capacity, "item-names", "24 个道具名称共用"))
        rows.append(_fixed("其他修改2", "道具价格", global_spec.item_price_table_offset,
                           global_spec.item_count, note="24 项固定字节价格表"))
    item_description = text.simple_group_usage("item_description")
    group = next(item for item in TEXT_GROUPS if item.key == "item_description")
    rows.append(_pool("其他修改2", "道具说明", _cpu_pool(project, group.bank, group.pool_start, group.pool_end),
                      item_description.used, item_description.capacity, "item-descriptions", "24 条道具说明共用"))
    try:
        shops = LegacyShopCodec(source)
    except Exception:
        shops = None
    if shops is not None:
        records = tuple(shops.record(shop_id) for shop_id in range(0xF0, 0xF5))
        rows.append(DatabaseMemoryRegion(
            "其他修改2", "商店目录与商品", "；".join(_file_range(record.file_offset, record.file_offset + len(record.raw)) for record in records),
            "固定结构（可改值）", "商店对话编号引用系统文字，但不占用系统文字池的新空间",
            sum(len(record.raw) for record in records), sum(len(record.raw) for record in records), None,
            "5 个商店记录商品数量固定；不能增减记录长度",
        ))

    return DatabaseMemoryReport(tuple(rows))


_REPORT_CACHE: WeakKeyDictionary[Any, tuple[int, DatabaseMemoryReport]] = (
    WeakKeyDictionary()
)


def cached_database_memory_report(
    project: Any, *, force: bool = False
) -> DatabaseMemoryReport:
    """Reuse the full database scan until the ROM edit generation changes."""

    revision = int(getattr(project, "revision", -1))
    cached = _REPORT_CACHE.get(project)
    if not force and cached is not None and cached[0] == revision:
        return cached[1]
    report = build_database_memory_report(project)
    _REPORT_CACHE[project] = (revision, report)
    return report


class DatabaseMemoryDialog(QDialog):
    MODULES = ("全部模块", "机体修改", "人物修改", "武器修改", "战斗对话", "其他修改1", "其他修改2")

    def __init__(
        self,
        project: Any,
        parent: QWidget | None = None,
        *,
        module: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.module = module
        complete_report = cached_database_memory_report(project)
        self.report = complete_report.for_module(module) if module else complete_report
        self.setWindowTitle(f"{module} · 内存与共用容量" if module else "数据库内存分布")
        self.resize(1180, 700)
        self.setMinimumSize(900, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        intro = QLabel(
            "只有已验证边界且已接通写入器的区域才计入“可用剩余”。“物理余量（未接通）”只用于解释 ROM 布局，"
            "不能直接拿来保存；固定表中的 00/FF、重复指针和未识别间隙也不算空闲。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("databaseMemoryNotice")
        intro.setStyleSheet(
            "QLabel { background: #eef7f7; border: 1px solid #b8d4d7; "
            "border-radius: 5px; color: #275761; padding: 7px 9px; }"
        )
        root.addWidget(intro)

        summary = QHBoxLayout()
        self.pool_summary = QLabel()
        self.fixed_summary = QLabel()
        self.shared_summary = QLabel()
        for card in (self.pool_summary, self.fixed_summary, self.shared_summary):
            card.setObjectName("databaseMemoryCard")
            card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card.setMinimumHeight(54)
            card.setStyleSheet(
                "QLabel { background: #f5f8f9; border: 1px solid #c8d5d9; "
                "border-radius: 5px; color: #244c56; padding: 5px 8px; }"
            )
            summary.addWidget(card, 1)
        root.addLayout(summary)
        self.pool_summary.setText(
            f"可重排池\n已用 {self.report.pool_used:,} / {self.report.pool_capacity:,} B · 剩余 {self.report.pool_remaining:,} B"
        )
        self.fixed_summary.setText(f"固定结构\n{self.report.fixed_bytes:,} B · 可改现有值，不增加结构")
        observed_count = len({
            region.pool_key for region in self.report.regions if region.is_observed_pool
        })
        self.shared_summary.setText(
            f"容量状态\n可写 {len(self.report.repackable_regions)} 组 · "
            f"仅观察 {observed_count} 组"
        )

        tools = QHBoxLayout()
        tools.addWidget(QLabel("显示："))
        self.module_filter = QComboBox()
        self.module_filter.addItems((module,) if module else self.MODULES)
        self.module_filter.setEnabled(module is None)
        self.module_filter.currentTextChanged.connect(self._populate)
        tools.addWidget(self.module_filter)
        tools.addStretch()
        self.refresh_button = QPushButton("重新读取当前草稿")
        self.refresh_button.clicked.connect(self.refresh)
        tools.addWidget(self.refresh_button)
        root.addLayout(tools)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(("模块", "数据区", "ROM 地址", "类型", "共用关系", "已用", "容量", "剩余", "占用"))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in (0, 1, 3, 5, 6, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (2, 4, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        hint = QLabel("提示：某一共享池的剩余只能供该池使用，不能借给另一模块；关闭本窗口不会修改 ROM。")
        hint.setWordWrap(True)
        footer.addWidget(hint, 1)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)
        self._populate()

    def refresh(self) -> None:
        complete_report = cached_database_memory_report(self.project, force=True)
        self.report = complete_report.for_module(self.module) if self.module else complete_report
        self.pool_summary.setText(
            f"可重排池\n已用 {self.report.pool_used:,} / {self.report.pool_capacity:,} B · 剩余 {self.report.pool_remaining:,} B"
        )
        self.fixed_summary.setText(f"固定结构\n{self.report.fixed_bytes:,} B · 可改现有值，不增加结构")
        observed_count = len({
            region.pool_key for region in self.report.regions if region.is_observed_pool
        })
        self.shared_summary.setText(
            f"容量状态\n可写 {len(self.report.repackable_regions)} 组 · "
            f"仅观察 {observed_count} 组"
        )
        self._populate()

    def _populate(self, _text: str = "") -> None:
        selected = self.module_filter.currentText()
        regions = [region for region in self.report.regions if selected == "全部模块" or region.module == selected]
        self.table.setRowCount(len(regions))
        for row, region in enumerate(regions):
            if region.is_repackable:
                availability = f"净增长 {region.remaining:,} B"
            elif region.is_observed_pool:
                availability = (
                    f"物理余量 {region.remaining:,} B（未接通）"
                    if region.remaining
                    else "当前门禁：不可增长"
                )
            else:
                availability = "可改值"
            values = (
                region.module, region.resource, region.address, region.kind,
                region.shared_with, f"{region.used:,} B", f"{region.capacity:,} B",
                availability,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(region.note)
                if column in (5, 6, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column == 3:
                    item.setForeground(
                        QColor("#1f6f78")
                        if region.is_repackable
                        else QColor("#8a641f")
                        if region.is_observed_pool
                        else QColor("#66717a")
                    )
                self.table.setItem(row, column, item)
            bar = QProgressBar()
            bar.setRange(0, max(1, region.capacity))
            bar.setValue(min(region.used, max(1, region.capacity)))
            suffix = (
                f" · 净增 {region.remaining:,} B"
                if region.is_repackable
                else f" · 物理余量 {region.remaining:,} B（未接通）"
                if region.is_observed_pool and region.remaining
                else " · 当前门禁"
                if region.is_observed_pool
                else " · 可改值"
            )
            bar.setFormat(
                f"{round(region.used * 100 / region.capacity) if region.capacity else 100}%{suffix}"
            )
            ratio = region.used / region.capacity if region.capacity else 1.0
            color = "#c5524a" if ratio >= 1 else "#d39b37" if ratio >= 0.85 else "#4a8f75"
            if region.is_observed_pool:
                color = "#c28a32"
            elif not region.is_repackable:
                color = "#84919a"
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")
            bar.setToolTip(region.note)
            self.table.setCellWidget(row, 8, bar)


class DatabaseModuleMemoryPanel(QFrame):
    """Compact, live capacity strip embedded in one database module.

    Pools are deliberately kept separate.  Adding their free bytes together
    would imply that unrelated ROM ranges can borrow capacity from each other,
    which is not true for the original game or the reference editor.
    """

    def __init__(
        self,
        project: Any,
        module: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.module = module
        self.setObjectName("databaseModuleMemoryPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame#databaseModuleMemoryPanel { background: #f3f8f8; "
            "border: 1px solid #bfd3d6; border-radius: 5px; }"
            "QLabel#databaseModuleMemoryTitle { color: #185968; font-weight: 600; }"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(7, 2, 7, 2)
        row.setSpacing(6)
        title = QLabel(f"{module} · 内存")
        title.setObjectName("databaseModuleMemoryTitle")
        self.summary = QLabel()
        self.summary.setObjectName("databaseModuleMemorySummary")
        self.summary.setMinimumWidth(0)
        self.summary.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_button = QPushButton("内存明细…")
        self.detail_button.setObjectName("databaseModuleMemoryDetails")
        self.detail_button.setFixedSize(96, 22)
        self.detail_button.setToolTip("查看本模块各内存区域的容量、占用和安全边界")
        self.detail_button.clicked.connect(self.open_details)
        row.addWidget(title)
        row.addWidget(self.summary, 1)
        row.addWidget(self.detail_button)
        self.setFixedHeight(28)
        self.refresh()

    def refresh(self, *_args: object) -> None:
        report = cached_database_memory_report(self.project).for_module(self.module)
        pools = report.repackable_regions
        if self.module == "人物修改":
            bank24 = next(
                (
                    region
                    for region in report.regions
                    if region.pool_key == "bank24-eight-resource-composite"
                ),
                None,
            )
            parts: list[str] = []
            if bank24 is not None:
                parts.append(
                    f"Bank $24：{bank24.used:,}/{bank24.capacity:,} B，"
                    f"共享余量 {bank24.remaining:,} B（人物名称与属性已接通）"
                )
            if any(region.pool_key != "bank24-eight-resource-composite" for region in pools):
                parts.append("其他池见明细")
            pool_text = " ｜ ".join(parts)
        elif pools:
            pool_text = "；".join(
                f"{region.resource}：{region.used:,}/{region.capacity:,} B（余 {region.remaining:,} B）"
                for region in pools
            )
        else:
            pool_text = "无可增长池"
        self.summary.setText(
            f"{pool_text} ｜ 固定 {report.fixed_bytes:,} B"
        )
        shared = "\n".join(
            f"{region.resource}：{region.shared_with}\n  {region.note}"
            for region in report.regions
        )
        self.summary.setToolTip(
            "可写余量只能由已接通的对应写入器使用；标为“未接通”的物理余量不能直接借用。\n"
            + shared
        )

    def open_details(self) -> None:
        dialog = DatabaseMemoryDialog(self.project, self, module=self.module)
        dialog.exec()

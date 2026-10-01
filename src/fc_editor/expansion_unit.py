from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Sequence

from .constants import INES_HEADER_SIZE, PRG_BANK_SIZE, UNIT_RECORD_SIZE


PAIR_SIZE = PRG_BANK_SIZE * 2
UNIT_ID_COUNT = 0xFF

# The reclaimed banks exposed by the 1.25 MiB Mapper 194 handoff.  Bank $64
# remains the dual-audio bridge and $7E/$7F remain fixed program banks.
MANAGED_EXPANSION_BANKS = frozenset(
    (*range(0x40, 0x61), *range(0x65, 0x7E))
)

# Active selector table in fixed PRG Bank $7F.  The older copy in Bank $3F is
# deliberately not patched.
RESOURCE_DESCRIPTOR_TABLE_OFFSET = (
    INES_HEADER_SIZE + 0x7F * PRG_BANK_SIZE + (0xF3E2 - 0xE000)
)

UNIT_NAME_SELECTOR = 0x13
UNIT_BODY_SELECTOR = 0x21
UNIT_FRAGMENT_SELECTOR = 0x41
UNIT_ATTRIBUTE_SELECTOR = 0x71
UNIT_CONFIGURATION_SELECTOR = 0x74

SOURCE_CONFIGURATION_PAIR = 0x04
SOURCE_CORE_PAIR = 0x24
SOURCE_COMPOSITION_PAIR = 0x28

ATTRIBUTE_TABLE = 0x875F
ATTRIBUTE_OLD_DATA_START = 0x895F
ATTRIBUTE_OLD_DATA_END = 0x8EBF
NAME_TABLE = 0x98F8
NAME_OLD_DATA_START = 0x9AF8
NAME_OLD_DATA_END = 0x9DAD
CORE_CAVE_START = 0xA929
CORE_CAVE_END = 0xBF40

CONFIGURATION_TABLE = 0xADB9
CONFIGURATION_OLD_DATA_START = 0xAFB9
CONFIGURATION_OLD_DATA_END = 0xB2C8
CONFIGURATION_CAVE_START = 0xB5E6
CONFIGURATION_CAVE_END = 0xC000
CONFIGURATION_RECORD_SIZE = 10

SOURCE_BODY_TABLE = 0x8010
SOURCE_BODY_DATA_START = 0x8210
SOURCE_BODY_DATA_END = 0x9201
SOURCE_FRAGMENT_TABLE = 0x9201
SOURCE_FRAGMENT_DATA_START = 0x9401
SOURCE_FRAGMENT_DATA_END = 0x9FFC

PACKED_BODY_TABLE = 0x8010
PACKED_FRAGMENT_TABLE = 0x8210
PACKED_COMPOSITION_DATA_START = 0x8410
SINGLE_RESOURCE_TABLE = 0x8010
SINGLE_RESOURCE_DATA_START = 0x8210

# A unit-name-only relocation uses the already verified selector $13 without
# forcing the map/body/fragment capacity planner to run.  The game reads only
# directory slot 6 and the active table at $8010.  The second table is editor
# metadata: it retains one canonical pointer per logical unit so changing one
# member of a shared-name group can use copy-on-write semantics after reopen.
STANDALONE_UNIT_NAME_MAGIC_V1 = b"DCUNAME1"
STANDALONE_UNIT_NAME_MAGIC = b"DCUNAME2"
STANDALONE_UNIT_NAME_RESOURCE_ID = "auto.partition.unit-names"
STANDALONE_UNIT_NAME_CANONICAL_TABLE = 0x8210
STANDALONE_UNIT_NAME_DATA_START = 0x8410
# With the other legacy resources unchanged, the reference editor could grow
# unit names from the observed end $A483 to its hard stop $BEB0.
LEGACY_UNIT_NAME_GROWTH_BUDGET = 0xBEB0 - 0xA483
STANDALONE_UNIT_NAME_CAPACITY_OFFSET = 8

# A unit-attribute-only relocation mirrors the original $24/$25 pair so the
# selector-$71 loader can return through the same code, but gives every
# logical unit its own fixed 16-byte record.  The mirror's $25 scenario bytes
# are not runtime-visible while selector $71 is active, so the same cave proven
# by the full unit linker can safely hold the independent records without
# consuming or changing the live initial-configuration pool.
STANDALONE_UNIT_ATTRIBUTE_MAGIC = b"DCUATTR1"
STANDALONE_UNIT_ATTRIBUTE_RESOURCE_ID = "auto.partition.unit-attributes"
STANDALONE_UNIT_ATTRIBUTE_MAGIC_OFFSET = CORE_CAVE_START
STANDALONE_UNIT_ATTRIBUTE_DATA_START = 0xA940

SUPPORTED_PAIR_COUNTS = (3, 4, 5)
SUPPORTED_UNIT_KIB = tuple(count * 16 for count in SUPPORTED_PAIR_COUNTS)


@dataclass(frozen=True)
class BankPairImage:
    """One runtime-visible $8000-$BFFF image and its target PRG banks."""

    role: str
    first_bank: int
    image: bytes

    def __post_init__(self) -> None:
        if len(self.image) != PAIR_SIZE:
            raise ValueError("Bank 对镜像必须正好是 16 KiB。")

    @property
    def second_bank(self) -> int:
        return self.first_bank + 1

    @property
    def file_offset(self) -> int:
        return INES_HEADER_SIZE + self.first_bank * PRG_BANK_SIZE

    @property
    def bank_images(self) -> tuple[tuple[int, bytes], tuple[int, bytes]]:
        return (
            (self.first_bank, self.image[:PRG_BANK_SIZE]),
            (self.second_bank, self.image[PRG_BANK_SIZE:]),
        )


@dataclass(frozen=True)
class DescriptorPatch:
    """One two-byte selector descriptor update in active fixed Bank $7F."""

    selector: int
    offset: int
    before: bytes
    after: bytes
    pair_start: int
    directory_index: int


@dataclass(frozen=True)
class ResourceLayout:
    """Everything a bank-aware editor needs to find one relocated table."""

    selector: int
    pair_start: int
    directory_index: int
    pointer_table: int
    pointers: tuple[int, ...]
    record_sizes: tuple[int, ...]
    data_spans: tuple[tuple[int, int], ...]
    used_bytes: int
    pool_capacity: int

    def __post_init__(self) -> None:
        if len(self.pointers) != 0x100 or len(self.record_sizes) != 0x100:
            raise ValueError("运行时布局必须包含 256 个索引。")
        if self.pointers[0] or self.record_sizes[0]:
            raise ValueError("ID $00 必须保留为空指针。")


@dataclass(frozen=True)
class UnitExpansionRecords:
    """Lossless ID $01-$FF source records used by the relocator."""

    attributes: tuple[bytes, ...]
    names: tuple[bytes, ...]
    configurations: tuple[bytes, ...]
    body_scripts: tuple[bytes, ...]
    fragment_scripts: tuple[bytes, ...]

    def __post_init__(self) -> None:
        groups = (
            ("机体属性", self.attributes),
            ("机体名称", self.names),
            ("战斗外观", self.configurations),
            ("主体拼图", self.body_scripts),
            ("碎片拼图", self.fragment_scripts),
        )
        for label, records in groups:
            if len(records) != UNIT_ID_COUNT:
                raise ValueError(f"{label}必须包含 ID $01—$FF 的 255 条记录。")
        if any(len(record) != UNIT_RECORD_SIZE for record in self.attributes):
            raise ValueError("每条机体属性必须正好是 16 字节。")
        if any(
            len(record) != CONFIGURATION_RECORD_SIZE
            for record in self.configurations
        ):
            raise ValueError("每条战斗外观必须是归一化的 10 字节。")
        for label, records in (
            ("机体名称", self.names),
            ("主体拼图", self.body_scripts),
            ("碎片拼图", self.fragment_scripts),
        ):
            if any(not record or record[-1] != 0xFF for record in records):
                raise ValueError(f"{label}记录必须以 $FF 结束。")


@dataclass(frozen=True)
class StockCompositionLayout:
    """Runtime-visible stock Bank $28/$29 composition directory."""

    body_table: int
    fragment_table: int
    data_end: int
    body_pointers: tuple[int, ...]
    fragment_pointers: tuple[int, ...]
    body_scripts: tuple[bytes, ...]
    fragment_scripts: tuple[bytes, ...]

    @property
    def body_used(self) -> int:
        return self.fragment_table - (self.body_table + 0x200)

    @property
    def fragment_used(self) -> int:
        return self.data_end - (self.fragment_table + 0x200)

    @property
    def script_capacity(self) -> int:
        return 0xC000 - (self.body_table + 0x400)


@dataclass(frozen=True)
class PackedUnitExpansion:
    """Three pair images, selector patches, and their runtime layouts."""

    pair_images: tuple[BankPairImage, ...]
    descriptor_patches: tuple[DescriptorPatch, ...]
    resources: tuple[ResourceLayout, ...]
    composition_capacity: int
    composition_used: int
    name_baseline_pointers: tuple[int, ...]

    @property
    def composition_available(self) -> int:
        return self.composition_capacity - self.composition_used

    @property
    def bank_images(self) -> tuple[tuple[int, bytes], ...]:
        return tuple(
            bank_image
            for pair in self.pair_images
            for bank_image in pair.bank_images
        )

    def resource(self, selector: int) -> ResourceLayout:
        try:
            return next(item for item in self.resources if item.selector == selector)
        except StopIteration as error:
            raise KeyError(f"未打包资源选择器 ${selector:02X}。") from error

    def pair(self, first_bank: int) -> BankPairImage:
        try:
            return next(
                item for item in self.pair_images if item.first_bank == first_bank
            )
        except StopIteration as error:
            raise KeyError(f"未打包 Bank 对 ${first_bank:02X}。") from error

    def record_bytes(self, selector: int, record_id: int) -> bytes:
        if not 1 <= record_id <= 0xFF:
            raise IndexError("机体 ID 必须在 $01—$FF 之间。")
        layout = self.resource(selector)
        pointer = layout.pointers[record_id]
        size = layout.record_sizes[record_id]
        if not 0x8000 <= pointer < 0xC000 or pointer + size > 0xC000:
            raise ValueError("打包指针超出 $8000—$BFFF 窗口。")
        image = self.pair(layout.pair_start).image
        start = pointer - 0x8000
        return image[start : start + size]

    def apply(self, rom_data: bytes | bytearray) -> bytes:
        """Return a ROM copy with pair images and active descriptors applied."""

        result = bytearray(rom_data)
        for pair in self.pair_images:
            end = pair.file_offset + PAIR_SIZE
            if end > len(result):
                raise ValueError("目标 Bank 对超出 ROM。")
            result[pair.file_offset:end] = pair.image
        for patch in self.descriptor_patches:
            if bytes(result[patch.offset : patch.offset + 2]) != patch.before:
                raise ValueError(
                    f"选择器 ${patch.selector:02X} 的原始描述符已变化。"
                )
            result[patch.offset : patch.offset + 2] = patch.after
        return bytes(result)


def _validate_rom(rom_data: bytes) -> None:
    if len(rom_data) < INES_HEADER_SIZE + 0x80 * PRG_BANK_SIZE:
        raise ValueError("ROM 没有完整的 128 个 PRG Bank。")
    if rom_data[:4] != b"NES\x1A":
        raise ValueError("文件不是 iNES ROM。")
    if rom_data[6] & 0x04:
        raise ValueError("机体扩展打包器不支持带 Trainer 的 ROM。")


def _pair_slice(rom_data: bytes, first_bank: int) -> bytes:
    start = INES_HEADER_SIZE + first_bank * PRG_BANK_SIZE
    end = start + PAIR_SIZE
    value = bytes(rom_data[start:end])
    if len(value) != PAIR_SIZE:
        raise ValueError(f"PRG Bank 对 ${first_bank:02X} 不完整。")
    return value


def _cpu_offset(cpu_address: int) -> int:
    if not 0x8000 <= cpu_address <= 0xC000:
        raise ValueError(f"CPU 地址 ${cpu_address:04X} 超出 16 KiB 窗口。")
    return cpu_address - 0x8000


def _read_pointers(image: bytes, table_address: int) -> tuple[int, ...]:
    start = _cpu_offset(table_address)
    end = start + 0x200
    if end > len(image):
        raise ValueError("指针表超出 Bank 对。")
    pointers = tuple(struct.unpack("<256H", image[start:end]))
    if pointers[0] != 0:
        raise ValueError(f"指针表 ${table_address:04X} 的 ID $00 不是空指针。")
    return pointers


def source_configuration_table(rom_data: bytes | bytearray) -> int:
    """Return the stock Bank $04 battle-appearance directory root."""

    image = _pair_slice(bytes(rom_data), SOURCE_CONFIGURATION_PAIR)
    pointer = struct.unpack_from("<H", image, 6 * 2)[0]
    if not 0x8000 <= pointer <= CONFIGURATION_CAVE_START - 0x200:
        raise ValueError("原 Bank $04/$05 的战斗外观目录无效。")
    return pointer


def _read_fixed_records(
    image: bytes,
    pointers: tuple[int, ...],
    size: int,
    *,
    lower: int,
    upper: int,
    label: str,
) -> tuple[bytes, ...]:
    records: list[bytes] = []
    for record_id, pointer in enumerate(pointers[1:], 1):
        if not lower <= pointer or pointer + size > upper:
            raise ValueError(
                f"{label} ${record_id:02X} 指针 ${pointer:04X} 超出已验证数据池。"
            )
        start = _cpu_offset(pointer)
        records.append(bytes(image[start : start + size]))
    return tuple(records)


def _read_fixed_records_from_spans(
    image: bytes,
    pointers: tuple[int, ...],
    size: int,
    *,
    spans: tuple[tuple[int, int], ...],
    label: str,
) -> tuple[bytes, ...]:
    """Read fixed records from one of several verified storage spans."""

    records: list[bytes] = []
    for record_id, pointer in enumerate(pointers[1:], 1):
        if not any(lower <= pointer and pointer + size <= upper
                   for lower, upper in spans):
            raise ValueError(
                f"{label} ${record_id:02X} 指针 ${pointer:04X} 超出已验证数据池。"
            )
        start = _cpu_offset(pointer)
        records.append(bytes(image[start:start + size]))
    return tuple(records)


def _read_terminated_names(
    image: bytes,
    pointers: tuple[int, ...],
    *,
    spans: tuple[tuple[int, int], ...] = ((NAME_OLD_DATA_START, NAME_OLD_DATA_END),),
) -> tuple[bytes, ...]:
    active = pointers[1:]
    pointer_spans: dict[int, tuple[int, int]] = {}
    for record_id, pointer in enumerate(active, 1):
        span = next(
            ((lower, upper) for lower, upper in spans if lower <= pointer < upper),
            None,
        )
        if span is None:
            raise ValueError(
                f"机体名称 ${record_id:02X} 指针 ${pointer:04X} 超出已验证数据池。"
            )
        pointer_spans[pointer] = span

    # Aliases are legal: several unit IDs may share one name record.  The
    # next distinct pointer in the same verified span is the authoritative
    # end of a packed record.  Searching for any later $FF is insufficient:
    # a damaged terminator would otherwise silently consume the next name.
    records_by_pointer: dict[int, bytes] = {}
    for span in spans:
        lower, upper = span
        packed = sorted(
            pointer for pointer in set(active) if pointer_spans[pointer] == span
        )
        for index, pointer in enumerate(packed):
            start = _cpu_offset(pointer)
            if index + 1 < len(packed):
                end = _cpu_offset(packed[index + 1])
            else:
                end = _cpu_offset(upper)
                # Relocated pairs are zero-filled after the last packed name.
                # The stock span also ends with padding, so trimming only that
                # padding recovers the final record boundary without assuming
                # a canonical (and no longer fixed) encoded length.
                while end > start and image[end - 1] == 0:
                    end -= 1
            value = bytes(image[start:end])
            if not value or value[-1] != 0xFF:
                raise ValueError(
                    f"机体名称记录 ${pointer:04X} 边界未以 $FF 结束。"
                )
            records_by_pointer[pointer] = value

    return tuple(records_by_pointer[pointer] for pointer in active)


def _standalone_name_record(raw: bytes) -> bytes:
    """Trim one decoded name view to its first complete record.

    Stock aliases can leave more than one terminated name between two distinct
    pointers.  The expansion format gives every logical source ID its own
    canonical record, so only the first complete name belongs to that ID.
    """

    glyph_leads = frozenset(
        (*range(0xB8, 0xBC), *range(0xC8, 0xCC), *range(0xD8, 0xDC))
    )
    cursor = 0
    while cursor < len(raw):
        lead = raw[cursor]
        if lead in glyph_leads:
            if cursor + 1 >= len(raw):
                raise ValueError("机体名称以不完整的双字节字形码结尾。")
            cursor += 2
            continue
        cursor += 1
        if lead == 0xFF:
            return raw[:cursor]
    raise ValueError("机体名称没有独立的 $FF 结束码。")


def _read_pointer_bounded_scripts(
    image: bytes,
    pointers: tuple[int, ...],
    *,
    data_start: int,
    data_end: int,
    label: str,
) -> tuple[bytes, ...]:
    usable = sorted(set(pointers[1:]))
    if not usable or any(not data_start <= value < data_end for value in usable):
        raise ValueError(f"{label}指针超出已验证数据池。")
    ends = {
        pointer: usable[index + 1] if index + 1 < len(usable) else data_end
        for index, pointer in enumerate(usable)
    }
    by_pointer: dict[int, bytes] = {}
    for pointer in usable:
        start = _cpu_offset(pointer)
        end = _cpu_offset(ends[pointer])
        value = bytes(image[start:end])
        if not value or value[-1] != 0xFF:
            raise ValueError(f"{label}记录 ${pointer:04X} 边界未以 $FF 结束。")
        by_pointer[pointer] = value
    return tuple(by_pointer[pointer] for pointer in pointers[1:])


def read_stock_composition_layout(
    rom_data: bytes | bytearray,
) -> StockCompositionLayout:
    """Read the movable stock Bank $28/$29 composition directory."""

    image = _pair_slice(bytes(rom_data), SOURCE_COMPOSITION_PAIR)
    body_table, fragment_table, data_end = struct.unpack_from("<3H", image, 0)
    if body_table != SOURCE_BODY_TABLE:
        raise ValueError("原生机体拼图目录起点与已验证格式不同。")
    if not (
        body_table + 0x200 < fragment_table
        and fragment_table + 0x200 < data_end <= 0xC000
    ):
        raise ValueError("原生机体拼图动态目录边界无效。")
    body_pointers = _read_pointers(image, body_table)
    fragment_pointers = _read_pointers(image, fragment_table)
    return StockCompositionLayout(
        body_table=body_table,
        fragment_table=fragment_table,
        data_end=data_end,
        body_pointers=body_pointers,
        fragment_pointers=fragment_pointers,
        body_scripts=_read_pointer_bounded_scripts(
            image,
            body_pointers,
            data_start=body_table + 0x200,
            data_end=fragment_table,
            label="主体拼图",
        ),
        fragment_scripts=_read_pointer_bounded_scripts(
            image,
            fragment_pointers,
            data_start=fragment_table + 0x200,
            data_end=data_end,
            label="碎片拼图",
        ),
    )


def repack_stock_composition(
    rom_data: bytes | bytearray,
    unit_id: int,
    *,
    body_script: bytes | None = None,
    fragment_script: bytes | None = None,
    body_unit_ids: Sequence[int] | None = None,
    fragment_unit_ids: Sequence[int] | None = None,
) -> bytes:
    """Repack native scripts, optionally preserving an edited alias group."""

    if not 1 <= unit_id <= UNIT_ID_COUNT:
        raise IndexError("请选择有效机体。")
    source = bytes(rom_data)
    layout = read_stock_composition_layout(source)
    body_targets = tuple(dict.fromkeys(body_unit_ids or (unit_id,)))
    fragment_targets = tuple(dict.fromkeys(fragment_unit_ids or (unit_id,)))
    for target in (*body_targets, *fragment_targets):
        if not 1 <= target <= UNIT_ID_COUNT:
            raise IndexError("请选择有效机体。")
    body_records = list(layout.body_scripts)
    fragment_records = list(layout.fragment_scripts)
    if body_script is not None:
        for target in body_targets:
            body_records[target - 1] = bytes(body_script)
    if fragment_script is not None:
        for target in fragment_targets:
            fragment_records[target - 1] = bytes(fragment_script)
    for label, records in (("主体拼图", body_records), ("碎片拼图", fragment_records)):
        if any(not record or record[-1] != 0xFF for record in records):
            raise ValueError(f"{label}记录必须以 $FF 结束。")

    image = bytearray(_pair_slice(source, SOURCE_COMPOSITION_PAIR))

    def pack_family(
        records: list[bytes],
        old_pointers: tuple[int, ...],
        changed: bool,
        changed_ids: tuple[int, ...],
        table: int,
        cursor: int,
    ) -> int:
        pointers = [0] * 0x100
        packed_by_key: dict[tuple[str, int], int] = {}
        changed_id_set = set(changed_ids)
        changed_key = min(changed_ids)
        for record_id, record in enumerate(records, 1):
            key = (
                ("changed", changed_key)
                if changed and record_id in changed_id_set
                else ("source", old_pointers[record_id])
            )
            pointer = packed_by_key.get(key)
            if pointer is None:
                pointer = cursor
                packed_by_key[key] = pointer
                end = cursor + len(record)
                if end > 0xC000:
                    raise ValueError(
                        "原生机体拼图池容量不足；请缩短主体或碎片指令。"
                    )
                image[_cpu_offset(cursor):_cpu_offset(end)] = record
                cursor = end
            pointers[record_id] = pointer
        struct.pack_into("<256H", image, _cpu_offset(table), *pointers)
        return cursor

    body_changed = body_script is not None and any(
        body_script != layout.body_scripts[target - 1] for target in body_targets
    )
    fragment_changed = (
        fragment_script is not None
        and any(
            fragment_script != layout.fragment_scripts[target - 1]
            for target in fragment_targets
        )
    )
    cursor = pack_family(
        body_records,
        layout.body_pointers,
        body_changed,
        body_targets,
        layout.body_table,
        layout.body_table + 0x200,
    )
    fragment_table = cursor
    fragment_data = fragment_table + 0x200
    if fragment_data > 0xC000:
        raise ValueError("原生机体拼图池没有空间容纳碎片指针表。")
    cursor = pack_family(
        fragment_records,
        layout.fragment_pointers,
        fragment_changed,
        fragment_targets,
        fragment_table,
        fragment_data,
    )
    struct.pack_into("<3H", image, 0, layout.body_table, fragment_table, cursor)
    return bytes(image)


def extract_unit_expansion_records(
    rom_data: bytes | bytearray,
    *,
    name_spans: tuple[tuple[int, int], ...] = (
        (NAME_OLD_DATA_START, NAME_OLD_DATA_END),
    ),
    attributes_override: tuple[bytes, ...] | None = None,
    names_override: tuple[bytes, ...] | None = None,
) -> UnitExpansionRecords:
    """Extract all five unit resource families from the verified stock pairs."""

    source = bytes(rom_data)
    _validate_rom(source)
    core = _pair_slice(source, SOURCE_CORE_PAIR)
    configuration = _pair_slice(source, SOURCE_CONFIGURATION_PAIR)
    attribute_pointers = (
        _read_pointers(core, ATTRIBUTE_TABLE)
        if attributes_override is None
        else ()
    )
    name_pointers = _read_pointers(core, NAME_TABLE) if names_override is None else ()
    configuration_table = source_configuration_table(source)
    configuration_pointers = _read_pointers(configuration, configuration_table)
    composition_layout = read_stock_composition_layout(source)

    return UnitExpansionRecords(
        attributes=(
            _read_fixed_records(
                core,
                attribute_pointers,
                UNIT_RECORD_SIZE,
                lower=ATTRIBUTE_OLD_DATA_START,
                upper=ATTRIBUTE_OLD_DATA_END,
                label="机体属性",
            )
            if attributes_override is None
            else attributes_override
        ),
        names=(
            _read_terminated_names(core, name_pointers, spans=name_spans)
            if names_override is None
            else names_override
        ),
        # Several small-unit records are physically nine bytes, but verified
        # callers read offsets 1..9 unconditionally.  Capture ten observable
        # bytes per ID so relocation cannot change that trailing read.
        configurations=_read_fixed_records_from_spans(
            configuration,
            configuration_pointers,
            CONFIGURATION_RECORD_SIZE,
            spans=(
                (configuration_table + 0x200, CONFIGURATION_CAVE_START),
                (CONFIGURATION_CAVE_START, CONFIGURATION_CAVE_END),
            ),
            label="战斗外观",
        ),
        body_scripts=composition_layout.body_scripts,
        fragment_scripts=composition_layout.fragment_scripts,
    )


def _validate_pairs(
    bank_pairs: Sequence[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    pairs = tuple((int(first), int(second)) for first, second in bank_pairs)
    if len(pairs) not in SUPPORTED_PAIR_COUNTS:
        raise ValueError(
            "机体扩展只支持 48/64/80 KiB（3/4/5 对 PRG Bank）；"
            "更大配额没有可安全绑定的资源选择器。"
        )
    flattened = tuple(bank for pair in pairs for bank in pair)
    if len(set(flattened)) != len(flattened):
        raise ValueError("机体扩展 Bank 对相互重叠。")
    for first, second in pairs:
        if second != first + 1:
            raise ValueError(
                f"Bank ${first:02X}/${second:02X} 不连续；"
                "不能把 $60 和 $65 当成一对。"
            )
        if first not in MANAGED_EXPANSION_BANKS or second not in MANAGED_EXPANSION_BANKS:
            raise ValueError(
                f"Bank ${first:02X}/${second:02X} 不在 464 KiB 可用资源区。"
            )
    return pairs


def _clear_spans(image: bytearray, spans: Sequence[tuple[int, int]]) -> None:
    for start, end in spans:
        if not 0x8000 <= start <= end <= 0xC000:
            raise ValueError("托管池超出 16 KiB CPU 窗口。")
        image[_cpu_offset(start) : _cpu_offset(end)] = bytes(end - start)


def _write_pointer_table(
    image: bytearray,
    table_address: int,
    pointers: Sequence[int],
) -> None:
    if len(pointers) != 0x100:
        raise ValueError("指针表必须包含 256 项。")
    start = _cpu_offset(table_address)
    image[start : start + 0x200] = struct.pack("<256H", *pointers)


def _pack_records_in_spans(
    image: bytearray,
    records: Sequence[bytes],
    spans: Sequence[tuple[int, int]],
    *,
    label: str,
) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
    pointers = [0]
    used_spans: list[tuple[int, int]] = []
    span_index = 0
    cursor = spans[0][0] if spans else 0
    for record_id, record in enumerate(records, 1):
        payload = bytes(record)
        while span_index < len(spans) and cursor + len(payload) > spans[span_index][1]:
            span_index += 1
            if span_index < len(spans):
                cursor = spans[span_index][0]
        if span_index >= len(spans):
            capacity = sum(end - start for start, end in spans)
            required = sum(len(value) for value in records)
            raise ValueError(
                f"{label}池容量不足：需要 {required} 字节，"
                f"可用 {capacity} 字节。"
            )
        start = cursor
        end = start + len(payload)
        image[_cpu_offset(start) : _cpu_offset(end)] = payload
        pointers.append(start)
        if used_spans and used_spans[-1][1] == start:
            used_spans[-1] = (used_spans[-1][0], end)
        else:
            used_spans.append((start, end))
        cursor = end
    return tuple(pointers), tuple(used_spans)


def _resource_layout(
    *,
    selector: int,
    pair_start: int,
    directory_index: int,
    pointer_table: int,
    pointers: tuple[int, ...],
    records: Sequence[bytes],
    stored_records: Sequence[bytes] | None = None,
    data_spans: tuple[tuple[int, int], ...],
    pool_capacity: int,
) -> ResourceLayout:
    storage = records if stored_records is None else stored_records
    return ResourceLayout(
        selector=selector,
        pair_start=pair_start,
        directory_index=directory_index,
        pointer_table=pointer_table,
        pointers=pointers,
        record_sizes=(0, *(len(record) for record in records)),
        data_spans=data_spans,
        used_bytes=sum(len(record) for record in storage),
        pool_capacity=pool_capacity,
    )


def _descriptor_patch(
    rom_data: bytes,
    selector: int,
    pair_start: int,
    directory_index: int,
) -> DescriptorPatch:
    offset = RESOURCE_DESCRIPTOR_TABLE_OFFSET + selector * 2
    before = bytes(rom_data[offset : offset + 2])
    if len(before) != 2:
        raise ValueError("活动资源描述符表不完整。")
    return DescriptorPatch(
        selector,
        offset,
        before,
        bytes((0xF0 | directory_index, pair_start)),
        pair_start,
        directory_index,
    )


def _pack_single_resource_pair(
    records: Sequence[bytes],
    *,
    directory_index: int,
    label: str,
) -> tuple[bytes, tuple[int, ...], tuple[tuple[int, int], ...]]:
    """Pack one selector into a data-only 16 KiB runtime pair."""

    if not 0 <= directory_index <= 7:
        raise ValueError("资源目录索引必须在 $0—$7 之间。")
    image = bytearray(PAIR_SIZE)
    struct.pack_into(
        "<H",
        image,
        directory_index * 2,
        SINGLE_RESOURCE_TABLE,
    )
    pointers, used_spans = _pack_records_in_spans(
        image,
        records,
        ((SINGLE_RESOURCE_DATA_START, 0xC000),),
        label=label,
    )
    _write_pointer_table(image, SINGLE_RESOURCE_TABLE, pointers)
    return bytes(image), pointers, used_spans


def pack_standalone_unit_names(
    records: Sequence[bytes],
) -> tuple[bytes, tuple[int, ...], tuple[tuple[int, int], ...]]:
    """Pack 255 names with the reference editor's verified growth budget."""

    if len(records) != UNIT_ID_COUNT:
        raise ValueError("独立机体名称池必须包含 255 条逻辑名称。")
    image = bytearray(PAIR_SIZE)
    image[: len(STANDALONE_UNIT_NAME_MAGIC)] = STANDALONE_UNIT_NAME_MAGIC
    required = sum(len(record) for record in records)
    capacity = required + LEGACY_UNIT_NAME_GROWTH_BUDGET
    maximum = 0xC000 - STANDALONE_UNIT_NAME_DATA_START
    if capacity > maximum:
        raise ValueError(
            f"机体名称基线共需 {required} 字节，无法再保留旧修改器的 "
            f"{LEGACY_UNIT_NAME_GROWTH_BUDGET} 字节增长余量。"
        )
    struct.pack_into("<H", image, STANDALONE_UNIT_NAME_CAPACITY_OFFSET, capacity)
    struct.pack_into("<H", image, 6 * 2, SINGLE_RESOURCE_TABLE)
    pointers, used_spans = _pack_records_in_spans(
        image,
        records,
        ((
            STANDALONE_UNIT_NAME_DATA_START,
            STANDALONE_UNIT_NAME_DATA_START + capacity,
        ),),
        label="机体名称",
    )
    _write_pointer_table(image, SINGLE_RESOURCE_TABLE, pointers)
    _write_pointer_table(
        image, STANDALONE_UNIT_NAME_CANONICAL_TABLE, pointers
    )
    return bytes(image), pointers, used_spans


def standalone_unit_name_bank(rom_data: bytes | bytearray) -> int | None:
    """Return the verified standalone-name Bank pair start, if installed."""

    source = bytes(rom_data)
    descriptor = source[
        RESOURCE_DESCRIPTOR_TABLE_OFFSET + UNIT_NAME_SELECTOR * 2 :
        RESOURCE_DESCRIPTOR_TABLE_OFFSET + UNIT_NAME_SELECTOR * 2 + 2
    ]
    if len(descriptor) != 2 or descriptor[0] != 0xF6:
        return None
    bank = descriptor[1]
    if bank not in MANAGED_EXPANSION_BANKS or bank + 1 not in MANAGED_EXPANSION_BANKS:
        return None
    start = INES_HEADER_SIZE + bank * PRG_BANK_SIZE
    image = source[start : start + PAIR_SIZE]
    if len(image) != PAIR_SIZE:
        return None
    magic = image[: len(STANDALONE_UNIT_NAME_MAGIC)]
    if magic not in (
        STANDALONE_UNIT_NAME_MAGIC,
        STANDALONE_UNIT_NAME_MAGIC_V1,
    ):
        return None
    if magic == STANDALONE_UNIT_NAME_MAGIC:
        capacity = struct.unpack_from(
            "<H", image, STANDALONE_UNIT_NAME_CAPACITY_OFFSET
        )[0]
        if not 1 <= capacity <= 0xC000 - STANDALONE_UNIT_NAME_DATA_START:
            return None
    if struct.unpack_from("<H", image, 6 * 2)[0] != SINGLE_RESOURCE_TABLE:
        return None
    return bank


def standalone_unit_name_capacity(
    rom_data: bytes | bytearray,
    bank: int | None = None,
) -> int | None:
    """Return the stored name-body capacity; V1 images keep their full span."""

    source = bytes(rom_data)
    resolved = standalone_unit_name_bank(source) if bank is None else bank
    if resolved is None:
        return None
    start = INES_HEADER_SIZE + resolved * PRG_BANK_SIZE
    image = source[start : start + PAIR_SIZE]
    magic = image[: len(STANDALONE_UNIT_NAME_MAGIC)]
    if magic == STANDALONE_UNIT_NAME_MAGIC_V1:
        return 0xC000 - STANDALONE_UNIT_NAME_DATA_START
    if magic != STANDALONE_UNIT_NAME_MAGIC:
        return None
    capacity = struct.unpack_from(
        "<H", image, STANDALONE_UNIT_NAME_CAPACITY_OFFSET
    )[0]
    maximum = 0xC000 - STANDALONE_UNIT_NAME_DATA_START
    if not 1 <= capacity <= maximum:
        return None
    return capacity


def pack_standalone_unit_attributes(
    rom_data: bytes | bytearray,
    records: Sequence[bytes],
) -> tuple[bytes, tuple[int, ...]]:
    """Mirror the core pair with one independent 16-byte record per ID."""

    if len(records) != UNIT_ID_COUNT:
        raise ValueError("独立机体属性池必须包含 255 条逻辑记录。")
    if any(len(record) != UNIT_RECORD_SIZE for record in records):
        raise ValueError("每条机体属性必须正好是 16 字节。")
    source = bytes(rom_data)
    _validate_rom(source)
    image = bytearray(_pair_slice(source, SOURCE_CORE_PAIR))
    if struct.unpack_from("<H", image, 2 * 2)[0] != ATTRIBUTE_TABLE:
        raise ValueError("原 Bank $24/$25 的属性目录已变化。")
    data_end = (
        STANDALONE_UNIT_ATTRIBUTE_DATA_START
        + UNIT_ID_COUNT * UNIT_RECORD_SIZE
    )
    if data_end > CORE_CAVE_END:
        raise ValueError("独立机体属性记录无法放入已验证镜像空间。")
    image[
        _cpu_offset(CORE_CAVE_START) : _cpu_offset(CORE_CAVE_END)
    ] = bytes(CORE_CAVE_END - CORE_CAVE_START)
    magic_offset = _cpu_offset(STANDALONE_UNIT_ATTRIBUTE_MAGIC_OFFSET)
    image[
        magic_offset : magic_offset + len(STANDALONE_UNIT_ATTRIBUTE_MAGIC)
    ] = STANDALONE_UNIT_ATTRIBUTE_MAGIC
    pointers = (0,) + tuple(
        STANDALONE_UNIT_ATTRIBUTE_DATA_START + index * UNIT_RECORD_SIZE
        for index in range(UNIT_ID_COUNT)
    )
    data_offset = _cpu_offset(STANDALONE_UNIT_ATTRIBUTE_DATA_START)
    image[data_offset : data_offset + UNIT_ID_COUNT * UNIT_RECORD_SIZE] = b"".join(
        records
    )
    _write_pointer_table(image, ATTRIBUTE_TABLE, pointers)
    return bytes(image), pointers


def standalone_unit_attribute_bank(
    rom_data: bytes | bytearray,
) -> int | None:
    """Return the verified attribute-only mirror pair start, if installed."""

    source = bytes(rom_data)
    descriptor = source[
        RESOURCE_DESCRIPTOR_TABLE_OFFSET + UNIT_ATTRIBUTE_SELECTOR * 2 :
        RESOURCE_DESCRIPTOR_TABLE_OFFSET + UNIT_ATTRIBUTE_SELECTOR * 2 + 2
    ]
    if len(descriptor) != 2 or descriptor[0] != 0xF2:
        return None
    bank = descriptor[1]
    if bank not in MANAGED_EXPANSION_BANKS or bank + 1 not in MANAGED_EXPANSION_BANKS:
        return None
    start = INES_HEADER_SIZE + bank * PRG_BANK_SIZE
    image = source[start : start + PAIR_SIZE]
    if len(image) != PAIR_SIZE:
        return None
    magic_offset = _cpu_offset(STANDALONE_UNIT_ATTRIBUTE_MAGIC_OFFSET)
    if image[
        magic_offset : magic_offset + len(STANDALONE_UNIT_ATTRIBUTE_MAGIC)
    ] != STANDALONE_UNIT_ATTRIBUTE_MAGIC:
        return None
    if struct.unpack_from("<H", image, 2 * 2)[0] != ATTRIBUTE_TABLE:
        return None
    expected = tuple(
        STANDALONE_UNIT_ATTRIBUTE_DATA_START + index * UNIT_RECORD_SIZE
        for index in range(UNIT_ID_COUNT)
    )
    raw = image[_cpu_offset(ATTRIBUTE_TABLE) : _cpu_offset(ATTRIBUTE_TABLE) + 0x200]
    if len(raw) != 0x200:
        return None
    pointers = struct.unpack("<256H", raw)
    if pointers[0] != 0 or pointers[1:] != expected:
        return None
    return bank


def pack_unit_expansion(
    rom_data: bytes | bytearray,
    bank_pairs: Sequence[tuple[int, int]],
    *,
    records: UnitExpansionRecords | None = None,
    name_source_ids: Sequence[int] | None = None,
) -> PackedUnitExpansion:
    """Build the safe 48/64/80 KiB machine-resource relocation.

    Pair 0 mirrors $24/$25 so selector $71 can return into the mirrored loader.
    Pair 1 mirrors $04/$05 for the same reason at selector $74.  With 48 KiB,
    pair 2 combines body and fragment scripts.  At 64 KiB those scripts get
    one pair each; at 80 KiB pair 4 also becomes a dedicated name pool.  Name
    rendering enters through fixed routine $FC13, which saves and restores the
    prior $8000/$A000 mapping around its resource lookup, so a data-only name
    pair does not have the return-PC hazard of selectors $71 and $74.
    """

    source = bytes(rom_data)
    _validate_rom(source)
    pairs = _validate_pairs(bank_pairs)
    values = extract_unit_expansion_records(source) if records is None else records
    name_sources = (
        tuple(range(1, UNIT_ID_COUNT + 1))
        if name_source_ids is None
        else tuple(int(source_id) for source_id in name_source_ids)
    )
    if len(name_sources) != UNIT_ID_COUNT or any(
        not 1 <= source_id <= UNIT_ID_COUNT for source_id in name_sources
    ):
        raise ValueError("机体名称来源表必须包含 255 个有效 ID。")

    core_bank = pairs[0][0]
    configuration_bank = pairs[1][0]
    body_bank = pairs[2][0]
    fragment_bank = pairs[3][0] if len(pairs) >= 4 else body_bank
    external_name_bank = pairs[4][0] if len(pairs) >= 5 else None

    core = bytearray(_pair_slice(source, SOURCE_CORE_PAIR))
    if struct.unpack_from("<H", core, 2 * 2)[0] != ATTRIBUTE_TABLE:
        raise ValueError("原 Bank $24/$25 的属性目录已变化。")
    if struct.unpack_from("<H", core, 6 * 2)[0] != NAME_TABLE:
        raise ValueError("原 Bank $24/$25 的名称目录已变化。")
    if any(
        core[_cpu_offset(CORE_CAVE_START) : _cpu_offset(CORE_CAVE_END)]
    ):
        raise ValueError("原 Bank $24/$25 的已验证空洞不再为空。")
    core_reclaim_spans = (
        (ATTRIBUTE_OLD_DATA_START, ATTRIBUTE_OLD_DATA_END),
        (NAME_OLD_DATA_START, NAME_OLD_DATA_END),
        (CORE_CAVE_START, CORE_CAVE_END),
    )
    if external_name_bank is None:
        _clear_spans(core, core_reclaim_spans)

    attribute_start = CORE_CAVE_START
    attribute_end = attribute_start + sum(len(item) for item in values.attributes)
    if attribute_end > CORE_CAVE_END:
        raise ValueError("机体属性无法放入核心镜像空洞。")
    attribute_pointers = (0,) + tuple(
        attribute_start + index * UNIT_RECORD_SIZE
        for index in range(UNIT_ID_COUNT)
    )
    core[_cpu_offset(attribute_start) : _cpu_offset(attribute_end)] = b"".join(
        values.attributes
    )
    _write_pointer_table(core, ATTRIBUTE_TABLE, attribute_pointers)

    name_pool_spans = (
        (attribute_end, CORE_CAVE_END),
        (ATTRIBUTE_OLD_DATA_START, ATTRIBUTE_OLD_DATA_END),
        (NAME_OLD_DATA_START, NAME_OLD_DATA_END),
    )
    # Retain one canonical pointer for every logical source ID.  Stock aliases
    # sometimes expose a pointer-bounded view containing later terminated
    # names as well; trim each view to its own first complete record before
    # packing.  This preserves old-editor source-ID semantics without wasting
    # capacity on duplicated tail records.
    canonical_name_records = tuple(
        _standalone_name_record(record) for record in values.names
    )
    name_pointer_table = NAME_TABLE
    name_directory_index = 6
    if external_name_bank is None:
        packed_name_pointers, name_used_spans = _pack_records_in_spans(
            core,
            canonical_name_records,
            name_pool_spans,
            label="机体名称",
        )
        name_capacity = sum(end - start for start, end in name_pool_spans)
        name_image = None
    else:
        name_image, packed_name_pointers, name_used_spans = _pack_single_resource_pair(
            canonical_name_records,
            directory_index=name_directory_index,
            label="机体名称",
        )
        name_pointer_table = SINGLE_RESOURCE_TABLE
        name_capacity = 0xC000 - SINGLE_RESOURCE_DATA_START
    canonical_name_pointers = packed_name_pointers
    name_pointers = (0,) + tuple(
        canonical_name_pointers[source_id] for source_id in name_sources
    )
    active_name_records = tuple(
        canonical_name_records[source_id - 1] for source_id in name_sources
    )
    if name_image is None:
        _write_pointer_table(core, name_pointer_table, name_pointers)
    else:
        mutable_name_image = bytearray(name_image)
        _write_pointer_table(mutable_name_image, name_pointer_table, name_pointers)
        name_image = bytes(mutable_name_image)

    configuration = bytearray(_pair_slice(source, SOURCE_CONFIGURATION_PAIR))
    source_configuration_table_address = source_configuration_table(source)
    # The editor may safely relocate a stock record here when changing a
    # small unit into a large unit (nine observable bytes become ten).  Accept
    # only bytes covered by active configuration pointers; unrelated cave
    # content remains a hard stop.
    source_configuration_pointers = _read_pointers(
        configuration, source_configuration_table_address
    )
    claimed_cave_offsets: set[int] = set()
    for pointer in source_configuration_pointers[1:]:
        if CONFIGURATION_CAVE_START <= pointer <= CONFIGURATION_CAVE_END - 10:
            start = _cpu_offset(pointer)
            claimed_cave_offsets.update(range(start, start + 10))
    cave_start = _cpu_offset(CONFIGURATION_CAVE_START)
    cave_end = _cpu_offset(CONFIGURATION_CAVE_END)
    if any(value and index not in claimed_cave_offsets
           for index, value in enumerate(configuration)
           if cave_start <= index < cave_end):
        raise ValueError("原 Bank $04/$05 的已验证空洞含有未知数据。")
    configuration_pool_spans = (
        (CONFIGURATION_OLD_DATA_START, CONFIGURATION_OLD_DATA_END),
        (CONFIGURATION_CAVE_START, CONFIGURATION_CAVE_END),
    )
    _clear_spans(configuration, configuration_pool_spans)
    configuration_pointers, configuration_used_spans = _pack_records_in_spans(
        configuration,
        values.configurations,
        ((CONFIGURATION_CAVE_START, CONFIGURATION_CAVE_END),),
        label="战斗外观",
    )
    _write_pointer_table(configuration, CONFIGURATION_TABLE, configuration_pointers)

    if fragment_bank == body_bank:
        composition = bytearray(PAIR_SIZE)
        struct.pack_into("<H", composition, 0, PACKED_BODY_TABLE)
        struct.pack_into("<H", composition, 2, PACKED_FRAGMENT_TABLE)
        body_pointers, body_used_spans = _pack_records_in_spans(
            composition,
            values.body_scripts,
            ((PACKED_COMPOSITION_DATA_START, 0xC000),),
            label="主体拼图",
        )
        body_end = body_used_spans[-1][1]
        fragment_pointers, fragment_used_spans = _pack_records_in_spans(
            composition,
            values.fragment_scripts,
            ((body_end, 0xC000),),
            label="碎片拼图",
        )
        _write_pointer_table(composition, PACKED_BODY_TABLE, body_pointers)
        _write_pointer_table(composition, PACKED_FRAGMENT_TABLE, fragment_pointers)
        body_image = bytes(composition)
        fragment_image = None
        body_pointer_table = PACKED_BODY_TABLE
        fragment_pointer_table = PACKED_FRAGMENT_TABLE
        body_directory_index = 0
        fragment_directory_index = 1
        body_capacity = 0xC000 - PACKED_COMPOSITION_DATA_START
        fragment_capacity = body_capacity
        composition_capacity = body_capacity
    else:
        body_directory_index = 0
        fragment_directory_index = 1
        body_image, body_pointers, body_used_spans = _pack_single_resource_pair(
            values.body_scripts,
            directory_index=body_directory_index,
            label="主体拼图",
        )
        fragment_image, fragment_pointers, fragment_used_spans = (
            _pack_single_resource_pair(
                values.fragment_scripts,
                directory_index=fragment_directory_index,
                label="碎片拼图",
            )
        )
        body_pointer_table = SINGLE_RESOURCE_TABLE
        fragment_pointer_table = SINGLE_RESOURCE_TABLE
        body_capacity = 0xC000 - SINGLE_RESOURCE_DATA_START
        fragment_capacity = body_capacity
        composition_capacity = body_capacity + fragment_capacity

    configuration_capacity = sum(
        end - start for start, end in configuration_pool_spans
    )
    composition_used = sum(len(item) for item in values.body_scripts) + sum(
        len(item) for item in values.fragment_scripts
    )

    pair_images_list = [
        BankPairImage("unit-core-mirror", core_bank, bytes(core)),
        BankPairImage(
            "unit-configuration-mirror",
            configuration_bank,
            bytes(configuration),
        ),
        BankPairImage(
            "unit-composition" if fragment_image is None else "unit-body",
            body_bank,
            body_image,
        ),
    ]
    if fragment_image is not None:
        pair_images_list.append(
            BankPairImage("unit-fragment", fragment_bank, fragment_image)
        )
    if name_image is not None:
        assert external_name_bank is not None
        pair_images_list.append(
            BankPairImage("unit-name", external_name_bank, name_image)
        )
    pair_images = tuple(pair_images_list)
    resources = (
        _resource_layout(
            selector=UNIT_ATTRIBUTE_SELECTOR,
            pair_start=core_bank,
            directory_index=2,
            pointer_table=ATTRIBUTE_TABLE,
            pointers=attribute_pointers,
            records=values.attributes,
            data_spans=((attribute_start, attribute_end),),
            pool_capacity=attribute_end - attribute_start,
        ),
        _resource_layout(
            selector=UNIT_NAME_SELECTOR,
            pair_start=(
                core_bank if external_name_bank is None else external_name_bank
            ),
            directory_index=name_directory_index,
            pointer_table=name_pointer_table,
            pointers=name_pointers,
            records=active_name_records,
            stored_records=values.names,
            data_spans=name_used_spans,
            pool_capacity=name_capacity,
        ),
        _resource_layout(
            selector=UNIT_CONFIGURATION_SELECTOR,
            pair_start=configuration_bank,
            directory_index=6,
            pointer_table=CONFIGURATION_TABLE,
            pointers=configuration_pointers,
            records=values.configurations,
            data_spans=configuration_used_spans,
            pool_capacity=configuration_capacity,
        ),
        _resource_layout(
            selector=UNIT_BODY_SELECTOR,
            pair_start=body_bank,
            directory_index=body_directory_index,
            pointer_table=body_pointer_table,
            pointers=body_pointers,
            records=values.body_scripts,
            data_spans=body_used_spans,
            pool_capacity=body_capacity,
        ),
        _resource_layout(
            selector=UNIT_FRAGMENT_SELECTOR,
            pair_start=fragment_bank,
            directory_index=fragment_directory_index,
            pointer_table=fragment_pointer_table,
            pointers=fragment_pointers,
            records=values.fragment_scripts,
            data_spans=fragment_used_spans,
            pool_capacity=fragment_capacity,
        ),
    )
    descriptor_patches = tuple(
        _descriptor_patch(source, selector, pair_start, directory_index)
        for selector, pair_start, directory_index in (
            (
                UNIT_NAME_SELECTOR,
                core_bank if external_name_bank is None else external_name_bank,
                name_directory_index,
            ),
            (UNIT_BODY_SELECTOR, body_bank, body_directory_index),
            (UNIT_FRAGMENT_SELECTOR, fragment_bank, fragment_directory_index),
            (UNIT_ATTRIBUTE_SELECTOR, core_bank, 2),
            (UNIT_CONFIGURATION_SELECTOR, configuration_bank, 6),
        )
    )
    return PackedUnitExpansion(
        pair_images,
        descriptor_patches,
        resources,
        composition_capacity,
        composition_used,
        canonical_name_pointers,
    )


def _require_directory_pointer(
    image: bytes,
    directory_index: int,
    expected_pointer: int,
    *,
    label: str,
) -> None:
    """Validate one runtime resource-directory entry in a mapped pair."""

    if not 0 <= directory_index <= 7:
        raise ValueError(f"{label}目录索引越界。")
    actual_pointer = struct.unpack_from("<H", image, directory_index * 2)[0]
    if actual_pointer != expected_pointer:
        raise ValueError(
            f"{label}目录 ${directory_index:X} 应指向 "
            f"${expected_pointer:04X}，实际为 ${actual_pointer:04X}。"
        )


def _read_packed_fixed_records(
    image: bytes,
    pointers: tuple[int, ...],
    size: int,
    *,
    data_start: int,
    data_end: int,
    label: str,
) -> tuple[bytes, ...]:
    """Decode a fixed-size relocated table and reject aliases or gaps."""

    for record_id, pointer in enumerate(pointers[1:], 1):
        expected = data_start + (record_id - 1) * size
        if pointer != expected:
            raise ValueError(
                f"{label} ${record_id:02X} 指针应为 ${expected:04X}，"
                f"实际为 ${pointer:04X}。"
            )
    return _read_fixed_records(
        image,
        pointers,
        size,
        lower=data_start,
        upper=data_end,
        label=label,
    )


def _read_packed_names(
    image: bytes,
    pointers: tuple[int, ...],
    canonical_pointers: tuple[int, ...],
    canonical_sizes: tuple[int, ...],
    *,
    spans: tuple[tuple[int, int], ...],
) -> tuple[bytes, ...]:
    """Decode active name references against all retained canonical records.

    The editor currently changes unit names by reference.  The source name
    table is deliberately retained so a directly reopened ROM can reconstruct
    the 255 canonical reset targets.  Use those record lengths to validate
    even canonical names that are not currently referenced by any unit.
    """

    records_by_pointer: dict[int, bytes] = {}
    for record_id, (pointer, size) in enumerate(
        zip(canonical_pointers[1:], canonical_sizes),
        1,
    ):
        containing_span = next(
            (
                (span_start, span_end)
                for span_start, span_end in spans
                if span_start <= pointer and pointer + size <= span_end
            ),
            None,
        )
        if containing_span is None:
            raise ValueError(
                f"机体名称 ${record_id:02X} 记录越过已验证数据池边界。"
            )
        start = _cpu_offset(pointer)
        value = bytes(image[start : start + size])
        if not value or value.find(b"\xFF") != len(value) - 1:
            raise ValueError(
                f"机体名称 ${record_id:02X} 未在记录边界以 $FF 结束。"
            )
        records_by_pointer[pointer] = value

    records: list[bytes] = []
    for record_id, pointer in enumerate(pointers[1:], 1):
        try:
            records.append(records_by_pointer[pointer])
        except KeyError as error:
            raise ValueError(
                f"机体名称 ${record_id:02X} 指针 ${pointer:04X} "
                "未指向可还原的规范名称记录。"
            ) from error
    return tuple(records)


def _read_packed_terminated_scripts(
    image: bytes,
    pointers: tuple[int, ...],
    *,
    data_start: int,
    data_end: int,
    label: str,
) -> tuple[bytes, ...]:
    """Decode sequential relocated scripts and validate every boundary."""

    active = pointers[1:]
    if not active or active[0] != data_start:
        actual = active[0] if active else 0
        raise ValueError(
            f"{label}首记录应从 ${data_start:04X} 开始，"
            f"实际为 ${actual:04X}。"
        )
    if not data_start < data_end <= 0xC000:
        raise ValueError(f"{label}数据池边界无效。")
    for record_id, pointer in enumerate(active, 1):
        if not data_start <= pointer < data_end:
            raise ValueError(
                f"{label} ${record_id:02X} 指针 ${pointer:04X} "
                "超出已验证数据池。"
            )
    for record_id, (left, right) in enumerate(zip(active, active[1:]), 1):
        if right <= left:
            raise ValueError(
                f"{label} ${record_id + 1:02X} 指针未严格递增。"
            )

    last_start = _cpu_offset(active[-1])
    last_end = _cpu_offset(data_end)
    # Relocated data-only pairs are zero-initialized.  Trimming only the final
    # zero fill recovers the otherwise unrecorded end of ID $FF.
    while last_end > last_start and image[last_end - 1] == 0:
        last_end -= 1
    boundaries = (*active[1:], 0x8000 + last_end)

    records: list[bytes] = []
    for record_id, (pointer, end) in enumerate(zip(active, boundaries), 1):
        if not pointer < end <= data_end:
            raise ValueError(f"{label} ${record_id:02X} 记录边界无效。")
        value = bytes(image[_cpu_offset(pointer) : _cpu_offset(end)])
        if not value or value[-1] != 0xFF:
            raise ValueError(
                f"{label} ${record_id:02X} 记录边界未以 $FF 结束。"
            )
        records.append(value)
    return tuple(records)


def validate_unit_expansion_payload(
    rom_data: bytes | bytearray,
    bank_pairs: Sequence[tuple[int, int]],
) -> UnitExpansionRecords:
    """Validate and decode a linked 48/64/80 KiB unit payload.

    This is intentionally independent of :func:`pack_unit_expansion`: it reads
    the bytes that will be consumed by the stock resolver, including each
    active directory entry and all 256 pointer-table entries.  Returning the
    decoded records also makes round-trip tests and future diagnostics cheap.
    """

    source = bytes(rom_data)
    _validate_rom(source)
    pairs = _validate_pairs(bank_pairs)

    core_bank = pairs[0][0]
    configuration_bank = pairs[1][0]
    body_bank = pairs[2][0]
    fragment_bank = pairs[3][0] if len(pairs) >= 4 else body_bank
    external_name_bank = pairs[4][0] if len(pairs) >= 5 else None

    core = _pair_slice(source, core_bank)
    configuration = _pair_slice(source, configuration_bank)
    body = _pair_slice(source, body_bank)
    fragment = body if fragment_bank == body_bank else _pair_slice(source, fragment_bank)

    _require_directory_pointer(core, 2, ATTRIBUTE_TABLE, label="机体属性")
    _require_directory_pointer(
        configuration,
        6,
        CONFIGURATION_TABLE,
        label="战斗外观",
    )

    attribute_pointers = _read_pointers(core, ATTRIBUTE_TABLE)
    attribute_end = CORE_CAVE_START + UNIT_ID_COUNT * UNIT_RECORD_SIZE
    attributes = _read_packed_fixed_records(
        core,
        attribute_pointers,
        UNIT_RECORD_SIZE,
        data_start=CORE_CAVE_START,
        data_end=attribute_end,
        label="机体属性",
    )

    if external_name_bank is None:
        name = core
        name_table = NAME_TABLE
        name_spans = (
            (attribute_end, CORE_CAVE_END),
            (ATTRIBUTE_OLD_DATA_START, ATTRIBUTE_OLD_DATA_END),
            (NAME_OLD_DATA_START, NAME_OLD_DATA_END),
        )
        _require_directory_pointer(name, 6, name_table, label="机体名称")
    else:
        name = _pair_slice(source, external_name_bank)
        name_table = SINGLE_RESOURCE_TABLE
        name_spans = ((SINGLE_RESOURCE_DATA_START, 0xC000),)
        _require_directory_pointer(name, 6, name_table, label="机体名称")
    name_pointers = _read_pointers(name, name_table)
    # Names can be edited to a different encoded length after relocation.
    # Validate every runtime-visible pointer and its terminator directly;
    # stock record lengths are not a valid boundary oracle for such outputs.
    names = _read_terminated_names(name, name_pointers, spans=name_spans)

    configuration_pointers = _read_pointers(configuration, CONFIGURATION_TABLE)
    configurations = _read_packed_fixed_records(
        configuration,
        configuration_pointers,
        CONFIGURATION_RECORD_SIZE,
        data_start=CONFIGURATION_CAVE_START,
        data_end=CONFIGURATION_CAVE_END,
        label="战斗外观",
    )

    if fragment_bank == body_bank:
        _require_directory_pointer(
            body,
            0,
            PACKED_BODY_TABLE,
            label="主体拼图",
        )
        _require_directory_pointer(
            fragment,
            1,
            PACKED_FRAGMENT_TABLE,
            label="碎片拼图",
        )
        body_pointers = _read_pointers(body, PACKED_BODY_TABLE)
        fragment_pointers = _read_pointers(fragment, PACKED_FRAGMENT_TABLE)
        fragment_start = fragment_pointers[1]
        body_scripts = _read_packed_terminated_scripts(
            body,
            body_pointers,
            data_start=PACKED_COMPOSITION_DATA_START,
            data_end=fragment_start,
            label="主体拼图",
        )
        fragment_scripts = _read_packed_terminated_scripts(
            fragment,
            fragment_pointers,
            data_start=fragment_start,
            data_end=0xC000,
            label="碎片拼图",
        )
    else:
        _require_directory_pointer(
            body,
            0,
            SINGLE_RESOURCE_TABLE,
            label="主体拼图",
        )
        _require_directory_pointer(
            fragment,
            1,
            SINGLE_RESOURCE_TABLE,
            label="碎片拼图",
        )
        body_pointers = _read_pointers(body, SINGLE_RESOURCE_TABLE)
        fragment_pointers = _read_pointers(fragment, SINGLE_RESOURCE_TABLE)
        body_scripts = _read_packed_terminated_scripts(
            body,
            body_pointers,
            data_start=SINGLE_RESOURCE_DATA_START,
            data_end=0xC000,
            label="主体拼图",
        )
        fragment_scripts = _read_packed_terminated_scripts(
            fragment,
            fragment_pointers,
            data_start=SINGLE_RESOURCE_DATA_START,
            data_end=0xC000,
            label="碎片拼图",
        )

    return UnitExpansionRecords(
        attributes=attributes,
        names=names,
        configurations=configurations,
        body_scripts=body_scripts,
        fragment_scripts=fragment_scripts,
    )

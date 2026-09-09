from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .constants import EXPECTED_BASE_SHA256, EXPECTED_MAPPER, EXPECTED_ROM_SIZE


@dataclass(frozen=True)
class StoryTextGroupSpec:
    selector: int
    prg_bank: int
    pointer_table: int
    count: int
    data_start: int
    data_end: int
    label: str
    first_pointer: int | None = None
    last_pointer_writable: bool = True

    @property
    def expected_first_pointer(self) -> int:
        return self.data_start if self.first_pointer is None else self.first_pointer


@dataclass(frozen=True)
class MapStorageRange:
    first_id: int
    end_id: int
    prg_bank: int
    window_base: int
    data_end_pointer: int

    def contains(self, map_id: int) -> bool:
        return self.first_id <= map_id < self.end_id


@dataclass(frozen=True)
class BattleMusicTrackSpec:
    command: int
    label: str

    @property
    def display(self) -> str:
        return f"${self.command:02X} · {self.label}"


@dataclass(frozen=True)
class BattleMusicSelectorSpec:
    selector: int
    label: str


@dataclass(frozen=True)
class BattleMusicSpec:
    attacker_table_offset: int
    defender_table_offset: int
    selector_count: int
    tracks: tuple[BattleMusicTrackSpec, ...]
    named_selectors: tuple[BattleMusicSelectorSpec, ...] = ()

    def selector_label(self, selector: int) -> str:
        for item in self.named_selectors:
            if item.selector == selector:
                return item.label
        return "未命名选择器"

    def track(self, command: int) -> BattleMusicTrackSpec | None:
        return next((item for item in self.tracks if item.command == command), None)


@dataclass(frozen=True)
class CustomMusicSlotSpec:
    command: int
    prg_bank: int
    label: str


@dataclass(frozen=True)
class ChapterEventSpec:
    code_prg_bank: int
    data_prg_bank: int
    pointer_tables: tuple[int, ...]
    phase_labels: tuple[str, ...]
    scenario_count: int
    data_window_base: int
    data_start: int
    data_end: int

    def __post_init__(self) -> None:
        if len(self.pointer_tables) != len(self.phase_labels):
            raise ValueError("章节事件阶段名与指针表数量不一致。")
        if not self.data_window_base <= self.data_start < self.data_end:
            raise ValueError("章节事件数据范围无效。")


@dataclass(frozen=True)
class MapTriggerSpec:
    """Per-chapter map-coordinate triggers and the managed replacement pool."""

    prg_bank: int
    window_base: int
    pointer_table: int
    scenario_count: int
    original_data_start: int
    original_data_end: int
    managed_data_start: int
    managed_data_end: int

    def __post_init__(self) -> None:
        bank_end = self.window_base + 0x2000
        ranges = (
            self.pointer_table,
            self.original_data_start,
            self.original_data_end - 1,
            self.managed_data_start,
            self.managed_data_end - 1,
        )
        if any(not self.window_base <= value < bank_end for value in ranges):
            raise ValueError("地图触发器地址超出 8 KiB PRG Bank。")
        if self.scenario_count <= 0:
            raise ValueError("地图触发器关卡数必须大于零。")
        if not self.original_data_start < self.original_data_end:
            raise ValueError("地图触发器原始数据范围无效。")
        if not self.managed_data_start < self.managed_data_end:
            raise ValueError("地图触发器托管数据范围无效。")


@dataclass(frozen=True)
class PersuasionRuleSpec:
    """Verified persuasion match records and their script pointer table."""

    table_offset: int
    script_pointer_table_offset: int
    slot_count: int
    editable_count: int

    def __post_init__(self) -> None:
        if self.table_offset < 16 or self.script_pointer_table_offset < 16:
            raise ValueError("劝降表文件偏移无效。")
        if not 0 < self.editable_count <= self.slot_count:
            raise ValueError("劝降表可编辑槽位数无效。")


@dataclass(frozen=True)
class PrgBankRegion:
    first_bank: int
    end_bank: int
    label: str

    def __post_init__(self) -> None:
        if self.first_bank < 0 or self.end_bank <= self.first_bank:
            raise ValueError("PRG Bank 区间无效。")

    @property
    def size(self) -> int:
        return (self.end_bank - self.first_bank) * 0x2000

    @property
    def display(self) -> str:
        return f"${self.first_bank:02X}—${self.end_bank - 1:02X}"


@dataclass(frozen=True)
class RomProfile:
    key: str
    label: str
    rom_size: int
    mapper: int
    reference_sha256: str
    unit_pointer_table_offset: int
    unit_count: int
    unit_data_prg_bank: int
    unit_data_window_base: int
    weapon_pointer_table_offset: int
    weapon_pointer_count: int
    weapon_count: int
    weapon_data_prg_bank: int
    weapon_data_window_base: int
    unit_weapon_table_offset: int | None
    unit_name_pointer_table_offset: int
    unit_name_count: int
    unit_name_first_pointer: int
    map_pointer_table_offset: int
    map_count: int
    map_first_pointer: int
    map_storage_ranges: tuple[MapStorageRange, ...]
    scenario_pointer_table_offset: int
    scenario_count: int
    scenario_data_prg_bank: int
    scenario_data_window_base: int
    scenario_data_end_pointer: int
    scenario_first_pointer: int
    story_text_groups: tuple[StoryTextGroupSpec, ...]
    growth_curve_max: int = 49
    uses_original_name_aliases: bool = True
    battle_music: BattleMusicSpec | None = None
    custom_music_slots: tuple[CustomMusicSlotSpec, ...] = ()
    chapter_events: ChapterEventSpec | None = None
    protected_prg_regions: tuple[PrgBankRegion, ...] = ()
    free_prg_regions: tuple[PrgBankRegion, ...] = ()
    weapon_name_pointer_table_offset: int | None = None
    weapon_name_pointer_count: int = 0
    weapon_name_first_pointer: int | None = None
    weapon_name_data_prg_bank: int | None = None
    weapon_name_data_window_base: int = 0x8000
    weapon_name_data_end_pointer: int | None = None
    character_name_pointer_table_offset: int | None = None
    character_name_count: int = 0
    character_name_first_pointer: int | None = None
    character_name_data_prg_bank: int | None = None
    character_name_data_window_base: int = 0x8000
    character_name_data_end_pointer: int | None = None
    map_triggers: MapTriggerSpec | None = None
    persuasion_rules: PersuasionRuleSpec | None = None

    def map_storage(self, map_id: int) -> MapStorageRange:
        for storage in self.map_storage_ranges:
            if storage.contains(map_id):
                return storage
        raise IndexError(f"地图 ID {map_id:02X} 没有对应的存储区。")


ORIGINAL_STORY_TEXT_GROUPS = (
    StoryTextGroupSpec(0x32, 12, 0x9245, 117, 0x932F, 0xAB65, "剧情文本 A"),
    StoryTextGroupSpec(0x33, 12, 0xAB65, 80, 0xAC05, 0xBD81, "剧情文本 B"),
    StoryTextGroupSpec(0x36, 14, 0x9402, 96, 0x94C2, 0xA55D, "剧情文本 C"),
    StoryTextGroupSpec(0x37, 14, 0xA55D, 52, 0xA5C5, 0xAAEF, "剧情文本 D"),
    StoryTextGroupSpec(0x38, 16, 0x8010, 136, 0x8120, 0xC000, "剧情文本 E"),
    StoryTextGroupSpec(0x39, 18, 0x8020, 144, 0x8140, 0xB0EE, "剧情文本 F"),
    StoryTextGroupSpec(0x3A, 20, 0x8020, 48, 0x8080, 0x8762, "剧情文本 G"),
    StoryTextGroupSpec(0x3B, 22, 0x8020, 16, 0x8040, 0x865C, "剧情文本 H"),
)


ORIGINAL_PROFILE = RomProfile(
    key="original-cn",
    label="原版中文汉化",
    rom_size=EXPECTED_ROM_SIZE,
    mapper=EXPECTED_MAPPER,
    reference_sha256=EXPECTED_BASE_SHA256,
    unit_pointer_table_offset=0xA06A,
    unit_count=0x80,
    unit_data_prg_bank=5,
    unit_data_window_base=0xA000,
    weapon_pointer_table_offset=0xB11D,
    weapon_pointer_count=0xC0,
    weapon_count=0xC0,
    weapon_data_prg_bank=5,
    weapon_data_window_base=0xA000,
    unit_weapon_table_offset=0xAF9D,
    unit_name_pointer_table_offset=0x18020,
    unit_name_count=0x100,
    unit_name_first_pointer=0x8210,
    map_pointer_table_offset=0x5AAF,
    map_count=0x1B,
    map_first_pointer=0x9AD5,
    map_storage_ranges=(MapStorageRange(0x00, 0x1B, 2, 0x8000, 0xADC2),),
    scenario_pointer_table_offset=0x7043,
    scenario_count=0x1B,
    scenario_data_prg_bank=2,
    scenario_data_window_base=0x8000,
    scenario_data_end_pointer=0xC000,
    scenario_first_pointer=0xB069,
    story_text_groups=ORIGINAL_STORY_TEXT_GROUPS,
)


V51_STORY_TEXT_GROUPS = (
    StoryTextGroupSpec(0x32, 12, 0x8010, 255, 0x820E, 0xC000, "剧情文本 A", last_pointer_writable=False),
    StoryTextGroupSpec(0x33, 46, 0x8010, 255, 0x820E, 0xC000, "剧情文本 B", last_pointer_writable=False),
    StoryTextGroupSpec(0x36, 44, 0x8010, 255, 0x820E, 0xC000, "剧情文本 C", last_pointer_writable=False),
    StoryTextGroupSpec(0x37, 14, 0xAE46, 52, 0x8000, 0xC000, "剧情文本 D", first_pointer=0xAEAE, last_pointer_writable=False),
    StoryTextGroupSpec(0x38, 16, 0x8010, 255, 0x820E, 0xC000, "剧情文本 E", last_pointer_writable=False),
    StoryTextGroupSpec(0x39, 18, 0x8010, 255, 0x820E, 0xC000, "剧情文本 F", last_pointer_writable=False),
    StoryTextGroupSpec(0x3A, 20, 0x8010, 255, 0x820E, 0xC000, "剧情文本 G", last_pointer_writable=False),
    StoryTextGroupSpec(0x3B, 22, 0x8010, 255, 0x820E, 0xC000, "剧情文本 H", last_pointer_writable=False),
)

# DC's selector $37 uses a split pointer/data layout that the current exact-size
# text writer cannot safely represent.  Keep the other seven verified groups
# available and leave $37 untouched until the relocatable text editor lands.
MMC5_STORY_TEXT_GROUPS = tuple(
    group for group in V51_STORY_TEXT_GROUPS if group.selector != 0x37
)


V51_PROFILE = RomProfile(
    key="shadow-time-ii-v5.1-kaiti",
    label="时空之影II V5.1（楷体）",
    rom_size=786_448,
    mapper=EXPECTED_MAPPER,
    reference_sha256="3CEB596BE06673A89FC455B380B142F99AC9D6461ABA0DDE2B0BD071A259BDD2",
    unit_pointer_table_offset=0x48873,
    unit_count=0xFC,
    unit_data_prg_bank=36,
    unit_data_window_base=0x8000,
    weapon_pointer_table_offset=0x496FB,
    weapon_pointer_count=0x100,
    weapon_count=0xFF,
    weapon_data_prg_bank=36,
    weapon_data_window_base=0x8000,
    unit_weapon_table_offset=0xB4E0,
    unit_name_pointer_table_offset=0x56031,
    unit_name_count=0x100,
    unit_name_first_pointer=0xA221,
    map_pointer_table_offset=0x5D90,
    map_count=0x64,
    map_first_pointer=0xA5BE,
    map_storage_ranges=(
        MapStorageRange(0x00, 0x1A, 3, 0xA000, 0xC000),
        MapStorageRange(0x1A, 0x3B, 52, 0xA000, 0xBFC7),
        MapStorageRange(0x3B, 0x64, 53, 0xA000, 0xAA40),
    ),
    scenario_pointer_table_offset=0x4B305,
    scenario_count=0x20,
    scenario_data_prg_bank=37,
    scenario_data_window_base=0xA000,
    scenario_data_end_pointer=0xBF40,
    scenario_first_pointer=0xB335,
    story_text_groups=V51_STORY_TEXT_GROUPS,
    growth_curve_max=255,
    uses_original_name_aliases=False,
)


MMC5_BATTLE_MUSIC = BattleMusicSpec(
    attacker_table_offset=0xCF86,
    defender_table_offset=0xD04E,
    selector_count=0xC8,
    tracks=(
        BattleMusicTrackSpec(0x00, "无专属曲（按游戏规则回退）"),
        *tuple(
            BattleMusicTrackSpec(command, label)
            for command, label in zip(
                range(0x80, 0x94),
                (
                    "大卫主题曲",
                    "盖塔主题曲",
                    "加代主题曲",
                    "古莲主题曲",
                    "吉尔变身曲",
                    "安东主题曲",
                    "第8关阶段三剧情曲",
                    "地球·我方战斗曲",
                    "地球·敌方战斗曲",
                    "存档曲",
                    "敌方增援曲 2",
                    "游戏结束曲",
                    "宇宙·我方战斗曲",
                    "敌方增援曲 1",
                    "升级曲",
                    "吉尔主题曲",
                    "瓦尔主题曲",
                    "宇宙·敌方战斗曲",
                    "原版保留曲19（当前剧情/战斗表未引用）",
                    "通关曲",
                ),
            )
        ),
        BattleMusicTrackSpec(0x9D, "Ash to Ash"),
        BattleMusicTrackSpec(0x9E, "Dark Knight"),
        BattleMusicTrackSpec(0x9F, "Dark Prison"),
    ),
    named_selectors=(
        BattleMusicSelectorSpec(0x04, "琉妮"),
        BattleMusicSelectorSpec(0x05, "白河愁"),
        BattleMusicSelectorSpec(0x13, "睿智之神"),
    ),
)


MMC5_PROFILE = RomProfile(
    key="dc-famistudio-mmc5-v1",
    label="DC FamiStudio MMC5（1 MiB）",
    rom_size=1_048_592,
    mapper=5,
    reference_sha256="982A10099679A8659168507077931CB5F9FE8E87E9A71C40C91F882AB8771472",
    unit_pointer_table_offset=0x4876F,
    unit_count=0x100,
    unit_data_prg_bank=0x24,
    unit_data_window_base=0x8000,
    weapon_pointer_table_offset=0x48ECF,
    weapon_pointer_count=0x100,
    weapon_count=0xFF,
    weapon_data_prg_bank=0x24,
    weapon_data_window_base=0x8000,
    # Verified two-slot direct weapon-ID table; IDs $01-$FF start at 0xB2DA.
    unit_weapon_table_offset=0xB2D8,
    unit_name_pointer_table_offset=0x49908,
    unit_name_count=0x100,
    unit_name_first_pointer=0x0000,
    map_pointer_table_offset=V51_PROFILE.map_pointer_table_offset,
    map_count=V51_PROFILE.map_count,
    map_first_pointer=V51_PROFILE.map_first_pointer,
    map_storage_ranges=(
        MapStorageRange(0x00, 0x22, 0x03, 0xA000, 0xBFF3),
        MapStorageRange(0x22, 0x2A, 0x34, 0xA000, 0xBF34),
        MapStorageRange(0x2A, 0x64, 0x35, 0xA000, 0xB421),
    ),
    scenario_pointer_table_offset=0x4A425,
    scenario_count=0x20,
    scenario_data_prg_bank=0x25,
    scenario_data_window_base=0xA000,
    scenario_data_end_pointer=0xA940,
    scenario_first_pointer=0xA455,
    story_text_groups=MMC5_STORY_TEXT_GROUPS,
    growth_curve_max=255,
    uses_original_name_aliases=False,
    battle_music=MMC5_BATTLE_MUSIC,
    protected_prg_regions=(
        PrgBankRegion(0x40, 0x60, "CHR 图像原始副本"),
        PrgBankRegion(0x60, 0x65, "FamiStudio 曲目与音频桥接"),
        PrgBankRegion(0x65, 0x66, "MMC5 启动程序"),
        PrgBankRegion(0x7E, 0x80, "固定程序银行"),
    ),
    free_prg_regions=(
        PrgBankRegion(0x66, 0x7E, "预留扩展空间"),
    ),
    weapon_name_pointer_table_offset=0x49DBD,
    weapon_name_pointer_count=0x100,
    weapon_name_first_pointer=0x9FAD,
    weapon_name_data_prg_bank=0x24,
    weapon_name_data_window_base=0x8000,
    weapon_name_data_end_pointer=0xA415,
    # The second of the two character-name tables is the in-battle name table.
    # It intentionally maps the five reserved character slots to the blank name.
    character_name_pointer_table_offset=0x49776,
    character_name_count=0xC8,
    character_name_first_pointer=0x95DB,
    character_name_data_prg_bank=0x24,
    character_name_data_window_base=0x8000,
    character_name_data_end_pointer=0x9766,
    map_triggers=MapTriggerSpec(
        prg_bank=0x0A,
        window_base=0x8000,
        pointer_table=0x987E,
        scenario_count=0x20,
        original_data_start=0x9946,
        original_data_end=0x9950,
        managed_data_start=0x9ED4,
        managed_data_end=0xA000,
    ),
)


DC_EXPANDED_MMC3_PROFILE = RomProfile(
    key="dc-kuorong-mmc3-v1",
    label="第二次机器人大战新DC篇·扩容 MMC3",
    rom_size=1_310_736,
    mapper=194,
    reference_sha256="1DDD4F74B2D3ACEAA8A0BC4A6846BE8E6148C858C2D8EA5A1F6E0A04F0AD4A75",
    unit_pointer_table_offset=MMC5_PROFILE.unit_pointer_table_offset,
    unit_count=MMC5_PROFILE.unit_count,
    unit_data_prg_bank=MMC5_PROFILE.unit_data_prg_bank,
    unit_data_window_base=MMC5_PROFILE.unit_data_window_base,
    weapon_pointer_table_offset=MMC5_PROFILE.weapon_pointer_table_offset,
    weapon_pointer_count=MMC5_PROFILE.weapon_pointer_count,
    weapon_count=MMC5_PROFILE.weapon_count,
    weapon_data_prg_bank=MMC5_PROFILE.weapon_data_prg_bank,
    weapon_data_window_base=MMC5_PROFILE.weapon_data_window_base,
    unit_weapon_table_offset=MMC5_PROFILE.unit_weapon_table_offset,
    unit_name_pointer_table_offset=MMC5_PROFILE.unit_name_pointer_table_offset,
    unit_name_count=MMC5_PROFILE.unit_name_count,
    unit_name_first_pointer=MMC5_PROFILE.unit_name_first_pointer,
    map_pointer_table_offset=MMC5_PROFILE.map_pointer_table_offset,
    map_count=MMC5_PROFILE.map_count,
    map_first_pointer=MMC5_PROFILE.map_first_pointer,
    map_storage_ranges=MMC5_PROFILE.map_storage_ranges,
    scenario_pointer_table_offset=MMC5_PROFILE.scenario_pointer_table_offset,
    scenario_count=MMC5_PROFILE.scenario_count,
    scenario_data_prg_bank=MMC5_PROFILE.scenario_data_prg_bank,
    scenario_data_window_base=MMC5_PROFILE.scenario_data_window_base,
    scenario_data_end_pointer=MMC5_PROFILE.scenario_data_end_pointer,
    scenario_first_pointer=MMC5_PROFILE.scenario_first_pointer,
    story_text_groups=MMC5_PROFILE.story_text_groups,
    growth_curve_max=MMC5_PROFILE.growth_curve_max,
    uses_original_name_aliases=False,
    battle_music=MMC5_BATTLE_MUSIC,
    custom_music_slots=(
        CustomMusicSlotSpec(0x9D, 0x61, "Ash to Ash"),
        CustomMusicSlotSpec(0x9E, 0x62, "Dark Knight"),
        CustomMusicSlotSpec(0x9F, 0x63, "Dark Prison"),
    ),
    chapter_events=ChapterEventSpec(
        code_prg_bank=0x1A,
        data_prg_bank=0x1B,
        pointer_tables=(0x9B00, 0x9B40, 0x9B80),
        phase_labels=("开场/阶段一", "阶段二", "阶段三"),
        scenario_count=0x20,
        data_window_base=0xA000,
        data_start=0xA000,
        data_end=0xBFDA,
    ),
    protected_prg_regions=(
        PrgBankRegion(0x40, 0x60, "原 CHR 字节的 PRG 保留副本"),
        PrgBankRegion(0x60, 0x61, "原音频驱动副本"),
        PrgBankRegion(0x64, 0x65, "双音频引擎与桥接器"),
        PrgBankRegion(0x7E, 0x80, "固定程序银行"),
    ),
    free_prg_regions=(
        PrgBankRegion(0x65, 0x7E, "修改器扩展资源空间"),
    ),
    weapon_name_pointer_table_offset=MMC5_PROFILE.weapon_name_pointer_table_offset,
    weapon_name_pointer_count=MMC5_PROFILE.weapon_name_pointer_count,
    weapon_name_first_pointer=MMC5_PROFILE.weapon_name_first_pointer,
    weapon_name_data_prg_bank=MMC5_PROFILE.weapon_name_data_prg_bank,
    weapon_name_data_window_base=MMC5_PROFILE.weapon_name_data_window_base,
    weapon_name_data_end_pointer=MMC5_PROFILE.weapon_name_data_end_pointer,
    character_name_pointer_table_offset=MMC5_PROFILE.character_name_pointer_table_offset,
    character_name_count=MMC5_PROFILE.character_name_count,
    character_name_first_pointer=MMC5_PROFILE.character_name_first_pointer,
    character_name_data_prg_bank=MMC5_PROFILE.character_name_data_prg_bank,
    character_name_data_window_base=MMC5_PROFILE.character_name_data_window_base,
    character_name_data_end_pointer=MMC5_PROFILE.character_name_data_end_pointer,
    map_triggers=MMC5_PROFILE.map_triggers,
    persuasion_rules=PersuasionRuleSpec(
        table_offset=0x3B73D,
        script_pointer_table_offset=0x35DD0,
        slot_count=0x20,
        editable_count=4,
    ),
)


SUPPORTED_PROFILES = (
    ORIGINAL_PROFILE,
    V51_PROFILE,
    MMC5_PROFILE,
    DC_EXPANDED_MMC3_PROFILE,
)


def detect_profile(data: bytes) -> RomProfile:
    matches = [profile for profile in SUPPORTED_PROFILES if len(data) == profile.rom_size]
    if not matches:
        sizes = "、".join(str(profile.rom_size) for profile in SUPPORTED_PROFILES)
        raise ValueError(f"不受支持的 ROM 大小 {len(data)}；已支持大小：{sizes}。")
    profile = matches[0]
    if profile is V51_PROFILE:
        signature = data[0x48074:0x48080]
        table_signature = data[0x48873:0x48879]
        if signature != bytes.fromhex("A9718518ADE1048519200BC1") or table_signature != bytes.fromhex("00005B8A6B8A"):
            raise ValueError("该 768 KiB ROM 不是已验证的《时空之影II》V5.1 布局。")
    if profile is MMC5_PROFILE:
        header = data[:16]
        if header != bytes.fromhex("4E45531A400053080000700C00000000"):
            raise ValueError("该 1 MiB ROM 不是已验证的 NES 2.0 MMC5 布局。")
        engine_start = 16 + 0x64 * 0x2000
        engine_end = engine_start + 0x2000
        engine_hash = hashlib.sha256(data[engine_start:engine_end]).hexdigest().upper()
        if engine_hash != "4F977F461CC672FB09DA384746FD43668F675523FC00D33180E8C751E5F521B0":
            raise ValueError("该 MMC5 ROM 的 FamiStudio 音频桥接银行不是已验证版本。")
    if profile is DC_EXPANDED_MMC3_PROFILE:
        header = data[:16]
        if header != bytes.fromhex("4E45531A402023C00000000000000000"):
            raise ValueError("该 1.25 MiB ROM 不是已验证的扩容 Mapper 194 布局。")
        engine_start = 16 + 0x64 * 0x2000
        engine_end = engine_start + 0x2000
        engine_hash = hashlib.sha256(data[engine_start:engine_end]).hexdigest().upper()
        if engine_hash != "1A78C5AC91BD578136F54E8353BB44DDFDF6A5B47AECC76FB2181E75FB4B554B":
            raise ValueError("该扩容 ROM 的双音频引擎银行不是已验证版本。")
    return profile

"""Build an expanded Mapper 194 dual-audio-engine DC.nes test ROM."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from fc_rom_editor_core import apply_ips


ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROM = ROOT / "build" / "nsf" / "新DC.nes"
OUTPUT_ROM = ROOT / "build" / "DC_FamiStudio_增容双引擎_测试.nes"
OUTPUT_IPS = ROOT / "patches" / "DC_FamiStudio_增容双引擎_测试.ips"
CAPACITY_REPORT = ROOT / "build" / "DC_FamiStudio_增容双引擎_容量报告.json"
BUILD_LOG = ROOT / "build" / "DC_FamiStudio_增容双引擎_构建记录.md"

ANALYSIS = ROOT / "analysis"
ENGINE_ASM = ANALYSIS / "dc_dual_engine_bank.asm"
ENGINE_BIN = ANALYSIS / "dc_dual_engine_bank.bin"
ENGINE_LST = ANALYSIS / "dc_dual_engine_bank.lst"
TRAMPOLINE_ASM = ANALYSIS / "dc_dual_audio_trampoline.asm"
TRAMPOLINE_BIN = ANALYSIS / "dc_dual_audio_trampoline.bin"
TRAMPOLINE_LST = ANALYSIS / "dc_dual_audio_trampoline.lst"
HANDOFF_ASM = ANALYSIS / "dc_dual_audio_handoff.asm"
HANDOFF_BIN = ANALYSIS / "dc_dual_audio_handoff.bin"
HANDOFF_LST = ANALYSIS / "dc_dual_audio_handoff.lst"
ASM6 = (
    ANALYSIS
    / "FamiStudio-4.5.3-source"
    / "FamiStudio-4.5.3"
    / "Tools"
    / "asm6_fixed.exe"
)

EXPECTED_SOURCE_SHA256 = (
    "267cfa5e6273e0fe3557d5339b0e50172bcf25475283944c7e8372276fb3493c"
)
EXPECTED_SOURCE_SIZE = 0xC0010
OUTPUT_SIZE = 0x140010
INES_HEADER_SIZE = 0x10
PRG_BANK_SIZE = 0x2000
ORIGINAL_PRG_SIZE = 0x80000
ORIGINAL_CHR_SIZE = 0x40000
EXPANDED_PRG_SIZE = 0x100000

ORIGINAL_PRG_BANK_COUNT = 0x40
EXPANDED_PRG_BANK_COUNT = 0x80
MAPPER = 194

COPIED_AUDIO_BANK = 0x60
ASH_TO_ASH_BANK = 0x61
DARK_KNIGHT_BANK = 0x62
DARK_PRISON_BANK = 0x63
ENGINE_BANK = 0x64
FIXED_BANK_C000 = 0x7E
FIXED_BANK_E000 = 0x7F

MUSIC_BANK_ASM = {
    ASH_TO_ASH_BANK: ANALYSIS / "three_song_ash_to_ash_data.asm",
    DARK_KNIGHT_BANK: ANALYSIS / "three_song_dark_knight_data.asm",
    DARK_PRISON_BANK: ANALYSIS / "three_song_dark_prison_v9_data.asm",
}
MUSIC_BANK_NAMES = {
    ASH_TO_ASH_BANK: "Ash to Ash",
    DARK_KNIGHT_BANK: "Dark Knight",
    DARK_PRISON_BANK: "Dark Prison",
}

STOCK_AUDIO_BANK = 0x18
STOCK_FIXED_C000_BANK = 0x3E
STOCK_FIXED_E000_BANK = 0x3F
STOCK_AUDIO_POINTER = 0x8020
TRAMPOLINE_CPU_ADDRESS = 0x99AF
TRAMPOLINE_BANK_OFFSET = TRAMPOLINE_CPU_ADDRESS - 0x8000
HANDOFF_CPU_ADDRESS = 0x99EC
HANDOFF_BANK_OFFSET = HANDOFF_CPU_ADDRESS - 0x8000

# The two NMI paths map stock audio bank $18 into $8000. Only the new copy of
# fixed bank $3F changes these operands, selecting expanded bank $60 instead.
FIXED_E000_AUDIO_OPERANDS = (0xFA84, 0xFADE)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prg_bank_offset(bank: int) -> int:
    return INES_HEADER_SIZE + bank * PRG_BANK_SIZE


def source_prg_bank(source: bytes, bank: int) -> bytes:
    if not 0 <= bank < ORIGINAL_PRG_BANK_COUNT:
        raise ValueError(f"Invalid source PRG bank: 0x{bank:02X}")
    start = prg_bank_offset(bank)
    return source[start : start + PRG_BANK_SIZE]


def assemble(source: Path, output: Path, listing: Path) -> None:
    result = subprocess.run(
        [str(ASM6), source.name, output.name, listing.name],
        cwd=source.parent,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        details = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"ASM6 failed for {source.name}: {details}")


def assemble_payloads() -> None:
    if not ASM6.is_file():
        raise FileNotFoundError(f"ASM6 not found: {ASM6}")
    for bank, source in MUSIC_BANK_ASM.items():
        stem = f"dc_dual_music_{bank:02x}"
        assemble(source, ANALYSIS / f"{stem}.bin", ANALYSIS / f"{stem}.lst")
    assemble(ENGINE_ASM, ENGINE_BIN, ENGINE_LST)
    assemble(
        TRAMPOLINE_ASM,
        TRAMPOLINE_BIN,
        TRAMPOLINE_LST,
    )
    assemble(HANDOFF_ASM, HANDOFF_BIN, HANDOFF_LST)


def label_address(listing: Path, label: str) -> int:
    lines = listing.read_text(encoding="utf-8", errors="replace").splitlines()
    assignment = re.compile(
        rf"^0[0-9A-F]{{4}}\s+{re.escape(label)}\s*=\s*\$([0-9A-Fa-f]+)(?:\s|$)"
    )
    for line in lines:
        match = assignment.match(line)
        if match:
            return int(match.group(1), 16)
    pattern = re.compile(rf"^0([0-9A-F]{{4}})\s+.*{re.escape(label)}:")
    for line in lines:
        match = pattern.match(line)
        if match:
            return int(match.group(1), 16)
    raise ValueError(f"Label {label!r} not found in {listing}")


def validate_ram_layout() -> dict[str, object]:
    """Prove that both engines reuse only the stock audio driver's RAM."""

    expected_symbols = {
        "famistudio_r0": 0x0028,
        "famistudio_r1": 0x0029,
        "famistudio_r2": 0x002A,
        "famistudio_r3": 0x002B,
        "famistudio_ptr0": 0x002D,
        "famistudio_song_speed": 0x002F,
        "famistudio_ptr1": 0x0030,
        "famistudio_chn_return_hi": 0x0032,
        "famistudio_chn_ref_len": 0x0037,
        "famistudio_pitch_env_repeat": 0x003C,
        "famistudio_pitch_env_addr_lo": 0x003F,
        "famistudio_chn_volume_track": 0x0042,
        "famistudio_pitch_env_addr_hi": 0x0047,
        "famistudio_tempo_env_ptr_lo": 0x004A,
        "famistudio_tempo_env_ptr_hi": 0x004B,
        "famistudio_output_buf": 0x004C,
        "famistudio_pitch_env_ptr": 0x0057,
        "famistudio_tempo_env_counter": 0x005A,
        "famistudio_tempo_env_idx": 0x005B,
        "famistudio_tempo_frame_num": 0x005C,
        "famistudio_tempo_frame_cnt": 0x005D,
        "famistudio_env_value": 0x0400,
        "famistudio_env_repeat": 0x040B,
        "famistudio_env_addr_lo": 0x0416,
        "famistudio_env_addr_hi": 0x0421,
        "famistudio_pitch_env_value_lo": 0x042C,
        "famistudio_pitch_env_value_hi": 0x042F,
        "famistudio_pitch_env_fine_value": 0x0432,
        "famistudio_env_ptr": 0x0435,
        "famistudio_chn_ptr_lo": 0x0440,
        "famistudio_chn_ptr_hi": 0x0445,
        "famistudio_chn_note": 0x044A,
        "famistudio_chn_repeat": 0x044F,
        "famistudio_chn_return_lo": 0x0454,
        "famistudio_sfx_base_addr": 0x0459,
        "bridge_magic_a": 0x0468,
        "bridge_magic_b": 0x0469,
        "bridge_magic_c": 0x046A,
        "custom_state": 0x046B,
        "famistudio_instrument_lo": 0x046C,
        "famistudio_instrument_hi": 0x046D,
        "famistudio_pulse1_prev": 0x046E,
        "famistudio_pulse2_prev": 0x046F,
    }
    actual_symbols = {
        name: label_address(ENGINE_LST, name) for name in expected_symbols
    }
    if actual_symbols != expected_symbols:
        mismatches = {
            name: {"expected": expected_symbols[name], "actual": actual_symbols[name]}
            for name in expected_symbols
            if actual_symbols[name] != expected_symbols[name]
        }
        raise AssertionError(f"Unsafe FamiStudio RAM layout: {mismatches}")

    spans = {
        "famistudio_r0": 1, "famistudio_r1": 1,
        "famistudio_r2": 1, "famistudio_r3": 1,
        "famistudio_ptr0": 2, "famistudio_song_speed": 1,
        "famistudio_ptr1": 2, "famistudio_chn_return_hi": 5,
        "famistudio_chn_ref_len": 5, "famistudio_pitch_env_repeat": 3,
        "famistudio_pitch_env_addr_lo": 3, "famistudio_chn_volume_track": 5,
        "famistudio_pitch_env_addr_hi": 3,
        "famistudio_tempo_env_ptr_lo": 1, "famistudio_tempo_env_ptr_hi": 1,
        "famistudio_output_buf": 11, "famistudio_pitch_env_ptr": 3,
        "famistudio_tempo_env_counter": 1, "famistudio_tempo_env_idx": 1,
        "famistudio_tempo_frame_num": 1, "famistudio_tempo_frame_cnt": 1,
        "famistudio_env_value": 11, "famistudio_env_repeat": 11,
        "famistudio_env_addr_lo": 11, "famistudio_env_addr_hi": 11,
        "famistudio_pitch_env_value_lo": 3,
        "famistudio_pitch_env_value_hi": 3,
        "famistudio_pitch_env_fine_value": 3, "famistudio_env_ptr": 11,
        "famistudio_chn_ptr_lo": 5, "famistudio_chn_ptr_hi": 5,
        "famistudio_chn_note": 5, "famistudio_chn_repeat": 5,
        "famistudio_chn_return_lo": 5, "famistudio_sfx_base_addr": 15,
        "bridge_magic_a": 1, "bridge_magic_b": 1,
        "bridge_magic_c": 1, "custom_state": 1,
        "famistudio_instrument_lo": 1, "famistudio_instrument_hi": 1,
        "famistudio_pulse1_prev": 1, "famistudio_pulse2_prev": 1,
    }
    occupied: dict[int, str] = {}
    for name, size in spans.items():
        start = actual_symbols[name]
        for address in range(start, start + size):
            if address in occupied:
                raise AssertionError(
                    f"RAM overlap at 0x{address:04X}: {occupied[address]} and {name}"
                )
            occupied[address] = name

    certified = set(range(0x0028, 0x005E)) | set(range(0x0400, 0x0470))
    certified.remove(0x002C)
    if set(occupied) != certified:
        missing = sorted(certified - set(occupied))
        extra = sorted(set(occupied) - certified)
        raise AssertionError(
            f"RAM ownership partition mismatch: missing={missing}, extra={extra}"
        )

    engine = ENGINE_BIN.read_bytes()
    bridge_start = 0xB500 - 0xA000
    bridge_end = label_address(ENGINE_LST, "dc_dual_audio_bridge_end") - 0xA000
    bridge = engine[bridge_start:bridge_end]
    save_pattern = b"".join(
        bytes((0xA5, address, 0x48)) for address in range(0x4C, 0x57)
    )
    restore_pattern = b"".join(
        bytes((0x68, 0x85, address)) for address in range(0x56, 0x4B, -1)
    )
    if bridge.count(save_pattern) != 1 or bridge.count(restore_pattern) != 1:
        raise AssertionError("The $004C-$0056 save/restore wrapper is missing")

    return {
        "certifiedStockAudioBytes": len(certified),
        "persistentBytes": len(certified) - 8 - 11,
        "scratchBytes": 8,
        "savedOutputBytes": 11,
        "unusedGapPreserved": "0x002C",
        "zeroPageOwned": "0x0028-0x005D except 0x002C",
        "page4Owned": "0x0400-0x046F",
    }


def make_expanding_ips(original: bytes, modified: bytes) -> bytes:
    """Create an IPS whose sequential tail records grow the source image."""
    if len(modified) < len(original):
        raise ValueError("This builder only supports ROM expansion")
    patch = bytearray(b"PATCH")
    position = 0
    while position < len(modified):
        equal = position < len(original) and original[position] == modified[position]
        if equal:
            position += 1
            continue
        start = position
        while position < len(modified) and position - start < 0xFFFF:
            if position < len(original) and original[position] == modified[position]:
                break
            position += 1
        data = modified[start:position]
        patch.extend(start.to_bytes(3, "big"))
        patch.extend(len(data).to_bytes(2, "big"))
        patch.extend(data)
    patch.extend(b"EOF")
    return bytes(patch)


def validate_source(source: bytes) -> None:
    if len(source) != EXPECTED_SOURCE_SIZE or source[:4] != b"NES\x1a":
        raise ValueError("Unexpected source ROM size or iNES signature")
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise ValueError(f"Unexpected source ROM SHA-256: {sha256(source)}")
    if source[4:8] != bytes.fromhex("20 20 23 C0"):
        raise ValueError("Expected 512 KiB PRG, 256 KiB CHR and Mapper 194")

    audio = source_prg_bank(source, STOCK_AUDIO_BANK)
    if audio[:2] != STOCK_AUDIO_POINTER.to_bytes(2, "little"):
        raise ValueError("Stock audio pointer is no longer $8020")
    if any(
        audio[
            TRAMPOLINE_BANK_OFFSET :
            TRAMPOLINE_BANK_OFFSET + 0x1D
        ]
    ):
        raise ValueError("Expected the copied-bank trampoline range to be empty")
    if any(audio[HANDOFF_BANK_OFFSET : HANDOFF_BANK_OFFSET + 0x94]):
        raise ValueError("Expected the copied-bank handoff range to be empty")

    fixed_e000 = source_prg_bank(source, STOCK_FIXED_E000_BANK)
    for address in FIXED_E000_AUDIO_OPERANDS:
        offset = address - 0xE000
        if fixed_e000[offset] != STOCK_AUDIO_BANK:
            raise ValueError(f"Unexpected audio-bank operand at ${address:04X}")


def load_payloads() -> tuple[dict[int, bytes], bytes, bytes, bytes]:
    music: dict[int, bytes] = {}
    for bank in MUSIC_BANK_ASM:
        payload = (ANALYSIS / f"dc_dual_music_{bank:02x}.bin").read_bytes()
        if len(payload) != PRG_BANK_SIZE:
            raise ValueError(f"Music bank 0x{bank:02X} is not exactly 8 KiB")
        music[bank] = payload

    engine = ENGINE_BIN.read_bytes()
    if len(engine) != PRG_BANK_SIZE:
        raise ValueError("Dual-engine bank is not exactly 8 KiB")
    entry_labels = (
        "famistudio_init",
        "famistudio_music_play",
        "famistudio_music_stop",
        "famistudio_update",
        "famistudio_sfx_init",
        "famistudio_sfx_play",
    )
    expected_entries = b"".join(
        b"\x4c" + label_address(ENGINE_LST, label).to_bytes(2, "little")
        for label in entry_labels
    )
    if engine[: len(expected_entries)] != expected_entries:
        raise ValueError("Unexpected FamiStudio entry table")
    if engine[0x12:0x16] != bytes((0x61, 0x62, 0x63, ord("D"))):
        raise ValueError("Unexpected expanded music-bank table")

    trampoline = TRAMPOLINE_BIN.read_bytes()
    if not trampoline or len(trampoline) > 0x40:
        raise ValueError("Unexpected dual-engine trampoline size")
    if trampoline[:3] != bytes.fromhex("A9 87 8D"):
        raise ValueError("Unexpected trampoline entry")

    handoff = HANDOFF_BIN.read_bytes()
    if not handoff or len(handoff) > 0x94:
        raise ValueError("Unexpected stock-handoff payload size")
    if handoff[:3] != bytes.fromhex("48 A9 87"):
        raise ValueError("Unexpected stock-handoff entry")

    return music, engine, trampoline, handoff


def build_expanded_rom(
    source: bytes,
    music: dict[int, bytes],
    engine: bytes,
    trampoline: bytes,
    handoff: bytes,
) -> bytes:
    header = bytearray(source[:INES_HEADER_SIZE])
    original_prg = source[
        INES_HEADER_SIZE : INES_HEADER_SIZE + ORIGINAL_PRG_SIZE
    ]
    original_chr = source[
        INES_HEADER_SIZE + ORIGINAL_PRG_SIZE : EXPECTED_SOURCE_SIZE
    ]

    # The old file body remains an exact prefix. Its old CHR bytes become
    # unused PRG banks $40-$5F, while an identical CHR copy is appended after
    # the new 1 MiB PRG region.
    expanded_prg = bytearray(original_prg + original_chr)
    expanded_prg.extend(bytes(EXPANDED_PRG_SIZE - len(expanded_prg)))

    copied_audio = bytearray(source_prg_bank(source, STOCK_AUDIO_BANK))
    copied_audio[:2] = TRAMPOLINE_CPU_ADDRESS.to_bytes(2, "little")
    copied_audio[
        TRAMPOLINE_BANK_OFFSET : TRAMPOLINE_BANK_OFFSET + len(trampoline)
    ] = trampoline
    copied_audio[
        HANDOFF_BANK_OFFSET : HANDOFF_BANK_OFFSET + len(handoff)
    ] = handoff
    start = COPIED_AUDIO_BANK * PRG_BANK_SIZE
    expanded_prg[start : start + PRG_BANK_SIZE] = copied_audio

    for bank, payload in music.items():
        start = bank * PRG_BANK_SIZE
        expanded_prg[start : start + PRG_BANK_SIZE] = payload

    start = ENGINE_BANK * PRG_BANK_SIZE
    expanded_prg[start : start + PRG_BANK_SIZE] = engine

    fixed_c000 = source_prg_bank(source, STOCK_FIXED_C000_BANK)
    start = FIXED_BANK_C000 * PRG_BANK_SIZE
    expanded_prg[start : start + PRG_BANK_SIZE] = fixed_c000

    fixed_e000 = bytearray(source_prg_bank(source, STOCK_FIXED_E000_BANK))
    for address in FIXED_E000_AUDIO_OPERANDS:
        fixed_e000[address - 0xE000] = COPIED_AUDIO_BANK
    start = FIXED_BANK_E000 * PRG_BANK_SIZE
    expanded_prg[start : start + PRG_BANK_SIZE] = fixed_e000

    header[4] = EXPANDED_PRG_SIZE // 0x4000
    header[6] = (header[6] & 0x0F) | ((MAPPER & 0x0F) << 4)
    header[7] = (header[7] & 0x0F) | (MAPPER & 0xF0)

    output = bytes(header) + bytes(expanded_prg) + original_chr
    if len(output) != OUTPUT_SIZE:
        raise AssertionError(f"Unexpected expanded size: {len(output)}")
    return output


def payload_layout() -> tuple[dict[int, int], dict[str, int]]:
    music_used: dict[int, int] = {}
    label_names = {
        ASH_TO_ASH_BANK: "ash_to_ash_data_end",
        DARK_KNIGHT_BANK: "dark_knight_data_end",
        DARK_PRISON_BANK: "dark_prison_data_end",
    }
    for bank, label in label_names.items():
        listing = ANALYSIS / f"dc_dual_music_{bank:02x}.lst"
        music_used[bank] = label_address(listing, label) - 0x8000

    engine_addresses = {
        "engineEnd": label_address(ENGINE_LST, "dc_dual_engine_end"),
        "sfxEnd": label_address(ENGINE_LST, "dc_dual_sfx_end"),
        "bridgeEnd": label_address(ENGINE_LST, "dc_dual_bridge_end"),
    }
    return music_used, engine_addresses


def write_reports(
    source: bytes,
    output: bytes,
    ips: bytes,
    music: dict[int, bytes],
    engine: bytes,
    trampoline: bytes,
    handoff: bytes,
) -> None:
    music_used, addresses = payload_layout()
    ram_layout = validate_ram_layout()
    engine_code_bytes = addresses["engineEnd"] - 0xA000
    sfx_data_bytes = addresses["sfxEnd"] - addresses["engineEnd"]
    bridge_bytes = addresses["bridgeEnd"] - 0xB500
    inserted_audio_bytes = (
        sum(music_used.values())
        + engine_code_bytes
        + sfx_data_bytes
        + bridge_bytes
        + len(trampoline)
        + len(handoff)
    )

    original_body_preserved = output[INES_HEADER_SIZE : len(source)] == source[
        INES_HEADER_SIZE:
    ]
    active_chr_start = INES_HEADER_SIZE + EXPANDED_PRG_SIZE
    source_chr_start = INES_HEADER_SIZE + ORIGINAL_PRG_SIZE
    active_chr_preserved = output[
        active_chr_start : active_chr_start + ORIGINAL_CHR_SIZE
    ] == source[source_chr_start:]

    report = {
        "source": {
            "rom": str(SOURCE_ROM.relative_to(ROOT)),
            "bytes": len(source),
            "sha256": sha256(source),
            "mapper": 194,
            "prgBytes": ORIGINAL_PRG_SIZE,
            "chrBytes": ORIGINAL_CHR_SIZE,
        },
        "output": {
            "rom": str(OUTPUT_ROM.relative_to(ROOT)),
            "bytes": len(output),
            "sha256": sha256(output),
            "mapper": MAPPER,
            "prgBytes": EXPANDED_PRG_SIZE,
            "chrBytes": ORIGINAL_CHR_SIZE,
            "ips": str(OUTPUT_IPS.relative_to(ROOT)),
            "ipsBytes": len(ips),
            "ipsSha256": sha256(ips),
        },
        "preservation": {
            "headerChangedOffsets": ["0x4"],
            "sourceBodySameAtOriginalOffsets": original_body_preserved,
            "sourceBodyRange": "0x000010-0x0C000F",
            "originalPrgUntouched": output[
                INES_HEADER_SIZE : INES_HEADER_SIZE + ORIGINAL_PRG_SIZE
            ] == source[
                INES_HEADER_SIZE : INES_HEADER_SIZE + ORIGINAL_PRG_SIZE
            ],
            "originalChrPrefixUntouched": output[
                source_chr_start : source_chr_start + ORIGINAL_CHR_SIZE
            ] == source[source_chr_start:],
            "activeChrCopyMatchesSource": active_chr_preserved,
            "newDataStartsAtOldEof": f"0x{len(source):06X}",
        },
        "engines": {
            "stock": {
                "musicTracks": 20,
                "sfxCommands": 56,
                "physicalBanks": ["0x00-0x3F"],
                "status": "source bytes untouched",
            },
            "famiStudio": {
                "musicTracks": 3,
                "sfxCommands": 56,
                "engineBank": f"0x{ENGINE_BANK:02X}",
                "engineCodeBytes": engine_code_bytes,
                "sfxDataBytes": sfx_data_bytes,
                "bridgeBytes": bridge_bytes,
                "trampolineBytes": len(trampoline),
                "handoffBytes": len(handoff),
                "totalUsedBytes": inserted_audio_bytes,
                "ram": {
                    "certifiedStockAudioBytes": ram_layout[
                        "certifiedStockAudioBytes"
                    ],
                    "zeroPageScratch": "0x0028-0x0031 except 0x002C",
                    "famiStudioState": [
                        "0x002F and 0x0032-0x004B",
                        "0x0057-0x005D",
                        "0x0400-0x0467 and 0x046C-0x046F",
                    ],
                    "savedTransientOutput": "0x004C-0x0056",
                    "bridgeState": "0x0468-0x046B",
                    "handoff": "stock/FamiStudio never update concurrently; stock driver is reset and the pending command replayed in the same NMI",
                },
            },
        },
        "musicBanks": [
            {
                "track": MUSIC_BANK_NAMES[bank],
                "command": f"0x{0x9D + index:02X}",
                "bank": f"0x{bank:02X}",
                "fileStart": f"0x{prg_bank_offset(bank):06X}",
                "usedBytes": music_used[bank],
                "freeBytes": PRG_BANK_SIZE - music_used[bank],
                "sha256": sha256(music[bank]),
                "gameplayBinding": None,
            }
            for index, bank in enumerate(MUSIC_BANK_ASM)
        ],
        "expandedLayout": [
            {
                "range": "PRG banks 0x00-0x3F",
                "purpose": "untouched original PRG",
            },
            {
                "range": "PRG banks 0x40-0x5F",
                "purpose": "untouched original CHR bytes retained at original offsets",
            },
            {
                "range": "PRG bank 0x60",
                "purpose": "new copy of stock audio bank plus dispatcher and same-frame handoff trampolines",
            },
            {
                "range": "PRG banks 0x61-0x63",
                "purpose": "three new FamiStudio tracks",
            },
            {
                "range": "PRG bank 0x64",
                "purpose": "second FamiStudio engine, migrated SFX and bridge",
            },
            {
                "range": "PRG banks 0x65-0x7D",
                "purpose": "new reserved expansion space",
            },
            {
                "range": "PRG banks 0x7E-0x7F",
                "purpose": "new fixed-bank copies required by the expanded PRG size",
            },
            {
                "range": "active CHR at 0x100010-0x14000F",
                "purpose": "exact copy of source CHR",
            },
        ],
        "compatibility": {
            "mapperReason": "Keep Mapper 194 so the source hybrid CHR-ROM/CHR-RAM behavior remains exact while PRG grows to 1 MiB",
            "chrBehavior": "unchanged Mapper 194 register and CHR memory semantics",
            "target": "emulators that derive Mapper 194 PRG bank count from the iNES PRG size; verified with Mesen 0.9.9",
            "knownIncompatible": "FCEUX 2.6.6 hard-codes Mapper 194 PRG to 512 KiB and wraps banks 0x60-0x7F",
        },
    }
    CAPACITY_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    BUILD_LOG.write_text(
        "\n".join(
            [
                "# DC.nes 增容双引擎构建记录",
                "",
                f"- 源 ROM SHA-256：`{sha256(source).upper()}`",
                f"- 输出 ROM SHA-256：`{sha256(output).upper()}`",
                f"- IPS SHA-256：`{sha256(ips).upper()}`",
                "- Mapper：保持 194；仅将 PRG 从 512 KiB 扩展到 1 MiB。",
                "- PRG：512 KiB → 1 MiB；CHR：保持 256 KiB。",
                "- 除文件头偏移 `$04` 外，原文件 `$000010-$0C000F` 全部逐字节保持。",
                "- 新增内容从原 EOF `$0C0010` 开始。",
                "- 原20首音乐与56个音效仍由旧驱动播放。",
                "- `$9D/$9E/$9F` 分别测试 Ash to Ash、Dark Knight、Dark Prison，未绑定游戏用途。",
                "- 新曲播放期间的56个音效由第二套 FamiStudio SFX 播放。",
                "- 保持 Mapper 194 后，原混合 CHR-ROM/CHR-RAM 和分屏 IRQ 映射无需转换。",
                "- 目标模拟器：Mesen 0.9.9（已验证真实 1 MiB PRG 偏移）；FCEUX 2.6.6 会把 Mapper 194 固定回绕到 512 KiB，不兼容本增容版。",
                "- FamiStudio 仅复用旧音频驱动专用的165字节 RAM；`$004C-$0056` 在每次更新前后入栈保护。",
                "- 两套引擎不并发更新 APU；切回旧驱动时在同一 NMI 内完成复位和命令重放。",
                "- IPS 扩容回放：通过。",
                "",
                "运行时结果见 `build/DC_FamiStudio_增容双引擎_验证记录.md`。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    source = SOURCE_ROM.read_bytes()
    validate_source(source)
    assemble_payloads()
    music, engine, trampoline, handoff = load_payloads()
    validate_ram_layout()
    output = build_expanded_rom(source, music, engine, trampoline, handoff)

    if output[INES_HEADER_SIZE : len(source)] != source[INES_HEADER_SIZE:]:
        raise AssertionError("Existing ROM body changed at an original file offset")

    ips = make_expanding_ips(source, output)
    if apply_ips(source, ips) != output:
        raise AssertionError("Expanding IPS round-trip verification failed")

    OUTPUT_ROM.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_IPS.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROM.write_bytes(output)
    OUTPUT_IPS.write_bytes(ips)
    write_reports(source, output, ips, music, engine, trampoline, handoff)

    print(f"ROM: {OUTPUT_ROM} ({sha256(output)})")
    print(f"IPS: {OUTPUT_IPS} ({len(ips)} bytes)")
    print(f"Capacity report: {CAPACITY_REPORT}")
    print(f"Build log: {BUILD_LOG}")


if __name__ == "__main__":
    main()

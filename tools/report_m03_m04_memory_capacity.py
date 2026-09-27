"""Report verified initial-configuration and map-trigger memory capacity."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fc_editor.codecs.map_trigger import MapTriggerCodec
from fc_editor.codecs.scenario_layout import ScenarioLayoutCodec
from fc_editor.rom_image import RomImage


DEFAULT_ROM = ROOT / "output" / "rom" / "DC_kuorong_464K.nes"
DEFAULT_OUTPUT = ROOT / "output" / "reports" / "m03-m04-memory-capacity.json"


def _ordered_unique(payloads: list[bytes]) -> list[bytes]:
    return list(dict.fromkeys(payloads))


def build_report(rom_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    rom = RomImage(data)
    scenarios = ScenarioLayoutCodec(rom, data)
    scenario_layouts = [
        scenarios.decode(map_id, data)
        for map_id in range(rom.profile.scenario_count)
    ]
    scenario_payloads = [scenarios.encode(layout) for layout in scenario_layouts]
    scenario_unique = _ordered_unique(scenario_payloads)
    scenario_used = scenarios.storage_used(data)

    triggers = MapTriggerCodec(rom, data)
    trigger_layouts = list(triggers.layouts(data))
    trigger_payloads = [
        triggers.encode_entries(layout.entries) for layout in trigger_layouts
    ]
    trigger_unique = _ordered_unique(trigger_payloads)
    trigger_semantic = sum(len(payload) for payload in trigger_unique)
    trigger_allocated = triggers.storage_used(data)

    scenario_counts = {
        "enemies": sum(len(layout.enemies) for layout in scenario_layouts),
        "guests": sum(len(layout.guests) for layout in scenario_layouts),
        "playerPlacements": sum(
            len(layout.player_placements) for layout in scenario_layouts
        ),
    }
    trigger_counts = {
        "events": sum(
            not entry.is_shop
            for layout in trigger_layouts
            for entry in layout.entries
        ),
        "shops": sum(
            entry.is_shop
            for layout in trigger_layouts
            for entry in layout.entries
        ),
    }
    checks = {
        "scenario_pool_fits": scenario_used <= scenarios.pool_capacity,
        "trigger_pool_fits": trigger_allocated <= triggers.pool_capacity,
        "scenario_first_pointer_matches_profile": (
            scenarios.pointers[0] == rom.profile.scenario_first_pointer
        ),
        "trigger_empty_layout_uses_five_byte_slot": (
            triggers.MINIMUM_SLOT_SIZE == 5
        ),
    }
    return {
        "schemaVersion": 1,
        "rom": {
            "path": str(rom_path.relative_to(ROOT)),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
            "profile": rom.profile.key,
        },
        "initialConfiguration": {
            "prgBank": f"${scenarios.data_prg_bank:02X}",
            "pointerTableFileOffset": f"0x{scenarios.pointer_table_offset:X}",
            "poolCpuRange": [
                f"${scenarios.pool_pointer:04X}",
                f"${scenarios.data_end_pointer:04X}",
            ],
            "poolFileRange": [
                f"0x{scenarios.pool_offset:X}",
                f"0x{scenarios.pool_offset + scenarios.pool_capacity:X}",
            ],
            "chapterCount": rom.profile.scenario_count,
            "uniqueLayouts": len(scenario_unique),
            "semanticBytesAllChapters": sum(map(len, scenario_payloads)),
            "usedBytesAfterDedup": scenario_used,
            "capacityBytes": scenarios.pool_capacity,
            "freeBytes": scenarios.pool_capacity - scenario_used,
            "capacityBoundary": (
                "Bank $25 的下一段已验证部署加载程序始于 $BF40；"
                "$A940 只是原始正文末尾与扩容 Hook 地址。"
            ),
            "recordCounts": scenario_counts,
            "allocation": "32关按地图顺序去重并连续重排；敌/客记录6字节，我方记录4字节。",
        },
        "mapEventsAndShops": {
            "prgBank": f"${triggers.spec.prg_bank:02X}",
            "pointerTableCpuAddress": f"${triggers.spec.pointer_table:04X}",
            "pointerTableFileOffset": f"0x{triggers.pointer_table_offset:X}",
            "sourceDataCpuRange": [
                f"${triggers.spec.original_data_start:04X}",
                f"${triggers.spec.original_data_end:04X}",
            ],
            "storageSegments": [
                {
                    "cpuRange": [f"${pointer:04X}", f"${pointer + capacity:04X}"],
                    "fileRange": [f"0x{offset:X}", f"0x{offset + capacity:X}"],
                    "capacityBytes": capacity,
                }
                for pointer, offset, capacity in triggers.pool_segments
            ],
            "chapterCount": triggers.spec.scenario_count,
            "uniqueLayouts": len(trigger_unique),
            "semanticBytes": trigger_semantic,
            "allocatedBytes": trigger_allocated,
            "capacityBytes": triggers.pool_capacity,
            "freeBytes": triggers.pool_capacity - trigger_allocated,
            "minimumUniqueSlotBytes": triggers.MINIMUM_SLOT_SIZE,
            "recordCounts": trigger_counts,
            "allocation": "32关去重后写入原始10 B区与尾部300 B区；每条4字节，FF结束；空表物理槽至少5字节。",
        },
        "expandedLayout": {
            "relationship": "启用地图容量规划后，地形、初始配置、地图事件/商店改为共用所分配的8 KiB地图Bank池。",
            "singleRecordLimit": "任何单条地形、部署或触发表都不得跨越一个8 KiB Bank。",
        },
        "referenceEvidence": {
            "report": "output/reports/m03-m04-structural-compatibility.json",
            "verifiedBehavior": "旧修改器新增/删除后顺序重排共享池；商店事件空表保留5字节槽。",
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    rom_path = args.rom.resolve()
    output = args.output.resolve()
    report = build_report(rom_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

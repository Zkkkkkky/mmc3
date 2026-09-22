"""Prepare isolated, valid ROM inputs for H-08 formal-EXE rejection checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fc_editor.codecs.map_trigger import MapTrigger
from fc_rom_editor_core import RomProject


SOURCE = ROOT / "output/rom/DC_kuorong_464K.nes"
OUTPUT = ROOT / "output/verification/h08-native-boundary-20260922"
EXPECTED_SOURCE_SHA256 = "82C218275459D53C0F306F6BC036C4797316976E0FA7AD1D5A8247E338995B8E"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def resized_tiles(tiles: tuple[int, ...], width: int, height: int) -> tuple[int, ...]:
    return tuple(tiles[y * width + x] for y in range(height) for x in range(width - 1))


def coordinate_candidate(project: RomProject) -> tuple[int, int, int, int]:
    for map_id in range(project.scenario_count):
        record = project.get_map(map_id)
        if record.width < 2 or project.get_map_triggers(map_id):
            continue
        new_width = record.width - 1
        encoded = project.map_codec.encode(
            new_width, record.height, resized_tiles(record.tiles, record.width, record.height)
        )
        if len(encoded) > project.map_codec.capacities[map_id]:
            continue
        try:
            project.scenario_layout_codec.validate_layout(
                project.get_scenario_layout(map_id), new_width, record.height
            )
        except ValueError:
            continue
        return map_id, record.width, record.height, len(encoded)
    raise RuntimeError("No coordinate-boundary map with spare RLE capacity was found.")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    input_sha = sha256(SOURCE)
    if input_sha != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f"Unexpected source ROM SHA-256: {input_sha}")
    capacity_path = OUTPUT / "h08-capacity-299.nes"
    coordinate_path = OUTPUT / "h08-coordinate-edge.nes"
    report_path = OUTPUT / "inputs.json"
    for path in (capacity_path, coordinate_path, report_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing H-08 input: {path}")

    capacity = RomProject.load(SOURCE)
    map_zero = capacity.get_map(0)
    entries = tuple(
        MapTrigger(index % map_zero.width, index // map_zero.width, 0xFF, 0xF2)
        for index in range(73)
    )
    capacity.set_map_triggers(0, entries)
    used = capacity.map_trigger_codec.storage_used(capacity.working)
    assert used == 299, used
    capacity.save_as(capacity_path, make_backup=False)
    assert len(RomProject.load(capacity_path).get_map_triggers(0)) == 73

    coordinates = RomProject.load(SOURCE)
    map_id, original_width, height, shrunk_rle = coordinate_candidate(coordinates)
    coordinates.set_map_triggers(
        map_id, (MapTrigger(original_width - 1, 0, 0xFF, 0xF2),)
    )
    coordinates.save_as(coordinate_path, make_backup=False)
    reopened = RomProject.load(coordinate_path)
    assert reopened.get_map_triggers(map_id) == (
        MapTrigger(original_width - 1, 0, 0xFF, 0xF2),
    )

    report = {
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256_before_and_after": input_sha,
        "capacity": {
            "path": str(capacity_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(capacity_path),
            "map_id": 0,
            "record_count": 73,
            "pool_used": used,
            "pool_capacity": capacity.map_trigger_codec.pool_capacity,
            "one_more_record_would_need": 303,
        },
        "coordinate": {
            "path": str(coordinate_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(coordinate_path),
            "map_id": map_id,
            "original_width": original_width,
            "height": height,
            "existing_event_x": original_width - 1,
            "proposed_width": original_width - 1,
            "proposed_rle_size": shrunk_rle,
            "rle_capacity": coordinates.map_codec.capacities[map_id],
        },
    }
    assert sha256(SOURCE) == input_sha
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

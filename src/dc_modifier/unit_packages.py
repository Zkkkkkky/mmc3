from __future__ import annotations

from fc_editor.unit_package import UnitPackage, UnitPackageAsset
from fc_rom_editor_core import RomProject


def package_from_project(
    project: RomProject,
    unit_id: int,
    *,
    chr_ranges: tuple[tuple[int, int], ...] = (),
) -> UnitPackage:
    """Create a portable package from the current in-memory unit state."""

    source_ids = project.unit_name_source_ids(unit_id)
    assets: list[UnitPackageAsset] = []
    for first_tile, tile_count in chr_ranges:
        payload = project.chr_codec.range_bytes(
            first_tile,
            tile_count,
            bytes(project.working),
        )
        assets.append(
            UnitPackageAsset(
                asset_id=f"chr.{first_tile:04X}.{tile_count}",
                kind="chr_tiles",
                filename=f"chr_{first_tile:04X}_{tile_count}.chr",
                data=payload,
                metadata=(("firstTile", first_tile), ("tileCount", tile_count)),
            )
        )
    return UnitPackage(
        label=f"${unit_id:02X} · {project.unit_display_name(unit_id)}",
        source_profile=project.profile.key,
        source_rom_sha256=project.source_sha256,
        source_unit_id=unit_id,
        unit_record=project.record_bytes(unit_id),
        name_source_id=source_ids[0] if source_ids else None,
        assets=tuple(assets),
    )


def affected_unit_ids(project: RomProject, target_unit_id: int) -> tuple[int, ...]:
    """Return every ID backed by the target's shared 16-byte record."""

    return project.unit_codec.decode_record(
        target_unit_id,
        bytes(project.working),
    ).ids


def apply_unit_package(
    project: RomProject,
    package: UnitPackage,
    target_unit_id: int,
) -> tuple[int, ...]:
    """Apply one package as a single undoable transaction.

    Version 1 packages reserve asset slots for graphics/animation resources.  They
    are intentionally rejected until their pointer formats have been verified, so
    an import can never silently lose part of a unit.
    """

    if package.source_profile != project.profile.key:
        raise ValueError(
            "机体包使用不同的ROM配置，不能安全导入当前工程。"
        )
    chr_assets: list[tuple[int, bytes]] = []
    unsupported_kinds = sorted(
        {asset.kind for asset in package.assets if asset.kind != "chr_tiles"}
    )
    if unsupported_kinds:
        raise ValueError(
            f"机体包包含当前版本尚未接通的资源：{'、'.join(unsupported_kinds)}。"
            "为防止不完整导入，本次操作未写入ROM。"
        )
    for asset in package.assets:
        metadata = asset.metadata_map
        first_tile = metadata.get("firstTile")
        tile_count = metadata.get("tileCount")
        if not isinstance(first_tile, int) or not isinstance(tile_count, int):
            raise ValueError(f"CHR资源 {asset.asset_id} 缺少有效的图块范围。")
        if tile_count <= 0 or len(asset.data) != tile_count * 16:
            raise ValueError(f"CHR资源 {asset.asset_id} 的长度与图块数量不匹配。")
        project.chr_codec.range_bytes(first_tile, tile_count, bytes(project.working))
        chr_assets.append((first_tile, asset.data))

    affected = affected_unit_ids(project, target_unit_id)
    with project.transaction(
        f"导入机体 {package.label} → ${target_unit_id:02X}"
    ):
        project.set_record_hex(target_unit_id, package.unit_record.hex())
        if package.name_source_id is not None:
            project.set_unit_name_reference(target_unit_id, package.name_source_id)
        for first_tile, payload in chr_assets:
            project.set_chr_range(first_tile, payload)
    return affected

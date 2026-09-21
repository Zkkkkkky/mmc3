from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .constants import UNIT_RECORD_SIZE
from .errors import ProjectFormatError


UNIT_PACKAGE_FORMAT = "newdc.unit"
UNIT_PACKAGE_VERSION = 1
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
MANIFEST_PATH = "manifest.json"


@dataclass(frozen=True)
class UnitPackageAsset:
    asset_id: str
    kind: str
    filename: str
    data: bytes
    metadata: tuple[tuple[str, int | str], ...] = ()

    def __post_init__(self) -> None:
        if not self.asset_id or not self.kind:
            raise ValueError("机体资源的ID和类型不能为空。")
        path = PurePosixPath(self.filename)
        if path.is_absolute() or ".." in path.parts or path.name != self.filename:
            raise ValueError("机体资源文件名必须是安全的单层相对名称。")
        if not self.data:
            raise ValueError("机体资源不能为空。")
        keys = [key for key, _value in self.metadata]
        if len(keys) != len(set(keys)) or any(not key for key in keys):
            raise ValueError("机体资源元数据键不能为空或重复。")

    @property
    def metadata_map(self) -> dict[str, int | str]:
        return dict(self.metadata)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest().upper()


@dataclass(frozen=True)
class UnitPackage:
    label: str
    source_profile: str
    source_rom_sha256: str
    source_unit_id: int
    unit_record: bytes
    name_source_id: int | None
    assets: tuple[UnitPackageAsset, ...] = ()

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("机体包名称不能为空。")
        if not self.source_profile:
            raise ValueError("机体包缺少来源配置。")
        if len(self.source_rom_sha256) != 64 or any(
            character not in "0123456789ABCDEFabcdef"
            for character in self.source_rom_sha256
        ):
            raise ValueError("机体包来源ROM哈希无效。")
        if not 1 <= self.source_unit_id <= 0xFF:
            raise ValueError("来源机体ID必须在01—FF之间。")
        if len(self.unit_record) != UNIT_RECORD_SIZE:
            raise ValueError(f"机体记录必须正好为{UNIT_RECORD_SIZE}字节。")
        if self.name_source_id is not None and not 1 <= self.name_source_id <= 0xFF:
            raise ValueError("名称来源ID必须在01—FF之间。")
        asset_ids = [asset.asset_id for asset in self.assets]
        filenames = [asset.filename for asset in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("机体包含有重复的资源ID。")
        if len(filenames) != len(set(filenames)):
            raise ValueError("机体包含有重复的资源文件名。")

    def to_manifest(self) -> dict[str, Any]:
        return {
            "format": UNIT_PACKAGE_FORMAT,
            "version": UNIT_PACKAGE_VERSION,
            "label": self.label,
            "source": {
                "profile": self.source_profile,
                "romSha256": self.source_rom_sha256.upper(),
                "unitId": self.source_unit_id,
            },
            "unit": {
                "record": self.unit_record.hex().upper(),
                "nameSourceId": self.name_source_id,
            },
            "assets": [
                {
                    "id": asset.asset_id,
                    "kind": asset.kind,
                    "path": f"assets/{asset.filename}",
                    "bytes": len(asset.data),
                    "sha256": asset.sha256,
                    "metadata": asset.metadata_map,
                }
                for asset in sorted(self.assets, key=lambda item: item.asset_id)
            ],
        }

    @staticmethod
    def _zip_info(name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        return info

    def to_bytes(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", strict_timestamps=True) as archive:
            manifest = (
                json.dumps(
                    self.to_manifest(),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            archive.writestr(self._zip_info(MANIFEST_PATH), manifest, compresslevel=9)
            for asset in sorted(self.assets, key=lambda item: item.asset_id):
                archive.writestr(
                    self._zip_info(f"assets/{asset.filename}"),
                    asset.data,
                    compresslevel=9,
                )
        payload = buffer.getvalue()
        if len(payload) > MAX_PACKAGE_BYTES:
            raise ValueError("机体包超过32 MiB安全上限。")
        return payload

    def save(self, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_bytes()
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary_name).replace(destination)
        finally:
            if temporary_name is not None:
                temporary = Path(temporary_name)
                if temporary.exists():
                    temporary.unlink()
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "UnitPackage":
        source = Path(path).expanduser().resolve()
        if source.stat().st_size > MAX_PACKAGE_BYTES:
            raise ProjectFormatError("机体包超过32 MiB安全上限。")
        try:
            with zipfile.ZipFile(source, "r") as archive:
                infos = archive.infolist()
                if len(infos) != len({info.filename for info in infos}):
                    raise ProjectFormatError("机体包包含重复文件。")
                if any(
                    PurePosixPath(info.filename).is_absolute()
                    or ".." in PurePosixPath(info.filename).parts
                    for info in infos
                ):
                    raise ProjectFormatError("机体包包含不安全路径。")
                if sum(info.file_size for info in infos) > MAX_PACKAGE_BYTES:
                    raise ProjectFormatError("机体包解压后超过32 MiB安全上限。")
                manifest_value = json.loads(archive.read(MANIFEST_PATH).decode("utf-8"))
                return cls._from_archive_manifest(archive, manifest_value)
        except ProjectFormatError:
            raise
        except (OSError, KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            raise ProjectFormatError(f"无法读取机体包：{error}") from error

    @classmethod
    def _from_archive_manifest(
        cls,
        archive: zipfile.ZipFile,
        manifest: Any,
    ) -> "UnitPackage":
        if not isinstance(manifest, dict):
            raise ProjectFormatError("机体包清单根节点必须是对象。")
        if manifest.get("format") != UNIT_PACKAGE_FORMAT:
            raise ProjectFormatError("文件不是新DC机体包。")
        if manifest.get("version") != UNIT_PACKAGE_VERSION:
            raise ProjectFormatError("机体包版本不受支持。")
        try:
            source = manifest["source"]
            unit = manifest["unit"]
            asset_rows = manifest.get("assets", [])
            if not isinstance(source, dict) or not isinstance(unit, dict):
                raise TypeError("source/unit必须是对象")
            if not isinstance(asset_rows, list):
                raise TypeError("assets必须是数组")
            assets: list[UnitPackageAsset] = []
            for row in asset_rows:
                if not isinstance(row, dict):
                    raise TypeError("资源项必须是对象")
                archive_path = str(row["path"])
                path = PurePosixPath(archive_path)
                if path.parent != PurePosixPath("assets") or path.name != archive_path.split("/")[-1]:
                    raise ProjectFormatError("资源必须位于assets目录的单层路径中。")
                data = archive.read(archive_path)
                if len(data) != int(row["bytes"]):
                    raise ProjectFormatError(f"资源 {row['id']} 的长度不匹配。")
                digest = hashlib.sha256(data).hexdigest().upper()
                if digest != str(row["sha256"]).upper():
                    raise ProjectFormatError(f"资源 {row['id']} 的哈希不匹配。")
                assets.append(
                    UnitPackageAsset(
                        str(row["id"]),
                        str(row["kind"]),
                        path.name,
                        data,
                        tuple(
                            sorted(
                                (str(key), value)
                                for key, value in dict(row.get("metadata", {})).items()
                                if isinstance(value, (int, str)) and not isinstance(value, bool)
                            )
                        ),
                    )
                )
            name_source_value = unit.get("nameSourceId")
            return cls(
                label=str(manifest["label"]),
                source_profile=str(source["profile"]),
                source_rom_sha256=str(source["romSha256"]).upper(),
                source_unit_id=int(source["unitId"]),
                unit_record=bytes.fromhex(str(unit["record"])),
                name_source_id=(
                    None if name_source_value is None else int(name_source_value)
                ),
                assets=tuple(assets),
            )
        except ProjectFormatError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise ProjectFormatError(f"机体包清单字段无效：{error}") from error

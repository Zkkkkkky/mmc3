"""Classify the eight remaining M05 reference action discoveries.

The legacy editor rewrites a large common byte set whenever these cases save.
Using either ordinary upload as the normalization baseline lets us distinguish
preview-only actions from actions that also touch a secondary resource.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "output/build/legacy-diff-audit/cases/legacy_live/M05"
JSON_OUT = ROOT / "output/reports/m05-pending-action-analysis.json"
MD_OUT = ROOT / "output/reports/m05-pending-action-analysis.md"
SAMPLE_ROOT = ROOT / "output/build/legacy-diff-audit/m05-upload-samples"

FIELDS = (
    "body_upload_bmp",
    "fragment_upload_bmp",
    "body_compressed_upload_bmp",
    "fragment_compressed_upload_bmp",
    "icon_upload_bmp",
    "main_clear_body",
    "main_clear_fragment",
    "body_puzzle_template_8x8",
)
PREVIEW_ONLY_FIELDS = {"body_upload_bmp", "fragment_upload_bmp"}
CORRECTED_PROMOTED_FIELDS = {"body_puzzle_template_8x8"}
EXPECTED_REOPEN_VALUES = {
    "body_puzzle_template_8x8": "F3 F9 00 FD 20 08 F9 40 00 FF ",
}
BODY_COMPRESSED_FIELD = "body_compressed_upload_bmp"
FRAGMENT_COMPRESSED_FIELD = "fragment_compressed_upload_bmp"
CLEAR_FIELDS = {"main_clear_body", "main_clear_fragment"}
ICON_UPLOAD_FIELD = "icon_upload_bmp"
COMPOSITION_PAIR_START = 16 + 0x28 * 0x2000
COMPOSITION_PAIR_END = COMPOSITION_PAIR_START + 0x4000


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _case_dir(field: str) -> Path:
    return CASE_ROOT / field / "cold_start_01"


def _range_summary(offsets: list[int], limit: int = 24) -> dict[str, object]:
    if not offsets:
        return {
            "count": 0,
            "rangeCount": 0,
            "minimum": None,
            "maximum": None,
            "firstRanges": [],
        }
    ranges: list[tuple[int, int]] = []
    start = previous = offsets[0]
    for offset in offsets[1:]:
        if offset != previous + 1:
            ranges.append((start, previous))
            start = offset
        previous = offset
    ranges.append((start, previous))
    return {
        "count": len(offsets),
        "rangeCount": len(ranges),
        "minimum": f"0x{offsets[0]:06X}",
        "maximum": f"0x{offsets[-1]:06X}",
        "firstRanges": [
            {
                "start": f"0x{start_offset:06X}",
                "end": f"0x{end_offset:06X}",
                "length": end_offset - start_offset + 1,
            }
            for start_offset, end_offset in ranges[:limit]
        ],
    }


def _region_breakdown(offsets: list[int], rom: bytes) -> dict[str, object]:
    chr_start = 16 + rom[4] * 0x4000
    regions = {
        "unitCompositionPair": (COMPOSITION_PAIR_START, COMPOSITION_PAIR_END),
        "activeChr": (chr_start, len(rom)),
    }
    result: dict[str, object] = {}
    accounted: set[int] = set()
    for name, (start, end) in regions.items():
        selected = [offset for offset in offsets if start <= offset < end]
        accounted.update(selected)
        result[name] = {
            "fileRange": f"0x{start:06X}-0x{end - 1:06X}",
            **_range_summary(selected),
        }
    result["unclassified"] = _range_summary(
        [offset for offset in offsets if offset not in accounted]
    )
    return result


def _encode_nes_tile(indices: list[int]) -> bytes:
    result = bytearray()
    for bit in (0, 1):
        for y in range(8):
            value = 0
            for x in range(8):
                value |= ((indices[y * 8 + x] >> bit) & 1) << (7 - x)
            result.append(value)
    return bytes(result)


def _compressed_body_bytes() -> bytes:
    image = Image.open(SAMPLE_ROOT / "body.bmp").convert("RGB")
    palette = {
        (0, 0, 0): 0,
        (57, 51, 255): 2,
        (99, 207, 99): 1,
        (220, 255, 255): 3,
    }
    tiles: list[bytes] = []
    for tile_y in range(16):
        for tile_x in range(16):
            indices = [
                palette[image.getpixel((tile_x * 8 + x, tile_y * 8 + y))]
                for y in range(8)
                for x in range(8)
            ]
            if any(indices):
                tiles.append(_encode_nes_tile(indices))
    return b"".join(tiles)


def _signed(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def _fragment_script_positions(rom: bytes, unit_id: int = 2) -> list[tuple[int, int]]:
    pair = rom[COMPOSITION_PAIR_START:COMPOSITION_PAIR_END]
    # The legacy V5.1 save image places the 256-entry fragment pointer table
    # at pair offset $17CC.  Row 1 in the UI is unit ID $02.
    pointer_offset = 0x17CC + unit_id * 2
    pointer = int.from_bytes(pair[pointer_offset:pointer_offset + 2], "little")
    cursor = pointer - 0x8000
    x = _signed(pair[cursor])
    y = _signed(pair[cursor + 1]) + 0x81
    cursor += 3
    positions: list[tuple[int, int]] = []
    parameter_counts = {
        0x02: 0, 0x03: 0, 0x06: 1, 0x07: 1, 0x0A: 1, 0x0B: 1,
        0x0E: 2, 0x0F: 2, 0x22: 1, 0x23: 1, 0x26: 2, 0x27: 2,
        0x2A: 2, 0x2B: 2, 0x2E: 3, 0x2F: 3,
    }
    while True:
        command = pair[cursor]
        cursor += 1
        if command == 0xFF:
            return positions
        base = command & 0x3F
        count = parameter_counts[base]
        parameters = pair[cursor:cursor + count]
        cursor += count
        positions.append((x, y))
        if base in (0x02, 0x03):
            x += 8
        elif base in (0x06, 0x07):
            x += _signed(parameters[0])
        elif base in (0x0A, 0x0B):
            x += _signed(parameters[0]); y += 8
        elif base in (0x0E, 0x0F):
            x += _signed(parameters[0]); y += _signed(parameters[1])
        elif base in (0x22, 0x23):
            x += 8
        elif base in (0x26, 0x27):
            x += _signed(parameters[1])
        elif base in (0x2A, 0x2B):
            x += _signed(parameters[1]); y += 8
        else:
            x += _signed(parameters[1]); y += _signed(parameters[2])


def _compressed_fragment_bytes(rom: bytes) -> tuple[bytes, list[tuple[int, int]]]:
    image = Image.open(SAMPLE_ROOT / "fragment.bmp").convert("RGB")
    palette = {
        (0, 0, 0): 0,
        (57, 51, 255): 2,
        (99, 207, 99): 1,
        (220, 255, 255): 3,
    }
    positions = _fragment_script_positions(rom)
    work = [[palette[image.getpixel((x, y))] for x in range(128)] for y in range(128)]
    tiles: list[bytes] = []
    for origin_x, origin_y in positions:
        indices = [
            work[origin_y + y][origin_x + x]
            for y in range(8)
            for x in range(8)
        ]
        tiles.append(_encode_nes_tile(indices))
        for y in range(8):
            for x in range(8):
                work[origin_y + y][origin_x + x] = 0
    return b"".join(tiles), positions


def analyze() -> dict[str, object]:
    loaded: dict[str, tuple[dict[str, object], bytes, bytes]] = {}
    for field in FIELDS:
        directory = _case_dir(field)
        case = json.loads((directory / "case.json").read_text(encoding="utf-8"))
        loaded[field] = (
            case,
            (directory / "before.nes").read_bytes(),
            (directory / "after.nes").read_bytes(),
        )

    baseline_case, baseline_before, normalization_after = loaded["body_upload_bmp"]
    rows: dict[str, dict[str, object]] = {}
    for field in FIELDS:
        case, before, after = loaded[field]
        if len(after) != len(normalization_after):
            raise ValueError(f"M05 {field} output length differs from normalization baseline")
        action_offsets = [
            offset
            for offset, (actual, normalized) in enumerate(
                zip(after, normalization_after, strict=True)
            )
            if actual != normalized
        ]
        reopen_matches_original = case.get("reopen_value") == case.get("original_value")
        chr_start = 16 + before[4] * 0x4000
        action_chr_offsets = [offset for offset in action_offsets if offset >= chr_start]
        semantic_evidence: dict[str, object] | None = None
        if field in PREVIEW_ONLY_FIELDS:
            classification = "reference_preview_only_confirmed"
            conclusion = (
                "保存结果与普通上传共同归一化基线逐字节一致，且全新进程重开恢复原预览；"
                "该入口不形成可持久化上传协议。"
            )
        elif field in CORRECTED_PROMOTED_FIELDS:
            classification = "reference_save_promoted_after_request_correction"
            conclusion = (
                "配方误把点击前脚本登记为请求值；冷重开得到已知 8×8 模板脚本，"
                "且动作专属写入全部位于机体拼图脚本对。原误登记值已作为审计字段保留，"
                "本次 14.735 秒证据已晋级黄金。"
            )
        elif field == BODY_COMPRESSED_FIELD:
            expected_body = _compressed_body_bytes()
            target_start = chr_start + 0x1300 * 16
            semantic_evidence = {
                "kind": "compressed_body_tiles",
                "nonblankTileCount": len(expected_body) // 16,
                "targetFirstTile": "0x1300",
                "encodedBytes": len(expected_body),
                "exactBytesMatch": after[
                    target_start : target_start + len(expected_body)
                ]
                == expected_body,
            }
            classification = "reference_resource_save_confirmed_capture_mismatch"
            conclusion = (
                "BMP 的 55 个非空图块按参考四色映射压缩后，880 字节与保存 ROM 的目标图库"
                "逐字节一致；资源保存协议已确认，冷重开控件像素哈希不是可靠判据。"
            )
        elif field == FRAGMENT_COMPRESSED_FIELD:
            expected_fragment, positions = _compressed_fragment_bytes(after)
            target_start = chr_start + 0x3F00 * 16
            semantic_evidence = {
                "kind": "compressed_fragment_tiles",
                "scriptPlacementCount": len(positions),
                "targetFirstTile": "0x3F00",
                "encodedBytes": len(expected_fragment),
                "consumeOverlappingPixels": True,
                "exactBytesMatch": after[
                    target_start : target_start + len(expected_fragment)
                ]
                == expected_fragment,
            }
            classification = "reference_resource_save_confirmed_capture_mismatch"
            conclusion = (
                "按保存脚本的 23 个坐标依次裁取并清除已消费像素后，生成的 368 字节与目标"
                "图库逐字节一致；压缩碎片保存协议已确认，冷重开控件像素哈希不是可靠判据。"
            )
        elif field in CLEAR_FIELDS:
            semantic_evidence = {
                "kind": "clear_nonzero_target_bytes",
                "actionSpecificChrBytes": len(action_chr_offsets),
                "allActionSpecificChrBytesZeroAfter": all(
                    after[offset] == 0 for offset in action_chr_offsets
                ),
                "allActionSpecificChrBytesNonzeroBefore": all(
                    before[offset] != 0 for offset in action_chr_offsets
                ),
            }
            classification = "reference_clear_save_confirmed_capture_mismatch"
            conclusion = (
                "动作涉及的目标 CHR 非零字节在保存后全部清零；清除语义已确认，"
                "冷重开整控件像素哈希不是可靠判据。"
            )
        elif field == ICON_UPLOAD_FIELD:
            icon_start = chr_start + 0x1188 * 16
            sample = Image.open(SAMPLE_ROOT / "icon.bmp").convert("RGB")
            semantic_evidence = {
                "kind": "icon_target_cleared_instead_of_imported",
                "sampleHasNonblackPixels": any(
                    sample.getpixel((x, y)) != (0, 0, 0)
                    for y in range(sample.height)
                    for x in range(sample.width)
                ),
                "targetFourTilesAllZeroAfter": not any(
                    after[icon_start : icon_start + 4 * 16]
                ),
                "targetFirstTile": "0x1188",
            }
            classification = "reference_upload_clears_target"
            conclusion = (
                "彩色 16×16 BMP 保存后目标四图块全部为零；参考入口没有形成有效图标上传协议，"
                "不得要求产品复制该破坏性结果。"
            )
        else:
            classification = "reference_secondary_resource_write_unresolved"
            conclusion = (
                "相对共同归一化基线存在动作专属写入，但冷重开既不等于请求值也不等于原值；"
                "需继续定位归一化或二级资源绑定，不能晋级黄金。"
            )
        rows[field] = {
            "classification": classification,
            "conclusion": conclusion,
            "durationSeconds": case.get("duration_seconds"),
            "withinBudget": case.get("within_budget"),
            "changedFromInputCount": len(case.get("changed_offsets", [])),
            "reopenMatchesRequest": case.get("reopen_matches_request"),
            "reopenMatchesOriginal": reopen_matches_original,
            "inputSha256": _sha256(before),
            "outputSha256": _sha256(after),
            "actionSpecificDiff": _range_summary(action_offsets),
            "actionSpecificRegions": _region_breakdown(action_offsets, before),
            "semanticEvidence": semantic_evidence,
        }

    preview_outputs_identical = (
        loaded["body_upload_bmp"][2] == loaded["fragment_upload_bmp"][2]
    )
    checks = {
        "allEightCasesLoaded": len(rows) == 8,
        "allCasesShareInput": len({_sha256(item[1]) for item in loaded.values()}) == 1,
        "ordinaryUploadOutputsIdentical": preview_outputs_identical,
        "ordinaryUploadsReopenOriginal": all(
            rows[field]["reopenMatchesOriginal"] is True
            for field in PREVIEW_ONLY_FIELDS
        ),
        "ordinaryUploadsHaveNoActionSpecificDiff": all(
            rows[field]["actionSpecificDiff"]["count"] == 0
            for field in PREVIEW_ONLY_FIELDS
        ),
        "remainingUnresolvedHaveActionSpecificDiff": all(
            rows[field]["actionSpecificDiff"]["count"] > 0
            for field in set(FIELDS)
            - PREVIEW_ONLY_FIELDS
            - CORRECTED_PROMOTED_FIELDS
        ),
        "remainingUnresolvedDoNotReopenOriginal": all(
            rows[field]["reopenMatchesOriginal"] is False
            for field in set(FIELDS)
            - PREVIEW_ONLY_FIELDS
            - CORRECTED_PROMOTED_FIELDS
        ),
        "template8x8CorrectionAudited": all(
            loaded[field][0].get("captured_requested_value")
            == loaded[field][0].get("original_value")
            and loaded[field][0].get("requested_value") == EXPECTED_REOPEN_VALUES[field]
            and loaded[field][0].get("reopen_value") == EXPECTED_REOPEN_VALUES[field]
            and rows[field]["withinBudget"] is True
            and loaded[field][0].get("case_kind") == "golden"
            and loaded[field][0].get("passed") is True
            for field in CORRECTED_PROMOTED_FIELDS
        ),
        "compressedBodyEncodingConfirmed": rows[BODY_COMPRESSED_FIELD][
            "semanticEvidence"
        ]["exactBytesMatch"]
        is True,
        "compressedFragmentEncodingConfirmed": rows[FRAGMENT_COMPRESSED_FIELD][
            "semanticEvidence"
        ]["exactBytesMatch"]
        is True,
        "clearActionsConfirmed": all(
            rows[field]["semanticEvidence"]["allActionSpecificChrBytesZeroAfter"]
            is True
            and rows[field]["semanticEvidence"][
                "allActionSpecificChrBytesNonzeroBefore"
            ]
            is True
            for field in CLEAR_FIELDS
        ),
        "iconUploadClearsTarget": rows[ICON_UPLOAD_FIELD]["semanticEvidence"][
            "sampleHasNonblackPixels"
        ]
        is True
        and rows[ICON_UPLOAD_FIELD]["semanticEvidence"][
            "targetFourTilesAllZeroAfter"
        ]
        is True,
        "allActionSpecificOffsetsMapped": all(
            rows[field]["actionSpecificRegions"]["unclassified"]["count"] == 0
            for field in FIELDS
        ),
    }
    return {
        "schemaVersion": 1,
        "module": "M05",
        "normalizationBaseline": {
            "field": "body_upload_bmp",
            "inputSha256": _sha256(baseline_before),
            "outputSha256": _sha256(normalization_after),
            "changedFromInputCount": len(baseline_case.get("changed_offsets", [])),
        },
        "counts": {
            "cases": len(rows),
            "previewOnlyConfirmed": sum(
                row["classification"] == "reference_preview_only_confirmed"
                for row in rows.values()
            ),
            "savePromotedAfterRequestCorrection": sum(
                row["classification"]
                == "reference_save_promoted_after_request_correction"
                for row in rows.values()
            ),
            "secondaryResourceWriteUnresolved": sum(
                row["classification"]
                == "reference_secondary_resource_write_unresolved"
                for row in rows.values()
            ),
            "resourceSaveConfirmedCaptureMismatch": sum(
                row["classification"]
                in {
                    "reference_resource_save_confirmed_capture_mismatch",
                    "reference_clear_save_confirmed_capture_mismatch",
                }
                for row in rows.values()
            ),
            "invalidReferenceUpload": sum(
                row["classification"] == "reference_upload_clears_target"
                for row in rows.values()
            ),
        },
        "checks": checks,
        "cases": rows,
        "passed": all(checks.values()),
    }


def _markdown(report: dict[str, object]) -> str:
    lines = [
        "# M05 剩余参考动作分析",
        "",
        f"结论：`passed={str(report['passed']).lower()}`；普通上传确认仅预览 2 项，8×8 模板修正请求后晋级黄金 1 项，资源保存确认但截图回读不适用 4 项，无效参考上传 1 项，未解码 0 项。",
        "",
        "| 动作 | 分类 | 动作专属差分 | 拼图脚本对 | 活动 CHR | 冷重开等于原值 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for field, row in report["cases"].items():
        lines.append(
            f"| `{field}` | `{row['classification']}` | "
            f"{row['actionSpecificDiff']['count']} | "
            f"{row['actionSpecificRegions']['unitCompositionPair']['count']} | "
            f"{row['actionSpecificRegions']['activeChr']['count']} | "
            f"{str(row['reopenMatchesOriginal']).lower()} |"
        )
    lines.extend(
        [
            "",
            "普通上传的主体与碎片输出 ROM SHA-256 完全相同，说明两次保存只产生共同归一化；",
            "两项在全新进程重开后均恢复原预览，因此不应要求当前产品复刻一个不存在的持久化协议。",
            "全部动作专属偏移均已定位到机体拼图脚本对或活动 CHR：8×8 模板只改脚本对，图标上传只改 CHR，压缩上传与两项清除同时改脚本对和 CHR。",
            "8×8 模板冷重开脚本正确，14.735 秒运行已晋级黄金；两项压缩上传与两项清除已由资源字节确认，图标上传确认保存为全零无效结果；未解码动作已清零。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    report = analyze()
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    MD_OUT.write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "counts": report["counts"],
                "json": JSON_OUT.relative_to(ROOT).as_posix(),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

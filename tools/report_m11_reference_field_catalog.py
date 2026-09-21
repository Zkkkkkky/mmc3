"""Build the complete 2688-field M11 font catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/verification/legacy-m11-reference-catalog-20260920/catalog.json"
DEFAULT_JSON = ROOT / "output/reports/m11-reference-field-catalog.json"
DEFAULT_MD = ROOT / "output/reports/m11-reference-field-catalog.md"
PAGE_BASES = {page: 0x6C010 + index * 0x1000 for index, page in enumerate(("B8", "B9", "BA", "BB", "C8", "C9", "CA", "CB", "D8", "D9", "DA", "DB"))}


def build(source: dict[str, object]) -> dict[str, object]:
    fields = []
    for page in source["pages"]:
        base = PAGE_BASES[str(page)]
        for row in range(16):
            for column in range(14):
                offset = base + row * 0x100 + column * 18
                fields.append({"field_id": f"M11/glyph/{page}/{row:X}{column:X}", "page": page, "row": row, "column": column, "code": f"{page}{row:X}{column:X}", "offset": offset, "length": 18})
    return {"module": "M11", "classification": "reference_controls_enumerated_page_save_pending", "source_sha256": source["source_sha256"], "controls": source["controls"], "pages": source["pages"], "counts": {"pages": 12, "rows_per_page": 16, "physical_columns_per_row": 14, "alias_columns_per_row": 2, "physical_fields": len(fields), "bytes_per_field": 18, "reserved_bytes_per_row": 4}, "alias_evidence": source["grid_samples"], "fields": fields}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    report = build(json.loads(SOURCE.read_text(encoding="utf-8")))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text("# M11 参考版字段目录\n\n- 12 个页面\n- 2688 个独立 18 字节字模\n- 每行 E/F 两列回指 0 列，不进入字段分母\n- 每行末 4 字节为保留区\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

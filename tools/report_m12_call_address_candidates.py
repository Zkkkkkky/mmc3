"""Compare the reference animation-$02 address list with the current ROM.

This is evidence triage only. An adjacent-byte match is not write authorization.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "references/research/fc资料集-v1.16/page_325.html"
ROM = ROOT / "output/rom/DC_kuorong_464K.nes"
REPORT = ROOT / "output/reports/m12-call-address-candidates.json"
CALL = bytes.fromhex("38 02 02")


def reference_addresses(document: str) -> list[int]:
    match = re.search(r"38\s+02\s+02<BR>(.*?)</FONT></P>", document, re.IGNORECASE | re.DOTALL)
    if match is None:
        raise ValueError("Reference animation-$02 address block was not found")
    addresses = re.findall(r"(?:^|<BR>)\s*([0-9A-F]{5})\b", match.group(1), re.IGNORECASE)
    if not addresses:
        raise ValueError("Reference animation-$02 address block has no addresses")
    return [int(address, 16) for address in addresses]


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    rom_bytes = ROM.read_bytes()
    addresses = reference_addresses(source_bytes.decode("gbk"))
    sites = []
    for address in addresses:
        matches = [
            address + delta
            for delta in (-1, 0, 1)
            if 0 <= address + delta <= len(rom_bytes) - len(CALL)
            and rom_bytes[address + delta:address + delta + len(CALL)] == CALL
        ]
        sites.append({
            "reference_offset": f"0x{address:06X}",
            "exact_match": address in matches,
            "adjacent_matches": [f"0x{site:06X}" for site in matches if site != address],
            "rom_bytes_at_reference": rom_bytes[address:address + 3].hex(" ").upper(),
        })
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "purpose": "Address consistency triage; not a call-site write whitelist",
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest().upper(),
        "rom": str(ROM.relative_to(ROOT)).replace("\\", "/"),
        "rom_sha256": hashlib.sha256(rom_bytes).hexdigest().upper(),
        "expected_call": CALL.hex(" ").upper(),
        "sites": sites,
        "counts": {
            "listed": len(sites),
            "exact": sum(site["exact_match"] for site in sites),
            "adjacent_only": sum(bool(site["adjacent_matches"]) and not site["exact_match"] for site in sites),
            "no_local_match": sum(not site["exact_match"] and not site["adjacent_matches"] for site in sites),
        },
        "candidate_0x38983": next(site for site in sites if site["reference_offset"] == "0x038983"),
        "conclusion": "0x38983 has an adjacent 0x38982 match, but no exact address match or reference save/reopen golden; keep read-only.",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "counts": report["counts"], "candidate": report["candidate_0x38983"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

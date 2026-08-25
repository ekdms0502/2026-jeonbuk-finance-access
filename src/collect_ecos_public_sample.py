"""Collect a reproducible public ECOS sample used as competition source evidence.

The ECOS `sample` key is an official public demonstration key limited to ten
rows.  This snapshot is context evidence only and is not an input to the
distance, typology, or routing models.
"""

from __future__ import annotations

import csv
import json
import urllib.request

from config import DATA_OUT, ROOT


START = "202508"
END = "202605"
RETRIEVED_ON = "2026-08-13"
STAT_CODE = "141Y003"
ITEM_CODE = "200000"
REGION_CODE = "Q00"
PUBLIC_SAMPLE_URL = (
    "https://ecos.bok.or.kr/api/StatisticSearch/sample/json/kr/1/10/"
    f"{STAT_CODE}/M/{START}/{END}/{ITEM_CODE}/{REGION_CODE}"
)
OUTPUT = DATA_OUT / "ecos_jeonbuk_loans_202508_202605.csv"
METADATA = DATA_OUT / "ecos_jeonbuk_loans_metadata.json"


def main() -> int:
    with urllib.request.urlopen(PUBLIC_SAMPLE_URL, timeout=30) as response:
        payload = json.load(response)
    if "RESULT" in payload:
        raise RuntimeError(f"ECOS error: {payload['RESULT']}")
    root = payload["StatisticSearch"]
    rows = root.get("row", [])
    if len(rows) != 10:
        raise RuntimeError(f"expected 10 ECOS sample rows, received {len(rows)}")
    if any(
        row["STAT_CODE"] != STAT_CODE
        or row["ITEM_CODE1"] != ITEM_CODE
        or row["ITEM_CODE2"] != REGION_CODE
        for row in rows
    ):
        raise RuntimeError("ECOS response does not match the declared query contract")

    output_rows = [
        {
            "time": row["TIME"],
            "value_billion_krw": row["DATA_VALUE"],
            "unit": row["UNIT_NAME"],
            "stat_code": row["STAT_CODE"],
            "item_code": row["ITEM_CODE1"],
            "region_code": row["ITEM_CODE2"],
            "institution_code": row["ITEM_CODE3"],
        }
        for row in rows
    ]
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)

    metadata = {
        "source": "한국은행 경제통계시스템 ECOS StatisticSearch",
        "source_docs_url": "https://ecos.bok.or.kr/api/",
        "request_url": PUBLIC_SAMPLE_URL,
        "retrieved_on": RETRIEVED_ON,
        "public_sample_key": True,
        "query": {
            "stat_code": STAT_CODE,
            "cycle": "M",
            "start": START,
            "end": END,
            "item_code": ITEM_CODE,
            "region_code": REGION_CODE,
            "item_order": ["account_item", "region"],
        },
        "row_count": len(output_rows),
        "usage": "competition-required context evidence; not a model input",
        "output_file": str(OUTPUT.relative_to(ROOT)),
    }
    METADATA.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"ECOS public sample: {len(rows)} rows → {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""새마을금고 전북 점포 수집 (kfcc.co.kr 금고위치안내).

공개 웹 목록(list.do?r1=전북&r2=시군)을 시군별로 조회해 CSV로 저장한다.
robots.txt: kfcc.co.kr는 확인 시점(2026-08-11) 차단 규칙이 관찰되지 않았다.
심야(자정 전후)에는 "거래일자 변경" 점검으로 응답이 닫히니 주간에 실행할 것.

출력  data/raw/points/kfcc_mg_jeonbuk.csv
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from config import ROOT, DATA_RAW

BASE = "https://www.kfcc.co.kr/map/list.do"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36",
      "Referer": "https://www.kfcc.co.kr/map/main.do"}
SIGUNGU = ["전주시", "군산시", "익산시", "정읍시", "남원시", "김제시",
           "완주군", "진안군", "무주군", "장수군", "임실군", "순창군", "고창군", "부안군"]


class TableParser(HTMLParser):
    """검색결과 표의 <tr>/<td> 텍스트를 행 단위로 수집."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, _attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def fetch(sgg: str) -> tuple[list[dict], int]:
    q = urllib.parse.urlencode({"r1": "전북", "r2": sgg})
    req = urllib.request.Request(f"{BASE}?{q}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html_text = resp.read().decode("utf-8", errors="replace")
    if "거래일자" in html_text:
        raise RuntimeError("사이트 점검 중 (거래일자 변경) — 주간에 재실행")
    if "존재하지" in html_text:
        return [], 0
    count_match = re.search(r'endElement\s*=\s*parseInt\("(\d+)"\)', html_text)
    if not count_match:
        raise RuntimeError("endElement 원천 건수를 파싱하지 못함")
    expected_count = int(count_match.group(1))
    parser = TableParser()
    parser.feed(html_text)
    out = []
    for row in parser.rows:
        # 실측 형태: [번호(내부데이터), 금고명, 분류, 주소, 전화번호, 이동]
        if len(row) >= 5 and ("전북" in row[3] or "전라북" in row[3]):
            out.append({"금고명": row[1], "분류": row[2], "주소": row[3],
                        "전화번호": row[4], "시군": sgg})
    if len(out) != expected_count:
        raise RuntimeError(f"endElement={expected_count}이지만 표 행수={len(out)}")
    return out, expected_count


def main() -> int:
    all_rows: list[dict] = []
    metadata = []
    for sgg in SIGUNGU:
        try:
            rows, expected_count = fetch(sgg)
        except RuntimeError as e:
            print(f"  {sgg}: 중단 — {e}")
            return 1
        print(f"  {sgg:6s} {len(rows):3d}건")
        all_rows.extend(rows)
        metadata.append({"sigungu": sgg, "endElement": expected_count,
                         "parsed_rows": len(rows), "matched": len(rows) == expected_count})
        time.sleep(0.8)

    # 중복 제거 (금고명+주소)
    seen: set = set()
    uniq = []
    for r in all_rows:
        k = (r["금고명"], r["주소"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)

    out = DATA_RAW / "points" / "kfcc_mg_jeonbuk.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["금고명", "분류", "주소", "전화번호", "시군"],
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(uniq)
    meta_out = DATA_RAW / "points" / "kfcc_collection_metadata.json"
    meta_out.write_text(json.dumps({
        "source": BASE,
        "collection_date": "2026-08-11",
        "regions": metadata,
        "source_rows": len(all_rows),
        "unique_name_address_rows": len(uniq),
        "all_endElement_matches": all(row["matched"] for row in metadata),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n새마을금고 전북 {len(uniq)}건 (원천 {len(all_rows)}) → {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

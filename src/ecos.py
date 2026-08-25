"""한국은행 ECOS API 클라이언트 (대회 필수 데이터).

검증된 통계표
  141Y003  예금은행 지역별 대출금(말잔)   월간 199512~
  141Y002  예금은행 지역별 수신
항목코드
  200000  원화대출금 (계정항목)
  Q00     전북 (지역)  ← 항목 순서는 (계정항목, 지역) 이어야 한다. 뒤집으면 INFO-200.

단독 실행 시 키 검증 + 전북 최근 6개월 조회를 수행한다:
    python3 src/ecos.py
"""

from __future__ import annotations

import json
import urllib.request

from config import get_key

BASE = "https://ecos.bok.or.kr/api"
JEONBUK = "Q00"


def search(stat_code: str, cycle: str, start: str, end: str, *items: str,
           first: int = 1, last: int = 100) -> list[dict]:
    """StatisticSearch 호출. 결과 row 리스트를 반환한다."""
    key = get_key("ECOS_API_KEY")
    path = "/".join([key, "json", "kr", str(first), str(last),
                     stat_code, cycle, start, end, *items])
    url = f"{BASE}/StatisticSearch/{path}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        payload = json.load(resp)
    if "RESULT" in payload:  # 오류 응답
        raise RuntimeError(f"ECOS 오류: {payload['RESULT']}")
    root = next(iter(payload))
    return payload[root].get("row", [])


def jeonbuk_loans(start: str = "202412", end: str = "202605") -> list[dict]:
    """전북 원화대출금(말잔) 월간 시계열."""
    return search("141Y003", "M", start, end, "200000", JEONBUK)


if __name__ == "__main__":
    rows = jeonbuk_loans()
    print(f"ECOS 연결 성공 — {len(rows)}건 수신")
    for r in rows:
        print(f"  {r['TIME']}  {r['ITEM_NAME1']}/{r['ITEM_NAME2']}  "
              f"{float(r['DATA_VALUE']):,.1f} {r['UNIT_NAME']}")

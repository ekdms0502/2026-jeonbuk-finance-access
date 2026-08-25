"""전북 금융 접점 통합 — 공개 목록 4종을 하나의 점포 표로 정규화한다.

원천
  우체국   data/raw/post_offices_utf8.csv        (전국 → 전북 필터)
  은행     data/raw/points/kfb_jeonbuk_full.csv  (= branches ∪ missing20, 검증됨)
  신협     data/raw/points/cu_jeonbuk.csv
  새마을금고 data/raw/points/kfcc_mg_jeonbuk.csv  (직장금고 제외)

범위 한계 (문서화)
  지역농협·축협 단위조합은 전북 전역 공개 목록을 확보하지 못해 제외한다.
  우체국 API 승인 전이므로 2026-08-10 공개 CSV 스냅샷을 사용한다.

출력  data/processed/points_raw.csv
"""

from __future__ import annotations

import csv
import hashlib
import html
import re
import sys
from collections import Counter
from pathlib import Path

from config import ROOT, DATA_RAW, DATA_OUT

# 일반 이용 불가 — 접점에서 제외
EXCLUDE_PAT = re.compile(r"군사우편|군부대")
# 일시 폐쇄·업무중지 — 접점 목록에는 남기되 금융업무 미운영으로 처리
SUSPENDED_PAT = re.compile(r"재건축|업무\s*중지|폐국|휴무")

SIDO_ALIASES = ("전북특별자치도", "전라북도", "전북")

# 전북 14개 시군 (전주는 완산/덕진 구 포함)
SIGUNGU = ["전주시", "군산시", "익산시", "정읍시", "남원시", "김제시",
           "완주군", "진안군", "무주군", "장수군", "임실군", "순창군", "고창군", "부안군"]

# 원천 목록의 명백한 주소 오류는 원천 파일을 덮어쓰지 않고 정정 장부로 관리한다.
SOURCE_CORRECTIONS = [
    {
        "correction_id": "CORR-001",
        "type": "은행",
        "name": "NH농협은행 전북혁신도시지점",
        "field": "주소",
        "source_value": "전북특별자치도 전주시 안전로 163",
        "corrected_value": "전북특별자치도 완주군 이서면 안전로 163",
        "evidence_title": "NH농협은행 공식 채용공고",
        "evidence_url": "https://with.nonghyup.com/jbnf/jbnfDtl.do?jbnfSqno=76719",
        "verification_date": "2026-08-11",
        "reason": "공식 지점 소재지와 도로명주소는 완주군 이서면이나 원천 목록은 전주시로 표기",
    }
]
CORRECTION_BY_KEY = {
    (row["type"], row["name"], row["source_value"]): row for row in SOURCE_CORRECTIONS
}


def norm_addr(addr: str) -> str:
    """주소 정규화: 우편번호·괄호·중복공백 제거, 시도명 통일, 붙어쓴 읍면동 분리."""
    a = addr.strip()
    a = re.sub(r"^\(\d{5}\)\s*", "", a)          # (56438) 제거
    a = re.sub(r"\s*\([^)]*\)\s*", " ", a)        # 남은 괄호구 제거
    for alias in SIDO_ALIASES:
        if a.startswith(alias):
            a = "전북특별자치도" + a[len(alias):]
            break
    # "고창읍동리로" 처럼 읍/면/리 뒤가 붙어있으면 띄운다
    a = re.sub(r"([가-힣]+[읍면])([가-힣]+(?:로|길|대로))", r"\1 \2", a)
    return re.sub(r"\s+", " ", a).strip()


def sigungu_of(addr: str) -> str:
    for s in SIGUNGU:
        if s in addr:
            return s
    return ""


def strip_building(addr: str, name: str) -> str:
    """주소 끝에 붙은 기관명(예: '... 46 고창신협')을 떼어 지오코딩 성공률을 높인다."""
    a = addr
    tail = re.search(r"(\S+)$", a)
    if tail and not re.search(r"\d", tail.group(1)):
        token = tail.group(1)
        if any(t in name for t in (token[:2], token)) or token.endswith(("신협", "금고", "은행", "우체국", "지점", "본점")):
            a = a[: tail.start()].strip()
    return a


def stable_outlet_id(r: dict) -> str:
    raw = "|".join((r["type"], r["name"], r["addr"]))
    return "JB-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12].upper()


def read_csv(path: Path, encodings=("utf-8-sig", "utf-8", "cp949")) -> list[dict]:
    raw = path.read_bytes()
    for enc in encodings:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError(f"인코딩 판별 실패: {path}")
    return list(csv.DictReader(text.splitlines()))


def collect() -> tuple[list[dict], dict]:
    rows: list[dict] = []
    stats = Counter()

    # 1) 우체국 — 전국 파일에서 전북만
    for r in read_csv(DATA_RAW / "post_offices_utf8.csv"):
        addr = (r.get("우체국주소") or "").strip()
        if not any(addr.startswith(a) for a in SIDO_ALIASES):
            continue
        stats["우체국_원본"] += 1
        name = html.unescape((r.get("관내우체국명") or "").strip())
        fin = html.unescape((r.get("금융영업시간") or "").strip())
        if EXCLUDE_PAT.search(name):
            stats["제외_일반이용불가"] += 1
            continue
        suspended = bool(SUSPENDED_PAT.search(name))
        if suspended:
            stats["운영중단_처리"] += 1
        if "미운영" in fin:
            finance_status = "closed_reported"
            finance_open = "N"
            status_basis = "원천 금융영업시간=미운영"
        elif suspended:
            finance_status = "suspended_unverified"
            finance_open = "N"
            status_basis = "원천 기관명의 재건축/업무중지 안내; 현재 상태 미확인"
        elif fin:
            finance_status = "open_reported"
            finance_open = "Y"
            status_basis = "원천에 금융영업시간 기재"
        else:
            finance_status = "unknown"
            finance_open = "N"
            status_basis = "원천 금융영업시간 공란"
        na = norm_addr(addr)
        # 이름 끝 괄호 안내문은 지오코딩·표기에 방해되므로 분리 보존
        base_name = re.sub(r"\s*\(.*$", "", name).strip() or name
        rows.append({
            "type": "우체국", "name": base_name, "addr": na,
            "addr_geo": strip_building(na, base_name),
            "sigungu": sigungu_of(na), "detail": (fin + (" / " + name[len(base_name):].strip() if suspended else "")).strip(),
            "finance_open": finance_open, "finance_status": finance_status,
            "status_basis": status_basis,
            "source_correction_id": "",
            "source": "우정사업본부 우체국 정보",
            "source_snapshot": "2026-08-10",
        })

    # 2) 은행
    for r in read_csv(DATA_RAW / "points" / "kfb_jeonbuk_full.csv"):
        stats["은행_원본"] += 1
        name = f"{(r.get('은행') or '').strip()} {(r.get('지점') or '').strip()}".strip()
        source_na = norm_addr((r.get("주소") or "").strip())
        correction = CORRECTION_BY_KEY.get(("은행", name, source_na))
        na = correction["corrected_value"] if correction else source_na
        if correction:
            stats["원천주소_공식정정"] += 1
        rows.append({
            "type": "은행", "name": name, "addr": na,
            "addr_geo": strip_building(na, name),
            "sigungu": sigungu_of(na), "detail": (r.get("전화번호") or "").strip(),
            "finance_open": "Y", "finance_status": "listed_assumed_open",
            "status_basis": "공시 점포목록 등재; 실시간 영업상태 미확인",
            "source_correction_id": correction["correction_id"] if correction else "",
            "source": "전국은행연합회 공시 점포현황(2025.12말) 열람 집계",
            "source_snapshot": "2026-08-10",
        })

    # 3) 신협
    for r in read_csv(DATA_RAW / "points" / "cu_jeonbuk.csv"):
        stats["신협_원본"] += 1
        name = f"{(r.get('조합명') or '').strip()} {(r.get('점포구분') or '').strip()}".strip()
        na = norm_addr((r.get("주소") or "").strip())
        rows.append({
            "type": "신협", "name": name, "addr": na,
            "addr_geo": strip_building(na, name),
            "sigungu": sigungu_of(na), "detail": (r.get("구분") or "").strip(),
            "finance_open": "Y", "finance_status": "listed_assumed_open",
            "status_basis": "중앙회 점포조회 등재; 실시간 영업상태 미확인",
            "source_correction_id": "",
            "source": "신협중앙회 점포 조회",
            "source_snapshot": "2026-08-10",
        })

    # 4) 새마을금고 (직장금고는 해당 직장 임직원 전용이라 제외)
    mg_path = DATA_RAW / "points" / "kfcc_mg_jeonbuk.csv"
    if mg_path.exists():
        for r in read_csv(mg_path):
            stats["새마을금고_원본"] += 1
            cls = (r.get("분류") or "").strip()
            if cls == "직장":
                stats["새마을금고_직장금고제외"] += 1
                continue
            name = f"{(r.get('금고명') or '').strip()} 새마을금고".replace("  ", " ")
            na = norm_addr((r.get("주소") or "").strip())
            rows.append({
                "type": "새마을금고", "name": name, "addr": na,
                "addr_geo": strip_building(na, name),
                "sigungu": sigungu_of(na), "detail": cls,
                "finance_open": "Y", "finance_status": "listed_assumed_open",
                "status_basis": "중앙회 공개 목록 등재; 실시간 영업상태 미확인",
                "source_correction_id": "",
                "source": "새마을금고중앙회 금고위치안내 (2026-08-11 조회)",
                "source_snapshot": "2026-08-11",
            })

    # 중복 제거 — (기관유형, 이름, 주소) 완전 동일건
    seen: dict[tuple, dict] = {}
    dupes: list[dict] = []
    for r in rows:
        key = (r["type"], r["name"], r["addr"])
        if key in seen:
            dupes.append(r)
            stats[f"{r['type']}_중복제거"] += 1
        else:
            seen[key] = r
    uniq = list(seen.values())
    for r in uniq:
        r["outlet_id"] = stable_outlet_id(r)

    # 같은 유형·같은 주소인데 이름만 다른 건 (표기 흔들림 의심) 표시
    by_addr: dict[tuple, list[dict]] = {}
    for r in uniq:
        by_addr.setdefault((r["type"], r["addr"]), []).append(r)
    stats["동일주소_다른이름_그룹"] = sum(1 for v in by_addr.values() if len(v) > 1)

    for r in uniq:
        stats[f"{r['type']}_최종"] += 1
        if not r["sigungu"]:
            stats["시군_미판별"] += 1
    return uniq, dict(stats)


def main() -> int:
    rows, stats = collect()
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    out = DATA_OUT / "points_raw.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["outlet_id", "type", "name", "addr", "addr_geo",
                        "sigungu", "detail", "finance_open", "finance_status",
                        "status_basis", "source_correction_id", "source", "source_snapshot"],
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(rows)

    applied_ids = {row["source_correction_id"] for row in rows if row["source_correction_id"]}
    corrections = [row for row in SOURCE_CORRECTIONS if row["correction_id"] in applied_ids]
    corrections_out = DATA_OUT / "source_corrections.csv"
    with corrections_out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=list(SOURCE_CORRECTIONS[0].keys()), lineterminator="\n"
        )
        w.writeheader()
        w.writerows(corrections)

    print(f"통합 접점 {len(rows)}건 → {out.relative_to(ROOT)}")
    for k in sorted(stats):
        print(f"  {k:24s} {stats[k]}")
    per = Counter(r["sigungu"] or "(미판별)" for r in rows)
    print("\n시군별 접점 수")
    for s in SIGUNGU:
        n = per.get(s, 0)
        flag = "  ← 없음" if n == 0 else ""
        print(f"  {s:6s} {n:4d}{flag}")
    if per.get("(미판별)"):
        print(f"  (미판별) {per['(미판별)']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

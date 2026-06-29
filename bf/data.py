# -*- coding: utf-8 -*-
"""bf.data — 데이터 로딩(샘플/실API)과 §2 표준 스키마 정규화.

★단일 진입점은 ``load_daily()``. 앱은 이 함수만 호출한다.
실데이터 전환은 ``load_from_api(keys)`` 한 함수 구현으로 끝난다(§5).

계층 분리(원칙 #4): **이 모듈은 ``st.secrets`` 를 import 하지 않는다.**
키는 호출자(app.py)가 ``keys`` dict 로 주입한다(§3.5, §5.2-5).

반환 스키마(§2, 불변):
    DataFrame[date(datetime64), item(str), retail(원/kg), wholesale(원/kg), volume(float)]
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .catalog import ITEMS, normalize_price, unit_to_kg, build_wholesale_index

SCHEMA = ["date", "item", "retail", "wholesale", "volume"]
_RECENT_DAYS = 7   # §3.1 '현재' 창과 동일 — 샘플 스토리를 최근 7일에 주입


# ── 샘플 스토리(시연 보증) ─────────────────────────────────────────────────
# 최근 7일에 적용할 (가격배수, 반입량배수). 명세서 §8 회귀 보증:
#   양파=과잉(공급 급증+가격 폭락), 사과=대기(가격 상승), 시금치=주의(변동성).
# 실연동(source="api")에서는 사용하지 않는다(리스크 #5).
SAMPLE_STORY: dict[str, dict] = {
    "양파": {"price_factor": 0.76, "vol_factor": 1.48},   # 과잉
    "배추": {"price_factor": 0.82, "vol_factor": 1.36},   # 과잉(가을 출하)
    "배": {"price_factor": 0.86, "vol_factor": 1.10},     # 구매추천(저렴)
    "무": {"price_factor": 0.93, "vol_factor": 1.12},
    "감자": {"price_factor": 0.98, "vol_factor": 1.00},
    "대파": {"price_factor": 1.02, "vol_factor": 0.95},
    "마늘": {"price_factor": 1.00, "vol_factor": 1.00},
    "당근": {"price_factor": 1.08, "vol_factor": 0.92},
    "시금치": {"price_factor": 1.00, "vol_factor": 0.90, "volatile": 0.14},  # 주의
    "사과": {"price_factor": 1.22, "vol_factor": 0.80},   # 대기(상승)
}


def load_daily(source: str = "sample", keys: dict | None = None,
               end=None, days: int = 90) -> pd.DataFrame:
    """표준 일별 DataFrame 반환(§2). source 로 샘플/실API 전환.

    Parameters
    ----------
    source : "sample" | "api"
    keys   : 실API 키 dict (source="api" 시 필수). app.py 가 주입.
    end    : 마지막 일자(기본=오늘). days : 조회 기간(기준선 계산에 ≥60일 필요).
    """
    if source == "sample":
        return _load_sample(end=end, days=days)
    if source == "api":
        if not keys:
            raise ValueError("source='api' 에는 keys dict 가 필요합니다(§3.5).")
        return load_from_api(keys, end=end, days=days)
    raise ValueError(f"알 수 없는 source: {source!r} (sample|api)")


# ── 샘플 합성 ──────────────────────────────────────────────────────────────
def _load_sample(end=None, days: int = 90, seed: int = 42) -> pd.DataFrame:
    """결정론적 합성 데이터(시연·테스트용). seed 고정으로 재현 가능."""
    end = (pd.Timestamp(end) if end is not None else pd.Timestamp.today()).normalize()
    dates = pd.date_range(end - pd.Timedelta(days=days - 1), end, freq="D")
    rng = np.random.default_rng(seed)

    rows: list[tuple] = []
    for item, meta in ITEMS.items():
        story = SAMPLE_STORY.get(item, {})
        pf = story.get("price_factor", 1.0)
        vf = story.get("vol_factor", 1.0)
        volatile = story.get("volatile", 0.0)
        base_retail = float(meta.base_retail)
        base_vol = 100.0

        for i, d in enumerate(dates):
            in_recent = (end - d).days < _RECENT_DAYS
            # 완만한 추세 + 주기 변동(기준선이 평평하지 않게)
            p = base_retail * (1 + 0.03 * np.sin(i / 14.0))
            v = base_vol * (1 + 0.06 * np.sin(i / 9.0))
            if in_recent:
                p *= pf
                v *= vf
                if volatile:
                    p *= (1 + rng.normal(0, volatile))   # '주의' 변동성
            p *= (1 + rng.normal(0, 0.02))
            v *= (1 + rng.normal(0, 0.04))
            retail = max(1, round(p))
            wholesale = max(1, round(p * 0.70))   # 도매 ≈ 소매의 70%
            rows.append((d, item, retail, wholesale, round(max(1.0, v), 1)))

    return pd.DataFrame(rows, columns=SCHEMA)


# ══════════════════════════════════════════════════════════════════════════
#  실연동 (§5) — data.go.kr B552845(aT) 3종 → 원/kg 정규화 → §2 스키마
#  · 가격(②): perRegion/price — 조사일'환산'평균가격(원/kg) 제공(리스크 #6 해소).
#  · 반입량(①): katRealTime2/trades2 — 일자별 경매 수량×단위물량 → 일 반입량.
#  · 코드(③): katCode/goods — 품목명↔상품중분류코드 런타임 해석(반입량 필터용).
#  · 인증은 data.go.kr serviceKey 1개(=keys["data_go_kr"]). KAMIS 직통키는 선택.
#  · 네트워크 호출부와 파싱부를 분리해 파싱을 픽스처로 테스트한다(§5.3).
#  · 모든 엔드포인트/필드명은 동봉 공식 API 명세서(xlsx)로 확정(임의 추정 금지).
#  ⚠️ data.go.kr 키는 **Decoding(일반 인증키)** 을 사용한다 — requests 가 파라미터를
#     재인코딩하므로 Encoding 키를 넣으면 이중 인코딩으로 인증 실패한다.
# ══════════════════════════════════════════════════════════════════════════
# (legacy) KAMIS 직통 — verify_catalog_codes 코드 점검에만 사용.
KAMIS_PRICE_URL = "https://www.kamis.or.kr/service/price/xml.do?action=periodProductList"

# ② 지역별 품목별 도·소매 가격정보 (서비스 perRegion / 오퍼레이션 price)
PRICE_URL = "https://apis.data.go.kr/B552845/perRegion/price"
PRICE_SE_RETAIL = "01"        # 구분코드: 소매
PRICE_SE_WHOLESALE = "02"     # 구분코드: 중도매
PRICE_SGG_DEFAULT = "1101"    # 시군구코드(필수): 서울 — 농산물은 전국코드 미지원
PRICE_GRADE_DEFAULT = "04"    # 등급코드: 상품(대표 소비등급)
PRICE_FIELD_DATE = "exmn_ymd"               # 조사일자(YYYYMMDD)
PRICE_FIELD_AVG = "exmn_dd_avg_prc"         # 조사일평균가격(원/조사단위) — 단위정규화 입력
PRICE_FIELD_UNIT = "unit"                   # 단위(kg/개/포기/g …)
PRICE_FIELD_UNITSZ = "unit_sz"              # 단위크기(배수: 10개·100g 등)
PRICE_FIELD_CNVS_AVG = "exmn_dd_cnvs_avg_prc"  # 조사일'환산'가 — 단위가 품목별 상이(verify용)


def load_from_api(keys: dict, end=None, days: int = 90) -> pd.DataFrame:
    """실API → §2 스키마. 키는 dict 주입(secrets 비의존).

    keys = {"data_go_kr": …}  (필수)  ·  KAMIS 직통키는 선택.
    가격(②)은 항상 수집. 반입량(①)은 코드 해석·네트워크 성공 시에만 합류하고
    실패하면 빈 프레임 → 가격만으로 동작(과잉 신호만 자연 비활성).
    """
    import requests  # 지연 import — 테스트/샘플 경로에서 불필요

    end = (pd.Timestamp(end) if end is not None else pd.Timestamp.today()).normalize()
    start = end - pd.Timedelta(days=days - 1)

    price_df = _collect_prices(keys, start, end, session=requests)
    if ENABLE_WHOLESALE_VOLUME:
        volume_df = _collect_volume(keys, start, end, session=requests)
    else:
        volume_df = pd.DataFrame(columns=["date", "item", "volume"])
    return _merge_normalize(price_df, volume_df)


def _collect_prices(keys: dict, start, end, session) -> pd.DataFrame:
    """perRegion/price 로 소매(01)·중도매(02) 일별 환산가(원/kg) 수집.

    반환 [date,item,retail,wholesale]. 환산평균가격은 데이터셋이 kg 기준으로
    제공하므로 추가 단위환산 불필요(리스크 #6 해소). 품목당 품종/지역 다건은
    _parse_price_records 가 일자별 평균으로 합친다.
    """
    if not keys.get("data_go_kr"):
        raise ValueError("data.go.kr 키 누락: data_go_kr (§5.2-5)")

    frames: list[pd.DataFrame] = []
    for se_code, col in ((PRICE_SE_RETAIL, "retail"), (PRICE_SE_WHOLESALE, "wholesale")):
        recs: list[dict] = []
        for item, meta in ITEMS.items():
            if not (meta.price_ctgry and meta.price_item):
                continue   # 가격 코드 미등록 품목 스킵(가드)
            records = _fetch_price_records(keys, meta, se_code, start, end, session)
            recs.extend(_parse_price_records(records, item))
        frames.append(pd.DataFrame(recs, columns=["date", "item", "price"])
                      .rename(columns={"price": col}))

    retail_df, whole_df = frames
    if retail_df.empty and whole_df.empty:
        return pd.DataFrame(columns=["date", "item", "retail", "wholesale"])
    return pd.merge(retail_df, whole_df, on=["date", "item"], how="outer")


def _fetch_price_records(keys: dict, meta, se_code: str, start, end, session) -> list[dict]:
    """perRegion/price 단일 (품목·구분) 기간조회 → item dict 리스트(페이지 합본).

    필터(cond[...]): 조사일자 범위(GTE/LTE) · 부류 · 품목 · 구분 · 시군구 · 등급.
    """
    out: list[dict] = []
    page = 1
    while True:
        params = {
            "serviceKey": keys["data_go_kr"], "returnType": "json",
            "numOfRows": 1000, "pageNo": page,
            "cond[exmn_ymd::GTE]": start.strftime("%Y%m%d"),
            "cond[exmn_ymd::LTE]": end.strftime("%Y%m%d"),
            "cond[ctgry_cd::EQ]": meta.price_ctgry,
            "cond[item_cd::EQ]": meta.price_item,
            "cond[se_cd::EQ]": se_code,
            "cond[sgg_cd::EQ]": PRICE_SGG_DEFAULT,
            "cond[grd_cd::EQ]": PRICE_GRADE_DEFAULT,
        }
        if meta.price_vrty:   # 이질 품종 혼입 방지(예: 대파에서 쪽파 제외)
            params["cond[vrty_cd::EQ]"] = meta.price_vrty
        resp = session.get(PRICE_URL, params=params, timeout=10)
        resp.raise_for_status()
        items = _extract_items(resp)
        out.extend(items)
        if len(items) < 1000 or page >= 20:   # 안전 상한
            break
        page += 1
    return out


def _parse_price_records(records, item: str) -> list[dict]:
    """perRegion 응답 → [{date,item,price(원/kg)}]. 평균가를 **원/kg 정규화**.

    perRegion 의 환산가(cnvs)는 품목별 환산단위가 달라(kg/포기/개/10개…) 직접
    쓰면 안 된다. 대신 평균가(avg, 원/조사단위)를 단위로 나눠 원/kg 로 환산한다:
        원/kg = avg ÷ (unit_sz × unit_to_kg(item, unit))      # 리스크 #6
    같은 날 여러 품종/지역 행은 원/kg 산술평균으로 합친다. 단위 미매핑·0·결측은
    제외(조용히 버리지 말고 운영 시 로깅 권장).
    """
    acc: dict = {}
    for rec in records:
        date = _parse_date(str(rec.get(PRICE_FIELD_DATE) or ""))
        if date is None:
            continue
        try:
            price = float(str(rec.get(PRICE_FIELD_AVG) or "").replace(",", "").strip())
            usz_raw = str(rec.get(PRICE_FIELD_UNITSZ) or "").replace(",", "").strip()
            unit_sz = float(usz_raw) if usz_raw else 1.0
        except ValueError:
            continue
        if price <= 0 or unit_sz <= 0:
            continue
        unit = str(rec.get(PRICE_FIELD_UNIT) or "kg").strip() or "kg"
        try:
            kg = unit_sz * unit_to_kg(item, unit)
        except KeyError:
            continue   # 단위 환산표 미등록 — 추정 금지(스킵, 운영 시 로깅 권장)
        if kg <= 0:
            continue
        acc.setdefault(date, []).append(price / kg)
    return [{"date": d, "item": item, "price": round(sum(v) / len(v))}
            for d, v in acc.items()]


def _parse_kamis_xml(xml_text: str, item: str) -> list[dict]:
    """KAMIS XML(item 엘리먼트) → [{date,item,price(원/kg)}]. 단위는 원/kg 정규화."""
    import xml.etree.ElementTree as ET

    out: list[dict] = []
    root = ET.fromstring(xml_text)
    for node in root.iter("item"):
        ymd = _node_text(node, "regday") or _node_text(node, "yyyy")
        raw_price = _node_text(node, "price") or _node_text(node, "dpr1")
        unit = _node_text(node, "unit") or "kg"
        if not (ymd and raw_price):
            continue
        try:
            price = float(str(raw_price).replace(",", ""))
        except ValueError:
            continue
        date = _parse_date(ymd)
        if date is None:
            continue
        try:
            won_per_kg = normalize_price(item, price, unit)
        except (KeyError, ValueError):
            continue   # 단위 매핑 누락 — 조용히 버리지 말고 로그 권장(운영 시)
        out.append({"date": date, "item": item, "price": round(won_per_kg)})
    return out


def _node_text(node, tag: str):
    el = node.find(tag)
    return el.text.strip() if el is not None and el.text else None


def _parse_date(s: str):
    """'YYYY-MM-DD' / 'YYYYMMDD' / 'YYYY.MM.DD' 등 → Timestamp. 실패 시 None.

    KAMIS·도매시장 응답 모두 이 파서를 공유한다(일자 표기 변형 흡수).
    """
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return pd.Timestamp(pd.to_datetime(s, format=fmt))
        except (ValueError, TypeError):
            continue
    try:
        return pd.Timestamp(pd.to_datetime(s))
    except (ValueError, TypeError):
        return None


# ── ① 전국 공영도매시장 실시간 경매정보 (서비스 katRealTime2 / 오퍼레이션 trades2) ──
#  응답 코드/수량 필드(공식 명세): gds_lclsf_cd/gds_mclsf_cd/gds_sclsf_cd(품목 대/중/소
#  분류), whsl_mrkt_cd(도매시장), unit_cd(단위), qty(수량), unit_qty(단위물량).
#  일 반입량 ≈ Σ(qty × unit_qty). 품목은 (대분류,중분류) 쌍으로 식별한다(중분류코드는
#  대분류 안에서만 유일 — 단일 코드로 조회하면 타품목이 섞임). 거래정산일자는 EQ·필수.
WHOLESALE_VOLUME_URL = "https://apis.data.go.kr/B552845/katRealTime2"
VOLUME_OPERATION = "trades2"
VOL_FIELD_DATE = "trd_clcln_ymd"   # 거래정산일자(YYYY-MM-DD)
VOL_FIELD_LCLSF = "gds_lclsf_cd"   # 상품대분류코드 (품목 식별 1)
VOL_FIELD_MCLSF = "gds_mclsf_cd"   # 상품중분류코드 (품목 식별 2)
VOL_FIELD_QTY = "qty"              # 수량(낙찰 단위 수)
VOL_FIELD_UNITQTY = "unit_qty"     # 단위물량(단위당 kg 등) — qty×unit_qty=물량
#  반입량 합류 스위치(기본 OFF). trades2 는 (품목×일자)별 조회이고 품목당 일 1,000건
#  초과(다중 페이지)라, 60일 기준선을 라이브로 모으면 수천 콜 → 개발쿼터(10,000/일)·
#  로딩 지연이 비현실적. True 로 켜면 실 반입량으로 '과잉' 신호까지 동작하지만 첫 로딩이
#  느리고 쿼터를 크게 쓴다(운영은 야간 배치 누적 권장). OFF 면 실가격만으로 동작.
ENABLE_WHOLESALE_VOLUME = False


def _collect_volume(keys: dict, start, end, session, index=None) -> pd.DataFrame:
    """경매 API → [date,item,volume]. (대분류,중분류) 쌍으로 품목 매핑(§5.2-3).

    빈 프레임 반환(가격만으로 앱 동작) 조건: data_go_kr 키 없음 · catalog 에 경매
    코드(vol_lclsf/vol_mclsf) 미등록. 네트워크 호출부 _fetch_volume_records, 파싱부
    _parse_volume_records 로 분리해 후자를 픽스처로 테스트한다(§5.3).
    """
    if not keys.get("data_go_kr"):
        return pd.DataFrame(columns=["date", "item", "volume"])
    idx = index if index is not None else build_wholesale_index()
    if not idx:
        return pd.DataFrame(columns=["date", "item", "volume"])  # 코드 미등록
    records = _fetch_volume_records(keys, start, end, session, idx)
    return _parse_volume_records(records, idx)


def _fetch_volume_records(keys: dict, start, end, session, index) -> list[dict]:
    """trades2 호출 → 레코드 dict 리스트. (대분류,중분류)×일자 루프(정산일자 EQ·필수).

    index 키는 (gds_lclsf_cd, gds_mclsf_cd) 쌍. 기간 내 각 일자를 두 코드로 필터해
    조회하고 응답을 [{필드:값}, …] 평면 dict 리스트로 합본해 돌려준다.
    """
    base = f"{WHOLESALE_VOLUME_URL.rstrip('/')}/{VOLUME_OPERATION}"
    records: list[dict] = []
    days = pd.date_range(start, end, freq="D")
    for lclsf, mclsf in index:
        for day in days:
            page = 1
            while True:
                params = {
                    "serviceKey": keys["data_go_kr"], "returnType": "json",
                    "numOfRows": 1000, "pageNo": page,
                    "cond[trd_clcln_ymd::EQ]": day.strftime("%Y-%m-%d"),
                    f"cond[{VOL_FIELD_LCLSF}::EQ]": lclsf,
                    f"cond[{VOL_FIELD_MCLSF}::EQ]": mclsf,
                }
                resp = session.get(base, params=params, timeout=10)
                resp.raise_for_status()
                items = _extract_items(resp)
                records.extend(items)
                if len(items) < 1000 or page >= 30:
                    break
                page += 1
    return records


def _extract_items(resp) -> list[dict]:
    """data.go.kr 응답(JSON 우선, XML 폴백) → item dict 리스트로 평탄화."""
    try:
        body = resp.json().get("response", {}).get("body", {})
        items = (body.get("items") or {}).get("item", [])
        return items if isinstance(items, list) else [items]
    except (ValueError, AttributeError):
        import xml.etree.ElementTree as ET
        out: list[dict] = []
        for node in ET.fromstring(resp.text).iter("item"):
            out.append({c.tag: (c.text or "").strip() for c in node})
        return out


def _parse_volume_records(records, code_index: dict | None = None
                          ) -> pd.DataFrame:
    """경매 응답 레코드(list[dict]) → [date,item,volume]. (대분류,중분류)로 매핑.

    · code_index: (gds_lclsf_cd, gds_mclsf_cd) → 품목명(기본 catalog 전체). 미등록
      코드 쌍은 스킵(§6-3).
    · 동일 (date,item) 다건은 합산(여러 시장·법인·등급 → 일 반입량 합).
    · 물량 = qty × unit_qty(단위물량). unit_qty 결측이면 qty 그대로(프록시).
    · 수량 파싱 실패/일자 결측 레코드는 조용히 버리지 말고 운영 시 로깅 권장.
    """
    idx = code_index if code_index is not None else build_wholesale_index()
    agg: dict[tuple, float] = {}
    for rec in records:
        key = (str(rec.get(VOL_FIELD_LCLSF)), str(rec.get(VOL_FIELD_MCLSF)))
        item = idx.get(key)
        if item is None:
            continue   # 미등록 코드 쌍 — 가드(§6-3)
        date = _parse_date(str(rec.get(VOL_FIELD_DATE) or ""))
        if date is None:
            continue
        try:
            qty = float(str(rec.get(VOL_FIELD_QTY)).replace(",", ""))
        except (TypeError, ValueError):
            continue
        unit_qty = rec.get(VOL_FIELD_UNITQTY)
        if unit_qty not in (None, ""):
            try:
                qty *= float(str(unit_qty).replace(",", ""))
            except (TypeError, ValueError):
                pass   # 단위물량 파싱 실패 시 수량만 사용
        agg[(date, item)] = agg.get((date, item), 0.0) + qty
    rows = [{"date": d, "item": it, "volume": v} for (d, it), v in agg.items()]
    return pd.DataFrame(rows, columns=["date", "item", "volume"])


# ── KAMIS 코드 검증 헬퍼 (§5.2-1 — KAMIS 는 코드조회 API 가 없음) ───────────
#  KAMIS 코드는 공식 '농축수산물 품목 및 등급 코드표'(다운로드)에서 취득해
#  catalog 의 kamis_category/kamis_item 에 채운다. 채운 코드가 실제로 데이터를
#  반환하는지 라이브로 점검해 오타·잘못된 코드를 표면화하는 것이 이 헬퍼다
#  (임의 추정 금지 원칙의 운영 보조 — 추정 대신 실데이터로 확인).
#  참고용 공식 부류코드(category): 100 식량작물 · 200 채소류 · 300 특용작물 ·
#  400 과일류 · 500 축산물 · 600 수산물. 품목코드는 코드표에서 확인할 것.
KAMIS_CATEGORY_CODES: dict[str, str] = {
    "100": "식량작물", "200": "채소류", "300": "특용작물",
    "400": "과일류", "500": "축산물", "600": "수산물",
}


def verify_catalog_codes(keys: dict, *, end=None, days: int = 14,
                         session=None) -> dict[str, dict]:
    """채워 넣은 KAMIS 코드가 실데이터를 반환하는지 라이브 점검.

    각 품목을 KAMIS periodProductList(소매)로 조회해 레코드 유무를 보고한다.
    반환: {item: {category, item_code, ok(bool), rows(int), error(str|None)}}.
    코드 미등록 품목은 ok=False + 안내 메시지. 운영자가 코드표로 채운 뒤 실행한다.
    """
    if session is None:
        import requests
        session = requests
    cert_key = keys.get("kamis_cert_key")
    cert_id = keys.get("kamis_cert_id")
    if not (cert_key and cert_id):
        raise ValueError("KAMIS 키 누락: kamis_cert_key / kamis_cert_id (§5.2-5)")

    end = (pd.Timestamp(end) if end is not None else pd.Timestamp.today()).normalize()
    start = end - pd.Timedelta(days=days - 1)
    report: dict[str, dict] = {}
    for item, meta in ITEMS.items():
        info = {"category": meta.kamis_category, "item_code": meta.kamis_item,
                "ok": False, "rows": 0, "error": None}
        if not meta.kamis_item:
            info["error"] = "코드 미등록 — 공식 품목 코드표에서 채우세요(§5.2-1)"
            report[item] = info
            continue
        try:
            params = {
                "p_cert_key": cert_key, "p_cert_id": cert_id, "p_returntype": "xml",
                "p_startday": start.strftime("%Y-%m-%d"),
                "p_endday": end.strftime("%Y-%m-%d"),
                "p_product_cls_code": "01",
                "p_item_category_code": meta.kamis_category or "",
                "p_itemcode": meta.kamis_item,
            }
            resp = session.get(KAMIS_PRICE_URL, params=params, timeout=10)
            resp.raise_for_status()
            rows = _parse_kamis_xml(resp.text, item)
            info["rows"] = len(rows)
            info["ok"] = len(rows) > 0
            if not rows:
                info["error"] = "응답 0건 — 코드/기간/단위 매핑 확인"
        except Exception as exc:   # noqa: BLE001 — 점검 도구는 품목별 실패를 격리 보고
            info["error"] = str(exc)
        report[item] = info
    return report


def verify_price_api(keys: dict, *, end=None, days: int = 7, session=None) -> dict:
    """perRegion/price 라이브 점검 — 코드·환산단위 가정을 실데이터로 확인.

    각 품목의 소매(01) 최근 데이터를 조회해 레코드 유무, 그리고 unit/unit_sz 와
    환산평균가격 표본을 함께 보고한다. **환산가격이 원/kg 인지**는 unit 표본으로
    확인할 수 있다(추정 대신 실데이터로 확인 — §5.1). catalog 가격 코드가 실제로
    데이터를 반환하는지 검증하는 용도.
    반환: {item: {ok, rows, sample_unit, sample_cnvs, error}}.
    """
    if session is None:
        import requests
        session = requests
    if not keys.get("data_go_kr"):
        raise ValueError("data.go.kr 키 누락: data_go_kr (§5.2-5)")

    end = (pd.Timestamp(end) if end is not None else pd.Timestamp.today()).normalize()
    start = end - pd.Timedelta(days=days - 1)
    report: dict[str, dict] = {}
    for item, meta in ITEMS.items():
        info = {"item_cd": meta.price_item, "ok": False, "rows": 0,
                "sample_unit": None, "sample_cnvs": None, "error": None}
        if not (meta.price_ctgry and meta.price_item):
            info["error"] = "가격 코드 미등록"
            report[item] = info
            continue
        try:
            recs = _fetch_price_records(keys, meta, PRICE_SE_RETAIL, start, end, session)
            info["rows"] = len(recs)
            info["ok"] = len(recs) > 0
            if recs:
                r0 = recs[0]
                unit = (str(r0.get("unit") or "").strip()
                        + str(r0.get("unit_sz") or "").strip())
                info["sample_unit"] = unit or None
                info["sample_cnvs"] = r0.get(PRICE_FIELD_CNVS_AVG)
            else:
                info["error"] = "응답 0건 — 코드/기간/시군구·등급 확인"
        except Exception as exc:   # noqa: BLE001 — 품목별 실패 격리 보고
            info["error"] = str(exc)
        report[item] = info
    return report


def _merge_normalize(price_df: pd.DataFrame, volume_df: pd.DataFrame) -> pd.DataFrame:
    """(date,item) outer 병합 → §2 스키마. 결측 보간/정리."""
    if price_df is None or price_df.empty:
        return pd.DataFrame(columns=SCHEMA)

    df = price_df.copy()
    if volume_df is not None and not volume_df.empty:
        df = pd.merge(df, volume_df, on=["date", "item"], how="outer")
    if "volume" not in df.columns:
        df["volume"] = float("nan")
    if "wholesale" not in df.columns:
        df["wholesale"] = df.get("retail")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["item", "date"])
    # 품목 내 시간축 결측은 보간/전후방 채움(반입량 누락 대비)
    for col in ("retail", "wholesale", "volume"):
        df[col] = df.groupby("item")[col].transform(
            lambda s: s.interpolate().ffill().bfill())
    # 반입량 전무하면 중립값(과잉 신호는 0으로 자연 비활성)
    df["volume"] = df["volume"].fillna(100.0)
    df = df.dropna(subset=["retail"])

    df["item"] = df["item"].astype(str)
    df["retail"] = df["retail"].round().astype(int)
    df["wholesale"] = df["wholesale"].round().astype(int)
    df["volume"] = df["volume"].astype(float)
    return df[SCHEMA].reset_index(drop=True)


def validate_schema(df: pd.DataFrame) -> pd.DataFrame:
    """§2 계약 검증 — 컬럼/타입/품목 정규화 확인. 위반 시 AssertionError."""
    assert list(df.columns) == SCHEMA, f"스키마 컬럼 위반: {list(df.columns)}"
    assert pd.api.types.is_datetime64_any_dtype(df["date"]), "date 는 datetime64 여야 함"
    bad = set(df["item"]) - set(ITEMS)
    assert not bad, f"카탈로그 외 품목(정규화 위반): {bad}"
    return df

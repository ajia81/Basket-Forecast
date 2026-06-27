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

from .catalog import ITEMS, normalize_price, build_wholesale_index

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
#  실연동 (§5) — KAMIS 가격 + 도매 반입량 → 원/kg 정규화 → §2 스키마
#  · 네트워크 호출부와 파싱/정규화부를 분리해 파싱·정규화를 픽스처로 테스트한다(§5.3).
#  · 엔드포인트/파라미터/코드값은 현행 공식 문서로 확인(임의 추정 금지, §5.1 주의).
# ══════════════════════════════════════════════════════════════════════════
KAMIS_PRICE_URL = "https://www.kamis.or.kr/service/price/xml.do?action=periodProductList"
# data.go.kr 도매시장 반입량 계열(B552895 등) — 운영자가 현행 엔드포인트로 교체.
WHOLESALE_VOLUME_URL = "https://apis.data.go.kr/B552895/..."


def load_from_api(keys: dict, end=None, days: int = 90) -> pd.DataFrame:
    """실API → §2 스키마. 키는 dict 주입(secrets 비의존).

    keys = {"kamis_cert_key":…, "kamis_cert_id":…, "data_go_kr":…}
    """
    import requests  # 지연 import — 테스트/샘플 경로에서 불필요

    end = (pd.Timestamp(end) if end is not None else pd.Timestamp.today()).normalize()
    start = end - pd.Timedelta(days=days - 1)

    price_df = _collect_kamis_prices(keys, start, end, session=requests)
    volume_df = _collect_volume(keys, start, end, session=requests)
    return _merge_normalize(price_df, volume_df)


def _collect_kamis_prices(keys: dict, start, end, session) -> pd.DataFrame:
    """KAMIS 기간조회로 소매(01)·도매(02) 일별가 수집 → [date,item,retail,wholesale].

    가격은 품목별 단위가 상이하므로 normalize_price()로 **원/kg 환산**(리스크 #6).
    """
    cert_key = keys.get("kamis_cert_key")
    cert_id = keys.get("kamis_cert_id")
    if not (cert_key and cert_id):
        raise ValueError("KAMIS 키 누락: kamis_cert_key / kamis_cert_id (§5.2-5)")

    frames: list[pd.DataFrame] = []
    for cls_code, col in (("01", "retail"), ("02", "wholesale")):
        recs: list[dict] = []
        for item, meta in ITEMS.items():
            if not meta.kamis_item:
                # 코드 미등록 — 공식 코드조회 API에서 취득 후 catalog 채울 것(§5.2-1)
                raise ValueError(
                    f"'{item}' KAMIS 코드 미등록. 공식 코드조회로 catalog 를 먼저 채우세요.")
            params = {
                "p_cert_key": cert_key, "p_cert_id": cert_id, "p_returntype": "xml",
                "p_startday": start.strftime("%Y-%m-%d"),
                "p_endday": end.strftime("%Y-%m-%d"),
                "p_product_cls_code": cls_code,
                "p_item_category_code": meta.kamis_category or "",
                "p_itemcode": meta.kamis_item,
            }
            resp = session.get(KAMIS_PRICE_URL, params=params, timeout=10)
            resp.raise_for_status()
            recs.extend(_parse_kamis_xml(resp.text, item))
        frames.append(pd.DataFrame(recs).rename(columns={"price": col}))

    retail_df, whole_df = frames
    if retail_df.empty and whole_df.empty:
        return pd.DataFrame(columns=["date", "item", "retail", "wholesale"])
    out = pd.merge(retail_df, whole_df, on=["date", "item"], how="outer")
    return out


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


# ── 도매시장 반입량 응답 필드명 (data.go.kr B552895, §5.2-3) ───────────────
#  공식 코드사전에서 확인된 표준 코드 필드: whsl_mrkt_cd(도매시장), gds_lclsf_cd/
#  gds_mclsf_cd/gds_sclsf_cd(품목 대/중/소분류), unit_cd(단위), plor_cd(산지).
#  ⚠️ 아래 4개 필드명·오퍼레이션은 **현행 기관 API 명세서로 확정**한다(임의 추정 금지).
#     틀린 값이 비즈니스 로직에 묻히지 않도록 *명명된 단일 상수*로 노출했다 —
#     운영자는 명세서를 보고 이 네 줄만 확인/수정하면 된다. 미확정(_UNSET) 상태면
#     _collect_volume 이 빈 프레임을 반환해 가격만으로 앱이 동작한다(반입량 선택적).
_VOLUME_OP_UNSET = "...operation...(명세서로 확정)"
VOLUME_OPERATION = _VOLUME_OP_UNSET   # 예: OrgPriceRealtimeService/getRealtimeAuctionList
VOL_FIELD_DATE = "saledate"     # 거래/반입 일자
VOL_FIELD_CODE = "gds_mclsf_cd"  # 품목 코드(중분류=품목) ↔ catalog.wholesale_code
VOL_FIELD_QTY = "delng_qy"      # 거래물량(반입량 프록시 — 별도 반입량 필드 있으면 교체)


def _collect_volume(keys: dict, start, end, session) -> pd.DataFrame:
    """도매시장 API → [date,item,volume]. 품목표준코드로 매핑(§5.2-3).

    빈 프레임 반환(가격만으로 앱 동작) 조건:
      · data_go_kr 키 없음
      · catalog 에 wholesale_code 미등록(공식 코드조회로 채우기 전)
      · VOLUME_OPERATION 미확정(_VOLUME_OP_UNSET — 운영자가 명세서로 확정 전)
    네트워크 호출부는 _fetch_volume_records, 파싱/정규화는 _parse_volume_records 로
    분리해 후자를 픽스처로 테스트한다(§5.3).
    """
    if not keys.get("data_go_kr"):
        return pd.DataFrame(columns=["date", "item", "volume"])
    index = build_wholesale_index()
    if not index:
        return pd.DataFrame(columns=["date", "item", "volume"])  # 코드 미등록
    if VOLUME_OPERATION == _VOLUME_OP_UNSET:
        return pd.DataFrame(columns=["date", "item", "volume"])  # 엔드포인트 미확정
    records = _fetch_volume_records(keys, start, end, session)
    return _parse_volume_records(records, index)


def _fetch_volume_records(keys: dict, start, end, session) -> list[dict]:
    """도매시장 OpenAPI 호출 → 레코드 dict 리스트(JSON/XML 공통 형태).

    ⚠️ 파라미터명/오퍼레이션/페이지네이션은 현행 명세서로 확정(§5.1). 등록된
    품목표준코드만 조회하고, 응답을 [{필드:값}, …] 평면 dict 리스트로 돌려준다.
    """
    base = f"{WHOLESALE_VOLUME_URL.rstrip('/')}/{VOLUME_OPERATION}"
    records: list[dict] = []
    for code in build_wholesale_index():
        params = {
            "serviceKey": keys["data_go_kr"], "_type": "json",
            "saleDate_start": start.strftime("%Y-%m-%d"),
            "saleDate_end": end.strftime("%Y-%m-%d"),
            VOL_FIELD_CODE: code, "numOfRows": 1000, "pageNo": 1,
        }
        resp = session.get(base, params=params, timeout=10)
        resp.raise_for_status()
        records.extend(_extract_items(resp))
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


def _parse_volume_records(records, code_index: dict[str, str] | None = None
                          ) -> pd.DataFrame:
    """도매시장 응답 레코드(list[dict]) → [date,item,volume]. 품목표준코드로 매핑.

    · code_index: wholesale_code → 품목명(기본 catalog 전체). 미등록 코드는 스킵(§6-3).
    · 동일 (date,item) 다건은 합산(여러 시장·법인·등급 → 일 반입량 합).
    · 수량 파싱 실패/일자 결측 레코드는 조용히 버리지 말고 운영 시 로깅 권장.
    """
    idx = code_index if code_index is not None else build_wholesale_index()
    agg: dict[tuple, float] = {}
    for rec in records:
        code = rec.get(VOL_FIELD_CODE)
        item = idx.get(str(code)) if code is not None else None
        if item is None:
            continue   # 미등록 코드 — 가드(§6-3)
        date = _parse_date(str(rec.get(VOL_FIELD_DATE) or ""))
        if date is None:
            continue
        try:
            qty = float(str(rec.get(VOL_FIELD_QTY)).replace(",", ""))
        except (TypeError, ValueError):
            continue
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

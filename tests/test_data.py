# -*- coding: utf-8 -*-
"""데이터 계층 테스트 (§5.3 수용 기준): 단위 정규화·코드매핑 픽스처 + 스키마.

실API 네트워크 없이 파싱/정규화 로직을 픽스처로 검증한다.
"""
import pandas as pd
import pytest

from bf import load_daily, validate_schema, SCHEMA, verify_catalog_codes
from bf.catalog import (
    ItemMeta, normalize_price, unit_to_kg, build_code_index, item_from_code,
    build_wholesale_index, GROUP_FRUIT, GROUP_SEASONING,
)
from bf.data import (
    _parse_kamis_xml, _merge_normalize, _parse_volume_records, _collect_volume,
    _extract_items, VOL_FIELD_DATE, VOL_FIELD_LCLSF, VOL_FIELD_MCLSF, VOL_FIELD_QTY,
)


# ── 네트워크 없는 가짜 세션/응답(라이브 경로 픽스처 테스트용) ──────────────
class _FakeResp:
    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._resp


# ── 단위 정규화 (리스크 #6) ───────────────────────────────────────────────
def test_normalize_piece_to_kg():
    # 양파 1개=0.25kg → 원/개 500 → 원/kg 2000
    assert normalize_price("양파", 500, "개") == pytest.approx(2000.0)


def test_normalize_box_to_kg():
    # 20kg 상자 40000원 → 원/kg 2000
    assert normalize_price("배추", 40000, "20kg") == pytest.approx(2000.0)


def test_normalize_kg_identity():
    assert normalize_price("사과", 5000, "kg") == pytest.approx(5000.0)


def test_normalize_unknown_unit_raises():
    with pytest.raises(KeyError):
        unit_to_kg("양파", "자루")   # 미등록 단위 → 임의 추정 금지(에러로 노출)


# ── 코드 ↔ 품목 매핑 (§5.2-1) ─────────────────────────────────────────────
def test_code_index_roundtrip():
    # 공식 코드표 대신 픽스처로 매핑 메커니즘만 검증(실코드는 운영자가 주입)
    fixture = {
        "사과": ItemMeta("사과", GROUP_FRUIT, 1.5, frozenset({9}), 5000, 53,
                        kamis_category="06", kamis_item="411"),
        "배": ItemMeta("배", GROUP_FRUIT, 1.0, frozenset({9}), 4500, 51,
                      kamis_category="06", kamis_item="412"),
    }
    idx = build_code_index(fixture)
    assert item_from_code("06", "411", idx) == "사과"
    assert item_from_code("06", "412", idx) == "배"
    assert item_from_code("06", "999", idx) is None   # 미등록 → None(가드)


# ── KAMIS XML 파싱 + 단위 정규화 통합 ─────────────────────────────────────
def test_parse_kamis_xml_normalizes_unit():
    xml = """<?xml version='1.0'?>
    <document><data>
        <item><regday>2025-11-10</regday><price>500</price><unit>개</unit></item>
        <item><regday>2025-11-11</regday><price>520</price><unit>개</unit></item>
    </data></document>"""
    recs = _parse_kamis_xml(xml, "양파")
    assert len(recs) == 2
    assert recs[0]["item"] == "양파"
    assert recs[0]["price"] == 2000   # 500원/개 ÷ 0.25kg
    assert pd.Timestamp(recs[0]["date"]) == pd.Timestamp("2025-11-10")


def test_merge_normalize_outputs_schema():
    price = pd.DataFrame({
        "date": pd.to_datetime(["2025-11-10", "2025-11-11"]),
        "item": ["양파", "양파"],
        "retail": [2000, 2100], "wholesale": [1400, 1500],
    })
    vol = pd.DataFrame({
        "date": pd.to_datetime(["2025-11-10", "2025-11-11"]),
        "item": ["양파", "양파"], "volume": [120.0, 140.0],
    })
    out = _merge_normalize(price, vol)
    assert list(out.columns) == SCHEMA
    assert pd.api.types.is_datetime64_any_dtype(out["date"])
    assert out["retail"].dtype.kind in "iu"   # 정수 원/kg


def test_merge_normalize_missing_volume_neutral():
    price = pd.DataFrame({
        "date": pd.to_datetime(["2025-11-10"]),
        "item": ["양파"], "retail": [2000], "wholesale": [1400],
    })
    out = _merge_normalize(price, pd.DataFrame(columns=["date", "item", "volume"]))
    assert list(out.columns) == SCHEMA
    assert out["volume"].notna().all()   # 반입량 전무 → 중립값 채움


# ── 경매 (대분류,중분류) 코드 매핑 (§5.2-3) ───────────────────────────────
def test_wholesale_index_roundtrip():
    fixture = {
        "양파": ItemMeta("양파", GROUP_SEASONING, 1.0, frozenset({5}), 2000, 39,
                        vol_lclsf="12", vol_mclsf="01"),
        "대파": ItemMeta("대파", GROUP_SEASONING, 0.5, frozenset({12}), 4000, 33,
                        vol_lclsf="12", vol_mclsf="02"),
    }
    idx = build_wholesale_index(fixture)
    assert idx == {("12", "01"): "양파", ("12", "02"): "대파"}


# ── 반입량 파싱: (대분류,중분류) 매핑 + 일별 합산 + 미등록 코드 가드 ─────────
def test_parse_volume_records_maps_aggregates_and_guards():
    L, M = VOL_FIELD_LCLSF, VOL_FIELD_MCLSF
    recs = [
        {VOL_FIELD_DATE: "2025-11-10", L: "12", M: "01", VOL_FIELD_QTY: "1,200"},
        {VOL_FIELD_DATE: "2025-11-10", L: "12", M: "01", VOL_FIELD_QTY: "800"},
        {VOL_FIELD_DATE: "2025-11-10", L: "05", M: "01", VOL_FIELD_QTY: "50"},   # 미등록쌍→스킵
        {VOL_FIELD_DATE: "20251111", L: "12", M: "01", VOL_FIELD_QTY: "500"},    # YYYYMMDD
    ]
    out = _parse_volume_records(recs, {("12", "01"): "양파"})
    assert list(out.columns) == ["date", "item", "volume"]
    day10 = out[out["date"] == pd.Timestamp("2025-11-10")]
    assert day10["volume"].iloc[0] == pytest.approx(2000.0)   # 1200+800 합산
    assert (out["item"] == "양파").all()                       # 미등록 코드쌍 제외(중분류 01 충돌 방지)
    assert pd.Timestamp("2025-11-11") in set(out["date"])      # YYYYMMDD 파싱


def test_collect_volume_empty_when_no_key():
    # data_go_kr 키 없으면 빈 프레임(가격만으로 동작) — 네트워크 미호출
    out = _collect_volume({}, pd.Timestamp("2025-11-01"),
                          pd.Timestamp("2025-11-10"), session=None)
    assert list(out.columns) == ["date", "item", "volume"]
    assert out.empty


def test_extract_items_json_and_xml():
    payload = {"response": {"body": {"items": {"item": [
        {VOL_FIELD_MCLSF: "01", VOL_FIELD_QTY: "10"}]}}}}
    assert _extract_items(_FakeResp(payload=payload))[0][VOL_FIELD_QTY] == "10"
    xml = f"<r><item><{VOL_FIELD_MCLSF}>01</{VOL_FIELD_MCLSF}>" \
          f"<{VOL_FIELD_QTY}>10</{VOL_FIELD_QTY}></item></r>"
    assert _extract_items(_FakeResp(text=xml))[0][VOL_FIELD_MCLSF] == "01"


# ── KAMIS 코드 검증 헬퍼 (§5.2-1) ─────────────────────────────────────────
def test_verify_catalog_codes_requires_keys():
    with pytest.raises(ValueError):
        verify_catalog_codes({})


def test_verify_catalog_codes_reports_missing_codes():
    # 실 catalog 코드 미등록 → 모든 품목 ok=False + 안내(네트워크 미호출)
    fake = _FakeSession(_FakeResp())
    report = verify_catalog_codes({"kamis_cert_key": "k", "kamis_cert_id": "i"},
                                  session=fake)
    assert all(not r["ok"] for r in report.values())
    assert all("미등록" in r["error"] for r in report.values())
    assert fake.calls == []   # 코드 없으면 호출하지 않음


def test_verify_catalog_codes_probes_live_when_coded(monkeypatch):
    # 코드가 채워진 품목은 라이브 조회 후 레코드 유무로 ok 판정
    coded = {"사과": ItemMeta("사과", GROUP_FRUIT, 1.5, frozenset({9}), 5000, 53,
                            kamis_category="400", kamis_item="411")}
    monkeypatch.setattr("bf.data.ITEMS", coded)
    xml = ("<r><item><regday>2025-11-10</regday><price>5000</price>"
           "<unit>kg</unit></item></r>")
    fake = _FakeSession(_FakeResp(text=xml))
    report = verify_catalog_codes({"kamis_cert_key": "k", "kamis_cert_id": "i"},
                                  end=pd.Timestamp("2025-11-15"), session=fake)
    assert report["사과"]["ok"] is True
    assert report["사과"]["rows"] == 1
    assert len(fake.calls) == 1


# ── ② 가격(perRegion) 파싱: 평균가 → 원/kg 단위정규화 + 결측/0 가드 ──────────
def test_parse_price_records_normalizes_avg_to_kg():
    from bf.data import (_parse_price_records, PRICE_FIELD_DATE, PRICE_FIELD_AVG,
                         PRICE_FIELD_UNIT, PRICE_FIELD_UNITSZ)
    # 사과: 10개 × 0.25kg = 2.5kg. 25000원 → 10000원/kg, 20000원 → 8000원/kg → 평균 9000
    recs = [
        {PRICE_FIELD_DATE: "20260601", PRICE_FIELD_AVG: "25,000",
         PRICE_FIELD_UNIT: "개", PRICE_FIELD_UNITSZ: "10"},
        {PRICE_FIELD_DATE: "20260601", PRICE_FIELD_AVG: "20000",
         PRICE_FIELD_UNIT: "개", PRICE_FIELD_UNITSZ: "10"},
        {PRICE_FIELD_DATE: "20260602", PRICE_FIELD_AVG: "0",
         PRICE_FIELD_UNIT: "개", PRICE_FIELD_UNITSZ: "10"},       # 0 → 제외
        {PRICE_FIELD_DATE: "20260603", PRICE_FIELD_AVG: "9999",
         PRICE_FIELD_UNIT: "자루", PRICE_FIELD_UNITSZ: "1"},      # 미등록 단위 → 제외
    ]
    out = pd.DataFrame(_parse_price_records(recs, "사과"))
    assert set(out["item"]) == {"사과"}
    v = out[out["date"] == pd.Timestamp("2026-06-01")]["price"].iloc[0]
    assert v == 9000
    assert pd.Timestamp("2026-06-02") not in set(out["date"])   # 0가 → 제외
    assert pd.Timestamp("2026-06-03") not in set(out["date"])   # 미등록 단위 → 제외


# 시금치 g/100 환산: 886원/100g → 8860원/kg (실데이터 단위 케이스 회귀)
def test_parse_price_records_grams_to_kg():
    from bf.data import (_parse_price_records, PRICE_FIELD_DATE, PRICE_FIELD_AVG,
                         PRICE_FIELD_UNIT, PRICE_FIELD_UNITSZ)
    recs = [{PRICE_FIELD_DATE: "20260601", PRICE_FIELD_AVG: "886",
             PRICE_FIELD_UNIT: "g", PRICE_FIELD_UNITSZ: "100"}]
    out = _parse_price_records(recs, "시금치")
    assert out[0]["price"] == 8860                       # 886 ÷ (100 × 0.001kg)


# ── ① 반입량: qty × unit_qty(단위물량) 으로 kg 물량 집계 ───────────────────
def test_parse_volume_multiplies_unit_qty():
    from bf.data import VOL_FIELD_UNITQTY
    L, M = VOL_FIELD_LCLSF, VOL_FIELD_MCLSF
    recs = [
        {VOL_FIELD_DATE: "2025-11-10", L: "12", M: "01",
         VOL_FIELD_QTY: "3", VOL_FIELD_UNITQTY: "10"},     # 3 × 10kg = 30
        {VOL_FIELD_DATE: "2025-11-10", L: "12", M: "01",
         VOL_FIELD_QTY: "2", VOL_FIELD_UNITQTY: "5"},       # 2 × 5kg = 10
    ]
    out = _parse_volume_records(recs, {("12", "01"): "양파"})
    assert out["volume"].iloc[0] == pytest.approx(40.0)     # 30 + 10 합산


def test_catalog_items_have_all_codes():
    from bf.catalog import ITEMS
    # 10개 품목 모두 가격 코드 + 경매 (대분류,중분류) 코드가 채워져 실연동 가능해야 함
    assert all(m.price_ctgry and m.price_item for m in ITEMS.values())
    assert all(m.vol_lclsf and m.vol_mclsf for m in ITEMS.values())


def test_sample_passes_schema_validation():
    df = load_daily(source="sample", end=pd.Timestamp("2025-11-15"))
    validate_schema(df)   # 위반 시 AssertionError


def test_api_requires_keys():
    with pytest.raises(ValueError):
        load_daily(source="api", keys=None)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

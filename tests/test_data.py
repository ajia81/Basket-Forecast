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
    _extract_items, VOL_FIELD_DATE, VOL_FIELD_CODE, VOL_FIELD_QTY,
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


# ── 도매 품목표준코드 매핑 (§5.2-3) ───────────────────────────────────────
def test_wholesale_index_roundtrip():
    fixture = {
        "양파": ItemMeta("양파", GROUP_SEASONING, 1.0, frozenset({5}), 2000, 39,
                        wholesale_code="0601"),
        "대파": ItemMeta("대파", GROUP_SEASONING, 0.5, frozenset({12}), 4000, 33,
                        wholesale_code="0602"),
    }
    idx = build_wholesale_index(fixture)
    assert idx == {"0601": "양파", "0602": "대파"}


# ── 반입량 파싱: 코드매핑 + 일별 합산 + 미등록 코드 가드 ────────────────────
def test_parse_volume_records_maps_aggregates_and_guards():
    recs = [
        {VOL_FIELD_DATE: "2025-11-10", VOL_FIELD_CODE: "0601", VOL_FIELD_QTY: "1,200"},
        {VOL_FIELD_DATE: "2025-11-10", VOL_FIELD_CODE: "0601", VOL_FIELD_QTY: "800"},
        {VOL_FIELD_DATE: "2025-11-10", VOL_FIELD_CODE: "9999", VOL_FIELD_QTY: "50"},  # 미등록→스킵
        {VOL_FIELD_DATE: "20251111", VOL_FIELD_CODE: "0601", VOL_FIELD_QTY: "500"},   # YYYYMMDD
    ]
    out = _parse_volume_records(recs, {"0601": "양파"})
    assert list(out.columns) == ["date", "item", "volume"]
    day10 = out[out["date"] == pd.Timestamp("2025-11-10")]
    assert day10["volume"].iloc[0] == pytest.approx(2000.0)   # 1200+800 합산
    assert (out["item"] == "양파").all()                       # 미등록 코드 제외
    assert pd.Timestamp("2025-11-11") in set(out["date"])      # YYYYMMDD 파싱


def test_collect_volume_empty_when_no_codes_registered():
    # 현재 catalog 에 wholesale_code 미등록 → 키가 있어도 빈 프레임(가격만으로 동작)
    out = _collect_volume({"data_go_kr": "x"}, pd.Timestamp("2025-11-01"),
                          pd.Timestamp("2025-11-10"), session=None)
    assert list(out.columns) == ["date", "item", "volume"]
    assert out.empty


def test_extract_items_json_and_xml():
    payload = {"response": {"body": {"items": {"item": [
        {VOL_FIELD_CODE: "0601", VOL_FIELD_QTY: "10"}]}}}}
    assert _extract_items(_FakeResp(payload=payload))[0][VOL_FIELD_QTY] == "10"
    xml = f"<r><item><{VOL_FIELD_CODE}>0601</{VOL_FIELD_CODE}>" \
          f"<{VOL_FIELD_QTY}>10</{VOL_FIELD_QTY}></item></r>"
    assert _extract_items(_FakeResp(text=xml))[0][VOL_FIELD_CODE] == "0601"


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


def test_sample_passes_schema_validation():
    df = load_daily(source="sample", end=pd.Timestamp("2025-11-15"))
    validate_schema(df)   # 위반 시 AssertionError


def test_api_requires_keys():
    with pytest.raises(ValueError):
        load_daily(source="api", keys=None)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

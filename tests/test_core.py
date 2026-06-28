# -*- coding: utf-8 -*-
"""핵심 로직 회귀 테스트 (명세서 §8 '테스트 회귀 보증').

시연 스토리를 코드로 고정한다: 양파=과잉, 사과=대기, sell_first에 양파 포함,
대체재 동일 용도군, 예산 5만원 제약 충족, 예산 단조성.
"""
import pandas as pd
import pytest

from bf import (
    load_daily, analyze, gluts, sell_first, substitutes, expensive, budget_basket,
)
from bf.catalog import ESSENTIAL_GROUPS
from bf.core import SIGNAL_WAIT

# 결정론적 기준일(제철: 가을 → 사과/배·배추/무 제철). 샘플 시드 고정.
END = pd.Timestamp("2025-11-15")


@pytest.fixture(scope="module")
def states():
    df = load_daily(source="sample", end=END)
    return analyze(df, end=END)


def test_schema_contract():
    df = load_daily(source="sample", end=END)
    assert list(df.columns) == ["date", "item", "retail", "wholesale", "volume"]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert df["item"].nunique() == 10
    # 기준선 계산에 충분한 기간(≥60일)
    span = (df["date"].max() - df["date"].min()).days
    assert span >= 60


def test_onion_is_glut(states):
    """양파 = 과잉(공급 급증 + 가격 폭락)."""
    s = states["양파"]
    assert s.is_glut is True
    assert s.vol_chg >= 0.30
    assert s.price_chg <= -0.15
    assert s.signal == "구매추천"


def test_apple_is_wait(states):
    """사과 = 대기(가격 상승)."""
    assert states["사과"].signal == SIGNAL_WAIT
    assert states["사과"].price_chg >= 0.15


def test_sell_first_includes_onion(states):
    names = [s.item for s in sell_first(states)]
    assert "양파" in names
    # 대기 품목은 '팔아줄 작물'에 없어야 함
    assert "사과" not in names


def test_gluts_sorted_by_strength(states):
    g = gluts(states)
    assert len(g) >= 1
    scores = [s.glut_score for s in g]
    assert scores == sorted(scores, reverse=True)


def test_substitutes_same_group(states):
    """비싼(대기) 품목의 대체재는 동일 용도군이며 자기 자신/대기 제외."""
    pricey = expensive(states)
    assert pricey, "대기 품목이 하나는 있어야 함(사과)"
    target = pricey[0].item
    subs = substitutes(states, target)
    assert subs, "대체재가 있어야 함"
    grp = states[target].group
    for s in subs:
        assert s.group == grp
        assert s.item != target
        assert s.signal != SIGNAL_WAIT


def test_apple_substitute_is_pear(states):
    subs = substitutes(states, "사과")
    assert "배" in [s.item for s in subs]   # 같은 과일, 더 저렴


def test_substitutes_are_cheaper_than_target(states):
    """대체재는 항상 대상보다 싸야 한다(가성비 대체의 정의). 더 비싼 품목 금지."""
    for target in states:
        ref = states[target].retail
        for s in substitutes(states, target):
            assert s.retail < ref, f"{target}({ref}) 대체재 {s.item}({s.retail})가 더 비쌈"


def test_substitute_excludes_more_expensive_same_group(states):
    """싼 품목(배추)의 대체재로 더 비싼 동일군 품목(당근)이 나오면 안 된다."""
    names = [s.item for s in substitutes(states, "배추")]
    assert "당근" not in names   # 당근은 배추보다 비쌈 → 가성비 대체 아님


def test_sell_first_only_value_picks(states):
    """가성비 목록은 실제 저렴/과잉(구매추천)만 — 제철이라는 이유만으로 비싼 품목 금지."""
    picks = sell_first(states)
    assert all(s.signal == "구매추천" for s in picks)
    # 비싸고 평탄한 제철 품목(마늘)은 제외돼야 함
    assert "마늘" not in [s.item for s in picks]


def test_budget_boost_only_cheap(states):
    """예산 증량(q>1)은 실제 저렴(구매추천) 품목에만 적용 — 평탄 제철 증량 금지."""
    res = budget_basket(states, 50000)
    for s, q in res["items"]:
        if q > 1:
            assert s.signal == "구매추천", f"{s.item}(신호 {s.signal})이 q={q}로 증량됨"


def test_budget_basket_constraints(states):
    """예산 5만원: 상한 준수 + 필수 용도군 충족 + 과잉 포함 + 대기 제외."""
    res = budget_basket(states, 50000)
    assert res["total"] <= 50000
    assert res["leftover"] == 50000 - res["total"]
    # 필수 용도군 모두 커버
    for g in ESSENTIAL_GROUPS:
        assert g in res["groups_covered"]
    # 과잉 우선(설명 가능성)
    assert res["glut_in_basket"] is True
    # 대기 품목 미포함
    for st, _q in res["items"]:
        assert st.signal != SIGNAL_WAIT
    # 수량 상한
    for _st, q in res["items"]:
        assert 1 <= q <= 3


def test_budget_monotonic(states):
    """예산이 늘면 총 지출은 줄지 않는다(단조성)."""
    totals = [budget_basket(states, b)["total"]
              for b in (15000, 25000, 35000, 50000, 70000, 100000)]
    for a, b in zip(totals, totals[1:]):
        assert b >= a, f"단조성 위반: {totals}"


def test_empty_input_safe():
    """빈/결측 입력에 안전(§6-3 가드)."""
    assert analyze(pd.DataFrame(columns=["date", "item", "retail", "wholesale", "volume"])) == {}
    assert gluts({}) == []
    assert sell_first({}) == []
    res = budget_basket({}, 50000)
    assert res["total"] == 0 and res["items"] == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

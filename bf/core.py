# -*- coding: utf-8 -*-
"""bf.core — 과잉(글럿) 포착·구매신호·가성비·대체·예산 최적화 (명세서 §3).

공개 함수 시그니처(§3.5)는 UI/테스트가 의존하므로 **변경 금지**. 내부 구현만 개선한다.
이 모듈은 ``bf.catalog`` 외 다른 내부 모듈에 의존하지 않으며, numpy 를 import 하지
않는다(리스크 #4 — 가격/통계는 pandas/표준 statistics 로 계산).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .catalog import ESSENTIAL_GROUPS, ITEMS

# ── 투명 규칙 상수 (§3.1) — 사이드바에 그대로 노출(평가 포인트) ──────────────
VOLUME_SURGE = 0.30   # 반입량 변화율 ≥ +30%
PRICE_DROP = -0.15    # 가격 변화율 ≤ -15%
RECENT_DAYS = 7       # '현재' = 최근 7일 평균
BASE_MIN, BASE_MAX = 8, 60   # '최근 기준선' = 직전 8~60일 중앙값 (다년 평년 아님)

# 구매신호 임계값 (§3.2) — 실데이터 튜닝 대상(§5.3, 리스크 #6)
BUY_DROP = -0.10      # 구매추천: price_chg ≤ -10%
WAIT_RISE = 0.15      # 대기: price_chg ≥ +15%
CV_WATCH = 0.08       # 주의: 최근 7일 변동계수(std/mean) ≥ 0.08

# 가성비 점수 가중치 (§3.3)
SEASON_BONUS = 0.15
GLUT_WEIGHT = 0.5

# 예산 장바구니 (§3.4)
MAXQ = 3              # 한 품목 최대 수량(잔여예산 소진 단계)

SIGNAL_BUY = "구매추천"
SIGNAL_WAIT = "대기"
SIGNAL_WATCH = "주의"
SIGNAL_NORMAL = "보통"


@dataclass
class ItemState:
    """한 품목의 분석 결과(표시·정렬·최적화의 단위)."""

    item: str
    group: str
    retail: int           # 현재가(최근 7일 평균, 원/kg)
    wholesale: int        # 현재 도매가(원/kg)
    volume: float         # 현재 반입량(상대단위)
    price_chg: float      # 가격 변화율 = 최근/기준선 - 1
    vol_chg: float        # 반입량 변화율
    glut_score: float     # 과잉 강도(정렬용)
    is_glut: bool         # 과잉 포착 여부
    signal: str           # 구매추천/대기/주의/보통
    value: float          # 가성비 점수(높을수록 '지금 사면 좋은')
    in_season: bool
    cv: float             # 최근 7일 변동계수
    portion_kg: float     # 표준구매량
    portion_cost: int     # 1회 분량 비용(원) = retail * portion_kg
    n_days: int           # 분석에 쓰인 일수

    def reason(self) -> str:
        """대체/추천 사유 한 줄(§4 '대체 사유 표기')."""
        bits = []
        if self.is_glut:
            bits.append("과잉")
        if self.in_season:
            bits.append("제철")
        if self.price_chg <= BUY_DROP:
            bits.append(f"가격↓{self.price_chg * 100:.0f}%")
        return "·".join(bits) if bits else "보통"


# ── 기준선 계산 (§3.1) ────────────────────────────────────────────────────
def _baseline(g: pd.DataFrame, col: str, end: pd.Timestamp, mode: str = "trailing") -> float:
    """col 의 기준선 값.

    mode="trailing" : 직전 8~60일 중앙값 (MVP 기본).
    mode="seasonal" : 전년 동기(±15일) 중앙값 — 다년 이력이 있을 때만(§3.1, T7).
        실데이터 연동 후에만 의미가 있으므로 데이터가 부족하면 trailing 으로 폴백한다.
    """
    if mode == "seasonal":
        prev = end - pd.Timedelta(days=365)
        win = g[(g["date"] >= prev - pd.Timedelta(days=15))
                & (g["date"] <= prev + pd.Timedelta(days=15))]
        if len(win) >= 3:
            return float(win[col].median())
        # 다년 이력 없음 → trailing 폴백

    base = g[(g["date"] <= end - pd.Timedelta(days=BASE_MIN))
             & (g["date"] >= end - pd.Timedelta(days=BASE_MAX))]
    if len(base) < 3:
        # 기준선 구간이 부족하면 최근 7일을 제외한 모든 과거로 폴백(가드, §6-3)
        base = g[g["date"] <= end - pd.Timedelta(days=RECENT_DAYS)]
    if len(base) == 0:
        return float("nan")
    return float(base[col].median())


def _signal(is_glut: bool, price_chg: float, cv: float) -> str:
    if is_glut or price_chg <= BUY_DROP:
        return SIGNAL_BUY
    if price_chg >= WAIT_RISE:
        return SIGNAL_WAIT
    if cv >= CV_WATCH:
        return SIGNAL_WATCH
    return SIGNAL_NORMAL


def _analyze_item(item: str, g: pd.DataFrame, end: pd.Timestamp,
                  mode: str) -> ItemState | None:
    g = g.sort_values("date")
    recent = g[(g["date"] > end - pd.Timedelta(days=RECENT_DAYS)) & (g["date"] <= end)]
    if len(recent) == 0:
        return None  # 최근 데이터 없음 → 소비 측에서 제외

    meta = ITEMS.get(item)
    if meta is None:
        return None  # 카탈로그 외 품목은 무시(정규화 계약)

    r_retail = float(recent["retail"].mean())
    r_vol = float(recent["volume"].mean())
    r_whole = float(recent["wholesale"].mean())

    b_retail = _baseline(g, "retail", end, mode)
    b_vol = _baseline(g, "volume", end, mode)

    price_chg = (r_retail / b_retail - 1.0) if b_retail and b_retail == b_retail else 0.0
    vol_chg = (r_vol / b_vol - 1.0) if b_vol and b_vol == b_vol else 0.0
    cv = float(recent["retail"].std(ddof=0) / r_retail) if r_retail else 0.0

    is_glut = (vol_chg >= VOLUME_SURGE) and (price_chg <= PRICE_DROP)
    glut_score = max(0.0, vol_chg) + max(0.0, -price_chg)
    in_season = meta.in_season(int(end.month))
    value = (-price_chg) + (SEASON_BONUS if in_season else 0.0) + GLUT_WEIGHT * glut_score
    signal = _signal(is_glut, price_chg, cv)

    return ItemState(
        item=item, group=meta.group,
        retail=round(r_retail), wholesale=round(r_whole), volume=round(r_vol, 1),
        price_chg=price_chg, vol_chg=vol_chg,
        glut_score=glut_score, is_glut=is_glut, signal=signal, value=value,
        in_season=in_season, cv=cv,
        portion_kg=meta.portion_kg, portion_cost=round(r_retail * meta.portion_kg),
        n_days=int(len(g)),
    )


def analyze(df: pd.DataFrame, end=None, mode: str = "trailing") -> dict[str, ItemState]:
    """표준 DataFrame(§2) → {품목명: ItemState}. 빈/결측 입력에 안전(§6-3)."""
    if df is None or len(df) == 0:
        return {}
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    end = pd.to_datetime(end) if end is not None else df["date"].max()

    states: dict[str, ItemState] = {}
    for item, g in df.groupby("item", sort=False):
        st = _analyze_item(str(item), g, end, mode)
        if st is not None:
            states[str(item)] = st
    return states


# ── 파생 뷰 (§3.5) ────────────────────────────────────────────────────────
def gluts(states: dict[str, ItemState]) -> list[ItemState]:
    """과잉 포착 품목, 강도(glut_score)순."""
    return sorted((s for s in states.values() if s.is_glut),
                  key=lambda s: s.glut_score, reverse=True)


def sell_first(states: dict[str, ItemState], n: int = 6) -> list[ItemState]:
    """'오늘 팔아줄 작물' — 과잉·제철·저렴 우선(value순). 대기 품목 제외."""
    pool = [s for s in states.values() if s.signal != SIGNAL_WAIT]
    return sorted(pool, key=lambda s: (s.is_glut, s.value), reverse=True)[:n]


def substitutes(states: dict[str, ItemState], item: str, n: int = 3) -> list[ItemState]:
    """같은 용도군의 가성비 상위 대체재(과잉 우선). 자기 자신·대기 제외."""
    group = states[item].group if item in states else (
        ITEMS[item].group if item in ITEMS else None)
    if group is None:
        return []
    pool = [s for s in states.values()
            if s.group == group and s.item != item and s.signal != SIGNAL_WAIT]
    return sorted(pool, key=lambda s: (s.is_glut, s.value), reverse=True)[:n]


def expensive(states: dict[str, ItemState]) -> list[ItemState]:
    """'대기'(비싼) 품목, 가격 상승폭순."""
    return sorted((s for s in states.values() if s.signal == SIGNAL_WAIT),
                  key=lambda s: s.price_chg, reverse=True)


# ── 예산별 장바구니 — 제약 최적화 (§3.4) ──────────────────────────────────
def _eff(s: ItemState) -> float:
    """효율 = (가성비 + 0.5) / 1회 분량 비용."""
    return (s.value + 0.5) / s.portion_cost if s.portion_cost > 0 else 0.0


def budget_basket(states: dict[str, ItemState], budget: int) -> dict:
    """예산 상한 + 필수 용도군 커버리지 하에서 가성비(과잉 우선) 효용 최대화.

    3단계 그리디: ①필수 용도군 1개씩 → ②나머지 가성비순(과잉 우선) →
    ③잔여예산을 과잉·제철 상위 수량 증가(MAXQ)로 소진. '대기' 품목은 제외(설명 가능성).
    선택 우선순위는 예산과 무관(예산은 가용성 게이트만) → 예산 단조성 보장.
    """
    candidates = [s for s in states.values()
                  if s.signal != SIGNAL_WAIT and s.portion_cost > 0]

    basket: dict[str, int] = {}
    spent = 0
    covered: set[str] = set()

    # ① 필수 용도군: 그룹별 효율 최상위 품목 1개(예산 내)
    for grp in ESSENTIAL_GROUPS:
        pool = sorted((s for s in candidates if s.group == grp and s.item not in basket),
                      key=_eff, reverse=True)
        for s in pool:
            if spent + s.portion_cost <= budget:
                basket[s.item] = 1
                spent += s.portion_cost
                covered.add(grp)
                break

    # ② 나머지: 과잉 우선 → 가성비순으로 1개씩
    rest = sorted((s for s in candidates if s.item not in basket),
                  key=lambda s: (s.is_glut, s.value), reverse=True)
    for s in rest:
        if spent + s.portion_cost <= budget:
            basket[s.item] = 1
            spent += s.portion_cost
            covered.add(s.group)

    # ③ 잔여예산: 과잉·제철 품목 수량 증가(MAXQ 상한), 효율순 반복
    boost = sorted((s for s in candidates
                    if s.item in basket and (s.is_glut or s.in_season)),
                   key=_eff, reverse=True)
    changed = True
    while changed:
        changed = False
        for s in boost:
            if basket[s.item] < MAXQ and spent + s.portion_cost <= budget:
                basket[s.item] += 1
                spent += s.portion_cost
                changed = True

    items = [(states[i], q) for i, q in basket.items()]
    items.sort(key=lambda iq: (iq[0].is_glut, iq[0].value), reverse=True)
    return {
        "items": items,
        "total": spent,
        "budget": budget,
        "leftover": budget - spent,
        "groups_covered": sorted(covered),
        "glut_in_basket": any(states[i].is_glut for i in basket),
    }

# -*- coding: utf-8 -*-
"""bf.catalog — 품목 메타데이터 (용도군·표준구매량·제철·열량 + 실연동 코드매핑·단위환산).

명세서 §1.2 / §5.2 참조. 이 모듈은 외부 의존이 없으며(core·data·app 공용 참조),
실연동(load_from_api) 시 필요한 KAMIS/도매 코드와 가격 단위 환산 정보를 함께 보관한다.

설계 원칙
- 데이터 스키마(§2)의 ``item`` 값은 반드시 여기 ITEM_NAMES 중 하나로 정규화된다.
- 실연동 코드는 **공식 코드표/코드조회 API에서 취득**해 등록한다(임의 추정 금지, §5.2-1).
  가격 ``price_*`` 와 경매 ``vol_lclsf``/``vol_mclsf`` 는 동봉 코드표·표준코드 API로
  확인한 정적 코드. 코드↔품목 매핑 *메커니즘*은 build_*_index()로 제공·픽스처 테스트한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── 용도군(=장보기 카테고리) ──────────────────────────────────────────────
GROUP_VEG_MAIN = "주채소"
GROUP_SEASONING = "양념채소"
GROUP_FRUIT = "과일"
GROUP_LEAF = "잎채소"
GROUP_STAPLE = "구황"

# 예산 장바구니(§3.4)가 최소 1개씩 반드시 커버해야 하는 필수 용도군.
ESSENTIAL_GROUPS: list[str] = [GROUP_VEG_MAIN, GROUP_SEASONING, GROUP_FRUIT]


@dataclass(frozen=True)
class ItemMeta:
    """한 품목의 불변 메타데이터."""

    name: str
    group: str
    portion_kg: float          # 표준구매량(1회 장보기 분량, kg)
    season_months: frozenset[int]   # 제철 월(1~12)
    base_retail: int           # 샘플 합성용 기준 소매가(원/kg)
    kcal_per_100g: int         # 열량(설명 변수)
    # ── 실연동 코드매핑(§5.2-1, 공식 코드표/코드조회 API에서 취득) ────────
    #   가격(②): data.go.kr B552845/perRegion/price — 부류·품목 코드는 동봉
    #   코드표(정적)에서 취득해 아래 price_* 에 등록.
    price_ctgry: str | None = None      # 가격 부류코드 ctgry_cd (예: 200 채소류)
    price_item: str | None = None       # 가격 품목코드 item_cd (예: 245 양파)
    price_vrty: str | None = None       # 가격 품종코드 vrty_cd — 한 품목코드에 이질
    #   품종이 섞여 평균이 왜곡될 때만 지정(예: 대파 246 안의 쪽파 제외 → "00").
    #   반입량(①): data.go.kr B552845/katRealTime2/trades2 — 품목은 (대분류,중분류)
    #   쌍으로 식별된다(중분류코드는 대분류 안에서만 유일). 표준코드 API(katCode/goods)
    #   로 확인한 정적 코드를 등록한다. 두 코드가 모두 있어야 반입량 조회 대상.
    vol_lclsf: str | None = None        # 경매 상품대분류코드 gds_lclsf_cd
    vol_mclsf: str | None = None        # 경매 상품중분류코드 gds_mclsf_cd
    kamis_category: str | None = None   # (legacy) KAMIS 직통 부류코드 — verify 용
    kamis_item: str | None = None       # (legacy) KAMIS 직통 품목코드 — verify 용
    # ── 가격 단위 환산: KAMIS 단위표기 → 1단위가 나타내는 kg (§5.2-2) ────
    #    무게단위(kg/100g/20kg…)는 전역 WEIGHT_UNITS로 처리하고,
    #    개·단·포기 등 낱개단위만 품목별 무게(kg)를 여기 등록한다.
    piece_kg: dict[str, float] = field(default_factory=dict)

    def in_season(self, month: int) -> bool:
        return month in self.season_months


# ── 무게 기반 단위 → kg (모든 품목 공통) ──────────────────────────────────
WEIGHT_UNITS: dict[str, float] = {
    "kg": 1.0, "1kg": 1.0, "2kg": 2.0, "3kg": 3.0, "5kg": 5.0,
    "10kg": 10.0, "15kg": 15.0, "20kg": 20.0,
    "g": 0.001, "100g": 0.1, "500g": 0.5, "600g": 0.6,
}


# ── 10개 품목 카탈로그 ────────────────────────────────────────────────────
# season_months 는 한국 노지/저장 출하 기준의 대표 제철. portion_kg 는 1회 분량.
#  price_ctgry/price_item: 동봉 코드표(지역별 품목별 도·소매가격정보) 정적 코드.
#  마늘=피마늘(244, 도매·소매 공통 핵심 품목). 파=대파 포함 품목코드 246.
ITEMS: dict[str, ItemMeta] = {
    "양파": ItemMeta("양파", GROUP_SEASONING, 1.0, frozenset({4, 5, 6}), 2000, 39,
                    price_ctgry="200", price_item="245",
                    vol_lclsf="12", vol_mclsf="01",
                    piece_kg={"개": 0.25, "망": 1.2}),
    "대파": ItemMeta("대파", GROUP_SEASONING, 0.5, frozenset({11, 12, 1, 2}), 4000, 33,
                    price_ctgry="200", price_item="246", price_vrty="00",  # 쪽파(02) 제외
                    vol_lclsf="12", vol_mclsf="02",
                    piece_kg={"단": 0.8, "개": 0.12}),
    "마늘": ItemMeta("마늘", GROUP_SEASONING, 0.3, frozenset({6, 7}), 12000, 132,
                    price_ctgry="200", price_item="258",  # 깐마늘(국산) — 244 피마늘은 소매 미조사
                    vol_lclsf="12", vol_mclsf="09",
                    piece_kg={"접": 1.5, "통": 0.05}),
    "배추": ItemMeta("배추", GROUP_VEG_MAIN, 2.0, frozenset({11, 12}), 1500, 12,
                    price_ctgry="200", price_item="211",
                    vol_lclsf="10", vol_mclsf="01",
                    piece_kg={"포기": 2.5, "망": 7.5}),
    "무": ItemMeta("무", GROUP_VEG_MAIN, 1.5, frozenset({11, 12}), 1200, 18,
                  price_ctgry="200", price_item="231",
                  vol_lclsf="11", vol_mclsf="01",
                  piece_kg={"개": 1.0, "단": 3.0}),
    "당근": ItemMeta("당근", GROUP_VEG_MAIN, 0.7, frozenset({9, 10, 11}), 3500, 37,
                    price_ctgry="200", price_item="232",
                    vol_lclsf="11", vol_mclsf="03",
                    piece_kg={"개": 0.2}),
    "시금치": ItemMeta("시금치", GROUP_LEAF, 0.4, frozenset({11, 12, 1, 2}), 6000, 23,
                     price_ctgry="200", price_item="213",
                     vol_lclsf="10", vol_mclsf="08",
                     piece_kg={"단": 0.4}),
    "감자": ItemMeta("감자", GROUP_STAPLE, 1.2, frozenset({6, 7, 8, 9}), 3000, 77,
                    price_ctgry="100", price_item="152",
                    vol_lclsf="05", vol_mclsf="01",
                    piece_kg={"개": 0.15}),
    "사과": ItemMeta("사과", GROUP_FRUIT, 1.5, frozenset({9, 10, 11}), 5000, 53,
                    price_ctgry="400", price_item="411",
                    vol_lclsf="06", vol_mclsf="01",
                    piece_kg={"개": 0.25, "봉": 1.5}),
    "배": ItemMeta("배", GROUP_FRUIT, 1.0, frozenset({9, 10, 11}), 4500, 51,
                  price_ctgry="400", price_item="412",
                  vol_lclsf="06", vol_mclsf="02",
                  piece_kg={"개": 0.5, "봉": 2.0}),
}

ITEM_NAMES: list[str] = list(ITEMS.keys())


# ── 단위 정규화 (§5.2-2 / 리스크 #6) ──────────────────────────────────────
def unit_to_kg(item: str, unit: str) -> float:
    """KAMIS 단위표기가 나타내는 kg 양을 반환.

    예) ("양파","개") → 0.25,  (*,"20kg") → 20.0,  (*,"kg") → 1.0.
    알 수 없는 단위는 KeyError(임의 추정 금지 — 매핑 누락을 드러낸다).
    """
    u = (unit or "").strip()
    if u in WEIGHT_UNITS:
        return WEIGHT_UNITS[u]
    meta = ITEMS.get(item)
    if meta and u in meta.piece_kg:
        return meta.piece_kg[u]
    raise KeyError(f"단위 환산 정보 없음: item={item!r}, unit={unit!r} (catalog에 등록 필요)")


def normalize_price(item: str, price: float, unit: str) -> float:
    """임의 단위 가격 → **원/kg** 으로 환산(§2 불변 스키마 보증).

    price 가 '단위당 총가격'이라고 가정한다. 예) 20kg 상자 40000원 → 2000원/kg.
    """
    kg = unit_to_kg(item, unit)
    if kg <= 0:
        raise ValueError(f"비정상 단위 무게: {item} {unit} -> {kg}kg")
    return price / kg


# ── 코드 ↔ 품목 매핑 메커니즘 (§5.2-1) ────────────────────────────────────
def build_code_index(items: dict[str, ItemMeta] | None = None
                     ) -> dict[tuple[str | None, str | None], str]:
    """(kamis_category, kamis_item) → 품목명 역인덱스. 코드가 채워진 항목만 포함."""
    src = items if items is not None else ITEMS
    idx: dict[tuple[str | None, str | None], str] = {}
    for name, meta in src.items():
        if meta.kamis_item:
            idx[(meta.kamis_category, meta.kamis_item)] = name
    return idx


def item_from_code(category: str | None, item_code: str | None,
                   index: dict[tuple[str | None, str | None], str] | None = None
                   ) -> str | None:
    """코드 → 품목명. 미등록 코드는 None(소비 측에서 가드, §6-3)."""
    idx = index if index is not None else build_code_index()
    return idx.get((category, item_code))


def build_wholesale_index(items: dict[str, ItemMeta] | None = None
                          ) -> dict[tuple[str, str], str]:
    """경매 (대분류,중분류)코드 → 품목명 역인덱스(반입량 매핑, §5.2-3).

    경매 API 의 품목은 (gds_lclsf_cd, gds_mclsf_cd) 쌍으로 식별된다(중분류코드는
    대분류 안에서만 유일). 두 코드가 모두 채워진 항목만 포함하고, 키는 문자열
    튜플로 정규화한다(코드 비교 일관성).
    """
    src = items if items is not None else ITEMS
    idx: dict[tuple[str, str], str] = {}
    for name, meta in src.items():
        if meta.vol_lclsf and meta.vol_mclsf:
            idx[(str(meta.vol_lclsf), str(meta.vol_mclsf))] = name
    return idx

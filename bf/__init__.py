# -*- coding: utf-8 -*-
"""장바구니 예보 AI — 핵심 패키지.

레이어: data(로딩·정규화) → core(분석) → app(표시). catalog 는 공용 메타.
공개 표면은 명세서 §3.5 시그니처를 따른다(변경 금지).
"""
from .data import (
    load_daily, load_from_api, validate_schema, SCHEMA, verify_catalog_codes,
)
from .core import (
    analyze, gluts, sell_first, substitutes, expensive, budget_basket,
    ItemState,
    VOLUME_SURGE, PRICE_DROP, RECENT_DAYS, BASE_MIN, BASE_MAX,
    BUY_DROP, WAIT_RISE, CV_WATCH,
)
from . import catalog

__all__ = [
    "load_daily", "load_from_api", "validate_schema", "SCHEMA",
    "verify_catalog_codes",
    "analyze", "gluts", "sell_first", "substitutes", "expensive", "budget_basket",
    "ItemState", "catalog",
    "VOLUME_SURGE", "PRICE_DROP", "RECENT_DAYS", "BASE_MIN", "BASE_MAX",
    "BUY_DROP", "WAIT_RISE", "CV_WATCH",
]

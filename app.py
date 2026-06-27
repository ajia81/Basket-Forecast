# -*- coding: utf-8 -*-
"""장바구니 예보 AI — Streamlit UI (명세서 §4).

표시 전용. 비즈니스 로직은 ``bf.core`` 만 호출한다. **키 주입 담당**(§5.2-5):
app.py 가 st.secrets 를 읽어 keys dict 로 데이터 계층에 전달한다(data.py 는 secrets 비의존).

화면: ① 오늘의 장보기 예보 · ② 예산별 장바구니 · ③ 비싸면 대체 · ④ 살까·기다릴까.
첫 화면은 '결정'이 먼저, 그래프는 화면4. selectbox 옵션은 list(states.keys())(리스크 #3).
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from bf import (
    load_daily, analyze, gluts, sell_first, substitutes, expensive, budget_basket,
)
from bf.catalog import ESSENTIAL_GROUPS
from bf.core import (
    VOLUME_SURGE, PRICE_DROP, RECENT_DAYS, BASE_MIN, BASE_MAX,
    SIGNAL_BUY, SIGNAL_WAIT, SIGNAL_WATCH, SIGNAL_NORMAL,
)

st.set_page_config(page_title="장바구니 예보 AI", page_icon="🛒", layout="wide")

# 신호별 고정 색상(§4 SIG_COLOR)
SIG_COLOR = {
    SIGNAL_BUY: "#2E7D32",    # 초록 — 지금 사면 좋은
    SIGNAL_WAIT: "#C62828",   # 빨강 — 기다리기
    SIGNAL_WATCH: "#F9A825",  # 노랑 — 변동성 주의
    SIGNAL_NORMAL: "#90A4AE", # 회색 — 보통
}
SIG_EMOJI = {SIGNAL_BUY: "🟢", SIGNAL_WAIT: "🔴", SIGNAL_WATCH: "🟡", SIGNAL_NORMAL: "⚪"}


# ── 데이터 로딩 (캐싱 + 폴백, §5.2-6 / T5) ────────────────────────────────
def _read_keys() -> dict | None:
    """st.secrets → keys dict. 시크릿 미설정이면 None(샘플 모드)."""
    try:
        return {
            "kamis_cert_key": st.secrets["KAMIS_CERT_KEY"],
            "kamis_cert_id": st.secrets["KAMIS_CERT_ID"],
            "data_go_kr": st.secrets["DATA_GO_KR_KEY"],
        }
    except Exception:   # FileNotFoundError(secrets.toml 없음) / KeyError 모두 흡수
        return None


@st.cache_data(ttl=6 * 60 * 60, show_spinner="시장 데이터 불러오는 중…")
def _get_data(source: str, _keys: dict | None, day_key: str) -> pd.DataFrame:
    # _keys 는 언더스코어 → 캐시 해시 제외(키 노출 방지). day_key 로 일 단위 갱신.
    return load_daily(source=source, keys=_keys)


def load_market(force_sample: bool):
    """실데이터 우선, 실패 시 샘플 폴백 + 경고 배너. 반환 (df, source_label, warn)."""
    keys = _read_keys()
    day_key = pd.Timestamp.today().strftime("%Y-%m-%d")
    if force_sample or keys is None:
        df = _get_data("sample", None, day_key)
        label = "샘플 데모 데이터" if keys is None else "샘플(수동 선택)"
        return df, label, None
    try:
        df = _get_data("api", keys, day_key)
        if df is None or df.empty:
            raise RuntimeError("API 응답이 비어 있음")
        return df, "실데이터(KAMIS·도매시장)", None
    except Exception as exc:   # 네트워크/파싱 실패 → 시연 보호 폴백
        df = _get_data("sample", None, day_key)
        return df, "샘플(폴백)", f"실데이터 연동 실패 → 샘플로 대체했습니다: {exc}"


def _pill(text: str, color: str) -> str:
    return (f"<span style='background:{color};color:#fff;padding:1px 8px;"
            f"border-radius:10px;font-size:0.8em;white-space:nowrap'>{text}</span>")


# ── 사이드바: 투명성 노출(평가 포인트, §4) ────────────────────────────────
def render_sidebar(states: dict, source_label: str):
    with st.sidebar:
        st.markdown("### ⚙️ 데이터 · 포착 기준")
        keys = _read_keys()
        force_sample = st.toggle("샘플 데모로 보기", value=(keys is None),
                                 disabled=(keys is None),
                                 help="실데이터 키가 없으면 항상 샘플로 동작합니다.")
        st.caption(f"현재 소스: **{source_label}**")
        st.divider()

        st.markdown("#### 🔍 과잉(글럿) 포착 규칙")
        st.markdown(
            f"- 반입량 변화율 **≥ +{VOLUME_SURGE:.0%}**\n"
            f"- 가격 변화율 **≤ {PRICE_DROP:.0%}**\n"
            f"- '현재' = 최근 **{RECENT_DAYS}일** 평균\n"
            f"- **최근 기준선** = 직전 **{BASE_MIN}~{BASE_MAX}일** 중앙값")
        st.caption("※ '평년/평월'이 아니라 **최근 추세(직전 N일)** 기준입니다. "
                   "다년 이력 연동 시 '전년 동기' 비교를 옵션으로 추가합니다.")
        st.divider()

        g = gluts(states)
        st.metric("오늘 과잉 포착", f"{len(g)} 품목")
        if g:
            st.caption("· " + " · ".join(s.item for s in g))
        st.caption("SUHO AI Works · 소비자는 가성비, 농민은 판로")
    return force_sample


# ── 화면 1: 오늘의 장보기 예보 ────────────────────────────────────────────
def tab_forecast(states: dict):
    g = gluts(states)
    if g:
        names = ", ".join(f"**{s.item}**(공급 {s.vol_chg:+.0%}·가격 {s.price_chg:+.0%})"
                          for s in g)
        st.success(f"📢 오늘 **{len(g)}개 품목**이 과잉입니다 — {names}\n\n"
                   f"공급이 몰려 값이 내렸어요. 지금이 살 때입니다. *(농가 판로에도 도움)*")
    else:
        st.info("오늘은 뚜렷한 과잉 품목이 없습니다. 아래 가성비 순위를 참고하세요.")

    st.markdown("#### 🥬 오늘 사면 좋은 작물 — 가성비 순")
    picks = sell_first(states, n=6)
    if not picks:
        st.warning("표시할 품목이 없습니다.")
        return
    cols = st.columns(min(3, len(picks)))
    for i, s in enumerate(picks):
        with cols[i % len(cols)]:
            st.metric(f"{SIG_EMOJI[s.signal]} {s.item}", f"{s.retail:,}원/kg",
                      delta=f"{s.price_chg:+.0%}", delta_color="inverse")
            badges = []
            if s.is_glut:
                badges.append(_pill("과잉·판로기여", "#6D4C41"))
            if s.in_season:
                badges.append(_pill("제철", "#00695C"))
            badges.append(_pill(s.signal, SIG_COLOR[s.signal]))
            st.markdown(" ".join(badges), unsafe_allow_html=True)

    st.divider()
    c1, c2, c3 = st.columns(3)
    _signal_list(c1, "🟢 구매추천", [s for s in states.values() if s.signal == SIGNAL_BUY])
    _signal_list(c2, "🟡 주의(변동성)", [s for s in states.values() if s.signal == SIGNAL_WATCH])
    _signal_list(c3, "🔴 대기(비쌈)", expensive(states))


def _signal_list(col, title: str, items: list):
    with col:
        st.markdown(f"**{title}**")
        if not items:
            st.caption("해당 없음")
            return
        for s in sorted(items, key=lambda x: x.price_chg):
            st.markdown(f"- {s.item} · {s.retail:,}원/kg ({s.price_chg:+.0%})")


# ── 화면 2: 예산별 장바구니 ───────────────────────────────────────────────
def tab_budget(states: dict):
    st.markdown("#### 💰 예산에 맞춘 장바구니 (과잉 우선 · 필수 용도군 보장)")
    budget = st.slider("예산", min_value=10000, max_value=100000, value=50000,
                       step=5000, format="%d원")
    res = budget_basket(states, budget)

    if not res["items"]:
        st.warning("이 예산으로 담을 수 있는 품목이 없습니다. 예산을 올려보세요.")
        return

    rows = []
    for s, q in res["items"]:
        rows.append({
            "품목": s.item, "용도군": s.group, "수량(분량)": f"{q} × {s.portion_kg}kg",
            "단가(원/kg)": s.retail, "금액": s.portion_cost * q,
            "신호": f"{SIG_EMOJI[s.signal]} {s.signal}", "사유": s.reason(),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={
                     "단가(원/kg)": st.column_config.NumberColumn(format="%d"),
                     "금액": st.column_config.NumberColumn(format="%d 원"),
                 })

    m1, m2, m3 = st.columns(3)
    m1.metric("합계", f"{res['total']:,}원")
    m2.metric("잔액", f"{res['leftover']:,}원")
    m3.metric("커버한 용도군", f"{len(res['groups_covered'])}개")
    covered = set(res["groups_covered"])
    missing = [g for g in ESSENTIAL_GROUPS if g not in covered]
    if res["glut_in_basket"] and not missing:
        st.success("✅ 과잉(저렴) 품목을 담아 **가성비 + 농가 판로**를 동시에 챙겼습니다.")
    elif missing:
        st.info(f"필수 용도군 미충족: {', '.join(missing)} (예산을 올리면 채워집니다).")


# ── 화면 3: 비싸면 대체 ───────────────────────────────────────────────────
def tab_substitute(states: dict):
    st.markdown("#### 🔁 비싼 품목 → 같은 용도군 가성비 대체재")
    pricey = expensive(states)
    options = list(states.keys())   # 실데이터 결측 대비(리스크 #3)
    if not options:
        st.warning("표시할 품목이 없습니다.")
        return

    default = pricey[0].item if pricey else options[0]
    target = st.selectbox("바꾸고 싶은(비싼) 품목", options, index=options.index(default))
    s = states[target]
    st.markdown(f"**{target}** — {s.retail:,}원/kg "
                f"({_pill(s.signal, SIG_COLOR[s.signal])} 가격 {s.price_chg:+.0%})",
                unsafe_allow_html=True)

    subs = substitutes(states, target)
    if not subs:
        st.info(f"같은 용도군({s.group})에 더 나은 대체재가 없습니다.")
        return
    st.caption(f"같은 용도군 **{s.group}** 에서 가성비 상위(과잉 우선):")
    for alt_s in subs:
        save = s.retail - alt_s.retail
        save_txt = f" · kg당 {save:,}원 절약" if save > 0 else ""
        st.markdown(
            f"- {SIG_EMOJI[alt_s.signal]} **{alt_s.item}** {alt_s.retail:,}원/kg "
            f"— 사유: _{alt_s.reason()}_{save_txt}")


# ── 화면 4: 살까·기다릴까 (그래프) ────────────────────────────────────────
def tab_trend(states: dict, df: pd.DataFrame):
    st.markdown("#### 📈 가격 추세 · 방향 신호")
    options = list(states.keys())
    if not options:
        st.warning("표시할 품목이 없습니다.")
        return
    item = st.selectbox("품목", options, key="trend_item")
    s = states[item]

    sub = df[df["item"] == item].sort_values("date")
    line = (alt.Chart(sub).mark_line(color="#B87333")
            .encode(x=alt.X("date:T", title="일자"),
                    y=alt.Y("retail:Q", title="소매가(원/kg)",
                            scale=alt.Scale(zero=False)),
                    tooltip=["date:T", "retail:Q", "volume:Q"])
            .properties(height=320))
    # 신 API(streamlit>=1.43): width="stretch" 사용. use_container_width 는 폐기(리스크 #2)
    st.altair_chart(line, width="stretch")

    arrow = {SIGNAL_BUY: "지금이 살 때 ⬇️", SIGNAL_WAIT: "조금 기다리기 ⬆️",
             SIGNAL_WATCH: "변동성 큼 ↕️", SIGNAL_NORMAL: "평소 수준 ➡️"}[s.signal]
    c1, c2 = st.columns([2, 3])
    c1.metric(f"{SIG_EMOJI[s.signal]} {item}", f"{s.retail:,}원/kg",
              delta=f"{s.price_chg:+.0%} vs 최근 기준선", delta_color="inverse")
    c2.markdown(f"### {arrow}")
    c2.caption(f"반입량 {s.vol_chg:+.0%} · 변동계수 {s.cv:.0%} · "
               f"기준선=직전 {BASE_MIN}~{BASE_MAX}일 중앙값")
    st.caption("※ 방향 신호는 최근 추세 기반 **보조 지표**입니다(미래가격 보장 아님).")


# ── 메인 ──────────────────────────────────────────────────────────────────
def main():
    st.title("🛒 장바구니 예보 AI")
    st.caption("과잉으로 값이 내린 농산물을 **반입량(공급)으로 매일 포착**해 장바구니에 연결합니다. "
               "*소비자는 가성비, 농민은 판로.*")

    # 1차 로딩(소스 결정 위해 사이드바 토글 먼저 읽기)
    keys = _read_keys()
    df, source_label, warn = load_market(force_sample=(keys is None))
    states = analyze(df)

    force_sample = render_sidebar(states, source_label)
    if force_sample and keys is not None:
        df, source_label, warn = load_market(force_sample=True)
        states = analyze(df)

    if warn:
        st.warning("⚠️ " + warn)
    if not states:
        st.error("데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return

    t1, t2, t3, t4 = st.tabs(
        ["🛒 오늘의 장보기 예보", "💰 예산별 장바구니", "🔁 비싸면 대체", "📈 살까·기다릴까"])
    with t1:
        tab_forecast(states)
    with t2:
        tab_budget(states)
    with t3:
        tab_substitute(states)
    with t4:
        tab_trend(states, df)


if __name__ == "__main__":
    main()

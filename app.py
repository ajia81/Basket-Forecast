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

# 신호별 고정 색상(§4 SIG_COLOR) — 시맨틱 팔레트(좋음=초록/비쌈=로즈/주의=앰버/보통=슬레이트)
SIG_COLOR = {
    SIGNAL_BUY: "#34D399",    # 에메랄드 — 지금 사면 좋은
    SIGNAL_WAIT: "#FB7185",   # 로즈 — 기다리기(비쌈)
    SIGNAL_WATCH: "#FBBF24",  # 앰버 — 변동성 주의
    SIGNAL_NORMAL: "#9AA8BC", # 슬레이트 — 보통
}
SIG_EMOJI = {SIGNAL_BUY: "🟢", SIGNAL_WAIT: "🔴", SIGNAL_WATCH: "🟡", SIGNAL_NORMAL: "⚪"}
SIG_CLASS = {SIGNAL_BUY: "buy", SIGNAL_WAIT: "wait", SIGNAL_WATCH: "watch",
             SIGNAL_NORMAL: "normal"}


# ── 디자인 시스템 (모던 카드 UI · §4 표시 전용) ────────────────────────────
def inject_css() -> None:
    """전역 테마 주입 — Pretendard 폰트 + 디자인 토큰 + 카드/칩/배너 스타일."""
    st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@latest/dist/web/static/pretendard.min.css');
:root{
  --font:'Pretendard','Pretendard Variable',-apple-system,BlinkMacSystemFont,'Segoe UI','Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif;
  --text:#EAF0F7; --muted:#94A6BD; --faint:#6B7F98;
  --border:rgba(255,255,255,.07); --copper:#C98A4B; --copper-strong:#E0A05A;
  --good:#34D399; --good-bg:rgba(52,211,153,.13);
  --bad:#FB7185;  --bad-bg:rgba(251,113,133,.13);
  --warn:#FBBF24; --warn-bg:rgba(251,191,36,.13);
  --slate:#9AA8BC;--slate-bg:rgba(154,168,188,.13);
}
html,body,.stApp,[data-testid="stSidebar"]{font-family:var(--font);}
.block-container{max-width:1200px;padding-top:2rem;}
h1,h2,h3,h4{font-family:var(--font);letter-spacing:-.4px;}

/* hero */
.hero{margin:0 0 6px;}
.hero .h-title{font-size:1.95rem;font-weight:900;letter-spacing:-1px;color:var(--text);display:flex;align-items:baseline;gap:6px;}
.hero .h-title .ai{color:var(--copper-strong);}
.hero .h-sub{color:var(--muted);margin-top:3px;font-size:.95rem;}
.hero .h-sub b{color:var(--text);} .hero .h-sub .accent{color:var(--copper-strong);font-weight:700;}

/* tabs */
.stTabs [data-baseweb="tab-list"]{gap:4px;border-bottom:1px solid var(--border);}
.stTabs [data-baseweb="tab"]{height:46px;padding:0 18px;background:transparent;color:var(--muted);font-weight:600;font-size:.98rem;}
.stTabs [aria-selected="true"]{color:var(--text);background:linear-gradient(180deg,rgba(201,138,75,.16),rgba(201,138,75,0));border-bottom:2px solid var(--copper-strong);}

/* section header */
.sec{display:flex;align-items:center;gap:9px;font-weight:800;font-size:1.12rem;color:var(--text);margin:18px 0 14px;}
.sec .bar{width:4px;height:19px;border-radius:3px;background:linear-gradient(var(--copper-strong),var(--copper));}
.sec .hint{font-weight:500;font-size:.82rem;color:var(--faint);margin-left:2px;}

/* banner */
.banner{display:flex;gap:14px;align-items:flex-start;padding:17px 20px;border-radius:16px;margin:4px 0 8px;
  background:linear-gradient(135deg,rgba(52,211,153,.15),rgba(201,138,75,.09));border:1px solid rgba(52,211,153,.30);}
.banner.neutral{background:linear-gradient(135deg,rgba(154,168,188,.10),rgba(255,255,255,.02));border-color:var(--border);}
.banner .ic{font-size:1.45rem;line-height:1.4;}
.banner .bt{font-weight:800;font-size:1.05rem;color:var(--text);}
.banner .bs{color:var(--muted);margin-top:4px;font-size:.92rem;}
.banner b{color:var(--good);font-weight:700;}

/* product grid + card */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:14px;}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;margin-top:6px;}
.card{background:linear-gradient(180deg,#16273F,#111E30);border:1px solid var(--border);border-radius:18px;padding:16px 18px 15px;transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease;}
.card:hover{transform:translateY(-3px);border-color:rgba(201,138,75,.45);box-shadow:0 12px 30px rgba(0,0,0,.38);}
.card .head{display:flex;justify-content:space-between;align-items:center;margin-bottom:11px;min-height:24px;}
.card .name{display:flex;align-items:center;gap:8px;font-weight:700;font-size:1.04rem;color:var(--text);}
.card .dot{width:9px;height:9px;border-radius:50%;box-shadow:0 0 0 3px rgba(255,255,255,.05);}
.card .price{font-size:1.72rem;font-weight:800;letter-spacing:-.6px;color:var(--text);line-height:1.1;font-variant-numeric:tabular-nums;}
.card .price .won{font-size:1rem;font-weight:700;margin-left:1px;}
.card .price .unit{font-size:.8rem;color:var(--faint);font-weight:600;margin-left:3px;}
.delta{display:inline-flex;align-items:center;gap:6px;margin-top:11px;padding:3px 11px;border-radius:999px;font-size:.82rem;font-weight:800;}
.delta .lab{font-weight:600;opacity:.85;}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:13px;}
.chip{font-size:.74rem;font-weight:700;padding:3px 9px;border-radius:8px;}
.chip.season{color:#5EEAD4;background:rgba(45,212,191,.12);}
.chip.buy{color:var(--good);background:var(--good-bg);} .chip.wait{color:var(--bad);background:var(--bad-bg);}
.chip.watch{color:var(--warn);background:var(--warn-bg);} .chip.normal{color:var(--slate);background:var(--slate-bg);}
.badge-glut{font-size:.72rem;font-weight:800;padding:3px 10px;border-radius:999px;color:#F4D9B0;
  background:linear-gradient(135deg,rgba(201,138,75,.32),rgba(201,138,75,.14));border:1px solid rgba(201,138,75,.5);}

/* kpi + list */
.kpi{background:linear-gradient(180deg,#16273F,#111E30);border:1px solid var(--border);border-radius:16px;padding:15px 18px;}
.kpi .lab{color:var(--muted);font-size:.83rem;font-weight:600;}
.kpi .val{font-size:1.5rem;font-weight:800;margin-top:4px;font-variant-numeric:tabular-nums;}
.list{background:rgba(255,255,255,.02);border:1px solid var(--border);border-radius:16px;padding:14px 17px;}
.list .lt{font-weight:700;font-size:.96rem;margin-bottom:8px;color:var(--text);}
.list .row{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px dashed rgba(255,255,255,.07);font-size:.9rem;}
.list .row:last-child{border-bottom:none;}
.list .row .nm{color:var(--text);font-weight:600;} .list .row .pv{color:var(--muted);font-variant-numeric:tabular-nums;}
.subline{display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:.92rem;margin:2px 0 4px;}
</style>
""", unsafe_allow_html=True)


def _delta_html(chg: float) -> str:
    """가격 변화율 → 색상 칩(소비자 관점: 하락=좋음 초록, 상승=로즈)."""
    pct = abs(chg) * 100
    if chg < -0.005:
        return (f"<div class='delta' style='color:var(--good);background:var(--good-bg)'>"
                f"▼ {pct:.0f}% <span class='lab'>싸졌어요</span></div>")
    if chg > 0.005:
        return (f"<div class='delta' style='color:var(--bad);background:var(--bad-bg)'>"
                f"▲ {pct:.0f}% <span class='lab'>올랐어요</span></div>")
    return ("<div class='delta' style='color:var(--slate);background:var(--slate-bg)'>"
            "― 0% <span class='lab'>보합</span></div>")


def product_card(s) -> str:
    """제품 카드 HTML(단일 라인 — st.markdown 코드블록화 방지)."""
    glut = ("<span class='badge-glut' title='공급 과잉 · 농가 판로 기여'>과잉</span>"
            if s.is_glut else "")
    chips = ""
    if s.in_season:
        chips += "<span class='chip season'>제철</span>"
    chips += f"<span class='chip {SIG_CLASS[s.signal]}'>{s.signal}</span>"
    return (
        "<div class='card'><div class='head'>"
        f"<span class='name'><span class='dot' style='background:{SIG_COLOR[s.signal]}'></span>{s.item}</span>"
        f"{glut}</div>"
        f"<div class='price'>{s.retail:,}<span class='won'>원</span><span class='unit'>/kg</span></div>"
        f"{_delta_html(s.price_chg)}"
        f"<div class='chips'>{chips}</div></div>")


def kpi_html(label: str, value: str, accent: str = "var(--text)") -> str:
    return (f"<div class='kpi'><div class='lab'>{label}</div>"
            f"<div class='val' style='color:{accent}'>{value}</div></div>")


def sec(title: str, hint: str = "") -> None:
    h = f"<span class='hint'>{hint}</span>" if hint else ""
    st.markdown(f"<div class='sec'><span class='bar'></span>{title}{h}</div>",
                unsafe_allow_html=True)


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
        names = ", ".join(f"<b>{s.item}</b>(공급 {s.vol_chg:+.0%}·가격 {s.price_chg:+.0%})"
                          for s in g)
        st.markdown(
            "<div class='banner'><div class='ic'>📢</div><div>"
            f"<div class='bt'>오늘 {len(g)}개 품목이 과잉입니다 — {names}</div>"
            "<div class='bs'>공급이 몰려 값이 내렸어요. "
            "<b style='color:var(--copper-strong)'>지금이 살 때</b>입니다. "
            "<span style='opacity:.8'>(농가 판로에도 도움)</span></div></div></div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='banner neutral'><div class='ic'>🧺</div><div>"
            "<div class='bt'>오늘은 뚜렷한 과잉 품목이 없습니다</div>"
            "<div class='bs'>아래 가성비 순위를 참고해 장바구니를 채워보세요.</div>"
            "</div></div>", unsafe_allow_html=True)

    sec("🥬 오늘 사면 좋은 작물", "가성비 순")
    picks = sell_first(states, n=6)
    if not picks:
        st.warning("표시할 품목이 없습니다.")
        return
    cards = "".join(product_card(s) for s in picks)
    st.markdown(f"<div class='grid'>{cards}</div>", unsafe_allow_html=True)

    sec("신호별 한눈에", "지금 사면 좋은 · 변동성 주의 · 대기")
    buy = [s for s in states.values() if s.signal == SIGNAL_BUY]
    watch = [s for s in states.values() if s.signal == SIGNAL_WATCH]
    wait = expensive(states)
    st.markdown(
        "<div class='grid3'>"
        + _signal_list_html("🟢 지금 사면 좋은", buy)
        + _signal_list_html("🟡 변동성 주의", watch)
        + _signal_list_html("🔴 대기 (비쌈)", wait)
        + "</div>", unsafe_allow_html=True)


def _signal_list_html(title: str, items: list) -> str:
    if not items:
        rows = "<div class='row'><span class='nm' style='color:var(--faint)'>해당 없음</span></div>"
    else:
        rows = "".join(
            f"<div class='row'><span class='nm'>{s.item}</span>"
            f"<span class='pv'>{s.retail:,}원/kg · {s.price_chg:+.0%}</span></div>"
            for s in sorted(items, key=lambda x: x.price_chg))
    return f"<div class='list'><div class='lt'>{title}</div>{rows}</div>"


# ── 화면 2: 예산별 장바구니 ───────────────────────────────────────────────
def tab_budget(states: dict):
    sec("💰 예산에 맞춘 장바구니", "과잉 우선 · 필수 용도군 보장")
    budget = st.slider("예산", min_value=10000, max_value=100000, value=50000,
                       step=5000, format="%d원")
    res = budget_basket(states, budget)

    if not res["items"]:
        st.warning("이 예산으로 담을 수 있는 품목이 없습니다. 예산을 올려보세요.")
        return

    m1, m2, m3 = st.columns(3)
    m1.markdown(kpi_html("합계", f"{res['total']:,}원", "var(--copper-strong)"),
                unsafe_allow_html=True)
    m2.markdown(kpi_html("잔액", f"{res['leftover']:,}원"), unsafe_allow_html=True)
    m3.markdown(kpi_html("커버한 용도군", f"{len(res['groups_covered'])}개"),
                unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
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

    covered = set(res["groups_covered"])
    missing = [g for g in ESSENTIAL_GROUPS if g not in covered]
    if res["glut_in_basket"] and not missing:
        st.success("✅ 과잉(저렴) 품목을 담아 **가성비 + 농가 판로**를 동시에 챙겼습니다.")
    elif missing:
        st.info(f"필수 용도군 미충족: {', '.join(missing)} (예산을 올리면 채워집니다).")


# ── 화면 3: 비싸면 대체 ───────────────────────────────────────────────────
def tab_substitute(states: dict):
    sec("🔁 비싸면 대체", "같은 용도군 가성비 대체재")
    pricey = expensive(states)
    options = list(states.keys())   # 실데이터 결측 대비(리스크 #3)
    if not options:
        st.warning("표시할 품목이 없습니다.")
        return

    default = pricey[0].item if pricey else options[0]
    target = st.selectbox("바꾸고 싶은(비싼) 품목", options, index=options.index(default))
    s = states[target]
    st.markdown(
        f"<div class='subline'><span class='dot' style='width:9px;height:9px;border-radius:50%;"
        f"display:inline-block;background:{SIG_COLOR[s.signal]}'></span>"
        f"<b style='color:var(--text);font-size:1.05rem'>{target}</b> "
        f"<span style='color:var(--text);font-weight:700'>{s.retail:,}원/kg</span>"
        f"<span class='chip {SIG_CLASS[s.signal]}'>{s.signal}</span>"
        f"<span>가격 {s.price_chg:+.0%}</span></div>", unsafe_allow_html=True)

    subs = substitutes(states, target)
    if not subs:
        st.info(f"같은 용도군({s.group})에 더 나은 대체재가 없습니다.")
        return
    st.markdown(f"<div class='subline'>같은 용도군 <b style='color:var(--text)'>&nbsp;{s.group}&nbsp;</b> "
                "에서 가성비 상위 (과잉 우선)</div>", unsafe_allow_html=True)
    cards = ""
    for a in subs:
        save = s.retail - a.retail
        save_txt = (f"<span class='chip buy'>kg당 {save:,}원 절약</span>" if save > 0 else "")
        cards += (
            "<div class='card'><div class='head'>"
            f"<span class='name'><span class='dot' style='background:{SIG_COLOR[a.signal]}'></span>{a.item}</span>"
            f"{save_txt}</div>"
            f"<div class='price'>{a.retail:,}<span class='won'>원</span><span class='unit'>/kg</span></div>"
            f"<div class='chips'><span class='chip {SIG_CLASS[a.signal]}'>{a.signal}</span>"
            f"<span class='chip season' style='color:var(--muted);background:rgba(255,255,255,.05)'>사유 {a.reason()}</span>"
            "</div></div>")
    st.markdown(f"<div class='grid'>{cards}</div>", unsafe_allow_html=True)


# ── 화면 4: 살까·기다릴까 (그래프) ────────────────────────────────────────
def tab_trend(states: dict, df: pd.DataFrame):
    sec("📈 살까·기다릴까", "가격 추세 · 방향 신호")
    options = list(states.keys())
    if not options:
        st.warning("표시할 품목이 없습니다.")
        return
    item = st.selectbox("품목", options, key="trend_item")
    s = states[item]

    sub = df[df["item"] == item].sort_values("date")
    grad = alt.Gradient(
        gradient="linear", x1=1, x2=1, y1=1, y2=0,
        stops=[alt.GradientStop(color="rgba(201,138,75,0.02)", offset=0),
               alt.GradientStop(color="rgba(224,160,90,0.35)", offset=1)])
    area = (alt.Chart(sub)
            .mark_area(line={"color": "#E0A05A", "strokeWidth": 2.5}, color=grad,
                       interpolate="monotone")
            .encode(x=alt.X("date:T", title=None,
                            axis=alt.Axis(format="%m/%d", tickCount=6)),
                    y=alt.Y("retail:Q", title="소매가 (원/kg)",
                            scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip("date:T", title="일자"),
                             alt.Tooltip("retail:Q", title="소매가", format=","),
                             alt.Tooltip("volume:Q", title="반입량", format=",.0f")])
            .properties(height=320))
    chart = (area
             .configure_view(strokeWidth=0)
             .configure(background="rgba(0,0,0,0)")
             .configure_axis(grid=True, gridColor="#ffffff10", domainColor="#ffffff22",
                             labelColor="#94A6BD", titleColor="#94A6BD",
                             labelFontSize=12, titleFontSize=12))
    # 신 API(streamlit>=1.43): width="stretch" 사용. use_container_width 는 폐기(리스크 #2)
    st.altair_chart(chart, width="stretch")

    arrow = {SIGNAL_BUY: "지금이 살 때 ⬇️", SIGNAL_WAIT: "조금 기다리기 ⬆️",
             SIGNAL_WATCH: "변동성 큼 ↕️", SIGNAL_NORMAL: "평소 수준 ➡️"}[s.signal]
    c1, c2 = st.columns([2, 3])
    c1.markdown(
        kpi_html(f"{SIG_EMOJI[s.signal]} {item}",
                 f"{s.retail:,}원/kg", SIG_COLOR[s.signal])
        + f"<div class='subline' style='margin-top:8px'>가격 {s.price_chg:+.0%} "
          "<span style='opacity:.7'>vs 최근 기준선</span></div>",
        unsafe_allow_html=True)
    c2.markdown(
        f"<div style='font-size:1.5rem;font-weight:800;color:{SIG_COLOR[s.signal]};"
        f"margin-top:2px'>{arrow}</div>"
        f"<div class='subline'>반입량 {s.vol_chg:+.0%} · 변동계수 {s.cv:.0%} · "
        f"기준선=직전 {BASE_MIN}~{BASE_MAX}일 중앙값</div>", unsafe_allow_html=True)
    st.caption("※ 방향 신호는 최근 추세 기반 **보조 지표**입니다(미래가격 보장 아님).")


# ── 메인 ──────────────────────────────────────────────────────────────────
def main():
    inject_css()
    st.markdown(
        "<div class='hero'>"
        "<div class='h-title'>🛒 장바구니 예보 <span class='ai'>AI</span></div>"
        "<div class='h-sub'>과잉으로 값이 내린 농산물을 <b>반입량(공급)으로 매일 포착</b>해 "
        "장바구니에 연결합니다. <span class='accent'>소비자는 가성비, 농민은 판로.</span></div>"
        "</div>", unsafe_allow_html=True)

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

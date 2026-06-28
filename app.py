# -*- coding: utf-8 -*-
"""장바구니 예보 AI — Streamlit UI (명세서 §4).

표시 전용. 비즈니스 로직은 ``bf.core`` 만 호출한다. **키 주입 담당**(§5.2-5):
app.py 가 st.secrets 를 읽어 keys dict 로 데이터 계층에 전달한다(data.py 는 secrets 비의존).

화면: ① 오늘의 장보기 예보 · ② 예산별 장바구니 · ③ 비싸면 대체 · ④ 살까·기다릴까.
첫 화면은 '결정'이 먼저, 그래프는 화면4. selectbox 옵션은 list(states.keys())(리스크 #3).

디자인: 라이트 + 그린 테마(standalone 시안 기준). 표시 토큰만 바뀌며 핵심 로직은 불변.
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

# 신호별 고정 색상(§4) — standalone sigStyle 팔레트(좋음=그린/비쌈=레드/주의=앰버/보통=슬레이트)
SIG_COLOR = {            # 도트 색
    SIGNAL_BUY: "#1F8F4E",
    SIGNAL_WAIT: "#E03131",
    SIGNAL_WATCH: "#F08C00",
    SIGNAL_NORMAL: "#B7BEB7",
}
SIG_STYLE = {            # (글자색, 배경색) — 칩/필
    SIGNAL_BUY:    ("#1E7E34", "#E9F5EC"),
    SIGNAL_WAIT:   ("#C92A2A", "#FDF3F3"),
    SIGNAL_WATCH:  ("#B45309", "#FDF8EE"),
    SIGNAL_NORMAL: ("#6B7770", "#F1F3EF"),
}
# 신호별 한눈에 카드 종류
SIGNAL_LIST_KIND = {SIGNAL_BUY: "buy", SIGNAL_WATCH: "watch", SIGNAL_WAIT: "wait"}


# ── 디자인 시스템 (라이트·그린 카드 UI · §4 표시 전용) ──────────────────────
def inject_css() -> None:
    """전역 테마 주입 — Pretendard 폰트 + 라이트/그린 토큰 + 카드/칩/배너 스타일."""
    st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@latest/dist/web/static/pretendard.min.css');
:root{
  --font:'Pretendard','Pretendard Variable',-apple-system,BlinkMacSystemFont,'Segoe UI','Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif;
  --bg:#F6F8F3; --card:#FFFFFF; --text:#111E18; --muted:#6B7770; --faint:#9AA39C;
  --line:#E6E8E3; --green:#1F8F4E; --green-strong:#1E7E34; --green-bg:#E9F5EC; --dark:#0F2A1B;
}
html,body,.stApp,[data-testid="stSidebar"]{font-family:var(--font);}
.stApp{background:var(--bg);}
.block-container{max-width:1340px;padding-top:2.2rem;}
h1,h2,h3,h4{font-family:var(--font);}
*{font-variant-numeric:tabular-nums;}

/* 위젯 라벨 */
[data-testid="stWidgetLabel"] p{font-size:13px;color:var(--muted);font-weight:600;}
/* selectbox */
div[data-baseweb="select"]>div{border-radius:10px;border-color:#DCE0D8;}

/* hero */
.hero{margin-bottom:4px;}
.hero .ht{display:flex;align-items:baseline;gap:11px;font-size:28px;font-weight:800;letter-spacing:-.03em;color:var(--text);}
.hero .ht .ai{color:var(--green);}
.hero .hs{margin-top:8px;font-size:14.5px;color:var(--muted);line-height:1.6;}
.hero .hs b{color:var(--text);} .hero .hs b.g{color:var(--green);}

/* tabs */
.stTabs [data-baseweb="tab-list"]{gap:28px;border-bottom:1px solid #E5E8E1;}
.stTabs [data-baseweb="tab"]{height:auto;padding:0 2px 13px;background:transparent;color:#8A938C;font-weight:600;font-size:15px;}
.stTabs [aria-selected="true"]{color:var(--green);font-weight:700;}
.stTabs [data-baseweb="tab-highlight"]{background:var(--green);height:2px;}
.stTabs [data-baseweb="tab-border"]{background:transparent;}

/* section header */
.sec{display:flex;align-items:baseline;gap:9px;margin:28px 0 14px;}
.sec.between{justify-content:space-between;}
.sec .sl{display:flex;align-items:baseline;gap:9px;}
.sec .st{font-size:17px;font-weight:800;color:var(--text);letter-spacing:-.01em;}
.sec .hint{font-size:12.5px;color:var(--faint);font-weight:600;}
.sec .right{font-size:12px;color:var(--faint);font-weight:600;}

/* glut banner */
.glutbanner{background:var(--card);border:1px solid #DDE7DF;border-left:3px solid var(--green);border-radius:10px;padding:17px 20px;}
.glutbanner.neutral{border-left-color:#B7BEB7;}
.glutbanner .top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.glutbanner .pill{font-size:11px;font-weight:800;letter-spacing:.04em;color:var(--green);background:var(--green-bg);padding:3px 8px;border-radius:5px;}
.glutbanner .pill.muted{color:var(--muted);background:#F1F3EF;}
.glutbanner .sub{font-size:13px;color:#8A938C;}
.glutbanner .line{margin-top:10px;font-size:16px;font-weight:700;color:#162B1F;}
.glutbanner .line .it{margin-right:18px;}
.glutbanner .line .det{color:var(--muted);font-weight:600;font-size:13.5px;}
.glutbanner .line.soft{font-size:14px;font-weight:600;color:var(--muted);}

/* product grid + card */
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:6px;}
.pcard{background:var(--card);border:1px solid var(--line);border-top:3px solid var(--green);border-radius:12px;padding:18px 20px;}
.pcard .phead{display:flex;justify-content:space-between;align-items:center;}
.pcard .pname{font-size:18px;font-weight:700;color:var(--text);}
.pcard .glut{font-size:11px;font-weight:700;color:#C2410C;border:1px solid #F0C9A8;background:#FFF6EE;padding:2px 7px;border-radius:5px;}
.pcard .pprice{margin-top:12px;font-size:30px;font-weight:800;letter-spacing:-.02em;color:var(--text);}
.pcard .pprice .u{font-size:13px;font-weight:600;color:var(--muted);margin-left:3px;}
.delta{margin-top:8px;font-size:13.5px;font-weight:700;}
.delta .lab{color:var(--faint);font-weight:500;}
.delta.down{color:var(--green-strong);} .delta.up{color:#C92A2A;} .delta.flat{color:var(--muted);}
.chips{margin-top:13px;display:flex;gap:6px;flex-wrap:wrap;}
.chip{font-size:11.5px;color:#52605A;border:1px solid #E0E4DE;padding:3px 8px;border-radius:5px;}

/* signal list cards */
.slist{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card);}
.slist .shead{display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid;}
.slist .sdot{width:8px;height:8px;border-radius:2px;}
.slist .stitle{font-weight:700;font-size:14px;}
.slist.buy .shead{background:#F2F9F4;border-color:#E0EBE2;} .slist.buy .sdot{background:#1F8F4E;} .slist.buy .stitle{color:#1E7E34;} .slist.buy .pv b{color:#1E7E34;}
.slist.watch .shead{background:#FDF8EE;border-color:#F0E6CE;} .slist.watch .sdot{background:#F08C00;} .slist.watch .stitle{color:#B45309;} .slist.watch .pv b{color:#B45309;}
.slist.wait .shead{background:#FDF3F3;border-color:#F3D7D7;} .slist.wait .sdot{background:#E03131;} .slist.wait .stitle{color:#C92A2A;} .slist.wait .pv b{color:#C92A2A;}
.slist .sbody{padding:4px 16px 12px;}
.slist .srow{display:flex;justify-content:space-between;font-size:13.5px;padding:9px 0;}
.slist .srow + .srow{border-top:1px solid #EEF2EE;}
.slist .srow .nm{font-weight:600;color:var(--text);}
.slist .srow .pv{color:var(--muted);}
.slist .empty{color:#B6BDB2;font-size:13px;padding:9px 0;}

/* kpi */
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;}
.kpi .lab{font-size:13px;color:var(--muted);font-weight:600;}
.kpi .val{font-size:28px;font-weight:800;margin-top:4px;letter-spacing:-.01em;color:var(--text);}
.kpi .val .won{font-size:15px;font-weight:600;color:var(--muted);margin-left:1px;}

/* budget slider card */
.budgetcard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 22px 8px;}
.budgetcard .bh{display:flex;justify-content:space-between;align-items:baseline;}
.budgetcard .bh .bl{font-size:13px;color:var(--muted);font-weight:600;}
.budgetcard .bh .bv{font-size:18px;font-weight:800;color:var(--green);}

/* budget table */
.bt{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:14px;}
.bt .bthead,.bt .btrow{display:grid;grid-template-columns:1.1fr .95fr 1.1fr .95fr 1fr 1.15fr 1.7fr;gap:8px;align-items:center;}
.bt .bthead{padding:13px 14px;background:#F4F6F1;font-size:12px;font-weight:700;color:#8A938C;}
.bt .btrow{padding:13px 14px;border-top:1px solid #EEF1ED;font-size:13.5px;}
.bt .r{text-align:right;}
.bt .nm{font-weight:700;font-size:14px;color:var(--text);}
.bt .mu{color:var(--muted);}
.bt .btrow .r b{font-weight:700;color:var(--text);}
.bt .won{color:var(--faint);font-weight:500;}
.bt .rs{color:var(--faint);font-size:12.5px;}
.bt .pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:700;padding:4px 10px;border-radius:999px;}
.bt .pd{width:7px;height:7px;border-radius:50%;}

/* ok / info banner */
.okbanner{margin-top:16px;border-radius:10px;padding:15px 18px;display:flex;align-items:center;gap:10px;font-size:14px;}
.okbanner.good{background:var(--green-bg);border:1px solid #CFE9D4;color:#18301F;}
.okbanner.good b{color:#1E7E34;}
.okbanner.info{background:#F4F6F1;border:1px solid var(--line);color:var(--muted);}

/* substitute */
.exline{display:flex;align-items:center;gap:10px;margin-top:22px;flex-wrap:wrap;}
.exline .exdot{width:9px;height:9px;border-radius:50%;display:inline-block;}
.exline .exname{font-size:18px;font-weight:700;color:var(--text);}
.exline .exprice{font-size:18px;font-weight:800;color:var(--text);}
.exline .exprice .u{font-size:13px;color:var(--muted);font-weight:600;margin-left:2px;}
.exline .exchg{font-size:13px;font-weight:600;}
.exsub{font-size:13px;color:var(--muted);margin-top:8px;}
.exsub b{color:var(--text);} .exsub .mu{color:var(--faint);}
.altcard{background:var(--card);border:1px solid var(--line);border-top:3px solid var(--green);border-radius:14px;padding:20px 22px;margin-top:14px;}
.altcard .ahead{display:flex;justify-content:space-between;align-items:center;}
.altcard .aname{display:flex;align-items:center;gap:9px;font-size:20px;font-weight:700;color:var(--text);}
.altcard .adot{width:10px;height:10px;border-radius:50%;display:inline-block;}
.altcard .savepill{font-size:12px;font-weight:800;color:#1E7E34;background:var(--green-bg);padding:6px 12px;border-radius:999px;}
.altcard .aprice{margin-top:14px;font-size:32px;font-weight:800;letter-spacing:-.02em;color:var(--text);}
.altcard .aprice .u{font-size:14px;font-weight:600;color:var(--muted);margin-left:4px;}
.altcard .achips{margin-top:14px;display:flex;gap:8px;flex-wrap:wrap;}
.sigchip{font-size:12px;font-weight:700;padding:5px 11px;border-radius:6px;}
.nchip{font-size:12px;color:#52605A;border:1px solid #E0E4DE;padding:5px 11px;border-radius:6px;}

/* trend cards */
.tcards{display:flex;gap:14px;margin-top:16px;flex-wrap:wrap;}
.tcard{flex:1;min-width:240px;background:var(--card);border:1px solid var(--line);border-top:3px solid var(--green);border-radius:12px;padding:18px 22px;}
.tcard .nm{display:flex;align-items:center;gap:8px;font-size:16px;font-weight:700;color:var(--text);}
.tcard .nm .d{width:9px;height:9px;border-radius:50%;}
.tcard .pr{margin-top:8px;font-size:30px;font-weight:800;letter-spacing:-.02em;}
.tcard .pr .u{font-size:14px;color:var(--muted);font-weight:600;margin-left:4px;}
.tdark{flex:1.4;min-width:280px;background:var(--dark);border-radius:12px;padding:18px 22px;color:#fff;}
.tdark .dt{display:flex;align-items:center;gap:8px;font-size:20px;font-weight:800;}
.tdark .ds{margin-top:8px;font-size:13.5px;color:#A9D4B8;}
.tdark .ds b{color:#fff;}
.tdark .note{margin-top:8px;font-size:11.5px;color:#6E977E;}

/* sidebar */
[data-testid="stSidebar"]{background:#fff;border-right:1px solid #E8EAE4;}
.sb-h{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:800;color:var(--text);margin-bottom:14px;}
.sb-src{font-size:11.5px;color:var(--faint);margin:-2px 0 0;}
.sb-src b{color:var(--muted);}
.sb-sep{height:1px;background:#EDF0EA;margin:18px 0;}
.sb-title{font-size:14px;font-weight:800;color:var(--text);margin-bottom:12px;}
.sb-rules{display:flex;flex-direction:column;gap:9px;}
.sb-rules .rr{display:flex;justify-content:space-between;font-size:13px;background:#F7F9F5;border:1px solid #ECEFE8;border-radius:8px;padding:9px 11px;}
.sb-rules .rr span:first-child{color:var(--muted);}
.sb-rules .gv{font-weight:700;color:#1E7E34;}
.sb-rules .bv{font-weight:700;color:var(--text);}
.sb-note{margin:16px 0 0;font-size:12px;line-height:1.7;color:var(--faint);}
.sb-note b{color:var(--muted);}
.sb-metric{background:var(--dark);border-radius:14px;padding:18px;}
.sb-metric .ml{font-size:12px;color:#8FC9A4;font-weight:600;}
.sb-metric .mv{font-size:30px;font-weight:800;color:#fff;margin:2px 0 4px;}
.sb-metric .mv span{font-size:16px;font-weight:600;color:#C7E6D2;}
.sb-metric .ms{font-size:13px;color:#A9D4B8;}
.sb-foot{margin:18px 0 0;font-size:11.5px;color:#B6BDB2;line-height:1.6;}
</style>
""", unsafe_allow_html=True)


def _delta_html(chg: float) -> str:
    """가격 변화율 → 카드 인라인 표기(하락=좋음 그린, 상승=레드 · vs 기준선)."""
    pct = abs(chg) * 100
    if chg < -0.005:
        return f"<div class='delta down'>▼ {pct:.0f}% <span class='lab'>vs 기준선</span></div>"
    if chg > 0.005:
        return f"<div class='delta up'>▲ {pct:.0f}% <span class='lab'>vs 기준선</span></div>"
    return "<div class='delta flat'>― 0% <span class='lab'>vs 기준선</span></div>"


def product_card(s) -> str:
    """제품 카드 HTML(단일 라인 — st.markdown 코드블록화 방지)."""
    glut = "<span class='glut' title='공급 과잉 · 농가 판로 기여'>과잉</span>" if s.is_glut else ""
    chips = "<span class='chip'>제철</span>" if s.in_season else ""
    chips += f"<span class='chip'>{s.signal}</span>"
    return (
        "<div class='pcard'><div class='phead'>"
        f"<span class='pname'>{s.item}</span>{glut}</div>"
        f"<div class='pprice'>{s.retail:,}<span class='u'>원/kg</span></div>"
        f"{_delta_html(s.price_chg)}"
        f"<div class='chips'>{chips}</div></div>")


def kpi_html(label: str, value: str, accent: str = "var(--text)") -> str:
    return (f"<div class='kpi'><div class='lab'>{label}</div>"
            f"<div class='val' style='color:{accent}'>{value}</div></div>")


def sec(title: str, hint: str = "", right: str = "") -> None:
    left = f"<span class='st'>{title}</span>"
    if hint:
        left += f"<span class='hint'>{hint}</span>"
    if right:
        st.markdown(f"<div class='sec between'><span class='sl'>{left}</span>"
                    f"<span class='right'>{right}</span></div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='sec'>{left}</div>", unsafe_allow_html=True)


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
        st.markdown("<div class='sb-h'><span>⚙️</span> 데이터 · 포착 기준</div>",
                    unsafe_allow_html=True)
        keys = _read_keys()
        force_sample = st.toggle("샘플 데모로 보기", value=(keys is None),
                                 disabled=(keys is None),
                                 help="실데이터 키가 없으면 항상 샘플로 동작합니다.")
        st.markdown(f"<div class='sb-src'>현재 소스 · <b>{source_label}</b></div>",
                    unsafe_allow_html=True)
        st.markdown("<div class='sb-sep'></div>", unsafe_allow_html=True)

        st.markdown("<div class='sb-title'>🔍 과잉(글럿) 포착 규칙</div>",
                    unsafe_allow_html=True)
        st.markdown(
            "<div class='sb-rules'>"
            f"<div class='rr'><span>반입량 변화율</span><span class='gv'>≥ +{VOLUME_SURGE:.0%}</span></div>"
            f"<div class='rr'><span>가격 변화율</span><span class='gv'>≤ {PRICE_DROP:.0%}</span></div>"
            f"<div class='rr'><span>'현재' 기준</span><span class='bv'>최근 {RECENT_DAYS}일 평균</span></div>"
            f"<div class='rr'><span>최근 기준선</span><span class='bv'>직전 {BASE_MIN}~{BASE_MAX}일 중앙값</span></div>"
            "</div>", unsafe_allow_html=True)
        st.markdown(
            "<p class='sb-note'>※ '평년/평월'이 아니라 <b>최근 추세(직전 N일)</b> 기준입니다. "
            "다년 이력 연동 시 '전년 동기' 비교를 옵션으로 추가합니다.</p>",
            unsafe_allow_html=True)
        st.markdown("<div class='sb-sep'></div>", unsafe_allow_html=True)

        g = gluts(states)
        names = " · ".join(s.item for s in g) if g else "없음"
        st.markdown(
            "<div class='sb-metric'><div class='ml'>오늘 과잉 포착</div>"
            f"<div class='mv'>{len(g)} <span>품목</span></div>"
            f"<div class='ms'>{names}</div></div>", unsafe_allow_html=True)
        st.markdown("<p class='sb-foot'>SUHO AI Works · 소비자는 가성비, 농민은 판로</p>",
                    unsafe_allow_html=True)
    return force_sample


# ── 화면 1: 오늘의 장보기 예보 ────────────────────────────────────────────
def tab_forecast(states: dict):
    g = gluts(states)
    if g:
        parts = "".join(
            f"<span class='it'>{s.item} <span class='det'>공급 {s.vol_chg:+.0%} / "
            f"가격 {s.price_chg:+.0%}</span></span>" for s in g)
        st.markdown(
            "<div class='glutbanner'><div class='top'>"
            "<span class='pill'>GLUT · 과잉 포착</span>"
            f"<span class='sub'>오늘 {len(g)}개 품목 — 지금이 살 때</span></div>"
            f"<div class='line'>{parts}</div></div>", unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='glutbanner neutral'><div class='top'>"
            "<span class='pill muted'>대기</span>"
            "<span class='sub'>오늘은 뚜렷한 과잉 품목이 없습니다</span></div>"
            "<div class='line soft'>아래 가성비 순위를 참고해 장바구니를 채워보세요.</div></div>",
            unsafe_allow_html=True)

    sec("오늘 사면 좋은 작물", right="SORTED BY 가성비")
    picks = sell_first(states, n=6)
    if not picks:
        st.info("오늘은 특별히 저렴하거나 과잉인 품목이 없습니다. "
                "필요한 품목은 '살까·기다릴까'에서 추세를 확인하세요.")
        return
    cards = "".join(product_card(s) for s in picks)
    st.markdown(f"<div class='grid3'>{cards}</div>", unsafe_allow_html=True)

    sec("신호별 한눈에")
    buy = [s for s in states.values() if s.signal == SIGNAL_BUY]
    watch = [s for s in states.values() if s.signal == SIGNAL_WATCH]
    wait = expensive(states)
    st.markdown(
        "<div class='grid3'>"
        + _signal_list_html("지금 사면 좋은", buy, "buy")
        + _signal_list_html("변동성 주의", watch, "watch")
        + _signal_list_html("대기 (비쌈)", wait, "wait")
        + "</div>", unsafe_allow_html=True)


def _signal_list_html(title: str, items: list, kind: str) -> str:
    if not items:
        body = "<div class='empty'>해당 없음</div>"
    else:
        body = "".join(
            f"<div class='srow'><span class='nm'>{s.item}</span>"
            f"<span class='pv'>{s.retail:,}원/kg · <b>{s.price_chg:+.0%}</b></span></div>"
            for s in sorted(items, key=lambda x: x.price_chg))
    return (f"<div class='slist {kind}'><div class='shead'><span class='sdot'></span>"
            f"<span class='stitle'>{title}</span></div>"
            f"<div class='sbody'>{body}</div></div>")


# ── 화면 2: 예산별 장바구니 ───────────────────────────────────────────────
def tab_budget(states: dict):
    sec("💰 예산에 맞춘 장바구니", hint="과잉 우선 · 필수 용도군 보장")
    budget = st.slider("예산", min_value=20000, max_value=100000, value=50000,
                       step=1000, format="%d원")
    res = budget_basket(states, budget)

    if not res["items"]:
        st.warning("이 예산으로 담을 수 있는 품목이 없습니다. 예산을 올려보세요.")
        return

    st.markdown(
        "<div class='kpis'>"
        + kpi_html("합계", f"{res['total']:,}<span class='won'>원</span>")
        + kpi_html("잔액", f"{res['leftover']:,}<span class='won'>원</span>", "#1E7E34")
        + kpi_html("커버한 용도군", f"{len(res['groups_covered'])}개")
        + "</div>", unsafe_allow_html=True)

    head = ("<div class='bt'><div class='bthead'><span>품목</span><span>용도군</span>"
            "<span>수량(분량)</span><span class='r'>단가(원/kg)</span><span class='r'>금액</span>"
            "<span>신호</span><span>사유</span></div>")
    body = ""
    for s, q in res["items"]:
        color, bg = SIG_STYLE[s.signal]
        amount = s.portion_cost * q
        body += (
            "<div class='btrow'>"
            f"<span class='nm'>{s.item}</span><span class='mu'>{s.group}</span>"
            f"<span class='mu'>{q} × {s.portion_kg}kg</span>"
            f"<span class='r'>{s.retail:,}</span>"
            f"<span class='r'><b>{amount:,}</b><span class='won'> 원</span></span>"
            f"<span><span class='pill' style='color:{color};background:{bg}'>"
            f"<span class='pd' style='background:{SIG_COLOR[s.signal]}'></span>{s.signal}</span></span>"
            f"<span class='rs'>{s.reason()}</span></div>")
    st.markdown(head + body + "</div>", unsafe_allow_html=True)

    covered = set(res["groups_covered"])
    missing = [g for g in ESSENTIAL_GROUPS if g not in covered]
    if res["glut_in_basket"] and not missing:
        st.markdown(
            "<div class='okbanner good'><span style='font-size:18px'>✅</span>"
            "<span>과잉(저렴) 품목을 담아 <b>가성비 + 농가 판로</b>를 동시에 챙겼습니다.</span></div>",
            unsafe_allow_html=True)
    elif missing:
        st.markdown(
            "<div class='okbanner info'><span style='font-size:16px'>ℹ️</span>"
            f"<span>필수 용도군 미충족: {', '.join(missing)} (예산을 올리면 채워집니다).</span></div>",
            unsafe_allow_html=True)


# ── 화면 3: 비싸면 대체 ───────────────────────────────────────────────────
def tab_substitute(states: dict):
    sec("🔁 비싸면 대체", hint="같은 용도군 가성비 대체재")
    if not states:
        st.warning("표시할 품목이 없습니다.")
        return
    pricey = expensive(states)
    # 비싸진(가격 상승) 순으로 정렬해 '바꿀 만한' 품목을 위에(리스크 #3: states.keys() 파생)
    options = sorted(states.keys(), key=lambda k: states[k].price_chg, reverse=True)
    if not pricey:
        st.caption("오늘은 '대기(비싼)' 품목이 없습니다 — 가격이 가장 오른 품목을 기본 선택했습니다.")

    target = st.selectbox("바꾸고 싶은 (비싼) 품목", options, index=0)
    s = states[target]
    color, bg = SIG_STYLE[s.signal]
    st.markdown(
        "<div class='exline'>"
        f"<span class='exdot' style='background:{SIG_COLOR[s.signal]}'></span>"
        f"<span class='exname'>{target}</span>"
        f"<span class='exprice'>{s.retail:,}<span class='u'>원/kg</span></span>"
        f"<span class='sigchip' style='color:{color};background:{bg}'>{s.signal}</span>"
        f"<span class='exchg' style='color:{color}'>{s.price_chg:+.0%}</span></div>",
        unsafe_allow_html=True)

    subs = substitutes(states, target)
    if not subs:
        st.info(f"같은 용도군({s.group})에 더 나은 대체재가 없습니다.")
        return
    st.markdown(
        f"<div class='exsub'>같은 용도군 <b>{s.group}</b> 에서 가성비 상위 "
        "<span class='mu'>(과잉 우선)</span></div>", unsafe_allow_html=True)
    cards = ""
    for a in subs:
        save = s.retail - a.retail
        savepill = (f"<span class='savepill'>kg당 {save:,}원 절약</span>" if save > 0 else "")
        ac, ab = SIG_STYLE[a.signal]
        cards += (
            "<div class='altcard'><div class='ahead'>"
            f"<span class='aname'><span class='adot' style='background:{SIG_COLOR[a.signal]}'></span>{a.item}</span>"
            f"{savepill}</div>"
            f"<div class='aprice'>{a.retail:,}<span class='u'>원/kg</span></div>"
            f"<div class='achips'><span class='sigchip' style='color:{ac};background:{ab}'>{a.signal}</span>"
            f"<span class='nchip'>사유 {a.reason()}</span></div></div>")
    st.markdown(cards, unsafe_allow_html=True)


# ── 화면 4: 살까·기다릴까 (그래프) ────────────────────────────────────────
def tab_trend(states: dict, df: pd.DataFrame):
    sec("📈 살까 · 기다릴까", hint="가격 추세 · 방향 신호")
    options = list(states.keys())
    if not options:
        st.warning("표시할 품목이 없습니다.")
        return
    item = st.selectbox("품목", options, key="trend_item")
    s = states[item]

    sub = df[df["item"] == item].sort_values("date")
    grad = alt.Gradient(
        gradient="linear", x1=1, x2=1, y1=1, y2=0,
        stops=[alt.GradientStop(color="rgba(31,143,78,0.0)", offset=0),
               alt.GradientStop(color="rgba(31,143,78,0.16)", offset=1)])
    area = (alt.Chart(sub)
            .mark_area(line={"color": "#1F8F4E", "strokeWidth": 2.5}, color=grad,
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
             .configure(background="#FFFFFF")
             .configure_axis(grid=True, gridColor="#EEF1ED", domainColor="#E6E8E3",
                             labelColor="#9AA39C", titleColor="#9AA39C",
                             labelFontSize=12, titleFontSize=12))
    # 신 API(streamlit>=1.43): width="stretch" 사용. use_container_width 는 폐기(리스크 #2)
    with st.container(border=True):
        st.altair_chart(chart, width="stretch")

    arrow = {SIGNAL_BUY: "지금이 살 때 ⬇", SIGNAL_WAIT: "조금 기다리기 ⬆",
             SIGNAL_WATCH: "변동성 큼 ↕", SIGNAL_NORMAL: "평소 수준 ➡"}[s.signal]
    pc = SIG_STYLE[s.signal][0]
    st.markdown(
        "<div class='tcards'>"
        f"<div class='tcard'><div class='nm'><span class='d' style='background:{SIG_COLOR[s.signal]}'></span>{item}</div>"
        f"<div class='pr' style='color:{pc}'>{s.retail:,}<span class='u'>원/kg</span></div></div>"
        f"<div class='tdark'><div class='dt'>{arrow}</div>"
        f"<div class='ds'>가격 <b>{s.price_chg:+.0%}</b> vs 최근 기준선 · "
        f"반입량 <b>{s.vol_chg:+.0%}</b> · 변동계수 {s.cv:.0%}</div>"
        "<div class='note'>※ 방향 신호는 최근 추세 기반 보조 지표입니다 (미래가격 보장 아님).</div>"
        "</div></div>", unsafe_allow_html=True)


# ── 메인 ──────────────────────────────────────────────────────────────────
def main():
    inject_css()
    st.markdown(
        "<div class='hero'>"
        "<div class='ht'><span>🛒</span><span>장바구니 예보 <span class='ai'>AI</span></span></div>"
        "<div class='hs'>과잉으로 값이 내린 농산물을 <b>반입량(공급)</b>으로 매일 포착해 "
        "장바구니에 연결합니다. <b class='g'>소비자는 가성비, 농민은 판로.</b></div>"
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
        ["오늘의 장보기 예보", "예산별 장바구니", "비싸면 대체", "살까·기다릴까"])
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

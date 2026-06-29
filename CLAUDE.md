# 장바구니 예보 AI — 개발 가이드 (Claude Code 기준)

> 단일 기준 명세서는 [`장바구니예보AI_아키텍처_명세서_v2.md`](장바구니예보AI_아키텍처_명세서_v2.md).
> 이 파일은 그 요약 + 코딩 시 지켜야 할 불변 계약이다.

## 한 줄
과잉으로 값이 폭락한 농산물을 **반입량(공급)으로 일 단위 포착**해 소비자 장바구니에 연결하는 수급-소비 연동 AI. *소비자는 가성비, 농민은 판로.*

## 레이어 (경계 유지 · 전면 재작성 금지)
```
bf/data.py    load_daily()  → §2 표준 DataFrame[date,item,retail,wholesale,volume]
bf/core.py    analyze()     → dict[str, ItemState]  (과잉·신호·가성비·예산)
app.py        Streamlit 4화면 (표시 전용 · 키 주입 담당)
bf/catalog.py 품목 메타(용도군·표준구매량·제철 + 실연동 코드·단위환산)
tests/        회귀 보증(시연 스토리)
```

## 불변 계약 (바꾸면 core·UI·테스트 동시 영향)
1. **데이터 스키마(§2)** — `date(datetime64) · item(str, 카탈로그명) · retail(원/kg) · wholesale(원/kg) · volume(float)`. 모든 가격은 **원/kg 정규화** 필수.
2. **공개 시그니처(§3.5)** — `analyze / gluts / sell_first / substitutes / expensive / budget_basket`, `load_daily(source, keys, end) / load_from_api(keys, end)`. 내부 구현만 개선.
3. **계층 분리** — `bf/data.py` 는 `st.secrets` 를 import 하지 않는다. 키는 app.py 가 dict 로 주입.
4. **용어** — "평년/평월" 금지. **"최근 기준선(직전 8~60일)"** 으로 표기(리스크 #1). `seasonal` 모드는 다년 이력 연동 후에만.
5. **API** — `width="stretch"` 사용(`use_container_width` 폐기, 리스크 #2). selectbox 옵션은 `list(states.keys())`(리스크 #3).

## 보안
서비스키는 코드·git 금지. `.streamlit/secrets.toml` 은 `.gitignore` 처리됨. 배포는 Streamlit Cloud Secrets 사용(§7).

## 개발 루프
```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 로직 변경 시 필수 (회귀 보증)
streamlit run app.py         # http://localhost:8501
```

## 회귀 보증 (반드시 통과 유지)
양파=과잉 · 사과=대기 · sell_first에 양파 · 대체재 동일 용도군 · 예산 5만원(상한·필수군·과잉우선·대기제외) · 예산 단조성 · 단위정규화/코드매핑 픽스처.

## 남은 작업 (우선순위, 명세서 §8)
- [x] T1 빌드 안정(selectbox 가드, width="stretch" 핀, numpy 미사용)
- [x] T2 실연동(data.go.kr B552845, serviceKey 1개): **가격** `perRegion/price`(환산평균가 = 원/kg, catalog `price_ctgry`/`price_item` 정적등록) · **반입량** `katRealTime2/trades2`(일자별 qty×unit_qty) · **코드** `katCode/goods`로 품목명↔중분류코드 런타임 자동해석(`_resolve_wholesale_index`). 어떤 실패든 가격만으로 폴백. 파싱 픽스처 + 오프라인 통합시뮬 통과. 점검: `verify_price_api(keys)`. ⚠️ data.go.kr 키는 **Decoding** 값 사용.
- [x] T3 시크릿·계층 분리
- [x] T4 용어 정합성("최근 기준선") + seasonal 스텁
- [x] T5 폴백/배너 + 캐싱 ttl
- [ ] T6 Streamlit Cloud 배포 → 공개 URL → 기획서 기입
- [ ] T7 (선택) 품목 확대·seasonal·지역 선택·표시단위 옵션

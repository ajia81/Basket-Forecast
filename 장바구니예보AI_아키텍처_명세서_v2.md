# 장바구니 예보 AI — 아키텍처 · 개발 명세서 (v2)

> **목적**: VS Code + Claude Code로 코딩할 때 넘기는 **단일 기준 명세서**.
> 기존 구조(`basket_forecast/`)를 **갈아엎지 말고 확장**하는 것을 원칙으로 한다.
> 저장소 루트에 `CLAUDE.md`로 두면 Claude Code가 자동 인식한다.

**제품 한 줄** — 과잉으로 값이 폭락한 농산물을 **반입량(공급)으로 일 단위 포착**해 소비자 장바구니에 연결하는 수급-소비 연동 AI. *소비자는 가성비, 농민은 판로.*

**대회/부문** — 제11회 농업·농촌 공공데이터+AI 활용 창업경진대회 · 제품 및 서비스 개발 부문 (발표심사 前 **공개 배포 URL = 시제품 완료** 필수, 로컬 데모 불가).

**현재 상태** — Streamlit MVP 동작(샘플 데이터). 실연동(`load_from_api`)·배포·하드닝이 남은 작업.

---

## 변경 이력 (v2 — 코드 검토 반영)

1. **[정정] 리스크 #2 / T1** — `width="stretch"`가 **올바른 신 API**, `use_container_width`가 폐기(제거됨). T1의 "use_container_width로 되돌리기"는 **회귀**이므로 삭제. → `width="stretch"` 유지 + `streamlit>=1.43` 핀.
2. **[확정] 다중 키 전달 계약** — `load_from_api(service_key:str)` 단일 문자열로는 KAMIS(cert_key+cert_id)+data.go.kr 키를 못 넘김 → `load_from_api(keys:dict)`로 확정(§3.5·§5). 데이터 계층은 `st.secrets` 비의존 유지.
3. **[전파] "평년/평월"→"최근 기준선"** — 코드·UI뿐 아니라 **기획서 docx 동기화** 작업 추가(T4).
4. **[추가] 정규화 단위테스트** — 원/kg 환산·코드매핑은 픽스처 단위테스트로 보증(T2 수용기준).
5. **[추가] 임계값 실데이터 튜닝** — 오탐/미탐 점검 후 조정(T2 수용기준).
6. **[선택] 표시 단위** — 내부 원/kg 유지, 표시만 단·개 옵션(T7).

---

## 0. 코딩 원칙 (Claude Code 준수)

1. 기존 모듈 경계(UI / 데이터 / 로직 / 메타)를 유지한다. 전면 재작성 금지.
2. **데이터 스키마는 계약이다.** §2의 스키마를 바꾸지 않는다(바꾸면 core·UI 동시 영향).
3. 변경 시 영향 범위를 주석/PR 설명에 적는다.
4. 보안: 서비스키는 코드·git에 절대 넣지 않는다(`st.secrets`/환경변수). `secrets.toml`은 커밋 금지. **데이터 계층(`bf/data.py`)은 `st.secrets`를 import하지 않는다** — 키는 호출자(app.py)가 주입한다.
5. 모든 로직 변경 후 `python -m pytest -q` 통과를 확인한다(테스트가 시연 안정성의 근거).

---

## 1. 시스템 아키텍처

### 1.1 레이어 & 데이터 흐름

```
[ data.go.kr / KAMIS ]            ← 외부 공공데이터(실연동)
        │  (또는 샘플 합성)
        ▼
 bf/data.py   load_daily()        ← ★단일 진입점 / 스키마 고정
        │  DataFrame[date,item,retail,wholesale,volume]
        ▼
 bf/core.py   analyze()           ← 과잉 포착 + 신호 + 가성비 (현재가 기준)
        │  dict[str, ItemState]
        ├─────────────┬───────────────┬──────────────┐
        ▼             ▼               ▼              ▼
   gluts/sell_first  budget_basket  substitutes   expensive
        │             │               │              │
        ▼             ▼               ▼              ▼
 app.py  화면1        화면2          화면3          화면4   ← Streamlit UI (표시 전용)

 bf/catalog.py : 품목 메타(용도군·표준구매량·제철) — core/UI 공용 참조
 tests/        : 핵심 로직 회귀 테스트(시연 스토리 보증)
```

### 1.2 모듈 명세표

| 파일 | 책임 | 의존 | 변경 빈도 |
|---|---|---|---|
| `app.py` | Streamlit 4화면 UI, 표시 전용. 로직 호출만. **키 주입 담당** | `bf.*`,`st.secrets` | 화면 추가 시 |
| `bf/data.py` | 데이터 로딩(샘플/실API), **스키마 정규화**. st.secrets 비의존 | `bf.catalog` | 실연동 시 ★ |
| `bf/core.py` | 과잉 포착·신호·가성비·대체·예산 최적화 | `bf.catalog` | 알고리즘 튜닝 시 |
| `bf/catalog.py` | 품목 용도군·표준구매량·제철·열량 (+실연동 시 코드매핑) | 없음 | 품목 확장 시 |
| `tests/test_core.py` | 핵심 로직 검증 | `bf.*` | 로직 변경 시 동반 |
| `.streamlit/config.toml` | 테마(네이비/카퍼) | — | 고정 |
| `requirements.txt` | 의존성 핀(`streamlit>=1.43`) | — | §6 리스크 반영 |

---

## 2. 데이터 계약 (불변)

`load_daily()`가 반환하고 `core.analyze()`가 소비하는 **표준 DataFrame**. 이 스키마를 깨면 안 된다.

| 컬럼 | 타입 | 의미 | 단위 |
|---|---|---|---|
| `date` | datetime64 | 일자 | — |
| `item` | str | 품목명(한글, `catalog.ITEM_NAMES`와 일치) | — |
| `retail` | int/float | 소매가 | **원/kg** |
| `wholesale` | int/float | 도매가 | **원/kg** |
| `volume` | float | 반입량(공급) | 상대단위(절대량 불필요, 변화율만 사용) |

- 기간: 최소 **최근 60~90일**(기준선 계산에 8~60일 필요).
- `item`은 카탈로그 품목명으로 **정규화**되어야 한다(코드→한글 매핑은 §5).
- **모든 가격은 원/kg으로 정규화**되어야 한다(실API 단위 상이 — §5.2-2, 리스크 #6).
- 결측 품목은 행이 없을 수 있다 → 소비 측(core/app)에서 가드(§6-3).

---

## 3. 핵심 알고리즘 명세 (`bf/core.py`)

### 3.1 과잉(글럿) 포착 — 투명 규칙

```python
VOLUME_SURGE = 0.30   # 반입량 변화율 ≥ +30%
PRICE_DROP   = -0.15  # 가격 변화율 ≤ -15%
RECENT_DAYS  = 7      # '현재' = 최근 7일 평균
BASE_MIN, BASE_MAX = 8, 60   # 기준선 = 직전 8~60일 중앙값

is_glut = (vol_chg >= VOLUME_SURGE) and (price_chg <= PRICE_DROP)
glut_score = max(0, vol_chg) + max(0, -price_chg)   # 강도(정렬용)
```

- `price_chg = recent_mean / base_median - 1`, `vol_chg` 동일.
- **기준선 정의(중요)**: 기준선은 *직전 8~60일 추세*다(다년 평년 아님). 코드 주석·UI·기획서에서 **"평년/평월"이라는 단어를 쓰지 말고 "최근 기준선(직전 N일)"** 으로 표기한다(리스크 #1, T4). 실데이터(KAMIS는 연도별 제공) 연동 후 옵션 추가:
  ```python
  def _baseline(series, dates, end, mode="trailing"):
      # mode="trailing" : 직전 8~60일 중앙값 (MVP 기본)
      # mode="seasonal" : 전년 동기(±N일) 중앙값 — 실데이터에 다년 이력 있을 때
  ```
  MVP는 `trailing` 유지, 실연동 후 `seasonal` 비교를 선택 가능하게. (`seasonal` 도입 시에만 "전년 동기 대비" 표현 사용 가능.)

### 3.2 구매 신호 (현재가 기준)

| 신호 | 조건 |
|---|---|
| 구매추천 | `is_glut` 또는 `price_chg <= -0.10` |
| 대기 | `price_chg >= 0.15` |
| 주의 | 최근 7일 변동계수 `std/mean >= 0.08` |
| 보통 | 그 외 |

### 3.3 가성비·추천 점수

```python
value = (-price_chg) + (0.15 if in_season else 0.0) + (0.5 * glut_score)
```
높을수록 "지금 사면 좋은". `sell_first`(오늘 팔아줄 작물)·대체재 정렬의 기준.

### 3.4 예산별 장바구니 — 제약 최적화

목적함수: 예산 상한 + **필수 용도군 커버리지**(`ESSENTIAL_GROUPS`) 하에서 가성비(과잉 우선) 효용 최대화.
- **'대기(비싼)' 품목 제외** → 추천 신호와 일관(설명 가능성).
- 3단계: ①필수 용도군 1개씩 → ②나머지 가성비순(과잉 우선) → ③남는 예산을 과잉·제철 상위 수량 증가(`MAXQ=3`)로 소진.
- 효율: `eff(s) = (value + 0.5) / portion_cost`.
- 반환 키: `items[(ItemState,qty)] · total · budget · leftover · groups_covered · glut_in_basket`.

### 3.5 공개 함수 계약 (시그니처 유지)

```python
analyze(df, end=None) -> dict[str, ItemState]
gluts(states) -> list[ItemState]                 # 과잉, 강도순
sell_first(states, n=6) -> list[ItemState]       # 과잉·제철·저렴 우선, value순
substitutes(states, item, n=3) -> list[ItemState]# 같은 용도군 가성비 상위(과잉 우선)
expensive(states) -> list[ItemState]             # '대기' 품목
budget_basket(states, budget:int) -> dict        # §3.4
```
> Claude Code: 위 `core` 시그니처를 바꾸지 말 것(UI·테스트가 의존). 내부 구현만 개선.

**[v2] 데이터 로더 키 전달 계약 (실연동 전 확정)** — 실연동은 키가 여러 개다(KAMIS `cert_key`+`cert_id`, data.go.kr `key`). 단일 문자열로 부족하므로 아래로 확정한다. **데이터 계층은 `st.secrets` 비의존**(키는 dict로 주입받음).

```python
load_daily(source="sample", keys: dict | None = None, end=None) -> DataFrame
load_from_api(keys: dict, end=None) -> DataFrame
#   keys = {"kamis_cert_key": ..., "kamis_cert_id": ..., "data_go_kr": ...}
```
> app.py가 `st.secrets`를 읽어 `keys` dict로 전달한다(§5.2-5). 기존 `service_key=` 인자는 제거하고 `keys=`로 대체.

---

## 4. UI 화면 명세 (`app.py`)

| 탭 | 표시 내용 | 데이터 소스 | 비고 |
|---|---|---|---|
| 🛒 오늘의 장보기 예보 | 과잉 배너 + '팔아줄 작물'(가성비순) + 구매추천/대기/주의 | `gluts`,`sell_first` | **가성비·저렴을 1순위로**, '농가 판로 기여'는 보조 배지 |
| 💰 예산별 장바구니 | 예산 슬라이더 → 조합표 + 합계/잔액/용도군 | `budget_basket` | 과잉 포함 시 성공 메시지 |
| 🔁 비싸면 대체 | 비싼 품목 → 같은 용도군 가성비 대체재 | `expensive`,`substitutes` | 대체 사유 표기(과잉/제철/가격) |
| 📈 살까·기다릴까 | 가격 추세 그래프 + 방향 신호 | `df`,`states` | **예측은 보조**임을 캡션 명시 |
| (사이드바) | 과잉 포착 기준·파라미터·포착 수 | `core` 상수 | 투명성 노출(평가 포인트) |

UI 규칙: 표시 전용(비즈니스 로직 금지). 색상은 신호별 고정(`SIG_COLOR`). 첫 화면은 '결정'이 먼저, 그래프는 화면4.
**selectbox 옵션은 `list(states.keys())` 사용**(`ITEM_NAMES` 직접 사용 금지 — 실데이터 결측 시 KeyError, 리스크 #3). 빈 상태 가드 포함.

---

## 5. ★ data.go.kr 실연동 명세 (`bf/data.py` · 최우선 작업)

**원칙**: 앱은 `load_daily()`만 호출한다. `load_from_api(keys)` 한 함수만 구현하면 실데이터로 전환된다. 반환은 §2 스키마로 **정규화**해야 한다.

### 5.1 데이터 원천

| 데이터 | 출처 | 용도 | 키 필드 |
|---|---|---|---|
| 일별 소매·도매가 | **KAMIS OpenAPI**(aT) `kamis.or.kr/service/price/xml.do` | `retail`,`wholesale` | `p_cert_key`,`p_cert_id` |
| 도매시장 경락가격·**반입량** | 농식품 공공데이터포털 `data.mafra.go.kr` / `data.go.kr`(B552895 계열) | `volume`(★과잉 신호) | 서비스키 |
| 품목 코드표 | 농식품 OpenAPI 코드조회(가락시장품목코드·품목표준코드 등) | 코드↔품목 매핑 | — |
| (보조) 기상·제철 | 기상청 ASOS / 농사로 | 설명 변수 | — |

> ⚠️ 위 엔드포인트/파라미터명은 시기에 따라 바뀐다 — **현행 KAMIS/공공데이터포털 문서로 확인**하고 코드값은 공식 코드조회 API에서 취득(임의 추정 금지).

### 5.2 구현 순서 (Claude Code 작업)

1. **품목 코드 매핑 테이블 작성** — `catalog.py`에 10개 품목 → KAMIS `item_category_code`/`item_code`(+ 도매 `품목표준코드`) 매핑 dict 추가. 코드값은 KAMIS 품목분류표 / data.mafra 코드조회 API에서 취득(임의 추정 금지).
2. **KAMIS 가격 수집** — 기간 조회로 최근 60~90일 일별 소매(`p_product_cls_code=01`)·도매(`02`)가 취득. 응답을 `date,item,retail,wholesale`로 파싱.
   - ⚠️ **단위 정규화**: KAMIS 가격 단위가 품목마다 다름(개/kg/단 등). **반드시 원/kg로 환산**(단위코드 활용). 미환산 시 가성비·예산 전부 왜곡(리스크 #6).
3. **반입량 수집** — 도매시장 API에서 동일 기간 `volume` 취득, `품목표준코드`로 매핑.
4. **병합·정규화** — (date,item) 기준 outer 병합 → §2 스키마 반환. 결측은 보간/제외 정책 명시.
5. **시크릿 주입(계층 분리)** — app.py에서 키를 모아 dict로 전달. **data.py는 `st.secrets`를 import하지 않는다.**
   ```python
   # app.py
   keys = {
       "kamis_cert_key": st.secrets["KAMIS_CERT_KEY"],
       "kamis_cert_id":  st.secrets["KAMIS_CERT_ID"],
       "data_go_kr":     st.secrets["DATA_GO_KR_KEY"],
   }
   df = load_daily(source="api", keys=keys)
   ```
6. **캐싱·에러 처리** — `@st.cache_data(ttl=...)`로 API 호출 캐시(일 단위 갱신 ttl). API 실패 시 (a) 명시적 예외 또는 (b) 샘플 폴백 + 화면 상단 경고 배너(시연 보호).

```toml
# .streamlit/secrets.toml  (커밋 금지 — .gitignore 확인)
KAMIS_CERT_KEY = "..."
KAMIS_CERT_ID  = "..."
DATA_GO_KR_KEY = "..."
```

> 참고: GitHub `kamispy` 라이브러리로 KAMIS 응답 파싱을 단순화할 수 있음(선택).

### 5.3 실연동 수용 기준

- `load_daily(source="api", keys=...)`가 §2 스키마 DataFrame을 반환(최근 ≥60일, 10품목).
- 모든 가격이 **원/kg**으로 정규화됨.
- **단위 정규화·코드매핑 단위테스트(픽스처 기반) 통과** — 예: 원/개 레코드 → 원/kg 변환 검증, 코드↔품목 매핑 검증.
- 실데이터로 과잉이 합리적으로 포착됨 → **오탐/미탐 육안 점검 후 임계값(§3.1) 조정**.
- 서비스키가 코드·git에 없음(시크릿 주입, data.py는 secrets 비의존).
- API 다운 시 앱이 죽지 않음(폴백 또는 명확한 안내).

---

## 6. 리스크 레지스터 & 수정 지시

| # | 리스크 | 영향 | 수정 |
|---|---|---|---|
| 1 | "평년/평월" 표현 vs 실제 추세 기준선 | 심사 신뢰성·과장 | 문구를 "최근 기준선"으로 — **코드·UI·기획서 docx 3축 동기화**(T4); 실데이터 후 `seasonal` 모드 옵션화(§3.1) |
| 2 | **(정정)** `width="stretch"`가 올바른 신 API. `use_container_width`는 폐기(2025-12-31 후 제거) | 구버전 런타임에서 신 API 미지원 시 에러 | `width="stretch"` **유지** + `requirements.txt`에 `streamlit>=1.43` 핀. **use_container_width로 되돌리지 말 것(폐기·회귀)** |
| 3 | tab3·tab4가 `ITEM_NAMES`로 selectbox | 실데이터 결측 품목 시 **KeyError** | `options=list(states.keys())` 사용, 빈 상태 가드 |
| 4 | `core.py` 미사용 `import numpy` | 린트/혼동 | 제거 |
| 5 | 샘플 스토리 하드코딩(`_BASE`) | 실데이터 시 무의미 | `source="api"`에서 실제 시장값 사용, 과잉 0개일 때 화면1 빈 상태 처리(이미 가드 있음, 유지) |
| 6 | 가격 단위 미정규화(실API) | 가성비·예산 전부 왜곡 | §5.2-2 단위→원/kg 환산 필수 + 단위테스트(§5.3) |

> 보안·데이터 손실: 읽기 전용 서비스라 데이터 손실 위험 없음. 유일한 보안 포인트는 **서비스키 노출**(시크릿으로 차단, data.py는 secrets 비의존).

---

## 7. 빌드 · 실행 · 배포

```bash
# 로컬 실행
pip install -r requirements.txt
streamlit run app.py            # http://localhost:8501

# 테스트(로직 변경 시 필수)
python -m pytest -q             # 또는 python tests/test_core.py
```

> `requirements.txt`에 `streamlit>=1.43` 핀(리스크 #2 — 신 API 지원 보장).

**배포 = 시제품 완료(서비스 개시)**
1. 저장소를 GitHub push (`secrets.toml`은 `.gitignore` 확인).
2. share.streamlit.io → New app → repo·branch·`app.py` → Deploy.
3. (실연동) Settings → Secrets에 `KAMIS_CERT_KEY/ID`, `DATA_GO_KR_KEY` 입력.
4. 공개 URL(예: `https://basket-forecast.streamlit.app`)을 **기획서 '등록 정보·웹서비스 URL'에 기입**.

---

## 8. Claude Code 작업 지시 (우선순위順)

각 작업은 **완료 기준(테스트/수용)**을 만족해야 함. 작업 후 `pytest -q` 통과 유지.

- [ ] **T1 (빌드 안정)** 리스크 #3·#4 수정 — selectbox `options=list(states.keys())`(tab3·tab4, 빈 상태 가드), 미사용 `import numpy` 제거. 리스크 #2: `width="stretch"` **유지** + `requirements.txt`에 `streamlit>=1.43` 핀(**되돌리지 말 것**). ▶ 수용: 샘플로 4화면 정상, 폐기 경고 없음, pytest 통과.
- [ ] **T2 (실연동 핵심)** §5 `load_from_api(keys)` 구현 — 코드 매핑→KAMIS 가격→반입량→**원/kg 정규화**→§2 스키마. 단위 정규화·코드매핑 **단위테스트(픽스처)** 동반. ▶ 수용: §5.3 충족, 실데이터로 과잉 포착 동작, **오탐/미탐 점검 후 임계값 조정**, 정규화 테스트 통과.
- [ ] **T3 (시크릿·계층 분리)** KAMIS cert_key/id + data.go.kr 키를 **app.py에서 dict로 모아 전달**, 배포 Secrets 설정. data.py는 `st.secrets` 비의존. ▶ 수용: 코드/git에 키 없음, 계층 분리 유지.
- [ ] **T4 (정합성)** 기준선 표기 "평년/평월"→"최근 기준선" 정정 — **코드 주석·UI·기획서 docx(§2 코어행·§4·체크리스트) 3축 동기화**, `seasonal` 모드 스텁 추가(§3.1). ▶ 수용: 코드·UI·기획서 용어 일치.
- [ ] **T5 (견고성)** API 실패 폴백/배너 + 캐싱 ttl. ▶ 수용: 네트워크 차단 시 앱 미중단.
- [ ] **T6 (배포)** Streamlit Cloud 배포 → 공개 URL 확보 → 기획서 기입.
- [ ] **T7 (확장, 선택)** 품목 10→확대, `seasonal` 기준선 실데이터 적용, 지역(도매시장) 선택, **표시 단위 단·개 옵션(내부 계산은 원/kg 유지)**.

**테스트 회귀 보증(현재 통과 유지)**: 양파=과잉, 사과=대기, sell_first에 양파 포함, 대체재 동일 용도군, 예산 5만원 내 + 필수 용도군 충족 + 과잉 우선 + 대기 제외, 예산 단조성.

---

*SUHO AI Works · 소비자는 가성비, 농민은 판로*

# 🛒 장바구니 예보 AI

> 과잉으로 값이 폭락한 농산물을 **반입량(공급)으로 매일 포착**해 소비자 장바구니에 연결하는
> 수급-소비 연동 AI. **소비자는 가성비, 농민은 판로.**
>
> 제11회 농업·농촌 공공데이터+AI 활용 창업경진대회 · 제품 및 서비스 개발 부문

## 핵심 아이디어
도매시장 **반입량(공급)** 이 급증하고 가격이 동시에 내리면 → "과잉(글럿)" 으로 포착하고,
그 작물을 **가성비 1순위**로 장바구니에 추천한다. 소비자는 싸게 사고, 농가는 판로가 생긴다.

## 화면
| 탭 | 내용 |
|---|---|
| 🛒 오늘의 장보기 예보 | 과잉 배너 + 오늘 사면 좋은 작물(가성비순) + 구매추천/주의/대기 |
| 💰 예산별 장바구니 | 예산 슬라이더 → 과잉 우선·필수 용도군 보장 조합 |
| 🔁 비싸면 대체 | 비싼 품목 → 같은 용도군 가성비 대체재(사유 표기) |
| 📈 살까·기다릴까 | 가격 추세 그래프 + 방향 신호(보조 지표) |

## 빠른 시작
```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 회귀 테스트(27개) 통과 확인
streamlit run app.py         # http://localhost:8501
```
시크릿 없이 실행하면 **샘플 데모 데이터**로 동작합니다.

## 실데이터 연동 (KAMIS · 도매시장)
1. `.streamlit/secrets.toml.example` → `secrets.toml` 복사 후 키 입력
   (`KAMIS_CERT_KEY`, `KAMIS_CERT_ID`, `DATA_GO_KR_KEY`).
2. `bf/catalog.py` 의 각 품목에 KAMIS `kamis_category`/`kamis_item`(공식 *품목 코드표*) 과
   도매 `wholesale_code`(*품목표준코드*) 를 채웁니다(임의 추정 금지). 도매 반입량은
   `bf/data.py` 상단 `VOLUME_OPERATION`·`VOL_FIELD_*` 를 현행 API 명세서로 확정합니다.
3. `verify_catalog_codes(keys)` 로 채운 KAMIS 코드가 실데이터를 반환하는지 점검(오타·오코드 표면화).
4. 사이드바 토글을 끄면 `load_from_api()` 로 실데이터를 불러옵니다. 가격은 **원/kg로 자동 정규화**.

> 키는 코드/깃에 절대 넣지 않습니다. `secrets.toml` 은 `.gitignore` 처리됨.
> 데이터 계층(`bf/data.py`)은 `st.secrets` 를 import 하지 않고, app.py 가 키를 dict 로 주입합니다.

## 구조
```
app.py            Streamlit 4화면 UI (표시 전용 · 키 주입)
bf/data.py        load_daily / load_from_api — §2 스키마 정규화(원/kg)
bf/core.py        과잉 포착·신호·가성비·대체·예산 최적화
bf/catalog.py     품목 메타 + 실연동 코드·단위환산
tests/            회귀(test_core) + 정규화·코드매핑(test_data)
```

## 배포 (Streamlit Community Cloud)
1. **GitHub 푸시** — 이 폴더를 GitHub 리포지토리로 올립니다(`secrets.toml` 은 `.gitignore` 로 제외됨).
2. [share.streamlit.io](https://share.streamlit.io) 로그인(GitHub 계정) → **New app** → 리포·브랜치 선택,
   Main file path = `app.py` → **Deploy**.
3. (선택) **Settings → Secrets** 에 3개 키 입력 — 미입력 시 자동으로 **샘플 데모**로 공개됩니다.
   ```toml
   KAMIS_CERT_KEY = "..."
   KAMIS_CERT_ID  = "..."
   DATA_GO_KR_KEY = "..."
   ```
4. 발급된 **공개 URL**(`https://<app>.streamlit.app`)을 기획서 '웹서비스 URL'에 기입.

> 키 없이도 즉시 동작(샘플 데모). Python 3.12 / `requirements.txt` 자동 설치.

---
*SUHO AI Works*

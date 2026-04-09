# 선물·옵션 수급 기반 익일 종목 선별 시스템

한국 주식시장의 외국인·기관 수급, 공매도, 기술적 지표를 종합해 **내일 살 종목**을 자동 선별하는 로컬 실행 시스템입니다.

> 투자 참고용 보조 도구입니다. 실제 투자 손익의 책임은 사용자에게 있습니다.

---

## 빠른 시작

**Python 3.10 이상만 설치되어 있으면 됩니다.**

```
1. git clone https://github.com/junp9950/stock_option_pj.git
2. 폴더 안의 start.bat 더블클릭
3. 브라우저에서 http://127.0.0.1:8000 자동 오픈
```

최초 실행 시 가상환경 생성 + 패키지 설치로 1~2분 소요. 이후 실행은 즉시 시작됩니다.

---

## 매일 사용법

### 장 마감 후 (15:30 이후)
1. **파이프라인 자동 실행** — 매일 15:35에 자동 수집 (서버 켜져 있어야 함)
2. 수동 실행하려면 대시보드 → 설정 탭 → "파이프라인 실행" 버튼

### 대시보드에서 확인
1. **내일 매수 후보** (최상단 파란 테두리 카드) — 바로 여기가 핵심
   - T+1 적합도 점수 순 정렬
   - 수급 연속일 보너스, 당일 급등 페널티 적용
   - 리스크 표시: 저(당일 +3% 미만) / 중(+3~8%) / 고(+8% 초과)
2. **시장 시그널** — 강세매수 / 상방 / 중립 / 하방 / 강세매도
3. **전종목 스크리너 탭** — 필터·정렬로 직접 발굴

### 종목 선택 기준 (T+1 전략)
- **리스크 저** + **T+1 점수 높은 것** 우선
- **외인+기관 동시매수** 배지 있으면 가점
- **동반매수 연속일** 길수록 지속성 있음
- 오늘 이미 +5% 넘게 오른 종목은 리스크 중/고 → 고점 주의

---

## 주요 기능

### 대시보드
- **내일 매수 후보** — T+1 진입 적합도 점수 TOP 7, 카드 형태
- **시장 시그널** — 외인/기관 전종목 순매수 합산 + 동시매수 비율 기반 (강세매수~강세매도 5단계)
- 시장 시그널 히스토리 (최근 7일, 색상 구분)
- 전일 대비 시그널 상승 TOP 5
- 추천 종목 테이블 (접기/펼치기)

### 전종목 스크리너
- KOSPI + KOSDAQ 시총 상위 100개씩 (총 200종목)
- 정렬: 총점 / 종목점수 / 등락률 / 시총 / 공매도% / RSI / 거래량배수 / MA / 합류
- 상세 필터: RSI 범위, 공매도%, 거래량배수, 등락률, 연속매수일, 총점, 기관+외인 동시매수
- 종목 클릭 → 상세 모달 (수급 히스토리 30일, 점수 이력, 가격 차트)

### 히스토리컬 백테스트
- **DB 시그널 기반** (기본): 2년치 실제 외인/기관 수급 데이터 포함 점수로 백테스트, 수초 내 완료
- FDR 기술지표 기반: FDR 가격 다운로드 후 기술지표만으로 백테스트
- 손절/익절 시뮬레이션 (OHLC 기반 T+1 갭 처리)
- 2년치 백테스트 결과 예시: 누적 +462%, 샤프 2.27, MDD 23%

### 종목 시그널 지표 (12개)

| 지표 | 비중 | 설명 |
|------|------|------|
| 외국인 강도 | 12% | 거래대금 대비 외국인 순매수 비율 |
| 기관 강도 | 12% | 거래대금 대비 기관 순매수 비율 |
| 동시매수 | 9% | 기관+외국인 동시 순매수 |
| MA 포지션 | 9% | 20일·60일선 위치 |
| MACD | 9% | 12/26일 MACD 시그널 |
| RSI(14) | 8% | 과매수/과매도 |
| 거래량 급등 | 7% | 20일 평균 대비 배수 |
| 모멘텀 5일 | 7% | 5일 수익률 |
| 연속매수 | 7% | 연속 순매수 일수 |
| 볼린저밴드 | 6% | 밴드 내 위치 |
| 공매도 비율 | 5% | 공매도 수준 (데이터 있을 때만) |
| 공매도 추세 | 4% | 공매도 방향성 |

### 시장 시그널 (6개 지표, DB 기반)
- 외인 전종목 순매수 합계 (억원)
- 기관 전종목 순매수 합계 (억원)
- 외인+기관 동시매수 종목 비율 (%)
- 외인 5일 누적 추세
- 전종목 평균 시그널 점수
- 전일 대비 점수 상승 종목 비율

---

## 데이터 소스

| 항목 | 소스 | 상태 |
|------|------|------|
| 주가·거래량·OHLC | FinanceDataReader | 정상 (병렬 수집, 2분) |
| 종목명·시총·거래대금 | FinanceDataReader | 정상 |
| 외국인·기관 순매수 | pykrx → 네이버 금융 fallback | KRX 차단 시 자동 전환 |
| 공매도 | pykrx | KRX 차단 시 생략 (점수 중립) |
| KOSPI200 지수 | FinanceDataReader | 정상 |

> 외국인·기관 수급은 **네이버 금융 자동 fallback**으로 수집되어 대부분 정상 동작합니다.  
> 선물/옵션 데이터(pykrx)는 KRX 차단 환경에서 수집 불가 → 시장 시그널은 현물 수급으로 대체 계산.

---

## 설치 방법 (수동)

```powershell
git clone https://github.com/junp9950/stock_option_pj.git
cd stock_option_pj

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

.\.venv\Scripts\uvicorn.exe backend.main:app --host 0.0.0.0 --port 8000
```

---

## 수동 파이프라인 실행

```powershell
# 오늘 데이터 수집
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/run-daily"

# 날짜 지정
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/run-daily?trading_date=2026-04-10"

# 과거 데이터 백필 (2년치)
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/backfill?start_date=2024-01-01&end_date=2026-04-09"

# 시그널 재계산 (백필 후 필요)
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/signal-backfill"
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/market-signal-backfill"
```

---

## 주요 API

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /api/health` | 서버 상태 |
| `GET /api/market-signal` | 오늘 시장 시그널 |
| `GET /api/screener` | 전종목 스크리너 |
| `GET /api/screener/tomorrow-picks` | 내일 매수 후보 TOP 7 |
| `GET /api/screener/trending` | 시그널 상승 TOP 5 |
| `GET /api/recommendations` | 추천 종목 |
| `GET /api/stock/{code}/flow-history` | 종목 수급 히스토리 30일 |
| `POST /api/jobs/run-daily` | 파이프라인 수동 실행 |
| `POST /api/backtest/historical?mode=db` | DB 시그널 기반 백테스트 |
| `POST /api/data/signal-backfill` | 종목 시그널 일괄 재계산 |
| `POST /api/data/market-signal-backfill` | 시장 시그널 일괄 재계산 |
| `GET /api/data/signal-backfill/status` | 재계산 진행상황 |

---

## 트러블슈팅

**파이프라인이 너무 느림**  
정상. 처음 실행 시 2년치 백필이 필요할 수 있음. 이후 일별 실행은 2~3분 소요.

**KRX 수집 실패**  
주말·사내망에서 발생. 외국인·기관 수급은 네이버 금융 자동 fallback으로 수집됨.

**시그널이 모두 중립**  
시그널 재계산 필요:
```powershell
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/signal-backfill"
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/market-signal-backfill"
```
또는 백테스트 탭 → `↺ 시그널 재계산` 버튼

**서버 포트 충돌**
```powershell
.\.venv\Scripts\uvicorn.exe backend.main:app --host 0.0.0.0 --port 8001
```

**DB 초기화**
```powershell
Remove-Item .\data\app.db
```
재실행 시 테이블 자동 재생성. 이후 파이프라인 + 시그널 재계산 필요.

**pykrx 설치 오류**
```powershell
pip install "setuptools<81"
pip install pykrx
```

# 선물·옵션 수급 기반 익일 종목 선별 시스템

한국 주식시장의 외국인·기관 수급, 공매도, 기술적 지표를 종합해 **내일 살 종목**을 자동 선별하는 시스템입니다.

> 투자 참고용 보조 도구입니다. 실제 투자 손익의 책임은 사용자에게 있습니다.

---

## 빠른 시작

### 1. 클론
```powershell
git clone https://github.com/junp9950/stock_option_pj.git
cd stock_option_pj
```

### 2. 가상환경 + 패키지 설치
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. .env 파일 확인
`.env` 파일이 이미 포함되어 있습니다 (Supabase DB 연결 정보).  
별도 수정 없이 바로 사용 가능합니다.

### 4. 서버 실행
```powershell
.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 `http://127.0.0.1:8000` 접속

---

## DB 구조

**Supabase PostgreSQL (클라우드)** 사용 — 집/회사 어디서든 같은 데이터 공유됩니다.

`.env` 파일에 `DATABASE_URL`이 설정되어 있으며, 서버 시작 시 자동으로 연결됩니다.

---

## 매일 사용법

### 자동 실행 (서버가 켜져 있으면 자동)
- **매일 19:00** 파이프라인 자동 실행
- 데이터가 아직 안 올라왔으면 **5분마다 재시도** (성공하면 자동 중단)

### 수동 실행
대시보드 우상단 **▶ 파이프라인 실행** 버튼

### 대시보드 확인
1. **내일 매수 후보** (최상단) — 핵심, T+1 적합도 점수 TOP 7
   - 리스크 저/중/고 표시
   - 기관+외인 동반매수 배지
   - 동반매수 연속일
2. **시장 시그널** — 상방 / 중립 / 하방
3. **추천 성과** — 과거 추천 종목 T+1 실제 수익률 (승률, 평균수익)
4. **전종목 스크리너 탭** — 필터·정렬로 직접 발굴

---

## 주요 기능

### 대시보드
- **내일 매수 후보** — T+1 적합도 TOP 7, 카드 형태
- **시장 시그널** — 외인/기관 수급 기반 5단계 (강세매수~강세매도)
- **추천 성과** — 과거 추천 T+1 수익률 실적 (기간 선택 가능)
- 시장 시그널 히스토리 (최근 7일)
- 전일 대비 시그널 상승 TOP 5

### 전종목 스크리너
- KOSPI + KOSDAQ 시총 상위 200종목
- 정렬: 총점 / 종목점수 / 등락률 / 시총 / 공매도% 등
- 상세 필터: RSI, 공매도%, 거래량, 연속매수일 등
- 종목 클릭 → 수급 히스토리 30일, 점수 이력, 가격 차트

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

> 공매도 데이터가 없으면 해당 비중이 다른 지표로 자동 재분배됩니다.

---

## 데이터 소스

| 항목 | 소스 | 비고 |
|------|------|------|
| 주가·거래량·OHLC | FinanceDataReader | 정상 |
| 외국인·기관 순매수 | pykrx → 네이버 금융 fallback | KRX 차단 시 자동 전환 |
| 공매도 | pykrx | KRX 차단 시 생략 (점수 중립) |
| KOSPI200 지수 | FinanceDataReader | 정상 |

---

## 신규 설치 후 초기 데이터 세팅

최초 설치 시 DB가 비어있으므로 아래 순서로 데이터를 채워야 합니다.

### 1단계: 원본 데이터 백필 (가격 + 수급)
```powershell
# 올해치 데이터 수집 (약 10~20분)
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/backfill?start_date=2026-01-01&end_date=2026-04-11"

# 진행 확인
Invoke-RestMethod "http://127.0.0.1:8000/api/data/backfill/status"
```

### 2단계: 시그널 재계산
```powershell
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/signal-backfill"
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/market-signal-backfill"

# 진행 확인
Invoke-RestMethod "http://127.0.0.1:8000/api/data/signal-backfill/status"
```

### 3단계: 추천 생성 (추천 성과 데이터)
```powershell
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/backfill?start_date=2026-01-02&end_date=2026-04-10"
```

> Supabase DB를 공유하므로 이미 데이터가 있으면 이 단계는 생략해도 됩니다.

---

## 주요 API

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /api/market-signal` | 오늘 시장 시그널 |
| `GET /api/screener/tomorrow-picks` | 내일 매수 후보 TOP 7 |
| `GET /api/screener` | 전종목 스크리너 |
| `GET /api/recommendations/performance` | 추천 성과 (T+1 수익률) |
| `POST /api/jobs/run-daily` | 파이프라인 수동 실행 |
| `POST /api/data/backfill` | 원본 데이터 백필 |
| `POST /api/data/signal-backfill` | 종목 시그널 재계산 |
| `POST /api/data/market-signal-backfill` | 시장 시그널 재계산 |

---

## 트러블슈팅

**백엔드 연결 실패 표시**
서버가 실행 중인데 뜨면 브라우저 강력 새로고침 (Ctrl+Shift+R)

**포트 이미 사용 중**
```powershell
# 점유 PID 확인 후 종료
netstat -ano | findstr :8000
taskkill /F /PID <PID번호>
```

**KRX 수집 실패**
회사망 or 주말에 자주 발생. 외국인·기관 수급은 네이버 금융 자동 fallback으로 수집됨.

**공매도 데이터 없음**
KRX 차단 환경에서는 공매도 데이터 수집 불가. 자동으로 해당 비중이 다른 지표로 재분배되어 점수 계산됨.

**데이터 품질 낮음**
주말·공휴일에는 당일 데이터가 없어 낮게 표시됨. 다음 거래일 19:00에 자동 업데이트됨.

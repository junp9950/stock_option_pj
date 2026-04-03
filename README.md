# Futures Options Analyzer

선물·옵션 수급 기반 익일 종목 선별 시스템의 로컬 실행용 MVP입니다.  
로컬 PC(Windows)에서 백엔드와 프론트엔드를 각각 개발 서버로 실행합니다.

이 시스템은 투자 참고용 보조 도구이며, 실제 투자 손익에 대한 책임은 사용자에게 있다.

## 현재 범위

- FastAPI 백엔드
- SQLite 단일 파일 DB
- 실데이터(pykrx / KRX JSON API / FinanceDataReader) + fallback 구조
- 시장 시그널 / 종목 시그널 / 전종목 스크리너 / 추천 종목 API
- React + Vite 대시보드 (다크 테마 종목 테이블, 태그/수급 표시)
- pytest 기본 테스트

## 데이터 소스 현황

| 항목 | 소스 | 상태 |
|------|------|------|
| 주가/거래량 | FinanceDataReader | 실제 |
| 종목명/시총/거래대금 | FinanceDataReader | 실제 |
| KOSPI200 지수 | FinanceDataReader/KS200 | 실제 |
| 외국인/기관 순매수 | pykrx | 실제 (fallback 가능) |
| 공매도 | pykrx | 실제 (fallback 가능) |
| 선물 투자자별 수급 | KRX JSON API (MDCSTAT12301) | 실제 (fallback 가능) |
| 옵션 미결제약정 | pykrx 전종목시세 | 실제 (fallback 가능) |
| 프로그램매매 | KRX JSON API (MDCSTAT22901) | 실제 (fallback 가능) |
| KOSPI200 선물 종가 | pykrx → 지수 fallback | 실제 (fallback 가능) |
| 차익잔고 압력 | - | TODO |

> KRX JSON API는 사내망 등 일부 환경에서 LOGOUT을 반환합니다. 이 경우 해당 항목은 0으로 fallback되고 시장 점수가 중립으로 고정됩니다.

## 사전 요구사항

- Python 3.11+ (3.13 권장)
- Node.js 18+

```powershell
python --version
node --version
```

## 설치 방법

프로젝트 폴더로 이동 (각 PC 경로에 맞게):

```powershell
cd <프로젝트 폴더 경로>
```

가상환경 생성 및 활성화:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

패키지 설치:

```powershell
pip install -r requirements.txt
```

프론트엔드 패키지 설치:

```powershell
cd frontend
npm install
cd ..
```

`.env` 파일 생성 (텔레그램 미사용 시 비워도 됨):

```powershell
Copy-Item .env.example .env
```

## 백엔드 실행

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

- API: http://127.0.0.1:8000
- Swagger: http://127.0.0.1:8000/docs

## 프론트엔드 실행

다른 터미널에서:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

- 대시보드: http://127.0.0.1:5173

## 최초 실행 순서

1. 백엔드 실행
2. 프론트엔드 실행
3. 브라우저에서 대시보드 열기
4. `수동 파이프라인 실행` 버튼 클릭 (또는 아래 PowerShell 명령)

## 수동 파이프라인 실행

```powershell
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/run-daily"
# 날짜 지정 시:
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/run-daily?trading_date=2026-04-03"
```

## 백필

```powershell
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/backfill?start_date=2026-04-02"
```

> 현재 MVP는 단일 날짜 재실행 형태이며, 날짜 범위 루프는 미구현.

## 테스트 실행

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m pytest
```

## 주요 API

- `GET /api/health`
- `GET /api/market-signal`
- `GET /api/market-signal/history`
- `GET /api/recommendations` — 상위 N개 (상방 10개 / 중립 5개 / 하방 0개)
- `GET /api/screener` — 전종목 점수 내림차순 (제한 없음)
- `GET /api/recommendations/history`
- `GET /api/stock/{code}/signals`
- `GET /api/derivatives/overview`
- `GET /api/data-sources` — 각 항목별 데이터 소스 상태 확인
- `GET /api/backtest/results`
- `PUT /api/settings/weights`
- `POST /api/jobs/run-daily`
- `POST /api/jobs/backfill`

## 설정 우선순위

1. DB `settings` 테이블
2. `backend/config.py`
3. 코드 기본값

## DB 초기화

```powershell
Remove-Item .\data\app.db
```

이후 백엔드 재실행 시 테이블 자동 재생성.

## 트러블슈팅

**KRX 수집 실패 (LOGOUT)**  
사내망·VPN 환경에서 `data.krx.co.kr`가 LOGOUT을 반환하는 경우입니다.  
시스템은 fallback(0)으로 계속 동작합니다. 개인 네트워크에서 실행하면 실데이터가 수집됩니다.

**pykrx 설치 오류**  
`pip install "setuptools<81"` 후 재설치.

**텔레그램 알림 미수신**  
`.env`의 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 확인.  
현재 MVP는 전송 로직 미구현 상태.

**포트 충돌**  
```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8001
```

## 시스템 한계 (MVP)

- KRX API 접근 불가 환경에서는 시장 점수가 0(중립)으로 고정됨
- 차익잔고 압력 / 종목별 프로그램 순매수 미구현 (항상 0)
- Backfill이 날짜 범위 루프 미지원 (단일 날짜만)
- 공매도 비율 정규화 범위 불일치 (0~5 가정 vs 실제 0~100)

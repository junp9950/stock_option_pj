# Futures Options Analyzer

선물·옵션 수급 기반 익일 종목 선별 시스템의 로컬 실행용 MVP입니다.  
이 프로젝트는 로컬 PC(Windows)에서 백엔드와 프론트엔드를 각각 개발 서버로 실행하는 흐름을 기준으로 작성되었습니다.

이 시스템은 투자 참고용 보조 도구이며, 실제 투자 손익에 대한 책임은 사용자에게 있다.

## 현재 범위

- FastAPI 백엔드
- SQLite 단일 파일 DB
- 데모 데이터 기반 일일 파이프라인
- 시장 시그널 / 종목 시그널 / 추천 종목 API
- React + Vite 대시보드
- pytest 기본 테스트

## 현재 MVP fallback

- 외부 데이터 수집이 안 되는 환경에서도 데모 데이터로 실행됩니다.
- `차익잔고 압력`, `종목별 프로그램 순매수`는 MVP에서 비활성화되며, 가중치는 재정규화됩니다.
- KRX OTP 크롤링 베이스 클래스는 포함되어 있으나, 실제 파라미터 매핑은 이후 확장 대상입니다.

## 사전 요구사항

- Python 3.11+
- Node.js 18+

Python 확인:

```powershell
python --version
```

Node.js 확인:

```powershell
node --version
```

## 설치 방법

프로젝트 폴더로 이동:

```powershell
cd C:\Users\Bat\Desktop\stock\futures-options-analyzer
```

가상환경 생성:

```powershell
python -m venv .venv
```

PowerShell에서 가상환경 활성화:

```powershell
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

`.env` 파일 생성:

```powershell
Copy-Item .env.example .env
```

텔레그램을 쓰지 않으면 `.env`는 비워둬도 됩니다.

## 백엔드 실행

```powershell
cd C:\Users\Bat\Desktop\stock\futures-options-analyzer
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="."
uvicorn backend.main:app --reload
```

백엔드 주소:

- http://127.0.0.1:8000
- http://127.0.0.1:8000/docs

## 프론트엔드 실행

다른 터미널을 열고 실행:

```powershell
cd C:\Users\Bat\Desktop\stock\futures-options-analyzer\frontend
npm run dev
```

프론트엔드 주소:

- http://127.0.0.1:5173

## 최초 실행 순서

1. 백엔드를 실행한다.
2. 프론트엔드를 실행한다.
3. 브라우저에서 대시보드를 연다.
4. 필요하면 대시보드에서 `수동 파이프라인 실행` 버튼을 눌러 데이터를 다시 생성한다.

## 수동 파이프라인 실행

PowerShell에서:

```powershell
Invoke-RestMethod -Method POST http://127.0.0.1:8000/api/jobs/run-daily
```

## 백필

현재 MVP는 단일 날짜 실행 중심이며, 백필 API는 같은 파이프라인을 날짜 기반으로 다시 실행하는 단순 형태입니다.

```powershell
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/backfill?start_date=2026-04-02"
```

## 테스트 실행

```powershell
cd C:\Users\Bat\Desktop\stock\futures-options-analyzer
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="."
pytest
```

## 주요 API

- `GET /api/health`
- `GET /api/market-signal`
- `GET /api/market-signal/history`
- `GET /api/recommendations`
- `GET /api/recommendations/history`
- `GET /api/stock/{code}/signals`
- `GET /api/derivatives/overview`
- `GET /api/backtest/results`
- `PUT /api/settings/weights`
- `POST /api/jobs/run-daily`
- `POST /api/jobs/backfill`

## 설정 우선순위

1. DB `settings`
2. `config.py`
3. 코드 기본값

## DB 초기화 방법

스키마를 다시 만들고 싶으면 SQLite 파일을 삭제하면 됩니다.

```powershell
Remove-Item .\data\app.db
```

그 다음 백엔드를 다시 실행하면 테이블이 재생성됩니다.

## 트러블슈팅

KRX 수집 실패 시:

- 현재 MVP는 데모 데이터 fallback으로 계속 동작합니다.
- 실제 KRX 파라미터 매핑은 이후 보강해야 합니다.

텔레그램 알림이 안 올 때:

- `.env`의 토큰과 채팅 ID를 확인합니다.
- 현재 MVP는 메시지 생성 로직 중심이며 실제 전송은 환경 설정 기반으로 확장 예정입니다.

포트 충돌 시:

```powershell
uvicorn backend.main:app --reload --port 8001
```

## 시스템 한계

- 현재는 외부 실데이터보다 로컬 실행성과 구조를 우선한 MVP입니다.
- 일부 수집기는 실제 KRX 요청 파라미터 매핑이 필요합니다.
- 차익잔고 압력과 종목별 프로그램 순매수는 fallback 처리됩니다.


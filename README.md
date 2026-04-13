# 한국 주식 수급 기반 익일 종목 선별 시스템

외국인·기관 수급, 공매도, 기술적 지표를 종합해 **내일 매수 후보**를 자동 선별하는 시스템입니다.

> 투자 참고용 보조 도구입니다. 실제 투자 손익의 책임은 사용자에게 있습니다.

---

## 구성

- **백엔드** — FastAPI + APScheduler (매일 16:30 KST 자동 실행)
- **DB** — Supabase PostgreSQL (클라우드, 집·회사 어디서든 같은 데이터)
- **데이터** — FinanceDataReader(주가) + KIS Open API(수급) + pykrx fallback

---

## 설치 방법

### Windows (로컬)

```powershell
git clone https://github.com/junp9950/stock_option_pj.git
cd stock_option_pj
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env` 파일 생성:
```
DATABASE_URL=your_supabase_url
KIS_APP_KEY=your_kis_key
KIS_APP_SECRET=your_kis_secret
```

서버 실행:
```powershell
.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### Rocky Linux / RHEL (서버 배포)

```bash
curl -O https://raw.githubusercontent.com/junp9950/stock_option_pj/main/setup.sh
chmod +x setup.sh
./setup.sh
```

스크립트가 Python 3.11 설치 → 레포 클론 → 패키지 설치 → .env 생성 → systemd 서비스 등록까지 자동으로 처리합니다. VM 재시작 시 서버 자동 실행됩니다.

---

## 매일 사용법

- **자동** — 매일 16:30 KST 파이프라인 실행. 데이터가 아직 없으면 5분마다 재시도
- **수동** — 대시보드 우상단 **▶ 파이프라인 실행** 버튼

---

## 대시보드

| 탭 | 내용 |
|----|------|
| 대시보드 | 내일 매수 후보 TOP 7, 시장 시그널, 추천 성과, 시그널 히스토리 |
| 전종목 스크리너 | KOSPI+KOSDAQ 200종목, 필터·정렬, 종목별 30일 수급 차트 |
| 시장 시그널 | 외인·기관 수급 기반 5단계 시그널 |
| 데이터 소스 | 수집 현황 및 데이터 품질 |
| 작업 로그 | 파이프라인 실행 이력 |

---

## 종목 시그널 지표

| 지표 | 비중 |
|------|------|
| 외국인 강도 | 12% |
| 기관 강도 | 12% |
| 동시매수 | 9% |
| MA 포지션 | 9% |
| MACD | 9% |
| RSI(14) | 8% |
| 거래량 급등 | 7% |
| 모멘텀 5일 | 7% |
| 연속매수 | 7% |
| 볼린저밴드 | 6% |
| 공매도 비율 | 5% |
| 공매도 추세 | 4% |

> 공매도 데이터가 없으면 해당 비중이 다른 지표로 자동 재분배됩니다.

---

## 초기 데이터 세팅 (최초 설치 시)

DB가 비어있으면 아래 순서로 데이터를 채웁니다. **Supabase DB를 공유 중이면 생략해도 됩니다.**

```powershell
# 1. 가격·수급 백필
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/backfill?start_date=2026-01-01&end_date=2026-04-14"

# 2. 시그널 재계산
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/signal-backfill"
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/market-signal-backfill"

# 3. 추천 생성
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/backfill?start_date=2026-01-02&end_date=2026-04-14"
```

---

## 주요 API

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /api/market-signal` | 시장 시그널 |
| `GET /api/screener/tomorrow-picks` | 내일 매수 후보 TOP 7 |
| `GET /api/screener` | 전종목 스크리너 |
| `GET /api/recommendations/performance` | 추천 성과 |
| `POST /api/jobs/run-daily` | 파이프라인 수동 실행 |

---

## 트러블슈팅

**KRX 수집 실패**
회사망·주말에 자주 발생. KIS API로 자동 전환되므로 무시해도 됩니다.

**포트 충돌 (Windows)**
```powershell
netstat -ano | findstr :8000
taskkill /F /PID <PID>
```

**서비스 재시작 (Linux)**
```bash
sudo systemctl restart stock-analyzer
sudo journalctl -u stock-analyzer -f
```

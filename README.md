# 선물·옵션 수급 기반 익일 종목 선별 시스템

한국 주식시장의 외국인·기관 수급, 공매도, 기술적 지표를 종합해 익일 유망 종목을 자동 선별하는 로컬 실행 시스템입니다.

> 이 시스템은 투자 참고용 보조 도구이며, 실제 투자 손익에 대한 책임은 사용자에게 있습니다.

---

## 빠른 시작 (Quick Start)

**Python 3.10 이상만 설치되어 있으면 됩니다.**

```
1. git clone https://github.com/junp9950/stock_option_pj.git
2. 폴더 안의 start.bat 더블클릭
3. 브라우저에서 http://127.0.0.1:8000 자동 오픈
```

최초 실행 시 가상환경 생성 + 패키지 설치로 1~2분 소요. 이후 실행은 즉시 시작됩니다.

---

## 주요 기능

### 대시보드
- 시장 시그널 (상방 / 중립 / 하방) 및 점수
- 추천 종목 테이블 (기관·외국인 순매수, 연속매수일, 태그)
- 시장 시그널 히스토리 (최근 7일)
- 전일 대비 시그널 상승 TOP 5

### 전종목 스크리너
- KOSPI + KOSDAQ 시총 상위 100개씩 (총 200종목)
- 정렬: 총점 / 종목점수 / 등락률 / 시총 / 공매도% / RSI / 거래량배수 / MA / 합류
- **상세 필터** (▼ 상세필터 버튼):
  - RSI 범위 (예: 30~50)
  - 공매도% 범위
  - 거래량배수 최소
  - 등락률 범위
  - 기관/외국인 매수·매도 방향
  - 신호 합류 수 최소
  - 연속매수일 최소
  - 총점 최소
  - 기관+외국인 동시매수만 보기
- CSV 내보내기

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
| 공매도 비율 변화 | 5% | 단기 공매도 증감 |
| 공매도 추세 | 4% | 공매도 방향성 |

### 시장 시그널 (7개 지표)
- 외국인/기관 선물 포지션
- 콜/풋 비율 (P/C Ratio)
- 베이시스 트렌드
- 미결제약정 변화
- 차익 프로그램매매 압력
- 지수 모멘텀

### 백테스트
- T+1 백테스트 (당일 종가 매수 → 익일 종가 매도)
- 수수료·슬리피지 0.3% 반영
- 지표: 평균수익률, 승률, 샤프지수, 누적수익률

---

## 데이터 소스

| 항목 | 소스 | 비고 |
|------|------|------|
| 주가·거래량 | FinanceDataReader | 정상 |
| 종목명·시총·거래대금 | FinanceDataReader | 정상 |
| 외국인·기관 순매수 | pykrx → 네이버 금융 fallback | KRX 차단 시 네이버 스크래핑 |
| 공매도 | pykrx | KRX 차단 시 fallback(0) |
| 선물 투자자별 수급 | KRX JSON API | KRX 차단 시 fallback(0) |
| 옵션 미결제약정 | pykrx | KRX 차단 시 fallback(0) |
| 프로그램매매 | KRX JSON API | KRX 차단 시 fallback(0) |
| KOSPI200 지수 | FinanceDataReader | 정상 |

> KRX API는 주말·일부 네트워크 환경에서 차단됩니다.  
> 이 경우 외국인·기관 수급은 **네이버 금융 자동 fallback**으로 수집됩니다.

---

## 설치 방법 (수동)

```powershell
# 1. 저장소 클론
git clone https://github.com/junp9950/stock_option_pj.git
cd stock_option_pj

# 2. 가상환경 생성
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. 패키지 설치
pip install -r requirements.txt

# 4. 서버 실행
.\.venv\Scripts\uvicorn.exe backend.main:app --host 0.0.0.0 --port 8000
```

---

## 수동 파이프라인 실행

```powershell
# 오늘 날짜 기준
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/run-daily"

# 날짜 지정
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/jobs/run-daily?trading_date=2026-04-03"
```

---

## 주요 API

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /api/health` | 서버 상태 |
| `GET /api/market-signal` | 시장 시그널 |
| `GET /api/screener?show_all=true` | 전종목 스크리너 |
| `GET /api/recommendations` | 추천 종목 |
| `GET /api/screener/trending` | 시그널 상승 TOP5 |
| `GET /api/data-quality` | 데이터 품질 점수 |
| `GET /api/stock/{code}/history` | 종목 시그널 이력 |
| `POST /api/jobs/run-daily` | 파이프라인 수동 실행 |
| `POST /api/backtest/run` | 백테스트 실행 |
| `POST /api/universe/refresh` | 종목 유니버스 갱신 |

---

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest
```

5개 테스트 통과 기준 유지.

---

## 트러블슈팅

**KRX 수집 실패 (LOGOUT)**
주말·사내망 환경에서 발생. 외국인·기관 수급은 네이버 금융 자동 fallback.  
시장 시그널(선물·옵션)은 0으로 고정됨.

**서버 포트 충돌**
```powershell
.\.venv\Scripts\uvicorn.exe backend.main:app --host 0.0.0.0 --port 8001
```

**DB 초기화**
```powershell
Remove-Item .\data\app.db
```
재실행 시 테이블 자동 재생성, 파이프라인 재실행 필요.

**pykrx 설치 오류**
```powershell
pip install "setuptools<81"
pip install pykrx
```

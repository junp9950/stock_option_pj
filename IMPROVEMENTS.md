# 개선 사항 목록

> 작성일: 2026-04-13  
> 현재 시스템은 정상 운영 중. 아래는 우선순위별 개선 아이디어.

---

## 즉시 할 수 있는 것

### 1. GitHub Actions 자동 배포 설정
`main` 브랜치에 push하면 VM이 자동으로 `git pull + restart`되도록.  
**`.github/workflows/deploy.yml`은 이미 작성됨. GitHub Secrets만 등록하면 됨.**

등록 방법:
1. GitHub → Settings → Secrets and variables → Actions → New repository secret
2. 아래 3개 등록:

| Secret 이름 | 값 |
|------------|-----|
| `VM_HOST` | Azure VM 공인 IP |
| `VM_USER` | `junp` |
| `VM_SSH_KEY` | VM의 SSH 개인키 (`ssh-keygen`으로 생성 후 등록) |

SSH 키 생성 (VM에서):
```bash
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/github_actions -N ""
cat ~/.ssh/github_actions.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/github_actions   # 이 내용을 VM_SSH_KEY에 등록
```

---

## 단기 개선 (1~2일)

### 2. 텔레그램 알림
파이프라인 완료/실패 시 폰으로 알림.  
`.env`에 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID` 추가하면 자동 활성화됨.  
(코드는 이미 준비되어 있음 — `backend/notification/telegram_bot.py`)

### 3. 새벽 백필 성능 개선
현재 30일치를 매일 전체 재수집 중 → **이미 수급 데이터가 있는 날짜는 건너뛰도록** 조건 추가.  
시간이 많이 단축될 것.

### 4. KIS 공매도 데이터 검증
오늘(2026-04-13) 처음 추가한 기능. 실제로 데이터가 잘 들어오는지 내일 확인 필요.  
`/api/screener`에서 공매도% 컬럼이 채워지는지 확인.

---

## 중기 개선 (1주 내)

### 5. 역사 데이터 갭 보완
서진시스템 등 최근 유니버스에 새로 편입된 종목은 과거 수급 데이터가 없음.  
새벽 3시 백필이 30일씩 쌓이면 점진적으로 채워지긴 하지만,  
한번 전체 재백필 돌리면 깔끔하게 해결됨 (로컬에서 실행 추천 — pykrx 사용 가능).

```powershell
Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/data/backfill?start_date=2026-01-01&end_date=2026-04-13"
```

### 6. 수급 데이터 단위 통일
현재 KIS API는 **수량(주)** 기준, pykrx는 **금액(원)** 기준으로 수집됨.  
두 소스가 섞이면 연속매수일 계산은 맞지만 절대값 비교는 부정확.  
KIS API도 금액 기준으로 변환하거나, 화면에 단위 표시 추가 권장.

### 7. 모바일 반응형
현재 PC 화면 기준으로만 구성됨. 폰에서 보기 불편.  
CSS 미디어쿼리 추가로 개선 가능.

---

## 장기 개선 (여유 있을 때)

### 8. 25년 데이터 백필
현재 26년 1월부터만 데이터 있음. 25년치까지 쌓이면 추천 성과 분석이 더 의미있어짐.  
로컬에서 백필 실행 (시간 오래 걸림).

### 9. 알림 기능
특정 종목 수급 급변 시 텔레그램/이메일 알림.

### 10. 점수 가중치 튜닝
현재 고정값. 추천 성과 데이터가 쌓이면 승률 높이는 방향으로 조정 가능.

---

## 현재 알려진 버그/이슈

| 이슈 | 원인 | 상태 |
|------|------|------|
| 데이터 품질 39.6% | 수급 데이터 없는 종목 多 (KRX 차단) | 새벽 백필로 점진 개선 중 |
| KIS 수급 단위 불일치 | KIS=수량, pykrx=금액 | 미해결 |
| 공매도 데이터 신규 | KIS 공매도 오늘 첫 수집 | 내일 확인 필요 |

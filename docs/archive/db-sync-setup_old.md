# DB 동기화 설정 가이드 (구글드라이브 심볼릭 링크)

## 목적
집 컴퓨터와 회사 컴퓨터가 동일한 `app.db`를 공유해서 항상 같은 데이터를 사용하기 위함.

## 사용 패턴
- 집 컴은 집에 있을 때만 켜고, 출근 시 꺼둠
- 회사 컴은 회사에서만 사용
- 동시에 두 컴이 켜지는 경우 없음 → 충돌 없음

## 사전 준비
구글드라이브 데스크탑 앱 설치 (양쪽 컴퓨터 모두)
- 다운로드: https://www.google.com/drive/download/

---

## 집 컴퓨터 설정 (먼저 진행)

### 1. 구글드라이브에 DB 폴더 생성
구글드라이브 앱 설치 후 동기화 폴더 확인 (보통 `C:\Users\[유저명]\Google Drive\My Drive\`)

### 2. DB 파일을 구글드라이브로 이동
**관리자 권한으로 CMD 실행** 후 아래 명령어 실행:

```cmd
:: 구글드라이브에 폴더 생성
mkdir "C:\Users\Metanet\Google Drive\My Drive\stock_db"

:: 현재 DB를 구글드라이브로 복사
copy "C:\Users\Metanet\Downloads\stock_option_pj-main\stock_option_pj-main\data\app.db" "C:\Users\Metanet\Google Drive\My Drive\stock_db\app.db"

:: 기존 DB 삭제
del "C:\Users\Metanet\Downloads\stock_option_pj-main\stock_option_pj-main\data\app.db"

:: 심볼릭 링크 생성
mklink "C:\Users\Metanet\Downloads\stock_option_pj-main\stock_option_pj-main\data\app.db" "C:\Users\Metanet\Google Drive\My Drive\stock_db\app.db"
```

### 3. 확인
```cmd
dir "C:\Users\Metanet\Downloads\stock_option_pj-main\stock_option_pj-main\data\"
```
`app.db`가 `[SYMLINK]` 또는 화살표(→)로 표시되면 성공.

---

## 회사 컴퓨터 설정

### 1. 구글드라이브 앱 설치 및 동기화 완료 확인
`C:\Users\Metanet\Google Drive\My Drive\stock_db\app.db` 파일이 존재하는지 확인.

### 2. 기존 DB 삭제 후 심볼릭 링크 생성
**관리자 권한으로 CMD 실행:**

```cmd
:: 기존 DB 백업 (혹시 몰라서)
copy "C:\Users\Metanet\Downloads\stock_option_pj-main\stock_option_pj-main\data\app.db" "C:\Users\Metanet\Downloads\stock_option_pj-main\stock_option_pj-main\data\app.db.bak"

:: 기존 DB 삭제
del "C:\Users\Metanet\Downloads\stock_option_pj-main\stock_option_pj-main\data\app.db"

:: 심볼릭 링크 생성
mklink "C:\Users\Metanet\Downloads\stock_option_pj-main\stock_option_pj-main\data\app.db" "C:\Users\Metanet\Google Drive\My Drive\stock_db\app.db"
```

---

## 주의사항
- **두 컴퓨터를 동시에 켜고 서버 실행 금지** (SQLite는 동시 쓰기 불가)
- 서버 실행 중에는 구글드라이브가 DB를 동기화하지 않도록 드라이브 앱의 "스트리밍" 모드가 아닌 "미러링" 모드 사용 권장
- `app.db-wal`, `app.db-shm` 파일도 같이 동기화될 수 있으나 서버 종료 후 자동으로 정리됨

## 동작 흐름
```
집 컴 켬 → 드라이브 동기화 → 최신 DB 로드 → 서버 실행 → 작업
출근 → 집 컴 끔 → 드라이브에 최신 DB 업로드됨
회사 도착 → 드라이브 동기화 → 최신 DB 로드 → 서버 실행 → 작업
퇴근 → 회사 컴 끔 (또는 그냥 두고 감) → 드라이브에 최신 DB 업로드됨
```

#!/bin/bash
# Rocky Linux / RHEL / Ubuntu / Debian 자동 설치 스크립트

set -e

REPO_URL="https://github.com/junp9950/stock_option_pj.git"
APP_DIR="$HOME/stock_option_pj"
SERVICE_NAME="stock-analyzer"

echo "=============================="
echo "  주식 분석 서버 자동 설치"
echo "=============================="

# OS 판별
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID="${ID,,}"  # lowercase
else
    OS_ID="unknown"
fi

case "$OS_ID" in
    ubuntu|debian)
        PKG_INSTALL="sudo apt-get install -y"
        PKG_UPDATE="sudo apt-get update -y"
        PYTHON_PKG="python3.11 python3.11-venv"
        ;;
    rocky|rhel|centos|fedora|almalinux)
        PKG_INSTALL="sudo dnf install -y"
        PKG_UPDATE=""
        PYTHON_PKG="python3.11"
        ;;
    *)
        echo "⚠ 지원하지 않는 OS ($OS_ID). Rocky/RHEL/Ubuntu/Debian 권장."
        PKG_INSTALL="sudo dnf install -y"
        PKG_UPDATE=""
        PYTHON_PKG="python3.11"
        ;;
esac

echo "  감지된 OS: $PRETTY_NAME"

# 패키지 매니저 업데이트 (apt 계열만)
if [ -n "$PKG_UPDATE" ]; then
    $PKG_UPDATE -q
fi

# 1. Python 3.11 설치
echo "[1/6] Python 3.11 설치 중..."
if ! command -v python3.11 &>/dev/null; then
    $PKG_INSTALL $PYTHON_PKG
else
    echo "  Python 3.11 이미 설치됨"
fi

# 2. git 설치
echo "[2/6] git 설치 확인..."
if ! command -v git &>/dev/null; then
    $PKG_INSTALL git
else
    echo "  git 이미 설치됨"
fi

# 3. 레포 클론 or 업데이트
echo "[3/6] 소스코드 준비 중..."
if [ -d "$APP_DIR" ]; then
    echo "  기존 디렉토리 발견, git pull..."
    cd "$APP_DIR" && git pull
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 4. 가상환경 + 패키지 설치
echo "[4/6] 가상환경 및 패키지 설치 중..."
cd "$APP_DIR"
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
echo "  패키지 설치 완료"

# 5. .env 파일 생성
echo "[5/6] 환경변수 설정..."
if [ -f "$APP_DIR/.env" ]; then
    echo "  .env 파일 이미 존재, 건너뜀"
else
    echo ""
    echo "DB 연결 정보를 입력하세요:"
    read -rp "  DATABASE_URL: " DB_URL
    read -rp "  KIS_APP_KEY: " KIS_KEY
    read -rp "  KIS_APP_SECRET: " KIS_SECRET

    cat > "$APP_DIR/.env" << EOF
DATABASE_URL=$DB_URL
KIS_APP_KEY=$KIS_KEY
KIS_APP_SECRET=$KIS_SECRET
EOF
    echo "  .env 파일 생성 완료"
fi

# 6. systemd 서비스 등록
echo "[6/6] systemd 서비스 등록 중..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Stock Analyzer FastAPI Server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "=============================="
echo "  설치 완료!"
echo "=============================="
echo ""
echo "서버 상태 확인: sudo systemctl status $SERVICE_NAME"
echo "로그 확인:      sudo journalctl -u $SERVICE_NAME -f"
echo "서버 주소:      http://$(hostname -I | awk '{print $1}'):8000"
echo ""

# 방화벽 포트 오픈 안내
if command -v firewall-cmd &>/dev/null; then
    echo "방화벽 포트 오픈 필요 시 (Rocky/RHEL):"
    echo "  sudo firewall-cmd --permanent --add-port=8000/tcp"
    echo "  sudo firewall-cmd --reload"
elif command -v ufw &>/dev/null; then
    echo "방화벽 포트 오픈 필요 시 (Ubuntu):"
    echo "  sudo ufw allow 8000/tcp"
fi

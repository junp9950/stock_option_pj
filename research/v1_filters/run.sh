#!/bin/bash
# v1_filters 스크립트 실행 (v11 엔진 환경 그대로, nice 15) — 사용: bash run.sh 스크립트.py > out.txt
cd /home/junp/stock_option_pj && set -a && . ./.env && set +a
export STOCK_DB_URL="$DATABASE_URL" STOCK_LAB_DATA=/home/junp/tmp_claude/lab_v11_data STOCK_APP_ROOT=/home/junp/stock/futures-options-analyzer LAB_DROP_ANOMALY=1 LAB_FORCED_SETTLE=1
cd /home/junp/tmp_claude/v1_filters
exec nice -n 15 /home/junp/stock_option_pj/.venv/bin/python "$@"

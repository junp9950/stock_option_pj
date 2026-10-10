#!/bin/bash
# GPT 수정 연구 스크립트로 12년 핵심 숫자 다시 계산 (2026-10-11 KST) — 한 번에 하나씩
cd /home/junp/stock_option_pj && set -a && . ./.env && set +a
export STOCK_DB_URL="$DATABASE_URL" STOCK_LAB_DATA=/home/junp/tmp_claude/lab_v11_data STOCK_APP_ROOT=/home/junp/stock/futures-options-analyzer LAB_DROP_ANOMALY=1 LAB_FORCED_SETTLE=1
OUT=/home/junp/tmp_claude/lab_v11_out
cd /home/junp/tmp_claude/lab_v11
for s in ranking_lab redteam_run lead_state12 pullback_open; do
  echo "$(date '+%m-%d %H:%M') 시작 $s" >> $OUT/progress.log
  nice -n 10 /home/junp/stock_option_pj/.venv/bin/python run_one.py $s.py > $OUT/${s}_out.txt 2>&1
  echo "$(date '+%m-%d %H:%M') 끝 $s (코드 $?)" >> $OUT/progress.log
done
echo "$(date '+%m-%d %H:%M') 전부 끝" >> $OUT/progress.log

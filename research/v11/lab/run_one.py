"""스크립트 하나를 __main__으로 돌리고, 끝나면 가정 적용 건수를 적는다 (2026-10-11 KST)."""
import runpy, sys, time
t = time.time()
script = sys.argv[1]
sys.argv = [script] + sys.argv[2:]          # 스크립트가 sys.argv[1]을 자기 인자로 읽음
runpy.run_path(script, run_name="__main__")
ma = sys.modules.get("ma_lab")
print(f"\n[가정] 가격 이상 봉에 걸쳐 뺀 거래: {len(getattr(ma, 'DROPPED', [])) if ma else 0}건 · 걸린 시간 {(time.time() - t) / 60:.1f}분", flush=True)

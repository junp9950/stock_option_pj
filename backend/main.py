from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from backend.api.routes import router
from backend.config import get_config
from backend.db.database import Base, SessionLocal, engine
from backend.db.seed import seed_reference_data
from backend.scheduler import start_scheduler
from backend.services.daily_pipeline import run_daily_pipeline


config = get_config()
app = FastAPI(title=config.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=config.api_prefix)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def status_dashboard() -> str:
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>선물·옵션 수급 시스템 — 상태</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d1117;color:#c9d1d9;font-family:'Segoe UI',sans-serif;font-size:14px;padding:24px}
  h1{font-size:20px;font-weight:700;color:#e6edf3;margin-bottom:4px}
  .sub{color:#8b949e;font-size:12px;margin-bottom:24px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:24px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
  .card h3{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#8b949e;margin-bottom:8px}
  .card .val{font-size:26px;font-weight:700;color:#e6edf3}
  .card .note{font-size:11px;color:#8b949e;margin-top:4px}
  .signal-상방{color:#3fb950} .signal-하방{color:#f85149} .signal-중립{color:#d29922}
  table{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden;margin-bottom:24px}
  th{background:#21262d;padding:8px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#8b949e;border-bottom:1px solid #30363d}
  td{padding:8px 12px;border-bottom:1px solid #21262d;font-size:13px}
  tr:last-child td{border-bottom:none}
  .badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600}
  .real{background:#0d4a2b;color:#3fb950} .rfb{background:#3d2b00;color:#d29922} .fallback{background:#3d0b0b;color:#f85149}
  .tag{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;margin:1px;background:#21262d;color:#8b949e}
  .score{font-weight:700;color:#58a6ff}
  section h2{font-size:15px;font-weight:600;color:#e6edf3;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #30363d}
  section{margin-bottom:24px}
  .btn{background:#238636;color:#fff;border:none;padding:7px 16px;border-radius:6px;cursor:pointer;font-size:13px;margin-right:8px}
  .btn:hover{background:#2ea043} .btn-gray{background:#21262d;color:#c9d1d9} .btn-gray:hover{background:#30363d}
  .toast{position:fixed;bottom:20px;right:20px;background:#238636;color:#fff;padding:10px 18px;border-radius:8px;display:none;font-size:13px}
  #err{color:#f85149;font-size:12px;margin-top:8px;display:none}
  .ts{color:#8b949e;font-size:11px}
</style>
</head>
<body>
<h1>선물·옵션 수급 기반 익일 종목 선별 시스템</h1>
<p class="sub">로컬 상태 대시보드 — 백엔드 직접 조회 (http://127.0.0.1:8000)</p>

<div style="margin-bottom:16px">
  <button class="btn" onclick="runPipeline()">▶ 파이프라인 수동 실행</button>
  <button class="btn btn-gray" onclick="load()">⟳ 새로고침</button>
  <span id="err"></span>
</div>

<div class="grid" id="cards">
  <div class="card"><h3>시장 시그널</h3><div class="val" id="sig">—</div><div class="note" id="sig-score"></div></div>
  <div class="card"><h3>기준일</h3><div class="val" id="date" style="font-size:18px">—</div></div>
  <div class="card"><h3>추천 종목 수</h3><div class="val" id="rec-cnt">—</div></div>
  <div class="card"><h3>스크리너 종목</h3><div class="val" id="scr-cnt">—</div><div class="note">시총·거래대금 필터 후</div></div>
</div>

<section>
  <h2>추천 종목</h2>
  <table><thead><tr><th>#</th><th>종목</th><th>점수</th><th>종가</th><th>등락</th><th>기관</th><th>외국인</th><th>태그</th></tr></thead>
  <tbody id="rec-body"><tr><td colspan="8" style="color:#8b949e;text-align:center">로딩 중…</td></tr></tbody></table>
</section>

<section>
  <h2>데이터 소스 현황</h2>
  <table><thead><tr><th>항목</th><th>소스</th><th>상태</th><th>비고</th></tr></thead>
  <tbody id="src-body"><tr><td colspan="4" style="color:#8b949e;text-align:center">로딩 중…</td></tr></tbody></table>
</section>

<div class="toast" id="toast"></div>

<script>
const API = 'http://127.0.0.1:8000/api';
const fmt = (n) => n == null ? '—' : Math.abs(n) >= 1e8 ? (n/1e8).toFixed(0)+'억' : Math.abs(n) >= 1e4 ? (n/1e4).toFixed(0)+'만' : String(Math.round(n));
const fmtP = (n) => n == null ? '—' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
const fmtKrw = (n) => n == null ? '—' : Number(n).toLocaleString() + '원';

async function load() {
  try {
    const [sig, recs, srcs] = await Promise.all([
      fetch(API+'/market-signal').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/recommendations').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/data-sources').then(r=>r.ok?r.json():null).catch(()=>null),
    ]);

    if (sig) {
      document.getElementById('sig').innerHTML = `<span class="signal-${sig.signal}">${sig.signal}</span>`;
      document.getElementById('sig-score').textContent = '점수: ' + sig.score;
      document.getElementById('date').textContent = sig.trading_date;
    }

    if (recs) {
      document.getElementById('rec-cnt').textContent = recs.items.length;
      const tbody = document.getElementById('rec-body');
      if (!recs.items.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="color:#8b949e;text-align:center">데이터 없음 — 파이프라인을 실행하세요</td></tr>';
      } else {
        tbody.innerHTML = recs.items.map(i => `<tr>
          <td>${i.rank}</td>
          <td><b>${i.name}</b><br><span class="ts">${i.code}</span></td>
          <td class="score">${i.total_score}</td>
          <td>${fmtKrw(i.close_price)}</td>
          <td style="color:${i.change_pct>=0?'#3fb950':'#f85149'}">${fmtP(i.change_pct)}</td>
          <td>${fmt(i.institution_net_buy)}</td>
          <td>${fmt(i.foreign_net_buy)}</td>
          <td>${(i.tags||[]).map(t=>`<span class="tag">${t}</span>`).join('')}</td>
        </tr>`).join('');
      }
    }

    // screener count
    fetch(API+'/screener').then(r=>r.ok?r.json():null).catch(()=>null).then(s=>{
      if(s) document.getElementById('scr-cnt').textContent = s.length;
    });

    if (srcs) {
      const statusMap = {real:'real',real_with_fallback:'rfb',fallback:'fallback'};
      const labelMap = {real:'실제',real_with_fallback:'실제(fallback가능)',fallback:'fallback'};
      document.getElementById('src-body').innerHTML = Object.entries(srcs).map(([k,v])=>`<tr>
        <td>${k}</td><td>${v.source}</td>
        <td><span class="badge ${statusMap[v.status]||''}">${labelMap[v.status]||v.status}</span></td>
        <td class="ts">${v.note||''}</td>
      </tr>`).join('');
    }

    document.getElementById('err').style.display='none';
  } catch(e) {
    document.getElementById('err').textContent = '연결 실패: 백엔드가 실행 중인지 확인하세요';
    document.getElementById('err').style.display='block';
  }
}

async function runPipeline() {
  const today = new Date().toISOString().slice(0,10);
  const btn = event.target;
  btn.disabled = true; btn.textContent = '실행 중…';
  try {
    const r = await fetch(`${API}/jobs/run-daily?trading_date=${today}`, {method:'POST'});
    const data = await r.json();
    showToast(`완료: ${data.market_signal} / 추천 ${data.recommendation_count}종목`);
    await load();
  } catch(e) {
    showToast('실행 실패: ' + e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = '▶ 파이프라인 수동 실행';
  }
}

function showToast(msg, err=false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = err ? '#da3633' : '#238636';
  t.style.display = 'block';
  setTimeout(() => t.style.display='none', 4000);
}

load();
setInterval(load, 60000); // 1분마다 자동 갱신
</script>
</body>
</html>"""


@app.on_event("startup")
def startup_event() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_reference_data(db)
        run_daily_pipeline(db)
    finally:
        db.close()
    start_scheduler()


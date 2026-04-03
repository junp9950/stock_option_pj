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
<title>선물·옵션 수급 시스템</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:'Segoe UI',sans-serif;font-size:14px}
header{padding:16px 24px;border-bottom:1px solid #30363d;display:flex;align-items:center;justify-content:space-between}
header h1{font-size:17px;font-weight:700;color:#e6edf3}
header .sub{font-size:11px;color:#8b949e;margin-top:2px}
.tabs{display:flex;gap:0;border-bottom:1px solid #30363d;padding:0 24px;background:#161b22}
.tab{padding:10px 18px;cursor:pointer;font-size:13px;color:#8b949e;border-bottom:2px solid transparent;transition:.15s}
.tab:hover{color:#c9d1d9}.tab.active{color:#58a6ff;border-bottom-color:#58a6ff}
.toolbar{padding:12px 24px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;border-bottom:1px solid #21262d}
.content{padding:20px 24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
.card h3{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#8b949e;margin-bottom:8px}
.card .val{font-size:28px;font-weight:700;color:#e6edf3}
.card .note{font-size:11px;color:#8b949e;margin-top:4px}
.signal-상방{color:#3fb950}.signal-하방{color:#f85149}.signal-중립{color:#d29922}
table{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden;margin-bottom:16px}
th{background:#21262d;padding:8px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:#8b949e;border-bottom:1px solid #30363d;cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:#c9d1d9}th .sort-icon{margin-left:4px;opacity:.5}
td{padding:7px 12px;border-bottom:1px solid #21262d;font-size:13px}
tr:last-child td{border-bottom:none}tr:hover td{background:#1c2128}
.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600}
.real{background:#0d4a2b;color:#3fb950}.rfb{background:#3d2b00;color:#d29922}.fallback{background:#3d0b0b;color:#f85149}
.tag{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;margin:1px;background:#21262d;color:#8b949e}
.tag.co{background:#0d2b10;color:#3fb950}.tag.inst{background:#0d1f3a;color:#58a6ff}
.tag.fgn{background:#0d2b2b;color:#39d0d0}.tag.big{background:#2b1f00;color:#d29922}.tag.sell{background:#3d0b0b;color:#f85149}
.score-bar{display:inline-block;height:6px;border-radius:3px;background:#58a6ff;margin-left:6px;vertical-align:middle}
.neg .score-bar{background:#f85149}
.btn{background:#238636;color:#fff;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:13px}
.btn:hover{background:#2ea043}.btn-gray{background:#21262d;color:#c9d1d9}.btn-gray:hover{background:#30363d}
.btn-sm{padding:4px 10px;font-size:12px}
input[type=text]{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:6px;font-size:13px;width:220px}
input[type=text]:focus{outline:none;border-color:#58a6ff}
select{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:6px;font-size:13px}
.panel{display:none}.panel.active{display:block}
.toast{position:fixed;bottom:20px;right:20px;background:#238636;color:#fff;padding:10px 18px;border-radius:8px;display:none;font-size:13px;z-index:999}
.err-bar{background:#3d0b0b;color:#f85149;padding:8px 24px;font-size:12px;display:none}
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.7);display:none;z-index:100;align-items:center;justify-content:center}
.modal-bg.show{display:flex}
.modal{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:24px;width:620px;max-height:80vh;overflow-y:auto}
.modal h2{font-size:16px;font-weight:700;margin-bottom:16px;color:#e6edf3}
.close-btn{float:right;cursor:pointer;color:#8b949e;font-size:18px;line-height:1}.close-btn:hover{color:#e6edf3}
.ts{color:#8b949e;font-size:11px}
.log-ok{color:#3fb950}.log-err{color:#f85149}.log-run{color:#d29922}
</style>
</head>
<body>
<header>
  <div>
    <h1>선물·옵션 수급 기반 익일 종목 선별 시스템</h1>
    <div class="sub">로컬 대시보드 · <span id="hdr-date">—</span> · <span id="hdr-sig">—</span> · 1분 자동 갱신</div>
  </div>
  <div style="display:flex;gap:8px">
    <button class="btn" onclick="runPipeline(this)">▶ 파이프라인 실행</button>
    <button class="btn btn-gray" onclick="refreshUniverse(this)">↺ 유니버스 갱신</button>
    <button class="btn btn-gray" onclick="loadAll()">⟳ 새로고침</button>
  </div>
</header>

<div class="err-bar" id="err-bar">백엔드 연결 실패 — 서버가 실행 중인지 확인하세요</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('dash')">대시보드</div>
  <div class="tab" onclick="switchTab('screener')">전종목 스크리너</div>
  <div class="tab" onclick="switchTab('signal')">시장 시그널 상세</div>
  <div class="tab" onclick="switchTab('backtest')">백테스트</div>
  <div class="tab" onclick="switchTab('sources')">데이터 소스</div>
  <div class="tab" onclick="switchTab('logs')">실행 이력</div>
</div>

<!-- 대시보드 탭 -->
<div id="panel-dash" class="panel active content">
  <div class="grid">
    <div class="card"><h3>시장 시그널</h3><div class="val" id="sig">—</div><div class="note" id="sig-score"></div></div>
    <div class="card"><h3>기준일</h3><div class="val" id="date" style="font-size:20px">—</div></div>
    <div class="card"><h3>추천 종목</h3><div class="val" id="rec-cnt">—</div><div class="note">상위 점수 기준</div></div>
    <div class="card"><h3>전종목 스크리닝</h3><div class="val" id="scr-cnt">—</div><div class="note">시총·거래대금 필터 후</div></div>
  </div>
  <table>
    <thead><tr>
      <th>#</th><th>종목</th><th>총점</th><th>종가</th><th>등락</th>
      <th>기관 순매수</th><th>외국인 순매수</th><th>연속일</th><th>태그</th>
    </tr></thead>
    <tbody id="rec-body"><tr><td colspan="9" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
</div>

<!-- 전종목 스크리너 탭 -->
<div id="panel-screener" class="panel">
  <div class="toolbar">
    <input type="text" id="scr-search" placeholder="종목명 또는 코드 검색…" oninput="renderScreener()">
    <select id="scr-market" onchange="renderScreener()">
      <option value="">전체 시장</option>
      <option value="KOSPI">KOSPI</option>
      <option value="KOSDAQ">KOSDAQ</option>
    </select>
    <select id="scr-sort" onchange="renderScreener()">
      <option value="total_score">총점 순</option>
      <option value="change_pct">등락률 순</option>
      <option value="close_price">종가 순</option>
      <option value="short_ratio">공매도% 순</option>
    </select>
    <span class="ts" id="scr-info"></span>
  </div>
  <div class="content">
    <table>
      <thead><tr>
        <th onclick="setScrSort('rank')">#<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('name')">종목<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('total_score')">총점<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('stock_score')">종목점수<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('close_price')">종가<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('change_pct')">등락<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('institution_net_buy')">기관<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('foreign_net_buy')">외국인<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('short_ratio')">공매도%<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('ma_score')">MA위치<span class="sort-icon">↕</span></th>
        <th>태그</th>
        <th>상세</th>
      </tr></thead>
      <tbody id="scr-body"><tr><td colspan="12" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
    </table>
  </div>
</div>

<!-- 백테스트 탭 -->
<div id="panel-backtest" class="panel content">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
    <button class="btn" onclick="runBacktest(this)">▶ 백테스트 실행 (T+1)</button>
    <span class="ts" id="bt-status"></span>
  </div>
  <div class="grid" id="bt-cards" style="margin-bottom:16px"></div>
  <table>
    <thead><tr><th>날짜</th><th>평균수익률(T+1)</th><th>승률</th><th>종목수</th></tr></thead>
    <tbody id="bt-body"><tr><td colspan="4" style="color:#8b949e;text-align:center;padding:20px">백테스트 실행 버튼을 눌러 결과를 확인하세요</td></tr></tbody>
  </table>
</div>

<!-- 시장 시그널 상세 탭 -->
<div id="panel-signal" class="panel content">
  <div class="grid" id="sig-cards"></div>
  <table>
    <thead><tr><th>지표</th><th>실측값</th><th>정규화 점수</th><th>설명</th><th>소스</th><th>비고</th></tr></thead>
    <tbody id="sig-detail-body"><tr><td colspan="6" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
</div>

<!-- 데이터 소스 탭 -->
<div id="panel-sources" class="panel content">
  <table>
    <thead><tr><th>항목</th><th>소스</th><th>상태</th><th>비고</th></tr></thead>
    <tbody id="src-body"><tr><td colspan="4" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
</div>

<!-- 실행 이력 탭 -->
<div id="panel-logs" class="panel content">
  <table>
    <thead><tr><th>시각</th><th>기준일</th><th>단계</th><th>상태</th><th>메시지</th></tr></thead>
    <tbody id="log-body"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
</div>

<!-- 종목 상세 모달 -->
<div class="modal-bg" id="modal-bg" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <span class="close-btn" onclick="closeModal()">✕</span>
    <h2 id="modal-title">종목 시그널 상세</h2>
    <div id="modal-body"></div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = 'http://127.0.0.1:8000/api';
let scrData = [], scrSortKey = 'total_score', scrSortAsc = false;

const fmt = n => n==null?'—':Math.abs(n)>=1e8?(n>=0?'+':'')+Math.abs(n/1e8).toFixed(0)+'억':(n>=0?'+':'-')+Math.abs(n/1e4).toFixed(0)+'만';
const fmtP = n => n==null?'—':(n>=0?'+':'')+n.toFixed(2)+'%';
const fmtKrw = n => n==null?'—':Number(n).toLocaleString()+'원';
const scoreBar = (s,max=3) => {const w=Math.min(Math.abs(s)/max*60,60);return `<span class="${s<0?'neg':''}" style="display:inline-flex;align-items:center"><b style="color:${s>0?'#58a6ff':s<0?'#f85149':'#8b949e'}">${s.toFixed(2)}</b><span class="score-bar" style="width:${w}px;background:${s>0?'#58a6ff':s<0?'#f85149':'#444'}"></span></span>`;};
const tagHtml = tags => (tags||[]).map(t=>{
  let cls='tag';
  if(t.includes('동시'))cls+=' co';
  else if(t.includes('기관'))cls+=' inst';
  else if(t.includes('외국인'))cls+=' fgn';
  else if(t.includes('대규모'))cls+=' big';
  else if(t.includes('개인'))cls+=' sell';
  return `<span class="${cls}">${t}</span>`;
}).join('');

function switchTab(id) {
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',['dash','screener','signal','backtest','sources','logs'][i]===id));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+id).classList.add('active');
  if(id==='screener')loadScreener();
  if(id==='signal')loadSignalDetail();
  if(id==='sources')loadSources();
  if(id==='logs')loadLogs();
  if(id==='backtest')loadBacktestSummary();
}

async function loadAll() {
  try {
    const [sig, recs, scr] = await Promise.all([
      fetch(API+'/market-signal').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/recommendations').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/screener').then(r=>r.ok?r.json():null).catch(()=>null),
    ]);
    document.getElementById('err-bar').style.display='none';

    if(sig){
      document.getElementById('sig').innerHTML=`<span class="signal-${sig.signal}">${sig.signal}</span>`;
      document.getElementById('sig-score').textContent='점수: '+sig.score;
      document.getElementById('date').textContent=sig.trading_date;
      document.getElementById('hdr-date').textContent=sig.trading_date;
      document.getElementById('hdr-sig').innerHTML=`<span class="signal-${sig.signal}">${sig.signal} (${sig.score})</span>`;
    }
    if(recs){
      document.getElementById('rec-cnt').textContent=recs.items.length;
      const empty='<tr><td colspan="9" style="color:#8b949e;text-align:center;padding:20px">데이터 없음 — 파이프라인을 실행하세요</td></tr>';
      document.getElementById('rec-body').innerHTML=recs.items.length?recs.items.map(i=>`<tr>
        <td>${i.rank}</td>
        <td><b>${i.name}</b><br><span class="ts">${i.code} · ${i.market||'KOSPI'}</span></td>
        <td>${scoreBar(i.total_score)}</td>
        <td>${fmtKrw(i.close_price)}</td>
        <td style="color:${i.change_pct>=0?'#3fb950':'#f85149'}">${fmtP(i.change_pct)}</td>
        <td>${fmt(i.institution_net_buy)}</td>
        <td>${fmt(i.foreign_net_buy)}</td>
        <td>${i.consecutive_days>0?'<b style="color:#58a6ff">'+i.consecutive_days+'일</b>':'—'}</td>
        <td>${tagHtml(i.tags)}</td>
      </tr>`).join(''):empty;
    }
    if(scr) document.getElementById('scr-cnt').textContent=scr.length;
  } catch(e) {
    document.getElementById('err-bar').style.display='block';
  }
}

async function loadScreener() {
  const r = await fetch(API+'/screener').catch(()=>null);
  if(!r||!r.ok){document.getElementById('scr-body').innerHTML='<tr><td colspan="11" style="color:#f85149;text-align:center;padding:20px">로드 실패</td></tr>';return;}
  scrData = await r.json();
  renderScreener();
}

function setScrSort(key){
  if(scrSortKey===key)scrSortAsc=!scrSortAsc;
  else{scrSortKey=key;scrSortAsc=false;}
  renderScreener();
}

function renderScreener(){
  const q=document.getElementById('scr-search').value.toLowerCase();
  const mkt=document.getElementById('scr-market').value;
  let data=[...scrData].filter(i=>{
    if(q&&!i.name.toLowerCase().includes(q)&&!i.code.includes(q))return false;
    if(mkt&&i.market!==mkt)return false;
    return true;
  });
  data.sort((a,b)=>{
    const av=a[scrSortKey]??0, bv=b[scrSortKey]??0;
    return scrSortAsc?(av>bv?1:-1):(av<bv?1:-1);
  });
  document.getElementById('scr-info').textContent=`${data.length}/${scrData.length}종목`;
  if(!data.length){document.getElementById('scr-body').innerHTML='<tr><td colspan="11" style="color:#8b949e;text-align:center;padding:16px">검색 결과 없음</td></tr>';return;}
  document.getElementById('scr-body').innerHTML=data.map((i,idx)=>`<tr>
    <td style="color:#8b949e">${idx+1}</td>
    <td><b>${i.name}</b><br><span class="ts">${i.code} · <span style="color:${i.market==='KOSPI'?'#58a6ff':'#39d0d0'}">${i.market||'KOSPI'}</span></span></td>
    <td>${scoreBar(i.total_score)}</td>
    <td>${scoreBar(i.stock_score)}</td>
    <td style="font-weight:600">${fmtKrw(i.close_price)}</td>
    <td style="color:${i.change_pct>=0?'#3fb950':'#f85149'};font-weight:600">${fmtP(i.change_pct)}</td>
    <td>${fmt(i.institution_net_buy)}</td>
    <td>${fmt(i.foreign_net_buy)}</td>
    <td style="color:${(i.short_ratio||0)<=4?'#3fb950':(i.short_ratio||0)<=10?'#d29922':'#f85149'}">${(i.short_ratio||0).toFixed(1)}%</td>
    <td>${scoreBar(i.ma_score||0,2)}</td>
    <td>${tagHtml(i.tags)}</td>
    <td><button class="btn btn-gray btn-sm" onclick="showStockDetail('${i.code}','${i.name}')">상세</button></td>
  </tr>`).join('');
}

async function loadSignalDetail(){
  const [sig, details] = await Promise.all([
    fetch(API+'/market-signal').then(r=>r.ok?r.json():null).catch(()=>null),
    fetch(API+'/market-signal/details').then(r=>r.ok?r.json():null).catch(()=>null),
  ]);
  if(sig){
    document.getElementById('sig-cards').innerHTML=`
      <div class="card"><h3>시장 시그널</h3><div class="val signal-${sig.signal}">${sig.signal}</div></div>
      <div class="card"><h3>종합 점수</h3><div class="val" style="color:${sig.score>0?'#3fb950':sig.score<0?'#f85149':'#d29922'}">${sig.score}</div></div>`;
  }
  if(!details){document.getElementById('sig-detail-body').innerHTML='<tr><td colspan="6" style="color:#f85149;text-align:center">로드 실패</td></tr>';return;}
  document.getElementById('sig-detail-body').innerHTML=details.map(d=>`<tr style="opacity:${d.is_enabled?1:.5}">
    <td><b>${d.key}</b></td>
    <td>${d.raw_value!=null?Number(d.raw_value).toLocaleString():'—'}</td>
    <td>${scoreBar(d.normalized_score,2)}</td>
    <td>${d.interpretation}</td>
    <td><span class="badge ${d.source==='computed'?'real':'fallback'}">${d.source}</span></td>
    <td class="ts">${d.note||''}</td>
  </tr>`).join('');
}

async function loadSources(){
  const srcs=await fetch(API+'/data-sources').then(r=>r.ok?r.json():null).catch(()=>null);
  if(!srcs){document.getElementById('src-body').innerHTML='<tr><td colspan="4" style="color:#f85149;text-align:center">로드 실패</td></tr>';return;}
  const sm={real:'real',real_with_fallback:'rfb',fallback:'fallback'};
  const lm={real:'실제',real_with_fallback:'실제(fallback가능)',fallback:'fallback'};
  document.getElementById('src-body').innerHTML=Object.entries(srcs).map(([k,v])=>`<tr>
    <td>${k}</td><td>${v.source}</td>
    <td><span class="badge ${sm[v.status]||''}">${lm[v.status]||v.status}</span></td>
    <td class="ts">${v.note||''}</td>
  </tr>`).join('');
}

async function loadLogs(){
  const logs=await fetch(API+'/jobs/logs?limit=100').then(r=>r.ok?r.json():null).catch(()=>null);
  if(!logs){document.getElementById('log-body').innerHTML='<tr><td colspan="5" style="color:#f85149;text-align:center">로드 실패</td></tr>';return;}
  document.getElementById('log-body').innerHTML=logs.map(l=>`<tr>
    <td class="ts">${l.created_at.replace('T',' ').slice(0,19)}</td>
    <td>${l.trading_date||'—'}</td>
    <td>${l.stage}</td>
    <td><span class="log-${l.status==='completed'?'ok':l.status==='started'?'run':'err'}">${l.status}</span></td>
    <td class="ts">${l.message}</td>
  </tr>`).join('');
}

async function loadBacktestSummary(){
  const d=await fetch(API+'/backtest/summary').then(r=>r.ok?r.json():null).catch(()=>null);
  if(!d||d.run_id==null){
    document.getElementById('bt-cards').innerHTML='<div class="card"><h3>백테스트 결과</h3><div class="val" style="font-size:16px;color:#8b949e">실행 기록 없음</div><div class="note">버튼을 눌러 백테스트를 실행하세요</div></div>';
    document.getElementById('bt-status').textContent='';
    return;
  }
  const m=d.metrics||{};
  const pct=v=>v!=null?(v*100).toFixed(3)+'%':'—';
  document.getElementById('bt-cards').innerHTML=`
    <div class="card"><h3>T+1 평균수익률</h3><div class="val" style="color:${(m.avg_return_1d||0)>=0?'#3fb950':'#f85149'};font-size:22px">${pct(m.avg_return_1d)}</div><div class="note">수수료·슬리피지 차감</div></div>
    <div class="card"><h3>승률</h3><div class="val" style="font-size:22px">${m.win_rate_1d!=null?(m.win_rate_1d*100).toFixed(1)+'%':'—'}</div></div>
    <div class="card"><h3>샤프 추정</h3><div class="val" style="font-size:22px">${m.sharpe_approx!=null?m.sharpe_approx.toFixed(2):'—'}</div><div class="note">연환산 근사</div></div>
    <div class="card"><h3>누적수익률</h3><div class="val" style="font-size:22px;color:${(m.cumulative_return||0)>=0?'#3fb950':'#f85149'}">${m.cumulative_return!=null?(m.cumulative_return*100).toFixed(2)+'%':'—'}</div></div>
    <div class="card"><h3>총 거래수</h3><div class="val" style="font-size:22px">${m.total_trades!=null?Math.round(m.total_trades):'—'}</div></div>
    <div class="card"><h3>분석 기간</h3><div class="val" style="font-size:14px;color:#c9d1d9">${d.period||'—'}</div></div>`;
  document.getElementById('bt-status').textContent=d.period?' ('+d.period+')':'';
}

async function runBacktest(btn){
  btn.disabled=true;btn.textContent='실행 중…';
  try{
    const r=await fetch(API+'/backtest/run?lookback_days=90',{method:'POST'});
    const d=await r.json();
    const m=d.metrics||{};
    const pct=v=>v!=null?(v*100).toFixed(3)+'%':'—';
    document.getElementById('bt-cards').innerHTML=`
      <div class="card"><h3>T+1 평균수익률</h3><div class="val" style="color:${(m.avg_return_1d||0)>=0?'#3fb950':'#f85149'};font-size:22px">${pct(m.avg_return_1d)}</div><div class="note">수수료·슬리피지 차감</div></div>
      <div class="card"><h3>승률</h3><div class="val" style="font-size:22px">${m.win_rate_1d!=null?(m.win_rate_1d*100).toFixed(1)+'%':'—'}</div></div>
      <div class="card"><h3>샤프 추정</h3><div class="val" style="font-size:22px">${m.sharpe_approx!=null?m.sharpe_approx.toFixed(2):'—'}</div><div class="note">연환산 근사</div></div>
      <div class="card"><h3>누적수익률</h3><div class="val" style="font-size:22px;color:${(m.cumulative_return||0)>=0?'#3fb950':'#f85149'}">${m.cumulative_return!=null?(m.cumulative_return*100).toFixed(2)+'%':'—'}</div></div>
      <div class="card"><h3>총 거래수</h3><div class="val" style="font-size:22px">${m.total_trades!=null?Math.round(m.total_trades):'—'}</div></div>
      <div class="card"><h3>기간</h3><div class="val" style="font-size:14px;color:#c9d1d9">${d.period||'—'}</div></div>`;
    const daily=d.daily_results||[];
    document.getElementById('bt-body').innerHTML=daily.length?daily.map(r=>`<tr>
      <td>${r.date}</td>
      <td style="color:${r.avg_return_pct>=0?'#3fb950':'#f85149'}">${r.avg_return_pct>=0?'+':''}${r.avg_return_pct}%</td>
      <td>${r.win_rate_pct}%</td>
      <td>${r.count}</td>
    </tr>`).join(''):'<tr><td colspan="4" style="color:#8b949e;text-align:center;padding:20px">추천 기록 없음 (파이프라인을 먼저 실행하세요)</td></tr>';
    document.getElementById('bt-status').textContent=' ('+d.period+')';
    showToast(`백테스트 완료: 평균수익 ${(m.avg_return_1d*100).toFixed(3)}%, 승률 ${(m.win_rate_1d*100).toFixed(1)}%`);
  }catch(e){showToast('백테스트 실패: '+e.message,true);}
  finally{btn.disabled=false;btn.textContent='▶ 백테스트 실행 (T+1)';}
}

async function showStockDetail(code, name){
  document.getElementById('modal-title').textContent=name+' ('+code+') 시그널 상세';
  document.getElementById('modal-body').innerHTML='<div style="color:#8b949e;padding:20px;text-align:center">로딩 중…</div>';
  document.getElementById('modal-bg').classList.add('show');
  const data=await fetch(API+'/stock/'+code+'/signals').then(r=>r.ok?r.json():null).catch(()=>null);
  if(!data){document.getElementById('modal-body').innerHTML='<div style="color:#f85149">데이터 없음</div>';return;}
  document.getElementById('modal-body').innerHTML=`<table>
    <thead><tr><th>지표</th><th>실측값</th><th>정규화 점수</th><th>설명</th><th>비고</th></tr></thead>
    <tbody>${data.map(d=>`<tr style="opacity:${d.is_enabled?1:.5}">
      <td><b>${d.key}</b></td>
      <td>${d.raw_value!=null?Number(d.raw_value).toLocaleString():'—'}</td>
      <td>${scoreBar(d.normalized_score,2)}</td>
      <td>${d.interpretation}</td>
      <td class="ts">${d.note||''}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}
function closeModal(){document.getElementById('modal-bg').classList.remove('show');}

async function runPipeline(btn){
  const today=new Date().toISOString().slice(0,10);
  btn.disabled=true;btn.textContent='실행 중…';
  try{
    const r=await fetch(`${API}/jobs/run-daily?trading_date=${today}`,{method:'POST'});
    const d=await r.json();
    showToast(`완료: ${d.market_signal} (${d.market_score}) / 추천 ${d.recommendation_count}종목`);
    await loadAll();
  }catch(e){showToast('실행 실패: '+e.message,true);}
  finally{btn.disabled=false;btn.textContent='▶ 파이프라인 실행';}
}

async function refreshUniverse(btn){
  btn.disabled=true;btn.textContent='갱신 중…';
  try{
    const r=await fetch(`${API}/universe/refresh`,{method:'POST'});
    const d=await r.json();
    showToast(`유니버스 갱신 완료: +${d.added}종목 추가 (총 ${d.total}종목)`);
  }catch(e){showToast('갱신 실패',true);}
  finally{btn.disabled=false;btn.textContent='↺ 유니버스 갱신';}
}

function showToast(msg,err=false){
  const t=document.getElementById('toast');
  t.textContent=msg;t.style.background=err?'#da3633':'#238636';
  t.style.display='block';setTimeout(()=>t.style.display='none',5000);
}

loadAll();
setInterval(loadAll,60000);
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


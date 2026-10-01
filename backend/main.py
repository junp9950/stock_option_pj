from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()  # .env 파일 자동 로드 (DATABASE_URL 등)

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


@app.get('/quant', response_class=HTMLResponse, include_in_schema=False)
def quant_dashboard() -> str:
    from pathlib import Path
    return (Path(__file__).parent/'views'/'quant.html').read_text(encoding='utf-8').replace('__API_PREFIX__', config.api_prefix)


@app.get('/earnings', response_class=HTMLResponse, include_in_schema=False)
def earnings_dashboard() -> str:
    from pathlib import Path
    return (Path(__file__).parent/'views'/'earnings.html').read_text(encoding='utf-8').replace('__API_PREFIX__', config.api_prefix)


@app.get('/suggestions', response_class=HTMLResponse, include_in_schema=False)
def suggestions_page() -> str:
    from pathlib import Path
    return (Path(__file__).parent/'views'/'suggestions.html').read_text(encoding='utf-8').replace('__API_PREFIX__', config.api_prefix)


@app.get('/discussion', response_class=HTMLResponse, include_in_schema=False)
def discussion_page() -> str:
    from pathlib import Path
    return (Path(__file__).parent/'views'/'discussion.html').read_text(encoding='utf-8').replace('__API_PREFIX__', config.api_prefix)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def status_dashboard() -> str:
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>눌림목 레이더</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect width=%22100%22 height=%22100%22 rx=%2222%22 fill=%22%231f6feb%22/><text x=%2250%22 y=%2270%22 font-size=%2258%22 text-anchor=%22middle%22>%F0%9F%93%88</text></svg>">
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
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.75);display:none;z-index:100;align-items:center;justify-content:center;padding:16px}
.modal-bg.show{display:flex}
.modal{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:24px;width:min(960px,100%);max-height:90vh;overflow-y:auto}
.modal h2{font-size:16px;font-weight:700;margin-bottom:16px;color:#e6edf3}
.close-btn{float:right;cursor:pointer;color:#8b949e;font-size:18px;line-height:1}.close-btn:hover{color:#e6edf3}
.modal-tabs{display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid #30363d;padding-bottom:0}
.modal-tab{padding:6px 14px;font-size:13px;color:#8b949e;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
.modal-tab.active{color:#58a6ff;border-bottom-color:#58a6ff}
.ts{color:#8b949e;font-size:11px}
.log-ok{color:#3fb950}.log-err{color:#f85149}.log-run{color:#d29922}
@media (max-width:720px){
  header{padding:12px 14px;flex-wrap:wrap;gap:8px}
  header h1{font-size:16px}
  .tabs{padding:0 6px;overflow-x:auto;-webkit-overflow-scrolling:touch}
  .tab{padding:10px 12px;white-space:nowrap;flex:0 0 auto}
  .toolbar{padding:10px 14px}
  .content{padding:14px}
  .err-bar{padding:8px 14px}
  .modal{padding:14px}
  .toast{left:14px;right:14px;bottom:14px}
  table:not(.pb-table){display:block;overflow-x:auto;white-space:nowrap}
  .pb-table,.pb-table tbody{display:block;border:none;background:transparent}
  .pb-table thead{display:none}
  .pb-table tr{display:block;background:#161b22;border:1px solid #30363d;border-radius:10px;padding:10px 12px;margin-bottom:10px}
  .pb-table td{display:block;text-align:right;padding:4px 0;border:none}
  .pb-table td:first-child{text-align:left;font-size:15px;padding-bottom:6px;margin-bottom:4px;border-bottom:1px solid #21262d}
  .pb-table td[data-label]::before{content:attr(data-label);float:left;color:#8b949e;font-size:12px}
  .pb-table td::after{content:"";display:block;clear:both}
  .pb-table tr:hover td{background:transparent}
}
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>
<header>
  <div>
    <h1>눌림목 레이더</h1>
    <div class="sub">불플래그 · 상승삼각형 · 기준봉 눌림 · 장대양봉 도지 후보를 섹터 강도 순으로 · 매일 15:41·18:00 갱신</div>
  </div>
  <div style="display:flex;gap:8px">
    <button class="btn" id="btn-run-pipeline" onclick="runPipeline()">▶ 파이프라인 실행</button>
  </div>
</header>

<div class="err-bar" id="err-bar">백엔드 연결 실패 — 서버가 실행 중인지 확인하세요</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('candidates')">차트 후보</div>
  <div class="tab" onclick="switchTab('screener')">거래대금 순위</div>
  <div class="tab" onclick="switchTab('sector')">섹터 수급</div>
  <div class="tab" onclick="switchTab('heatmap')">시장 히트맵</div>
  <div class="tab" onclick="switchTab('earnings')">실적 개선</div>
  <div class="tab" onclick="switchTab('suggest')">건의사항</div>
  <div class="tab" onclick="switchTab('discussion')">종목토론</div>
</div>

<div id="panel-earnings" class="panel"><iframe title="실적 개선" id="earnings-frame" style="width:100%;height:2200px;border:0" loading="lazy"></iframe></div>
<div id="panel-suggest" class="panel"><iframe title="건의사항" id="suggest-frame" style="width:100%;height:1600px;border:0" loading="lazy"></iframe></div>
<div id="panel-discussion" class="panel"><iframe title="종목토론" id="discussion-frame" style="width:100%;height:2000px;border:0" loading="lazy"></iframe></div>

<!-- 거래대금 순위 탭 -->
<div id="panel-screener" class="panel content">
  <div class="toolbar">
    <span id="tv-mkt" style="display:inline-flex;border:1px solid #30363d;border-radius:6px;overflow:hidden">
      <button class="btn btn-sm" data-m="KOSPI" onclick="setTvMarket('KOSPI')">코스피</button>
      <button class="btn btn-gray btn-sm" data-m="KOSDAQ" onclick="setTvMarket('KOSDAQ')">코스닥</button>
    </span>
    <select id="tv-limit" onchange="loadTopValue()">
      <option value="50">50위까지</option>
      <option value="100" selected>100위까지</option>
      <option value="200">200위까지</option>
    </select>
    <input type="text" id="tv-search" placeholder="종목명 또는 코드 검색…" oninput="renderTopValue()">
    <button class="btn btn-gray btn-sm" onclick="loadTopValue()">⟳ 새로고침</button>
    <span class="ts" id="tv-info"></span>
  </div>
  <table class="pb-table">
    <thead><tr><th>순위</th><th>종목</th><th>종가</th><th>등락률</th><th>거래대금</th><th>거래량</th><th>시총</th></tr></thead>
    <tbody id="tv-body"><tr><td colspan="7" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
  <div class="ts" style="padding:8px 16px">거래대금 = 거래량 × 종가 근사치 (정규장 기준, 시간외 제외). 종목을 누르면 차트가 열립니다.</div>
</div>

<!-- 섹터 수급 탭 -->
<div id="panel-sector" class="panel content">
  <div class="toolbar" style="margin-bottom:12px">
    <select id="sec-sort" onchange="loadSector()">
      <option value="stealth">스텔스 매집순</option>
      <option value="flow">수급 점수순</option>
      <option value="foreign">외국인 순매수순</option>
      <option value="inst">기관 순매수순</option>
    </select>
    <select id="sec-source" onchange="loadSector()">
      <option value="">전체</option>
      <option value="custom">커스텀</option>
      <option value="naver_theme">네이버 테마</option>
    </select>
    <button class="btn btn-gray btn-sm" onclick="loadSector()">⟳ 새로고침</button>
    <button class="btn btn-gray btn-sm" onclick="refreshSectorMapping()">↺ 매핑 갱신</button>
    <span class="ts" id="sec-info"></span>
  </div>

  <!-- 매집 감지 섹터 -->
  <div style="margin-bottom:20px">
    <div style="font-size:12px;text-transform:uppercase;color:#8b949e;margin-bottom:8px;letter-spacing:.06em">🕵️ 매집 감지 섹터 (수급↑ 주가↔)</div>
    <table id="sec-stealth-table">
      <thead><tr>
        <th>섹터</th><th>분류</th>
        <th onclick="setSectorSort('foreign')" style="cursor:pointer">외국인</th>
        <th onclick="setSectorSort('inst')" style="cursor:pointer">기관</th>
        <th>합산</th>
        <th>평균등락</th>
        <th>연속일</th>
        <th onclick="setSectorSort('stealth')" style="cursor:pointer">스텔스점수 ↕</th>
      </tr></thead>
      <tbody id="sec-stealth-body"><tr><td colspan="8" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
    </table>
  </div>

  <!-- 전체 섹터 수급 랭킹 -->
  <div>
    <div style="font-size:12px;text-transform:uppercase;color:#8b949e;margin-bottom:8px;letter-spacing:.06em">📊 전체 섹터 수급 랭킹 (flow_score 순)</div>
    <table id="sec-surged-table">
      <thead><tr>
        <th>섹터</th><th>분류</th><th>외국인</th><th>기관</th><th>합산</th><th>평균등락</th><th>수급점수</th><th>상태</th>
      </tr></thead>
      <tbody id="sec-surged-body"><tr><td colspan="8" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
    </table>
  </div>

  <!-- 섹터 종목 모달 -->
  <div class="modal-bg" id="sector-modal-bg" onclick="if(event.target===this)closeSectorModal()">
    <div class="modal">
      <span class="close-btn" onclick="closeSectorModal()">✕</span>
      <h2 id="sector-modal-title">섹터 소속 종목</h2>
      <div id="sector-modal-body"></div>
    </div>
  </div>
</div>

<!-- 시장 히트맵 탭 -->
<div id="panel-heatmap" class="panel content">
  <div class="toolbar" style="margin-bottom:12px">
    <select id="hm-market" onchange="loadHeatmap()">
      <option value="">전체 시장</option>
      <option value="KOSPI">KOSPI</option>
      <option value="KOSDAQ">KOSDAQ</option>
    </select>
    <select id="hm-limit" onchange="loadHeatmap()">
      <option value="150">시총 상위 150</option>
      <option value="250" selected>시총 상위 250</option>
      <option value="500">시총 상위 500</option>
    </select>
    <button class="btn btn-gray btn-sm" onclick="loadHeatmap()">⟳ 새로고침</button>
    <span class="ts" id="hm-info"></span>
  </div>
  <div id="heatmap-container" style="position:relative;width:100%;height:640px;background:#000;border-radius:8px;overflow:hidden"></div>
  <div id="heatmap-legend" style="display:flex;margin-top:10px;border-radius:6px;overflow:hidden;font-size:12px"></div>
</div>

<!-- 눌림목 레이더 탭 -->
<div id="panel-candidates" class="panel active content">
  <div id="pb-market" hidden style="border-radius:10px;padding:12px 16px;margin-bottom:14px;border:1px solid #30363d"></div>
  <p class="note" style="color:#8b949e;font-size:12.5px;margin:0 0 12px">
    원하는 모양(<b style="color:#c9d1d9">불플래그</b> · <b style="color:#c9d1d9">상승삼각형</b> · <b style="color:#c9d1d9">기준봉 눌림</b> · <b style="color:#c9d1d9">장대양봉 도지</b>) 중 하나라도 해당하는 종목을 <b style="color:#c9d1d9">섹터 점수</b> 순으로 보여줍니다.
    섹터 점수(0~100)는 종목의 <b style="color:#c9d1d9">대표 테마</b>(네이버 테마 중 최근 60일 주가가 가장 비슷하게 움직인 테마)의 최근 20일 수익률 순위이고, <b style="color:#3fb950">80점 이상이 강한 섹터</b>입니다.
    3년 백테스트에서 <b>강한 대표 테마 + 차트 후보</b>는 탐색·검증 두 기간 모두 같은 날 아무 종목보다 20일 평균 +1.4~1.6%p 높았습니다(상승삼각형이 가장 일관, 중간값은 마이너스).
    손절선까지 거리는 <b style="color:#3fb950">3~6%가 적정</b>입니다(같은 백테스트에서 종가 매수 기준 두 기간 모두 최고, 3% 미만은 흔들림에 거의 다 털려 마이너스, 10% 이상도 부진).
    <b style="color:#e3b341">★</b>는 강한 섹터 + 손절 3~6%로 두 기간 모두 가장 좋았던 조합입니다. 점수는 <b>먼저 볼 순서</b>이지 오를 확률이 아닙니다. 종목을 누르면 차트가 열립니다.
  </p>
  <div class="toolbar" style="margin-bottom:12px">
    <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#8b949e">
      최소 시가총액(억원)
      <input type="number" id="cd-min-cap" value="0" min="0" step="100" onchange="loadCandidates()"
             style="width:90px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px">
    </label>
    <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#c9d1d9;cursor:pointer">
      <input type="checkbox" id="cd-strong" onchange="renderCandidates()"> 강한 섹터만 (80+)
    </label>
    <select id="cd-pattern" onchange="renderCandidates()">
      <option value="">모든 모양</option>
      <option value="불플래그">불플래그</option>
      <option value="상승삼각형">상승삼각형</option>
      <option value="기준봉 눌림">기준봉 눌림</option>
      <option value="장대양봉 도지">장대양봉 도지</option>
    </select>
    <button class="btn btn-gray btn-sm" onclick="loadCandidates()">⟳ 새로고침</button>
    <span class="ts" id="cd-info"></span>
  </div>
  <table class="pb-table">
    <thead><tr>
      <th>종목</th><th>섹터 점수</th><th>모양</th><th>현재가</th><th>손절선</th>
    </tr></thead>
    <tbody id="cd-body"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
</div>

<!-- 캔들차트 모달 (토스증권 실시간) -->
<div class="modal-bg" id="chart-modal-bg" onclick="if(event.target===this)closeChartModal()">
  <div class="modal">
    <span class="close-btn" onclick="closeChartModal()">✕</span>
    <h2 id="chart-modal-title">종목 차트</h2>
    <div class="note" id="chart-modal-note" style="margin-bottom:8px"></div>
    <canvas id="pb-candle-canvas" style="width:100%;height:340px;display:block"></canvas>
    <canvas id="pb-volume-canvas" style="width:100%;height:100px;display:block;margin-top:4px"></canvas>
  </div>
</div>

<!-- 종목 상세 모달 -->
<div class="modal-bg" id="modal-bg" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <span class="close-btn" onclick="closeModal()">✕</span>
    <h2 id="modal-title">종목 시그널 상세</h2>
    <div class="modal-tabs">
      <div class="modal-tab active" onclick="switchModalTab('chart',this)">차트</div>
      <div class="modal-tab" onclick="switchModalTab('flow',this)">수급 히스토리</div>
      <div class="modal-tab" onclick="switchModalTab('signal',this)">시그널 상세</div>
    </div>
    <!-- 차트 탭 -->
    <div id="modal-chart-tab">
      <div style="position:relative;margin-bottom:8px">
        <canvas id="modal-price-chart" style="max-height:220px"></canvas>
      </div>
      <div style="position:relative">
        <canvas id="modal-volume-chart" style="max-height:80px"></canvas>
      </div>
      <div id="modal-chart-info" style="display:flex;gap:16px;margin-top:12px;flex-wrap:wrap"></div>
    </div>
    <!-- 수급 히스토리 탭 -->
    <div id="modal-flow-tab" style="display:none">
      <div id="modal-flow-body"></div>
    </div>
    <!-- 시그널 탭 -->
    <div id="modal-signal-tab" style="display:none">
      <div id="modal-body"></div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = window.location.origin + '/api';

const fmt = n => { if(n==null)return '—'; const a=Math.abs(n); const s=n<0?'-':'+'; if(a>=1e12)return s+(a/1e12).toFixed(1)+'조'; if(a>=1e8)return s+(a/1e8).toFixed(0)+'억'; if(a>=1e4)return s+(a/1e4).toFixed(0)+'만'; return n===0?'—':s+a.toFixed(0); };
const fmtP = n => n==null?'—':(n>=0?'+':'')+n.toFixed(2)+'%';
const fmtKrw = n => n==null?'—':Number(n).toLocaleString()+'원';
const scoreBar = (s,max=3) => {const w=Math.min(Math.abs(s)/max*60,60);return `<span class="${s<0?'neg':''}" style="display:inline-flex;align-items:center"><b style="color:${s>0?'#58a6ff':s<0?'#f85149':'#8b949e'}">${s.toFixed(2)}</b><span class="score-bar" style="width:${w}px;background:${s>0?'#58a6ff':s<0?'#f85149':'#444'}"></span></span>`;};
const trustPct = score => { const pct = Math.min(100, Math.max(0, Math.round((score/3)*100))); const color = pct>=70?'#3fb950':pct>=40?'#58a6ff':'#d29922'; return `<span style="color:${color};font-weight:700">${pct}%</span>`; };
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
  const tabs = ['candidates','screener','sector','heatmap','earnings','suggest','discussion'];
  if(!tabs.includes(id))return;
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',tabs[i]===id));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+id).classList.add('active');
  if(id==='screener')loadTopValue();
  if(id==='sector')loadSector();
  if(id==='heatmap')loadHeatmap();
  if(id==='candidates')loadCandidates();
  if(id==='earnings'&&!document.getElementById('earnings-frame').src)document.getElementById('earnings-frame').src='/earnings';
  if(id==='suggest')document.getElementById('suggest-frame').src='/suggestions';
  if(id==='discussion'&&!document.getElementById('discussion-frame').src)document.getElementById('discussion-frame').src='/discussion';
}

// ── 섹터 수급 ──────────────────────────────────────────────────
let _sectorData = [];
function setSectorSort(s){document.getElementById('sec-sort').value=s;loadSector();}

async function loadSector(){
  const sort=document.getElementById('sec-sort').value;
  const source=document.getElementById('sec-source').value;
  try{
    const data=await fetch(`${API}/sectors/flow?sort=${sort}${source?`&source=${source}`:''}&limit=300`).then(r=>r.ok?r.json():[]);
    _sectorData=data;
    renderSector(data);
    document.getElementById('sec-info').textContent=data.length?`기준일: ${data[0].date}`:'';
  }catch(e){console.error(e);}
}

function renderSector(data){
  const stealth=data.filter(d=>d.combined_net_buy>0&&!d.is_surged).sort((a,b)=>b.stealth_score-a.stealth_score);
  const surged=[...data].sort((a,b)=>b.flow_score-a.flow_score);

  const srcBadge=s=>({custom:'<span class="badge real">커스텀</span>',naver_theme:'<span class="badge rfb">네이버</span>'}[s]||s);
  const fmtBil=n=>n==null?'—':(n>=0?'<span style="color:#3fb950">':' <span style="color:#58a6ff">')+((n>=0?'+':'')+Math.round(n/1e8))+'억</span>';
  const chgColor=n=>n>0?'#3fb950':n<0?'#f85149':'#8b949e';
  const scoreBar10=s=>{const w=Math.min(s/10*80,80);const c=s>=7?'#3fb950':s>=4?'#58a6ff':'#d29922';return `<span style="display:inline-flex;align-items:center;gap:4px"><b style="color:${c}">${s.toFixed(1)}</b><span style="display:inline-block;width:${w}px;height:5px;border-radius:3px;background:${c}"></span></span>`;};

  const sRow=(d,showStealth)=>`<tr style="cursor:pointer" onclick="openSectorModal(${d.sector_id},'${d.sector_name}')">
    <td><b>${d.sector_name}</b>${d.buy_streak>1?` <span style="color:#d29922;font-size:11px">${d.buy_streak}일연속</span>`:''}</td>
    <td>${srcBadge(d.source)}</td>
    <td>${fmtBil(d.foreign_net_buy)}</td>
    <td>${fmtBil(d.inst_net_buy)}</td>
    <td>${fmtBil(d.combined_net_buy)}</td>
    <td style="color:${chgColor(d.avg_change_pct)}">${d.avg_change_pct>=0?'+':''}${d.avg_change_pct.toFixed(2)}%</td>
    ${showStealth
      ?`<td>${d.buy_streak}</td><td>${scoreBar10(d.stealth_score)}</td>`
      :`<td>${scoreBar10(d.flow_score)}</td><td>${d.is_surged?'<span style="color:#d29922;font-size:11px">⚠️ 추격주의</span>':d.combined_net_buy>0?'<span style="color:#3fb950;font-size:11px">✅ 순매수</span>':'<span style="color:#f85149;font-size:11px">📉 순매도</span>'}</td>`
    }
  </tr>`;

  document.getElementById('sec-stealth-body').innerHTML=stealth.length
    ?stealth.slice(0,10).map(d=>sRow(d,true)).join('')
    :'<tr><td colspan="8" style="color:#8b949e;text-align:center;padding:16px">매집 감지 섹터 없음</td></tr>';

  document.getElementById('sec-surged-body').innerHTML=surged.length
    ?surged.map(d=>sRow(d,false)).join('')
    :'<tr><td colspan="8" style="color:#8b949e;text-align:center;padding:16px">섹터 데이터 없음</td></tr>';
}

async function openSectorModal(sectorId, name){
  document.getElementById('sector-modal-title').textContent=name+' 소속 종목';
  document.getElementById('sector-modal-body').innerHTML='<div style="color:#8b949e;text-align:center;padding:20px">로딩 중…</div>';
  document.getElementById('sector-modal-bg').classList.add('show');
  try{
    const stocks=await fetch(`${API}/sectors/${sectorId}/stocks`).then(r=>r.ok?r.json():[]);
    const fmtBil=n=>(n>=0?'<span style="color:#3fb950">+':' <span style="color:#58a6ff">')+Math.round(n/1e8)+'억</span>';
    const rows=stocks.map(s=>`<tr>
      <td>${s.stock_code}</td><td>${s.stock_name}</td><td style="color:#8b949e">${s.market}</td>
      <td>${fmtBil(s.foreign_net_buy)}</td><td>${fmtBil(s.inst_net_buy)}</td>
      <td style="color:${s.change_pct>0?'#3fb950':s.change_pct<0?'#f85149':'#8b949e'}">${s.change_pct>=0?'+':''}${s.change_pct.toFixed(2)}%</td>
      <td>${Number(s.close_price).toLocaleString()}원</td>
    </tr>`).join('');
    document.getElementById('sector-modal-body').innerHTML=`<table>
      <thead><tr><th>코드</th><th>종목명</th><th>시장</th><th>외국인</th><th>기관</th><th>등락</th><th>종가</th></tr></thead>
      <tbody>${rows||'<tr><td colspan="7" style="color:#8b949e;text-align:center">데이터 없음</td></tr>'}</tbody>
    </table>`;
  }catch(e){document.getElementById('sector-modal-body').innerHTML='<div style="color:#f85149;padding:16px">오류 발생</div>';}
}
function closeSectorModal(){document.getElementById('sector-modal-bg').classList.remove('show');}

async function refreshSectorMapping(){
  if(!confirm('섹터 매핑(커스텀 + 네이버 테마 264개)을 갱신합니다. 네이버 테마를 받느라 3~5분 걸립니다. 계속할까요?'))return;
  document.getElementById('sec-info').textContent='갱신 중…';
  try{
    const r=await fetch(`${API}/sectors/refresh`,{method:'POST'}).then(res=>res.json());
    document.getElementById('sec-info').textContent=`갱신 완료: 추가 ${r.added} 업데이트 ${r.updated}`;
    loadSector();
  }catch(e){document.getElementById('sec-info').textContent='갱신 실패';}
}

// ── 시장 히트맵(트리맵) ────────────────────────────────────────
function hmColor(pct){
  const stops = [
    [-3, [30,58,95]], [-1, [45,60,90]], [0, [50,55,65]],
    [1, [90,45,45]], [2, [140,35,35]], [3.5, [200,30,30]],
  ];
  const p = Math.max(-3.5, Math.min(3.5, pct));
  let lo = stops[0], hi = stops[stops.length-1];
  for(let i=0;i<stops.length-1;i++){
    if(p>=stops[i][0] && p<=stops[i+1][0]){ lo=stops[i]; hi=stops[i+1]; break; }
  }
  const range = hi[0]-lo[0] || 1;
  const t = (p-lo[0])/range;
  const c = lo[1].map((v,i)=>Math.round(v+(hi[1][i]-v)*t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

// 표준 squarified treemap 알고리즘 (Bruls et al.) — 종횡비가 고른 사각형을 만들어줌
function squarify(items, x, y, w, h){
  const result = [];
  const total = items.reduce((s,i)=>s+i.value, 0);
  if (!total || !items.length) return result;
  const scale = (w*h)/total;
  const sorted = [...items].sort((a,b)=>b.value-a.value).map(i=>({...i, area: i.value*scale}));

  function layoutRow(row, x, y, w, h, vertical){
    const rowTotal = row.reduce((s,i)=>s+i.area, 0);
    let offset = vertical ? x : y;
    row.forEach(item=>{
      const size = rowTotal>0 ? item.area/rowTotal : 0;
      if (vertical){
        const rw = (h>0)? item.area/h : 0;
        result.push({...item, x: offset, y, w: rw, h});
        offset += rw;
      } else {
        const rh = (w>0)? item.area/w : 0;
        result.push({...item, x, y: offset, w, h: rh});
        offset += rh;
      }
    });
  }

  function worstRatio(row, sideLen){
    const sum = row.reduce((s,i)=>s+i.area,0);
    if (sum===0) return Infinity;
    const maxA = Math.max(...row.map(i=>i.area));
    const minA = Math.min(...row.map(i=>i.area));
    return Math.max((sideLen*sideLen*maxA)/(sum*sum), (sum*sum)/(sideLen*sideLen*minA));
  }

  let remaining = sorted, rx=x, ry=y, rw=w, rh=h;
  while(remaining.length){
    const vertical = rw < rh;
    const sideLen = vertical ? rh : rw;
    let row = [remaining[0]];
    let i = 1;
    while(i < remaining.length){
      const next = [...row, remaining[i]];
      if (worstRatio(next, sideLen) <= worstRatio(row, sideLen)) { row = next; i++; }
      else break;
    }
    const rowArea = row.reduce((s,it)=>s+it.area,0);
    if (vertical){
      const rowW = sideLen>0 ? rowArea/sideLen : 0;
      layoutRow(row, rx, ry, rowW, rh, false);
      rx += rowW; rw -= rowW;
    } else {
      const rowH = sideLen>0 ? rowArea/sideLen : 0;
      layoutRow(row, rx, ry, rw, rowH, true);
      ry += rowH; rh -= rowH;
    }
    remaining = remaining.slice(row.length);
  }
  return result;
}

async function loadHeatmap(){
  const market = document.getElementById('hm-market').value;
  const limit = document.getElementById('hm-limit').value;
  const box = document.getElementById('heatmap-container');
  box.innerHTML = '<div style="color:#8b949e;text-align:center;padding:40px">로딩 중…</div>';
  try{
    const data = await fetch(`${API}/heatmap?limit=${limit}`).then(r=>r.ok?r.json():null);
    if(!data || !data.items || !data.items.length){
      box.innerHTML = '<div style="color:#8b949e;text-align:center;padding:40px">데이터 없음</div>';
      return;
    }
    let items = data.items;
    if (market) items = items.filter(i=>i.market===market);
    document.getElementById('hm-info').textContent = `기준일: ${data.trading_date} · ${items.length}개 종목`;
    renderHeatmap(items, box);
    renderHeatmapLegend();
  }catch(e){
    console.error(e);
    box.innerHTML = '<div style="color:#f85149;text-align:center;padding:40px">로딩 실패</div>';
  }
}

function renderHeatmap(items, box){
  const W = box.clientWidth || 1200, H = box.clientHeight || 640;
  const bySector = {};
  items.forEach(it=>{ (bySector[it.sector] = bySector[it.sector] || []).push(it); });
  const sectorItems = Object.entries(bySector).map(([name, stocks])=>({
    name, stocks, value: stocks.reduce((s,x)=>s+x.market_cap, 0),
  }));
  const sectorRects = squarify(sectorItems, 0, 0, W, H);

  let html = '';
  sectorRects.forEach(sec=>{
    if (sec.w < 1 || sec.h < 1) return;
    const headH = sec.h > 40 ? 18 : 0;
    html += `<div style="position:absolute;left:${sec.x}px;top:${sec.y}px;width:${sec.w}px;height:${sec.h}px;border:1px solid #000;box-sizing:border-box;overflow:hidden;background:#161b22">`;
    if (headH) html += `<div style="height:${headH}px;line-height:${headH}px;font-size:11px;color:#c9d1d9;text-align:center;background:#21262d;overflow:hidden;white-space:nowrap">${sec.name}</div>`;
    const stockRects = squarify(sec.stocks.map(s=>({...s, value: s.market_cap})), 0, 0, sec.w, sec.h - headH);
    stockRects.forEach(st=>{
      if (st.w < 1 || st.h < 1) return;
      const showText = st.w > 40 && st.h > 24;
      const big = st.w > 90 && st.h > 60;
      html += `<div title="${st.name} ${st.change_pct>=0?'+':''}${st.change_pct.toFixed(2)}%"
        style="position:absolute;left:${st.x}px;top:${st.y+headH}px;width:${st.w}px;height:${st.h}px;background:${hmColor(st.change_pct)};border:1px solid #000;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:hidden;cursor:pointer"
        onclick="showStockDetail('${st.code}','${st.name}')">
        ${showText ? `<div style="color:#fff;font-weight:${big?'800':'600'};font-size:${big?'15px':'11px'};text-shadow:0 1px 2px #000;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:95%">${st.name}</div>
        <div style="color:#fff;font-size:${big?'13px':'10px'};text-shadow:0 1px 2px #000">${st.change_pct>=0?'+':''}${st.change_pct.toFixed(2)}%</div>` : ''}
      </div>`;
    });
    html += '</div>';
  });
  box.innerHTML = html;
}

function renderHeatmapLegend(){
  const steps = [-3,-2,-1,0,1,2,3];
  const html = steps.map(s=>`<div style="flex:1;text-align:center;padding:6px 0;background:${hmColor(s)};color:#fff;font-weight:600">${s>0?'+':''}${s}%</div>`).join('');
  document.getElementById('heatmap-legend').innerHTML = html;
}

// ── 눌림목 스캐너 ──────────────────────────────────────────────
// ── 차트 후보 ─────────────────────────────────────────────────
let _cdData = null;
async function loadCandidates(){
  const body = document.getElementById('cd-body');
  body.innerHTML = '<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr>';
  try{
    const cap = parseFloat(document.getElementById('cd-min-cap').value) || 0;
    _cdData = await fetch(`${API}/screener/chart-candidates?min_cap=${cap}`).then(r=>r.ok?r.json():null);
    renderMarket(_cdData && _cdData.market);
    renderCandidates();
  }catch(e){
    console.error(e);
    body.innerHTML = '<tr><td colspan="5" style="color:#f85149;text-align:center;padding:20px">로딩 실패</td></tr>';
  }
}

function renderCandidates(){
  const body = document.getElementById('cd-body');
  const d = _cdData;
  if(!d){ return; }
  const strong = document.getElementById('cd-strong').checked;
  const pat = document.getElementById('cd-pattern').value;
  const items = d.items
    .filter(it=>(!strong||it.strong_sector) && (!pat||it.patterns.some(p=>p.type===pat)));
  const nStrong = d.items.filter(x=>x.strong_sector).length;
  const nBest = d.items.filter(x=>x.best_combo).length;
  document.getElementById('cd-info').textContent = d.trading_date ? `기준일: ${d.trading_date} · ${d.items.length}개 (강한 섹터 ${nStrong}개 · ★ ${nBest}개)` : '';
  if(!items.length){
    body.innerHTML = '<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">조건에 맞는 종목이 없습니다</td></tr>';
    return;
  }
  const tagColor = {'불플래그':'#58a6ff','상승삼각형':'#bc8cff','기준봉 눌림':'#d29922','장대양봉 도지':'#3fb950'};
  body.innerHTML = items.map(it=>{
    const sc = it.sector_score;
    const scHtml = sc==null ? '<span class="ts">테마 없음</span>'
      : `<b style="font-size:16px;color:${sc>=80?'#3fb950':sc>=50?'#c9d1d9':'#8b949e'}">${sc}</b><br><span class="ts">${it.sector_name} · 20일 ${it.sector_ret20>=0?'+':''}${it.sector_ret20}%</span>`;
    const pats = it.patterns.map(p=>`<span style="display:inline-block;margin:0 4px 3px 0;padding:1px 7px;border-radius:10px;border:1px solid ${tagColor[p.type]};color:${tagColor[p.type]};font-size:11.5px">${p.type}${p.grade?'·'+p.grade:''}</span><br><span class="ts">${p.detail}</span>`).join('<br>');
    return `<tr style="cursor:pointer" onclick="openChartModal('${it.code}','${it.name}','')">
      <td>${it.best_combo?'<b style="color:#e3b341">★</b> ':''}<b>${it.name}</b> <span style="color:#8b949e;font-size:11px">${it.code}</span></td>
      <td data-label="섹터 점수">${scHtml}</td>
      <td data-label="모양" style="font-size:12px">${pats}</td>
      <td data-label="현재가" style="text-align:right">${it.close_price.toLocaleString()}원<br><span style="color:${it.change_pct>=0?'#f85149':'#3b82f6'};font-size:11px">${it.change_pct>=0?'+':''}${it.change_pct.toFixed(2)}%</span></td>
      <td data-label="손절선" style="color:#f85149">${it.stop_price?it.stop_price.toLocaleString()+'원<br><span style="font-size:11px;color:'+({적정:'#3fb950',보통:'#c9d1d9',얕음:'#8b949e',깊음:'#8b949e'}[it.stop_zone])+'">-'+it.stop_dist_pct+'% · '+it.stop_zone+'</span>':'—'}</td>
    </tr>`;
  }).join('');
}

function renderMarket(m){
  const el = document.getElementById('pb-market');
  if(!m){ el.hidden = true; return; }
  const style = {
    '상승': {bg:'rgba(63,185,80,.10)', bd:'#3fb950', msg:'매매 가능'},
    '횡보': {bg:'rgba(210,153,34,.10)', bd:'#d29922', msg:'매매 가능 · 점수 높은 종목 위주'},
    '하락': {bg:'rgba(248,81,73,.12)', bd:'#f85149', msg:'매매 쉬기'},
  }[m.state];
  el.style.background = style.bg;
  el.style.borderColor = style.bd;
  const sign = n => (n>=0?'+':'')+n.toFixed(1)+'%';
  el.innerHTML = `<b style="color:${style.bd};font-size:15px">시장 ${m.state}</b>
    <span style="color:#e6edf3;margin-left:8px">${style.msg}</span>
    <div class="ts" style="margin-top:4px">전종목 평균 지수 · 20일선 대비 ${sign(m.vs_ma20_pct)} · 최근 20일 ${sign(m.cum20_pct)} · ${m.as_of} 마감 기준</div>`;
  el.hidden = false;
}

async function openChartModal(code, name, spikeDate){
  document.getElementById('chart-modal-title').textContent = `${name} (${code}) — 토스증권 실시간 일봉`;
  document.getElementById('chart-modal-note').textContent = '로딩 중…';
  document.getElementById('chart-modal-bg').classList.add('show');
  try{
    const data = await fetch(`${API}/toss/candles/${code}?interval=1d&count=90`).then(r=>r.ok?r.json():null);
    if(!data || !data.candles || !data.candles.length){
      document.getElementById('chart-modal-note').textContent = '토스 API에서 차트 데이터를 가져오지 못했습니다.';
      return;
    }
    document.getElementById('chart-modal-note').textContent = spikeDate ? `스파이크일: ${spikeDate}` : `최근 90거래일 일봉`;
    drawCandleChart(data.candles, spikeDate);
  }catch(e){
    console.error(e);
    document.getElementById('chart-modal-note').textContent = '차트 로딩 실패';
  }
}
function closeChartModal(){ document.getElementById('chart-modal-bg').classList.remove('show'); }

// 외부 라이브러리 없이 순수 canvas로 캔들차트 + 거래량 + 눌림목 지지선 그리기
function drawCandleChart(candles, spikeDate){
  const cvCandle = document.getElementById('pb-candle-canvas');
  const cvVol = document.getElementById('pb-volume-canvas');
  const dpr = window.devicePixelRatio || 1;
  const W = cvCandle.clientWidth || 760;
  [[cvCandle,340],[cvVol,100]].forEach(([cv,h])=>{ cv.width=W*dpr; cv.height=h*dpr; });

  const ctxC = cvCandle.getContext('2d'); ctxC.scale(dpr,dpr);
  const ctxV = cvVol.getContext('2d'); ctxV.scale(dpr,dpr);
  const H = 340, HV = 100;
  ctxC.clearRect(0,0,W,H); ctxV.clearRect(0,0,W,HV);
  ctxC.fillStyle = '#0d1117'; ctxC.fillRect(0,0,W,H);
  ctxV.fillStyle = '#0d1117'; ctxV.fillRect(0,0,W,HV);

  const n = candles.length;
  const cw = W/n, bw = Math.max(1, cw*0.6);
  const lows = candles.map(c=>+c.lowPrice), highs = candles.map(c=>+c.highPrice);
  const minP = Math.min(...lows), maxP = Math.max(...highs);
  const pad = (maxP-minP)*0.06 || 1;
  const yP = p => H - 10 - (p-(minP-pad))/((maxP+pad)-(minP-pad))*(H-20);
  const maxV = Math.max(...candles.map(c=>+c.volume), 1);
  const yV = v => HV - 4 - (v/maxV)*(HV-8);

  const UP='#f85149', DOWN='#3b82f6'; // 국내 관례: 상승=빨강, 하락=파랑
  let spikeIdx = -1, spikeLow = null;
  candles.forEach((c,i)=>{
    const dateStr = (c.timestamp||'').slice(0,10);
    if (dateStr === spikeDate) { spikeIdx = i; spikeLow = +c.lowPrice; }
  });

  candles.forEach((c,i)=>{
    const x = i*cw + cw/2;
    const o=+c.openPrice, h=+c.highPrice, l=+c.lowPrice, cl=+c.closePrice, v=+c.volume;
    const up = cl >= o;
    const color = up ? UP : DOWN;
    ctxC.strokeStyle = color; ctxC.fillStyle = color;
    ctxC.beginPath(); ctxC.moveTo(x, yP(h)); ctxC.lineTo(x, yP(l)); ctxC.stroke();
    const bodyTop = yP(Math.max(o,cl)), bodyBot = yP(Math.min(o,cl));
    ctxC.fillRect(x-bw/2, bodyTop, bw, Math.max(1, bodyBot-bodyTop));
    if (i === spikeIdx){
      ctxC.strokeStyle = '#d29922'; ctxC.lineWidth = 2;
      ctxC.strokeRect(x-bw/2-2, bodyTop-2, bw+4, Math.max(1,bodyBot-bodyTop)+4);
      ctxC.lineWidth = 1;
    }
    ctxV.fillStyle = color;
    ctxV.fillRect(x-bw/2, yV(v), bw, HV-4-yV(v));
  });

  // 눌림목 지지선: 스파이크 저가 -> 최근 저점을 잇는 완만한 상승 트렌드라인(참고용 근사치)
  if (spikeIdx >= 0 && spikeIdx < n-1){
    const after = candles.slice(spikeIdx);
    let minIdx = spikeIdx;
    after.forEach((c,off)=>{ if(+c.lowPrice < +candles[minIdx].lowPrice) minIdx = spikeIdx+off; });
    const x1 = spikeIdx*cw+cw/2, y1 = yP(spikeLow);
    const x2 = (n-1)*cw+cw/2, y2 = yP(Math.min(+candles[n-1].lowPrice, spikeLow));
    ctxC.strokeStyle = '#58a6ff'; ctxC.setLineDash([4,3]);
    ctxC.beginPath(); ctxC.moveTo(x1,y1); ctxC.lineTo(x2, Math.min(y1,y2)); ctxC.stroke();
    ctxC.setLineDash([]);
  }
}

async function runPipeline(){
  const btn=document.getElementById('btn-run-pipeline');
  btn.disabled=true;btn.textContent='실행 중…';
  try{
    const r=await fetch(`${API}/jobs/run-daily`,{method:'POST'}).then(res=>res.json());
    btn.textContent='▶ 파이프라인 실행';btn.disabled=false;
    showToast(`완료: ${r.trading_date} 시그널=${r.market_signal} 종목=${r.stock_signal_count}`);
    loadCandidates();
  }catch(e){
    btn.textContent='▶ 파이프라인 실행';btn.disabled=false;
    showToast('파이프라인 실행 실패');
  }
}

// ── 거래대금 순위 ──────────────────────────────────────────
let tvMarket = 'KOSPI', tvData = null;
function setTvMarket(m){
  tvMarket = m;
  document.querySelectorAll('#tv-mkt button').forEach(b=>b.className='btn btn-sm'+(b.dataset.m===m?'':' btn-gray'));
  loadTopValue();
}
async function loadTopValue(){
  const body = document.getElementById('tv-body');
  body.innerHTML = '<tr><td colspan="7" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr>';
  try{
    const limit = document.getElementById('tv-limit').value;
    tvData = await fetch(`${API}/screener/top-value?market=${tvMarket}&limit=${limit}`).then(r=>r.ok?r.json():null);
    renderTopValue();
  }catch(e){
    body.innerHTML = '<tr><td colspan="7" style="color:#f85149;text-align:center;padding:20px">로딩 실패</td></tr>';
  }
}
function renderTopValue(){
  const body = document.getElementById('tv-body');
  if(!tvData){ body.innerHTML = '<tr><td colspan="7" style="color:#f85149;text-align:center;padding:20px">데이터 없음</td></tr>'; return; }
  const q = (document.getElementById('tv-search').value||'').trim().toLowerCase();
  const rows = tvData.items.filter(it=>!q || it.name.toLowerCase().includes(q) || it.code.includes(q));
  document.getElementById('tv-info').textContent = `기준일: ${tvData.trading_date} · ${tvMarket==='KOSPI'?'코스피':'코스닥'} 거래대금 상위 ${tvData.items.length}종목`;
  if(!rows.length){ body.innerHTML = '<tr><td colspan="7" style="color:#8b949e;text-align:center;padding:20px">검색 결과 없음</td></tr>'; return; }
  const won = v=>v>=1e12?(v/1e12).toFixed(2)+'조':Math.round(v/1e8).toLocaleString()+'억';
  body.innerHTML = rows.map(it=>{
    const c = it.change_pct>0?'#f85149':it.change_pct<0?'#58a6ff':'#c9d1d9';
    const nm = it.name.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
    return `<tr style="cursor:pointer" data-code="${it.code}" data-name="${nm}" onclick="openChartModal(this.dataset.code,this.dataset.name,'')">
      <td>${it.rank}</td>
      <td><b>${nm}</b> <span style="color:#8b949e;font-size:11px">${it.code}</span></td>
      <td>${Math.round(it.close_price).toLocaleString()}</td>
      <td style="color:${c}">${it.change_pct>0?'+':''}${it.change_pct.toFixed(2)}%</td>
      <td><b>${won(it.trading_value)}</b></td>
      <td>${Math.round(it.volume).toLocaleString()}</td>
      <td>${it.market_cap?won(it.market_cap):'—'}</td>
    </tr>`;}).join('');
}

// 모달 차트 인스턴스
let _modalPriceChart = null, _modalVolumeChart = null;

function switchModalTab(tab, el){
  document.querySelectorAll('.modal-tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('modal-chart-tab').style.display = tab==='chart'?'':'none';
  document.getElementById('modal-flow-tab').style.display = tab==='flow'?'':'none';
  document.getElementById('modal-signal-tab').style.display = tab==='signal'?'':'none';
}

async function showStockDetail(code, name){
  document.getElementById('modal-title').textContent = name + ' (' + code + ')';
  document.getElementById('modal-bg').classList.add('show');
  document.getElementById('modal-body').innerHTML = '<div style="color:#8b949e;padding:20px;text-align:center">로딩 중…</div>';
  document.getElementById('modal-chart-info').innerHTML = '<div style="color:#8b949e;font-size:13px">차트 로딩 중…</div>';

  // 차트 탭 기본 활성화
  document.querySelectorAll('.modal-tab').forEach((t,i)=>t.classList.toggle('active',i===0));
  document.getElementById('modal-chart-tab').style.display='';
  document.getElementById('modal-flow-tab').style.display='none';
  document.getElementById('modal-signal-tab').style.display='none';

  const [data, hist, priceHist, flowHist] = await Promise.all([
    fetch(API+'/stock/'+code+'/signals').then(r=>r.ok?r.json():null).catch(()=>null),
    fetch(API+'/stock/'+code+'/history?limit=60').then(r=>r.ok?r.json():null).catch(()=>null),
    fetch('https://query1.finance.yahoo.com/v8/finance/chart/'+code+'.KS?interval=1d&range=3mo')
      .then(r=>r.ok?r.json():null).catch(()=>null),
    fetch(API+'/stock/'+code+'/flow-history?days=30').then(r=>r.ok?r.json():null).catch(()=>null),
  ]);

  // ── 수급 히스토리 탭
  if(flowHist && flowHist.length){
    const rows = [...flowHist].reverse().map(d=>{
      const fCol = d.foreign_net>0?'#3fb950':d.foreign_net<0?'#f85149':'#8b949e';
      const iCol = d.institution_net>0?'#3fb950':d.institution_net<0?'#f85149':'#8b949e';
      const chgCol = d.change_pct>=0?'#3fb950':'#f85149';
      return `<tr>
        <td class="ts">${d.date}</td>
        <td style="color:${fCol};font-weight:600">${fmt(d.foreign_net)}</td>
        <td style="color:${iCol};font-weight:600">${fmt(d.institution_net)}</td>
        <td style="font-weight:600">${d.close_price!=null?Number(d.close_price).toLocaleString()+'원':'—'}</td>
        <td style="color:${chgCol}">${d.change_pct!=null?fmtP(d.change_pct):'—'}</td>
      </tr>`;
    }).join('');
    document.getElementById('modal-flow-body').innerHTML=`
      <table style="width:100%;margin-top:8px">
        <thead><tr>
          <th>날짜</th><th style="color:#39d0d0">외인순매수</th><th style="color:#58a6ff">기관순매수</th><th>종가</th><th>등락</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } else {
    document.getElementById('modal-flow-body').innerHTML='<div style="color:#8b949e;padding:20px;text-align:center">수급 데이터 없음</div>';
  }

  // ── 가격 차트 (Yahoo Finance)
  let priceData = null;
  if(priceHist && priceHist.chart && priceHist.chart.result && priceHist.chart.result[0]){
    const res = priceHist.chart.result[0];
    const ts = res.timestamp || [];
    const q = res.indicators.quote[0] || {};
    priceData = {
      labels: ts.map(t=>new Date(t*1000).toLocaleDateString('ko-KR',{month:'2-digit',day:'2-digit'})),
      closes: q.close || [],
      volumes: q.volume || [],
      opens: q.open || [],
      highs: q.high || [],
      lows: q.low || [],
    };
  }

  if(priceData && priceData.closes.length > 0){
    const closes = priceData.closes;
    const lastClose = closes[closes.length-1];
    const firstClose = closes[0];
    const chg = ((lastClose-firstClose)/firstClose*100).toFixed(2);
    const high3m = Math.max(...closes).toLocaleString();
    const low3m = Math.min(...closes).toLocaleString();
    const color = chg >= 0 ? '#3fb950' : '#f85149';

    document.getElementById('modal-chart-info').innerHTML = `
      <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 14px;font-size:13px">
        <span style="color:#8b949e">현재가</span> <span style="font-weight:700;font-size:16px">${lastClose?.toLocaleString()}원</span>
        <span style="color:${color};margin-left:8px">${chg>=0?'+':''}${chg}% (3개월)</span>
      </div>
      <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 14px;font-size:13px">
        <span style="color:#8b949e">3개월 고가</span> <span style="color:#3fb950">${high3m}</span>
      </div>
      <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 14px;font-size:13px">
        <span style="color:#8b949e">3개월 저가</span> <span style="color:#f85149">${low3m}</span>
      </div>`;

    if(typeof Chart !== 'undefined'){
      // 가격 차트
      if(_modalPriceChart){_modalPriceChart.destroy();_modalPriceChart=null;}
      const ctx1 = document.getElementById('modal-price-chart').getContext('2d');
      const grad = ctx1.createLinearGradient(0,0,0,200);
      grad.addColorStop(0, chg>=0?'rgba(63,185,80,0.3)':'rgba(248,81,73,0.3)');
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      _modalPriceChart = new Chart(ctx1,{
        type:'line',
        data:{
          labels: priceData.labels,
          datasets:[{
            label:'종가',
            data: closes,
            borderColor: chg>=0?'#3fb950':'#f85149',
            backgroundColor: grad,
            borderWidth:2,
            pointRadius:0,
            fill:true,
            tension:0.2,
          }]
        },
        options:{
          responsive:true,
          interaction:{mode:'index',intersect:false},
          plugins:{
            legend:{display:false},
            tooltip:{callbacks:{label:c=>c.parsed.y?.toLocaleString()+'원'}}
          },
          scales:{
            x:{ticks:{maxTicksLimit:8,font:{size:10}},grid:{color:'#21262d'},border:{color:'#30363d'}},
            y:{ticks:{callback:v=>v?.toLocaleString(),font:{size:10}},grid:{color:'#21262d'},border:{color:'#30363d'}}
          },
          animation:{duration:300}
        }
      });

      // 거래량 차트
      if(_modalVolumeChart){_modalVolumeChart.destroy();_modalVolumeChart=null;}
      const ctx2 = document.getElementById('modal-volume-chart').getContext('2d');
      const avgVol = priceData.volumes.reduce((a,b)=>a+(b||0),0)/priceData.volumes.length;
      _modalVolumeChart = new Chart(ctx2,{
        type:'bar',
        data:{
          labels: priceData.labels,
          datasets:[{
            label:'거래량',
            data: priceData.volumes,
            backgroundColor: priceData.volumes.map(v=>v>avgVol*1.5?'rgba(88,166,255,0.7)':'rgba(88,166,255,0.3)'),
            borderWidth:0,
          }]
        },
        options:{
          responsive:true,
          plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>(c.parsed.y/10000).toFixed(0)+'만주'}}},
          scales:{
            x:{display:false},
            y:{ticks:{callback:v=>(v/10000).toFixed(0)+'만',font:{size:9}},grid:{color:'#21262d'},border:{color:'#30363d'}}
          },
          animation:{duration:300}
        }
      });
    }
  } else {
    // Yahoo 실패 시 DB 가격 데이터로 폴백
    document.getElementById('modal-chart-info').innerHTML='<div style="color:#8b949e;font-size:12px">차트 데이터를 불러올 수 없습니다 (Yahoo Finance 접속 불가)</div>';
    if(_modalPriceChart){_modalPriceChart.destroy();_modalPriceChart=null;}
    if(_modalVolumeChart){_modalVolumeChart.destroy();_modalVolumeChart=null;}
  }

  // ── 시그널 탭
  if(!data){document.getElementById('modal-body').innerHTML='<div style="color:#f85149">시그널 데이터 없음</div>';return;}

  let histHtml='';
  if(hist&&hist.history&&hist.history.length>1){
    const scores=hist.history.map(h=>h.score);
    const maxS=Math.max(...scores)||1;
    const bars=hist.history.slice(0,20).map(h=>{
      const w=Math.max(2,(h.score/maxS)*120);
      const color=h.score>=5?'#3fb950':h.score>=2?'#58a6ff':'#8b949e';
      return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
        <span class="ts" style="width:85px">${h.date}</span>
        <div style="height:10px;width:${w}px;background:${color};border-radius:2px"></div>
        <span class="ts">${h.score.toFixed(2)}</span>
      </div>`;
    }).join('');
    histHtml=`<div style="margin-bottom:16px">
      <div style="font-size:11px;text-transform:uppercase;color:#8b949e;margin-bottom:6px">점수 이력 (최근 20일)</div>
      ${bars}
    </div>`;
  }

  document.getElementById('modal-body').innerHTML=histHtml+`<table>
    <thead><tr><th>지표</th><th>실측값</th><th>정규화 점수</th><th>설명</th><th>비고</th></tr></thead>
    <tbody>${data.map(d=>`<tr style="opacity:${d.is_enabled?1:.5}">
      <td><b>${d.key}</b></td>
      <td>${d.raw_value!=null?(typeof d.raw_value==='number'&&Math.abs(d.raw_value)>1000?d.raw_value.toLocaleString():d.raw_value.toFixed(2)):'—'}</td>
      <td>${scoreBar(d.normalized_score,2)}</td>
      <td>${d.interpretation}</td>
      <td class="ts">${d.note||''}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

function closeModal(){
  document.getElementById('modal-bg').classList.remove('show');
  if(_modalPriceChart){_modalPriceChart.destroy();_modalPriceChart=null;}
  if(_modalVolumeChart){_modalVolumeChart.destroy();_modalVolumeChart=null;}
}



function showToast(msg,err=false){
  const t=document.getElementById('toast');
  t.textContent=msg;t.style.background=err?'#da3633':'#238636';
  t.style.display='block';setTimeout(()=>t.style.display='none',5000);
}

loadCandidates();
if (location.hash) switchTab(location.hash.slice(1));
const chartQuery=new URLSearchParams(location.search);
if (/^[0-9A-Z]{6}$/.test(chartQuery.get('chart')||'')) openChartModal(chartQuery.get('chart'),chartQuery.get('name')||chartQuery.get('chart'),'');
</script>
</body>
</html>"""


@app.on_event("startup")
def startup_event() -> None:
    import threading
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text  # noqa: PLC0415
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE stocks ADD COLUMN IF NOT EXISTS shares_outstanding FLOAT DEFAULT 0.0"))
        conn.execute(text("ALTER TABLE radar_picks ADD COLUMN IF NOT EXISTS market_cap FLOAT DEFAULT 0.0"))
    db = SessionLocal()
    try:
        seed_reference_data(db)
    finally:
        db.close()
    def _bg() -> None:
        from backend.utils.dates import is_trading_day  # noqa: PLC0415
        from datetime import date as _date  # noqa: PLC0415
        today = _date.today()
        if not is_trading_day(today):
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).info("오늘(%s)은 거래일이 아니므로 startup 파이프라인 스킵", today)
            return
        _db = SessionLocal()
        try:
            run_daily_pipeline(_db)
        finally:
            _db.close()
    threading.Thread(target=_bg, daemon=True).start()
    start_scheduler()

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
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>
<header>
  <div>
    <h1>선물·옵션 수급 기반 익일 종목 선별 시스템</h1>
    <div class="sub">로컬 대시보드 · <span id="hdr-date">—</span> · <span id="hdr-sig">—</span> · 1분 자동 갱신</div>
  </div>
  <div style="display:flex;gap:8px">
    <button class="btn btn-gray" onclick="loadAll()">⟳ 새로고침</button>
  </div>
</header>

<div class="err-bar" id="err-bar">백엔드 연결 실패 — 서버가 실행 중인지 확인하세요</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('dash')">대시보드</div>
  <div class="tab" onclick="switchTab('screener')">전종목 스크리너</div>
  <div class="tab" onclick="switchTab('signal')">시장 시그널 상세</div>
</div>

<!-- 대시보드 탭 -->
<div id="panel-dash" class="panel active content">

  <!-- 내일 매수 후보 (최상단) -->
  <div style="background:#0d1117;border:2px solid #388bfd;border-radius:10px;padding:18px;margin-bottom:20px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px">
      <div>
        <span style="font-weight:800;color:#58a6ff;font-size:17px">내일 매수 후보</span>
        <span style="font-size:12px;color:#8b949e;margin-left:8px">T+1 진입 적합도 · 수급 연속성 보너스 · 급등 페널티 적용</span>
      </div>
      <div style="font-size:11px;color:#8b949e" id="picks-date-label"></div>
    </div>
    <div id="tomorrow-picks-body">
      <div style="color:#8b949e;font-size:13px;text-align:center;padding:20px">로딩 중…</div>
    </div>
  </div>

  <!-- 요약 카드 -->
  <div class="grid" style="margin-bottom:16px">
    <div class="card"><h3>시장 시그널</h3><div class="val" id="sig">—</div><div class="note" id="sig-score"></div></div>
    <div class="card"><h3>기준일</h3><div class="val" id="date" style="font-size:20px">—</div></div>
    <div class="card"><h3>전종목 스크리닝</h3><div class="val" id="scr-cnt">—</div><div class="note">시총·거래대금 필터 후</div></div>
    <div class="card"><h3>데이터 품질</h3><div class="val" id="dq-score" style="font-size:24px">—</div><div class="note" id="dq-note">데이터 수집 현황</div></div>
  </div>

  <!-- 시장 시그널 히스토리 -->
  <div style="margin-bottom:16px">
    <div style="font-size:12px;text-transform:uppercase;color:#8b949e;margin-bottom:8px;letter-spacing:.06em">시장 시그널 히스토리 (외인+기관 수급 기반)</div>
    <div id="sig-history" style="display:flex;gap:8px;flex-wrap:wrap"></div>
  </div>

  <!-- 전일 대비 상승 종목 -->
  <div style="margin-bottom:16px">
    <div style="font-size:12px;text-transform:uppercase;color:#8b949e;margin-bottom:8px;letter-spacing:.06em">전일 대비 시그널 상승 TOP 5</div>
    <div id="trending-stocks" style="display:flex;gap:8px;flex-wrap:wrap"></div>
  </div>

  <span id="rec-cnt" style="display:none"></span>

  <!-- 추천 성과 섹션 -->
  <div style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:18px;margin-top:20px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px">
      <div style="font-weight:600;color:#c9d1d9;font-size:15px">추천 성과 <span style="font-size:12px;color:#8b949e;font-weight:400">(T+1 실제 수익률)</span></div>
      <div style="display:flex;align-items:center;gap:8px">
        <select id="perf-days" onchange="loadPerformance()" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px;font-size:12px">
          <option value="14">최근 2주</option>
          <option value="30" selected>최근 1개월</option>
          <option value="60">최근 2개월</option>
        </select>
      </div>
    </div>
    <!-- 요약 카드 -->
    <div id="perf-summary" style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px"></div>
    <!-- 상세 테이블 -->
    <div style="max-height:300px;overflow-y:auto;border:1px solid #21262d;border-radius:6px">
      <table style="font-size:12px">
        <thead style="position:sticky;top:0;background:#161b22;z-index:1">
          <tr><th>추천일</th><th>종목</th><th>순위</th><th>매수가</th><th>익일가</th><th>수익률</th></tr>
        </thead>
        <tbody id="perf-body"><tr><td colspan="6" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
      </table>
    </div>
  </div>

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
    <select id="scr-sort" onchange="setScrSort(this.value)">
      <option value="total_score">총점 순</option>
      <option value="stock_score">종목점수 순</option>
      <option value="change_pct">등락률 순</option>
      <option value="close_price">종가 순</option>
      <option value="market_cap">시총 순</option>
      <option value="short_ratio">공매도% 순</option>
      <option value="rsi_14">RSI 순</option>
      <option value="volume_surge">거래량배수 순</option>
      <option value="ma_score">MA위치 순</option>
      <option value="signal_confluence">신호합류 순</option>
    </select>
    <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:13px">
      <input type="checkbox" id="scr-showall" onchange="loadScreener()"> 필터 무시 (전종목)
    </label>
    <button class="btn btn-gray btn-sm" onclick="toggleFilterPanel()">▼ 상세필터</button>
    <button class="btn btn-gray btn-sm" onclick="resetFilters()">✕ 필터초기화</button>
    <button class="btn btn-gray btn-sm" onclick="loadScreener()">⟳ 새로고침</button>
    <button class="btn btn-gray btn-sm" onclick="exportCsv()">↓ CSV</button>
    <span class="ts" id="scr-info"></span>
  </div>
  <!-- 상세 필터 패널 -->
  <div id="filter-panel" style="display:none;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 18px;margin:0 16px 12px;display:none">
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px 20px;font-size:13px">
      <div>
        <div style="color:#8b949e;margin-bottom:4px">RSI 범위</div>
        <div style="display:flex;gap:6px;align-items:center">
          <input type="number" id="f-rsi-min" placeholder="최소" min="0" max="100" style="width:70px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
          <span style="color:#8b949e">~</span>
          <input type="number" id="f-rsi-max" placeholder="최대" min="0" max="100" style="width:70px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
        </div>
      </div>
      <div>
        <div style="color:#8b949e;margin-bottom:4px">공매도% 범위</div>
        <div style="display:flex;gap:6px;align-items:center">
          <input type="number" id="f-short-min" placeholder="최소" min="0" step="0.1" style="width:70px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
          <span style="color:#8b949e">~</span>
          <input type="number" id="f-short-max" placeholder="최대" min="0" step="0.1" style="width:70px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
        </div>
      </div>
      <div>
        <div style="color:#8b949e;margin-bottom:4px">거래량배수 최소</div>
        <input type="number" id="f-vol-min" placeholder="예: 1.5" min="0" step="0.1" style="width:100px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
      </div>
      <div>
        <div style="color:#8b949e;margin-bottom:4px">등락률 범위 (%)</div>
        <div style="display:flex;gap:6px;align-items:center">
          <input type="number" id="f-chg-min" placeholder="최소" step="0.1" style="width:70px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
          <span style="color:#8b949e">~</span>
          <input type="number" id="f-chg-max" placeholder="최대" step="0.1" style="width:70px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
        </div>
      </div>
      <div>
        <div style="color:#8b949e;margin-bottom:4px">기관 순매수 방향</div>
        <select id="f-inst" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px" onchange="renderScreener()">
          <option value="">전체</option>
          <option value="buy">매수(+)</option>
          <option value="sell">매도(-)</option>
        </select>
      </div>
      <div>
        <div style="color:#8b949e;margin-bottom:4px">외국인 순매수 방향</div>
        <select id="f-foreign" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px" onchange="renderScreener()">
          <option value="">전체</option>
          <option value="buy">매수(+)</option>
          <option value="sell">매도(-)</option>
        </select>
      </div>
      <div>
        <div style="color:#8b949e;margin-bottom:4px">신호 합류 수 최소</div>
        <input type="number" id="f-conf-min" placeholder="예: 5" min="0" max="13" style="width:100px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
      </div>
      <div>
        <div style="color:#8b949e;margin-bottom:4px">연속매수일 최소</div>
        <input type="number" id="f-consec-min" placeholder="예: 3" min="0" style="width:100px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
      </div>
      <div>
        <div style="color:#8b949e;margin-bottom:4px">총점 최소</div>
        <input type="number" id="f-score-min" placeholder="예: 0.5" min="0" max="1" step="0.01" style="width:100px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 6px;border-radius:4px" oninput="renderScreener()">
      </div>
      <div>
        <div style="color:#8b949e;margin-bottom:4px">기관+외국인 동시매수</div>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
          <input type="checkbox" id="f-cobuy" onchange="renderScreener()">
          <span>동시매수만 보기</span>
        </label>
      </div>
    </div>
  </div>
  <div class="content">
    <table>
      <thead><tr>
        <th onclick="setScrSort('rank')">#<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('name')">종목<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('total_score')">신뢰도<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('close_price')">종가<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('change_pct')">등락<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('institution_net_buy')">기관</th>
        <th onclick="setScrSort('foreign_net_buy')">외인</th>
        <th onclick="setScrSort('institution_consecutive_days')">기관연속<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('foreign_consecutive_days')">외인연속<span class="sort-icon">↕</span></th>
        <th>수급비율</th>
        <th onclick="setScrSort('rsi_14')">RSI<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('volume_surge')">거래량<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('short_ratio')">공매도<span class="sort-icon">↕</span></th>
        <th onclick="setScrSort('market_cap')">시총<span class="sort-icon">↕</span></th>
        <th>태그</th>
        <th>상세</th>
      </tr></thead>
      <tbody id="scr-body"><tr><td colspan="16" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
    </table>
  </div>
</div>


<!-- 시장 시그널 상세 탭 -->
<div id="panel-signal" class="panel content">
  <div class="grid" id="sig-cards"></div>
  <table>
    <thead><tr><th>지표</th><th>실측값</th><th>정규화 점수</th><th>설명</th><th>소스</th><th>비고</th></tr></thead>
    <tbody id="sig-detail-body"><tr><td colspan="6" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
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
let scrData = [], scrSortKey = 'total_score', scrSortAsc = false;

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
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',['dash','screener','signal'][i]===id));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+id).classList.add('active');
  if(id==='screener')loadScreener();
  if(id==='signal')loadSignalDetail();
}

async function loadAll() {
  try {
    const [sig, recs, scr, hist, dq, trending, tomorrowPicks] = await Promise.all([
      fetch(API+'/market-signal').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/recommendations').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/screener').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/market-signal/history?limit=7').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/data-quality').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/screener/trending?top_n=5').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/screener/tomorrow-picks?top_n=7').then(r=>r.ok?r.json():null).catch(()=>null),
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
    }
    if(scr) document.getElementById('scr-cnt').textContent=scr.length;
    if(dq){
      const score=dq.overall_score;
      const color=score>=80?'#3fb950':score>=50?'#d29922':'#f85149';
      document.getElementById('dq-score').innerHTML=`<span style="color:${color}">${score}%</span>`;
      const c=dq.checks||{};
      document.getElementById('dq-note').textContent=`현물${(c.spot_coverage*100||0).toFixed(0)}% 수급${(c.flow_coverage*100||0).toFixed(0)}% 선물${c.futures_real?'✓':'✗'}`;
    }
    if(trending && trending.length){
      document.getElementById('trending-stocks').innerHTML=trending.map(t=>`
        <div style="background:#161b22;border:1px solid #30363d;border-radius:6px;padding:8px 14px;min-width:140px;cursor:pointer" onclick="showStockDetail('${t.code}','${t.name}')">
          <div style="font-size:13px;font-weight:700">${t.name}</div>
          <div class="ts">${t.code}</div>
          <div style="color:#3fb950;font-weight:600;margin-top:4px">+${(t.delta||0).toFixed(2)} ↑</div>
          <div class="ts">${(t.today_score||0).toFixed(2)} (전: ${(t.prev_score||0).toFixed(2)})</div>
        </div>`).join('');
    } else if(document.getElementById('trending-stocks')) {
      document.getElementById('trending-stocks').innerHTML='<span class="ts">이전 거래일 데이터 없음</span>';
    }
    // 내일 매수 후보 렌더링
    const tpEl = document.getElementById('tomorrow-picks-body');
    if(tpEl){
      if(tomorrowPicks && tomorrowPicks.length){
        const riskColor = r => r==='고'?'#f85149':r==='중'?'#d29922':'#3fb950';
        const fmtNet = v => { const a=Math.abs(v); const s=v<0?'-':'+'; if(a>=1e12)return s+(a/1e12).toFixed(1)+'조'; if(a>=1e8)return s+(a/1e8).toFixed(1)+'억'; if(a>=1e4)return s+(a/1e4).toFixed(0)+'만'; return v===0?'—':s+a.toFixed(0); };
        tpEl.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px">` +
          tomorrowPicks.map((p,i) => {
            const chgColor = p.change_pct>=0?'#3fb950':'#f85149';
            const bothBadge = p.both_buying ? '<span style="background:#1f6feb33;color:#58a6ff;border:1px solid #1f6feb;border-radius:4px;padding:1px 6px;font-size:10px;margin-left:4px">기관+외인</span>' : '';
            const coLine = p.co_consecutive_days>=2 ? `<div style="color:#d29922;font-size:11px">동반매수 ${p.co_consecutive_days}일 연속</div>` : '';
            return `<div style="background:#0d1117;border:1px solid ${i===0?'#388bfd':'#30363d'};border-radius:8px;padding:12px;cursor:pointer" onclick="showStockDetail('${p.code}','${p.name}')">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
                <div>
                  <span style="font-weight:700;font-size:14px">${i+1}. ${p.name}</span>${bothBadge}
                  <div class="ts">${p.code} · ${p.market}</div>
                </div>
                <div style="text-align:right">
                  <div style="font-size:13px;color:${riskColor(p.risk)};font-weight:600">리스크 ${p.risk}</div>
                  <div class="ts" style="color:${chgColor}">${p.change_pct>=0?'+':''}${p.change_pct}%</div>
                </div>
              </div>
              <div style="display:flex;justify-content:space-between;margin-bottom:6px">
                <div style="font-size:18px;font-weight:700;color:#f0f6fc">${p.close_price!=null?p.close_price.toLocaleString():'—'}원</div>
                <div style="text-align:right">
                  <div style="font-size:11px;color:#8b949e">T+1 적합도</div>
                  <div style="font-size:16px;font-weight:700;color:#58a6ff">${(p.t1_score||0).toFixed(2)}</div>
                </div>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px;color:#8b949e;margin-bottom:4px">
                <div>외인 <b style="color:#c9d1d9">${p.foreign_consecutive_days}일 연속</b></div>
                <div>기관 <b style="color:#c9d1d9">${p.institution_consecutive_days}일 연속</b></div>
                <div>수급비율 <b style="color:#c9d1d9">${p.flow_ratio}</b></div>
                <div>기관 <b style="color:${p.institution_net_buy>=0?'#3fb950':'#f85149'}">${fmtNet(p.institution_net_buy)}</b></div>
              </div>
              ${coLine}
            </div>`;
          }).join('') + `</div>`;
      // picks-date-label 업데이트
      const pdl = document.getElementById('picks-date-label');
      if(pdl && sig) pdl.textContent = sig.trading_date + ' 기준';
      } else {
        tpEl.innerHTML = '<div style="color:#8b949e;font-size:13px;text-align:center;padding:20px">데이터 없음 — 파이프라인을 실행하세요</div>';
      }
    }
    if(hist && hist.length){
      const sorted=[...hist].sort((a,b)=>a.trading_date>b.trading_date?1:-1);
      const sigColor = s => s==='강세매수'?'#3fb950':s==='상방'?'#58a6ff':s==='하방'?'#f85149':s==='강세매도'?'#f85149':'#d29922';
      document.getElementById('sig-history').innerHTML=sorted.map(h=>`
        <div style="background:#161b22;border:1px solid #30363d;border-radius:6px;padding:8px 14px;text-align:center;min-width:110px">
          <div class="ts">${h.trading_date}</div>
          <div style="font-weight:700;font-size:14px;color:${sigColor(h.signal)}">${h.signal}</div>
          <div class="ts" style="color:${h.score>0?'#3fb950':h.score<0?'#f85149':'#8b949e'}">${h.score>0?'+':''}${h.score.toFixed(1)}</div>
        </div>`).join('');
    }
  } catch(e) {
    console.error('loadAll error:', e);
    document.getElementById('err-bar').style.display='block';
  }
}

async function loadScreener() {
  const showAll = document.getElementById('scr-showall')?.checked ? '&show_all=true' : '';
  const r = await fetch(API+'/screener?'+showAll).catch(()=>null);
  if(!r||!r.ok){document.getElementById('scr-body').innerHTML='<tr><td colspan="12" style="color:#f85149;text-align:center;padding:20px">로드 실패</td></tr>';return;}
  scrData = await r.json();
  renderScreener();
}

function setScrSort(key){
  if(scrSortKey===key)scrSortAsc=!scrSortAsc;
  else{scrSortKey=key;scrSortAsc=false;}
  const sel=document.getElementById('scr-sort');
  if(sel&&sel.value!==key){
    const opt=[...sel.options].find(o=>o.value===key);
    if(opt) sel.value=key;
  }
  renderScreener();
}

function toggleFilterPanel(){
  const p=document.getElementById('filter-panel');
  p.style.display=p.style.display==='none'?'block':'none';
}
function resetFilters(){
  ['f-rsi-min','f-rsi-max','f-short-min','f-short-max','f-vol-min',
   'f-chg-min','f-chg-max','f-conf-min','f-consec-min','f-score-min'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.value='';
  });
  ['f-inst','f-foreign'].forEach(id=>{const el=document.getElementById(id);if(el)el.value='';});
  const cb=document.getElementById('f-cobuy'); if(cb) cb.checked=false;
  renderScreener();
}
function _fv(id){const v=document.getElementById(id)?.value;return v===''||v==null?null:parseFloat(v);}
function _fs(id){return document.getElementById(id)?.value||'';}

function renderScreener(){
  const sortSel=document.getElementById('scr-sort');
  if(sortSel&&sortSel.value)scrSortKey=sortSel.value;
  const q=document.getElementById('scr-search').value.toLowerCase();
  const mkt=document.getElementById('scr-market').value;
  const showAll=document.getElementById('scr-showall')?.checked;
  const rsiMin=_fv('f-rsi-min'), rsiMax=_fv('f-rsi-max');
  const shortMin=_fv('f-short-min'), shortMax=_fv('f-short-max');
  const volMin=_fv('f-vol-min');
  const chgMin=_fv('f-chg-min'), chgMax=_fv('f-chg-max');
  const confMin=_fv('f-conf-min');
  const consecMin=_fv('f-consec-min');
  const scoreMin=_fv('f-score-min');
  const instDir=_fs('f-inst'), foreignDir=_fs('f-foreign');
  const cobuy=document.getElementById('f-cobuy')?.checked;
  let data=[...scrData].filter(i=>{
    if(q&&!i.name.toLowerCase().includes(q)&&!i.code.includes(q))return false;
    if(mkt&&i.market!==mkt)return false;
    if(showAll)return true;
    const rsi=i.rsi_14;
    if(rsiMin!=null&&(rsi==null||rsi<rsiMin))return false;
    if(rsiMax!=null&&(rsi==null||rsi>rsiMax))return false;
    const sr=i.short_ratio||0;
    if(shortMin!=null&&sr<shortMin)return false;
    if(shortMax!=null&&sr>shortMax)return false;
    if(volMin!=null&&(i.volume_surge||1)<volMin)return false;
    const chg=i.change_pct||0;
    if(chgMin!=null&&chg<chgMin)return false;
    if(chgMax!=null&&chg>chgMax)return false;
    if(confMin!=null&&(i.signal_confluence||0)<confMin)return false;
    if(consecMin!=null&&(i.consecutive_days||0)<consecMin)return false;
    if(scoreMin!=null&&(i.total_score||0)<scoreMin)return false;
    if(instDir==='buy'&&(i.institution_net_buy||0)<=0)return false;
    if(instDir==='sell'&&(i.institution_net_buy||0)>=0)return false;
    if(foreignDir==='buy'&&(i.foreign_net_buy||0)<=0)return false;
    if(foreignDir==='sell'&&(i.foreign_net_buy||0)>=0)return false;
    if(cobuy&&!((i.institution_net_buy||0)>0&&(i.foreign_net_buy||0)>0))return false;
    return true;
  });
  data.sort((a,b)=>{
    const av=a[scrSortKey]??0, bv=b[scrSortKey]??0;
    return scrSortAsc?(av>bv?1:-1):(av<bv?1:-1);
  });
  document.getElementById('scr-info').textContent=`${data.length}/${scrData.length}종목`;
  if(!data.length){document.getElementById('scr-body').innerHTML='<tr><td colspan="17" style="color:#8b949e;text-align:center;padding:16px">검색 결과 없음</td></tr>';return;}
  document.getElementById('scr-body').innerHTML=data.map((i,idx)=>{
    const instCol = i.institution_net_buy>0?'#3fb950':i.institution_net_buy<0?'#f85149':'#8b949e';
    const fgnCol = i.foreign_net_buy>0?'#3fb950':i.foreign_net_buy<0?'#f85149':'#8b949e';
    const instDays = i.institution_consecutive_days||0;
    const fgnDays = i.foreign_consecutive_days||0;
    const instDayHtml = instDays>0?`<b style="color:#58a6ff">${instDays}일</b>`:'<span style="color:#444">—</span>';
    const fgnDayHtml = fgnDays>0?`<b style="color:#39d0d0">${fgnDays}일</b>`:'<span style="color:#444">—</span>';
    const pct = Math.min(100, Math.round((i.total_score/3)*100));
    const pctColor = pct>=70?'#3fb950':pct>=40?'#58a6ff':'#d29922';
    return `<tr>
    <td style="color:#8b949e">${idx+1}</td>
    <td><b style="cursor:pointer;color:#e6edf3" onclick="showStockDetail('${i.code}','${i.name}')">${i.name}</b><br><span class="ts">${i.code} · <span style="color:${i.market==='KOSPI'?'#58a6ff':'#39d0d0'}">${i.market||'KOSPI'}</span></span></td>
    <td><span style="color:${pctColor};font-weight:700;font-size:15px">${pct}%</span><br><span class="ts" style="color:#444">${i.total_score.toFixed(2)}</span></td>
    <td style="font-weight:600">${fmtKrw(i.close_price)}</td>
    <td style="color:${i.change_pct>=0?'#3fb950':'#f85149'};font-weight:600">${fmtP(i.change_pct)}</td>
    <td style="color:${instCol};font-weight:600">${fmt(i.institution_net_buy)}</td>
    <td style="color:${fgnCol};font-weight:600">${fmt(i.foreign_net_buy)}</td>
    <td style="text-align:center">${instDayHtml}</td>
    <td style="text-align:center">${fgnDayHtml}</td>
    <td style="color:#8b949e;font-size:12px">${i.flow_ratio||'—'}</td>
    <td style="color:${i.rsi_14!=null?(i.rsi_14<30?'#58a6ff':i.rsi_14>70?'#f85149':'#c9d1d9'):'#444'}">${i.rsi_14!=null?Math.round(i.rsi_14):'—'}</td>
    <td style="color:${(i.volume_surge||1)>=2?'#3fb950':(i.volume_surge||1)<0.8?'#f85149':'#c9d1d9'}">${(i.volume_surge||1).toFixed(1)}x</td>
    <td style="color:${(i.short_ratio||0)<=4?'#3fb950':(i.short_ratio||0)<=10?'#d29922':'#f85149'}">${(i.short_ratio||0).toFixed(1)}%</td>
    <td class="ts">${i.market_cap>=1e12?((i.market_cap/1e12).toFixed(1)+'조'):i.market_cap>=1e8?((i.market_cap/1e8).toFixed(0)+'억'):'—'}</td>
    <td>${tagHtml(i.tags)}</td>
    <td><button class="btn btn-gray btn-sm" onclick="showStockDetail('${i.code}','${i.name}')">상세</button></td>
  </tr>`;}).join('');
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


function exportCsv(){
  if(!scrData.length){showToast('내보낼 데이터가 없습니다.',true);return;}
  const q=document.getElementById('scr-search').value.toLowerCase();
  const mkt=document.getElementById('scr-market').value;
  const data=[...scrData].filter(i=>{
    if(q&&!i.name.toLowerCase().includes(q)&&!i.code.includes(q))return false;
    if(mkt&&i.market!==mkt)return false;
    return true;
  });
  const headers=['순위','코드','종목명','시장','시총(억)','총점','종목점수','시장점수','종가','등락%','기관순매수','외국인순매수','공매도%','RSI','거래량배수','MA점수','연속매수일'];
  const rows=data.map((i,idx)=>[
    idx+1,i.code,i.name,i.market,i.market_cap?(i.market_cap/1e8).toFixed(0):'',
    i.total_score,i.stock_score,i.market_score,i.close_price,i.change_pct,
    (i.institution_net_buy/1e8).toFixed(2),(i.foreign_net_buy/1e8).toFixed(2),
    (i.short_ratio||0).toFixed(1),i.rsi_14!=null?Math.round(i.rsi_14):'',
    (i.volume_surge||1).toFixed(2),i.ma_score||0,i.consecutive_days||0,
  ]);
  const csv=[headers,...rows].map(r=>r.join(',')).join(String.fromCharCode(10));
  const blob=new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download='screener_'+new Date().toISOString().slice(0,10)+'.csv';
  a.click();URL.revokeObjectURL(url);
  showToast(`CSV 내보내기 완료 (${data.length}종목)`);
}

async function loadPerformance(){
  const days = document.getElementById('perf-days')?.value || 30;
  const d = await fetch(API+'/recommendations/performance?days='+days).then(r=>r.ok?r.json():null).catch(()=>null);
  if(!d){
    document.getElementById('perf-summary').innerHTML='<div style="color:#f85149;font-size:12px;margin:8px 0">데이터를 불러오지 못했습니다</div>';
    document.getElementById('perf-body').innerHTML='<tr><td colspan="6" style="color:#8b949e;text-align:center;padding:20px">데이터 없음</td></tr>';
    return;
  }
  const s = d.summary;
  const retColor = v => v==null?'#8b949e':v>=0?'#3fb950':'#f85149';
  document.getElementById('perf-summary').innerHTML = s.total===0
    ? '<div style="color:#8b949e;font-size:12px;margin:8px 0">추천 이력이 없습니다 — 파이프라인을 실행하세요</div>'
    : `<div style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0">
        <div class="card" style="min-width:110px;padding:12px 16px">
          <h3>분석 종목수</h3><div class="val" style="font-size:22px">${s.total}</div>
        </div>
        <div class="card" style="min-width:110px;padding:12px 16px">
          <h3>승률</h3><div class="val" style="font-size:22px;color:${retColor(s.win_rate-50)}">${s.win_rate}%</div>
          <div class="note">${s.win_count}승 / ${s.total-s.win_count}패</div>
        </div>
        <div class="card" style="min-width:110px;padding:12px 16px">
          <h3>평균 수익률</h3><div class="val" style="font-size:22px;color:${retColor(s.avg_return)}">${s.avg_return>=0?'+':''}${s.avg_return}%</div>
        </div>
        <div class="card" style="min-width:110px;padding:12px 16px">
          <h3>최고</h3><div class="val" style="font-size:22px;color:#3fb950">+${s.best}%</div>
        </div>
        <div class="card" style="min-width:110px;padding:12px 16px">
          <h3>최저</h3><div class="val" style="font-size:22px;color:#f85149">${s.worst}%</div>
        </div>
      </div>`;
  document.getElementById('perf-body').innerHTML = d.records.length
    ? d.records.map(r=>`<tr>
        <td class="ts">${r.trading_date}</td>
        <td><b>${r.stock_name}</b><br><span class="ts">${r.stock_code}</span></td>
        <td>${r.rank}</td>
        <td>${r.entry_price!=null?r.entry_price.toLocaleString()+'원':'—'}</td>
        <td>${r.next_price!=null?r.next_price.toLocaleString()+'원':'<span style="color:#8b949e">미확인</span>'}</td>
        <td style="font-weight:600;color:${retColor(r.return_pct)}">${r.return_pct!=null?(r.return_pct>=0?'+':'')+r.return_pct+'%':'<span style="color:#8b949e">—</span>'}</td>
      </tr>`).join('')
    : '<tr><td colspan="6" style="color:#8b949e;text-align:center;padding:20px">추천 이력 없음</td></tr>';
}

let _sigBackfillTimer = null;
async function runSignalBackfill(btn){
  btn.disabled=true;
  const statusEl=document.getElementById('sig-backfill-status');
  statusEl.textContent='시작 중…';
  try{
    await fetch(API+'/data/signal-backfill',{method:'POST'});
    // 폴링
    _sigBackfillTimer = setInterval(async()=>{
      const r=await fetch(API+'/data/signal-backfill/status');
      const d=await r.json();
      statusEl.textContent=d.progress||'';
      if(!d.running){
        clearInterval(_sigBackfillTimer);
        btn.disabled=false;
        if(d.result){
          const errs=d.result.errors?.length||0;
          statusEl.textContent=`완료 ${d.result.done}/${d.result.total}일${errs?` (오류${errs})`:' ✓'}`;
          showToast(`시그널 재계산 완료: ${d.result.done}/${d.result.total}일`);
        }else if(d.error){statusEl.textContent='오류: '+d.error;showToast('시그널 재계산 오류',true);}
      }
    },5000);
  }catch(e){btn.disabled=false;statusEl.textContent='실패';showToast('시그널 재계산 실패',true);}
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

loadAll();
loadPerformance();
setInterval(loadAll,60000);
</script>
</body>
</html>"""


@app.on_event("startup")
def startup_event() -> None:
    import threading
    Base.metadata.create_all(bind=engine)
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


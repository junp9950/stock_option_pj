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
.lead{color:#c9d1d9;font-size:13px;margin:0 0 6px}
.why{margin:0 0 12px;color:#8b949e;font-size:12px;line-height:1.65}
.why summary{cursor:pointer;color:#8b949e;font-size:12px;width:max-content}
.why[open] summary{margin-bottom:4px}
.log-ok{color:#3fb950}.log-err{color:#f85149}.log-run{color:#d29922}
.m-only{display:none}
@media (max-width:720px){
  .m-only{display:inline}
  .pb-table.tv-table tr{display:grid;grid-template-columns:28px 1fr auto;column-gap:10px;row-gap:2px;align-items:center;padding:9px 12px;margin-bottom:6px;border-radius:8px}
  .pb-table.tv-table td{display:block;padding:0;border:none;margin:0;text-align:left;font-size:14px}
  .pb-table.tv-table td.c-rank{grid-column:1;grid-row:1/3;text-align:center;color:#8b949e;font-size:13px}
  .pb-table.tv-table td.c-name{grid-column:2;grid-row:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .pb-table.tv-table td.c-price{grid-column:3;grid-row:1;text-align:right}
  .pb-table.tv-table td.c-tv{grid-column:2;grid-row:2;font-size:12px;color:#8b949e}
  .pb-table.tv-table td.c-tv::before{content:"거래대금 "}
  .pb-table.tv-table td.c-chg{grid-column:3;grid-row:2;text-align:right;font-size:13px}
  .pb-table.tv-table td.c-vol,.pb-table.tv-table td.c-cap,.pb-table.tv-table td.c-turn{display:none}
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
    <h1>주식 레이더</h1>
    <div class="sub">장 마감 후 자동 갱신</div>
  </div>
  <div style="display:flex;gap:8px">
    <button class="btn" id="btn-run-pipeline" onclick="runPipeline()" hidden>▶ 파이프라인 실행</button>
  </div>
</header>

<div class="err-bar" id="err-bar">백엔드 연결 실패 — 서버가 실행 중인지 확인하세요</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('jongbe')">종베 후보</div>
  <div class="tab" onclick="switchTab('candidates')">차트 후보</div>
  <div class="tab" onclick="switchTab('sector')">섹터 수급</div>
  <div class="tab" onclick="switchTab('journal')">매매 일지</div>
  <div class="tab" onclick="switchTab('screener')">거래대금 순위</div>
  <div class="tab" onclick="switchTab('heatmap')">시장 히트맵</div>
  <div class="tab" onclick="switchTab('discussion')">종목토론</div>
  <div class="tab" onclick="switchTab('suggest')">건의사항</div>
</div>

<div id="panel-suggest" class="panel"><iframe title="건의사항" id="suggest-frame" style="width:100%;height:1600px;border:0" loading="lazy"></iframe></div>
<div id="panel-discussion" class="panel"><iframe title="종목토론" id="discussion-frame" style="width:100%;height:2000px;border:0" loading="lazy"></iframe></div>

<!-- 거래대금 순위 탭 -->
<div id="panel-screener" class="panel content">
  <div class="toolbar">
    <span id="tv-mkt" style="display:inline-flex;border:1px solid #30363d;border-radius:6px;overflow:hidden">
      <button class="btn btn-sm" data-m="KOSPI" onclick="setTvMarket('KOSPI')">코스피</button>
      <button class="btn btn-gray btn-sm" data-m="KOSDAQ" onclick="setTvMarket('KOSDAQ')">코스닥</button>
    </span>
    <select id="tv-sort" onchange="loadTopValue()">
      <option value="value">거래대금 순</option>
      <option value="cap">시총 순</option>
      <option value="up">상승률 순</option>
      <option value="down">하락률 순</option>
      <option value="turnover">회전율 순</option>
    </select>
    <select id="tv-min" onchange="loadTopValue()">
      <option value="0">거래대금 전체</option>
      <option value="10">10억 이상</option>
      <option value="50">50억 이상</option>
      <option value="100">100억 이상</option>
    </select>
    <select id="tv-limit" onchange="loadTopValue()">
      <option value="50">50위까지</option>
      <option value="100" selected>100위까지</option>
      <option value="200">200위까지</option>
    </select>
    <input type="text" id="tv-search" placeholder="종목명 또는 코드 검색…" oninput="renderTopValue()">
    <button class="btn btn-gray btn-sm" onclick="loadTopValue()">⟳ 새로고침</button>
    <span class="ts" id="tv-info"></span>
  </div>
  <table class="pb-table tv-table">
    <thead><tr><th>순위</th><th>종목</th><th>종가</th><th>등락률</th><th>거래대금</th><th>거래량</th><th>시총</th><th>회전율</th></tr></thead>
    <tbody id="tv-body"><tr><td colspan="8" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
  <div class="ts" style="padding:8px 16px">거래대금 = 거래량 × 종가 근사치 (정규장 기준, 시간외 제외). 종목을 누르면 차트가 열립니다.</div>
</div>

<!-- 종베 후보 탭 -->
<div id="panel-jongbe" class="panel active content">
  <div id="jb-market" style="border-radius:10px;padding:12px 16px;margin-bottom:12px;border:1px solid #30363d">로딩 중…</div>
  <p class="lead">시장 상승·횡보 → 뜨거운 섹터 → 그날 섹터에 돈 몰림 → 거래 실린 양봉. <b>다음 날 오전 정리</b>가 기본, 갭이 크면 덜어내기.</p>
  <details class="why"><summary>근거 보기</summary>
    3년(상승·횡보장, 다음 날 "갭상승이면 시가·아니면 종가" 매도): 기본 +0.42%, 뜨거운 섹터(20일 상승 상위 3) +0.74%, <b style="color:#3fb950">A등급(섹터 거래대금 1.2배까지) +0.94%·수익 71%</b>, 섹터 밖 +0.28%, 하락장 +0.12%.
    시가 매도는 -5% 넘는 손실 2%, 종가까지 들고 가면 18%. 이격 +20%↑·그날 +12%↑는 평균은 비슷한데 큰 손실이 2~4배(안정형 필터).
    🔔 = 오늘 거래대금이 몇 년 만의 최대, 🔥 = 대량거래 관심종목 단계. 숫자는 수수료·세금 빼기 전.
  </details>
  <div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:6px">
    <span style="font-size:12px;color:#8b949e">🔥 뜨거운 섹터 <span class="ts" id="jb-date"></span></span>
    <label style="font-size:12.5px;color:#c9d1d9">시총
      <select id="jb-mincap" onchange="try{localStorage.setItem('jb-mincap',this.value)}catch(e){};renderJongbe()">
        <option value="0">전체</option><option value="500">500억 이상</option><option value="1000" selected>1,000억 이상</option>
        <option value="3000">3,000억 이상</option><option value="10000">1조 이상</option>
      </select></label>
    <label style="font-size:12.5px;color:#c9d1d9;cursor:pointer" title="3년 확인: 이격 +20% 이상·그날 +12% 이상은 평균은 비슷한데 -5% 넘는 손실이 2~4배"><input type="checkbox" id="jb-safe" checked onchange="try{localStorage.setItem('jb-safe',this.checked?'1':'0')}catch(e){};renderJongbe()"> 안정형만</label>
    <label style="font-size:12.5px;color:#c9d1d9;cursor:pointer"><input type="checkbox" id="jb-showb" onchange="renderJongbe()"> B등급도 보기</label>
    <span class="ts" id="jb-count"></span>
  </div>
  <div id="jb-fams" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px"></div>
  <table class="pb-table">
    <thead><tr><th>종목</th><th>등급</th><th>그날 봉</th><th>섹터</th><th>종가</th></tr></thead>
    <tbody id="jb-body"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
  <div id="jb-limit" class="ts" hidden></div>
  <div style="margin:12px 0 22px">
    <b style="font-size:14px;color:#e6edf3">🔔 오늘 거래대금 신기록 + 상한가</b> <span class="ts" id="lu-info"></span>
    <details class="why" style="margin:2px 0 6px"><summary>근거 보기</summary>
      몇 년 만의 최대 거래대금(평소 10배↑)이면서 상한가로 끝난 종목. 3년 247건: 종가 매수 → 다음 날 시가 평균 +5.6%(중간 +4.3%, 수익 74%).
      <b style="color:#f85149">단 상한가에 묶이면 실제로 못 사는 경우가 많습니다.</b> 점상 = 하루 종일 상한가.
    </details>
    <div id="lu-body" class="ts">로딩 중…</div>
  </div>

  <div style="margin:4px 0 20px">
    <b style="font-size:15px;color:#e6edf3">📈 스윙 후보 (10~20일)</b> <span class="ts" id="jb-swing-info"></span>
    <p class="lead" style="margin-top:6px">뜨거운 섹터 안에서 박스 상단(60일 고점)에 붙었거나 막 넘은 종목. 박스 안으로 다시 들어오면 손절.</p>
    <details class="why"><summary>근거 보기</summary>
      3년(같은 날 전 종목 평균 대비 20일 뒤): 붙음(-2% 이내) +2.4%p, 막 넘음(0~+3%) +2.9%p. 거래 2배 넘게 터지며 넘은 경우(📢)는 +0.8%p로 약했고, 이미 +3% 넘게 더 간 종목은 효과가 줄었습니다.
    </details>
    <table class="pb-table">
      <thead><tr><th>종목</th><th>박스 상단 대비</th><th>오늘</th><th>섹터</th><th>종가</th></tr></thead>
      <tbody id="jb-swing"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:16px">로딩 중…</td></tr></tbody>
    </table>
  </div>

  <div style="border:1px solid #30363d;border-radius:10px;padding:12px 16px;margin-bottom:20px">
    <b style="color:#e6edf3">✅ 보유·관심 종목 체크</b> <span class="ts">종목명이나 코드를 쉼표로 (브라우저에 기억됩니다)</span>
    <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
      <input id="jb-q" placeholder="예: 디케이티, 원익, 에스피지" style="flex:1;min-width:220px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:6px">
      <button class="btn btn-sm" onclick="jbCheck()">확인</button>
    </div>
    <div id="jb-check" style="margin-top:10px"></div>
  </div>

  <div style="font-size:12px;color:#8b949e;margin-bottom:6px">📒 이 화면 후보의 실제 다음 날 결과</div>
  <div id="jb-perf" class="ts">로딩 중…</div>
</div>

<!-- 매매 일지 탭 -->
<div id="panel-journal" class="panel content">
  <div id="jr-login" style="border:1px solid #30363d;border-radius:10px;padding:16px;max-width:420px">
    <b style="color:#e6edf3">🔒 매매 일지</b> <span class="ts">사람마다 따로 기록됩니다. 금액이 보이는 화면이라 비밀번호로 잠급니다.</span>
    <div style="display:flex;flex-direction:column;gap:8px;margin-top:12px">
      <input id="jr-owner" list="jr-owners" placeholder="이름 (예: 우라늄)" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:8px 10px;border-radius:6px">
      <datalist id="jr-owners"></datalist>
      <input id="jr-pin" type="password" placeholder="비밀번호 (4자 이상)" onkeydown="if(event.key==='Enter')jrLogin()" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:8px 10px;border-radius:6px">
      <button class="btn" onclick="jrLogin()">열기</button>
      <div id="jr-login-msg" class="ts"></div>
    </div>
  </div>

  <div id="jr-main" style="display:none">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:12px">
      <div><b style="color:#e6edf3;font-size:16px" id="jr-who"></b> <span class="ts" id="jr-asof"></span></div>
      <div style="display:flex;gap:6px">
        <button class="btn btn-sm" onclick="jrToggle('jr-input')">＋ 기록 넣기</button>
        <button class="btn btn-sm" onclick="jrLogout()">잠그기</button>
      </div>
    </div>

    <div id="jr-input" style="display:none;border:1px solid #30363d;border-radius:10px;padding:12px 16px;margin-bottom:16px">
      <b style="color:#e6edf3">기록 넣기</b>
      <div class="ts" style="margin:4px 0 8px">증권사 체결 내역을 그대로 복사해 붙여넣으세요(같은 체결은 두 번 안 들어갑니다). 한 줄씩 직접 쓸 때는
        <b style="color:#c9d1d9">10/5 한양디지텍 매수 100 21500</b>처럼 쓰면 됩니다(날짜를 빼면 아래 날짜). 사진은 Claude한테 보내면 대신 넣어 드립니다.</div>
      <textarea id="jr-text" rows="7" style="width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:8px;border-radius:6px;font-family:monospace;font-size:12px"></textarea>
      <div style="display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap">
        <input id="jr-date" type="date" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:5px 8px;border-radius:6px">
        <button class="btn btn-sm" onclick="jrImport(true)">미리보기</button>
        <button class="btn btn-sm" onclick="jrImport(false)" style="border-color:#238636;color:#3fb950">저장</button>
        <span id="jr-import-msg" class="ts"></span>
      </div>
      <div id="jr-preview" style="margin-top:8px;font-size:12px"></div>
    </div>

    <div id="jr-cards" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px"></div>
    <div id="jr-insights" style="border:1px solid #30363d;border-radius:10px;padding:10px 14px;margin-bottom:16px;font-size:13px;line-height:1.7"></div>

    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px" id="jr-groupbtns"></div>
    <table class="pb-table" style="margin-bottom:18px">
      <thead><tr><th id="jr-gname">구분</th><th>건수</th><th>이긴 비율</th><th>평균</th><th>평균 이익 / 손실</th><th>손익</th></tr></thead>
      <tbody id="jr-group"></tbody>
    </table>

    <div id="jr-holding"></div>

    <div style="font-size:12px;color:#8b949e;margin:6px 0">📒 청산 기록
      <label style="margin-left:8px"><select id="jr-kindf" onchange="jrRenderTrips()" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:2px 6px"><option value="">전체</option></select></label></div>
    <table class="pb-table" style="margin-bottom:18px">
      <thead><tr><th>종목</th><th>유형</th><th>산 날 → 판 날</th><th>매수 → 매도</th><th>수익률</th><th>산 날 상태</th></tr></thead>
      <tbody id="jr-trips"></tbody>
    </table>

    <details style="margin-bottom:16px">
      <summary style="cursor:pointer;color:#8b949e;font-size:12.5px">체결 내역 보기 · 근거 적기 · 삭제</summary>
      <div class="ts" style="margin:8px 0">매수 줄에 근거를 고르면 분석의 "내 근거별"에 반영됩니다. "장투"를 고르면 분석에서 빠집니다. 유형이 틀렸으면 바꿀 수 있습니다.</div>
      <div style="margin-bottom:8px;font-size:12px">분석에서 뺄 종목(코드나 이름, 쉼표): <input id="jr-excl" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:6px;min-width:220px"> <button class="btn btn-sm" onclick="jrSaveExcl()">저장</button></div>
      <table class="pb-table"><thead><tr><th>날짜</th><th>구분</th><th>종목</th><th>수량·단가</th><th>근거</th><th>유형</th><th></th></tr></thead>
        <tbody id="jr-execs"></tbody></table>
    </details>
  </div>
</div>

<!-- 섹터 수급 탭 -->
<div id="panel-sector" class="panel content">

  <!-- 순환매 모니터 -->
  <div style="margin-bottom:20px">
    <div style="font-size:12px;color:#8b949e;margin-bottom:6px;letter-spacing:.06em">🔄 순환매 모니터 (섹터 16개) <span class="ts" id="rot-info"></span></div>
    <p class="lead">지금 어느 섹터에 돈이 붙었나를 보는 표. 다음에 어디가 오를지 맞히는 용도는 아닙니다.</p>
    <details class="why"><summary>근거 보기</summary>
      272개 테마를 16개 섹터로 묶음. <b style="color:#f85149">과열</b> = 섹터 안 종목 중 20일선보다 20%↑ 뜬 종목이 20% 이상, <b style="color:#d29922">주의</b> = 10~20%.
      3년: 이 비율 0~5% 섹터는 20일 뒤 +0.1%p, 10~20% -0.3%p, 20~30% -1.7%p, 30%↑ -3.1%p. 상위 3 섹터 + 그날 거래대금 1.2배의 거래 실린 양봉 종베 +0.94%(섹터 밖 +0.28%).
      다음 10~20일 앞설 섹터는 거의 못 맞힘(-0.2%p). 섹터 밖에서 돈이 반복해 들어오는 테마는 주도가 될 확률이 3~4배지만, 들어온 날 사는 건 평균 이득이 없었습니다.
    </details>
    <table>
      <thead><tr><th>섹터</th><th>20일 상승 (순위)</th><th>확산 (20일선 위)<br><span class="ts">+20% 넘게 뜬 종목</span></th><th>거래대금 (평소 대비)</th><th>오늘</th><th>오늘 돈 붙은 종목 (거래 2배↑)</th></tr></thead>
      <tbody id="rot-body"><tr><td colspan="6" style="color:#8b949e;text-align:center;padding:16px">로딩 중…</td></tr></tbody>
    </table>
  </div>

  <!-- 오늘 강한 테마 (실시간) -->
  <div style="margin-bottom:20px">
    <div style="font-size:12px;color:#8b949e;margin-bottom:8px;letter-spacing:.06em">🔥 오늘 강한 테마 (실시간 · 1분마다 갱신) <span class="ts" id="live-theme-info"></span></div>
    <table>
      <thead><tr><th>테마</th><th>오늘 등락</th><th>상승 비율</th><th title="그 테마 종목 거래대금 합계 / 직전 20거래일 평균 (DB 최근 거래일 기준)">거래대금<br><span class="ts" id="live-theme-tvdate"></span></th><th>주도주</th></tr></thead>
      <tbody id="live-theme-body"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:16px">로딩 중…</td></tr></tbody>
    </table>
  </div>

  <details class="why" style="margin-top:8px"><summary>외국인·기관 수급 테마 표 보기 (3년 검증 안 된 참고용)</summary>
  <!-- 매집 감지 테마 -->
  <div style="margin:10px 0 20px">
    <div style="font-size:12px;text-transform:uppercase;color:#8b949e;margin-bottom:8px;letter-spacing:.06em">🕵️ 매집 감지 테마 (수급↑ 주가↔)</div>
    <table id="sec-stealth-table">
      <thead><tr>
        <th>테마</th><th>분류</th>
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

  <!-- 전체 테마 수급 랭킹 -->
  <div>
    <div style="font-size:12px;text-transform:uppercase;color:#8b949e;margin-bottom:8px;letter-spacing:.06em">📊 전체 테마 수급 랭킹 (<span id="sec-rank-label">스텔스 매집순</span>)</div>
    <table id="sec-surged-table">
      <thead><tr>
        <th>테마</th><th>분류</th><th>외국인</th><th>기관</th><th>합산</th><th>평균등락</th><th>수급점수</th><th>상태</th>
      </tr></thead>
      <tbody id="sec-surged-body"><tr><td colspan="8" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
    </table>
  </div>
  </details>

  <!-- 테마 종목 모달 -->
  <div class="modal-bg" id="sector-modal-bg" onclick="if(event.target===this)closeSectorModal()">
    <div class="modal">
      <span class="close-btn" onclick="closeSectorModal()">✕</span>
      <h2 id="sector-modal-title">테마 소속 종목</h2>
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
<div id="panel-candidates" class="panel content">
  <div id="pb-market" hidden style="border-radius:10px;padding:12px 16px;margin-bottom:14px;border:1px solid #30363d"></div>
  <p class="lead">불플래그 · 상승삼각형 · 기준봉 눌림 · 장대음봉도지 중 하나라도 해당하는 종목. 손절선까지 <b style="color:#3fb950">3~6%</b>가 적정.</p>
  <div class="toolbar" style="margin-bottom:12px">
    <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#8b949e">
      최소 시가총액(억원)
      <input type="number" id="cd-min-cap" value="0" min="0" step="100" onchange="loadCandidates()"
             style="width:90px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px">
    </label>
    <select id="cd-sort" onchange="renderCandidates()">
      <option value="value">거래대금순</option>
      <option value="cap">시총순</option>
      <option value="turnover">회전율순</option>
      <option value="up">등락률순</option>
    </select>
    <input id="cd-industry" list="cd-industry-list" placeholder="업종 (예: 전기전자, 반도체)" oninput="renderCandidates()"
           style="width:190px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px">
    <datalist id="cd-industry-list"></datalist>
    <select id="cd-pattern" onchange="renderCandidates()">
      <option value="">모든 모양</option>
      <option value="불플래그">불플래그</option>
      <option value="상승삼각형">상승삼각형</option>
      <option value="기준봉 눌림">기준봉 눌림</option>
      <option value="장대음봉도지">장대음봉도지</option>
    </select>
    <button class="btn btn-gray btn-sm" onclick="loadCandidates()">⟳ 새로고침</button>
    <span class="ts" id="cd-info"></span>
  </div>
  <table class="pb-table">
    <thead><tr>
      <th>종목</th><th>업종 · 테마</th><th>모양</th><th>현재가 · 거래대금</th><th>손절선</th>
    </tr></thead>
    <tbody id="cd-body"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
  <div style="margin-top:26px">
    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:8px">
      <b style="font-size:15px;color:#e6edf3">🔥 대량거래 관심종목</b>
      <select id="vr-stage" onchange="renderVolumeRecords()">
        <option value="live">숨고르기 · 신규 · 진행 중</option>
        <option value="숨고르기">숨고르기만</option>
        <option value="신규">신규만</option>
        <option value="설거지">설거지만</option>
        <option value="">설거지·무너짐 포함 전체</option>
      </select>
      <span class="ts" id="vr-info"></span>
      <label style="display:flex;align-items:center;gap:5px;font-size:13px;color:#c9d1d9;cursor:pointer"><input type="checkbox" id="vr-signal" onchange="renderVolumeRecords()"> 🎯 진입 신호만</label>
    </div>
    <p class="lead">몇 년 만의 최대 거래대금이 터진 종목. <b>터진 날 사지 말고</b> 숨고르기 뒤 🎯 돌려세우는 봉에서 보세요. 손절선 = 신기록 전날 종가.</p>
    <details class="why"><summary>근거 · 단계 설명 · 파는 법</summary>
      <b>신기록</b> = 최근 4개월 안에 평소 10배↑ 거래대금 + 전날 대비 +5% 양봉(리츠·스팩·ETF 제외).
      3년: 터진 날 사면 20일 뒤 중간 <b style="color:#f85149">-7%</b>, 대신 95%가 20일 안에 더 높은 가격을 찍음(중간 +15%).<br>
      <b style="color:#3fb950">숨고르기</b> = 거래가 마르며 기준선 지킴 · <b>무너짐</b> = 기준선 아래이거나 한 번이라도 -15% 아래 마감 · <b style="color:#f85149">설거지</b> = 다음 1~2일 더 큰 거래의 윗꼬리 음봉(20일 뒤 중간 -12%).<br>
      <b style="color:#e3b341">🎯 진입 신호</b> = 숨고르기 중 +3% 양봉·거래 2배 + 시장 상승·횡보 → 40일 뒤 시장 대비 +1.9%p(하락장은 -5.8%p), 📈 실적까지 겹치면 +7.8%p(31건).<br>
      <b>파는 법</b>: 그냥 40일 보유(중간 -2.0%)보다 <b>+10%에 절반 + 나머지 고점 대비 -8% 이탈</b>(중간 +3.8%, 수익 69%)이 안정적, 시초 +5% 갭엔 덜어내기(+7.3%).
    </details>
    <table class="pb-table">
      <thead><tr><th>종목</th><th>단계</th><th>신기록일</th><th>그 뒤 최고</th><th>지금</th></tr></thead>
      <tbody id="vr-body"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
    </table>
  </div>
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
  // 실적 개선 탭은 2026-10-04 숨김 (데이터는 📈 실적 표시로 계속 쓴다, /earnings 주소는 그대로)
  const tabs = ['jongbe','candidates','sector','journal','screener','heatmap','discussion','suggest'];
  if(!tabs.includes(id))return;
  try{ history.replaceState(null,'',id==='jongbe'?location.pathname:'#'+id); }catch(e){}   // 새로고침해도 이 탭에 남게
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',tabs[i]===id));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+id).classList.add('active');
  if(id==='screener')loadTopValue();
  if(id==='jongbe')loadJongbe();
  if(id==='journal')loadJournal();
  if(id==='sector'){loadSector();loadLiveThemes();loadRotation();}
  if(id==='heatmap')loadHeatmap();
  if(id==='candidates')loadCandidates();
  if(id==='suggest')document.getElementById('suggest-frame').src='/suggestions';
  if(id==='discussion'&&!document.getElementById('discussion-frame').src)document.getElementById('discussion-frame').src='/discussion';
}

// ── 오늘 강한 테마 (실시간) ──────────────────────────────────
// ── 종베 후보 ─────────────────────────────────────────────────
let _jbData=null;
async function loadJongbe(){
  let d=null;
  try{ d=await fetch(`${API}/screener/jongbe`).then(r=>r.ok?r.json():null); }catch(e){}
  _jbData=d;
  try{ const mc=localStorage.getItem('jb-mincap'); if(mc!==null) document.getElementById('jb-mincap').value=mc;
       const sf=localStorage.getItem('jb-safe'); if(sf!==null) document.getElementById('jb-safe').checked=sf==='1'; }catch(e){}
  const mk=document.getElementById('jb-market');
  if(!d){ mk.textContent='불러오지 못했습니다'; return; }
  const st=(d.market&&d.market.state)||'-';
  mk.style.background=d.market_ok?'rgba(63,185,80,.10)':'rgba(248,81,73,.12)';
  mk.style.borderColor=d.market_ok?'#3fb950':'#f85149';
  mk.innerHTML=d.market_ok?`<b style="color:#3fb950">시장 ${st}</b> <span style="color:#e6edf3;margin-left:6px">종베 가능</span>`
    :`<b style="color:#f85149">시장 ${st} · 종베 쉬기</b> <span class="ts">3년 확인: 하락장 종베는 거의 0(+0.12%)</span>`;
  document.getElementById('jb-date').textContent=`· ${d.trading_date} 장 마감 기준`;
  const stc={'과열':'#f85149','주의':'#d29922'};
  document.getElementById('jb-fams').innerHTML=d.families.map(f=>{
    const isHot=d.hot.includes(f.family);
    return `<span style="padding:6px 10px;border:1px solid ${isHot?'#e3b341':'#30363d'};border-radius:8px;font-size:12.5px">
      <b style="color:${isHot?'#e6edf3':'#8b949e'}">${f.rank}. ${f.family}</b> <span class="ts">20일 ${f.ret20_pct>=0?'+':''}${f.ret20_pct}%</span>
      · <span style="color:${f.money?'#3fb950':'#8b949e'}">거래 ${f.tv_x.toFixed(2)}배${f.money?' 돈 몰림':''}</span>
      ${f.status?` · <b style="color:${stc[f.status]}">${f.status}</b>`:''}</span>`;}).join('');
  renderJongbe();
  try{ const saved=localStorage.getItem('jb-q'); if(saved&&!document.getElementById('jb-q').value){document.getElementById('jb-q').value=saved; jbCheck();} }catch(e){}
  loadJongbePerf();
  if(_vrData) renderLimitUp(); else loadVolumeRecords();
}
// 시총 기준(억 원) 미만은 숨긴다. 시총을 모르는 종목(0)은 그대로 보여 준다.
function renderJongbe(){
  const d=_jbData; if(!d) return;
  const min=parseFloat(document.getElementById('jb-mincap').value)*1e8||0;
  const okCap=x=>!min||!x.market_cap||x.market_cap>=min;
  const safe=document.getElementById('jb-safe').checked, showB=document.getElementById('jb-showb').checked;
  const okSafe=x=>!safe||((x.gap20_pct==null||x.gap20_pct<20)&&x.change_pct<12);
  const pool=d.items.filter(x=>okCap(x)&&okSafe(x)), lim=d.limit_up.filter(okCap);
  const nA=pool.filter(x=>x.grade==='A').length, nB=pool.length-nA;
  const items=pool.filter(x=>showB||x.grade==='A');
  document.getElementById('jb-count').textContent=`A ${nA}개 · B ${nB}개 (전체 후보 ${d.items.length}개)`;
  const body=document.getElementById('jb-body');
  if(!items.length){ body.innerHTML=`<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">${nB&&!showB?`오늘은 A등급이 없습니다. <a href="#" onclick="document.getElementById('jb-showb').checked=true;renderJongbe();return false" style="color:#58a6ff">B등급 ${nB}개 보기</a> (3년 다음 날 평균 +0.48%, A는 +0.94%)`:'오늘은 조건에 맞는 종목이 없습니다'}</td></tr>`; }
  else body.innerHTML=items.map(x=>`<tr style="cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','')">
    <td><b>${x.name}</b> <span style="color:#8b949e;font-size:11px">${x.code}</span>${x.earn_up?' <span style="color:#3fb950;font-size:11px;border:1px solid #238636;border-radius:8px;padding:0 5px">📈 실적</span>':''}${x.leader?' <span style="color:#e3b341;font-size:11px">👑 대장</span>':''}${x.record_today?' <span style="color:#f85149;font-size:11px" title="오늘 몇 년 만의 최대 거래대금">🔔 거래대금 신기록</span>':''}${x.vr_stage&&x.vr_stage!=='무너짐'&&!x.record_today?` <span style="font-size:11px;color:${x.vr_signal?'#e3b341':'#8b949e'}" title="대량거래 관심종목 단계 (스윙 관점)">🔥 ${x.vr_signal?'진입 신호':x.vr_stage}</span>`:''}${x.market_cap?`<br><span class="ts">시총 ${cdWon(x.market_cap)}</span>`:''}</td>
    <td data-label="등급"><b style="color:${x.grade==='A'?'#3fb950':'#c9d1d9'}">${x.grade}</b><br><span class="ts">${x.grade==='A'?'섹터 돈 몰림':'섹터 돈 몰림 아님'}</span></td>
    <td data-label="그날 봉"><span style="color:#f85149">+${x.change_pct}%</span> · 거래 ${x.tv_x}배<br><span class="ts" style="color:${x.upper_pct<=30?'#3fb950':'#8b949e'}">윗꼬리 ${x.upper_pct}%</span> · <span class="ts">${cdWon(x.value)}</span></td>
    <td data-label="섹터" style="font-size:12px">${x.families.join(', ')}</td>
    <td data-label="종가" style="text-align:right">${x.close.toLocaleString()}원${gapTag(x.gap20_pct)}</td>
  </tr>`).join('');
  const sw=(d.swing||[]).filter(okCap);
  document.getElementById('jb-swing-info').textContent=`${sw.length}개 · 붙음 ${sw.filter(x=>x.state==='붙음').length} · 막 넘음 ${sw.filter(x=>x.state==='막 넘음').length}`;
  document.getElementById('jb-swing').innerHTML=sw.length?sw.map(x=>`<tr style="cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','')">
    <td><b>${x.name}</b> <span style="color:#8b949e;font-size:11px">${x.code}</span>${x.earn_up?' <span style="color:#3fb950;font-size:11px;border:1px solid #238636;border-radius:8px;padding:0 5px">📈 실적</span>':''}${x.vr_stage&&x.vr_stage!=='무너짐'?` <span class="ts">🔥 ${x.vr_stage}</span>`:''}${x.market_cap?`<br><span class="ts">시총 ${cdWon(x.market_cap)}</span>`:''}</td>
    <td data-label="박스 상단 대비"><b style="color:${x.state==='막 넘음'?'#f85149':'#d29922'}">${x.state}</b> ${x.pos_pct>=0?'+':''}${x.pos_pct}%${x.loud?' <span title="거래 2배 넘게 터지며 넘음 — 3년 확인상 약했음">📢</span>':''}<br><span class="ts">60일 고점 ${x.box_top.toLocaleString()}원</span></td>
    <td data-label="오늘"><span style="color:${x.change_pct>=0?'#f85149':'#58a6ff'}">${x.change_pct>=0?'+':''}${x.change_pct}%</span> · 거래 ${x.tv_x}배</td>
    <td data-label="섹터" style="font-size:12px">${x.families.join(', ')}</td>
    <td data-label="종가" style="text-align:right">${x.close.toLocaleString()}원${gapTag(x.gap20_pct)}</td>
  </tr>`).join(''):'<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:16px">오늘은 해당 종목이 없습니다</td></tr>';
  document.getElementById('jb-limit').innerHTML=lim.length?`상한가 (체결 어려움 주의): ${lim.map(x=>`<b style="color:#e6edf3;cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','')">${x.name}</b>${x.record_today?' <span style="color:#f85149;font-size:11px">🔔 신기록 · 3년 다음 날 시가 평균 +5.6%</span>':''}`).join(' · ')}`:'';
}
async function jbCheck(){
  const q=document.getElementById('jb-q').value.trim();
  try{ localStorage.setItem('jb-q',q); }catch(e){}
  const el=document.getElementById('jb-check');
  if(!q){ el.innerHTML=''; return; }
  const d=await fetch(`${API}/screener/jongbe/check?q=${encodeURIComponent(q)}`).then(r=>r.ok?r.json():null).catch(()=>null);
  if(!d){ el.textContent='확인 실패'; return; }
  el.innerHTML=d.items.map(x=>{
    if(!x.found) return `<div class="ts">${x.query}: 못 찾음</div>`;
    const ok=Object.values(x.checks).filter(Boolean).length, tot=Object.keys(x.checks).length;
    return `<div style="padding:6px 0;border-top:1px solid #21262d"><b style="color:#e6edf3">${x.name}</b> <span class="ts">${x.change_pct>=0?'+':''}${x.change_pct}% · 거래 ${x.tv_x}배 · 윗꼬리 ${x.upper_pct}%</span>${gapTag(x.gap20_pct)}
      <b style="margin-left:6px;color:${ok===tot?'#3fb950':ok>=tot-2?'#d29922':'#f85149'}">${ok}/${tot}</b><br>
      <span style="font-size:12px">${Object.entries(x.checks).map(([k,v])=>`${v?'✅':'❌'} ${k}`).join(' &nbsp; ')}</span>
      <span class="ts"> · 섹터 ${x.families.join(', ')||'없음'}${x.best_rank?` (최고 ${x.best_rank}위)`:''}</span>
      <br><span class="ts">같이 움직인 섹터(최근 60일): ${(x.comove||[]).map(c=>`${c.family} ${c.corr}`).join(' · ')}</span>
      <select class="jb-ov" data-code="${x.code}" style="margin-left:6px;font-size:11.5px;padding:1px 4px" title="네이버 테마 분류에 더해 이 섹터에도 넣습니다">
        <option value="">섹터 직접 지정 안 함</option>${(d.families||[]).map(f=>`<option value="${f}"${x.override===f?' selected':''}>${f}에도 넣기</option>`).join('')}
      </select></div>`;}).join('');
  el.querySelectorAll('.jb-ov').forEach(sel=>sel.onchange=async()=>{
    const r=await fetch(`${API}/sectors/override`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stock:sel.dataset.code,sector:sel.value})});
    if(!r.ok){alert('저장 실패');return;}
    await loadJongbe(); jbCheck();
  });
}
async function loadJongbePerf(){
  const el=document.getElementById('jb-perf');
  const d=await fetch(`${API}/screener/jongbe/performance`).then(r=>r.ok?r.json():null).catch(()=>null);
  if(!d){ el.textContent='불러오지 못했습니다'; return; }
  const gs=Object.entries(d.summary);
  if(!gs.length){ el.textContent='아직 기록이 없습니다. 장 마감 후 18:20부터 매일 쌓이고, 다음 거래일 시세가 들어오면 결과가 보입니다.'; return; }
  el.innerHTML=gs.map(([g,s])=>`<b style="color:#e6edf3">${g}</b> ${s.count}건 · 수익 ${s.win_pct}% · 평균 ${s.avg_rule_pct>=0?'+':''}${s.avg_rule_pct}% (갭상승이면 시가·아니면 종가) · 다음 날 고가 평균 +${s.avg_high_pct}%`).join('<br>')
    +'<div style="margin-top:6px">'+d.items.slice(0,40).map(x=>`<span style="display:inline-block;margin:0 10px 4px 0">${x.date.slice(5)} ${x.name}(${x.grade}) <span style="color:${x.rule_pct>=0?'#f85149':'#58a6ff'}">${x.rule_pct>=0?'+':''}${x.rule_pct}%</span> <span class="ts">고가 +${x.high_pct}%</span></span>`).join('')+'</div>';
}

// ── 매매 일지 ─────────────────────────────────────────────────
let _jr=null, _jrGroup='by_kind';
function jrAuth(){ try{ return {o:localStorage.getItem('jr-owner')||'', p:localStorage.getItem('jr-pin')||''}; }catch(e){ return {o:'',p:''}; } }
function jrH(){ const a=jrAuth(); return {'X-Owner':encodeURIComponent(a.o),'X-Pin':encodeURIComponent(a.p),'Content-Type':'application/json'}; }
function jrToggle(id){ const el=document.getElementById(id); el.style.display=el.style.display==='none'?'block':'none'; }
function jrPct(v){ return v==null?'-':`<span style="color:${v>0?'#f85149':v<0?'#58a6ff':'#8b949e'}">${v>0?'+':''}${v}%</span>`; }
function jrWon(v){ return `<span style="color:${v>0?'#f85149':v<0?'#58a6ff':'#8b949e'}">${v>0?'+':''}${Math.round(v).toLocaleString()}원</span>`; }
async function loadJournal(){
  const a=jrAuth();
  if(!a.o||!a.p){
    document.getElementById('jr-login').style.display='block'; document.getElementById('jr-main').style.display='none';
    const d=await fetch(`${API}/journal/owners`).then(r=>r.json()).catch(()=>({owners:[]}));
    document.getElementById('jr-owners').innerHTML=d.owners.map(o=>`<option value="${o}">`).join('');
    if(a.o) document.getElementById('jr-owner').value=a.o;
    return;
  }
  const r=await fetch(`${API}/journal`,{headers:jrH()}).catch(()=>null);
  if(!r||!r.ok){ if(r&&(r.status===401||r.status===429)){ try{localStorage.removeItem('jr-pin');}catch(e){} } document.getElementById('jr-login-msg').textContent=r?'다시 입력해 주세요':'불러오지 못했습니다'; jrShowLogin(); return; }
  _jr=await r.json();
  document.getElementById('jr-login').style.display='none'; document.getElementById('jr-main').style.display='block';
  document.getElementById('jr-who').textContent=`${a.o}의 매매 일지`;
  document.getElementById('jr-asof').textContent=_jr.as_of?`· 시세 ${_jr.as_of} 기준`:'';
  if(!document.getElementById('jr-date').value) document.getElementById('jr-date').value=_jr.as_of||'';
  jrRender();
}
function jrShowLogin(){ document.getElementById('jr-login').style.display='block'; document.getElementById('jr-main').style.display='none'; }
async function jrLogin(create){
  const o=document.getElementById('jr-owner').value.trim(), p=document.getElementById('jr-pin').value;
  const msg=document.getElementById('jr-login-msg');
  if(!o||p.length<4){ msg.textContent='이름과 4자 이상 비밀번호를 넣어 주세요'; return; }
  const r=await fetch(`${API}/journal/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({owner:o,pin:p,create:!!create})}).catch(()=>null);
  if(r&&r.status===404){
    msg.innerHTML=`처음 쓰는 이름입니다. 이 비밀번호로 <b style="color:#3fb950;cursor:pointer;text-decoration:underline" onclick="jrLogin(true)">새로 만들기</b> (잊으면 되찾을 수 없으니 기억해 두세요)`;
    return;
  }
  if(!r||!r.ok){ const e=r?await r.json().catch(()=>({})):{}; msg.textContent=e.detail||'실패'; return; }
  try{ localStorage.setItem('jr-owner',o); localStorage.setItem('jr-pin',p); }catch(e){}
  document.getElementById('jr-pin').value=''; msg.textContent='';
  loadJournal();
}
function jrLogout(){ try{ localStorage.removeItem('jr-pin'); }catch(e){} _jr=null; loadJournal(); }
function jrRender(){
  const s=_jr.summary, all=s.all||{count:0};
  const card=(t,v,sub)=>`<div style="border:1px solid #30363d;border-radius:10px;padding:10px 14px;min-width:110px"><div class="ts">${t}</div><div style="font-size:17px;font-weight:600;color:#e6edf3">${v}</div>${sub?`<div class="ts">${sub}</div>`:''}</div>`;
  document.getElementById('jr-cards').innerHTML=!all.count?'<div class="ts">아직 청산된 매매가 없습니다. 위 "＋ 기록 넣기"로 체결 내역을 붙여넣으세요.</div>':
    card('청산',`${all.count}건`,'')+card('이긴 비율',`${all.win_pct}%`,'')+card('평균 수익률',jrPct(all.avg_pct),`이익 ${all.avg_win_pct??'-'}% · 손실 ${all.avg_loss_pct??'-'}%`)
    +card('손익 합계',jrWon(all.pnl),`투입 대비 ${all.ret_on_cost_pct}%`)+card('최고 / 최악',`${jrPct(all.best_pct)} / ${jrPct(all.worst_pct)}`,'');
  document.getElementById('jr-insights').innerHTML='<b style="color:#e6edf3">🔎 숫자로 보이는 것</b><br>'+(_jr.insights.length?_jr.insights.map(x=>'· '+x).join('<br>'):'<span class="ts">아직 없음</span>');
  const groups={by_kind:'유형별',by_state:'산 날 상태별',by_user_tag:'내 근거별',by_family:'섹터별',by_month:'월별'};
  document.getElementById('jr-groupbtns').innerHTML=Object.entries(groups).map(([k,v])=>`<button class="btn btn-sm" style="${k===_jrGroup?'border-color:#58a6ff;color:#58a6ff':''}" onclick="_jrGroup='${k}';jrRender()">${v}</button>`).join('');
  document.getElementById('jr-gname').textContent=groups[_jrGroup];
  const g=Object.entries(s[_jrGroup]||{}).sort((a,b)=>_jrGroup==='by_month'?b[0].localeCompare(a[0]):b[1].count-a[1].count);
  document.getElementById('jr-group').innerHTML=g.length?g.map(([k,v])=>`<tr><td><b>${k}</b></td><td data-label="건수">${v.count}</td><td data-label="이긴 비율">${v.win_pct}%</td><td data-label="평균">${jrPct(v.avg_pct)}</td>
    <td data-label="평균 이익 / 손실"><span class="ts">${v.avg_win_pct??'-'}% / ${v.avg_loss_pct??'-'}%</span></td><td data-label="손익" style="text-align:right">${jrWon(v.pnl)}</td></tr>`).join('')
    :'<tr><td colspan="6" class="ts" style="text-align:center;padding:14px">없음</td></tr>';
  const h=_jr.holding||[];
  document.getElementById('jr-holding').innerHTML=h.length?`<div style="font-size:12px;color:#8b949e;margin:6px 0">📦 아직 들고 있는 것 (일지에 산 기록이 있는 물량만)</div><div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">`+
    h.map(x=>`<span style="border:1px solid #30363d;border-radius:8px;padding:6px 10px;font-size:12.5px;cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','')"><b style="color:#e6edf3">${x.name}</b> <span class="ts">${x.buy_date.slice(5)} ${x.qty}주 @${Math.round(x.price).toLocaleString()}</span> ${jrPct(x.eval_pct)}</span>`).join('')+'</div>':'';
  const kf=document.getElementById('jr-kindf'), kinds=[...new Set(_jr.trips.map(t=>t.kind))];
  const cur=kf.value; kf.innerHTML='<option value="">전체</option>'+kinds.map(k=>`<option ${k===cur?'selected':''}>${k}</option>`).join('');
  jrRenderTrips();
  document.getElementById('jr-excl').value=(_jr.cfg.exclude||[]).map(c=>{ const e=_jr.executions.find(e=>e.code===c); return e?e.name:c; }).join(', ');
  const tagOpt=(sel)=>'<option value="">-</option>'+_jr.user_tags.map(t=>`<option ${t===sel?'selected':''}>${t}</option>`).join('');
  const kindOpt=(sel)=>'<option value="">자동</option>'+_jr.kinds.map(t=>`<option ${t===sel?'selected':''}>${t}</option>`).join('');
  const sel='background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:2px 4px;font-size:12px';
  document.getElementById('jr-execs').innerHTML=_jr.executions.slice(0,400).map(e=>`<tr><td>${e.date.slice(5)} <span class="ts">${e.seq}</span></td>
    <td data-label="구분" style="color:${e.side==='매수'?'#f85149':'#58a6ff'}">${e.side}</td><td data-label="종목">${e.name}</td>
    <td data-label="수량·단가">${e.qty}주 · ${Math.round(e.price).toLocaleString()}</td>
    <td data-label="근거">${e.side==='매수'?`<select style="${sel}" onchange="jrEdit(${e.id},{tag:this.value})">${tagOpt(e.tag)}</select>`:''}</td>
    <td data-label="유형">${e.side==='매수'?`<select style="${sel}" onchange="jrEdit(${e.id},{kind:this.value})">${kindOpt(e.kind)}</select>`:''}</td>
    <td style="text-align:right"><span style="cursor:pointer;color:#8b949e" title="삭제" onclick="jrDel(${e.id})">✕</span></td></tr>`).join('');
}
function jrRenderTrips(){
  const k=document.getElementById('jr-kindf').value;
  const ts=_jr.trips.filter(t=>!k||t.kind===k);
  const tagc={'거래 실린 양봉':'#3fb950','뜨거운 섹터':'#e3b341','섹터 돈 몰림':'#e3b341','박스 상단':'#58a6ff','조용한 날':'#f85149','빠진 날':'#f85149','윗꼬리 긴 날':'#f85149','과열(이격 20%↑)':'#f85149','하락장':'#f85149','섹터 밖':'#8b949e'};
  document.getElementById('jr-trips').innerHTML=ts.length?ts.slice(0,300).map(t=>{
    const st=t.state;
    const tags=st?st.tags.map(x=>`<span style="color:${tagc[x]||'#8b949e'};border:1px solid #30363d;border-radius:8px;padding:0 5px;margin:0 3px 3px 0;display:inline-block">${x}</span>`).join(''):'<span class="ts">-</span>';
    const det=st?`<br><span class="ts">그날 ${st.change_pct>0?'+':''}${st.change_pct}% · 거래 ${st.tv_x??'-'}배 · 윗꼬리 ${st.upper_pct}% · 이격 ${st.gap20_pct??'-'}% · 종가 대비 ${st.vs_close_pct>0?'+':''}${st.vs_close_pct}%에 삼${st.families.length?' · '+st.families.join(', '):''}</span>`:'';
    return `<tr style="${t.excluded?'opacity:.45':''}"><td><b style="cursor:pointer" onclick="openChartModal('${t.code}','${t.name}','')">${t.name}</b>${t.user_tags.length?` <span class="ts">${t.user_tags.join(', ')}</span>`:''}${t.excluded?' <span class="ts">(분석 제외)</span>':''}</td>
      <td data-label="유형">${t.kind}</td><td data-label="산 날 → 판 날">${t.buy_date?t.buy_date.slice(5):'?'} → ${t.sell_date.slice(5)}${t.days!=null?` <span class="ts">${t.days}일</span>`:''}</td>
      <td data-label="매수 → 매도">${Math.round(t.buy_px).toLocaleString()} → ${Math.round(t.sell_px).toLocaleString()} <span class="ts">${t.qty}주</span></td>
      <td data-label="수익률">${jrPct(t.pct)}<br>${jrWon(t.pnl)}</td><td data-label="산 날 상태" style="font-size:11.5px;max-width:340px">${tags}${det}</td></tr>`;}).join('')
    :'<tr><td colspan="6" class="ts" style="text-align:center;padding:14px">없음</td></tr>';
}
async function jrImport(preview){
  const text=document.getElementById('jr-text').value, msg=document.getElementById('jr-import-msg');
  if(!text.trim()){ msg.textContent='붙여넣은 내용이 없습니다'; return; }
  const r=await fetch(`${API}/journal/import`,{method:'POST',headers:jrH(),body:JSON.stringify({text,date:document.getElementById('jr-date').value,preview})}).catch(()=>null);
  if(!r||!r.ok){ msg.textContent='실패'; return; }
  const d=await r.json();
  const bad=d.bad.length?`<div style="color:#d29922;margin-top:4px">못 읽은 줄 ${d.bad.length}개: ${d.bad.slice(0,5).map(x=>x.replace(/</g,'&lt;')).join(' / ')}</div>`:'';
  if(preview){
    msg.textContent=`${d.rows.length}건 읽음`;
    document.getElementById('jr-preview').innerHTML=d.rows.slice(0,50).map(x=>`<span style="display:inline-block;margin:0 10px 3px 0">${x.trade_date.slice(5)} <span style="color:${x.side==='매수'?'#f85149':'#58a6ff'}">${x.side}</span> ${x.name} ${x.qty}주 @${Math.round(x.price).toLocaleString()}</span>`).join('')+(d.rows.length>50?' …':'')+bad;
    return;
  }
  msg.textContent=`${d.added}건 저장${d.skipped?` · 이미 있던 ${d.skipped}건 건너뜀`:''}`;
  document.getElementById('jr-preview').innerHTML=bad;
  if(d.added){ document.getElementById('jr-text').value=''; loadJournal(); }
}
async function jrEdit(id,body){ await fetch(`${API}/journal/${id}`,{method:'PATCH',headers:jrH(),body:JSON.stringify(body)}).catch(()=>null); loadJournal(); }
async function jrDel(id){ if(!confirm('이 체결을 지울까요?'))return; await fetch(`${API}/journal/${id}`,{method:'DELETE',headers:jrH()}).catch(()=>null); loadJournal(); }
async function jrSaveExcl(){
  const v=document.getElementById('jr-excl').value.split(',').map(x=>x.trim()).filter(Boolean);
  const codes=v.map(x=>{ const e=_jr.executions.find(e=>e.name===x||e.code===x); return e?e.code:x; });
  await fetch(`${API}/journal/config`,{method:'POST',headers:jrH(),body:JSON.stringify({exclude:codes})}).catch(()=>null);
  loadJournal();
}

async function loadRotation(){
  const body=document.getElementById('rot-body');
  try{
    const d=await fetch(`${API}/sectors/rotation`).then(r=>r.ok?r.json():null);
    if(!d||!d.items.length){body.innerHTML='<tr><td colspan="6" style="color:#8b949e;text-align:center;padding:16px">데이터 없음</td></tr>';return;}
    document.getElementById('rot-info').textContent=`· ${d.trading_date} 장 마감 기준`;
    const c=n=>n>0?'#f85149':n<0?'#58a6ff':'#8b949e';
    const sg=n=>(n>0?'+':'')+n;
    const badge={'과열':'<b style="color:#f85149;border:1px solid #f85149;border-radius:8px;padding:0 6px;font-size:11px">과열</b>','주의':'<b style="color:#d29922;border:1px solid #d29922;border-radius:8px;padding:0 6px;font-size:11px">주의</b>'};
    body.innerHTML=d.items.map(t=>{
      const mv=t.rank_10ago-t.rank;
      return `<tr>
      <td><b>${t.family}</b> ${badge[t.status]||''}<br><span class="ts">${t.count}종목</span></td>
      <td><b style="color:${c(t.ret20_pct)}">${sg(t.ret20_pct)}%</b> <span class="ts">${t.rank}위</span>${mv?` <span style="font-size:11px;color:${mv>0?'#3fb950':'#8b949e'}">${mv>0?'▲':'▼'}${Math.abs(mv)}</span>`:''}<br><span class="ts">5일 ${sg(t.ret5_pct)}%</span></td>
      <td>${t.breadth_pct}% <span class="ts">(10일 전 ${t.breadth_10ago}%)</span><br><span class="ts" style="color:${t.stretch_pct>=20?'#f85149':t.stretch_pct>=10?'#d29922':'#8b949e'}">+20% 넘게 뜬 종목 ${t.stretch_pct}% (10일 전 ${t.stretch_10ago}%)</span></td>
      <td><b style="color:${t.tv5_x>=1.1?'#f85149':t.tv5_x<0.9?'#58a6ff':'#c9d1d9'}">${t.tv5_x.toFixed(2)}배</b> <span class="ts">최근 5일 · 5일 정점 ${t.tv5_peak5.toFixed(2)}</span><br><span class="ts">오늘 ${t.tv1_x.toFixed(2)}배</span></td>
      <td style="color:${c(t.chg_pct)}">${sg(t.chg_pct.toFixed(1))}%</td>
      <td style="font-size:12px">${t.leaders.map(l=>`<span style="cursor:pointer" onclick="openChartModal('${l.code}','${l.name}','')">${l.name} <span style="color:${c(l.change_pct)}">${sg(l.change_pct)}%</span></span>`).join(' · ')||'<span class="ts">없음</span>'}</td>
    </tr>`}).join('');
  }catch(e){console.error(e);body.innerHTML='<tr><td colspan="6" style="color:#f85149;text-align:center;padding:16px">로딩 실패</td></tr>';}
}
async function loadLiveThemes(){
  const body=document.getElementById('live-theme-body');
  try{
    const d=await fetch(`${API}/sectors/live?limit=20`).then(r=>r.ok?r.json():null);
    if(!d||!d.items.length){body.innerHTML='<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:16px">시세를 받지 못했습니다</td></tr>';return;}
    document.getElementById('live-theme-tvdate').textContent=d.tv_date?`${d.tv_date.slice(5)} 평소 대비`:'';
    document.getElementById('live-theme-info').textContent=d.as_of?`· ${d.as_of.slice(5,10)} ${d.as_of.slice(11,16)} 기준`:'';
    const c=n=>n>0?'#f85149':n<0?'#58a6ff':'#8b949e';
    const pct=n=>`<span style="color:${c(n)}">${n>0?'+':''}${n.toFixed(2)}%</span>`;
    body.innerHTML=d.items.map(t=>`<tr style="cursor:pointer" onclick="openSectorModal(${t.sector_id},'${t.sector_name}')">
      <td><b>${t.sector_name}</b> <span class="ts">${t.count}종목</span></td>
      <td><b>${pct(t.avg_change_pct)}</b></td>
      <td><span style="display:inline-flex;align-items:center;gap:6px">${t.up_ratio}%<span style="display:inline-block;width:${Math.round(t.up_ratio*0.6)}px;height:5px;border-radius:3px;background:${t.up_ratio>=70?'#f85149':t.up_ratio>=50?'#d29922':'#8b949e'}"></span></span></td>
      <td>${t.tv_x==null?'—':`<b style="color:${t.tv_x>=1.5?'#f85149':t.tv_x>=1.1?'#d29922':'#8b949e'}">${t.tv_x.toFixed(2)}배</b>${t.tv_x>=1.5?' <span class="ts">돈 몰림</span>':''}`}</td>
      <td style="font-size:12px">${t.leaders.map(l=>`${l.name} ${pct(l.change_pct)}`).join(' · ')}</td>
    </tr>`).join('');
  }catch(e){console.error(e);}
}
setInterval(()=>{if(document.visibilityState==='visible'&&document.getElementById('panel-sector').classList.contains('active'))loadLiveThemes();},60000);

// ── 섹터 수급 ──────────────────────────────────────────────────
let _sectorData = [];
// 정렬은 표 머리(외국인·기관·스텔스점수)를 눌러 바꾼다. 위쪽 정렬·분류·새로고침·매핑 갱신 버튼은 2026-10-04 제거 (매핑은 매주 일요일 자동 갱신)
let _secSort = 'stealth';
const SEC_SORT_LABEL = {stealth:'스텔스 매집순',flow:'수급 점수순',foreign:'외국인 순매수순',inst:'기관 순매수순'};
function setSectorSort(s){_secSort=s;loadSector();}

async function loadSector(){
  try{
    const data=await fetch(`${API}/sectors/flow?sort=${_secSort}&limit=300`).then(r=>r.ok?r.json():[]);
    _sectorData=data;
    renderSector(data);
  }catch(e){console.error(e);}
}

function renderSector(data){
  // 고른 정렬 기준으로 두 표 모두 정렬 (매집 감지 표는 순매수·미급등 섹터만)
  const key={stealth:'stealth_score',flow:'flow_score',foreign:'foreign_net_buy',inst:'inst_net_buy'}[_secSort]||'stealth_score';
  const byKey=(a,b)=>(b[key]||0)-(a[key]||0);
  document.getElementById('sec-rank-label').textContent=SEC_SORT_LABEL[_secSort]||'';
  const stealth=data.filter(d=>d.combined_net_buy>0&&!d.is_surged).sort(byKey);
  const surged=[...data].sort(byKey);

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
    :'<tr><td colspan="8" style="color:#8b949e;text-align:center;padding:16px">매집 감지 테마 없음</td></tr>';

  document.getElementById('sec-surged-body').innerHTML=surged.length
    ?surged.map(d=>sRow(d,false)).join('')
    :'<tr><td colspan="8" style="color:#8b949e;text-align:center;padding:16px">테마 데이터 없음</td></tr>';
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
  loadVolumeRecords();   // 아래 대량거래 관심종목은 따로 동시에 불러온다
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

// 넓은 업종 이름 → 표준산업분류 업종명에 들어가는 단어 (backend/services/industry_map.py GROUPS와 같게)
const CD_GROUPS = {
  '전기전자':['반도체','전자부품','통신 및 방송 장비','컴퓨터 및 주변장치','영상 및 음향','전동기','전지','절연선','조명장치','전기장비','가정용 기기','측정, 시험'],
  '제약바이오':['의약품','의료용 물질','자연과학 및 공학 연구개발'],'의료기기':['의료용 기기'],'2차전지':['전지'],
  '화학':['화학','플라스틱','고무'],'기계':['기계 제조업'],'철강금속':['철강','금속'],'자동차':['자동차'],'조선':['선박'],
  '건설':['건설','건물'],'IT서비스':['소프트웨어','컴퓨터 프로그래밍','정보서비스','자료처리'],'금융':['금융','보험','은행','신탁'],
};
function cdMatch(it, terms){
  if(!terms.length) return true;
  const ind = it.industry||'';
  return terms.some(t=>{
    const g = CD_GROUPS[t];
    if(g && g.some(w=>ind.includes(w))) return true;
    return ind.includes(t) || (it.themes||[]).some(x=>x.includes(t)) || (it.sector_name||'').includes(t);
  });
}
// 20일선 이격도 표시: +30%↑ 과열, +20%↑ 주의 (3년 확인 기준)
function gapTag(g){
  if(g==null) return '';
  const col = g>=30?'#f85149':g>=20?'#d29922':'#8b949e';
  return ` <span style="font-size:11px;color:${col}" title="20일선 대비">${g>=30?'⚠과열 ':g>=20?'주의 ':''}이격 ${g>=0?'+':''}${g}%</span>`;
}
function cdWon(v){ return v>=1e12?(v/1e12).toFixed(1)+'조':Math.round(v/1e8).toLocaleString()+'억'; }
function renderCandidates(){
  const body = document.getElementById('cd-body');
  const d = _cdData;
  if(!d){ return; }
  const dl = document.getElementById('cd-industry-list');
  if(!dl.dataset.filled){
    const inds = [...new Set(d.items.map(x=>x.industry).filter(Boolean))].sort();
    dl.innerHTML = [...Object.keys(CD_GROUPS), ...inds].map(v=>`<option value="${v}">`).join('');
    dl.dataset.filled = '1';
  }
  const pat = document.getElementById('cd-pattern').value;
  const terms = document.getElementById('cd-industry').value.split(',').map(t=>t.trim()).filter(Boolean);
  const sortKey = document.getElementById('cd-sort').value;
  const val = {value:x=>x.trading_value||0, cap:x=>x.market_cap||0, turnover:x=>x.turnover_pct||0, up:x=>x.change_pct||0}[sortKey];
  const items = d.items
    .filter(it=>(!pat||it.patterns.some(p=>p.type===pat)) && cdMatch(it, terms))
    .sort((a,b)=>val(b)-val(a));
  document.getElementById('cd-info').textContent = d.trading_date ? `기준일: ${d.trading_date} · ${items.length}개${items.length!==d.items.length?' / 전체 '+d.items.length+'개':''}` : '';
  if(!items.length){
    body.innerHTML = '<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">조건에 맞는 종목이 없습니다</td></tr>';
    return;
  }
  const tagColor = {'불플래그':'#58a6ff','상승삼각형':'#bc8cff','기준봉 눌림':'#d29922','장대음봉도지':'#3fb950'};
  body.innerHTML = items.map(it=>{
    const indHtml = `<span style="font-size:12.5px">${it.industry||'업종 정보 없음'}</span>`
      + (it.sector_name?`<br><span class="ts">${it.sector_name} · 20일 ${it.sector_ret20>=0?'+':''}${it.sector_ret20}%</span>`:'');
    const pats = it.patterns.map(p=>`<span style="display:inline-block;margin:0 4px 3px 0;padding:1px 7px;border-radius:10px;border:1px solid ${tagColor[p.type]};color:${tagColor[p.type]};font-size:11.5px">${p.type}${p.grade?'·'+p.grade:''}</span><br><span class="ts">${p.detail}</span>`).join('<br>');
    return `<tr style="cursor:pointer" onclick="openChartModal('${it.code}','${it.name}','')">
      <td><b>${it.name}</b> <span style="color:#8b949e;font-size:11px">${it.code}</span>${it.earn_up?' <span style="color:#3fb950;font-size:11px;border:1px solid #238636;border-radius:8px;padding:0 5px" title="영업이익 +30%·매출 +10%, 120일 안 공시">📈 실적</span>':''}${it.market_cap?`<br><span class="ts">시총 ${cdWon(it.market_cap)}</span>`:''}</td>
      <td data-label="업종 · 테마">${indHtml}</td>
      <td data-label="모양" style="font-size:12px">${pats}</td>
      <td data-label="현재가" style="text-align:right">${it.close_price.toLocaleString()}원${gapTag(it.gap20_pct)}<br><span style="color:${it.change_pct>=0?'#f85149':'#3b82f6'};font-size:11px">${it.change_pct>=0?'+':''}${it.change_pct.toFixed(2)}%</span><br><span class="ts">거래대금 ${cdWon(it.trading_value||0)}${it.turnover_pct!=null?' · 회전율 '+it.turnover_pct.toFixed(1)+'%':''}</span></td>
      <td data-label="손절선" style="color:#f85149">${it.stop_price?it.stop_price.toLocaleString()+'원<br><span style="font-size:11px;color:'+({적정:'#3fb950',보통:'#c9d1d9',얕음:'#8b949e',깊음:'#8b949e'}[it.stop_zone])+'">-'+it.stop_dist_pct+'% · '+it.stop_zone+'</span>':'—'}</td>
    </tr>`;
  }).join('');
}

// ── 대량거래 관심종목 ──────────────────────────────────────────
let _vrData = null;
async function loadVolumeRecords(){
  try{ _vrData = await fetch(`${API}/screener/volume-records`).then(r=>r.ok?r.json():null); }catch(e){ _vrData = null; }
  renderVolumeRecords();
}
function renderLimitUp(){
  const el = document.getElementById('lu-body');
  const lu = (_vrData && _vrData.limit_up) || [];
  document.getElementById('lu-info').textContent = _vrData ? `기준일 ${_vrData.trading_date} · ${lu.length}개` : '';
  if(!_vrData){ el.textContent = '로딩 실패'; return; }
  if(!lu.length){ el.textContent = '오늘은 해당 종목이 없습니다'; return; }
  el.innerHTML = lu.map(x=>`<span style="display:inline-block;margin:0 8px 6px 0;padding:6px 10px;border:1px solid #30363d;border-radius:8px;cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','')">
    <b style="color:#e6edf3">${x.name}</b> <span style="color:#f85149">+${x.change_pct}%</span>${x.locked?' <b style="color:#d29922">점상</b>':''}
    <span class="ts">· ${x.close_price.toLocaleString()}원 · ${cdWon(x.value)}(평소 ${x.x}배)${x.market_cap?' · 시총 '+cdWon(x.market_cap):''}</span></span>`).join('');
}
function renderVolumeRecords(){
  renderLimitUp();
  const body = document.getElementById('vr-body');
  if(!_vrData){ body.innerHTML = '<tr><td colspan="5" style="color:#f85149;text-align:center;padding:20px">로딩 실패</td></tr>'; return; }
  const sel = document.getElementById('vr-stage').value;
  const sigOnly = document.getElementById('vr-signal').checked;
  const items = _vrData.items.filter(x=> (sel==='live' ? !['무너짐','설거지'].includes(x.stage) : (!sel || x.stage===sel)) && (!sigOnly || x.entry_signal));
  const cnt = s=>_vrData.items.filter(x=>x.stage===s).length;
  const nsig = _vrData.items.filter(x=>x.entry_signal).length;
  document.getElementById('vr-info').textContent = `기준일 ${_vrData.trading_date} · 시장 ${_vrData.market_state||'-'} · 🎯 ${nsig} · 숨고르기 ${cnt('숨고르기')} · 신규 ${cnt('신규')} · 진행 중 ${cnt('진행 중')} · 설거지 ${cnt('설거지')} · 무너짐 ${cnt('무너짐')}`;
  if(!items.length){ body.innerHTML = '<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">해당 종목이 없습니다</td></tr>'; return; }
  const color = {'숨고르기':'#3fb950','신규':'#58a6ff','진행 중':'#d29922','설거지':'#f85149','무너짐':'#8b949e'};
  const sg = n=>(n>=0?'+':'')+n;
  body.innerHTML = items.map(x=>`<tr style="cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','${x.event_date}')">
    <td>${x.entry_signal?'<b style="color:#e3b341">🎯 진입 신호</b><br>':''}<b>${x.name}</b> <span style="color:#8b949e;font-size:11px">${x.code}</span>${x.earn_up?' <span style="color:#3fb950;font-size:11px;border:1px solid #238636;border-radius:8px;padding:0 5px">📈 실적</span>':''}${x.market_cap?`<br><span class="ts">시총 ${cdWon(x.market_cap)}</span>`:''}</td>
    <td data-label="단계"><b style="color:${color[x.stage]}">${x.stage}</b><br><span class="ts">마지막 대량거래 뒤 ${x.rest_days}일</span></td>
    <td data-label="신기록일">${x.event_date.slice(5)} <span style="color:#f85149">${sg(x.event_change_pct)}%</span><br><span class="ts">${cdWon(x.event_value)} · 평소 ${x.event_x}배</span></td>
    <td data-label="그 뒤 최고" style="color:#f85149">${sg(x.rise_pct)}%<br><span class="ts">${x.peak_date.slice(5)}</span></td>
    <td data-label="지금" style="text-align:right">${x.close_price.toLocaleString()}원${gapTag(x.gap20_pct)} <span style="color:${x.change_pct>=0?'#f85149':'#3b82f6'};font-size:11px">${sg(x.change_pct.toFixed(2))}%</span><br><span class="ts">고점 ${x.off_peak_pct}% · 상승분 ${x.kept_pct}% 유지 · 거래 ${x.dry_pct}%로 마름</span><br><span class="ts" style="color:#f85149">기준선(손절) ${x.stop_price.toLocaleString()}원 · ${x.stop_gap_pct}%</span>${x.entry_signal?`<br><span class="ts" style="color:#e3b341">매도: 시초가 +5% 이상 갭이면 덜어내기 · ${Math.round(x.close_price*1.1).toLocaleString()}원(+10%)에 절반 · 나머지는 보유 중 최고 종가 -8% 이탈 시</span>`:''}</td>
  </tr>`).join('');
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
  body.innerHTML = '<tr><td colspan="8" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr>';
  try{
    const limit = document.getElementById('tv-limit').value;
    const sort = document.getElementById('tv-sort').value, minv = document.getElementById('tv-min').value;
    tvData = await fetch(`${API}/screener/top-value?market=${tvMarket}&limit=${limit}&sort=${sort}&min_value=${minv}`).then(r=>r.ok?r.json():null);
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
  const sortName = {value:'거래대금',cap:'시총',up:'상승률',down:'하락률',turnover:'회전율'}[tvData.sort]||'거래대금';
  document.getElementById('tv-info').textContent = `기준일: ${tvData.trading_date} · ${tvMarket==='KOSPI'?'코스피':'코스닥'} ${sortName} 순 ${tvData.items.length}종목`;
  if(!rows.length){ body.innerHTML = '<tr><td colspan="7" style="color:#8b949e;text-align:center;padding:20px">검색 결과 없음</td></tr>'; return; }
  const won = v=>v>=1e12?(v/1e12).toFixed(2)+'조':Math.round(v/1e8).toLocaleString()+'억';
  body.innerHTML = rows.map(it=>{
    const c = it.change_pct>0?'#f85149':it.change_pct<0?'#58a6ff':'#c9d1d9';
    const nm = it.name.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
    return `<tr style="cursor:pointer" data-code="${it.code}" data-name="${nm}" onclick="openChartModal(this.dataset.code,this.dataset.name,'')">
      <td class="c-rank">${it.rank}</td>
      <td class="c-name"><b>${nm}</b> <span style="color:#8b949e;font-size:11px">${it.code}</span></td>
      <td class="c-price">${Math.round(it.close_price).toLocaleString()}</td>
      <td class="c-chg" style="color:${c}">${it.change_pct>0?'+':''}${it.change_pct.toFixed(2)}%</td>
      <td class="c-tv"><b>${won(it.trading_value)}</b><span class="m-only">${it.market_cap?' · 시총 '+won(it.market_cap):''}${it.turnover_pct!=null?' · 회전 '+it.turnover_pct.toFixed(1)+'%':''}</span></td>
      <td class="c-vol">${Math.round(it.volume).toLocaleString()}</td>
      <td class="c-cap">${it.market_cap?won(it.market_cap):'—'}</td>
      <td class="c-turn">${it.turnover_pct!=null?it.turnover_pct.toFixed(2)+'%':'—'}</td>
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

// 주소 끝의 #탭이름(새로고침 전에 보던 탭, switchTab이 남긴다)으로 시작
switchTab(location.hash ? location.hash.slice(1) : 'jongbe');
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
        conn.execute(text("ALTER TABLE discussion_comments ADD COLUMN IF NOT EXISTS image_data TEXT"))
        conn.execute(text("ALTER TABLE discussion_posts ADD COLUMN IF NOT EXISTS title VARCHAR(100)"))
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

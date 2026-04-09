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
    <div class="card"><h3>데이터 품질</h3><div class="val" id="dq-score" style="font-size:24px">—</div><div class="note" id="dq-note">데이터 수집 현황</div></div>
  </div>
  <!-- 시장 시그널 히스토리 -->
  <div style="margin-bottom:20px">
    <div style="font-size:12px;text-transform:uppercase;color:#8b949e;margin-bottom:8px;letter-spacing:.06em">시장 시그널 히스토리</div>
    <div id="sig-history" style="display:flex;gap:8px;flex-wrap:wrap"></div>
  </div>
  <table>
    <thead><tr>
      <th>#</th><th>종목</th><th>총점</th><th>종가</th><th>등락</th>
      <th>기관 순매수</th><th>외국인 순매수</th><th>연속일</th><th>태그</th>
    </tr></thead>
    <tbody id="rec-body"><tr><td colspan="9" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>

  <!-- 전일 대비 상승 종목 -->
  <div style="margin-top:16px">
    <div style="font-size:12px;text-transform:uppercase;color:#8b949e;margin-bottom:8px;letter-spacing:.06em">전일 대비 시그널 상승 TOP 5</div>
    <div id="trending-stocks" style="display:flex;gap:8px;flex-wrap:wrap"></div>
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
    <select id="scr-sort" onchange="renderScreener()">
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

<!-- 백테스트 탭 -->
<div id="panel-backtest" class="panel content">

  <!-- 히스토리컬 백테스트 -->
  <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:20px">
    <div style="font-weight:600;color:#c9d1d9;margin-bottom:12px;font-size:15px">히스토리컬 백테스트 (FDR 가격 기반)</div>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px">
      <label style="color:#8b949e;font-size:13px">시작일</label>
      <input type="text" id="hbt-start" placeholder="2026-01-01" maxlength="10" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px;font-size:13px;width:100px;font-family:monospace">
      <label style="color:#8b949e;font-size:13px">종료일</label>
      <input type="text" id="hbt-end" placeholder="2026-04-05" maxlength="10" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px;font-size:13px;width:100px;font-family:monospace">
      <label style="color:#8b949e;font-size:13px">Top-N</label>
      <input type="number" id="hbt-topn" value="5" min="1" max="20" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px;font-size:13px;width:60px">
    </div>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px">
      <label style="color:#8b949e;font-size:13px">손절</label>
      <div style="display:flex;align-items:center;gap:4px">
        <input type="number" id="hbt-stoploss" value="3" min="0" max="20" step="0.5" style="background:#0d1117;border:1px solid #30363d;color:#f85149;padding:4px 8px;border-radius:4px;font-size:13px;width:60px">
        <span style="color:#8b949e;font-size:13px">%</span>
      </div>
      <label style="color:#8b949e;font-size:13px">익절</label>
      <div style="display:flex;align-items:center;gap:4px">
        <input type="number" id="hbt-takeprofit" value="5" min="0" max="50" step="0.5" style="background:#0d1117;border:1px solid #30363d;color:#3fb950;padding:4px 8px;border-radius:4px;font-size:13px;width:60px">
        <span style="color:#8b949e;font-size:13px">%</span>
      </div>
      <label style="color:#8b949e;font-size:12px;display:flex;align-items:center;gap:4px">
        <input type="checkbox" id="hbt-use-sltp" checked> 손절/익절 적용
      </label>
      <button class="btn" onclick="runHistoricalBacktest(this)">▶ 실행</button>
      <span class="ts" id="hbt-status"></span>
    </div>
    <div class="grid" id="hbt-cards" style="margin-bottom:12px"></div>
    <canvas id="hbt-chart" style="display:none;max-height:180px;margin-bottom:12px"></canvas>
    <div id="hbt-table-wrap" style="display:none;max-height:320px;overflow-y:auto;border:1px solid #30363d;border-radius:6px">
      <table id="hbt-table" style="width:100%">
        <thead style="position:sticky;top:0;background:#161b22;z-index:1"><tr><th>날짜</th><th>평균수익률</th><th>승률</th><th>종목수</th><th>추천종목</th></tr></thead>
        <tbody id="hbt-body"></tbody>
      </table>
    </div>
  </div>

  <!-- 기존 DB 기반 백테스트 -->
  <div style="font-weight:600;color:#8b949e;margin-bottom:8px;font-size:13px">DB 추천 기록 기반 백테스트</div>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
    <button class="btn" onclick="runBacktest(this)">▶ 실행 (최근 90일 추천)</button>
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

  <!-- 과거 데이터 백필 -->
  <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:20px">
    <div style="font-weight:600;color:#c9d1d9;margin-bottom:12px;font-size:15px">과거 데이터 백필 (수급·가격)</div>
    <div style="color:#8b949e;font-size:12px;margin-bottom:12px">pykrx로 과거 기관/외국인 수급 + FDR 가격을 한번에 수집합니다. 이미 있는 날짜는 건너뜁니다.<br>수급 포함 백테스트를 하려면 먼저 이 기능으로 데이터를 채우세요.</div>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px">
      <label style="color:#8b949e;font-size:13px">시작일</label>
      <input type="text" id="bf-start" placeholder="2024-01-01" maxlength="10" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px;font-size:13px;width:100px;font-family:monospace">
      <label style="color:#8b949e;font-size:13px">종료일</label>
      <input type="text" id="bf-end" placeholder="2025-12-31" maxlength="10" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:4px;font-size:13px;width:100px;font-family:monospace">
      <button class="btn" onclick="runBackfill(this)">▶ 백필 시작</button>
      <span class="ts" id="bf-status"></span>
    </div>
    <div id="bf-result" style="font-size:13px;color:#8b949e"></div>
  </div>

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
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',['dash','screener','signal','backtest','sources','logs'][i]===id));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+id).classList.add('active');
  if(id==='screener')loadScreener();
  if(id==='signal')loadSignalDetail();
  if(id==='sources')loadSources();
  if(id==='logs'){loadLogs();_initBfDates();}
  if(id==='backtest'){loadBacktestSummary();_initHbtDates();}
}

async function loadAll() {
  try {
    const [sig, recs, scr, hist, dq, trending] = await Promise.all([
      fetch(API+'/market-signal').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/recommendations').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/screener').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/market-signal/history?limit=7').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/data-quality').then(r=>r.ok?r.json():null).catch(()=>null),
      fetch(API+'/screener/trending?top_n=5').then(r=>r.ok?r.json():null).catch(()=>null),
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
          <div style="color:#3fb950;font-weight:600;margin-top:4px">+${t.delta.toFixed(2)} ↑</div>
          <div class="ts">${t.today_score.toFixed(2)} (전: ${t.prev_score.toFixed(2)})</div>
        </div>`).join('');
    } else if(document.getElementById('trending-stocks')) {
      document.getElementById('trending-stocks').innerHTML='<span class="ts">이전 거래일 데이터 없음</span>';
    }
    if(hist && hist.length){
      const sorted=[...hist].sort((a,b)=>a.trading_date>b.trading_date?1:-1);
      document.getElementById('sig-history').innerHTML=sorted.map(h=>`
        <div style="background:#161b22;border:1px solid #30363d;border-radius:6px;padding:8px 14px;text-align:center;min-width:100px">
          <div class="ts">${h.trading_date}</div>
          <div class="signal-${h.signal}" style="font-weight:700;font-size:15px">${h.signal}</div>
          <div class="ts" style="color:${h.score>0?'#3fb950':h.score<0?'#f85149':'#d29922'}">${h.score.toFixed(1)}</div>
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

function _initBfDates(){
  const fmt = d => d.toISOString().slice(0,10);
  const es = document.getElementById('bf-start');
  const ee = document.getElementById('bf-end');
  if(!es.value){const d=new Date();d.setFullYear(d.getFullYear()-2);es.value=fmt(d);}
  if(!ee.value){const d=new Date();d.setDate(d.getDate()-1);ee.value=fmt(d);}
}

let _bfPollTimer = null;

async function runBackfill(btn){
  const start = document.getElementById('bf-start').value;
  const end = document.getElementById('bf-end').value;
  if(!start||!end){showToast('시작일·종료일을 입력하세요',true);return;}
  if(!confirm(`${start} ~ ${end} 기간 데이터를 백필합니다.\n종목 수에 따라 수십 분 소요될 수 있습니다.\n계속하시겠습니까?`)){return;}
  btn.disabled=true;btn.textContent='백필 중…';
  document.getElementById('bf-result').textContent='';
  try{
    const r=await fetch(API+`/data/backfill?start_date=${start}&end_date=${end}`,{method:'POST'});
    const d=await r.json();
    if(!r.ok){
      const msg=d.detail||d.error||JSON.stringify(d);
      showToast('오류: '+msg,true);
      document.getElementById('bf-result').innerHTML=`<span style="color:#f85149">오류: ${msg}</span>`;
      document.getElementById('bf-status').textContent='';
      btn.disabled=false;btn.textContent='▶ 백필 시작';return;
    }
    // 백그라운드 실행 시작됨 — 5초마다 상태 polling
    document.getElementById('bf-status').textContent='백필 실행 중… (서버 로그에서 진행 확인 가능)';
    if(_bfPollTimer) clearInterval(_bfPollTimer);
    _bfPollTimer = setInterval(async()=>{
      try{
        const s=await fetch(API+'/data/backfill/status').then(r=>r.json());
        if(s.error){
          clearInterval(_bfPollTimer);
          document.getElementById('bf-status').textContent='오류 발생';
          document.getElementById('bf-result').innerHTML=`<span style="color:#f85149">오류: ${s.error}</span>`;
          btn.disabled=false;btn.textContent='▶ 백필 시작';
        } else if(!s.running && s.result){
          clearInterval(_bfPollTimer);
          const res=s.result;
          document.getElementById('bf-status').textContent='완료';
          document.getElementById('bf-result').innerHTML=`
            <span style="color:#3fb950">✓ ${res.days_filled}일 채움</span> &nbsp;
            <span style="color:#8b949e">/ 건너뜀 ${res.days_skipped}일 / 전체 ${res.days_total}일 / 종목 ${res.stocks}개</span>
            ${res.errors&&res.errors.length?'<br><span style="color:#f85149">오류 '+res.errors.length+'건: '+res.errors[0]+'</span>':''}`;
          showToast(`백필 완료: ${res.days_filled}일 채움`);
          btn.disabled=false;btn.textContent='▶ 백필 시작';
          loadLogs();
        }
      }catch(e){}
    }, 5000);
  }catch(e){
    showToast('백필 요청 실패: '+e.message,true);
    document.getElementById('bf-status').textContent='';
    btn.disabled=false;btn.textContent='▶ 백필 시작';
  }
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
  finally{btn.disabled=false;btn.textContent='▶ 실행 (최근 90일 추천)';}
}

// 히스토리컬 백테스트 차트 인스턴스
let hbtChart = null;

function _initHbtDates(){
  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth()-3);
  const fmt = d => d.toISOString().slice(0,10);
  const es = document.getElementById('hbt-start');
  const ee = document.getElementById('hbt-end');
  if(!es.value) es.value = fmt(start);
  if(!ee.value) ee.value = fmt(end);
}

async function runHistoricalBacktest(btn){
  const start = document.getElementById('hbt-start').value;
  const end = document.getElementById('hbt-end').value;
  const topn = document.getElementById('hbt-topn').value||5;
  const useSltp = document.getElementById('hbt-use-sltp')?.checked;
  const sl = useSltp ? (document.getElementById('hbt-stoploss').value||0) : 0;
  const tp = useSltp ? (document.getElementById('hbt-takeprofit').value||0) : 0;
  if(!start||!end){showToast('시작일·종료일을 입력하세요',true);return;}
  btn.disabled=true;btn.textContent='실행 중…';
  document.getElementById('hbt-status').textContent='FDR 가격 다운로드 중 (수십 초 소요)…';
  try{
    const r=await fetch(API+`/backtest/historical?start_date=${start}&end_date=${end}&top_n=${topn}&stop_loss_pct=${sl}&take_profit_pct=${tp}`,{method:'POST'});
    const d=await r.json();
    if(!r.ok||d.error||d.detail){showToast('오류: '+(d.error||d.detail||r.status),true);document.getElementById('hbt-status').textContent='';return;}
    const m=d.metrics||{};
    const pct=v=>v!=null?v.toFixed(3)+'%':'—';
    const pctWr=v=>v!=null?v.toFixed(1)+'%':'—';
    document.getElementById('hbt-cards').innerHTML=`
      <div class="card"><h3>평균수익률</h3><div class="val" style="color:${(m.avg_return_pct||0)>=0?'#3fb950':'#f85149'};font-size:22px">${pct(m.avg_return_pct)}</div><div class="note">수수료·슬리피지 차감</div></div>
      <div class="card"><h3>승률</h3><div class="val" style="font-size:22px">${pctWr(m.win_rate_pct)}</div></div>
      <div class="card"><h3>샤프</h3><div class="val" style="font-size:22px">${m.sharpe!=null?m.sharpe.toFixed(3):'—'}</div><div class="note">연환산</div></div>
      <div class="card"><h3>누적수익률</h3><div class="val" style="font-size:22px;color:${(m.cumulative_return_pct||0)>=0?'#3fb950':'#f85149'}">${pct(m.cumulative_return_pct)}</div></div>
      <div class="card"><h3>최대낙폭</h3><div class="val" style="font-size:22px;color:#f85149">${pct(m.max_drawdown_pct)}</div></div>
      <div class="card"><h3>총 거래수</h3><div class="val" style="font-size:22px">${d.total_trades||0}</div><div class="note">${d.simulated_days||0}일 진입 / 시장필터 ${d.skipped_market_filter||0}일 스킵 / 점수필터 ${d.skipped_score_filter||0}일 스킵</div></div>
      <div class="card"><h3>손절/익절</h3><div class="val" style="font-size:18px">${(d.filters?.stop_loss_pct!=null?'<span style="color:#f85149">-'+d.filters.stop_loss_pct+'%</span>':'<span style="color:#444">없음</span>')} / ${(d.filters?.take_profit_pct!=null?'<span style="color:#3fb950">+'+d.filters.take_profit_pct+'%</span>':'<span style="color:#444">없음</span>')}</div><div class="note">시장레짐필터 MA${d.filters?.market_filter_ma||20}</div></div>`;

    // 누적수익 곡선 차트
    const curve = d.cumulative_curve||[];
    if(curve.length>1){
      const canvas=document.getElementById('hbt-chart');
      canvas.style.display='block';
      if(hbtChart){hbtChart.destroy();hbtChart=null;}
      if(typeof Chart!=='undefined'){
        const ctx=canvas.getContext('2d');
        const color=curve[curve.length-1]>=0?'#3fb950':'#f85149';
        hbtChart=new Chart(ctx,{
          type:'line',
          data:{labels:Array.from({length:curve.length},(_,i)=>i+1),datasets:[{label:'누적수익률(%)',data:curve,borderColor:color,backgroundColor:color+'22',borderWidth:1.5,pointRadius:0,fill:true,tension:0.2}]},
          options:{responsive:true,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${c.parsed.y.toFixed(3)}%`}}},scales:{x:{display:false},y:{ticks:{callback:v=>v+'%'},grid:{color:'#30363d'},border:{color:'#30363d'}}},animation:{duration:300}}
        });
      }
    }

    // 일별 결과 테이블
    const daily=d.daily_results||[];
    document.getElementById('hbt-table-wrap').style.display=daily.length?'':'none';
    document.getElementById('hbt-body').innerHTML=daily.map(r=>`<tr>
      <td>${r.date}</td>
      <td style="color:${r.avg_return_pct>=0?'#3fb950':'#f85149'}">${r.avg_return_pct>=0?'+':''}${r.avg_return_pct}%</td>
      <td>${r.win_rate_pct}%</td>
      <td>${r.count}</td>
      <td style="font-size:11px;color:#8b949e">${(r.top_stocks||[]).join(', ')}</td>
    </tr>`).join('');
    document.getElementById('hbt-status').textContent=` (${d.period})`;
    showToast(`히스토리컬 백테스트 완료: 승률 ${m.win_rate_pct?.toFixed(1)}%, 샤프 ${m.sharpe?.toFixed(3)}`);
  }catch(e){showToast('히스토리컬 백테스트 실패: '+e.message,true);document.getElementById('hbt-status').textContent='';}
  finally{btn.disabled=false;btn.textContent='▶ 실행';}
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


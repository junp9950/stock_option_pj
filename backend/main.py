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
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
app.add_middleware(GZipMiddleware, minimum_size=1000)   # 폰에서 느림 (2026-10-07) — 첫 화면 150KB·차트 24KB를 압축해서 보냄
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
<title>주식레이더</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect width=%22100%22 height=%22100%22 rx=%2222%22 fill=%22%231f6feb%22/><text x=%2250%22 y=%2270%22 font-size=%2258%22 text-anchor=%22middle%22>%F0%9F%93%88</text></svg>">
<style>
:root{--bg:#0d1117;--card:#161b22;--card2:#1c2128;--line:#30363d;--line2:#21262d;--text:#e6edf3;--body:#c9d1d9;--muted:#8b949e;
  --blue:#58a6ff;--orange:#f0883e;--up:#f85149;--down:#58a6ff;--ok-bg:rgba(56,139,253,.12);--warn-bg:rgba(240,136,62,.13)}
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
/* 종목 차트 창: 왼쪽 차트 + 오른쪽 패널 (2026-10-09, 색은 :root 변수 — 나중에 밝은 화면 전환용) */
.modal.cm-wide{width:min(1240px,100%);padding:20px}
.cm-body{display:flex;gap:16px;align-items:flex-start}
.cm-chart{flex:1;min-width:0}
.cm-panel{width:330px;flex-shrink:0;display:flex;flex-direction:column;gap:10px}
.cm-panel:empty{display:none}
.cp-head{display:flex;gap:12px;align-items:center}
.cp-grade{width:46px;height:46px;border-radius:10px;background:var(--card2);border:1px solid var(--line);display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:800;color:var(--text)}
.cp-gw{font-size:11px;color:var(--muted)}.cp-gw b{display:block;font-size:15px;color:var(--text)}
.cp-price{font-size:13px;color:var(--body)}
.cp-state{background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.cp-steps{display:flex;gap:4px;margin-bottom:10px}
.cp-step{flex:1;text-align:center;font-size:10px;color:var(--muted)}
.cp-step i{display:block;height:4px;border-radius:2px;background:var(--line);margin-bottom:4px}
.cp-step.on{color:var(--text);font-weight:700}.cp-step.on i{background:var(--blue)}
.cp-step.done i{background:rgba(88,166,255,.35)}
.cp-title{font-size:17px;font-weight:800;color:var(--text)}
.cp-sub{font-size:12px;color:var(--muted);margin-top:3px}
.cp-chips{display:flex;flex-wrap:wrap;gap:5px}
.cp-chip{font-size:11.5px;padding:3px 8px;border-radius:12px;border:1px solid}
.cp-chip.ok{color:var(--blue);background:var(--ok-bg);border-color:rgba(56,139,253,.35)}
.cp-chip.warn{color:var(--orange);background:var(--warn-bg);border-color:rgba(240,136,62,.4)}
.cp-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.cp-card{background:var(--card2);border:1px solid var(--line);border-radius:8px;padding:8px}
.cp-card .l{font-size:10.5px;color:var(--muted)}.cp-card .v{font-size:14px;font-weight:700;color:var(--text);margin-top:2px}.cp-card .s{font-size:10.5px;color:var(--muted)}
.cp-rows{border-top:1px solid var(--line2)}
.cp-row{display:flex;justify-content:space-between;gap:8px;padding:6px 2px;border-bottom:1px solid var(--line2);font-size:12px}
.cp-row .k{color:var(--muted)}.cp-row .v{color:var(--text);text-align:right}
@media(max-width:900px){.cm-body{flex-direction:column}.cm-panel{width:100%}}
/* 첫 화면 작업대: 종목 목록 | 신호 찍힌 차트 | 패널 (2026-10-09, 카드형 작업대) */
.ws{display:grid;grid-template-columns:360px minmax(0,1fr);gap:14px;align-items:start;margin-bottom:14px}
.ws-list,.ws-main{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
.ws-list{max-height:none;display:flex;flex-direction:column;min-height:0;grid-row:1;align-self:stretch;contain:size}   /* 목록 높이 = 차트 높이 (2026-10-10 '아래 빈 공간 메꾸기') */
.ws-list>#ws-items,.ws-list>#jr-ws-items{flex:1;min-height:0;overflow-y:auto}
.ws-sub{font-size:11.5px;color:var(--muted);margin:10px 4px 4px;padding-top:8px;border-top:1px solid var(--line2)}.ws-item.dim{opacity:.72}
.ws-main{min-width:0;padding:12px;grid-row:1}
/* 종목 정보는 목록·차트 아래에 가로로 넓게 (10/10 위 → 아래: 차트가 먼저 보이게) — 내용은 칸(column)으로 흘려서 낮게 (2026-10-10) */
.ws>.cm-panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;grid-column:1/-1;grid-row:2;width:auto;display:block;columns:5 230px;column-gap:16px}
.ws>.cm-panel>*{break-inside:avoid;margin-bottom:10px}.ws>.cm-panel>.cp-rows{break-inside:auto}.ws>.cm-panel .cp-row{break-inside:avoid}
.ws>.cm-panel:empty{display:none}
.ws-search{position:relative;margin-bottom:6px}.ws-search input{width:100%;box-sizing:border-box;background:var(--card2);border:1px solid var(--line);color:var(--text);border-radius:16px;padding:7px 12px;font-size:13px;outline:none}.ws-search input:focus{border-color:var(--blue)}#ws-sr{position:absolute;left:0;right:0;top:100%;z-index:30;background:var(--card);border:1px solid var(--line);border-radius:10px;margin-top:4px;max-height:360px;overflow:auto;display:none;box-shadow:0 6px 18px rgba(0,0,0,.4)}#ws-sr.on{display:block}
.htop{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:14px;margin-bottom:14px}
.hc-spark{position:relative;height:92px;margin:2px 0 8px}.hc-spark svg{width:100%;height:100%;display:block}
.hc-sx{display:flex;justify-content:space-between;font-size:10.5px;color:var(--muted);margin-top:-6px;margin-bottom:10px}
.hc-tg{display:flex;gap:4px}.hc-tg button{background:none;border:1px solid var(--line);color:var(--muted);border-radius:10px;font-size:11px;padding:1px 8px;cursor:pointer}.hc-tg button.on{color:var(--text);border-color:var(--blue)}
.hcard{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 18px;min-width:0}
.hc-h{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:10px}.hc-h b{font-size:15px;color:var(--text)}.hc-h span{font-size:11.5px;color:var(--muted)}
.hc-head{font-size:18px;font-weight:800;color:var(--text);line-height:1.35;margin:2px 0 4px;word-break:keep-all}
.hc-do{font-size:12.5px;color:var(--muted);margin-bottom:10px;word-break:keep-all}
.hc-nums{display:flex;gap:0;margin-bottom:10px}.hc-num{flex:1;min-width:0;padding:0 14px;border-left:1px solid var(--line)}.hc-num:first-child{padding-left:0;border-left:none}
.hc-num .l{font-size:11.5px;color:var(--muted)}.hc-num .v{font-size:20px;font-weight:800;color:var(--text);margin:2px 0}.hc-num .s{font-size:12.5px;font-weight:600}
.hc-flow{display:grid;grid-template-columns:40px 1fr;gap:6px 8px;align-items:center;font-size:12px}.hc-flow .k{color:var(--muted)}
.hc-pill{display:inline-block;margin:0 5px 4px 0;padding:3px 10px;border-radius:12px;border:1px solid var(--line);font-size:12px;color:var(--text);white-space:nowrap}
.hc-pill.up{border-color:rgba(248,81,73,.45)}.hc-pill.dn{border-color:rgba(88,166,255,.45)}
.hc-verdict{display:flex;align-items:center;gap:8px;margin:2px 0 4px}.hc-verdict b{font-size:17px;color:var(--text)}
.hc-sum{font-size:12.5px;color:var(--muted);margin-bottom:8px}
.hc-bars{display:flex;gap:4px;margin:4px 0 8px}.hc-bars i{flex:1;height:5px;border-radius:3px;background:var(--line)}
.hc-bars i{background:#e6edf3}.hc-bars i.g{background:#2ea043}.hc-bars i.b{background:#da3633}
.hc-row{display:flex;align-items:center;gap:10px;padding:6px 0;border-top:1px solid var(--line2)}
.hc-row .t{flex:1;min-width:0}.hc-row .t b{display:block;font-size:13.5px;color:var(--text)}.hc-row .t span{font-size:11.5px;color:var(--muted)}
.hc-row .v{font-size:16px;font-weight:700;color:var(--text);white-space:nowrap}
.hc-badge{font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;white-space:nowrap;border:1px solid}
.hc-badge.g{color:var(--blue);border-color:rgba(88,166,255,.45);background:rgba(56,139,253,.10)}
.hc-badge.n{color:#0d1117;background:#e6edf3;border-color:#e6edf3}   /* 중립 = 흰 테두리·흰 배지(사용자 10/10 후보 7개 중 E 고름 — 적색약·노랑초록 색약, 노랑·주황 다 안 보임) — ■ 글자로도 구분 */
.hc-badge.b{color:var(--orange);border-color:rgba(240,136,62,.5);background:rgba(240,136,62,.10)}
/* 양호·약화가 한눈에 (2026-10-10, 사용자 고름: 양호 초록 · 약화 빨강 — 노랑과 안 헷갈리게 진한 초록) · 중립 = 회색 테두리만. 색약이라 ▲■▼ 모양·글자도 같이 */
.hc-badge.g{background:#2ea043;color:#fff;border-color:#2ea043}.hc-badge.b{background:#da3633;color:#fff;border-color:#da3633}
.hc-row.k-g{background:rgba(35,134,54,.16);box-shadow:inset 3px 0 0 #2ea043;padding-left:8px;padding-right:4px}.hc-row.k-g .v{color:#7ee787}
.hc-row.k-b{background:rgba(218,54,51,.16);box-shadow:inset 3px 0 0 #f85149;padding-left:8px;padding-right:4px}.hc-row.k-b .v{color:#ffa198}
.hc-row.k-n{background:rgba(230,237,243,.05);box-shadow:inset 3px 0 0 #e6edf3;padding-left:8px;padding-right:4px}.hc-row.k-n .v{color:#ffffff}
/* PC: 위 카드 두 개를 낮게 줄여서 목록·차트가 한 화면에 들어오게 (2026-10-10 "차트·종목 검색 아래까지 한 페이지에") */
@media(min-width:901px){
.htop{margin-bottom:10px;gap:10px}.hcard{padding:10px 14px;border-radius:12px}
.hc-h{margin-bottom:4px}.hc-h b{font-size:13.5px}
#hc-today{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"h h" "sp sp" "sx sx" "head nums" "flow nums";column-gap:16px;row-gap:2px;align-items:start}
#hc-today>.hc-h{grid-area:h}#hc-today>.hc-spark{grid-area:sp;height:62px;margin:0}#hc-today>.hc-sx{grid-area:sx;margin:0 0 4px}
#hc-today>.hc-head{grid-area:head;font-size:15px;margin:0}#hc-today>.hc-do{grid-area:head;margin:22px 0 0;font-size:12px}
#hc-today>.hc-nums{grid-area:nums;margin:0}#hc-today .hc-num{padding:0 12px}#hc-today .hc-num .v{font-size:16px;margin:0}#hc-today .hc-num .l,#hc-today .hc-num .s{font-size:11px}
#hc-today>.hc-flow{grid-area:flow;display:flex;flex-wrap:wrap;gap:2px 6px;align-items:center}#hc-today .hc-pill{margin:0 3px 2px 0;padding:1px 8px;font-size:11.5px}
#hc-market{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:auto auto auto auto 1fr 1fr;column-gap:8px;row-gap:6px}
#hc-market>.hc-h,#hc-market>.hc-verdict,#hc-market>.hc-sum,#hc-market>.hc-bars{grid-column:1/-1}
#hc-market>.hc-verdict{margin:0}#hc-market>.hc-verdict b{font-size:14px}#hc-market>.hc-sum{font-size:11px;margin:0 0 2px}#hc-market>.hc-bars{margin:2px 0 4px}
/* 근거 6개 = 타일 (제목·설명 왼쪽 / 값·배지 오른쪽) — 카드 남는 높이를 채움 */
#hc-market>.hc-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;column-gap:6px;align-items:center;padding:4px 8px;border:1px solid var(--line2);border-radius:8px;background:var(--card2)}
#hc-market .hc-row .t{min-width:0}#hc-market .hc-row .t b{font-size:12.5px}#hc-market .hc-row .t span{display:block;font-size:10.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#hc-market .hc-row .v{font-size:14px;text-align:right}#hc-market .hc-row .hc-badge{justify-self:end;font-size:10.5px;padding:1px 6px}
#hc-market .hc-row.k-g{background:rgba(35,134,54,.20);border-color:#2ea043;box-shadow:inset 5px 0 0 #2ea043;padding-left:12px}#hc-market .hc-row.k-g .v{color:#7ee787;font-weight:800}#hc-market .hc-row.k-g .t b{color:#fff}
#hc-market .hc-row.k-b{background:rgba(218,54,51,.20);border-color:#f85149;box-shadow:inset 5px 0 0 #f85149;padding-left:12px}#hc-market .hc-row.k-b .v{color:#ffa198;font-weight:800}#hc-market .hc-row.k-b .t b{color:#fff}
#hc-market .hc-row.k-n{background:rgba(230,237,243,.06);border-color:#e6edf3;box-shadow:inset 5px 0 0 #e6edf3;padding-left:12px}#hc-market .hc-row.k-n .v{color:#ffffff;font-weight:800}#hc-market .hc-row.k-n .t b{color:#fff}#hc-market .hc-row .hc-badge{font-size:11px;padding:2px 8px}
.lwbox>.lwc{height:clamp(300px,calc(100vh - 512px),720px)}
}
@media(max-width:900px){.htop{grid-template-columns:1fr}.hc-head{font-size:18px}.hc-num .v{font-size:19px}.hcard{padding:16px}}
#ws-lane-note{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}#ws-lane-note.open{display:block}
.ws-tabs{display:flex;gap:6px;margin-bottom:6px}
.ws-tabs button{flex:1;background:var(--card2);border:1px solid var(--line);color:var(--muted);border-radius:16px;padding:6px 0;font-size:12px;cursor:pointer;white-space:nowrap}
.ws-tabs button.on{background:var(--text);color:var(--bg);font-weight:700;border-color:var(--text)}
.ws-item{display:flex;align-items:center;gap:10px;padding:8px 6px;border-radius:8px;cursor:pointer}
.ws-item:hover{background:var(--card2)}.ws-item.on{background:var(--card2);box-shadow:inset 3px 0 0 var(--blue)}
.ws-av{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;flex-shrink:0}
.ws-txt{min-width:0;flex:1}.ws-nm{font-weight:700;color:var(--text);font-size:13.5px;display:flex;align-items:center;gap:5px;min-width:0}.ws-nm .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:4.5em;flex:0 1 auto}.ws-nm .b{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;font-size:11px;font-weight:600;padding:0 6px;border-radius:8px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.ws-tg{font-size:11px;color:var(--muted);line-height:1.35;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:keep-all;overflow-wrap:anywhere}
.ws-px{text-align:right;font-size:12.5px;color:var(--text);white-space:nowrap}
.ws-head{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:4px}
.ws-head b{font-size:17px;color:var(--text)}
.ws-sec{font-size:11px;color:var(--muted);margin:10px 4px 4px}
.ws-ctl{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center;margin:2px 0 6px}.ws-ctl .ws-per{margin:0}
.ws-per{display:flex;gap:4px;margin:2px 0 6px}.ws-per button{background:var(--card2);border:1px solid var(--line);color:var(--muted);border-radius:12px;padding:3px 10px;font-size:11.5px;cursor:pointer}
.ws-per button.on{color:var(--text);border-color:var(--blue)}
.ws-lg{margin-top:6px}.ws-lg summary{cursor:pointer;font-size:12px;color:var(--muted);list-style:none;display:inline-block;padding:3px 10px;border:1px solid var(--line);border-radius:12px}.ws-lg summary::-webkit-details-marker{display:none}.ws-lg[open] summary{color:var(--text);border-color:var(--blue)}
.ws-legend{display:flex;flex-direction:column;gap:5px;margin-top:8px;font-size:12px;line-height:1.5;color:var(--muted)}
.ws-legend span{display:block;word-break:keep-all;overflow-wrap:anywhere}.ws-legend i{width:10px;height:10px;border-radius:3px;display:inline-block}
/* 차트 (Lightweight Charts: 확대·이동·십자선, 2026-10-09) */
.lwbox{position:relative}.lwc{width:100%;height:clamp(420px,calc(100vh - 250px),720px)}
#cm-chart.lwc{height:460px}
.lwleg{font-size:11.5px;color:var(--body);line-height:1.5;height:56px;overflow:hidden;padding:2px 2px 4px}
.lwleg>div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lwleg b{color:var(--text)}
.lwwhy{display:none;position:absolute;left:6px;top:62px;z-index:5;max-width:min(560px,calc(100% - 70px));pointer-events:none;font-size:11.5px;line-height:1.55;
  color:var(--text);background:var(--card);opacity:.96;border:1px solid #d2a8ff;border-radius:6px;padding:6px 9px}
.lwwhy b{color:#d2a8ff}.lwwhy div{white-space:normal}
@media(max-width:760px){.lwwhy{top:54px;font-size:10.5px;max-width:calc(100% - 60px)}}
@media(max-width:760px){.lwc,#cm-chart.lwc{height:400px}.lwleg{font-size:10.5px;height:50px}
  .mstrip{position:static;box-shadow:none;flex-wrap:nowrap;overflow-x:auto;white-space:nowrap;font-size:12px;padding:6px 10px;gap:8px;-webkit-overflow-scrolling:touch}
  .mstrip .ix b{font-size:14px}.mstrip .rg .ts:last-child,.mstrip .sep{display:none}.mstrip .rg{padding:1px 7px;font-size:11.5px}}
/* 시장 한 줄 (맨 위 고정, 2026-10-09) — 색약이라 ▲▼■ 모양도 같이 */
.mstrip{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 14px;margin-bottom:10px;font-size:13px;box-shadow:0 4px 12px rgba(0,0,0,.35)}
.mstrip .ix{cursor:pointer;display:flex;align-items:baseline;gap:6px}.mstrip .ix b{font-size:16px}
.mstrip .sep{width:1px;height:22px;background:var(--line)}
.mstrip .rg{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;border-radius:12px;border:1px solid var(--line);font-size:12.5px}
#db-more>summary{font-size:15px;font-weight:700;color:var(--text);cursor:pointer;margin:6px 0 10px}
@media(max-width:1250px){.ws{grid-template-columns:320px minmax(0,1fr)}}
@media(max-width:760px){.ws{grid-template-columns:1fr}.ws-list{max-height:320px;height:320px;grid-row:1}.ws-main{grid-row:2}.ws>.cm-panel{columns:1;grid-row:3}}   /* 폰은 예전 순서: 목록 → 차트 → 종목 정보 */
.close-btn{float:right;cursor:pointer;color:#8b949e;font-size:18px;line-height:1}.close-btn:hover{color:#e6edf3}
.modal-tabs{display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid #30363d;padding-bottom:0}
.modal-tab{padding:6px 14px;font-size:13px;color:#8b949e;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
.modal-tab.active{color:#58a6ff;border-bottom-color:#58a6ff}
.ts{color:#8b949e;font-size:11px}
.lead{color:#c9d1d9;font-size:13px;margin:0 0 6px}
.sec{border:1px solid #30363d;border-radius:10px;padding:10px 14px;margin-top:10px;background:#0f141b}
.sec>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;font-size:15px;font-weight:600;color:#e6edf3;flex-wrap:wrap}
.sec>summary::-webkit-details-marker{display:none}
.sec>summary::after{content:'펼치기 ▾';margin-left:auto;font-size:12px;font-weight:400;color:#8b949e}
.sec[open]>summary::after{content:'접기 ▴'}.sec[open]>summary{margin-bottom:10px}

.cal-wrap{max-width:1180px;margin:0 auto}
.cal-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.cal-top .m{font-size:20px;font-weight:700;color:#e6edf3;min-width:130px;text-align:center}
.cal-nav{background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:8px;width:34px;height:34px;cursor:pointer;font-size:14px}
.cal-nav:hover{border-color:#58a6ff;color:#fff}
.cal-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px}
.cal-h{font-size:12px;color:#8b949e;text-align:center;padding-bottom:2px;font-weight:600}
.cal-c{position:relative;background:#11161d;border:1px solid #262c36;border-radius:10px;padding:10px 10px 9px;min-height:132px;cursor:pointer;display:flex;flex-direction:column;gap:5px;transition:border-color .12s,transform .12s}
.cal-c:hover{border-color:#3d4a5c;transform:translateY(-1px)}.cal-c.on{border-color:#58a6ff;box-shadow:0 0 0 1px #58a6ff inset}
.cal-c.off{cursor:default;background:transparent;border-style:dashed;border-color:#1f242c;color:#484f58;font-size:12px;justify-content:center;align-items:center}
.cal-c.off:hover{transform:none}
.cal-c.we{cursor:default;background:#0d1117;border-color:#1a1f27}.cal-c.we:hover{transform:none}
.cal-c.hol{cursor:default;background:#1a1214;border-color:#3a2226}.cal-c.hol:hover{transform:none}
.cal-c .hn{font-size:11.5px;color:#f47067;margin-top:2px}.cal-c .dn.sun,.cal-h.sun{color:#f47067}.cal-c .dn.sat,.cal-h.sat{color:#6cb6ff}
.cal-c.today{border-color:#e3b341}
.cal-c .hd{display:flex;justify-content:space-between;align-items:center}
.cal-c .dn{font-size:16px;font-weight:700;color:#e6edf3}
.cal-c .mk{font-size:11px;padding:1px 7px;border-radius:10px;background:#1c2330}
.cal-c .top{border-radius:7px;padding:6px 8px;font-size:13px;font-weight:600;color:#fff;display:flex;justify-content:space-between;gap:6px;align-items:baseline}
.cal-c .top .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cal-c .top .v{font-size:12px;white-space:nowrap;opacity:.95}
.cal-c .sub{display:flex;justify-content:space-between;gap:6px;font-size:12px;color:#adbac7;padding:0 2px}
.cal-c .sub .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.cal-c .sub .v{color:#f0883e;white-space:nowrap}
.cal-det{max-width:1180px;margin:14px auto 0;background:#11161d;border:1px solid #262c36;border-radius:12px;padding:14px 16px}
.cal-det .ttl{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.cal-det .chip{font-size:12px;padding:2px 9px;border-radius:12px;background:#1c2330;color:#c9d1d9}
.cal-det .rows{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px}
.cal-det .tc{border:1px solid #262c36;border-radius:9px;padding:9px 11px;cursor:pointer}.cal-det .tc:hover{border-color:#58a6ff}
.cal-det .tc .h{display:flex;justify-content:space-between;gap:6px;font-weight:600;color:#e6edf3;font-size:13.5px}
.cal-det .tc .l{margin-top:5px;display:flex;flex-wrap:wrap;gap:4px}.cal-det .tc .l span{font-size:11.5px;background:#1c2330;border-radius:6px;padding:1px 6px;color:#c9d1d9}
@media(max-width:640px){.cal-grid{gap:3px}.cal-c{min-height:86px;padding:5px 4px;gap:3px;border-radius:7px}.cal-c .dn{font-size:12px}.cal-c .mk{display:none}
.cal-c .top{font-size:10px;padding:3px 4px;flex-direction:column;gap:0}.cal-c .top .v{font-size:10px}.cal-c .sub{font-size:9.5px;flex-direction:column;gap:0}.cal-c .sub.s2{display:none}.cal-c.off{font-size:10px}.cal-c .hn{font-size:9px}.cal-c .top .v,.cal-c .sub .v{display:none}.cal-c{min-height:70px}}

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
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
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
  <div class="tab active" onclick="switchTab('home')">오늘</div>
  <div class="tab" onclick="switchTab('candidates')">차트 후보</div>
  <div class="tab" onclick="switchTab('calendar')">섹터 캘린더</div>
  <div class="tab" onclick="switchTab('sector')">섹터 수급</div>
  <div class="tab" onclick="switchTab('journal')">매매 일지</div>
  <div class="tab" onclick="switchTab('screener')">거래대금 순위</div>
  <div class="tab" onclick="switchTab('heatmap')">시장 히트맵</div>
  <div class="tab" onclick="switchTab('jongbe')">종베</div>
  <div class="tab" onclick="switchTab('discussion')">종목토론</div>
  <div class="tab" onclick="switchTab('suggest')">건의사항</div>
</div>

<div id="panel-suggest" class="panel"><iframe title="건의사항" id="suggest-frame" style="width:100%;height:1600px;border:0"></iframe></div>
<div id="panel-discussion" class="panel"><iframe title="종목토론" id="discussion-frame" style="width:100%;height:2000px;border:0"></iframe></div>

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
<div id="panel-jongbe" class="panel content">
  <div id="mp-box" style="border:1px solid #9e6a03;border-radius:10px;padding:12px 16px;margin-bottom:14px;background:rgba(210,153,34,.06)">로딩 중…</div>
  <b style="font-size:15px;color:#e6edf3;display:block;margin:4px 0 8px">① 시장</b>
  <div id="jb-market" style="border-radius:10px;padding:12px 16px;margin-bottom:12px;border:1px solid #30363d">로딩 중…</div>
  <p class="lead">시장 상승·횡보 → 뜨거운 섹터 → 그날 섹터에 돈 몰림 → 거래 실린 양봉, 또는 <b style="color:#e3b341">🕯 큰 양봉 다음 날 밑꼬리 도지</b>. <b>파는 법:</b> 다음 날 +2% 미만이면 전부 정리, +2% 이상이면 30% · 그다음 날도 오르면 30% 더 · 나머지는 최고 종가 -15% 이탈 시.</p>
  <div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:6px">
    <b style="font-size:15px;color:#e6edf3;margin:4px 0 8px">② 뜨는 섹터</b> <span class="ts" id="jb-date"></span>
    <label style="font-size:12.5px;color:#c9d1d9">시총
      <select id="jb-mincap" onchange="try{localStorage.setItem('jb-mincap',this.value)}catch(e){};renderJongbe()">
        <option value="0">전체</option><option value="500">500억 이상</option><option value="1000" selected>1,000억 이상</option><option value="2000">2,000억 이상</option>
        <option value="3000">3,000억 이상</option><option value="10000">1조 이상</option>
      </select></label>
    <label style="font-size:12.5px;color:#c9d1d9;cursor:pointer" title="20일선보다 +20% 넘게 뜬 종목과 그날 +12% 넘게 오른 종목을 뺍니다. 3년 확인: 평균 수익은 비슷한데 다음 날 -5% 넘는 손실이 2~4배"><input type="checkbox" id="jb-safe" checked onchange="try{localStorage.setItem('jb-safe',this.checked?'1':'0')}catch(e){};renderJongbe()"> 급등·과열 빼기</label>
    <label style="font-size:12.5px;color:#c9d1d9;cursor:pointer"><input type="checkbox" id="jb-showb" onchange="renderJongbe()"> B등급도 보기</label>
    <label style="font-size:12.5px;color:#c9d1d9;cursor:pointer" title="투자주의·경고·위험, 단기과열, 관리종목을 모든 목록에서 뺍니다"><input type="checkbox" id="jb-noflag" onchange="try{localStorage.setItem('jb-noflag',this.checked?'1':'0')}catch(e){};renderJongbe()"> 경고 빼기</label>
    <label style="font-size:12.5px;color:#c9d1d9;cursor:pointer" title="신용 매수 불가(증거금 100%, 한국투자증권 기준) 종목을 뺍니다"><input type="checkbox" id="jb-nocred" onchange="try{localStorage.setItem('jb-nocred',this.checked?'1':'0')}catch(e){};renderJongbe()"> 신용불가(한투) 빼기</label>
    <span class="ts" id="jb-count"></span>
  </div>
  <div id="jb-fams" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:22px"></div>
  <b style="font-size:15px;color:#e6edf3;display:block;margin:4px 0 8px">③ 뜨는 섹터의 좋은 차트 · 오늘 종가에 살 종목 (종베)</b>
  <table class="pb-table">
    <thead><tr><th>종목</th><th>등급</th><th>그날 봉</th><th>섹터</th><th>종가</th></tr></thead>
    <tbody id="jb-body"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
  <div id="jb-limit" class="ts" hidden></div>
  <div style="margin:12px 0 22px">
    <b style="font-size:14px;color:#e6edf3">🔔 오늘 거래대금 신기록</b> <span class="ts" id="vrc-info"></span>
    <p class="lead" style="margin:4px 0 6px">오늘 거래대금이 6개월 넘게 만의 최고인 종목 (거래대금 30억↑). 오래된 기록일수록 위. 관심 등록용 — 터진 날 추격보다 며칠 쉬는 걸 보고 들어가기.</p>
    <div id="vrc-body" style="display:flex;flex-wrap:wrap;gap:6px">로딩 중…</div>
    <span class="ts" id="lu-info" hidden></span>
    <div id="lu-body" class="ts" hidden></div>
  </div>

  <div style="margin:4px 0 22px">
    <b style="font-size:15px;color:#e6edf3;margin:4px 0 8px">③ 뜨는 섹터의 좋은 차트 · 며칠~몇 주 들고 갈 종목 (스윙·선취매)</b> <span class="ts" id="jb-ch-info"></span>
    <p class="lead" style="margin-top:6px"><b style="color:#3fb950">🚀 돌파</b>·<b>돌파 대기</b> = 120일 박스 상단(20일 넘게 묵은 고점) 처음 넘음·-3% 이내 (이미 많이 오른 종목·꼬리만 남은 종목 뺌) · <b style="color:#3fb950">🚀 꼬리 돌파</b> = 종가 고점 넘고 버티다 옛 꼬리 끝까지 종가로 넘음(물린 사람 0) · <b style="color:#3fb950">저가 지킴</b> = 대량거래 봉 저가 안 깸 · <b style="color:#58a6ff">눌림</b> = 20일 고점 -5~-15% · <b style="color:#e3b341">버팀</b> = 섹터 빠진 날 안 빠짐</p>
    <table class="pb-table">
      <thead><tr><th>종목</th><th>근거</th><th>오늘</th><th>섹터</th><th>종가</th></tr></thead>
      <tbody id="jb-charts"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:16px">로딩 중…</td></tr></tbody>
    </table>
  </div>

  <div style="margin:4px 0 22px">
    <b style="font-size:15px;color:#e6edf3;margin:4px 0 8px">④ 다음에 뜰 섹터 후보 (움직이기 시작)</b>
    <p class="lead" style="margin-top:6px">상위 3 밖인데 최근 5일 시장보다 +2%p↑ · 20일 안 돈 유입(섹터 거래대금 1.5배 + 섹터 +1%) 2번↑ · 순위 5일 새 3계단↑ 중 하나. 누르면 그 섹터 종목이 보입니다.</p>
    <div id="jb-movers" style="display:flex;flex-wrap:wrap;gap:8px"></div>
    <div id="jb-mover-detail" style="margin-top:8px"></div>
  </div>

  <div style="border:1px solid #30363d;border-radius:10px;padding:12px 16px;margin-bottom:20px">
    <b style="color:#e6edf3">✅ 보유·관심 종목 체크</b> <span class="ts">종목명이나 코드를 쉼표로 (브라우저에 기억됩니다)</span>
    <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
      <input id="jb-q" placeholder="예: 디케이티, 원익, 에스피지" style="flex:1;min-width:220px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:6px">
      <button class="btn btn-sm" onclick="jbCheck()">확인</button>
    </div>
    <div id="jb-check" style="margin-top:10px"></div>
  </div>

  <div style="border:1px solid #30363d;border-radius:10px;padding:12px 16px;margin-bottom:20px">
    <b style="color:#e6edf3">🔎 공매도·대차잔고 감시</b> <span class="ts">대차잔고 = 빌려 간 주식(공매도 실탄). 교환사채·유상증자 앞두고 늘면 매도 압력. 종목명·코드 쉼표로 (브라우저 기억)</span>
    <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
      <input id="sw-q" placeholder="예: 가온전선, 티에스이" style="flex:1;min-width:220px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:6px">
      <button class="btn btn-sm" onclick="swCheck()">확인</button>
    </div>
    <div id="sw-out" style="margin-top:10px"></div>
  </div>

  <div style="display:none;border:1px solid #30363d;border-radius:10px;padding:12px 16px;margin-bottom:20px"><!-- 2026-10-05 숨김: 사용자가 진입 종목을 직접 알려 주기로 -->
    <b style="color:#e6edf3">📝 차트 판단 기록</b> <span class="ts" id="lb-stats"></span>
    <p class="ts" style="margin:4px 0 8px">목록 종목 옆 👍(살 만함) · 👎(아님)를 눌러 주세요 — 결과를 모를 때 누른 판단이 고르는 눈을 배우는 재료입니다. 👎는 이유 한 단어(매물대·꼬리·거래 약함 등)를 적으면 더 빨리 배웁니다.
      나중에 보고 "이거 왜 안 들어갔지" 싶은 종목은 아래에 날짜와 함께 따로 남겨 주세요(결과를 알고 고른 것이라 따로 씁니다).</p>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <input id="lb-mname" placeholder="놓친 종목 (예: 필옵틱스)" style="flex:1;min-width:140px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:6px">
      <input id="lb-mdate" type="date" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:5px 8px;border-radius:6px">
      <input id="lb-mmemo" placeholder="그날 들어갔어야 한 이유 (선택)" style="flex:2;min-width:180px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:6px">
      <button class="btn btn-sm" onclick="lbMissed()">남기기</button>
    </div>
    <div id="lb-missed" class="ts" style="margin-top:8px"></div>
  </div>

  <details class="why"><summary>📒 이 화면 종베 후보의 실제 다음 날 결과</summary>
  <div id="jb-perf" class="ts">로딩 중…</div></details>
</div>

<!-- 매매 일지 탭 -->
<div id="panel-journal" class="panel content">
  <div id="jr-login" style="border:1px solid #30363d;border-radius:10px;padding:16px;max-width:420px">
    <b style="color:#e6edf3">🔒 매매 일지</b> <span class="ts">사람마다 따로 기록됩니다. 금액이 보이는 화면이라 비밀번호로 잠급니다.</span>
    <div style="display:flex;flex-direction:column;gap:8px;margin-top:12px">
      <input id="jr-owner" list="jr-owners" autocomplete="off" data-bwignore="true" data-lpignore="true" data-1p-ignore="true" placeholder="이름 (예: 우라늄)" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:8px 10px;border-radius:6px">
      <datalist id="jr-owners"></datalist>
      <input id="jr-pin" type="text" autocomplete="off" data-bwignore="true" data-lpignore="true" data-1p-ignore="true" data-form-type="other" spellcheck="false" placeholder="PIN (4자 이상)" onkeydown="if(event.key==='Enter')jrLogin()" style="-webkit-text-security:disc;text-security:disc;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:8px 10px;border-radius:6px">
      <button class="btn" id="jr-open" onclick="jrLogin()">열기</button>
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

    <div id="jr-size" style="border:1px solid #30363d;border-radius:10px;padding:10px 14px;margin-bottom:14px;font-size:13px"></div>
    <div id="jr-cards" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px"></div>
    <div id="jr-insights" style="border:1px solid #30363d;border-radius:10px;padding:10px 14px;margin-bottom:16px;font-size:13px;line-height:1.7"></div>

    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px" id="jr-groupbtns"></div>
    <table class="pb-table" style="margin-bottom:18px">
      <thead><tr><th id="jr-gname">구분</th><th>건수</th><th>이긴 비율</th><th>평균</th><th>평균 이익 / 손실</th><th>손익</th></tr></thead>
      <tbody id="jr-group"></tbody>
    </table>

    <div style="font-size:15px;font-weight:700;color:var(--text);margin:18px 0 8px">📈 보유 종목 차트 — 내 매수·매도 자리 표시</div>
    <div class="ws" id="jr-ws">
      <div class="ws-list"><div class="ts" id="jr-ws-asof" style="margin:0 4px 4px"></div><div id="jr-ws-items"><div class="ts" style="padding:10px">불러오는 중…</div></div></div>
      <div class="ws-main">
        <div class="ws-head"><b id="jr-ws-name">종목을 고르세요</b><span class="ts" id="jr-ws-sub"></span></div>
        <div class="note" id="jr-ws-note" style="margin-bottom:6px"></div>
        <div class="ws-per" id="jr-ws-tf"><button data-tf="1d" onclick="jrWsTf('1d')">일봉</button><button data-tf="1w" onclick="jrWsTf('1w')">주봉</button><button data-tf="60m" onclick="jrWsTf('60m')">60분</button><button data-tf="30m" onclick="jrWsTf('30m')">30분</button><button data-tf="15m" onclick="jrWsTf('15m')">15분</button><button data-tf="5m" onclick="jrWsTf('5m')">5분</button><button data-tf="1m" onclick="jrWsTf('1m')">1분</button></div>
      <div class="ws-per" id="jr-ws-per"><button data-n="66" onclick="jrWsPeriod(66)">3개월</button><button data-n="130" onclick="jrWsPeriod(130)">6개월</button><button data-n="250" onclick="jrWsPeriod(250)">1년</button></div>
        <div class="lwbox"><div class="lwleg" id="jr-chart-leg"></div><div id="jr-chart" class="lwc"></div></div>
        <details class="ws-lg"><summary>ⓘ 차트 표시 설명</summary><div class="ws-legend"><span>⬆ 흰색 = 내가 산 날 · ⬇ 보라 = 내가 판 날</span><span>▲ 진입 → ▼ 절반 팔기 · 나머지 팔기 / 손절</span><span>● 보라 숫자 6·7 = 종가 진입 점수</span><span>● 점 = 참고</span></div></details>
      </div>
      <aside class="cm-panel" id="jr-ws-panel"></aside>
    </div>
    <div id="jr-holding"></div>

    <div style="font-size:12px;color:#8b949e;margin:6px 0">📒 청산 기록
      <label style="margin-left:8px"><select id="jr-kindf" onchange="jrRenderTrips()" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:2px 6px"><option value="">전체</option></select></label>
      <span style="margin-left:8px">규칙: 손절선 = 산 날 저가 -1% 아래 종가 → 다음 날까지 정리 · 급등(+8%↑) 날 추격 금지 · 물타기 금지 · R = 번 값 ÷ 손절폭 (1이면 손절폭만큼 범) · 장중 매매는 빼고 봄</span></div>
    <table class="pb-table" style="margin-bottom:18px">
      <thead><tr><th>종목</th><th>유형</th><th>산 날 → 판 날</th><th>매수 → 매도</th><th>수익률</th><th>규칙 · R</th><th>산 날 상태</th></tr></thead>
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

<!-- 섹터 캘린더 탭 -->
<div id="panel-calendar" class="panel content">
  <div class="cal-wrap">
    <div class="cal-top">
      <button class="cal-nav" onclick="calMove(-1)" aria-label="이전 달">◀</button>
      <span class="m" id="cal-month"></span>
      <button class="cal-nav" onclick="calMove(1)" aria-label="다음 달">▶</button>
      <span class="ts">그날 가장 강했던 테마 (소속 종목 평균 등락 · 거래대금 100억↑) · 날짜를 누르면 섹터·대장주</span>
    </div>
    <div id="cal-grid" class="cal-grid"></div>
  </div>
  <div id="cal-detail"></div>
</div>

<!-- 섹터 수급 탭 -->
<div id="panel-sector" class="panel content">

  <!-- 순환매 모니터 -->
  <div style="margin-bottom:20px">
    <div style="font-size:12px;color:#8b949e;margin-bottom:6px;letter-spacing:.06em">🔄 순환매 모니터 (섹터 16개) <span class="ts" id="rot-info"></span></div>
    <p class="lead">지금 어느 섹터에 돈이 붙었나를 보는 표. 다음에 어디가 오를지 맞히는 용도는 아닙니다.</p>
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

  <details class="why" style="margin-top:8px"><summary>외국인·기관 수급 테마 표 보기 (참고용)</summary>
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
<!-- 오늘 (대시보드, 2026-10-06) -->
<div id="panel-home" class="panel active content">
  <!-- 첫 화면 위: '오늘' 카드 + '시장 상태' 카드 (2026-10-09 "깔끔한 대시보드처럼") — 예전 띠·판단 상자는 숨김(아래 코드가 아직 씀) -->
  <div class="htop"><section class="hcard" id="hc-today"><div class="ts">불러오는 중…</div></section><section class="hcard" id="hc-market"></section></div>
  <div id="db-strip" class="mstrip" style="display:none"></div>
  <div id="db-verdict" style="display:none"></div>
  <div class="ws">
    <div class="ws-list">
      <div class="ws-search"><input id="ws-q" placeholder="🔍 종목 검색 (이름·코드·초성)" autocomplete="off" oninput="wsSearch(this.value)" onkeydown="if(event.key==='Enter'){const f=document.querySelector('#ws-sr .ws-item');if(f)f.click();}else if(event.key==='Escape'){this.value='';wsSearch('');}"><div id="ws-sr"></div></div>
      <div class="ws-tabs"><button data-t="entry" onclick="wsTab('entry')">오늘 진입</button><button data-t="wait" onclick="wsTab('wait')">대기</button><button data-t="track" onclick="wsTab('track')">신호 추적</button></div>
      <div class="ts" id="ws-lane-note" style="margin:0 4px 4px" title="눌러서 펼치기" onclick="this.classList.toggle('open')"></div>
      <div class="ts" id="ws-asof" style="margin:0 4px 4px"></div>
      <div id="ws-items"><div class="ts" style="padding:10px">불러오는 중…</div></div>
    </div>
    <div class="ws-main">
      <div class="ws-head"><b id="ws-name">종목을 고르세요</b><span class="ts" id="ws-sub"></span></div>
      <div class="note" id="ws-note" style="margin-bottom:6px"></div>
      <div class="ws-ctl"><div class="ws-per" id="ws-tf"><button data-tf="1d" onclick="wsTf('1d')">일봉</button><button data-tf="1w" onclick="wsTf('1w')">주봉</button><button data-tf="60m" onclick="wsTf('60m')">60분</button><button data-tf="30m" onclick="wsTf('30m')">30분</button><button data-tf="15m" onclick="wsTf('15m')">15분</button><button data-tf="5m" onclick="wsTf('5m')">5분</button><button data-tf="1m" onclick="wsTf('1m')">1분</button></div>
      <div class="ws-per" id="ws-per"><button data-n="66" onclick="wsPeriod(66)">3개월</button><button data-n="130" onclick="wsPeriod(130)">6개월</button><button data-n="250" onclick="wsPeriod(250)">1년</button></div></div>
      <div class="lwbox"><div class="lwleg" id="ws-chart-leg"></div><div id="ws-chart" class="lwc"></div></div>
      <details class="ws-lg"><summary>ⓘ 차트 표시 설명</summary><div class="ws-legend"><span>▲ <b>진입</b> = 사기 좋은 자리 (2~3주 보유 · 급등봉 당일은 안 냄) → 스탑로스 = 신호 봉 저가 -1% 예약 · ▼ 14일선 아래 종가 절반 · 21일선 아래 종가 나머지</span><span>↑ 주황 <b>🔥주도</b> = 주도주 매수 (강도 최상위 RS 95↑ · 정배열 · 양봉 위쪽 마감 · 손절폭 8%↓ · 기본 매수와 별도로 소량, 거래당 위험 0.10%) → 스탑로스 = 그날 저가 -1% · 21일선 아래 종가면 다음 날 아침 정리 · 들고 있는 동안 또 뜨면 작은 주황 점 · 봉에 올리면 📍 눌림 / 🚀 돌파 / ⚠️ 과열 표시</span><span>↑ 하늘색 <b>줍기</b> = 급락 날 줍기 · 시험 중 (상승장에서 시장 -2%↓ 날 · 뜨는 섹터 3곳의 주도주가 같이 빠졌을 때 · 손절 20일선 · 수량 절반)</span><span>↑ 보라 <b>매수</b> = 종가 매수 신호 (점수 6↑ · 강도 70~95 · 손절폭 8%↓ · 상승장, ✅ = 손절폭 3%↓) · 다음 날도 이어지면 작은 보라 점 = 자리 유지, ↑ <b>더 좋음</b> = 손절폭이 확 짧아진 날 · 산 뒤 아직 들고 있는데 또 뜨면: ↑ <b>더 사기</b> = 첫 매수가 +1R↑ (같은 크기까지 · 전체 손절을 새 저가 -1%로 올림), ● <b>보유 중</b> = 첫 매수가 +1R 안 됨 → 더 사지 않기 · 봉에 올리면 위에 매수 근거 (점수 6↑ 또는 이평선 모였다 돌파 + 정배열 · 강도 · 손절폭) → 사면 바로 스탑로스 = 그날 저가 -1% 예약 · 21일선 아래 종가면 다음 날 아침 정리</span><span>· 회색 점 = 버틴 종목(텔레그램 종베, 참고)</span><span>· 회색 작은 점 = 돌파 모양만 나온 날 (매수 아님 · 봉에 올리면 이유 — 정배열·강도·손절폭까지 맞으면 보라 매수로 뜸)</span><span>● 초록 = 오르던 종목의 거래 적은 눌림</span><span>· 작은 점 = 참고 (돌파 대기 · 아깝게 놓침 · 상승 추세 시작) — 봉에 올리면 위에 내용</span><span>■ 회색 = 급등봉 · 1년 최대 거래</span><span>▼ 주황 = 조심</span><span>· 두 손가락으로 확대, 끌어서 이동, 누르면 그 날 가격</span></div></details>
    </div>
    <aside class="cm-panel" id="ws-panel"></aside>
  </div>
  <details id="db-more"><summary>📋 오늘 판단 자세히 — 시장 카드 · 장세별 자리 · 참고 (눌러서 펼치기)</summary>
  <div id="db-market" style="margin-bottom:12px"></div>
  <div id="db-top" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;margin-bottom:6px;align-items:stretch"></div>
  <div style="font-size:15px;font-weight:700;color:#e6edf3;margin:14px 0 8px">🎯 오늘 볼 자리 — 장세에 맞는 순서로 3개</div>
  <div id="db-rank"></div>
  <details style="margin-top:14px"><summary style="font-size:15px;font-weight:700;color:#e6edf3;cursor:pointer">📎 참고 — 내일 후보 · 관심 종목 선 · 대량거래 · 내 원칙 (눌러서 펼치기)</summary>
  <div id="db-ref" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;align-items:start;margin-top:10px"></div></details>
  </details>
</div>

<div id="panel-candidates" class="panel content">
  <div id="pb-market" hidden style="border-radius:10px;padding:12px 16px;margin-bottom:14px;border:1px solid #30363d"></div>
  <p class="ts" style="margin:0 0 6px">제목을 누르면 펼쳐지고 접힙니다 (브라우저가 기억).</p>
  <details class="sec" data-k="ss">
    <summary>🎯 손절 짧은 자리 <span class="ts" id="ss-info"></span></summary>

    <p class="lead" style="margin-top:6px"><b>추세선 지지</b>(저점 높이는 추세선 + 위 수평 저항, 전진건설로봇형) · <b>수평 지지 수렴</b>(거래 마르며 좁아지는 박스, SK이터닉스형). 둘 다 앞서 거래가 터진 뒤 거래가 마른 종목. 실적 좋은 순 → 손절선이 가까운 순. 3년 검증: 전체는 우위 거의 없음(+0.1R) · <b>📈 실적 개선이면 +0.5R</b> · 영업 적자(−0.2R)는 뺐음. 강도 숫자 = 시장 대비 세기(70↑ 센 편, 95↑ 🔥 최상위).</p>
    <div id="ss-body" style="display:flex;flex-wrap:wrap;gap:6px" class="ts">로딩 중…</div>
  </details>
  <details class="sec" data-k="cd">
    <summary>📐 차트 모양 후보 <span class="ts" id="cd-sum"></span></summary>
  <p class="lead">불플래그 · 상승삼각형 · 기준봉 눌림 · 장대음봉도지 · <b style="color:#f778ba">VCP</b>(눌림 폭이 15일마다 줄고 거래 마름) 중 하나라도 해당하는 종목. 손절선까지 <b style="color:#3fb950">3~6%</b>가 적정.</p>
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
      <option value="VCP">VCP</option>
      <option value="기준봉 눌림">기준봉 눌림</option>
      <option value="장대음봉도지">장대음봉도지</option>
    </select>
    <label style="display:flex;align-items:center;gap:5px;font-size:13px;color:#c9d1d9;cursor:pointer" title="투자주의·경고·위험, 단기과열, 관리종목을 뺍니다"><input type="checkbox" id="cd-noflag" onchange="try{localStorage.setItem('cd-noflag',this.checked?'1':'0')}catch(e){};renderCandidates()"> 경고 빼기</label>
    <label style="display:flex;align-items:center;gap:5px;font-size:13px;color:#c9d1d9;cursor:pointer" title="신용 매수 불가(증거금 100%) 종목을 뺍니다"><input type="checkbox" id="cd-nocred" onchange="try{localStorage.setItem('cd-nocred',this.checked?'1':'0')}catch(e){};renderCandidates()"> 신용불가(한투) 빼기</label>
    <button class="btn btn-gray btn-sm" onclick="loadCandidates()">⟳ 새로고침</button>
    <span class="ts" id="cd-info"></span>
  </div>
  <table class="pb-table">
    <thead><tr>
      <th>종목</th><th>업종 · 테마</th><th>모양</th><th>현재가 · 거래대금</th><th>손절선</th>
    </tr></thead>
    <tbody id="cd-body"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
  </table>
  </details>
  <details class="sec" data-k="vr">
    <summary>🔥 대량거래 관심종목 <span class="ts" id="vr-sum"></span></summary>

    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:8px">
      <select id="vr-stage" onchange="renderVolumeRecords()">
        <option value="live">볼 만한 것 전부 (무너진 것만 뺌)</option>
        <option value="숨고르기">😮‍💨 쉬는 중 — 거래 마르며 버팀 (진입 대기)</option>
        <option value="꼬리 돌파">🚀 윗꼬리 뚫음 — 터진 날 꼬리 끝을 종가로 넘음</option>
        <option value="신규">🆕 최근 터짐 — 10일 안</option>
        <option value="설거지">⚠ 위에서 팔림 — 터진 뒤 윗꼬리·큰 거래 (조심)</option>
        <option value="">무너진 것까지 전부</option>
      </select>
      <label style="font-size:13px;color:#c9d1d9">시총
        <select id="vr-mincap" onchange="try{localStorage.setItem('vr-mincap',this.value)}catch(e){};renderVolumeRecords()">
          <option value="0">전체</option><option value="500">500억 이상</option><option value="1000">1,000억 이상</option><option value="2000">2,000억 이상</option>
          <option value="3000">3,000억 이상</option><option value="10000">1조 이상</option>
        </select></label>
      <span class="ts" id="vr-info"></span>
      <label style="display:flex;align-items:center;gap:5px;font-size:13px;color:#c9d1d9;cursor:pointer"><input type="checkbox" id="vr-signal" onchange="renderVolumeRecords()"> 🎯 진입 신호만</label>
    </div>
    <p class="lead">🔥 <b>몇 년 만에 거래대금이 가장 크게 터진 종목</b>들입니다. 크게 움직일 힘이 생긴 종목이지만, <b>터진 날 바로 사면 손해가 많았습니다</b>.
      쉬는 걸 지켜보다가 <b style="color:#e3b341">🎯 다시 힘이 붙는 날</b> 들어가세요. 손절선 = 터지기 전날 종가.</p>
    <details class="why"><summary>📖 이 목록 보는 법 (단계 뜻 · 언제 사나 · 파는 법)</summary>
      <div style="line-height:1.75;font-size:13px">
      <b>무엇을 모으나</b><br>
      최근 4개월 안에 <b>평소 10배 넘는 거래대금</b>이 터진 종목 (리츠·스팩·ETF 제외). 두 가지입니다.<br>
      ① 그날 <b>+5% 넘는 양봉</b>으로 크게 오른 경우 ② 장중 <b>+8% 넘게 쐈다가 밀린</b> 경우(윗꼬리, 대한제강 10/1형 — 블록딜은 뺌, 지켜보기용)<br><br>
      <b>단계 뜻</b><br>
      😮‍💨 <b>쉬는 중</b> — 거래가 말라 가면서 기준선(터지기 전날 종가)을 지키는 중 → <b>진입 대기</b><br>
      🚀 <b>윗꼬리 뚫음</b> — 터진 날 윗꼬리 끝(그날 고가)을 종가로 넘음 → 그날 산 사람이 전부 수익이라 위에 팔 물량이 없음<br>
      🆕 <b>최근 터짐</b> — 터진 지 10일 안<br>
      📈 <b>오르는 중</b> — 아직 거래가 안 말랐음 (쉬기 전)<br>
      ⚠ <b>위에서 팔림</b> — 터진 다음 1~2일 더 큰 거래로 윗꼬리 음봉 → 조심<br>
      <span class="ts">무너짐</span> — 기준선 아래로 내려갔거나 한 번이라도 -15% 아래로 마감 → 끝난 종목 (기본 화면에서 뺌)<br><br>
      <b style="color:#e3b341">🎯 언제 사나</b><br>
      '쉬는 중'에 <b>+3% 양봉 · 거래 2배</b>로 다시 고개를 드는 날 (돌려세우는 봉) + 시장이 상승·횡보일 때<br>
      → 실적까지 좋아진 종목(📈 실적)이면 더 좋았습니다. 하락장에선 쉬기.<br><br>
      <b>왜 터진 날 안 사나</b><br>
      터진 날 바로 사면 대부분 다시 밀렸습니다. 대신 대부분 20일 안에 그보다 높은 값을 한 번은 찍습니다. 쉬었다가 다시 고개를 드는 날을 기다립니다.<br><br>
      <b>파는 법</b><br>
      +10%에서 절반 팔고, 나머지는 보유 중 최고 종가에서 -8% 내려오면 정리.<br>
      다음 날 시초가가 +5% 넘게 뜨면 일부 덜기.
      </div>
    </details>
    <table class="pb-table">
      <thead><tr><th>종목</th><th>단계</th><th>신기록일</th><th>그 뒤 최고</th><th>지금</th></tr></thead>
      <tbody id="vr-body"><tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">로딩 중…</td></tr></tbody>
    </table>
  </details>
  <details class="sec" data-k="ema">
    <summary>📏 EMA 모임 돌파 · 후보 <span class="ts" id="ema-info"></span></summary>
    <p class="lead" style="margin-top:6px">단기 <b>EMA 5·10·20</b>이 모여 있다가(전날 간격 4%↓) 세 선 위·10일 고점 돌파(+3%↑·거래 1.5배↑). <b>EMA60은 추세 필터</b> — 📈정배열(종가>EMA60 & EMA20>EMA60)이면 5일 성적 2~3배. 손절 = 돌파 봉 저가 아래 마감 · 5~10일.</p>
    <div class="ts" style="margin:6px 0 4px">오늘 돌파</div>
    <div id="ema-brk" style="display:flex;flex-wrap:wrap;gap:6px" class="ts">로딩 중…</div>
    <div class="ts" style="margin:10px 0 4px">내일 후보 — EMA 3% 안으로 모여서 10일 고점 4% 안 · 60일선 위 · 오늘 조용</div>
    <div id="ema-wait" style="display:flex;flex-wrap:wrap;gap:6px" class="ts"></div>
  </details>
  <details class="sec" data-k="lp">
    <summary>🏦 대형주 눌림 박스 <span class="ts">· 참고 (검증 약함)</span> <span class="ts" id="lp-info"></span></summary>
    <p class="lead" style="margin-top:6px">하루 거래대금 <b>500억↑ 대형주</b>가 60일 고점에서 <b>-5~-20%</b> 눌려 120일선 근처 위에서 쉬고, 거래가 평소(60일) 이하. 대형주는 바닥(-40%)까지 잘 안 빠져서 바닥 박스 감시에는 안 잡히는 자리(에이피알형). <b>손절 = 최근 15일 박스 하단 아래 마감</b> · 20일 보유. <span style="color:#d29922">⚠️ 근거가 '3년 20일 뒤 평균 +7%' 하나뿐(시장 대비·손절 반영 안 됨) — 매수 신호가 아니라 차트 볼 목록.</span></p>
    <div id="lp-body" style="display:flex;flex-wrap:wrap;gap:6px" class="ts">로딩 중…</div>
  </details>
  <details class="sec" data-k="bb">
    <summary>👀 바닥 박스 감시 <span class="ts" id="bb-info"></span></summary>

    <p class="lead" style="margin-top:6px">급등했다 크게 빠진 뒤(120일 고점 -40%↓, 1년 저점보다는 15%↑ 위) 15일째 좁은 박스(폭 13%↓)에서 거래 없이 버티는 종목. 아직 신저가를 깨는 종목은 뺍니다. <b>추천이 아니라 감시용</b> — 박스에서 터지는 날(🔔) 섹터·시장이 받쳐 주면 봅니다.</p>
    <div id="bb-burst" style="margin-bottom:8px"></div>
    <div id="bb-body" style="display:flex;flex-wrap:wrap;gap:6px" class="ts">로딩 중…</div>
  </details>
</div>

<!-- 캔들차트 모달 (토스증권 실시간) -->
<div class="modal-bg" id="chart-modal-bg" onclick="if(event.target===this)closeChartModal()">
  <div class="modal cm-wide">
    <span class="close-btn" onclick="closeChartModal()">✕</span>
    <h2 id="chart-modal-title">종목 차트</h2>
    <div class="cm-body">
      <div class="cm-chart">
        <div class="note" id="chart-modal-note" style="margin-bottom:8px"></div>
        <div class="ws-per" id="cm-tf"><button data-tf="1d" onclick="cmTf('1d')">일봉</button><button data-tf="1w" onclick="cmTf('1w')">주봉</button><button data-tf="60m" onclick="cmTf('60m')">60분</button><button data-tf="30m" onclick="cmTf('30m')">30분</button><button data-tf="15m" onclick="cmTf('15m')">15분</button><button data-tf="5m" onclick="cmTf('5m')">5분</button><button data-tf="1m" onclick="cmTf('1m')">1분</button></div>
        <div class="lwbox"><div class="lwleg" id="cm-chart-leg"></div><div id="cm-chart" class="lwc"></div></div>
      </div>
      <aside class="cm-panel" id="cm-panel"></aside>
    </div>
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
// 비밀번호 관리자(Bitwarden 등) 자동완성 창이 뜨지 않게 — 모든 칸 (2026-10-07: 매매 일지 로그인 칸을 남겼더니 숨은 탭의 그 칸 때문에 화면 왼쪽 위에 창이 떴음)
(function(){
  const mark=el=>{ if(el.tagName==='INPUT'||el.tagName==='TEXTAREA'){ el.setAttribute('data-bwignore','true'); el.setAttribute('data-lpignore','true'); el.setAttribute('data-1p-ignore','true'); el.setAttribute('data-form-type','other'); el.setAttribute('autocomplete','off'); } };
  const scan=root=>{ if(root.querySelectorAll) root.querySelectorAll('input,textarea').forEach(mark); if(root.tagName==='INPUT'||root.tagName==='TEXTAREA') mark(root); };
  document.addEventListener('DOMContentLoaded',()=>{ scan(document);
    new MutationObserver(ms=>ms.forEach(m=>m.addedNodes.forEach(n=>n.nodeType===1&&scan(n)))).observe(document.body,{childList:true,subtree:true}); });
})();
</script>
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
  // 2026-10-05 사용자 "당분간 차트 후보 보고 매매" → 차트 후보를 첫 탭으로, 종베는 검증 중으로 뒤로
  const tabs = ['home','candidates','calendar','sector','journal','screener','heatmap','jongbe','discussion','suggest'];
  if(!tabs.includes(id))return;
  try{ history.replaceState(null,'',id==='home'?location.pathname:'#'+id); }catch(e){}   // 새로고침해도 이 탭에 남게
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',tabs[i]===id));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.getElementById('panel-'+id).classList.add('active');
  if(id==='screener')loadTopValue();
  if(id==='jongbe')loadJongbe();
  if(id==='journal')loadJournal();
  if(id==='sector'){loadSector();loadLiveThemes();loadRotation();}
  if(id==='calendar')loadSectorCal();
  if(id==='heatmap')loadHeatmap();
  if(id==='candidates')loadCandidates();
  if(id==='home'){loadDashboard();loadWorkspace();}
  if(id==='suggest')document.getElementById('suggest-frame').src='/suggestions';
  if(id==='discussion'&&!document.getElementById('discussion-frame').src)document.getElementById('discussion-frame').src='/discussion';
}

// ── 오늘 강한 테마 (실시간) ──────────────────────────────────
// ── 종베 후보 ─────────────────────────────────────────────────
let _jbData=null;
// ── 오늘 (대시보드) ─────────────────────────────────────────
async function loadDashboard(){
  // 지난번 결과를 먼저 바로 그리고(브라우저에 저장), 새 결과가 오면 다시 그린다
  let old=null; try{ old=JSON.parse(localStorage.getItem('db-last')||'null'); }catch(e){}
  if(old) renderDashboard(old, true);
  const d=await fetch(`${API}/dashboard`).then(r=>r.ok?r.json():null).catch(()=>null);
  if(!d){ if(!old) document.getElementById('db-verdict').textContent='불러오지 못했습니다'; return; }
  try{ localStorage.setItem('db-last',JSON.stringify(d)); }catch(e){}
  renderDashboard(d, false);
  loadLive(d);
}
// 장중(평일 9:00~15:40)에는 지금 가격으로 장세를 다시 판단해 판단 문구·과매도·순환 카드·카드 순서를 바꾼다 (대시보드 본체는 장 마감 데이터) — 2026-10-07
async function loadLive(d){
  const k=new Date(new Date().toLocaleString('en-US',{timeZone:'Asia/Seoul'})), hm=k.getHours()*100+k.getMinutes(), wd=k.getDay();
  if(wd===0||wd===6||hm<900||hm>1540) return;
  const el=document.getElementById('db-dip'); if(el) el.insertAdjacentHTML('afterbegin','<div class="ts" id="db-dip-wait">장중 가격으로 확인 중…</div>');
  const r=await fetch(`${API}/dashboard/dip-live`).then(x=>x.ok?x.json():null).catch(()=>null);
  if(!r){ const w=document.getElementById('db-dip-wait'); if(w) w.textContent='장중 가격을 못 불러왔습니다'; return; }
  // 시장 국면·20일 비교·섹터 표·조건 B·박스 돌파도 지금 가격으로 바꿔 그림 (2026-10-07 "지금 기준으로 시장 데이터 전부")
  const d2={...d};
  if(r.market) d2.market={...r.market, sh_foreign5:(d.market||{}).sh_foreign5};
  ['sector_day','heat','b_sectors','best_lead','best_swing','box_break','box_near','index_today'].forEach(k=>{ if(r[k]!==undefined) d2[k]=r[k]; });
  renderDashboard(d2, false, r);
}
// 첫 화면 위 카드 두 장 (2026-10-09) — 색약: 상태는 ▲■▼ 모양 + 파랑/회색/주황
function renderHomeTop(d, live){
  const sg=x=>(x>0?'+':'')+x, m=d.market||{}, all=m['전체']||{}, br=d.breadth||{}, it=d.index_today||{}, md=(live&&live.mode)||d.mode||{};
  const B={g:['g','▲ 양호'],n:['n','■ 중립'],b:['b','▼ 약화']};
  const rows=[];
  const add=(t,sub,v,k,click,bt)=>rows.push({t,sub,v,k,click,bt});
  add('시장 국면','종목 평균 지수 · 20일선 '+(all.vs_ma20_pct!=null?sg(all.vs_ma20_pct)+'%':'-'),all.state||'-',all.state==='상승'?'g':all.state==='하락'?'b':'n');
  if(br.pct!=null) add('시장 폭','50일선 위 비율 · 10일 '+sg(br.chg10)+'%p'+(br.weak?' · 곧 흔들릴 수 있음':''),br.pct+'%',br.narrow?'b':br.weak?'n':br.pct>=55?'g':'n');
  // 과매수·과매도 — 판단은 사용자, 사이트는 온도만 (2026-10-09) · 색 대신 모양·글자로 (색약)
  if(br.temp) add('과매수 · 과매도','20일선 위 '+br.br20+'% · 20일선 +20% 넘은 종목 '+br.hot20+'% · 3일 '+sg(br.c3)+'%'+(br.temp_say?' · '+br.temp_say:''),br.temp,'n',null,br.temp_k==='up'?'⚠ 과매수':br.temp_k?'⬇ 과매도':'■ 보통');
  if(br.hi60!=null) add('신고가 · 신저가','최근 60일 최고 · 최저 종가 종목 수',br.hi60+' · '+br.lo60,br.hi60>=br.lo60*2&&br.hi60>=10?'g':br.lo60>br.hi60?'b':'n');
  if(m.rel!=null) add('삼전·하닉 vs 코스닥','최근 20일 · 삼하 '+sg(m.sh20)+'% · 코스닥 '+sg(m.kq20)+'%',sg(m.rel)+'%p',m.rel>=10?'b':m.rel<=-3?'g':'n');
  if(m.sh_foreign5!=null) add('외국인','삼전·하닉 5일 순매수',(Math.abs(m.sh_foreign5)>=10000?(m.sh_foreign5>=0?'+':'-')+(Math.abs(m.sh_foreign5)/10000).toFixed(1)+'조':(m.sh_foreign5>=0?'+':'')+Math.round(m.sh_foreign5).toLocaleString()+'억'),m.sh_foreign5>0?'g':'b');
  const good=rows.filter(r=>r.k==='g').length;
  let vt, vk;
  // 속 약해짐 = '꺾임'이 아니라 '곧 흔들림' (12년: 20일 안 20일선 이탈 88% vs 76%, 낙폭은 같고 20일 뒤 시장은 더 오름) — 2026-10-09
  if(all.state==='하락'){ vt='쉬는 날'; vk='b'; } else if(br.weak||br.narrow){ vt='곧 흔들릴 수 있음 · 쫓지 말고 빠지는 날 줍기'; vk='n'; } else if(all.state==='상승'){ vt='진입 가능'; vk='g'; } else { vt='골라서 작게'; vk='n'; }
  const when=live?`장중 ${live.as_of}`:`${(d.as_of||'').slice(5).replace('-','/')} 마감 기준`;
  document.getElementById('hc-market').innerHTML=`<div class="hc-h"><b>시장 상태</b><span>${when}</span></div>
    <div class="hc-verdict"><span class="hc-badge ${B[vk][0]}">${B[vk][1].split(' ')[0]}</span><b>${vt}</b></div>
    <div class="hc-sum">근거 ${rows.length}개 중 ${good}개 양호 · 하락장은 쉬고, 시장이 -2% 넘게 빠지는 날은 센 종목 줍기</div>
    <div class="hc-bars">${rows.map(r=>`<i class="${r.k==='g'?'g':r.k==='b'?'b':''}"></i>`).join('')}</div>
    ${rows.map(r=>`<div class="hc-row k-${r.k}" title="${r.t} — ${r.sub}"><div class="t"><b>${r.t}</b><span>${r.sub}</span></div><div class="v">${r.v}</div><span class="hc-badge ${B[r.k][0]}">${r.bt||B[r.k][1]}</span></div>`).join('')}`;
  const ix=k=>{ const x=it[k]; if(!x) return ''; const c=x.pct>=0?'var(--up)':'var(--down)';
    return `<div class="hc-num" style="cursor:pointer" onclick="openIndexChart('${k==='코스피'?'KOSPI':'KOSDAQ'}','${k}')"><div class="l">${k}${x.status==='OPEN'?' · 장중':''}</div><div class="v">${x.close}</div><div class="s" style="color:${c}">${sg(x.pct)}%</div></div>`; };
  const st=d.sectors_today||{}, pill=(x,c)=>`<span class="hc-pill ${c}" title="20일 순위 ${x.rank||'-'}위 (10일 전 ${x.rank_10ago||'-'}위)">${x.family} <b style="color:${x.chg>=0?'var(--up)':'var(--down)'}">${sg(x.chg)}%</b></span>`;
  document.getElementById('hc-today').innerHTML=`<div class="hc-h"><b>오늘</b><span class="hc-tg"><button data-s="KOSPI" onclick="hcSpark('KOSPI')">코스피</button><button data-s="KOSDAQ" onclick="hcSpark('KOSDAQ')">코스닥</button></span></div>
    <div class="hc-spark" id="hc-spark"></div><div class="hc-sx" id="hc-sx"></div>
    <div class="hc-head">${md.title||'판단 준비 중'}</div><div class="hc-do">${md.do?'→ '+md.do:''}</div>
    <div class="hc-nums">${ix('코스피')}${ix('코스닥')}${br.adv_pct!=null?`<div class="hc-num"><div class="l">오른 종목 비율</div><div class="v">${br.adv_pct}%</div><div class="s" style="color:var(--muted)">조용한 종목 빼고</div></div>`:''}</div>
    ${(st.strong||[]).length?`<div class="hc-flow"><span class="k">강함</span><div>${st.strong.map(x=>pill(x,'up')).join('')}</div><span class="k">약함</span><div>${(st.weak||[]).map(x=>pill(x,'dn')).join('')}</div></div>`:''}`;
}
// '오늘' 카드 지수 하루 선 (SVG) — 전일 종가 점선 · 위면 빨강, 아래면 파랑
let _hcSym='KOSPI';
async function hcSpark(sym){
  _hcSym=sym||_hcSym; document.querySelectorAll('.hc-tg button').forEach(b=>b.classList.toggle('on',b.dataset.s===_hcSym));
  const box=document.getElementById('hc-spark'); if(!box) return;
  const d=await fetch(`${API}/index/intraday/${_hcSym}`).then(r=>r.ok?r.json():null).catch(()=>null);
  if(!d||!d.points||d.points.length<2){ box.innerHTML='<div class="ts" style="padding:40px 0;text-align:center">지수 선을 못 불러왔습니다</div>'; return; }
  const P=d.points.map(p=>p[1]), lo=Math.min(...P,d.prev), hi=Math.max(...P,d.prev), W=600, H=92, pad=6;
  const x=i=>{ const t=d.points[i][0], m=(+t.slice(0,2)-9)*60+(+t.slice(2)); return m/390*W; }, y=v=>pad+(hi-v)/((hi-lo)||1)*(H-pad*2);
  const line=P.map((v,i)=>`${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const c=d.close>=d.prev?'var(--up)':'var(--down)', fill=d.close>=d.prev?'rgba(248,81,73,.10)':'rgba(88,166,255,.12)';
  box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polygon points="${x(0).toFixed(1)},${H} ${line} ${x(P.length-1).toFixed(1)},${H}" fill="${fill}"/>
    <line x1="0" x2="${W}" y1="${y(d.prev)}" y2="${y(d.prev)}" stroke="var(--muted)" stroke-dasharray="3 4" stroke-width="1" vector-effect="non-scaling-stroke"/>
    <polyline points="${line}" fill="none" stroke="${c}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
  document.getElementById('hc-sx').innerHTML=`<span>09:00</span><span>${d.date.slice(5).replace('-','/')} · 전일 종가 ${d.prev.toLocaleString()}</span><span>15:30</span>`;
}
async function renderDashboard(d, stale, live){
  try{ renderHomeTop(d, live); hcSpark(); }catch(e){ console.error(e); }
  const v=document.getElementById('db-verdict');
  const m=d.market||{}, all=m['전체']||{}, al=d.alert||{};
  const col={상승:'#3fb950',횡보:'#d29922',하락:'#f85149'}, ico={상승:'🟢',횡보:'🟡',하락:'🔴'};
  const sg=x=>(x>0?'+':'')+x;
  // 카드를 위에서 아래로 흘려 채움(PC에서 좁은 기둥 8개로 쪼개지지 않게, 폰은 한 줄) — 2026-10-06
  // 순위 카드: 왼쪽 굵은 띠 + 순위 번호 (위에서 아래로 1→4)
  // 첫 화면은 대시보드 — 설명은 한 줄(누르면 펼침), 종목이 많으면 잘라서 '더 보기' (2026-10-07 "정보가 너무 많다")
  const rcard=(no,c,title,how,body,long)=>`<div style="display:flex;gap:12px;border:1px solid #30363d;border-left:5px solid ${c};border-radius:12px;padding:12px 14px;margin-bottom:10px;background:#0d1117">
    <div style="flex:none;width:34px;height:34px;border-radius:50%;background:${c};color:#0d1117;font-weight:800;display:flex;align-items:center;justify-content:center;font-size:15px">${no}</div>
    <div style="flex:1;min-width:0"><div style="font-size:14.5px;font-weight:700;color:#e6edf3">${title}</div>
    <div class="ts" style="margin:2px 0 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer" title="눌러서 설명 펼치기" onclick="this.style.whiteSpace=this.style.whiteSpace==='normal'?'nowrap':'normal'">ⓘ ${how}</div>
    ${long?`<div style="max-height:118px;overflow:hidden">${body}</div><a href="#" class="ts" style="color:#58a6ff" onclick="this.previousElementSibling.style.maxHeight='none';this.remove();return false">더 보기 ▾</a>`:body}</div></div>`;
  const card=(t,body)=>`<div style="width:100%;height:100%;border:1px solid #30363d;border-radius:12px;padding:12px 14px;background:#0d1117;box-sizing:border-box"><div style="font-size:13px;color:#8b949e;margin-bottom:8px;font-weight:600">${t}</div>${body}</div>`;
  const more=(arr,n,f)=>arr.length<=n?arr.map(f).join(''):arr.slice(0,n).map(f).join('')+`<details style="display:inline"><summary class="ts" style="cursor:pointer;display:inline">외 ${arr.length-n}개 더 보기</summary>${arr.slice(n).map(f).join('')}</details>`;
  const chip=(x,c,extra)=>`<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 9px;border:1px solid ${c||'#30363d'};border-radius:8px;cursor:pointer;font-size:12.5px" onclick="openChartModal('${x.code}','${x.name}','')"><b style="color:#e6edf3">${x.name}</b>${extra||''}</span>`;
  // 오늘 판단 = 장세에 따라 '어떤 방식으로 살지' (2026-10-07: 한 가지 규칙만 매일 쓰다 10/6 과열 섹터에 몰려 짐)
  const md=(live&&live.mode)||d.mode;
  const mcol={쉬기:'#f85149',과매도:'#58a6ff',과열:'#ff7b72',주도:'#3fb950',순환:'#bc8cff',쉬어가기:'#8b949e'};
  let vt,vc;
  if(md){ vt=`${md.icon} <b>${md.title}</b>${md.sectors&&md.sectors.length?` <span style="font-size:14px">(${md.sectors.join(' · ')})</span>`:''}<div style="margin-top:4px;font-size:14px">→ ${md.do}</div>`; vc=mcol[md.mode]||'#8b949e'; }
  else if(all.state==='하락'){ vt='🔴 <b>오늘은 쉬는 날</b>'; vc='#f85149'; }
  else { vt='⚪ <b>판단 준비 중</b>'; vc='#8b949e'; }
  const warn=[];
  if(al.suck) warn.push('🧲 삼하가 수급 흡수 중 — 코스닥 비중 줄이기');
  if(all.state!=='하락'&&all.vs_ma20_pct!=null&&all.vs_ma20_pct<=1) warn.push('⚠️ 하락 전환 가까움 — 빠지는 종목 줍기 금지');
  v.style.borderColor=vc; v.style.background=vc+'14';
  const when=live?`⏱ 장중 ${live.as_of} 가격 기준 — 시장·섹터·판단·종베·박스·과매도·순환 모두 지금 가격 (거래량은 마감 환산, 종가 전이라 바뀔 수 있음) · 추세 도지·이틀 쉼·돌려세움·내일 후보는 ${d.as_of||''} 종가 기준`:`${d.as_of||''} 종가 기준 · 장 마감 수집 뒤(16시쯤) 갱신 · 장중엔 지금 가격으로 다시 판단`;
  v.innerHTML=`<div>${vt}</div>${warn.map(w=>`<div style="margin-top:6px;color:#e3b341">${w}</div>`).join('')}<div class="ts" style="margin-top:6px">${when}</div>`;
  const mk=k=>{ const x=m[k]||{}; return `<div style="flex:1;min-width:150px;border:2px solid ${col[x.state]||'#30363d'};border-radius:14px;padding:14px 18px;background:${(col[x.state]||'#30363d')}14">
    <div style="font-size:15px;color:#c9d1d9;font-weight:600">${k} <span class="ts" style="font-weight:400">국면(추세)</span></div>
    <div style="font-size:30px;font-weight:800;color:${col[x.state]||'#c9d1d9'};margin:4px 0">${ico[x.state]||''} ${x.state||'-'}</div>
    <div style="font-size:14px;color:#c9d1d9">${x.today_pct!=null?`오늘 <b style="color:${x.today_pct>=0?'#f85149':'#58a6ff'}">${sg(x.today_pct)}%</b> · `:''}20일선보다 <b>${x.vs_ma20_pct!=null?sg(x.vs_ma20_pct)+'%':'-'}</b> · 최근 20일 <b>${x.cum20_pct!=null?sg(x.cum20_pct)+'%':'-'}</b></div></div>`; };
  const rel=m.rel, relW=rel==null?0:Math.max(0,Math.min(100,(rel+15)/30*100));
  // 시장 한 줄 (맨 위 고정): 오늘 지수 · 국면 3개 · 삼하 vs 코스닥 20일
  { const it=d.index_today||{}, RG={상승:['▲','#3fb950'],횡보:['■','#d29922'],하락:['▼','#f85149']};
    const ix=k=>{ const x=it[k]; if(!x) return ''; const c=x.pct>=0?'var(--up)':'var(--down)';
      return `<span class="ix" onclick="openIndexChart('${k==='코스피'?'KOSPI':'KOSDAQ'}','${k}')" title="누르면 차트"><span class="ts">${k}${x.status==='OPEN'?' 장중':''}</span><b style="color:${c}">${x.close}</b><span style="color:${c}">${sg(x.pct)}%</span></span>`; };
    const rg=k=>{ const x=m[k]||{}, r=RG[x.state]||['·','#8b949e'];
      return `<span class="rg" style="border-color:${r[1]}66" title="20일선보다 ${x.vs_ma20_pct!=null?sg(x.vs_ma20_pct)+'%':'-'} · 최근 20일 ${x.cum20_pct!=null?sg(x.cum20_pct)+'%':'-'}"><span class="ts">${k}</span><b style="color:${r[1]}">${r[0]} ${x.state||'-'}</b><span class="ts">${x.vs_ma20_pct!=null?'20일선 '+sg(x.vs_ma20_pct)+'%':''}</span></span>`; };
    const sh=m.sh20, kq=m.kq20;
    document.getElementById('db-strip').innerHTML=`${ix('코스피')}${ix('코스닥')}<span class="sep"></span><span class="ts">국면</span>${rg('전체')}${rg('코스피')}${rg('코스닥')}`
      +(sh!=null&&kq!=null?`<span class="sep"></span><span class="ts">최근 20일</span><span>삼하 <b style="color:${sh>=0?'var(--up)':'var(--down)'}">${sg(sh)}%</b> · 코스닥 <b style="color:${kq>=0?'var(--up)':'var(--down)'}">${sg(kq)}%</b></span>`:'')
      +(d.breadth?`<span class="sep"></span><span class="rg" style="border-color:${d.breadth.weak||d.breadth.narrow?'#f0883e':'var(--line)'}" title="거래대금 30억↑ 종목 중 50일선 위 비율 · 지수는 오르는데 이 비율이 줄면 속이 약해지는 것 (3년: 그때 진입 10일 -0.3% vs 폭 늘 때 +3.4%)"><span class="ts">시장 폭</span><b>${d.breadth.pct}%</b><span class="ts">10일 ${d.breadth.chg10>0?'+':''}${d.breadth.chg10}%p</span>${d.breadth.weak?'<b style="color:#f0883e">⚠ 속 약해짐</b>':d.breadth.narrow?'<b style="color:#f0883e">⚠ 폭 좁음</b>':''}</span>`:'')
      +(m.sh_foreign5!=null?`<span class="ts">외국인 삼하 5일 ${Math.round(m.sh_foreign5).toLocaleString()}억</span>`:''); }
  const top=[],rank=[],ref=[];
  document.getElementById('db-market').innerHTML=card('📊 시장',
    // ① 오늘 지수 (실제 코스피·코스닥, 네이버) ② 국면(추세) — 둘을 나눠 보여 줌 (2026-10-07 "시장 상태랑 당일 지수 상태 구분 필요")
    (()=>{ const it=d.index_today||{}; const one=k=>{ const x=it[k]; if(!x) return ''; const c=x.pct>=0?'#f85149':'#58a6ff';
      return `<div onclick="openIndexChart('${k==='코스피'?'KOSPI':'KOSDAQ'}','${k}')" title="누르면 최근 60일 차트" style="cursor:pointer;flex:1;min-width:150px;border:1px solid #30363d;border-radius:10px;padding:8px 14px;background:#161b22"><span class="ts">${k} 지수 ${x.status==='OPEN'?'(장중)':''} · 📈 차트</span><br><b style="font-size:20px;color:${c}">${x.close}</b> <b style="color:${c}">${sg(x.pct)}%</b></div>`; };
      return (it['코스피']||it['코스닥'])?`<div class="ts" style="margin-bottom:6px">📉 오늘 지수 (하루 오르내림)</div><div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px">${one('코스피')}${one('코스닥')}</div>`:''; })()
    +`<div class="ts" style="margin-bottom:6px">🧭 시장 국면 (추세 · 종목 평균 지수가 20일선 아래면 하락, 20일선이 오르면 상승 — 하루 빠져도 20일선 위면 상승 유지)</div><div style="display:flex;gap:12px;flex-wrap:wrap">${mk('전체')}${mk('코스피')}${mk('코스닥')}</div>`);
  // 막대 하나(-15~+15%p)는 0이 어딘지 안 보여 '늘어나는' 것처럼 읽혔음 → 두 막대를 나란히 비교 (2026-10-06)
  const mx=Math.max(Math.abs(m.sh20||0),Math.abs(m.kq20||0),1);
  const bar=(lab,v,c)=>`<div style="display:flex;align-items:center;gap:8px;font-size:13px;margin:4px 0"><span style="width:72px;flex:none">${lab}</span><div style="flex:1;height:10px;background:#21262d;border-radius:5px;overflow:hidden"><div style="height:10px;width:${Math.abs(v)/mx*100}%;background:${v>=0?c:'#58a6ff'}"></div></div><b style="width:58px;text-align:right">${sg(v)}%</b></div>`;
  const who=rel==null?'':rel>=15?'<b style="color:#f85149">🧲 삼하 독주 — 코스닥 비중 줄이기</b>':rel>=10?'<b style="color:#d29922">삼하 쪽으로 기우는 중</b>':rel<=-3?'<b style="color:#3fb950">코스닥 우세</b>':'<b>비슷</b>';
  top.push(card('🧲 최근 20일 — 삼전·하닉 vs 코스닥',rel==null?'<span class="ts">-</span>':
    bar('삼전·하닉',m.sh20,'#f778ba')+bar('코스닥 평균',m.kq20,'#3fb950')
    +`<div style="margin-top:6px;font-size:13px">→ ${who} <span class="ts">(차이 ${sg(rel)}%p)</span></div>
     <div class="ts" style="margin-top:4px">삼하가 코스닥보다 +15%p 넘게 앞서면 경고 · 외국인 삼하 5일 <b style="color:${m.sh_foreign5>0?'#f85149':'#58a6ff'}">${(m.sh_foreign5>0?'+':'')+(m.sh_foreign5||0).toLocaleString()}억</b></div>`));
  const sd=Object.entries(d.sector_day||{});
  top.push(card('🔥 섹터 (20일 순위 · 오늘 등락 중간 · 거래 중간)',sd.map(([f,x],i)=>`<div style="display:flex;justify-content:space-between;font-size:13px;padding:3px 0;border-bottom:1px solid #21262d"><span>${i+1}. ${d.b_sectors.includes(f)?'⭐ ':''}<b style="color:#e6edf3">${f}</b></span><span><span style="color:${x.chg>=0?'#f85149':'#58a6ff'}">${sg(x.chg)}%</span> · <span class="ts">${x.tvx==null?'거래 -':x.tvx+'배'}</span>${x.heat!=null?` · <span style="color:${x.heat>=25?'#ff7b72':x.heat>=10?'#d29922':'#8b949e'}" title="섹터 종목 중 20일선보다 20% 넘게 뜬 비율">과열 ${x.heat}%</span>`:''}</span></div>`).join('')+'<div class="ts" style="margin-top:6px">⭐ = 오늘 돈 몰린 섹터 · 과열 = 섹터 종목 중 20일선보다 20%↑ 뜬 비율 (25%↑ 🔥 들고 가지 말 것)</div>'));
  const H=d.heat||{}, isHot=x=>(H[x.family]||0)>=25;
  // EMA(5·10·20) 모임/벌어짐 표시 (2026-10-07 ema_squeeze.py: 모임 4%↓ 돌파 5일 +0.9~1.0%, 벌어짐 7%↑ -0.2~-1.4%)
  const emaTag=x=>x.ema_gap==null?'':x.ema_gap<=4?` <b style="color:#3fb950;font-size:11px" title="돌파 전날 5·10·20일 EMA 간격 ${x.ema_gap}%">EMA 모임✓</b>`:x.ema_gap>=7?` <b style="color:#d29922;font-size:11px" title="돌파 전날 5·10·20일 EMA 간격 ${x.ema_gap}% — 벌어진 상태 돌파는 5일 평균 마이너스였음">⚠EMA 벌어짐</b>`:'';
  const bchip=x=>chip(x,x.retail_only?'#f85149':'#9e6a03',` <span style="color:#f85149">${sg(x.change_pct)}%</span> <span class="ts">${x.tv_x}배 · ${x.family}</span>${emaTag(x)}${x.retail_only?' <b style="color:#f85149;font-size:11px">⚠개인만</b>':''}${isHot(x)?' <b style="color:#ff7b72;font-size:11px" title="섹터 종목 중 20일선보다 20% 넘게 뜬 비율 '+H[x.family]+'%">🔥과열·다음 날 정리만</b>':''}`);
  const hotNote=[...(d.best_lead||[]),...(d.best_swing||[])].some(isHot)?'<div class="ts" style="color:#ff7b72;margin-top:4px">🔥과열 섹터 = 섹터 종목 25% 넘게 20일선보다 20%↑ 뜸 → 다음 날은 좋았지만 5~10일 들고 가면 나빴음</div>':'';
  const anyRetail=(d.best||[]).some(x=>x.retail_only)?'<div class="ts" style="color:#f85149;margin-top:4px">⚠개인만 = 외인·기관 둘 다 팔았는데 오른 날 — 빼는 게 좋음</div>':'';
  const C={};   // 카드 모음 → 장세(md.mode)에 맞는 순서로 번호 매김
  const LV=live?`<div class="ts" style="margin-bottom:6px;color:#58a6ff">⏱ 장중 ${live.as_of} 가격 · 거래는 마감 환산</div>`:'';
  // 박스 돌파 (2026-10-06 rank2.py: 10일 +5.9/+6.8/+6.5% 세 기간 고르게) · 뚫기 직전은 보조
  const boxchip=x=>chip(x,'#f0883e',` <span style="color:#f85149">${sg(x.change_pct)}%</span> <span class="ts">손절 ${x.line.toLocaleString()} · ${x.family}</span>${x.is_b?' <b style="color:#e3b341;font-size:11px">⭐종베도 OK</b>':''}${emaTag(x)}${isHot(x)?' <b style="color:#ff7b72;font-size:11px">🔥과열 섹터</b>':''}`);
  C.box=['#f0883e','📦 박스 돌파 → 5~10일 스윙',
    '20일 동안 눌려 있던 고점을 <b>종가로</b> 뚫음 · 섹터에 돈 몰린 날 · 200일선 위 · 거래 2배↑ · <b>손절 = 뚫은 고점 아래로 마감</b>',
    LV+(all.state==='하락'?'<div style="color:#f85149;font-size:12.5px;margin-bottom:4px">하락장 — 보기만</div>':'')
    +((d.box_break||[]).map(boxchip).join('')||'<span class="ts">없음</span>')
    +`<div class="ts" style="margin:8px 0 4px">뚫기 직전 — 고점 -3% 안까지 붙여 마감 (보조)</div>`
    +((d.box_near||[]).map(x=>chip(x,'#9e6a03',` <span class="ts">고점 ${x.line.toLocaleString()} (${sg(x.line_pct)}%)</span>`)).join('')||'<span class="ts">없음</span>')
    +'<div class="ts" style="margin-top:4px">같은 섹터에서 여러 개 나오면 한두 개만 — 섹터가 꺾이면 같이 꺾임</div>'];
  C.lead=['#e3b341','⭐ 주도 섹터의 힘 있는 양봉 → 종베',
    '돈 몰린 섹터가 20일 1~3위 · 거래 평소 1.5~6배 · 고가 근처 마감 · <b>섹터당 2개(과열 섹터 1개)까지</b> · <b>다음 날 분할 매도</b>',
    LV+((d.best_lead||[]).map(bchip).join('')||'<span class="ts">없음</span>')+anyRetail+hotNote];
  C.swing=['#e3b341','⭐ 올라오는 섹터의 힘 있는 양봉 → 5~10일 스윙',
    '돈 몰린 섹터가 20일 4~8위 (아직 주도 전 · 올라오는 중) · <b>5~10일 보유</b> ',
    LV+((d.best_swing||[]).map(bchip).join('')||'<span class="ts">없음</span>')+`<div class="ts" style="margin-top:4px"><a href="#" onclick="switchTab('jongbe');return false" style="color:#58a6ff">후보 전체 보기 →</a></div>`];
  // 과매도 줍기 (2026-10-07 dipbuy.py·dipstock.py): 직전 20일 +10%↑ 섹터가 오늘 평균 -2%↓ → 대형·덜 빠진 주도주 종가 매수 5~10일
  const dips=live?(live.secs||[]):(d.dip||[]);
  C.dip=['#58a6ff','📉 과매도 줍기 → 5~10일 (오른 섹터가 하루 크게 빠진 날)',
    '직전 20일 +10%↑ 섹터가 오늘 평균 -2%↓ · <b>대형(하루 500억↑)·섹터보다 덜 빠진 종목(⭐)</b>이 가장 좋았음 · <b>종가에 절반 비중</b> · 손절 = 오늘 저가 아래 마감 · 하락장 전환 날은 실패',
    (all.state==='하락'?'<div style="color:#f85149;font-size:12.5px;margin-bottom:4px">하락장 — 줍지 않기</div>':'')
    +'<div id="db-dip">'+(live?`<div class="ts" style="margin-bottom:6px;color:#58a6ff">⏱ 장중 ${live.as_of} 가격</div>`:'')
    +(dips.map(s=>`<div style="margin-bottom:6px"><b style="color:#e6edf3">${s.family}</b> <span style="color:#58a6ff">${sg(s.chg)}%</span> <span class="ts">(20일 ${s.rank?s.rank+'위 · ':''}+${s.s20}%) ${s.note||''}</span><br>${s.items.map(x=>chip(x,x.best?'#e3b341':'#1f6feb',`${x.best?' <b style="color:#e3b341;font-size:11px">⭐</b>':''} <span class="ts">${sg(x.change_pct)}%${x.low?' · 손절 '+x.low.toLocaleString():''}</span>`)).join('')||'<span class="ts">고를 종목 없음</span>'}</div>`).join('')||`<span class="ts">${live?'지금은 -2% 넘게 빠진 오른 섹터 없음':'해당 없음'}</span>`)+'</div>'];
  // 순환: 20일 4위↓ 섹터에 오늘 돈 (2026-10-07 — 검증 약함: B 9위↓ 이김 62~72%)
  const rots=live?(live.rot||[]):(d.rotation||[]);
  C.rot=['#bc8cff','🔄 새로 돈이 들어온 섹터 → 작게',
    '20일 순위 9위↓ 섹터가 오늘 등락 중간 +1%↑ · 그 섹터의 +3%↑ 양봉(20일선 위) · <b>비중 작게</b> · 다음 날도 돈이 붙으면 "올라오는 섹터" 종베 자리',
    (live?`<div class="ts" style="margin-bottom:6px;color:#bc8cff">⏱ 장중 ${live.as_of} 가격</div>`:'')
    +(rots.map(s=>`<div style="margin-bottom:6px"><b style="color:#e6edf3">${s.family}</b> <span style="color:#f85149">${sg(s.chg)}%</span> <span class="ts">(20일 ${s.rank}위)</span><br>${s.items.map(x=>chip(x,'#6e40c9',` <span class="ts">${sg(x.change_pct)}%</span>`)).join('')||'<span class="ts">고를 종목 없음</span>'}</div>`).join('')||'<span class="ts">없음</span>')];
  // EMA 모임 돌파 (2026-10-07 ema_squeeze.py · 사용자 원칙)
  C.ema=['#56d4dd','📏 EMA(5·10·20) 모임 돌파 → 5~20일',
    '단기 EMA 셋이 4% 안으로 모여 있다가 세 선 위·10일 고점 돌파(+3%↑·거래 1.5배↑) · <b>섹터 돈 겹치면(⭐) 20일 +6%</b> · <b>📈EMA60 정배열</b>이면 5일 2~3배 · 손절 = 돌파 봉 저가 아래 마감 · 5~10일',
    ((d.ema_break||[]).map(x=>chip(x,x.money?'#e3b341':'#56d4dd',` <span style="color:#f85149">${sg(x.change_pct)}%</span> <span class="ts">거래 ${x.tv_x}배 · 전날 간격 ${x.ema_gap}%${x.family?' · '+x.family:''}</span>${x.money?' <b style="color:#e3b341;font-size:11px">⭐섹터 돈</b>':''}${x.up60?' <b style="color:#3fb950;font-size:11px" title="종가가 EMA60 위 & EMA20>EMA60">📈정배열</b>':''}${x.avwap_below?' <b style="color:#f0883e;font-size:11px" title="기준봉 이후 평균 단가 '+x.avwap.toLocaleString()+' 아래">⚠기준봉VWAP 아래</b>':''}`)).join('')||'<span class="ts">오늘 돌파 없음</span>')
    +`<div class="ts" style="margin:8px 0 4px">내일 후보 — EMA 3% 안으로 모여서 10일 고점 4% 안 · 60일선 위 · 오늘 조용 (뚫는 날 거래·섹터 확인)</div>`
    +((d.ema_wait||[]).map(x=>chip(x,x.money?'#e3b341':'#30363d',` <span class="ts">고점 ${x.line.toLocaleString()}까지 ${x.to_high_pct}% · 간격 ${x.ema_now}%${x.family?' · '+x.family:''}</span>${x.up60?' <b style="color:#3fb950;font-size:11px">📈</b>':''}${x.avwap_below?' <b style="color:#f0883e;font-size:11px" title="기준봉 이후 평균 단가 '+x.avwap.toLocaleString()+' 아래">⚠기준봉VWAP 아래</b>':''}`)).join('')||'<span class="ts">없음</span>')];
  C.doji=['#bc8cff','🕯 추세 도지 → 5일 안쪽',
    '상승 추세 종목의 장대양봉 다음 날 도지 · 이격 20%↓ · 5일 +3.7% (10일 넘기면 효과 없음)',((d.trend_doji||[]).map(x=>chip(x,'#bc8cff',` <span class="ts">어제 ${sg(x.big_pct)}% · 이격 ${x.gap20_pct}%</span>`)).join('')||'<span class="ts">없음</span>')
    +`<div class="ts" style="margin:8px 0 4px">내일 도지면 그 자리 (오늘 장대양봉)</div>`+((d.trend_big||[]).map(x=>chip(x,'#6e40c9',` <span class="ts">${sg(x.change_pct)}%</span>`)).join('')||'<span class="ts">없음</span>')];
  C.rest2=['#3fb950','🛌 장대양봉 이틀 쉼 + 종가 지킴 → 5~10일',
    '뜨는 섹터 · 장대양봉 종가 아래로 끝나면 정리 · AI 랠리 5일 +3.4% · 10일 +4.9%',
    ((d.rest2||[]).map(x=>chip(x,isHot(x)?'#ff7b72':'#3fb950',` <span class="ts">손절 ${x.big_close.toLocaleString()} · 이격 ${x.gap20_pct}%</span>${isHot(x)?' <b style="color:#ff7b72;font-size:11px">🔥과열 섹터·짧게</b>':''}`)).join('')||'<span class="ts">없음</span>')];
  C.turn=['#58a6ff','🔄 바닥 돌려세움 → 20일 (상승장 전용)',
    '빠진 뒤 바닥 횡보 → 양봉 3연속 · 20일선 회복 · 손절 = 바닥 박스 하단 · AI 랠리 AI 종목 20일 +11.3%',
    (all.state==='하락'?'<div style="color:#f85149;font-size:12.5px;margin-bottom:4px">하락장에선 이 자리도 마이너스였음 — 오늘은 보기만</div>':'')
    +(more(d.turn3||[],10,x=>chip(x,x.ai?'#3fb950':'#30363d',`${x.ai?' <b style="color:#3fb950;font-size:11px">AI</b>':''} <span class="ts">고점 ${x.off120_pct}% · 손절 ${x.box_low.toLocaleString()}</span>`))||'<span class="ts">없음</span>')
    +((d.turn2||[]).length?`<div class="ts" style="margin:6px 0 4px">2연속 — 내일도 양봉이면 3연속</div>`+(d.turn2||[]).map(x=>chip(x,'#30363d','')).join(''):'')];
  const ORDER={과매도:['dip','box','ema','swing','lead','rot','doji','rest2','turn'], 과열:['swing','box','ema','rot','lead','dip','doji','rest2','turn'],
               주도:['lead','box','ema','swing','dip','rot','doji','rest2','turn'], 순환:['swing','rot','ema','box','lead','dip','doji','rest2','turn']};
  // 종목이 있는 카드만 위에 3개, 나머지는 접어 둠 · 오늘 없는 자리는 이름만
  const CNT={lead:(d.best_lead||[]).length, swing:(d.best_swing||[]).length, box:(d.box_break||[]).length+(d.box_near||[]).length,
    dip:dips.reduce((a,s)=>a+s.items.length,0), rot:rots.reduce((a,s)=>a+s.items.length,0), ema:(d.ema_break||[]).length+(d.ema_wait||[]).length,
    doji:(d.trend_doji||[]).length+(d.trend_big||[]).length, rest2:(d.rest2||[]).length, turn:(d.turn3||[]).length+(d.turn2||[]).length};
  const ord=(ORDER[md&&md.mode]||['box','ema','lead','swing','dip','rot','doji','rest2','turn']);
  const has=ord.filter(k=>CNT[k]>0), none=ord.filter(k=>!CNT[k]);
  has.slice(0,3).forEach((k,i)=>{ const c=C[k]; rank.push(rcard(String(i+1),c[0],c[1],c[2],c[3],CNT[k]>8)); });
  const rest=has.slice(3);
  if(rest.length||none.length){
    rank.push(`<details style="margin:4px 0 6px"><summary class="ts" style="cursor:pointer;font-size:13px">${rest.length?`다른 자리 ${rest.length}개 더 보기 (${rest.map(k=>C[k][1].split('→')[0].trim()).join(' · ')})`:'다른 자리 없음'}${none.length?` &nbsp;·&nbsp; 오늘 없음: ${none.map(k=>C[k][1].split('→')[0].replace(/^[^가-힣A-Za-z]+/,'').trim()).join(', ')}`:''}</summary><div style="margin-top:8px">`
      +rest.map((k,i)=>{ const c=C[k]; return rcard(String(i+4),c[0],c[1],c[2],c[3],CNT[k]>8); }).join('')+'</div></details>');
  }
  ref.push(card('👀 내일 후보 — 뜨는 섹터에서 고점 근처 쉬는 중',(d.next.map(x=>chip(x,'#1f6feb',` <span class="ts">고점 ${x.off_hi20_pct}%</span>`)).join('')||'<span class="ts">없음</span>')+'<div class="ts" style="margin-top:4px">내일 거래 붙은 양봉으로 고점 넘으면 종베 자리</div>'));
  const wc={'⚠ 이탈':'#f85149','✅ 선 위 마감':'#3fb950','🚀 수렴 위로 돌파':'#3fb950'};
  ref.push(card(`📋 관심 종목 — 선에 닿은 것 (${d.watch.length})`,d.watch.map(w=>`<div style="display:flex;justify-content:space-between;gap:8px;font-size:13px;padding:3px 0;border-bottom:1px solid #21262d;cursor:pointer" onclick="openChartModal('${w.code}','${w.name}','')"><span><b style="color:${wc[w.tag]||'#e6edf3'}">${w.tag}</b> ${w.name}</span><span class="ts">${w.close.toLocaleString()} / 선 ${w.level.toLocaleString()} (${sg(w.gap_pct)}%)${w.box_days?`<br><span style="color:#58a6ff">${w.box_days}일 수렴 · 폭 ${w.box_width}% · 손절 ${w.box_low.toLocaleString()} (${w.stop_pct}%)</span>`:''}</span></div>`).join('')||'<span class="ts">없음</span>'));
  const vr=d.volume||{};
  ref.push(card('🔥 대량거래 관심종목',[['🎯 진입 신호',vr.signal,'#e3b341'],['🚀 꼬리 돌파',vr.tail_break,'#3fb950'],['🆕 신규(최근 터짐)',vr.new,'#58a6ff']].map(([t,l,c])=>`<div style="margin-bottom:4px"><span class="ts">${t}</span><br>${(l||[]).map(x=>chip(x,c,x.days!=null?` <span class="ts">${x.days}일 전</span>`:'')).join('')||'<span class="ts">없음</span>'}</div>`).join('')));
  ref.push(card('📌 데이터로 확인된 내 원칙',`<ol style="margin:0;padding-left:18px;font-size:13px;line-height:1.7">
    <li><b>하락장은 쉰다</b> — 특히 들고 가기 금지</li>
    <li><b>빠지는 종목 줍지 않기</b> — 20일선 아래·고점 -8%↓에서 사지 않기</li>
    <li><b>종베는 섹터에 돈 들어온 날의 거래 붙은 양봉</b> — 혼자 튄 종목 X</li>
    <li>B로 산 건 <b>분할 매도</b> (다음 날 +2%↓ 전량, ↑면 30%씩), 쉬는 봉은 <b>3~5일</b> 손절선만</li>
    <li><b>추격 금지</b> — 이격 30%↑ · 윗꼬리 긴 날 · 거래 6배↑ 피하기</li></ol>`));
  document.getElementById('db-top').innerHTML=top.join('');
  document.getElementById('db-rank').innerHTML=rank.join('');
  document.getElementById('db-ref').innerHTML=ref.join('');
  // 내 계좌 카드는 뺐음 (2026-10-06 사용자: 첫 화면에 계좌 금액이 보이는 건 원치 않음 — 매매 일지 탭에서만)
}

// 최적 조건 B · 내 패턴 A · 내일 후보 (2026-10-06)
async function loadMyPattern(){
  const el=document.getElementById('mp-box');
  const r=await fetch(`${API}/screener/my-pattern`).then(x=>x.ok?x.json():null).catch(()=>null);
  if(!r||!r.trading_date){ el.innerHTML='<span class="ts">불러오지 못했습니다</span>'; return; }
  // ⚠️ 이격 20%↑ (2026-10-10): 3년 20일선 이격 +20~30% −0.8%p · +30%↑ −1.4%p, 내 종베 10/2~10/8 이격 20%↑ 9건 다음 날 +0.34% vs 미만 25건 +2.36%
  const chip=(x,c)=>`<span style="display:inline-block;margin:0 6px 6px 0;padding:5px 9px;border:1px solid ${c};border-radius:8px;cursor:pointer;font-size:12.5px" onclick="openChartModal('${x.code}','${x.name}','')"><b style="color:#e6edf3">${x.name}</b>${x.gap20_pct>=20?' <b style="color:#f0883e;font-size:11px" title="20일선보다 20%↑ 위 — 3년·내 기록 모두 약했던 자리">⚠️이격 20%↑</b>':''} <span style="color:${x.change_pct>=0?'#f85149':'#58a6ff'}">${x.change_pct>0?'+':''}${x.change_pct}%</span> <span class="ts">거래 ${x.tv_x}배 · 이격 ${x.gap20_pct}%${x.upper_pct!=null?' · 윗꼬리 '+x.upper_pct+'%':''}</span>${x.retail_only?' <b style="color:#f85149;font-size:11px" title="외인·기관 둘 다 순매도인데 오른 날 — 그 뒤 약했음">⚠개인만</b>':''}</span>`;
  const B=r.items.filter(x=>x.b), A=r.items.filter(x=>x.a&&!x.b), N=r.next.slice(0,20);
  const sd=Object.entries(r.sector_day||{}).map(([f,v])=>`${f} ${v.chg>0?'+':''}${v.chg}%·${v.tvx}배`).join(' · ');
  const sb=await fetch(`${API}/jongbe/scoreboard`).then(x=>x.ok?x.json():null).catch(()=>null);
  const G=(sb&&sb.groups)||{}, f=(k,lab)=>G[k]?`${lab} <b style="color:${G[k].close>0?'#f85149':G[k].close<0?'#58a6ff':'#8b949e'}">${G[k].close>0?'+':''}${G[k].close}%</b> <span class="ts">(이김 ${G[k].win}% · ${G[k].n}건)</span>`:'';
  const sbLine=Object.keys(G).length?`<div style="margin:0 0 8px;font-size:13px">📊 <b>최근 ${sb.days}거래일 다음 날 종가</b> (산 값 대비) — ${[f('me','내 종베'),f('A','사이트 A'),f('B','사이트 B')].filter(Boolean).join(' · ')}</div>`:'';
  el.innerHTML=sbLine+`<b style="font-size:15px;color:#e3b341">🎯 오늘 종베 — 돈 몰린 섹터의 힘 있는 양봉 · 내가 잘 먹던 자리</b> <span class="ts">${r.trading_date} 종가 기준 · 시장 ${r.market||'-'}</span>
   <div class="ts" style="margin:4px 0 8px">섹터 오늘(등락 중간·거래 중간): ${sd}</div>
   ${r.market==='하락'?'<div style="color:#f85149;margin-bottom:6px">하락장 — 쉬는 날</div>':''}
   <div style="margin-bottom:4px"><b style="color:#e3b341">⭐ 돈 몰린 섹터의 힘 있는 양봉</b> <span class="ts">${r.b_sectors.length?'섹터: '+r.b_sectors.join(', '):'오늘은 쉬는 날 (돈 몰린 섹터 없음)'}</span></div>
   <div>${B.map(x=>chip(x,'#9e6a03')).join('')||''}</div>
   <div style="margin:6px 0 4px"><b style="color:#3fb950">🎯 내가 잘 먹던 자리 (고점 근처 양봉)</b> <span class="ts">뜨는 섹터 1~3위 · 양봉 · 20일 고점 -8% 안 · 20일선 위 · 거래 1배↑</span></div>
   <div>${A.slice(0,30).map(x=>chip(x,'#238636')).join('')||'<span class="ts">없음</span>'}${A.length>30?`<span class="ts">외 ${A.length-30}개</span>`:''}</div>
   <div style="margin:6px 0 4px"><b style="color:#58a6ff">👀 내일 후보</b> <span class="ts">뜨는 섹터 · 20일선 위 · 고점 -5% 안에서 오늘 조용히 쉰 종목 — 내일 거래 붙은 양봉이면 A</span></div>
   <div>${N.map(x=>chip(x,'#1f6feb')).join('')||'<span class="ts">없음</span>'}</div>
   <div class="ts" style="margin-top:6px">⚠ 매매 기록에서 손실이 난 자리: 20일선 아래·20일 고점 -8%↓에서 산 것 평균 -1.43%, 거래 0.5배↓ 날 매수 -1.51%. ⚠️이격 20%↑ = 20일선보다 20% 넘게 위 (3년 20일 뒤 −0.8~−1.4%p · 내 종베도 약했음).</div>`;
}
async function loadJongbe(){
  loadMyPattern();
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
    :`<b style="color:#f85149">시장 ${st} · 종베 쉬기</b>`;
  document.getElementById('jb-date').textContent=`· ${d.trading_date} 장 마감 기준`;
  const stc={'과열':'#f85149','주의':'#d29922'};
  document.getElementById('jb-fams').innerHTML=d.families.map(f=>{
    const isHot=d.hot.includes(f.family);
    return `<span style="padding:6px 10px;border:1px solid ${isHot?'#e3b341':'#30363d'};border-radius:8px;font-size:12.5px">
      <b style="color:${isHot?'#e6edf3':'#8b949e'}">${f.rank}. ${f.family}</b> <span class="ts">20일 ${f.ret20_pct>=0?'+':''}${f.ret20_pct}%</span>
      · <span style="color:${f.money?'#3fb950':'#8b949e'}" title="섹터 종목들의 '오늘 거래대금 ÷ 자기 평소(20일 평균)' 중간값. 1배 이상 = 섹터 종목 절반 이상이 평소보다 거래가 많음 (대형주 몇 개에 안 끌리게 합계 대신 중간값)">종목 거래 중간 ${f.tv_med.toFixed(2)}배${f.money?' 💰':''}</span>
      ${f.status?` · <b style="color:${stc[f.status]}">${f.status}</b>`:''}</span>`;}).join('');
  renderJongbe();
  try{ const saved=localStorage.getItem('jb-q'); if(saved&&!document.getElementById('jb-q').value){document.getElementById('jb-q').value=saved; jbCheck();} }catch(e){}
  try{ const sw=localStorage.getItem('sw-q'); if(sw&&!document.getElementById('sw-q').value){document.getElementById('sw-q').value=sw; swCheck();} }catch(e){}
  loadJongbePerf();
  if(_vrData) renderLimitUp(); else loadVolumeRecords();
  loadValueRecords();
}
let _vrcData=null;
async function loadValueRecords(){
  if(!_vrcData){ try{ _vrcData=await fetch(`${API}/screener/value-records`).then(r=>r.ok?r.json():null); }catch(e){} }
  renderValueRecords();
}
function renderValueRecords(){
  const el=document.getElementById('vrc-body'); if(!el) return;
  if(!_vrcData){ el.textContent='로딩 중…'; return; }
  const min=parseFloat(document.getElementById('jb-mincap').value)*1e8||0;
  const nf=document.getElementById('jb-noflag').checked, nc=document.getElementById('jb-nocred').checked;
  const xs=_vrcData.items.filter(x=>(!min||!x.market_cap||x.market_cap>=min)&&noFlag(x,nf,nc));
  document.getElementById('vrc-info').textContent=`${_vrcData.trading_date} · ${xs.length}개`;
  el.innerHTML=xs.length?xs.map(x=>`<span onclick="openChartModal('${x.code}','${x.name}','')" style="cursor:pointer;border:1px solid ${x.since_days>=365?'#e3b341':'#30363d'};border-radius:8px;padding:6px 10px;font-size:12.5px;line-height:1.5">
      <b style="color:#e6edf3">${x.name}</b>${flagTag(x)}${x.limit_up?' <b style="color:#f85149;font-size:11px">상한가</b>':''}<br>
      <span style="color:${x.since_days>=365?'#e3b341':'#c9d1d9'}">${x.label} 거래대금</span><br>
      <span class="ts">${cdWon(x.value)}${x.tv_x?` (평소 ${x.tv_x}배)`:''} · <span style="color:${x.change_pct>=0?'#f85149':'#58a6ff'}">${x.change_pct>=0?'+':''}${x.change_pct}%</span>${x.families.length?' · '+x.families[0]:''}</span></span>`).join('')
    :'<span class="ts">오늘은 6개월 넘게 만의 최고 거래대금 종목이 없습니다</span>';
}
// 시총 기준(억 원) 미만은 숨긴다. 시총을 모르는 종목(0)은 그대로 보여 준다.
const _jbOpen={};
function renderJongbe(){
  const d=_jbData; if(!d) return;
  if(_lbDate!==d.trading_date){ _lbDate=d.trading_date; lbLoad(d.trading_date).then(renderJongbe); }
  const min=parseFloat(document.getElementById('jb-mincap').value)*1e8||0;
  renderValueRecords();
  const nf=document.getElementById('jb-noflag').checked, nc=document.getElementById('jb-nocred').checked;
  const okCap=x=>(!min||!x.market_cap||x.market_cap>=min)&&noFlag(x,nf,nc);
  const safe=document.getElementById('jb-safe').checked, showB=document.getElementById('jb-showb').checked;
  const okSafe=x=>!safe||((x.gap20_pct==null||x.gap20_pct<20)&&x.change_pct<12);
  const pool=d.items.filter(x=>okCap(x)&&okSafe(x)), lim=d.limit_up.filter(okCap);
  const nA=pool.filter(x=>x.grade==='A').length, nB=pool.length-nA;
  const items=pool.filter(x=>showB||x.grade==='A');
  document.getElementById('jb-count').textContent=`A ${nA}개 · B ${nB}개 (전체 후보 ${d.items.length}개)`;
  const body=document.getElementById('jb-body');
  if(!items.length){ body.innerHTML=`<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">${nB&&!showB?`오늘은 A등급이 없습니다. <a href="#" onclick="document.getElementById('jb-showb').checked=true;renderJongbe();return false" style="color:#58a6ff">B등급 ${nB}개 보기</a>`:'오늘은 조건에 맞는 종목이 없습니다'}</td></tr>`; }
  else body.innerHTML=items.map(x=>`<tr style="cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','')">
    <td><b>${x.name}</b> <span style="color:#8b949e;font-size:11px">${x.code}</span>${x.earn_up?' <span style="color:#3fb950;font-size:11px;border:1px solid #238636;border-radius:8px;padding:0 5px">📈 실적</span>':''}${x.leader?' <span style="color:#e3b341;font-size:11px">👑 대장</span>':''}${flagTag(x)}${x.record_today?' <span style="color:#f85149;font-size:11px" title="오늘 몇 년 만의 최대 거래대금">🔔 거래대금 신기록</span>':''}${x.vr_stage&&x.vr_stage!=='무너짐'&&!x.record_today?` <span style="font-size:11px;color:${x.vr_signal?'#e3b341':'#8b949e'}" title="대량거래 관심종목 단계 (스윙 관점)">🔥 ${x.vr_signal?'진입 신호':x.vr_stage}</span>`:''}${x.market_cap?`<br><span class="ts">시총 ${cdWon(x.market_cap)}</span>`:''}${(d.ai_picks||[]).includes(x.code)?' <b style="color:#bc8cff;font-size:11px" title="장 마감 기준 규칙으로 고른 3개(점수·윗꼬리 순). 매일 기록해 사용자 선택과 비교">🤖 Claude 선택</b>':''}${lbBtns(x,'종베')}</td>
    <td data-label="등급"><b style="color:${x.grade==='A'?'#3fb950':'#c9d1d9'}">${x.grade}</b>${x.pos60_pct!=null?` <span class="ts" title="60일 종가 고점 대비 ${x.pos60_pct}% — 3년 확인상 돌파형·반등형 다음 날 성과는 같았음(+0.5~0.7%)">${x.pos60_pct>=0?(x.under_wick?'돌파형 (전 고점 윗꼬리 아래)':'돌파형'):x.pos60_pct>=-5?'고점 근처':'반등형'}</span>`:''}<br><span class="ts">${(()=>{ const tv=Math.max(...d.families.filter(f=>x.families.includes(f.family)).map(f=>f.tv_med),0); return x.grade==='A'?`섹터 종목 거래 중간 ${tv.toFixed(2)}배`:`섹터 종목 거래 중간 ${tv.toFixed(2)}배<br>(1배↑면 A)`; })()}</span></td>
    <td data-label="그날 봉">${x.kind==='밑꼬리 도지'?`<b style="color:#e3b341;font-size:12px">🕯 밑꼬리 도지</b> <span style="color:${x.change_pct>=0?'#f85149':'#58a6ff'}">${x.change_pct>=0?'+':''}${x.change_pct}%</span><br><span class="ts">밑꼬리 ${x.low_wick_pct}% · 전날 +${x.prev_chg}% 거래 ${x.prev_tv_x}배</span>`:`<span style="color:#f85149">+${x.change_pct}%</span> · 거래 ${x.tv_x}배<br><span class="ts" style="color:${x.upper_pct<=30?'#3fb950':'#8b949e'}">윗꼬리 ${x.upper_pct}%</span> · <span class="ts">${cdWon(x.value)}</span>`}</td>
    <td data-label="섹터" style="font-size:12px">${x.families.join(', ')}</td>
    <td data-label="종가" style="text-align:right">${x.close.toLocaleString()}원${gapTag(x.gap20_pct)}</td>
  </tr>`).join('');
  const merged={};
  for(const x of (d.swing||[]).filter(okCap)){
    const t=x.state==='막 넘음'?(x.held?'🚀 꼬리 돌파':'🚀 돌파'):'돌파 대기';
    merged[x.code]={...x, tags:[t], loud:x.loud, box:x};
  }
  for(const x of (d.prebuy||[]).filter(okCap)){
    if(merged[x.code]){ merged[x.code].tags.push(...x.tags); merged[x.code].stop_price=x.stop_price; merged[x.code].off_high_pct=x.off_high_pct; }
    else merged[x.code]={...x, tags:[...x.tags]};
  }
  const isBrk=x=>x.tags.some(t=>t.startsWith('🚀'));
  const ch=Object.values(merged).sort((a,b)=>(isBrk(b)-isBrk(a))||(b.tags.length-a.tags.length)||((b.market_cap||0)-(a.market_cap||0)));
  const cnt=t=>ch.filter(x=>x.tags.includes(t)).length;
  document.getElementById('jb-ch-info').textContent=`${ch.length}개 · 🚀 돌파 ${cnt('🚀 돌파')} · 돌파 대기 ${cnt('돌파 대기')} · 저가 지킴 ${cnt('저가 지킴')} · 눌림 ${cnt('눌림')} · 버팀 ${cnt('버팀')}`;
  const tagCol={'🚀 돌파':'#3fb950','🚀 꼬리 돌파':'#3fb950','돌파 대기':'#c9d1d9','저가 지킴':'#3fb950','눌림':'#58a6ff','버팀':'#e3b341'};
  const rowHtml=x=>`<tr style="cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','')">
    <td><b>${x.name}</b> <span style="color:#8b949e;font-size:11px">${x.code}</span>${flagTag(x)}${x.earn_up?' <span style="color:#3fb950;font-size:11px;border:1px solid #238636;border-radius:8px;padding:0 5px">📈 실적</span>':''}${x.market_cap?`<br><span class="ts">시총 ${cdWon(x.market_cap)}</span>`:''}${lbBtns(x,'스윙·선취매')}</td>
    <td data-label="근거">${x.tags.map(t=>`<b style="color:${tagCol[t]||'#c9d1d9'}">${t}</b>`).join(' · ')}${x.loud?' <span class="ts" style="color:#d29922" title="거래 2배 넘게 터지며 돌파 (긴 박스에선 약하지 않음 +5.4%p)">📢 거래 폭발</span>':''}
      <br><span class="ts">${x.box?`박스 상단 ${x.box.box_top.toLocaleString()}원(${x.box.box_date.slice(5).replace('-','/')} 고점) 대비 ${x.box.pos_pct>=0?'+':''}${x.box.pos_pct}%`:`20일 고점 ${x.off_high_pct}%`}${x.stop_price?` · 손절선 ${x.stop_price.toLocaleString()}원`:''}</span></td>
    <td data-label="오늘"><span style="color:${x.change_pct>=0?'#f85149':'#58a6ff'}">${x.change_pct>=0?'+':''}${x.change_pct}%</span> · 거래 ${x.tv_x}배</td>
    <td data-label="섹터" style="font-size:12px">${x.families.join(', ')}</td>
    <td data-label="종가" style="text-align:right">${x.close.toLocaleString()}원${gapTag(x.gap20_pct)}</td>
  </tr>`;
  const brk=ch.filter(x=>x.tags.some(t=>t.startsWith('🚀')||t==='돌파 대기')), pre=ch.filter(x=>!brk.includes(x));
  const nr=(d.near||[]).filter(x=>okCap(x)&&!merged[x.code]).map(x=>({...x, tags:[`🎯 꼬리까지 ${x.pos_pct}%`], box:x,
    families:x.families.map((f,i)=>i===0&&x.hot?'🔥 '+f:f)}));
  const grp=(title,sub,arr,key)=>{
    const open=_jbOpen[key], shown=open?arr:arr.slice(0,8);
    return `<tr><td colspan="5" style="background:#0d1117;padding:10px 4px 6px;border:none"><b style="color:#e6edf3">${title}</b> <span class="ts">${arr.length}개 · ${sub}</span></td></tr>`
      +(arr.length?shown.map(rowHtml).join(''):'<tr><td colspan="5" class="ts" style="text-align:center;padding:10px">오늘은 없습니다</td></tr>')
      +(arr.length>8?`<tr><td colspan="5" style="text-align:center;border:none"><a href="#" style="color:#58a6ff;font-size:12.5px" onclick="_jbOpen['${key}']=!_jbOpen['${key}'];renderJongbe();return false">${open?'접기':`${arr.length-8}개 더 보기`}</a></td></tr>`:'');
  };
  document.getElementById('jb-charts').innerHTML=grp('🚀 돌파형','120일 박스 상단을 처음 넘음 · 또는 -3% 안까지 붙음',brk,'b')+grp('🎯 돌파 임박 (가온전선형)','종가 고점은 넘고 옛 꼬리 끝 아래서 횡보 · 꼬리 끝 위로 종가 마감하는 날이 매수 자리 · 🔥 = 뜨는 섹터',nr,'n')+grp('🌱 선취매형','터지기 전 조용한 눌림·저가 지킴·버팀',pre,'p');
  const mv=d.movers||[];
  document.getElementById('jb-movers').innerHTML=mv.length?mv.map(m=>`<span onclick="jbMover('${m.family}')" style="cursor:pointer;padding:7px 11px;border:1px solid ${m.why.length>=2?'#3fb950':'#30363d'};border-radius:8px;font-size:12.5px">
      <b style="color:#e6edf3">${m.family}</b> <span class="ts">${m.rank}위</span><br><span class="ts" style="color:#c9d1d9">${m.why.join(' · ')}</span></span>`).join('')
    :'<span class="ts">지금 상위 3 밖에서 움직이기 시작한 섹터는 없습니다</span>';
  document.getElementById('jb-limit').innerHTML=lim.length?`상한가 (체결 어려움 주의): ${lim.map(x=>`<b style="color:#e6edf3;cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','')">${x.name}</b>${x.record_today?' <span style="color:#f85149;font-size:11px">🔔 신기록</span>':''}`).join(' · ')}`:'';
}
async function jbMover(fam){
  const el=document.getElementById('jb-mover-detail');
  el.innerHTML='<span class="ts">불러오는 중…</span>';
  const d=await fetch(`${API}/sectors/rotation`).then(r=>r.ok?r.json():null).catch(()=>null);
  const f=d&&(d.families||d.items||[]).find(x=>x.family===fam);
  if(!f){ el.innerHTML=`<span class="ts">섹터 수급 탭 순환매 모니터에서 ${fam}을 보세요</span>`; return; }
  const ls=(f.leaders||[]);
  el.innerHTML=`<div style="border:1px solid #30363d;border-radius:8px;padding:9px 12px;font-size:12.5px"><b style="color:#e6edf3">${fam}</b> <span class="ts">20일 ${f.ret20_pct>=0?'+':''}${f.ret20_pct}% · 5일 ${f.ret5_pct>=0?'+':''}${f.ret5_pct}% · 오늘 거래 평소 ${f.tv1_x}배</span><br>`
    +(ls.length?'오늘 돈 붙은 종목: '+ls.map(x=>`<b style="cursor:pointer;color:#e6edf3" onclick="openChartModal('${x.code}','${x.name}','')">${x.name}</b> <span style="color:${x.change_pct>=0?'#f85149':'#58a6ff'}">${x.change_pct>=0?'+':''}${x.change_pct}%</span>`).join(' · '):'<span class="ts">오늘 거래 2배 넘게 붙은 종목은 없습니다</span>')+'</div>';
}
// ── 차트 판단 기록 (👍/👎) ─────────────────────────────────────
let _lb={}, _lbDate='', _ssDate='';
function lbOwner(ask){ try{ let o=localStorage.getItem('jr-owner')||localStorage.getItem('lb-owner'); if(!o){ if(!ask) return '익명'; o=prompt('판단 기록에 쓸 이름 (매매 일지 이름과 같게)','junp')||'익명'; localStorage.setItem('lb-owner',o);} return o; }catch(e){ return '익명'; } }
async function lbLoad(date){
  try{ const d=await fetch(`${API}/labels?owner=${encodeURIComponent(lbOwner())}&day=${date}`).then(r=>r.json());
    d.day.forEach(x=>{ _lb[date+'|'+x.code]=x.label; });
    const st=document.getElementById('lb-stats'); if(st) st.textContent=`지금까지 👍 ${d.stats.up} · 👎 ${d.stats.down} · 놓친 종목 ${d.stats.missed}`;
    const ms=document.getElementById('lb-missed'); if(ms) ms.innerHTML=d.missed.length?'최근 놓친 종목: '+d.missed.map(x=>`${x.date.slice(5)} <b style="color:#e6edf3">${x.name}</b>${x.reason?` (${x.reason})`:''}`).join(' · '):'';
  }catch(e){}
}
function lbBtns(x,src,date){
  return '';   // 2026-10-05 👍/👎 뺌 ("내가 진입하는 거 적어 줄 테니까") — 기록 데이터와 API는 그대로
  date=date||_lbDate; const v=_lb[date+'|'+x.code]||0;
  const b=(val,ic)=>`<span onclick="event.stopPropagation();lbSet('${x.code}','${x.name}',${val},'${src}','${date}')" title="${val>0?'살 만함':'아님'}" style="cursor:pointer;margin-left:4px;font-size:13px;opacity:${v===val?1:0.35}">${ic}</span>`;
  return ` <span class="lb" data-k="${date}|${x.code}">${b(1,'👍')}${b(-1,'👎')}</span>`;
}
async function lbSet(code,name,val,src,date){
  const k=date+'|'+code; const cur=_lb[k]||0; const nv=cur===val?0:val;
  let reason=''; if(nv<0){ reason=prompt(`${name} 👎 이유 한 단어 (선택: 매물대·꼬리·거래 약함·자리 아님 …)`,'')||''; }
  const r=await fetch(`${API}/labels`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({owner:lbOwner(true),date,stock:code,label:nv,reason,source:src})}).catch(()=>null);
  if(!r||!r.ok){ alert('저장 실패'); return; }
  _lb[k]=nv;
  document.querySelectorAll(`.lb[data-k="${k}"]`).forEach(s=>{ const sp=s.querySelectorAll('span'); sp[0].style.opacity=nv===1?1:0.35; sp[1].style.opacity=nv===-1?1:0.35; });
  lbLoad(date);
}
async function lbMissed(){
  const name=document.getElementById('lb-mname').value.trim(), date=document.getElementById('lb-mdate').value, memo=document.getElementById('lb-mmemo').value.trim();
  if(!name||!date){ alert('종목과 날짜를 넣어 주세요'); return; }
  const r=await fetch(`${API}/labels`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({owner:lbOwner(true),date,stock:name,label:1,reason:memo,source:'놓친 종목',hindsight:true})}).catch(()=>null);
  if(!r||!r.ok){ const e=r?await r.json().catch(()=>({})):{}; alert(e.detail||'저장 실패'); return; }
  document.getElementById('lb-mname').value=''; document.getElementById('lb-mmemo').value='';
  lbLoad(_lbDate);
}
async function swCheck(){
  const q=document.getElementById('sw-q').value.trim();
  try{ localStorage.setItem('sw-q',q); }catch(e){}
  const el=document.getElementById('sw-out');
  if(!q){ el.innerHTML=''; return; }
  el.innerHTML='<span class="ts">불러오는 중… (종목당 1~2초)</span>';
  const d=await fetch(`${API}/stocks/short-watch?q=${encodeURIComponent(q)}`).then(r=>r.ok?r.json():null).catch(()=>null);
  if(!d){ el.textContent='불러오지 못했습니다'; return; }
  const n=v=>v==null?'-':Math.round(v).toLocaleString();
  const sg=v=>v==null?'-':(v>0?'+':'')+Math.round(v).toLocaleString();
  el.innerHTML=d.items.map(x=>{
    if(!x.found) return `<div class="ts">${x.query}: 못 찾음</div>`;
    const hot5=x.loan_5d_chg!=null&&x.loan_now&&x.loan_5d_chg/x.loan_now>=0.05;
    const shortUp=x.short_pct_5d!=null&&x.short_pct_prev20&&x.short_pct_5d>=x.short_pct_prev20*1.5;
    const rows=(x.days||[]).slice(-10).reverse().map(r=>`<tr><td>${r.date.slice(5)}</td><td style="text-align:right">${n(r.close)}</td><td style="text-align:right">${r.short_pct!=null?r.short_pct.toFixed(1)+'%':'-'}</td><td style="text-align:right">${n(r.loan_bal)}</td><td style="text-align:right;color:${(r.loan_new||0)>(r.loan_repay||0)?'#f85149':'#58a6ff'}">${sg((r.loan_new||0)-(r.loan_repay||0))}</td></tr>`).join('');
    return `<div style="padding:8px 0;border-top:1px solid #21262d">
      <b style="color:#e6edf3">${x.name}</b> <span class="ts">대차잔고 ${n(x.loan_now)}주${x.loan_pct_shares!=null?` (발행주식의 ${x.loan_pct_shares}%`+(x.loan_pct_float!=null?`, 유통주식의 <b style="color:${x.loan_pct_float>=10?'#f85149':'#c9d1d9'}">${x.loan_pct_float}%</b>`:'')+')':''}
      · 5일 ${sg(x.loan_5d_chg)}주 · 20일 ${sg(x.loan_20d_chg)}주 · 공매도 비중 최근 5일 ${x.short_pct_5d??'-'}% (그 전 ${x.short_pct_prev20??'-'}%)</span>
      ${hot5?' <b style="color:#f85149;font-size:12px">⚠ 대차잔고 5일 새 5%↑ 증가</b>':''}${shortUp?' <b style="color:#f85149;font-size:12px">⚠ 공매도 비중 증가</b>':''}
      <details class="why" style="margin:4px 0 0"><summary>최근 10일 보기</summary>
        <table style="font-size:12px"><thead><tr><th>날짜</th><th>종가</th><th>공매도 비중</th><th>대차잔고</th><th>대차 순증</th></tr></thead><tbody>${rows}</tbody></table></details></div>`;}).join('');
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
    +'<div style="margin-top:6px">'+d.items.slice(0,40).map(x=>`<span style="display:inline-block;margin:0 10px 4px 0">${x.date.slice(5)} ${x.ai_pick?'🤖':''}${x.name}(${x.grade}) <span style="color:${x.rule_pct>=0?'#f85149':'#58a6ff'}">${x.rule_pct>=0?'+':''}${x.rule_pct}%</span> <span class="ts">고가 +${x.high_pct}%</span></span>`).join('')+'</div>';
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
  jrBusy('일지 불러오는 중… (몇 초 걸립니다)');
  const r=await fetch(`${API}/journal`,{headers:jrH()}).catch(()=>null);
  jrBusy('');
  if(!r||!r.ok){ if(r&&(r.status===401||r.status===429)){ try{localStorage.removeItem('jr-pin');}catch(e){} } document.getElementById('jr-login-msg').textContent=r?'다시 입력해 주세요':'불러오지 못했습니다'; jrShowLogin(); return; }
  _jr=await r.json();
  document.getElementById('jr-login').style.display='none'; document.getElementById('jr-main').style.display='block';
  document.getElementById('jr-who').textContent=`${a.o}의 매매 일지`;
  document.getElementById('jr-asof').textContent=_jr.as_of?`· 시세 ${_jr.as_of} 기준`:'';
  if(!document.getElementById('jr-date').value) document.getElementById('jr-date').value=_jr.as_of||'';
  jrRender(); jrSizeRender();
}
function jrBusy(t){   // 로그인·불러오기 중인지 보이게 (2026-10-06 "로딩일 때 됐는지 안 됐는지 알 수가 없다")
  const b=document.getElementById('jr-open'), m=document.getElementById('jr-login-msg');
  if(b){ b.disabled=!!t; b.textContent=t?'⏳ 여는 중…':'열기'; b.style.opacity=t?'0.6':''; }
  if(t){ m.innerHTML=`<span style="color:#58a6ff">⏳ ${t}</span>`; document.getElementById('jr-login').style.display='block'; document.getElementById('jr-main').style.display='none'; }
}
function jrShowLogin(){ document.getElementById('jr-login').style.display='block'; document.getElementById('jr-main').style.display='none'; }
async function jrLogin(create){
  const o=document.getElementById('jr-owner').value.trim(), p=document.getElementById('jr-pin').value;
  const msg=document.getElementById('jr-login-msg');
  if(!o||p.length<4){ msg.textContent='이름과 4자 이상 비밀번호를 넣어 주세요'; return; }
  jrBusy('비밀번호 확인 중…');
  const r=await fetch(`${API}/journal/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({owner:o,pin:p,create:!!create})}).catch(()=>null);
  jrBusy('');
  if(r&&r.status===404){
    msg.innerHTML=`처음 쓰는 이름입니다. 이 비밀번호로 <b style="color:#3fb950;cursor:pointer;text-decoration:underline" onclick="jrLogin(true)">새로 만들기</b> (잊으면 되찾을 수 없으니 기억해 두세요)`;
    return;
  }
  if(!r||!r.ok){ const e=r?await r.json().catch(()=>({})):{}; msg.innerHTML=`<span style="color:#f85149">❌ ${e.detail||(r?'비밀번호가 맞지 않습니다':'서버에 연결하지 못했습니다')}</span>`; return; }
  try{ localStorage.setItem('jr-owner',o); localStorage.setItem('jr-pin',p); }catch(e){}
  document.getElementById('jr-pin').value=''; msg.textContent='';
  loadJournal();
}
function jrLogout(){ try{ localStorage.removeItem('jr-pin'); }catch(e){} _jr=null; loadJournal(); }
// 오늘 신호 몇 주 살지 (2026-10-10 "수량은 매매 일지에서만") — 수량 = 계좌 × 거래당 위험 ÷ (매수가 − 스탑로스)
// 거래당 위험: 기본 0.5% · 수량 절반 표시 0.25% · 🔥 주도주 0.10%. 가격은 지금 목록 가격(장중이면 실시간).
async function jrSizeRender(){
  const el=document.getElementById('jr-size'); if(!el||!_jr) return;
  const cap=+(_jr.cfg.capital||0);
  const head=`<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px"><b style="color:#e6edf3">🧮 오늘 신호 수량</b>
    <span class="ts">계좌 금액</span><input id="jr-cap" type="number" inputmode="numeric" value="${cap||''}" placeholder="예: 100000000" style="width:140px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:6px">
    <button class="btn btn-sm" onclick="jrCapSave()">저장</button><span class="ts">거래당 위험: 기본 0.5% · 수량 절반 0.25% · 🔥 주도주 0.10%</span></div>`;
  if(!cap){ el.innerHTML=head+'<div class="ts">계좌 금액을 넣으면 오늘 매수 신호마다 몇 주인지 계산합니다.</div>'; return; }
  const d=await fetch(`${API}/workspace/list`).then(r=>r.ok?r.json():null).catch(()=>null);
  const L=((d&&d.candidates)||[]).filter(x=>(x.lane||'entry')==='entry'&&x.close&&x.risk);
  if(!L.length){ el.innerHTML=head+'<div class="ts">오늘은 매수 신호가 없습니다.</div>'; return; }
  const row=x=>{ const half=(x.tags||[]).some(t=>t.includes('수량 절반')); const rp=x.lead?0.001:half?0.0025:0.005;
    const stop=x.close*(1-x.risk/100), per=x.close-stop, q=per>0?Math.floor(cap*rp/per):0;
    return `<tr><td>${x.lead?'🔥 ':''}<b>${x.name}</b></td><td style="text-align:right">${Math.round(x.close).toLocaleString()}</td><td style="text-align:right">${Math.round(stop).toLocaleString()} <span class="ts">(-${x.risk}%)</span></td><td style="text-align:right">${(rp*100).toFixed(2).replace(/0$/,'')}%</td><td style="text-align:right"><b>${q.toLocaleString()}주</b></td><td style="text-align:right">${Math.round(q*x.close).toLocaleString()}원</td></tr>`; };
  el.innerHTML=head+`<table class="pb-table"><thead><tr><th>종목</th><th style="text-align:right">가격</th><th style="text-align:right">스탑로스</th><th style="text-align:right">위험</th><th style="text-align:right">수량</th><th style="text-align:right">금액</th></tr></thead><tbody>${L.map(row).join('')}</tbody></table>
    <div class="ts" style="margin-top:4px">${d.live?d.live+' 실시간 가격':'종가'} 기준 · 손절에 걸리면 계좌의 위험 % 만큼만 잃는 수량 · 금액이 계좌보다 크면 칸 수를 줄이기</div>`;
}
async function jrCapSave(){
  const v=Math.max(0,Math.round(+document.getElementById('jr-cap').value||0));
  const r=await fetch(`${API}/journal/config`,{method:'POST',headers:jrH(),body:JSON.stringify({capital:v})}).then(r=>r.ok?r.json():null).catch(()=>null);
  if(r) _jr.cfg=r; jrSizeRender();
}
function jrRender(){
  const s=_jr.summary, all=s.all||{count:0};
  const card=(t,v,sub)=>`<div style="border:1px solid #30363d;border-radius:10px;padding:10px 14px;min-width:110px"><div class="ts">${t}</div><div style="font-size:17px;font-weight:600;color:#e6edf3">${v}</div>${sub?`<div class="ts">${sub}</div>`:''}</div>`;
  document.getElementById('jr-cards').innerHTML=!all.count?'<div class="ts">아직 청산된 매매가 없습니다. 위 "＋ 기록 넣기"로 체결 내역을 붙여넣으세요.</div>':
    card('청산',`${all.count}건`,'')+card('이긴 비율',`${all.win_pct}%`,'')+card('평균 수익률',jrPct(all.avg_pct),`이익 ${all.avg_win_pct??'-'}% · 손실 ${all.avg_loss_pct??'-'}%`)
    +card('손익 합계',jrWon(all.pnl),`투입 대비 ${all.ret_on_cost_pct}%`)+card('최고 / 최악',`${jrPct(all.best_pct)} / ${jrPct(all.worst_pct)}`,'')
    +(s.pool_cmp?card('내 선택 vs 같은 날 후보',`${jrPct(s.pool_cmp.my_avg_pct)} / ${jrPct(s.pool_cmp.pool_avg_pct)}`,`${s.pool_cmp.count}건 중 후보 평균 이김 ${s.pool_cmp.beat_pct}%`):'');
  document.getElementById('jr-insights').innerHTML='<b style="color:#e6edf3">🔎 숫자로 보이는 것</b><br>'+(_jr.insights.length?_jr.insights.map(x=>'· '+x).join('<br>'):'<span class="ts">아직 없음</span>');
  const groups={by_rule:'규칙별',by_kind:'유형별',by_state:'산 날 상태별',by_user_tag:'내 근거별',by_family:'섹터별',by_day:'날짜별 실현손익',by_month:'월별 실현손익'};
  document.getElementById('jr-groupbtns').innerHTML=Object.entries(groups).map(([k,v])=>`<button class="btn btn-sm" style="${k===_jrGroup?'border-color:#58a6ff;color:#58a6ff':''}" onclick="_jrGroup='${k}';jrRender()">${v}</button>`).join('');
  document.getElementById('jr-gname').textContent=groups[_jrGroup];
  const g=Object.entries(s[_jrGroup]||{}).sort((a,b)=>(_jrGroup==='by_month'||_jrGroup==='by_day')?b[0].localeCompare(a[0]):b[1].count-a[1].count);
  document.getElementById('jr-group').innerHTML=g.length?g.map(([k,v])=>`<tr><td><b>${k}</b></td><td data-label="건수">${v.count}</td><td data-label="이긴 비율">${v.win_pct}%</td><td data-label="평균">${jrPct(v.avg_pct)}</td>
    <td data-label="평균 이익 / 손실"><span class="ts">${v.avg_win_pct??'-'}% / ${v.avg_loss_pct??'-'}%</span></td><td data-label="손익" style="text-align:right">${jrWon(v.pnl)}</td></tr>`).join('')
    :'<tr><td colspan="6" class="ts" style="text-align:center;padding:14px">없음</td></tr>';
  jrRenderHolding(); jrWsLoad();
  const kf=document.getElementById('jr-kindf'), kinds=[...new Set(_jr.trips.map(t=>t.kind))];
  const cur=kf.value; kf.innerHTML='<option value="">전체</option>'+kinds.map(k=>`<option ${k===cur?'selected':''}>${k}</option>`).join('');
  jrRenderTrips();
  document.getElementById('jr-excl').value=(_jr.cfg.exclude||[]).map(c=>{ const e=_jr.executions.find(e=>e.code===c); return e?e.name:c; }).join(', ');
  const tagOpt=(sel)=>'<option value="">-</option>'+_jr.user_tags.map(t=>`<option ${t===sel?'selected':''}>${t}</option>`).join('');
  const kindOpt=(sel)=>'<option value="">자동</option>'+_jr.kinds.map(t=>`<option ${t===sel?'selected':''}>${t}</option>`).join('');
  const sel='background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;padding:2px 4px;font-size:12px';
  document.getElementById('jr-execs').innerHTML=_jr.executions.slice(0,400).map(e=>`<tr><td>${e.date.slice(5)} <span class="ts">${e.seq}</span></td>
    <td data-label="구분" style="color:${e.side==='매수'?'#f85149':'#58a6ff'}">${e.side}</td><td data-label="종목">${e.name}</td>
    <td data-label="수량·단가">${e.qty}주 · ${Math.round(e.price).toLocaleString()}${e.price_warn?` <span style="color:#d29922" title="${e.price_warn}">⚠️ ${e.price_warn}</span>`:''}</td>
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
    const pl=t.pool?`<br><span class="ts">같은 날 선취매 후보 ${t.pool.n}개를 같은 기간 들었다면 평균 ${t.pool.avg_pct>0?'+':''}${t.pool.avg_pct}%${t.pool.in_pool?' · <b style="color:#3fb950">이 종목도 후보에 있었음</b>':''}</span>`:'';
    return `<tr style="${t.excluded?'opacity:.45':''}"><td><b style="cursor:pointer" onclick="openChartModal('${t.code}','${t.name}','')">${t.name}</b>${t.user_tags.length?` <span class="ts">${t.user_tags.join(', ')}</span>`:''}${t.excluded?' <span class="ts">(분석 제외)</span>':''}</td>
      <td data-label="유형">${t.kind}</td><td data-label="산 날 → 판 날">${t.buy_date?t.buy_date.slice(5):'?'} → ${t.sell_date.slice(5)}${t.days!=null?` <span class="ts">${t.days}일</span>`:''}</td>
      <td data-label="매수 → 매도">${Math.round(t.buy_px).toLocaleString()} → ${Math.round(t.sell_px).toLocaleString()} <span class="ts">${t.qty}주</span></td>
      <td data-label="수익률">${jrPct(t.pct)}<br>${jrWon(t.pnl)}</td>
      <td data-label="규칙 · R" style="font-size:11.5px">${t.rules?(t.rules.broke.length?t.rules.broke.map(b=>`<div style="color:#f0883e">${b}</div>`).join(''):'<div>✅ 지킴</div>')+`<span class="ts">R ${t.rules.r==null?'-':(t.rules.r>0?'+':'')+t.rules.r} · 손절선 ${t.rules.stop.toLocaleString()}</span>`:'<span class="ts">-</span>'}</td><td data-label="산 날 상태" style="font-size:11.5px;max-width:340px">${tags}${det}${pl}</td></tr>`;}).join('')
    :'<tr><td colspan="7" class="ts" style="text-align:center;padding:14px">없음</td></tr>';
}
async function jrImport(preview){
  const text=document.getElementById('jr-text').value, msg=document.getElementById('jr-import-msg');
  if(!text.trim()){ msg.textContent='붙여넣은 내용이 없습니다'; return; }
  const r=await fetch(`${API}/journal/import`,{method:'POST',headers:jrH(),body:JSON.stringify({text,date:document.getElementById('jr-date').value,preview})}).catch(()=>null);
  if(!r||!r.ok){ msg.textContent='실패'; return; }
  const d=await r.json();
  const sh=d.shift?`<div style="color:#58a6ff;margin-top:4px">증권사 내역 날짜가 결제일이라 체결일로 ${d.shift}거래일 앞당겨 넣었습니다(체결가가 그날 시세 범위와 맞는 쪽).</div>`:'';
  const bad=(d.bad.length?`<div style="color:#d29922;margin-top:4px">못 읽은 줄 ${d.bad.length}개: ${d.bad.slice(0,5).map(x=>x.replace(/</g,'&lt;')).join(' / ')}</div>`:'')+sh;
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
// 보유 물량: 종목별 비중(예수금 포함)·정렬 (2026-10-06)
let _jrHSort='eval';
function jrRenderHolding(){
  const el=document.getElementById('jr-holding'), h=(_jr.holding||[]).map(x=>{
    const cost=x.qty*x.price, val=x.close?x.qty*x.close:cost;
    return {...x,cost,val,pl:val-cost};
  });
  if(!h.length){ el.innerHTML=''; return; }
  // 현금은 뺌 (2026-10-07 사용자: 신용 때문에 비중이 어차피 안 맞음) — 비중은 주식 평가금액 합 기준
  const tv=h.reduce((a,x)=>a+x.val,0), tot=tv, tc=h.reduce((a,x)=>a+x.cost,0);
  const key={rate:x=>-(x.eval_pct??-1e9),cost:x=>-x.cost,eval:x=>-x.val,pl:x=>-x.pl,name:null}[_jrHSort];
  h.sort(key?(a,b)=>key(a)-key(b):(a,b)=>a.name.localeCompare(b.name,'ko'));
  const w=v=>tot?(v/tot*100).toFixed(1)+'%':'-';
  const bar=v=>`<div style="height:4px;background:#21262d;border-radius:2px;margin-top:3px"><div style="height:4px;width:${tot?Math.min(100,v/tot*100):0}%;background:#58a6ff;border-radius:2px"></div></div>`;
  // 비중 도넛 (평가금액 큰 순 10개 + 기타)
  const pal=['#1f6feb','#58a6ff','#a5d6ff','#f778ba','#ffa7d1','#bc8cff','#8957e5','#3fb950','#56d4dd','#d29922'];
  const byv=[...h].sort((a,b)=>b.val-a.val), top=byv.slice(0,10), rest=byv.slice(10).reduce((a,x)=>a+x.val,0);
  const segs=top.map((x,i)=>({n:x.name,v:x.val,c:pal[i]})).concat(rest>0?[{n:'기타 '+(byv.length-10)+'종목',v:rest,c:'#6e7681'}]:[]);
  let acc=0; const grad=segs.map(g=>{ const a=acc/tot*360; acc+=g.v; return `${g.c} ${a}deg ${acc/tot*360}deg`; }).join(',');
  const donut=tot?`<div style="display:flex;flex-wrap:wrap;align-items:center;gap:18px;margin:4px 0 14px">
    <div style="position:relative;width:170px;height:170px;border-radius:50%;background:conic-gradient(${grad});flex:none">
      <div style="position:absolute;inset:34px;border-radius:50%;background:#0d1117;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center">
        <span class="ts">주식 평가</span><b style="color:#e6edf3;font-size:15px">${Math.round(tot/10000).toLocaleString()}만</b></div></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:4px 14px;flex:1;min-width:220px;font-size:12.5px">
      ${segs.map(g=>`<div style="display:flex;align-items:center;gap:6px"><span style="width:10px;height:10px;border-radius:50%;background:${g.c};flex:none"></span><span style="color:#c9d1d9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${g.n}</span><b style="margin-left:auto;color:#e6edf3">${(g.v/tot*100).toFixed(1)}%</b></div>`).join('')}
    </div></div>`:'';
  const opts=[['eval','평가금액 순'],['cost','매입금액 순'],['rate','수익률 순'],['pl','평가손익 순'],['name','가나다 순']];
  el.innerHTML=`<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:6px 0 8px">
    <span style="font-size:13px;color:#e6edf3">📦 보유 ${h.length}종목 (일지에 산 기록이 있는 물량)</span>
    <select onchange="_jrHSort=this.value;jrRenderHolding()" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;border-radius:6px">${opts.map(([k,v])=>`<option value="${k}" ${k===_jrHSort?'selected':''}>${v}</option>`).join('')}</select></div>${donut}
  <table class="pb-table" style="margin-bottom:16px"><thead><tr><th>종목</th><th>수량 · 평단</th><th style="text-align:right">매입금액</th><th style="text-align:right">평가금액</th><th style="text-align:right">평가손익</th><th style="text-align:right">수익률</th><th style="min-width:90px">비중</th></tr></thead><tbody>`+
  h.map(x=>`<tr style="cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','')"><td><b>${x.name}</b><br><span class="ts">${x.buy_date.slice(5)}${x.buys>1?` 외 ${x.buys-1}번`:''}</span></td>
    <td data-label="수량 · 평단">${x.qty.toLocaleString()}주<br><span class="ts">@${Math.round(x.price).toLocaleString()}</span></td>
    <td data-label="매입금액" style="text-align:right">${Math.round(x.cost).toLocaleString()}</td>
    <td data-label="평가금액" style="text-align:right">${x.close?Math.round(x.val).toLocaleString():'<span class="ts">시세 없음</span>'}</td>
    <td data-label="평가손익" style="text-align:right">${x.close?jrWon(x.pl):'-'}</td>
    <td data-label="수익률" style="text-align:right">${jrPct(x.eval_pct)}</td>
    <td data-label="비중">${w(x.val)}${bar(x.val)}</td></tr>`).join('')+
  `<tr style="border-top:1px solid #30363d"><td><b>합계</b></td><td></td><td data-label="매입금액" style="text-align:right">${Math.round(tc).toLocaleString()}</td><td data-label="평가금액" style="text-align:right"><b>${Math.round(tot).toLocaleString()}</b></td><td data-label="평가손익" style="text-align:right">${jrWon(tv-tc)}</td><td data-label="수익률" style="text-align:right">${jrPct(tc?Math.round((tv/tc-1)*10000)/100:null)}</td><td>100%</td></tr></tbody></table>
  <div class="ts" style="margin:-10px 0 14px">평가금액은 ${_jr.as_of||''} 시세 기준 · 비중은 주식 평가금액 합 기준(현금·신용 제외)</div>`;
}
async function jrSaveExcl(){
  const v=document.getElementById('jr-excl').value.split(',').map(x=>x.trim()).filter(Boolean);
  const codes=v.map(x=>{ const e=_jr.executions.find(e=>e.name===x||e.code===x); return e?e.code:x; });
  await fetch(`${API}/journal/config`,{method:'POST',headers:jrH(),body:JSON.stringify({exclude:codes})}).catch(()=>null);
  loadJournal();
}

// ── 강한 섹터 캘린더 ─────────────────────────────────────────
let _cal=null,_calMonth=null;
async function loadSectorCal(){
  if(!_cal){ try{ _cal=await fetch(`${API}/sectors/calendar`).then(r=>r.ok?r.json():null); }catch(e){} }
  if(!_cal||!_cal.days.length){ document.getElementById('cal-grid').innerHTML='<span class="ts">불러오지 못했습니다</span>'; return; }
  const first=!_calMonth;
  if(!_calMonth) _calMonth=_cal.days[_cal.days.length-1].date.slice(0,7);
  renderCal();
  if(first) calPick(_cal.days[_cal.days.length-1].date, true);
}
function calMove(k){
  const ms=[...new Set(_cal.days.map(d=>d.date.slice(0,7)))];
  const i=ms.indexOf(_calMonth)+k; if(i<0||i>=ms.length) return;
  _calMonth=ms[i]; document.getElementById('cal-detail').innerHTML=''; renderCal();
}
function calHeat(v){ // 등락이 클수록 진한 빨강
  const k=Math.max(0,Math.min(1,(v-2)/10));
  return `rgba(${Math.round(150+90*k)},${Math.round(45-20*k)},${Math.round(50-20*k)},${(0.35+0.55*k).toFixed(2)})`;
}
function renderCal(){
  const [y,m]=_calMonth.split('-').map(Number);
  document.getElementById('cal-month').textContent=`${y}년 ${m}월`;
  const byDate=Object.fromEntries(_cal.days.filter(d=>d.date.startsWith(_calMonth)).map(d=>[d.date,d]));
  const last=_cal.days[_cal.days.length-1].date;
  const pc=v=>`<span style="color:${v>=0?'#f85149':'#58a6ff'}">${v>=0?'+':''}${v}%</span>`;
  const hol=_cal.holidays||{};
  let html=['일','월','화','수','목','금','토'].map((x,i)=>`<div class="cal-h ${i===0?'sun':i===6?'sat':''}">${x}</div>`).join('');
  const nd=new Date(y,m,0).getDate(), first=new Date(y,m-1,1).getDay();
  for(let k=0;k<first;k++) html+='<div></div>';
  const tk=new Date(), todayKey=`${tk.getFullYear()}-${String(tk.getMonth()+1).padStart(2,'0')}-${String(tk.getDate()).padStart(2,'0')}`;
  for(let dd=1;dd<=nd;dd++){
    const wd=new Date(y,m-1,dd).getDay();
    const key=`${y}-${String(m).padStart(2,'0')}-${String(dd).padStart(2,'0')}`, d=byDate[key];
    const dcls=wd===0?'sun':wd===6?'sat':'';
    if(!d){
      const hn=hol[key], closed=hn||(wd>0&&wd<6&&key<=last);
      const cls=hn?'hol':(wd===0||wd===6)?'we':'off';
      html+=`<div class="cal-c ${cls}${key===todayKey?' today':''}" style="justify-content:flex-start;align-items:stretch"><div class="hd"><span class="dn ${hn?'sun':dcls}">${dd}</span></div>${hn?`<div class="hn">${hn}</div>`:closed&&cls==='off'?'<div class="hn" style="color:#8b949e">휴장</div>':''}</div>`;
      continue;
    }
    const t=d.themes;
    html+=`<div class="cal-c${key===todayKey?' today':''}" data-d="${key}" onclick="calPick('${key}')">
      <div class="hd"><span class="dn ${dcls}">${dd}</span><span class="mk">시장 ${pc(d.market_chg)}</span></div>
      ${t[0]?`<div class="top" style="background:${calHeat(t[0].chg)}" title="${t[0].name}"><span class="n">${t[0].name.split('(')[0]}</span><span class="v">+${t[0].chg}%</span></div>`:''}
      ${t.slice(1,3).map((x,i)=>`<div class="sub s${i+1}" title="${x.name}"><span class="n">${x.name.split('(')[0]}</span><span class="v">+${x.chg}%</span></div>`).join('')}
    </div>`;
  }
  document.getElementById('cal-grid').innerHTML=html;
}
function calPick(date, quiet){
  const d=_cal.days.find(x=>x.date===date); if(!d) return;
  document.querySelectorAll('.cal-c').forEach(c=>c.classList.toggle('on',c.dataset.d===date));
  const pc=v=>`<span style="color:${v>=0?'#f85149':'#58a6ff'}">${v>=0?'+':''}${v}%</span>`;
  const [y,m,dd]=date.split('-').map(Number), wd='일월화수목금토'[new Date(y,m-1,dd).getDay()];
  document.getElementById('cal-detail').innerHTML=`<div class="cal-det">
    <div class="ttl"><b style="color:#e6edf3;font-size:15px">${m}월 ${dd}일 (${wd})</b><span class="chip">시장 평균 ${pc(d.market_chg)}</span>
      ${d.families.map(f=>`<span class="chip">${f.name} ${pc(f.chg)}</span>`).join('')}</div>
    <div class="rows">${d.themes.map((t,i)=>`<div class="tc" onclick="openSectorModal(${t.id},'${t.name.replace(/'/g,'')}')">
      <div class="h"><span>${i+1}. ${t.name}</span>${pc(t.chg)}</div>
      <div class="ts" style="margin-top:2px">종목 중 ${t.up_pct}% 상승</div>
      <div class="l">${t.leaders.map(l=>`<span>${l.name} ${l.chg>=0?'+':''}${l.chg}%</span>`).join('')}</div></div>`).join('')}</div></div>`;
  if(!quiet) document.getElementById('cal-detail').scrollIntoView({behavior:'smooth',block:'nearest'});
}

async function loadRotation(){
  const body=document.getElementById('rot-body');
  try{
    const d=await fetch(`${API}/sectors/rotation`).then(r=>r.ok?r.json():null);
    if(!d||!d.items.length){body.innerHTML='<tr><td colspan="6" style="color:#8b949e;text-align:center;padding:16px">데이터 없음</td></tr>';return;}
    document.getElementById('rot-info').textContent=d.live?`· 오늘 ${d.live.as_of} 기준${d.live.projected?' (장중 · 거래대금은 마감까지 환산)':''}`:`· ${d.trading_date} 장 마감 기준`;
    const c=n=>n>0?'#f85149':n<0?'#58a6ff':'#8b949e';
    const sg=n=>(n>0?'+':'')+n;
    const badge={'과열':'<b style="color:#f85149;border:1px solid #f85149;border-radius:8px;padding:0 6px;font-size:11px">과열</b>','주의':'<b style="color:#d29922;border:1px solid #d29922;border-radius:8px;padding:0 6px;font-size:11px">주의</b>'};
    window._rotMem=null; loadRotMembers();
    body.innerHTML=d.items.map(t=>{
      const mv=t.rank_10ago-t.rank;
      return `<tr style="cursor:pointer" onclick="toggleRotMembers(this,'${t.family}')" title="눌러서 종목 보기">
      <td><b>${t.family}</b> ${badge[t.status]||''} <span class="ts">▸</span><br><span class="ts">${t.count}종목 · 눌러서 보기</span></td>
      <td><b style="color:${c(t.ret20_pct)}">${sg(t.ret20_pct)}%</b> <span class="ts">${t.rank}위</span>${mv?` <span style="font-size:11px;color:${mv>0?'#3fb950':'#8b949e'}">${mv>0?'▲':'▼'}${Math.abs(mv)}</span>`:''}<br><span class="ts">5일 ${sg(t.ret5_pct)}%</span></td>
      <td>${t.breadth_pct}% <span class="ts">(10일 전 ${t.breadth_10ago}%)</span><br><span class="ts" style="color:${t.stretch_pct>=20?'#f85149':t.stretch_pct>=10?'#d29922':'#8b949e'}">+20% 넘게 뜬 종목 ${t.stretch_pct}% (10일 전 ${t.stretch_10ago}%)</span></td>
      <td><b style="color:${t.tv5_x>=1.1?'#f85149':t.tv5_x<0.9?'#58a6ff':'#c9d1d9'}">${t.tv5_x.toFixed(2)}배</b> <span class="ts">최근 5일 · 5일 정점 ${t.tv5_peak5.toFixed(2)}</span><br><span class="ts">오늘 ${t.tv1_x.toFixed(2)}배</span></td>
      <td style="color:${c(t.chg_pct)}">${sg(t.chg_pct.toFixed(1))}%</td>
      <td style="font-size:12px">${t.leaders.map(l=>`<span style="cursor:pointer" onclick="event.stopPropagation();openChartModal('${l.code}','${l.name}','')">${l.name} <span style="color:${c(l.change_pct)}">${sg(l.change_pct)}%</span></span>`).join(' · ')||'<span class="ts">없음</span>'}</td>
    </tr>`}).join('');
  }catch(e){console.error(e);body.innerHTML='<tr><td colspan="6" style="color:#f85149;text-align:center;padding:16px">로딩 실패</td></tr>';}
}
// 섹터 소속 종목은 표가 뜰 때 한 번에 미리 받아 둔다 (누르면 바로 펼치게)
function loadRotMembers(){
  window._rotMemP=fetch(`${API}/sectors/rotation/members-all`).then(r=>r.ok?r.json():null).then(d=>{window._rotMem=d;return d;}).catch(()=>null);
  return window._rotMemP;
}
// 섹터를 누르면 소속 종목 펼치기 (2026-10-09 건의 #2)
async function toggleRotMembers(tr,fam){
  const nx=tr.nextElementSibling;
  if(nx&&nx.classList.contains('rot-mem')){nx.remove();return;}
  const row=document.createElement('tr'); row.className='rot-mem';
  row.innerHTML='<td colspan="6" style="background:#0d1117;padding:8px 10px"><span class="ts">불러오는 중…</span></td>';
  tr.after(row);
  let d=null;
  const all=window._rotMem||await (window._rotMemP||loadRotMembers());
  if(all&&all.families&&all.families[fam]) d={as_of:all.as_of,items:all.families[fam]};
  if(!d) d=await fetch(`${API}/sectors/rotation/members?family=${encodeURIComponent(fam)}`).then(r=>r.ok?r.json():null).catch(()=>null);
  const td=row.firstElementChild;
  if(!d||!d.items.length){td.innerHTML='<span class="ts">종목 없음</span>';return;}
  const c=n=>n>0?'#f85149':n<0?'#58a6ff':'#8b949e', sg=n=>(n>0?'+':'')+n;
  const line=x=>`<tr><td style="padding:3px 6px"><span style="cursor:pointer;text-decoration:underline dotted" onclick="openChartModal('${x.code}','${x.name}','')">${x.name}</span></td>
    <td style="color:${c(x.chg)};padding:3px 6px">${sg(x.chg)}%</td><td style="color:${c(x.ret20)};padding:3px 6px">${sg(x.ret20)}%</td>
    <td style="padding:3px 6px;color:${x.gap20>=20?'#f85149':'#c9d1d9'}">${sg(x.gap20)}%</td><td style="padding:3px 6px;${x.tv_x>=2?'font-weight:700':''}">${x.tv_x}배${x.tv_d1!=null?` <span class="ts" title="어제 거래대금 대비 — 1보다 크면 오늘 더 들어옴, 작으면 식는 중">· 어제의 ${x.tv_d1}배</span>`:''}</td><td class="ts" style="padding:3px 6px">${x.tv.toLocaleString()}억</td></tr>`;
  const head='<tr class="ts"><th style="text-align:left;padding:3px 6px">종목</th><th>오늘</th><th>20일</th><th>20일선 이격</th><th title="평소 = 직전 20거래일 평균 · 옆 숫자 = 어제 대비">거래 (평소 대비 · 어제 대비)</th><th>거래대금</th></tr>';
  const first=d.items.slice(0,30), rest=d.items.slice(30);
  td.innerHTML=`<div class="ts" style="margin-bottom:4px">${fam} ${d.items.length}종목 (하루 거래대금 10억↑) · ${d.as_of} 기준 · 오늘 등락 순 · 이름 누르면 차트</div>
    <table style="width:100%;font-size:12px">${head}${first.map(line).join('')}</table>`
    +(rest.length?`<button class="ts" style="margin-top:6px;background:none;border:1px solid #30363d;border-radius:6px;color:#8b949e;padding:3px 10px;cursor:pointer" onclick="this.previousElementSibling.insertAdjacentHTML('beforeend',window._rotRest);this.remove()">${rest.length}개 더 보기</button>`:'');
  window._rotRest=rest.map(line).join('');
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
    const rows=stocks.map(s=>`<tr style="cursor:pointer" onclick="closeSectorModal();openChartModal('${s.stock_code}','${s.stock_name}','')">
      <td><b>${s.stock_name}</b> <span class="ts">${s.stock_code}</span></td>
      <td style="color:${s.change_pct>0?'#f85149':s.change_pct<0?'#58a6ff':'#8b949e'}">${s.change_pct>=0?'+':''}${s.change_pct.toFixed(2)}%</td>
      <td>${Number(s.close_price).toLocaleString()}원</td>
      <td>${s.trading_value?cdWon(s.trading_value):'-'}</td>
      <td title="그날 거래량 / 유통주식수 (발행주식 × 유동비율)">${s.float_turnover_pct!=null?`<b style="color:${s.float_turnover_pct>=50?'#f85149':s.float_turnover_pct>=10?'#e3b341':'#c9d1d9'}">${s.float_turnover_pct}%</b> <span class="ts">유동 ${s.float_ratio}%</span>`:'<span class="ts">-</span>'}</td>
      <td>${fmtBil(s.foreign_net_buy)}</td><td>${fmtBil(s.inst_net_buy)}</td>
    </tr>`).join('');
    document.getElementById('sector-modal-body').innerHTML=`<div class="ts" style="margin-bottom:6px">유통 회전율 = 그날 거래량 ÷ 유통주식수(발행주식 × 유동비율, 네이버 기업정보). 100%면 유통 물량을 하루에 한 바퀴 돌린 것. 많이 돌린 순.</div><div style="overflow-x:auto"><table>
      <thead><tr><th>종목</th><th>등락</th><th>종가</th><th>거래대금</th><th>유통 회전율</th><th>외국인</th><th>기관</th></tr></thead>
      <tbody>${rows||'<tr><td colspan="7" style="color:#8b949e;text-align:center">데이터 없음</td></tr>'}</tbody>
    </table></div>`;
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
  loadBottomBox();
  loadSupportSetups();
  loadLargePullback();
  loadEmaSection();
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
function rsTag(x){   // 강도(RS) 숫자 (2026-10-10 차트 후보 카드)
  return x.rs!=null?` <span style="font-size:11px;color:${x.rs>=95?'#e8590c':x.rs>=70?'#c9d1d9':'#8b949e'}" title="강도: 거래대금 30억↑ 종목 중 3·6·9·12개월 수익률 순위 (99가 최고) · 기본 매수 70~95 · 주도주 95↑">강도 ${x.rs}${x.rs>=95?' 🔥':''}</span>`:'';
}
function flagTag(x){   // 투자주의·경고·위험, 단기과열, 관리종목, 신용불가
  const f=(x&&x.flags)||[]; if(!f.length) return '';
  const col=t=>t==='투자위험'||t==='투자경고'||t==='관리종목'?'#f85149':t==='신용불가'?'#d29922':'#e3b341';
  return ' '+f.map(t=>`<span style="font-size:10.5px;color:${col(t)};border:1px solid ${col(t)};border-radius:6px;padding:0 4px;white-space:nowrap" title="${t==='신용불가'?'신용 매수 불가 (증거금 100%) — 한국투자증권 기준이라 메리츠 등 다른 증권사와 다를 수 있음':'거래소 지정 — 모든 증권사 공통'}">${t==='신용불가'?'신용불가(한투)':t}</span>`).join(' ');
}
function noFlag(x, warnOff, credOff){ const f=x.flags||[]; return !(warnOff&&f.some(t=>t!=='신용불가')) && !(credOff&&f.includes('신용불가')); }
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
    .filter(it=>(!pat||it.patterns.some(p=>p.type===pat)) && cdMatch(it, terms) && noFlag(it, document.getElementById('cd-noflag').checked, document.getElementById('cd-nocred').checked))
    .sort((a,b)=>val(b)-val(a));
  document.getElementById('cd-info').textContent = d.trading_date ? `기준일: ${d.trading_date} · ${items.length}개${items.length!==d.items.length?' / 전체 '+d.items.length+'개':''}` : '';
  document.getElementById('cd-sum').textContent = `${items.length}개`;
  if(!items.length){
    body.innerHTML = '<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">조건에 맞는 종목이 없습니다</td></tr>';
    return;
  }
  const tagColor = {'불플래그':'#58a6ff','상승삼각형':'#bc8cff','기준봉 눌림':'#d29922','장대음봉도지':'#3fb950','VCP':'#f778ba'};
  body.innerHTML = items.map(it=>{
    const indHtml = `<span style="font-size:12.5px">${it.industry||'업종 정보 없음'}</span>`
      + (it.sector_name?`<br><span class="ts">${it.sector_name} · 20일 ${it.sector_ret20>=0?'+':''}${it.sector_ret20}%</span>`:'');
    const pats = it.patterns.map(p=>`<span style="display:inline-block;margin:0 4px 3px 0;padding:1px 7px;border-radius:10px;border:1px solid ${tagColor[p.type]};color:${tagColor[p.type]};font-size:11.5px">${p.type}${p.grade?'·'+p.grade:''}</span><br><span class="ts">${p.detail}</span>`).join('<br>');
    return `<tr style="cursor:pointer" onclick="openChartModal('${it.code}','${it.name}','')">
      <td><b>${it.name}</b> <span style="color:#8b949e;font-size:11px">${it.code}</span>${flagTag(it)}${it.earn_up?' <span style="color:#3fb950;font-size:11px;border:1px solid #238636;border-radius:8px;padding:0 5px" title="영업이익 +30%·매출 +10%, 120일 안 공시">📈 실적</span>':''}${it.market_cap?`<br><span class="ts">시총 ${cdWon(it.market_cap)}</span>`:''}</td>
      <td data-label="업종 · 테마">${indHtml}</td>
      <td data-label="모양" style="font-size:12px">${pats}</td>
      <td data-label="현재가" style="text-align:right">${it.close_price.toLocaleString()}원${gapTag(it.gap20_pct)}<br><span style="color:${it.change_pct>=0?'#f85149':'#3b82f6'};font-size:11px">${it.change_pct>=0?'+':''}${it.change_pct.toFixed(2)}%</span><br><span class="ts">거래대금 ${cdWon(it.trading_value||0)}${it.turnover_pct!=null?' · 회전율 '+it.turnover_pct.toFixed(1)+'%':''}</span></td>
      <td data-label="손절선" style="color:#f85149">${it.stop_price?it.stop_price.toLocaleString()+'원<br><span style="font-size:11px;color:'+({적정:'#3fb950',보통:'#c9d1d9',얕음:'#8b949e',깊음:'#8b949e'}[it.stop_zone])+'">-'+it.stop_dist_pct+'% · '+it.stop_zone+'</span>':'—'}</td>
    </tr>`;
  }).join('');
}

// ── 손절 짧은 자리 ────────────────────────────────────────────
async function loadSupportSetups(){
  const d=await fetch(`${API}/screener/support-setups`).then(r=>r.ok?r.json():null).catch(()=>null);
  const el=document.getElementById('ss-body'); if(!el) return;
  if(!d){ el.textContent='불러오지 못했습니다'; return; }
  _ssDate=d.trading_date; await lbLoad(d.trading_date);
  document.getElementById('ss-info').textContent=`${d.trading_date} · ${d.items.length}개${d.dropped_loss?` · 영업 적자 ${d.dropped_loss}개 뺌`:''}`;
  el.innerHTML=d.items.length?d.items.map(x=>`<span onclick="openChartModal('${x.code}','${x.name}','')" style="cursor:pointer;border:1px solid ${x.type.startsWith('추세선')?'#bc8cff':'#58a6ff'};border-radius:8px;padding:6px 10px;font-size:12.5px;line-height:1.55">
    <b style="color:#e6edf3">${x.name}</b>${flagTag(x)}${rsTag(x)} <span style="font-size:11px;color:${x.type.startsWith('추세선')?'#bc8cff':'#58a6ff'}">${x.type}</span><br>
    <span style="color:#58a6ff">손절 ${x.stop.toLocaleString()}원 (${x.stop_pct}%)</span> · <span style="color:#f85149">위 ${x.target.toLocaleString()}원 (+${x.target_pct}%)</span><br>
    ${lbBtns(x,'손절 짧은 자리',_ssDate)}<br><span class="ts">현재 ${x.close.toLocaleString()}원 · 거래 터질 때의 ${x.dry}배 · 터진 뒤 ${x.since_burst}일${x.families.length?' · '+x.families[0]:''}</span>
    ${x.fund?`<br><span style="font-size:11.5px;color:${x.fund.good?'#3fb950':x.fund.grow?'#c9d1d9':x.fund.loss?'#f85149':'#8b949e'}">${x.fund.good?'📈 실적 개선':x.fund.grow?'이익 증가':x.fund.loss?'⚠ 영업 적자':'이익 감소'} · ${x.fund.period} 영업익 ${x.fund.op_yoy!=null?(x.fund.op_yoy>0?'+':'')+x.fund.op_yoy+'%':'-'} · 매출 ${x.fund.rev_yoy!=null?(x.fund.rev_yoy>0?'+':'')+x.fund.rev_yoy+'%':'-'}${x.fund.margin!=null?' · 이익률 '+x.fund.margin+'%':''}</span>`:''}</span>`).join('')
    :'지금은 없습니다';
}

// ── 바닥 박스 감시 ────────────────────────────────────────────
// EMA 모임 돌파 · 후보 (2026-10-07) — my-pattern 결과에서
async function loadEmaSection(){
  const d=await fetch(`${API}/screener/my-pattern`).then(r=>r.ok?r.json():null).catch(()=>null);
  const b=document.getElementById('ema-brk'), w=document.getElementById('ema-wait'); if(!b) return;
  if(!d){ b.textContent='불러오지 못했습니다'; return; }
  const eb=d.ema_break||[], ew=d.ema_wait||[];
  document.getElementById('ema-info').textContent=`${d.trading_date} · 돌파 ${eb.length} · 후보 ${ew.length}`;
  const tag=x=>(x.money?' <b style="color:#e3b341;font-size:11px">⭐섹터 돈</b>':'')+(x.up60?' <b style="color:#3fb950;font-size:11px">📈정배열</b>':'')+(x.avwap_below?' <b style="color:#f0883e;font-size:11px">⚠기준봉VWAP 아래</b>':'');
  const card=(x,body)=>`<span onclick="openChartModal('${x.code}','${x.name}','')" style="cursor:pointer;border:1px solid ${x.up60?'#3fb950':'#30363d'};border-radius:8px;padding:6px 10px;font-size:12.5px;line-height:1.55"><b style="color:#e6edf3">${x.name}</b>${tag(x)}<br><span class="ts">${body}</span></span>`;
  b.innerHTML=eb.length?eb.map(x=>card(x,`<span style="color:#f85149">${x.change_pct>0?'+':''}${x.change_pct}%</span> · 거래 ${x.tv_x}배 · 전날 간격 ${x.ema_gap}%${x.family?' · '+x.family:''}`)).join(''):'오늘 돌파 없음';
  w.innerHTML=ew.length?ew.map(x=>card(x,`10일 고점 ${x.line.toLocaleString()}까지 ${x.to_high_pct}% · 간격 ${x.ema_now}%${x.family?' · '+x.family:''}`)).join(''):'없음';
}
// 대형주 눌림 박스 (2026-10-07)
async function loadLargePullback(){
  const d=await fetch(`${API}/screener/large-pullback`).then(r=>r.ok?r.json():null).catch(()=>null);
  const el=document.getElementById('lp-body'); if(!el) return;
  if(!d){ el.textContent='불러오지 못했습니다'; return; }
  document.getElementById('lp-info').textContent=`${d.trading_date} · ${d.items.length}개${d.market==='하락'?' · 🔴 하락장 — 보기만':''}`;
  el.innerHTML=d.items.length?d.items.map(x=>`<span onclick="openChartModal('${x.code}','${x.name}','')" style="cursor:pointer;border:1px solid #1f6feb;border-radius:8px;padding:6px 10px;font-size:12.5px;line-height:1.55">
    <b style="color:#e6edf3">${x.name}</b>${rsTag(x)} <span style="color:${x.change_pct>=0?'#f85149':'#58a6ff'}">${x.change_pct>0?'+':''}${x.change_pct}%</span><br>
    <span class="ts">고점 ${x.off_hi60_pct}% · 15일 박스 폭 ${x.box_pct}% · 거래 ${x.vol_ratio}배 · 하루 ${x.liq_eok.toLocaleString()}억${x.families.length?' · '+x.families[0]:''}</span><br>
    <span style="color:#58a6ff">손절 ${x.stop.toLocaleString()}원 (${x.stop_pct}%)</span></span>`).join(''):'지금은 없습니다';
}
async function loadBottomBox(){
  const d=await fetch(`${API}/screener/bottom-box`).then(r=>r.ok?r.json():null).catch(()=>null);
  const el=document.getElementById('bb-body'); if(!el) return;
  if(!d){ el.textContent='불러오지 못했습니다'; return; }
  document.getElementById('bb-info').textContent=`${d.trading_date} · ${d.items.length}개${d.burst.length?` · 오늘 터짐 ${d.burst.length}`:''}`;
  const chip=(x,b)=>`<span onclick="openChartModal('${x.code}','${x.name}','')" style="cursor:pointer;border:1px solid ${b?'#f85149':'#30363d'};border-radius:8px;padding:5px 9px;font-size:12px;line-height:1.5">
    <b style="color:#e6edf3">${x.name}</b>${b?` <b style="color:#f85149">🔔 +${x.change_pct}%</b>`:''}<br><span class="ts">박스 ${x.days}일째 · 폭 ${x.band_pct}% · 고점 ${x.dd_pct}% · 거래 ${x.dry_x}배${x.families.length?' · '+x.families[0]:''}</span></span>`;
  document.getElementById('bb-burst').innerHTML=d.burst.length?'<div class="ts" style="color:#f85149;margin-bottom:4px">🔔 오늘 박스에서 터짐</div><div style="display:flex;flex-wrap:wrap;gap:6px">'+d.burst.map(x=>chip(x,true)).join('')+'</div>':'';
  el.innerHTML=d.items.length?d.items.map(x=>chip(x,false)).join(''):'지금은 없습니다';
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
  const vmin = parseFloat(document.getElementById('vr-mincap').value)*1e8||0;
  const items = _vrData.items.filter(x=> (sel==='live' ? x.stage!=='무너짐' : (!sel || x.stage===sel)) && (!sigOnly || x.entry_signal) && (!vmin || !x.market_cap || x.market_cap>=vmin));
  const cnt = s=>_vrData.items.filter(x=>x.stage===s).length;
  const nsig = _vrData.items.filter(x=>x.entry_signal).length;
  document.getElementById('vr-sum').textContent = `${_vrData.items.filter(x=>x.stage!=='무너짐').length}개 · 🎯 진입 신호 ${nsig}`;
  document.getElementById('vr-info').textContent = `기준일 ${_vrData.trading_date} · 시장 ${_vrData.market_state||'-'} · 🎯 진입 신호 ${nsig} · 쉬는 중 ${cnt('숨고르기')} · 윗꼬리 뚫음 ${cnt('꼬리 돌파')} · 최근 터짐 ${cnt('신규')} · 오르는 중 ${cnt('진행 중')} · 위에서 팔림 ${cnt('설거지')} · 무너짐 ${cnt('무너짐')}`;
  if(!items.length){ body.innerHTML = '<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:20px">해당 종목이 없습니다</td></tr>'; return; }
  const SN = {'숨고르기':'😮‍💨 쉬는 중','꼬리 돌파':'🚀 윗꼬리 뚫음','신규':'🆕 최근 터짐','진행 중':'📈 오르는 중','설거지':'⚠ 위에서 팔림','무너짐':'무너짐'};
  const color = {'꼬리 돌파':'#3fb950','숨고르기':'#3fb950','신규':'#58a6ff','진행 중':'#d29922','설거지':'#f85149','무너짐':'#8b949e'};
  const sg = n=>(n>=0?'+':'')+n;
  body.innerHTML = items.map(x=>`<tr style="cursor:pointer" onclick="openChartModal('${x.code}','${x.name}','${x.event_date}')">
    <td>${x.entry_signal?'<b style="color:#e3b341">🎯 진입 신호</b><br>':''}<b>${x.name}</b> <span style="color:#8b949e;font-size:11px">${x.code}</span>${flagTag(x)}${x.earn_up?' <span style="color:#3fb950;font-size:11px;border:1px solid #238636;border-radius:8px;padding:0 5px">📈 실적</span>':''}${x.market_cap?`<br><span class="ts">시총 ${cdWon(x.market_cap)}</span>`:''}${(x.families||[]).length?`<br><span class="ts" style="color:#c9d1d9">${x.families.join(', ')}</span>`:''}</td>
    <td data-label="단계"><b style="color:${color[x.stage]}">${SN[x.stage]||x.stage}</b><br><span class="ts">마지막 대량거래 뒤 ${x.rest_days}일</span></td>
    <td data-label="신기록일">${x.event_date.slice(5)} <span style="color:#f85149">${sg(x.event_change_pct)}%</span>${x.event_kind==='윗꼬리'?` <span style="font-size:11px;color:#d29922" title="장중 고가까지 올랐다가 밀린 대량거래">윗꼬리(고가 ${sg(x.event_high_pct)}%)</span>`:''} <span style="font-size:11px;color:${x.days_since>40?'#d29922':'#8b949e'}">(${x.days_since}거래일 전)</span><br><span class="ts">${cdWon(x.event_value)} · 평소 ${x.event_x}배</span></td>
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

let _avwapNote='';
function clearChartCanvas(){   // 열 때 이전 종목 차트가 남아 보이던 것 지움 (2026-10-07)
  ['pb-candle-canvas','pb-volume-canvas'].forEach(id=>{ const cv=document.getElementById(id); if(cv){ const x=cv.getContext('2d'); x.setTransform(1,0,0,1,0,0); x.clearRect(0,0,cv.width,cv.height); } });
}
// ── 첫 화면 작업대: 종목 목록 → 신호 찍힌 차트 → 패널 (2026-10-09) ──
let _ws={tab:null,data:null,code:null,per:130,cache:{}};
try{ _ws.per=+localStorage.getItem('ws-per')||130; }catch(e){}
function wsPeriod(n){ _ws.per=n; try{ localStorage.setItem('ws-per',n); }catch(e){} wsDraw(); }
_ws.tf='1d';
const TF_NAME={'1d':'일봉','1w':'주봉','60m':'60분봉','30m':'30분봉','15m':'15분봉','5m':'5분봉','1m':'1분봉'};
async function tfCandles(code,tf){   // 분봉·주봉 (네이버, 60초 캐시는 서버)
  const r=await fetch(`${API}/stock/${code}/candles?tf=${tf}`).then(x=>x.ok?x.json():null).catch(()=>null);
  return r&&r.candles&&r.candles.length?r:null;
}
async function wsTf(tf){ _ws.tf=tf; wsDraw(); }
async function wsDraw(){
  document.querySelectorAll('#ws-tf button').forEach(b=>b.classList.toggle('on',b.dataset.tf===_ws.tf));
  document.getElementById('ws-per').style.display=(_ws.tf==='1d')?'flex':'none';
  document.querySelectorAll('#ws-per button').forEach(b=>b.classList.toggle('on',+b.dataset.n===_ws.per));
  const c=_ws.cache[_ws.code]; if(!c||!c.cd) return;
  if(_ws.tf!=='1d'){
    const code=_ws.code, tf=_ws.tf; document.getElementById('ws-note').textContent=`${TF_NAME[tf]} 불러오는 중…`;
    const cd=c[tf]||(c[tf]=await tfCandles(code,tf));
    if(_ws.code!==code||_ws.tf!==tf) return;
    if(!cd){ document.getElementById('ws-note').textContent=`${TF_NAME[tf]}을 못 받았습니다`; return; }
    renderLwChart('ws-chart',cd.candles,[],tf==='1w'?80:120);
    document.getElementById('ws-note').textContent=`${TF_NAME[tf]}${tf==='1w'?'':' · 최근 약 6거래일 (네이버)'} · EMA 5·10·20·60 · 신호는 일봉에서만 보여요`;
    return;
  }
  const g=renderLwChart('ws-chart',c.cd.candles,c.sg?c.sg.items:[],_ws.per);
  const a=c.sg&&c.sg.active;
  document.getElementById('ws-note').innerHTML=(a?`<b style="color:var(--blue)">▲ 진입 신호 ${a.date.slice(5).replace('-','/')} ${Math.round(a.entry).toLocaleString()} · ${a.days}일째 · ${a.gain>0?'+':''}${a.gain.toFixed(1)}% · 손절 ${Math.round(a.stop).toLocaleString()}${a.half?' · 절반 익절함':''}</b> · `:'')
    +`최근 ${_ws.per}거래일 · EMA 5·10·20·60`+(g!=null?` · EMA 5·10·20 간격 ${g.toFixed(1)}% ${g<=4?'(모임 ✓)':g>=7?'(벌어짐 ⚠)':''}`:'')+_avwapNote;
}
const WS_PAL=['#3b5bdb','#c2255c','#2b8a3e','#e8590c','#5f3dc4','#0b7285','#a61e4d','#5c940d','#d9480f','#364fc7'];
function wsAv(code,name){ let h=0; for(const ch of code) h=(h*31+ch.charCodeAt(0))%997; return `<div class="ws-av" style="background:${WS_PAL[h%WS_PAL.length]}">${(name||'?').slice(0,1)}</div>`; }
async function loadWorkspace(){
  const d=await fetch(`${API}/workspace/list`).then(r=>r.ok?r.json():null).catch(()=>null);
  if(!d){ document.getElementById('ws-items').innerHTML='<div class="ts" style="padding:10px">목록을 못 불러왔습니다</div>'; return; }
  _ws.data=d;
  if(!_ws.tab){ let t=null; try{ t=localStorage.getItem('ws-tab'); }catch(e){}
    _ws.tab=['entry','wait','track'].includes(t)?t:(['entry','wait'].find(k=>wsItems(k).length)||'track'); }
  document.getElementById('ws-asof').textContent = d.live ? `장중 ${d.live} 가격` : `${d.as_of} 정규장 종가`;
  renderWsList();
  if(!_ws.code){ const L=wsItems(_ws.tab); const f=L[0]||(d.candidates||[])[0]||(d.track||[])[0]; if(f) wsOpen(f.code,f.name); }
}
function wsItems(t){ const d=_ws.data||{}; return t==='track'?(d.track||[]):(d.candidates||[]).filter(x=>(x.lane||'entry')===t); }
const WS_LANE={entry:'종가에 진입 · 강도(RS) 높은 순 — 칸이 모자라면 위에서부터 · 5~8%는 수량 절반 · 사면 스탑로스(그날 저가 -1%) 예약 · 21일선 아래 종가면 다음 날 아침 정리 · ⬇ 급락 날 줍기(시험 중)는 손절 20일선 · 수량 절반',
  wait:'신호 전 · 돌파 나오면 그때 · ⏸ 손절폭 8%↑는 폭 좁은 날 기다리기 · 참고 = 다른 기준 신호', track:'내 매매 아님 · 최근 20일 사이트 신호(점수 6↑ · ⬇ 급락 날 줍기) + 🔥 주도주(60일)를 규칙대로 따라간 것 · ⚠ = 내일 아침 정리'};
function wsTab(t){ _ws.tab=t; try{ localStorage.setItem('ws-tab',t); }catch(e){} renderWsList(); }
function renderWsList(){
  document.querySelectorAll('.ws-tabs button').forEach(b=>{ const n=wsItems(b.dataset.t).length; b.classList.toggle('on',b.dataset.t===_ws.tab); b.innerHTML=`${{entry:'오늘 진입',wait:'대기',track:'신호 추적'}[b.dataset.t]} ${n}`; });
  const td=(_ws.data||{}).track_done||{};
  document.getElementById('ws-lane-note').textContent=(WS_LANE[_ws.tab]||'')+(_ws.tab==='track'&&(td.stop||td.exit)?` · 끝난 것: 스탑 ${td.stop||0} · 21선 ${td.exit||0}`:'');
  const L=wsItems(_ws.tab), el=document.getElementById('ws-items');
  if(!L.length){ el.innerHTML=`<div class="ts" style="padding:12px">${_ws.tab==='track'?'없음':'오늘은 없습니다'}</div>`; return; }
  const KIND={above:'선 위 마감 대기',near:'수렴 자리',hold:'지지선',watch:'봉 보기'};
  const row=x=>{
    let tg='';
    if(_ws.tab==='track') tg=(x.sell_tmr?'⚠ 내일 아침 정리 · ':'')+(x.dip?'⬇ 줍기 · ':'')+(x.lead?'🔥 주도주 · ':'')+`${x.date.slice(5).replace('-','/')} ${Math.round(x.entry).toLocaleString()} · 스탑 ${x.stop.toLocaleString()} · 21선 ${x.to21>0?'+':''}${x.to21}%`;
    else if(_ws.tab!=='watch') tg=(x.risk!=null?`손절 ${x.risk}% · `:'')+x.tags.filter(t=>t!=='종가 점수 6↑'||x.tags.length===1).join(' · ')+(x.family?` · ${x.family}`:'');   // 손절폭 = 종가에서 그날 저가 -1%까지
    else if(_ws.tab==='held') tg=(x.stop?`손절 ${Math.round(x.stop).toLocaleString()}${x.room!=null?` · ${x.room<0?'⛔ 이탈':x.room<=2?'⚠ '+x.room+'% 남음':x.room+'% 남음'}`:''}`:'손절선 없음')+(x.long?' · 장기':'');
    else tg=`${KIND[x.kind]||''}${x.level?' '+Math.round(x.level).toLocaleString():''}${x.note?' · '+x.note:''}`;
    const sub=_ws.tab==='held'&&x.gain!=null?`<div class="ws-tg" style="text-align:right">수익 ${x.gain>0?'+':''}${x.gain}%</div>`:'';
    return `<div class="ws-item${x.code===_ws.code?' on':''}" data-c="${x.code}" onclick="wsOpen('${x.code}','${x.name.replace(/'/g,'')}')">${wsAv(x.code,x.name)}
      <div class="ws-txt"><div class="ws-nm"><span class="n">${x.name}</span>${(x.lane==='entry'&&_ws.tab==='entry'&&!x.lead)?(()=>{const half=(x.tags||[]).some(t=>t.includes('수량 절반'));return `<span class="b" style="border-color:var(--blue);color:var(--blue)" title="${half?'수량 절반 (손절폭 5~8% · 과열 매수 · 반도체 특별 중 하나)':'정상 수량'}${x.score!=null?' · 종가 진입 점수 '+x.score+'/7':''}">${x.rr?'✅ ':''}매수${half?' · 절반':''}</span>`;})():''}${(x.lead&&x.lane==='entry'&&_ws.tab==='entry')?`<span class="b" style="border-color:#e8590c;color:#e8590c" title="강도 최상위 주도주 — 기본 신호와 별도로 소량 (거래당 위험 0.10%, 2종목까지)">🔥 주도 매수</span>`:''}</div><div class="ws-tg" title="${tg.replace(/"/g,'')}">${tg}</div></div>
      <div class="ws-px">${x.close?Math.round(x.close).toLocaleString():'-'}${_ws.tab==='track'?`<div style="color:${x.gain>0?'var(--up)':x.gain<0?'var(--down)':'var(--muted)'}" title="진입 뒤">${x.gain>0?'+':''}${x.gain}%</div>`:`<div style="color:${x.chg>0?'var(--up)':x.chg<0?'var(--down)':'var(--muted)'}">${x.chg>0?'+':''}${(x.chg||0).toFixed(2)}%</div>`}${sub}</div></div>`;
  };
  if(_ws.tab==='held'){ const a=L.filter(x=>!x.long), b=L.filter(x=>x.long);
    el.innerHTML=a.map(row).join('')+(b.length?`<div class="ws-sec">장기 보유</div>`+b.map(row).join(''):''); }
  else{
    let h;
    if(_ws.tab==='entry'){      // 기본 신호 칸과 주도주 칸을 따로 채운다 (2026-10-10 "이 종목 중에 좋은 순위가 뭐란 거고")
      const B=L.filter(x=>!x.lead), Ld=L.filter(x=>x.lead);
      h=(B.length&&Ld.length?`<div class="ws-sub">기본 신호 · 빈 칸 수만큼 위에서부터 (강도 RS 높은 순)</div>`:'')+B.map(row).join('')
        +(Ld.length?`<div class="ws-sub">🔥 주도주 · 기본과 따로 위에서 2종목까지 소량 (거래당 위험 0.10%)</div>`+Ld.map(row).join(''):'');
    } else h=L.map(row).join('');
    if(_ws.tab==='entry'&&L.length<6){      // 오늘 진입이 적은 날: 아래를 비워 두지 않고 다음 후보(대기)를 흐리게 이어서 (2026-10-09 "여기가 붕 뜬다")
      const W=wsItems('wait').slice(0,10);
      if(W.length) h+=`<div class="ws-sub">다음 후보 · 대기</div>`+W.map(x=>row(x).replace('class="ws-item','class="ws-item dim')).join('');
    }
    el.innerHTML=h;
  }
  wsFit();
}
let _wsQT=null;
function wsSearch(v){      // 종목 검색 (2026-10-09) — 이름·코드·초성, 고르면 오른쪽에 차트·패널
  clearTimeout(_wsQT); const box=document.getElementById('ws-sr');
  if(!v.trim()){ box.classList.remove('on'); box.innerHTML=''; return; }
  _wsQT=setTimeout(async()=>{
    const d=await fetch(`${API}/stocks/search?q=${encodeURIComponent(v)}`).then(r=>r.ok?r.json():null).catch(()=>null);
    if(document.getElementById('ws-q').value!==v) return;
    const L=(d&&d.items)||[];
    box.innerHTML=L.length?L.map(x=>`<div class="ws-item" onclick="wsPick('${x.code}','${x.name.replace(/'/g,'')}')">${wsAv(x.code,x.name)}<div class="ws-txt"><div class="ws-nm"><span class="n">${x.name}</span></div><div class="ws-tg">${x.code}</div></div>
      <div class="ws-px">${x.close?Math.round(x.close).toLocaleString():'-'}<div style="color:${x.chg>0?'var(--up)':x.chg<0?'var(--down)':'var(--muted)'}">${x.chg>0?'+':''}${(x.chg||0).toFixed(2)}%</div></div></div>`).join('')
      :'<div class="ts" style="padding:10px">찾는 종목이 없습니다</div>';
    box.classList.add('on');
  },200);
}
function wsPick(code,name){
  const q=document.getElementById('ws-q'); q.value=''; q.blur(); wsSearch('');
  wsOpen(code,name);
  const m=document.querySelector('.ws-main'); if(m&&window.innerWidth<900) m.scrollIntoView({behavior:'smooth',block:'start'});
}
document.addEventListener('click',e=>{ if(!e.target.closest('.ws-search')){ const b=document.getElementById('ws-sr'); if(b) b.classList.remove('on'); } });
// 목록 칸 높이를 가운데 차트 칸에 맞춤 (PC) — 짧은 목록이 위에 떠 보이지 않게
function wsFit(){ const m=document.querySelector('#panel-home .ws-main'), l=document.querySelector('#panel-home .ws-list');
  if(!m||!l) return; l.style.height=window.innerWidth>760?m.offsetHeight+'px':''; }
if(window.ResizeObserver){ const _wsRO=new ResizeObserver(()=>wsFit()); document.addEventListener('DOMContentLoaded',()=>{ const m=document.querySelector('#panel-home .ws-main'); if(m) _wsRO.observe(m); }); }
window.addEventListener('resize',wsFit);
async function wsOpen(code,name){
  _ws.code=code;
  document.querySelectorAll('.ws-item').forEach(e=>e.classList.toggle('on',e.dataset.c===code));
  document.getElementById('ws-name').textContent=name; document.getElementById('ws-sub').textContent=code;
  document.getElementById('ws-note').textContent='불러오는 중…';
  document.getElementById('ws-panel').innerHTML='<div class="ts">불러오는 중…</div>';
  // 패널은 따로 — 차트는 패널을 기다리지 않고 먼저 그림 (2026-10-09 "오래 걸리노")
  fetch(`${API}/stock/${code}/panel`).then(r=>r.ok?r.json():null).catch(()=>null).then(pn=>{ if(_ws.code===code) renderStockPanel(pn,'ws-panel'); });
  // 봉이 오면 바로 그리고 신호는 덧그림 (2026-10-09 "로딩이 느리다")
  const sgP = fetch(`${API}/stock/${code}/chart-signals`).then(r=>r.ok?r.json():null).catch(()=>null);
  const cd = await fetch(`${API}/stock/${code}/candles?count=330`).then(r=>r.ok?r.json():null).catch(()=>null);   // 1년 + EMA 계산용 (DB + 토스 최근)
  if(_ws.code!==code) return;      // 그사이 다른 종목을 눌렀으면 버림
  if(!cd||!cd.candles||!cd.candles.length){ document.getElementById('ws-note').textContent='차트 데이터를 못 불러왔습니다'; return; }
  _ws.cache={[code]:{cd,sg:null}};
  wsDraw();
  const sg = await sgP;
  if(_ws.code!==code) return;
  _ws.cache[code].sg=sg; wsDraw();
}

// ── 매매 일지: 보유 종목 차트 (로그인 헤더로 평단·손절·내 매수·매도까지, 2026-10-09) ──
let _jrWs={code:null,data:null,cache:null};
async function jrWsLoad(){
  const d=await fetch(`${API}/journal/holdings`,{headers:jrH()}).then(r=>r.ok?r.json():null).catch(()=>null);
  const el=document.getElementById('jr-ws-items');
  if(!d){ el.innerHTML='<div class="ts" style="padding:10px">못 불러왔습니다</div>'; return; }
  _jrWs.data=d; document.getElementById('jr-ws-asof').textContent=d.live?`장중 ${d.live} 가격`:`${d.as_of} 정규장 종가`;
  const row=x=>{ const tg=(x.stop?`손절 ${Math.round(x.stop).toLocaleString()}${x.room!=null?` · ${x.room<0?'⛔ 이탈':x.room<=2?'⚠ '+x.room+'% 남음':x.room+'% 남음'}`:''}`:'손절선 없음');
    return `<div class="ws-item${x.code===_jrWs.code?' on':''}" data-c="${x.code}" onclick="jrWsOpen('${x.code}','${x.name.replace(/'/g,'')}')">${wsAv(x.code,x.name)}
      <div class="ws-txt"><div class="ws-nm">${x.name}</div><div class="ws-tg">${tg}</div></div>
      <div class="ws-px">${x.close?Math.round(x.close).toLocaleString():'-'}<div style="color:${x.chg>0?'var(--up)':x.chg<0?'var(--down)':'var(--muted)'}">${x.chg>0?'+':''}${(x.chg||0).toFixed(2)}%</div>${x.gain!=null?`<div class="ws-tg">수익 ${x.gain>0?'+':''}${x.gain}%</div>`:''}</div></div>`; };
  const a=d.held.filter(x=>!x.long), b=d.held.filter(x=>x.long);
  el.innerHTML=(a.map(row).join('')+(b.length?'<div class="ws-sec">장기 보유</div>'+b.map(row).join(''):''))||'<div class="ts" style="padding:10px">보유 종목 없음</div>';
  if(!_jrWs.code&&d.held.length) jrWsOpen(d.held[0].code,d.held[0].name);
}
function jrWsPeriod(n){ _ws.per=n; try{ localStorage.setItem('ws-per',n); }catch(e){} jrWsDraw(); }
function jrWsTf(tf){ _jrWs.tf=tf; jrWsDraw(); }
async function jrWsDraw(){
  const tf=_jrWs.tf||'1d';
  document.querySelectorAll('#jr-ws-tf button').forEach(b=>b.classList.toggle('on',b.dataset.tf===tf));
  document.getElementById('jr-ws-per').style.display=(tf==='1d')?'flex':'none';
  document.querySelectorAll('#jr-ws-per button').forEach(b=>b.classList.toggle('on',+b.dataset.n===_ws.per));
  const c=_jrWs.cache; if(!c||!c.cd||c.code!==_jrWs.code) return;
  if(tf!=='1d'){
    const code=_jrWs.code; document.getElementById('jr-ws-note').textContent=`${TF_NAME[tf]} 불러오는 중…`;
    const cd=c[tf]||(c[tf]=await tfCandles(code,tf));
    if(_jrWs.code!==code||(_jrWs.tf||'1d')!==tf) return;
    if(!cd){ document.getElementById('jr-ws-note').textContent=`${TF_NAME[tf]}을 못 받았습니다`; return; }
    renderLwChart('jr-chart',cd.candles,[],tf==='1w'?80:120);
    document.getElementById('jr-ws-note').textContent=`${TF_NAME[tf]} · 내가 산·판 날과 신호는 일봉에서만 보여요`;
    return;
  }
  const g=renderLwChart('jr-chart',c.cd.candles,c.sg?c.sg.items:[],_ws.per);
  document.getElementById('jr-ws-note').textContent=`최근 ${_ws.per}거래일 · EMA 5·10·20·60`+(g!=null?` · EMA 5·10·20 간격 ${g.toFixed(1)}%`:'')+_avwapNote;
}
async function jrWsOpen(code,name){
  _jrWs.code=code;
  document.querySelectorAll('#jr-ws-items .ws-item').forEach(e=>e.classList.toggle('on',e.dataset.c===code));
  document.getElementById('jr-ws-name').textContent=name; document.getElementById('jr-ws-sub').textContent=code;
  document.getElementById('jr-ws-note').textContent='불러오는 중…'; document.getElementById('jr-ws-panel').innerHTML='<div class="ts">불러오는 중…</div>';
  fetch(`${API}/stock/${code}/panel`,{headers:jrH()}).then(r=>r.ok?r.json():null).catch(()=>null).then(pn=>{ if(_jrWs.code===code) renderStockPanel(pn,'jr-ws-panel'); });
  const [cd,sg]=await Promise.all([
    fetch(`${API}/stock/${code}/candles?count=330`).then(r=>r.ok?r.json():null).catch(()=>null),
    fetch(`${API}/stock/${code}/chart-signals`,{headers:jrH()}).then(r=>r.ok?r.json():null).catch(()=>null)]);
  if(_jrWs.code!==code) return;
  if(!cd||!cd.candles||!cd.candles.length){ document.getElementById('jr-ws-note').textContent='차트 데이터를 못 불러왔습니다'; return; }
  _jrWs.cache={code,cd,sg}; jrWsDraw();
}
// 오른쪽 패널: 결론(상태 제목) 크게 · 단계 막대 · ✓/⚠ 칩 · 카드 · 세부 지표 (2026-10-09, 카드형pha식 배치)
function renderStockPanel(p, target){
  const el=document.getElementById(target||'cm-panel');
  if(!p||!p.ok){el.innerHTML='';return;}
  const steps=['관찰','후보','보유','관리','청산'];
  const sg=n=>(n>0?'+':'')+n.toFixed(2)+'%';
  el.innerHTML=`
    <div class="cp-head"><div class="cp-grade">${p.grade.letter}</div>
      <div class="cp-gw">추세 등급<b>${p.grade.word}</b><span class="cp-price">${Math.round(p.close).toLocaleString()} <span style="color:${p.chg>0?'var(--up)':p.chg<0?'var(--down)':'var(--muted)'}">${sg(p.chg)}</span></span></div></div>
    <div class="cp-state">
      <div class="cp-steps">${steps.map((s,i)=>`<div class="cp-step ${i===p.stage?'on':i<p.stage?'done':''}"><i></i>${s}</div>`).join('')}</div>
      <div class="cp-title">${p.title}</div><div class="cp-sub">${p.sub||''}</div>
    </div>
    ${(p.checks&&p.checks.length)?`<div class="cp-state" style="padding:10px 12px"><div style="font-size:12px;color:var(--muted);margin-bottom:4px">신호 앞 체크리스트 · ${p.checks.filter(c=>c.ok).length}/${p.checks.length} ✓${p.checks.some(c=>!c.ok)?' — ⚠ 하나라도 있으면 약한 신호':''}</div>
      ${p.checks.map(c=>`<div style="display:flex;gap:6px;font-size:12px;padding:2px 0"><b style="color:${c.ok?'var(--blue)':'var(--orange)'};width:14px">${c.ok?'✓':'⚠'}</b><span style="color:var(--muted);width:62px;flex:none">${c.k}</span><span style="color:var(--text)">${c.v}</span></div>`).join('')}</div>`:''}
    <div class="cp-chips">${p.chips.map(c=>`<span class="cp-chip ${c.ok?'ok':'warn'}">${c.ok?'✓':'⚠'} ${c.text}</span>`).join('')}</div>
    <div class="cp-cards">${p.cards.map(c=>`<div class="cp-card"><div class="l">${c.label}</div><div class="v">${c.value}</div><div class="s">${c.sub||''}</div></div>`).join('')}</div>
    <div class="cp-rows">${p.rows.map(r=>`<div class="cp-row"${r.tip?` title="${r.tip}"`:''}><span class="k">${r.k}${r.tip?' ⓘ':''}</span><span class="v">${r.v}</span></div>`).join('')}</div>
    <div class="ts" style="font-size:10.5px">일봉 ${p.date} 기준 · 종가는 정규장 15:30</div>`;
}
let _cm={code:null,tf:'1d',cache:{}};
async function cmTf(tf){
  _cm.tf=tf; document.querySelectorAll('#cm-tf button').forEach(b=>b.classList.toggle('on',b.dataset.tf===tf));
  const code=_cm.code, c=_cm.cache; if(!code||!c.cd) return;
  if(tf==='1d'){ const g=renderLwChart('cm-chart',c.cd.candles,c.sg?c.sg.items:[],90);
    document.getElementById('chart-modal-note').textContent=`일봉 · 1년 (끌어서 과거 보기)`+(g!=null?` · EMA 5·10·20 간격 ${g.toFixed(1)}% ${g<=4?'(모임 ✓)':g>=7?'(벌어짐 ⚠)':''}`:'')+_avwapNote; return; }
  document.getElementById('chart-modal-note').textContent=`${TF_NAME[tf]} 불러오는 중…`;
  const cd=c[tf]||(c[tf]=await tfCandles(code,tf));
  if(_cm.code!==code||_cm.tf!==tf) return;
  if(!cd){ document.getElementById('chart-modal-note').textContent=`${TF_NAME[tf]}을 못 받았습니다`; return; }
  renderLwChart('cm-chart',cd.candles,[],tf==='1w'?80:120);
  document.getElementById('chart-modal-note').textContent=`${TF_NAME[tf]}${tf==='1w'?'':' · 최근 약 6거래일'} · 신호는 일봉에서만 보여요`;
}
async function openChartModal(code, name, spikeDate){
  _cm={code,tf:'1d',cache:{}}; document.getElementById('cm-tf').style.display='flex';
  document.querySelectorAll('#cm-tf button').forEach(b=>b.classList.toggle('on',b.dataset.tf==='1d'));
  document.getElementById('chart-modal-title').textContent = `${name} (${code})`;
  document.getElementById('chart-modal-note').textContent = '로딩 중…';
  lwClear('cm-chart');
  document.getElementById('cm-panel').innerHTML='<div class="ts">불러오는 중…</div>';
  document.getElementById('chart-modal-bg').classList.add('show');
  fetch(`${API}/stock/${code}/panel`).then(r=>r.ok?r.json():null).then(renderStockPanel).catch(()=>renderStockPanel(null));
  try{
    // 봉이 오면 바로 그리고, 신호는 따로 받아 덧그림 (2026-10-09 "로딩이 느리다" — 둘 다 기다리던 것)
    const sigP = fetch(`${API}/stock/${code}/chart-signals`).then(r=>r.ok?r.json():null).catch(()=>null);
    const data = await fetch(`${API}/stock/${code}/candles?count=330`).then(r=>r.ok?r.json():null);   // 1년 (DB + 토스 최근) — 확대·이동으로 볼 수 있게
    if(!data || !data.candles || !data.candles.length){
      document.getElementById('chart-modal-note').textContent = '토스 API에서 차트 데이터를 가져오지 못했습니다.';
      return;
    }
    if(_cm.code!==code) return;
    _cm.cache={cd:data,sg:null};
    renderLwChart('cm-chart', data.candles, [], 90);
    const sig = await sigP;
    if(_cm.code!==code || _cm.tf!=='1d') return;
    _cm.cache.sg=sig;
    const g = renderLwChart('cm-chart', data.candles, sig?sig.items:[], 90);
    document.getElementById('chart-modal-note').textContent = (spikeDate ? `스파이크일: ${spikeDate}` : `최근 90거래일 일봉`)
      + (g!=null ? ` · EMA 5·10·20 간격 ${g.toFixed(1)}% ${g<=4?'(모임 ✓)':g>=7?'(벌어짐 ⚠)':''}` : '') + _avwapNote;
  }catch(e){
    console.error(e);
    document.getElementById('chart-modal-note').textContent = '차트 로딩 실패';
  }
}
// 지수 차트 (2026-10-07: 오늘 탭 지수 카드를 누르면 최근 60일 + EMA)
async function openIndexChart(sym, name){
  _cm={code:null,tf:'1d',cache:{}}; document.getElementById('cm-tf').style.display='none';
  document.getElementById('cm-panel').innerHTML='';
  document.getElementById('chart-modal-title').textContent = `${name} 지수 — 일봉`;
  document.getElementById('chart-modal-note').textContent = '로딩 중…';
  lwClear('cm-chart');
  document.getElementById('chart-modal-bg').classList.add('show');
  const data = await fetch(`${API}/index/candles/${sym}?count=150`).then(r=>r.ok?r.json():null).catch(()=>null);
  if(!data || !data.candles || !data.candles.length){ document.getElementById('chart-modal-note').textContent='지수 데이터를 가져오지 못했습니다'; return; }
  const g = renderLwChart('cm-chart', data.candles, [], 60);
  const c=data.candles, last=+c[c.length-1].closePrice, prev=+c[c.length-2].closePrice;
  document.getElementById('chart-modal-note').textContent = `최근 60거래일 · 마지막 ${last.toLocaleString()} (${((last/prev-1)*100).toFixed(2)}%)`
    + (g!=null ? ` · EMA 5·10·20 간격 ${g.toFixed(1)}% ${g<=4?'(모임 ✓)':g>=7?'(벌어짐 ⚠)':''}` : '');
}
function closeChartModal(){ document.getElementById('chart-modal-bg').classList.remove('show'); }

// ── Lightweight Charts 차트: 손가락으로 확대·이동, 올리면 그 봉 가격·거래량·이평선 (2026-10-09) ──
const _lw={};
function lwClear(cid){ if(_lw[cid]){ try{ _lw[cid].ro.disconnect(); _lw[cid].chart.remove(); }catch(e){} delete _lw[cid]; } const el=document.getElementById(cid); if(el) el.innerHTML=''; const lg=document.getElementById(cid+'-leg'); if(lg) lg.innerHTML=''; }
function renderLwChart(cid, allCandles, signals, per){
  const el=document.getElementById(cid);
  if(!el) return null;
  if(!window.LightweightCharts){ el.innerHTML='<div class="ts" style="padding:20px">차트 라이브러리를 못 불러왔습니다 (새로고침)</div>'; return null; }
  lwClear(cid);
  const intra=allCandles.length&&allCandles[0].t!=null;      // 분봉이면 시간 = 숫자(한국 시간 그대로)
  const data=allCandles.map(c=>({time:intra?c.t:(c.timestamp||'').slice(0,10),open:+c.openPrice,high:+c.highPrice,low:+c.lowPrice,close:+c.closePrice,vol:+c.volume,lab:intra?(c.timestamp||'').slice(5,16).replace('-','/').replace('T',' '):(c.timestamp||'').slice(2,10).replace(/-/g,'/')})).filter(d=>d.time);
  if(!data.length) return null;
  const small=el.clientWidth<600;
  const chart=LightweightCharts.createChart(el,{width:el.clientWidth,height:el.clientHeight,
    layout:{background:{type:'solid',color:'#0d1117'},textColor:'#8b949e',fontSize:small?10:11},
    grid:{vertLines:{color:'rgba(139,148,158,.07)'},horzLines:{color:'rgba(139,148,158,.10)'}},
    rightPriceScale:{borderColor:'#30363d',scaleMargins:{top:0.08,bottom:0.24}},
    timeScale:{borderColor:'#30363d',rightOffset:3,barSpacing:small?5:7,minBarSpacing:1,timeVisible:intra,secondsVisible:false},
    crosshair:{mode:0,vertLine:{color:'#6e7681',labelBackgroundColor:'#30363d'},horzLine:{color:'#6e7681',labelBackgroundColor:'#30363d'}},
    localization:{priceFormatter:p=>Math.round(p).toLocaleString(),dateFormat:'yy/MM/dd'},
    handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},handleScale:{axisPressedMouseMove:true,mouseWheel:true,pinch:true}});
  const cs=chart.addCandlestickSeries({upColor:'#f85149',downColor:'#3b82f6',borderVisible:false,wickUpColor:'#f85149',wickDownColor:'#3b82f6'});
  cs.setData(data.map(d=>({time:d.time,open:d.open,high:d.high,low:d.low,close:d.close})));
  const vs=chart.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'vol',lastValueVisible:false,priceLineVisible:false});
  chart.priceScale('vol').applyOptions({scaleMargins:{top:0.8,bottom:0}});
  vs.setData(data.map(d=>({time:d.time,value:d.vol,color:d.close>=d.open?'rgba(248,81,73,.5)':'rgba(59,130,246,.5)'})));
  const emaOf=(arr,n)=>{ const k=2/(n+1); let e=arr[0]; return arr.map(v=>(e=v*k+e*(1-k))); };
  const closes=data.map(d=>d.close), EN=[5,10,20,60], EC=['#f778ba','#e3b341','#56d4dd','#3fb950'];
  const ES=EN.map(n=>emaOf(closes,n));
  ES.forEach((a,k)=>{ const ls=chart.addLineSeries({color:EC[k],lineWidth:k===3?2:1,priceLineVisible:false,lastValueVisible:!small,crosshairMarkerVisible:false}); ls.setData(a.map((v,i)=>({time:data[i].time,value:v}))); });
  // 기준봉 VWAP (7/30 뒤 +8%·거래 3배 양봉, 없으면 거래 가장 많은 양봉부터)
  _avwapNote='';
  let cyc=intra?data.length:data.findIndex(d=>d.time>='2026-07-30'); if(cyc<0) cyc=data.length;
  const st=Math.max(20,cyc); let ai=-1, lab='기준봉';
  for(let i=data.length-1;i>=st;i--){ const avg=data.slice(i-20,i).reduce((a,b)=>a+b.vol,0)/20; if(data[i].close>=data[i-1].close*1.08&&data[i].close>data[i].open&&avg>0&&data[i].vol>=avg*3){ai=i;break;} }
  if(ai<0&&!intra){ let b=-1; for(let i=Math.max(st,1);i<data.length;i++){ if(data[i].close>data[i].open&&data[i].close>data[i-1].close&&(b<0||data[i].vol>data[b].vol)) b=i; } if(b>=0){ai=b;lab='최대거래 양봉';} }
  if(ai>=0){ let pv=0,vv=0; const av=[]; for(let i=ai;i<data.length;i++){ const tp=(data[i].high+data[i].low+data[i].close)/3; pv+=tp*data[i].vol; vv+=data[i].vol; av.push({time:data[i].time,value:vv?pv/vv:tp}); }
    const ls=chart.addLineSeries({color:'#f0883e',lineWidth:2,lineStyle:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}); ls.setData(av);
    const lv=av[av.length-1].value, lc=closes[closes.length-1]; _avwapNote=` · ${lab} ${data[ai].time.slice(5)} VWAP ${Math.round(lv).toLocaleString()} ${lc>=lv?'위 ✓':'아래 ⚠'}`; }
  // 신호 → 화살표 표시 (폰에선 진입·청산·손절·종베 추천·매수매도·위험만 글자)
  const MC={entry:['#58a6ff','arrowUp'],exit:['#c9d1d9','arrowDown'],exit_bad:['#f0883e','arrowDown'],buy:['#1f6feb','arrowUp'],rest:['#2d9c87','circle'],info:['#8b949e','square'],
            warn:['#f0883e','arrowDown'],trade_buy:['#ffffff','arrowUp'],trade_sell:['#bc8cff','arrowDown'],wait:['#58a6ff','circle'],near:['#6e7681','circle'],note:['#8b949e','circle'],score:['#d2a8ff','circle'],score_better:['#d2a8ff','arrowUp'],score_keep:['#d2a8ff','circle'],score_add:['#d2a8ff','arrowUp'],score_hold:['#d2a8ff','circle'],dip:['#56d4dd','arrowUp'],lead:['#e8590c','arrowUp'],lead_keep:['#e8590c','circle'],shape:['#6e7681','circle']};
  const KEY=['entry','exit','exit_bad','trade_buy','trade_sell','warn'];
  const ts=new Set(data.map(d=>d.time));
  let mk=(signals||[]).filter(sg=>ts.has(sg.date));
  if(small) mk=mk.filter(sg=>sg.kind!=='info');
  const DOT=['near','note','wait','shape'];     // 참고 점: 작게 점만 — 글자는 봉에 올리면 위 정보 줄에 (2026-10-09 "점 뜨는 거 뭐고", 글자 겹침)
  mk=mk.map(sg=>{ const [col,shape]=MC[sg.kind]||MC.info; const dot=DOT.includes(sg.kind);
    const showTxt=!dot&&(!small||KEY.includes(sg.kind)||sg.label.startsWith('종가 매수'));
    if(sg.kind==='score') return {time:sg.date,position:'belowBar',color:col,shape:'arrowUp',text:sg.good?'✅매수':'매수',size:sg.good?1.2:1};   // 종가 매수 신호 (점수는 봉에 올리면)
    if(sg.kind==='score_better') return {time:sg.date,position:'belowBar',color:col,shape:'arrowUp',text:'더 좋음',size:0.7};
    if(sg.kind==='score_add') return {time:sg.date,position:'belowBar',color:col,shape:'arrowUp',text:'더 사기',size:0.8};   // 들고 있는 첫 매수 +1R↑ · 손절 올리기
    if(sg.kind==='score_hold') return {time:sg.date,position:'belowBar',color:col,shape:'circle',text:'보유 중',size:0.6};   // 들고 있으면 더 사지 않기
    if(sg.kind==='score_keep') return {time:sg.date,position:'belowBar',color:col,shape:'circle',text:'',size:0.4};   // 매수 자리 유지 (점만)
    if(sg.kind==='lead') return {time:sg.date,position:'belowBar',color:'#e8590c',shape:'arrowUp',text:'🔥주도',size:1};   // 주도주 매수 (소량 · 위험 0.10%)
    if(sg.kind==='lead_keep') return {time:sg.date,position:'belowBar',color:'#e8590c',shape:'circle',text:'',size:0.4};   // 주도주 보유 중 또 뜸
    if(sg.kind==='dip') return {time:sg.date,position:'belowBar',color:col,shape,text:'줍기',size:0.9};      // 급락 날 줍기   // 종가 점수 6·7 — 숫자만 (글자 겹침 방지)
    return {time:sg.date,position:sg.pos==='below'?'belowBar':'aboveBar',color:col,shape,text:showTxt?sg.label:'',size:sg.kind==='entry'?1.6:dot?0.4:1}; })
    .sort((a,b)=>a.time<b.time?-1:a.time>b.time?1:0);
  cs.setMarkers(mk);
  // 십자선 → 위에 그 봉 정보
  const leg=document.getElementById(cid+'-leg'), byT={}; data.forEach((d,i)=>byT[d.time]=i);
  const sigBy={}, whyBy={}; (signals||[]).forEach(sg=>{ (sigBy[sg.date]=sigBy[sg.date]||[]).push(sg.label); if(sg.why) whyBy[sg.date]=sg.why; });   // 올린 봉의 우리 신호도 글자로 · 매수면 근거 (한 줄에 하나)
  const show=(i,hov)=>{ if(!leg||i==null||i<0) return; const d=data[i], pc=i>0?data[i-1].close:d.open, ch=(d.close/pc-1)*100, c=ch>=0?'#f85149':'#58a6ff';
    leg.innerHTML=`<div><b>${d.lab}</b> 시 ${Math.round(d.open).toLocaleString()} 고 ${Math.round(d.high).toLocaleString()} 저 ${Math.round(d.low).toLocaleString()} 종 <b style="color:${c}">${Math.round(d.close).toLocaleString()} (${ch>=0?'+':''}${ch.toFixed(2)}%)</b> · 거래 ${Math.round(d.vol).toLocaleString()}</div>`
      +`<div>${EN.map((n,k)=>`<span style="color:${EC[k]}">EMA${n} ${Math.round(ES[k][i]).toLocaleString()}</span>`).join(' · ')}</div>`
      +`<div><b style="color:#58a6ff">${sigBy[d.time]?'신호: '+sigBy[d.time].join(' · '):'&nbsp;'}</b></div>`;
    // 매수 근거 — 매수 봉에 올렸을 때만 차트 위 상자로 (2026-10-09 "매수별로 매수 근거가 필요하다") · 한 줄에 하나
    let wb=el.parentNode.querySelector('.lwwhy'); if(!wb){ wb=document.createElement('div'); wb.className='lwwhy'; el.parentNode.appendChild(wb); }
    const w=hov&&whyBy[d.time]; wb.style.display=w?'block':'none';
    if(w) wb.innerHTML=`<b>매수 근거 · ${d.lab}</b>`+w.map(x=>`<div>· ${String(x).replace(/</g,'&lt;')}</div>`).join(''); };
  show(data.length-1);
  chart.subscribeCrosshairMove(p=>{ const h=p&&p.time&&byT[p.time]!=null; show(h?byT[p.time]:data.length-1,h); });
  const n=data.length; chart.timeScale().setVisibleLogicalRange({from:Math.max(0,n-(per||90)),to:n+2});
  const ro=new ResizeObserver(()=>chart.applyOptions({width:el.clientWidth,height:el.clientHeight})); ro.observe(el);
  _lw[cid]={chart,ro};
  const last=ES.slice(0,3).map(a=>a[a.length-1]); return closes.length?(Math.max(...last)-Math.min(...last))/closes[closes.length-1]*100:null;
}
// 외부 라이브러리 없이 순수 canvas로 캔들차트 + 거래량 + 눌림목 지지선 그리기 (지금은 안 씀 — Lightweight Charts로 바꿈)
function drawCandleChart(allCandles, spikeDate, show, opt){
  opt=opt||{};
  // 단기 EMA 5·10·20 (2026-10-07 사용자 "EMA를 내 눈으로 확인할 수 없나") — 앞쪽 캔들로 미리 계산하고 최근 90개만 그림
  const emaOf=(arr,n)=>{ const k=2/(n+1); let e=arr[0]; return arr.map(v=>(e=v*k+e*(1-k))); };
  const closesAll=allCandles.map(c=>+c.closePrice);
  const EMA=[5,10,20,60].map(n=>emaOf(closesAll,n));
  const off=Math.max(0,allCandles.length-(show||90));
  const candles=allCandles.slice(off);
  const ES=EMA.map(a=>a.slice(off));
  const cvCandle = document.getElementById(opt.cId||'pb-candle-canvas');
  const cvVol = document.getElementById(opt.vId||'pb-volume-canvas');
  const dpr = window.devicePixelRatio || 1;
  const W = cvCandle.clientWidth || 760;
  const H = cvCandle.clientHeight || 340, HV = cvVol.clientHeight || 100;
  [[cvCandle,H],[cvVol,HV]].forEach(([cv,h])=>{ cv.width=W*dpr; cv.height=h*dpr; });

  const ctxC = cvCandle.getContext('2d'); ctxC.scale(dpr,dpr);
  const ctxV = cvVol.getContext('2d'); ctxV.scale(dpr,dpr);
  ctxC.clearRect(0,0,W,H); ctxV.clearRect(0,0,W,HV);
  ctxC.fillStyle = '#0d1117'; ctxC.fillRect(0,0,W,H);
  ctxV.fillStyle = '#0d1117'; ctxV.fillRect(0,0,W,HV);

  const n = candles.length;
  const AX = 66;                       // 오른쪽 가격축·이평선 값 자리 (2026-10-09)
  const PW = W - AX;
  const cw = PW/n, bw = Math.max(1, cw*0.62);
  const lows = candles.map(c=>+c.lowPrice), highs = candles.map(c=>+c.highPrice);
  const minP = Math.min(...lows, ...ES.flat()), maxP = Math.max(...highs, ...ES.flat());
  const pad = (maxP-minP)*0.06 || 1;
  const sigOn = opt.signals && opt.signals.length, mt = sigOn?40:22, mb = (sigOn?34:12)+14;   // 신호 라벨 + 아래 날짜 자리
  const yP = p => H - mb - (p-(minP-pad))/((maxP+pad)-(minP-pad))*(H-mt-mb);
  const maxV = Math.max(...candles.map(c=>+c.volume), 1);
  const yV = v => HV - 4 - (v/maxV)*(HV-8);

  // 가격 눈금(오른쪽) · 가로 격자 · 날짜(아래, 달 바뀌는 봉)
  { const lo=minP-pad, hi=maxP+pad, raw=(hi-lo)/6, mag=Math.pow(10,Math.floor(Math.log10(raw))), stp=[1,2,2.5,5,10].map(m=>m*mag).find(v=>v>=raw)||raw;
    ctxC.font='11px sans-serif'; ctxC.textAlign='left';
    for(let v=Math.ceil(lo/stp)*stp; v<=hi; v+=stp){ const y=yP(v); if(y<mt-6||y>H-mb+2) continue;
      ctxC.strokeStyle='rgba(139,148,158,.12)'; ctxC.beginPath(); ctxC.moveTo(0,y); ctxC.lineTo(PW,y); ctxC.stroke();
      ctxC.fillStyle='#6e7681'; ctxC.fillText(Math.round(v).toLocaleString(), PW+6, y+4); }
    let pm=''; candles.forEach((c,i)=>{ const d=(c.timestamp||'').slice(0,10), m=d.slice(5,7);
      if(m && m!==pm){ if(pm){ const x=i*cw; ctxC.strokeStyle='rgba(139,148,158,.10)'; ctxC.beginPath(); ctxC.moveTo(x,mt-10); ctxC.lineTo(x,H-14); ctxC.stroke();
        ctxC.fillStyle='#6e7681'; ctxC.fillText(`${+m}월`, x+3, H-3); } pm=m; } }); }
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
  // 7/30 바닥(이번 상승 구간 시작) 세로 점선
  { const ci=candles.findIndex(c=>(c.timestamp||'').slice(0,10)>='2026-07-30');
    if(ci>0){ const x=ci*cw; ctxC.strokeStyle='#6e7681'; ctxC.setLineDash([2,4]); ctxC.beginPath(); ctxC.moveTo(x,20); ctxC.lineTo(x,H); ctxC.stroke(); ctxC.setLineDash([]);
      ctxC.fillStyle='#8b949e'; ctxC.font='11px sans-serif'; ctxC.fillText('7/30 바닥', x+3, H-6); } }
  // EMA 선 + 범례
  const EC=['#f778ba','#e3b341','#56d4dd','#3fb950'], EN=['EMA5','EMA10','EMA20','EMA60'];   // EMA60 = 초록(추세 필터, 굵게)
  ctxC.lineWidth=1.4;
  ES.forEach((a,k)=>{ ctxC.strokeStyle=EC[k]; ctxC.lineWidth=k===3?2.2:1.4; ctxC.beginPath(); a.forEach((v,i)=>{ const x=i*cw+cw/2, y=yP(v); i?ctxC.lineTo(x,y):ctxC.moveTo(x,y); }); ctxC.stroke(); });
  ctxC.lineWidth=1; ctxC.font='12px sans-serif';
  EN.forEach((t,k)=>{ ctxC.fillStyle=EC[k]; ctxC.fillText(t, 8+k*62, 16); });
  // 기준봉 앵커드 VWAP (2026-10-07 vwap.py: 장대양봉 뒤 종가가 이 선 위면 20일 +2.3%, 아래면 0.0%)
  // 기준봉 = 보이는 구간에서 가장 최근의 +8%↑·거래 3배↑ 양봉. 그날부터 (고+저+종)/3 × 거래량으로 평균
  _avwapNote='';
  const volsAll=allCandles.map(c=>+c.volume);
  // 기준봉은 이번 상승 구간(7/30 바닥) 이후에서만 찾음 (2026-10-07 사용자: 솔브레인 6/12처럼 하락 전 봉에서 시작하면 의미 없음)
  const CYCLE='2026-07-30';
  let cyc=allCandles.findIndex(c=>(c.timestamp||'').slice(0,10)>=CYCLE); if(cyc<0) cyc=allCandles.length;
  const st=Math.max(off,20,cyc);
  let ai=-1;
  for(let i=allCandles.length-1;i>=st;i--){
    const c=allCandles[i], p=+allCandles[i-1].closePrice, avg=volsAll.slice(i-20,i).reduce((a,b)=>a+b,0)/20;
    if(+c.closePrice>=p*1.08 && +c.closePrice>+c.openPrice && avg>0 && +c.volume>=avg*3){ ai=i; break; }
  }
  let anchorLab='기준봉 VWAP';
  if(ai<0){   // 기준봉(+8%·거래 3배)이 없으면 보이는 구간에서 거래가 가장 많았던 양봉에서 시작 (2026-10-07 SK이노베이션처럼 선이 안 뜨던 것)
    let best=-1;
    for(let i=Math.max(st,1);i<allCandles.length;i++){ const c=allCandles[i]; if(+c.closePrice>+c.openPrice && +c.closePrice>+allCandles[i-1].closePrice && (best<0||+c.volume>+allCandles[best].volume)) best=i; }
    if(best>=0){ ai=best; anchorLab='최대거래 양봉 VWAP'; }
  }
  if(ai>=0){
    let pv=0, vv=0; const av=[];
    for(let i=ai;i<allCandles.length;i++){ const c=allCandles[i], tp=(+c.highPrice + +c.lowPrice + +c.closePrice)/3; pv+=tp*(+c.volume); vv+=+c.volume; av.push(vv?pv/vv:tp); }
    ctxC.strokeStyle='#f0883e'; ctxC.lineWidth=2; ctxC.setLineDash([6,4]); ctxC.beginPath();
    av.forEach((v,k)=>{ const x=(ai-off+k)*cw+cw/2, y=yP(v); k?ctxC.lineTo(x,y):ctxC.moveTo(x,y); }); ctxC.stroke(); ctxC.setLineDash([]); ctxC.lineWidth=1;
    ctxC.fillStyle='#f0883e'; ctxC.fillText(anchorLab, 8+4*62, 16);
    const lv=av[av.length-1], lc=+allCandles[allCandles.length-1].closePrice;
    _avwapNote=` · ${anchorLab==='기준봉 VWAP'?'기준봉':'최대거래 양봉'} ${(allCandles[ai].timestamp||'').slice(5,10)} VWAP ${Math.round(lv).toLocaleString()} ${lc>=lv?'위 ✓':'아래 ⚠'}`;
  }
  // 신호 라벨 (2026-10-09 "차트에 조건들 넣어서 신호") — 사는 자리 아래, 기준봉·위험 위. 겹치면 비켜 쌓고 한 봉 한쪽에 2개까지
  if(sigOn){
    const idxOf={}; candles.forEach((c,i)=>{ idxOf[(c.timestamp||'').slice(0,10)]=i; });
    const COL={buy:['#1f6feb','#fff'],rest:['#2d7d6f','#fff'],info:['#484f58','#e6edf3'],warn:['#9a4d0f','#fff'],trade_buy:['#e6edf3','#0d1117'],trade_sell:['#8957e5','#fff'],
               entry:['#388bfd','#fff'],exit:['#21262d','#e6edf3'],exit_bad:['#bd561d','#fff']};
    const placed=[], cnt={}; ctxC.font='11px sans-serif'; ctxC.lineWidth=1;
    const rr=(x,y,w,h,r)=>{ ctxC.beginPath(); if(ctxC.roundRect) ctxC.roundRect(x,y,w,h,r); else ctxC.rect(x,y,w,h); };
    const PR={trade_buy:0,trade_sell:0,entry:0,exit:0,exit_bad:0,buy:1,warn:2,rest:3,info:4,wait:5,near:6,note:7};
    [...opt.signals].sort((a,b)=>(PR[a.kind]??9)-(PR[b.kind]??9)).forEach(sg=>{
      const i=idxOf[sg.date]; if(i===undefined) return;
      const k=i+sg.pos; cnt[k]=(cnt[k]||0)+1; if(cnt[k]>2 && !sg.kind.startsWith('trade')) return;
      const c=candles[i], x=i*cw+cw/2, tw=ctxC.measureText(sg.label).width+10, th=16, below=sg.pos==='below';
      const anchor = below ? yP(+c.lowPrice)+2 : yP(+c.highPrice)-2;
      let y = below ? anchor+8 : anchor-8-th, bx=Math.min(Math.max(x-tw/2,2),PW-tw-2);
      for(let t=0;t<8;t++){ if(!placed.some(r=>bx<r.x+r.w+2 && bx+tw+2>r.x && y<r.y+r.h+1 && y+th+1>r.y)) break; y += below ? th+3 : -(th+3); }
      y=Math.max(20,Math.min(H-th-1,y)); placed.push({x:bx,y,w:tw,h:th});
      if(sg.kind==='near'||sg.kind==='wait'||sg.kind==='note'){   // 점선·흐린 표시: 아깝게 놓침 / 지금 대기 / 정배열 시작(정보)
        const col=sg.kind==='wait'?'#58a6ff':sg.kind==='note'?'#8b949e':'#6e7681';
        ctxC.strokeStyle=col; ctxC.setLineDash([3,3]); ctxC.beginPath(); ctxC.moveTo(x,anchor); ctxC.lineTo(x, below?y:y+th); ctxC.stroke();
        if(sg.kind!=='note'){ rr(bx,y,tw,th,5); ctxC.stroke(); }
        ctxC.setLineDash([]); ctxC.fillStyle=col; ctxC.fillText(sg.label,bx+5,y+12); return;
      }
      const [bg,fg]=COL[sg.kind]||COL.info;
      ctxC.strokeStyle=bg; ctxC.beginPath(); ctxC.moveTo(x,anchor); ctxC.lineTo(x, below?y:y+th); ctxC.stroke();
      ctxC.fillStyle=bg; rr(bx,y,tw,th,5); ctxC.fill();
      if(sg.kind==='entry'||sg.kind==='exit'){ ctxC.strokeStyle='#e6edf3'; ctxC.lineWidth=1.2; rr(bx,y,tw,th,5); ctxC.stroke(); ctxC.lineWidth=1; }
      ctxC.fillStyle=fg; ctxC.fillText(sg.label,bx+5,y+12);
    });
  }
  { const tags=[[+candles[n-1].closePrice,(+candles[n-1].closePrice>=+candles[n-1].openPrice)?UP:DOWN,'현재']].concat(ES.map((a,k)=>[a[a.length-1],EC[k],EN[k]]));
    tags.sort((a,b)=>b[0]-a[0]); let py=-99; ctxC.font='10.5px sans-serif';
    tags.forEach(([v,col])=>{ let y=Math.max(yP(v)-7, py+14); y=Math.min(y,H-mb); py=y;
      ctxC.fillStyle=col; ctxC.beginPath(); if(ctxC.roundRect) ctxC.roundRect(PW+2,y,AX-4,14,3); else ctxC.rect(PW+2,y,AX-4,14); ctxC.fill();
      ctxC.fillStyle='#0d1117'; ctxC.fillText(Math.round(v).toLocaleString(), PW+6, y+11); }); }
  const last=ES.slice(0,3).map(a=>a[a.length-1]), cl=+candles[n-1].closePrice;   // 간격은 5·10·20만
  return cl ? (Math.max(...last)-Math.min(...last))/cl*100 : null;
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
// 차트 후보 탭 접기/펼치기 상태 기억 (기본: 손절 짧은 자리만 펼침)
(function(){
  let st={}; try{ st=JSON.parse(localStorage.getItem('cd-open')||'{}'); }catch(e){}
  document.querySelectorAll('details.sec').forEach(d=>{
    const k=d.dataset.k; d.open = k in st ? st[k] : k==='ss';
    d.addEventListener('toggle',()=>{ st[k]=d.open; try{ localStorage.setItem('cd-open',JSON.stringify(st)); }catch(e){} });
  });
})();
try{ try{ const v=localStorage.getItem('vr-mincap'); if(v!==null) document.getElementById('vr-mincap').value=v; }catch(e){}
  for(const id of ['jb-noflag','jb-nocred','cd-noflag','cd-nocred']){ const v=localStorage.getItem(id); if(v!==null) document.getElementById(id).checked=v==='1'; } }catch(e){}
switchTab(location.hash ? location.hash.slice(1) : 'home');
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
        conn.execute(text("ALTER TABLE discussion_comments ADD COLUMN IF NOT EXISTS parent_id INTEGER"))
        conn.execute(text("ALTER TABLE discussion_posts ADD COLUMN IF NOT EXISTS title VARCHAR(100)"))
        conn.execute(text("ALTER TABLE suggestions ADD COLUMN IF NOT EXISTS image_data TEXT"))
        conn.execute(text("ALTER TABLE jongbe_picks ADD COLUMN IF NOT EXISTS ai_pick BOOLEAN DEFAULT FALSE"))
    db = SessionLocal()
    try:
        seed_reference_data(db)
    finally:
        db.close()
    def _bg() -> None:
        from backend.utils.dates import is_trading_day  # noqa: PLC0415
        from datetime import date as _date  # noqa: PLC0415
        today = _date.today()
        from datetime import datetime as _dtm  # noqa: PLC0415
        from zoneinfo import ZoneInfo as _ZI  # noqa: PLC0415
        _now = _dtm.now(_ZI("Asia/Seoul"))
        if is_trading_day(today) and (_now.hour, _now.minute) < (15, 41):
            # 장중 재시작(배포)이면 수집하지 않는다 — 장중 시세가 오늘 종가 행으로 들어가 15:41 수집을 막았다 (2026-10-06)
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).info("장중 재시작 — startup 파이프라인 스킵 (15:41 정규 수집에 맡김)")
            return
        if not is_trading_day(today):
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).info("오늘(%s)은 거래일이 아니므로 startup 파이프라인 스킵", today)
            return
        from sqlalchemy import text as _t  # noqa: PLC0415
        _db0 = SessionLocal()
        try:      # 오늘 수집이 이미 끝났으면(장 마감 뒤 배포) 다시 돌리지 않는다 — 재시작마다 3분 넘게 무거웠다 (2026-10-06)
            done = _db0.execute(_t("select count(*) from spot_investor_flows where trading_date = :d and "
                                   "(foreign_net_buy <> 0 or institution_net_buy <> 0)"), {"d": today}).scalar() or 0
        finally:
            _db0.close()
        if done:
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).info("오늘 수집 이미 끝남 — startup 파이프라인 스킵")
            return
        _db = SessionLocal()
        try:
            run_daily_pipeline(_db)
        finally:
            _db.close()
    def _warm_journal() -> None:
        _db = SessionLocal()
        try:
            from backend.api.routes import warm_caches  # noqa: PLC0415
            warm_caches(_db)                 # 첫 화면(오늘)·차트 후보를 재시작 직후 바로 데움
            from backend.services import trade_journal  # noqa: PLC0415
            trade_journal.warm(_db)
        except Exception as exc:  # noqa: BLE001
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).warning("매매 일지 미리 계산 실패: %s", exc)
        finally:
            _db.close()
    import os  # noqa: PLC0415
    if os.environ.get("NO_SCHEDULER"):        # 화면 시험용 서버(:8011 등) — 수집·예약 작업(텔레그램 확인·알림)을 돌리지 않는다 (2026-10-10)
        return
    threading.Thread(target=_warm_journal, daemon=True).start()
    threading.Thread(target=_bg, daemon=True).start()
    start_scheduler()

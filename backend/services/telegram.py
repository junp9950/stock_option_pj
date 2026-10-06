"""텔레그램 봇 알림 (2026-10-05). 토큰은 .env TELEGRAM_BOT_TOKEN 에만 둔다 — 코드·로그에 쓰지 않는다.

- 봇에 /start 를 보낸 대화방이 알림을 받는다 (settings 'telegram_chats'). /stop 으로 해제.
- 장 마감 요약: 15:41 수집이 끝나면 종베 후보(양봉·🕯 밑꼬리 도지)·🤖 Claude 선택·뜨는 섹터를 보낸다.
- 가격 알림: /알림 종목 가격 → 장중(09:00~15:30) 현재가가 그 가격 이상이면 하루 한 번 알림, 15:15에 '종가 조건' 점검.
- /후보, /체크 종목, /알림목록, /알림삭제 종목, /도움
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.db.models import Setting, Stock
from backend.utils.logger import get_logger

logger = get_logger(__name__)
MAX_CHATS = 5
HELP = ("주식 레이더 봇 명령\n"
        "/후보 — 오늘 종베 후보 요약\n"
        "/체크 종목명 — 시세·섹터·경고·실적\n"
        "/알림 종목명 가격 — 현재가가 그 가격 이상이면 알림 (예: /알림 PS일렉트로닉스 9420)\n"
        "/알림목록 · /알림삭제 종목명\n"
        "/관심 — 관심 종목 점검 지금 받기 (평일 15:40 자동)\n"
        "/종베 종목 가격 [메모] — 오늘 종베 기록 (여러 줄 가능) · /종베목록 · /종베삭제 종목 · /채점\n"
        "종목토론 알림에 '답장' — 그 글에 댓글(댓글 알림이면 답글)로 달림 · /이름 우라늄 — 댓글 이름 정하기\n"
        "/board — (그룹에서) 이 방을 종목토론·건의사항 알림 전용으로 · /board_off — 해제\n"
        "/stop — 알림 끄기")


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


def _api(method: str, **params) -> dict:
    tok = _token()
    if not tok:
        return {}
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/{method}", json=params, timeout=15)
        return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("텔레그램 %s 실패: %s", method, type(exc).__name__)
        return {}


def _get(db: Session, key: str, default):
    row = db.scalar(select(Setting).where(Setting.key == key))
    try:
        return json.loads(row.value) if row else default
    except ValueError:
        return default


def _put(db: Session, key: str, value) -> None:
    row = db.scalar(select(Setting).where(Setting.key == key))
    v = json.dumps(value, ensure_ascii=False)
    if row is None:
        db.add(Setting(key=key, value=v))
    else:
        row.value = v
    db.commit()


def send(db: Session, msg: str, chat_id: int | str | None = None, html: bool = False) -> dict[str, int]:
    """보낸 대화방별 마지막 메시지 id를 돌려준다 (답장으로 댓글 달기 연결용)."""
    targets = [chat_id] if chat_id is not None else list(_get(db, "telegram_chats", {}).keys())
    extra = {"parse_mode": "HTML"} if html else {}
    sent = {}
    for c in targets:
        for i in range(0, len(msg), 3900):      # 텔레그램 한 메시지 4096자 제한 (HTML은 짧게 써서 태그가 안 잘리게)
            r = _api("sendMessage", chat_id=c, text=msg[i:i + 3900], disable_web_page_preview=True, **extra)
            mid = (r.get("result") or {}).get("message_id")
            if mid:
                sent[str(c)] = mid
    return sent


# 사이트 주소: IP로 https를 열면 인증서가 없어 안 열린다 (Caddy가 http→https로 돌림) — 인증서 있는 도메인으로 (2026-10-05)
SITE = "https://stock.20-196-212-146.sslip.io"
AUTHORS = ("우라늄", "감사하모니카")
MSGMAP_MAX = 300


ME = "감사하모니카"      # 사용자 본인 — 본인이 쓴 글·댓글은 알리지 않는다 (2026-10-05 "내꺼는 빼고 우라늄이 뭐 달았을 때만")


def notify_async(msg: str, author: str = "", ref: dict | None = None) -> None:
    """요청 처리를 늦추지 않게 별도 스레드로 보낸다 (종목토론·건의사항 새 글·댓글). 본인이 쓴 건 보내지 않는다.
    ref = {"post": 글 id, "comment": 댓글 id} 이면 그 알림에 텔레그램 '답장'으로 댓글을 달 수 있게 기억해 둔다."""
    import threading  # noqa: PLC0415
    author = (author or "").strip()
    if ref:
        msg += f"{chr(10)}↩ 이 메시지에 답장하면 {'답글' if ref.get('comment') else '댓글'}로 달립니다"

    def _run():
        from backend.db.database import SessionLocal  # noqa: PLC0415
        db = SessionLocal()
        try:
            board = _get(db, "telegram_board_chats", [])     # 게시판 알림 전용 방이 있으면 거기로만 (2026-10-06 매일 알림과 분리)
            targets = board or list(_get(db, "telegram_chats", {}).keys())
            names = _get(db, "telegram_authors", {})
            mine = set(_get(db, "telegram_chats", {}).keys())
            sent = {}
            for c in targets:
                # 방마다 그 방 사람이 쓴 글·댓글은 빼고 보냄 (/name 으로 정한 이름. 이름이 없으면 사용자 본인 방만 본인 글을 뺌) — 우라늄도 받게 (2026-10-06)
                if author and author == names.get(c, ME if c in mine else None):
                    continue
                sent.update(send(db, msg, c))
            if ref and sent:
                mm = _get(db, "telegram_msgmap", {})
                for c, mid in sent.items():
                    mm[f"{c}:{mid}"] = ref
                if len(mm) > MSGMAP_MAX:
                    mm = dict(list(mm.items())[-MSGMAP_MAX:])
                _put(db, "telegram_msgmap", mm)
        except Exception as exc:  # noqa: BLE001
            logger.warning("텔레그램 알림 실패: %s", type(exc).__name__)
        finally:
            db.close()
    if _token():
        threading.Thread(target=_run, daemon=True).start()


def _cut(s: str, n: int = 120) -> str:
    s = (s or "").strip().replace(chr(10), " ")
    return s if len(s) <= n else s[:n] + "…"


# ── 장 마감 요약 ────────────────────────────────────────────────
def jongbe_summary(db: Session) -> str:
    from backend.screener.jongbe import scan  # noqa: PLC0415
    d = scan(db)
    m = d.get("market") or {}
    lines = [f"📊 {d['trading_date']} 종베 후보", f"시장 {m.get('state', '-')} · {'종베 가능' if d.get('market_ok') else '쉬기'}"]
    fams = d.get("families") or []
    lines.append("뜨는 섹터: " + ", ".join(f"{f['family']}{' 💰' if f.get('money') else ''}" for f in fams[:3]))
    mv = d.get("movers") or []
    if mv:
        lines.append("움직이기 시작: " + ", ".join(x["family"] for x in mv[:4]))
    names = {x["code"]: x for x in d["items"]}
    ai = [names[c] for c in d.get("ai_picks", []) if c in names]
    if ai:
        lines.append("\n🤖 Claude 선택")
        for x in ai:
            lines.append(f"· {x['name']} {x['close']:,}원 ({x['change_pct']:+}%) {x.get('kind', '양봉')} · 시총 {round((x.get('market_cap') or 0) / 1e8):,}억")
    safe = [x for x in d["items"] if x["grade"] == "A" and (x.get("gap20_pct") or 0) < 20 and x["change_pct"] < 12
            and (x.get("market_cap") or 0) >= 1e11 and not any(t in ("투자경고", "투자위험") for t in x.get("flags", []))]
    doji = [x for x in safe if x.get("kind") == "밑꼬리 도지"]
    bull = [x for x in safe if x.get("kind") != "밑꼬리 도지"]
    if bull:
        lines.append(f"\nA등급 양봉 {len(bull)}개 (급등·과열·1천억 미만·경고 제외)")
        lines += [f"· {x['name']} {x['change_pct']:+}% 거래 {x['tv_x']}배 윗꼬리 {x['upper_pct']}%" for x in bull[:10]]
    if doji:
        lines.append(f"\n🕯 밑꼬리 도지 {len(doji)}개")
        lines += [f"· {x['name']} 밑꼬리 {x.get('low_wick_pct')}% · 전날 +{x.get('prev_chg')}%" for x in doji[:8]]
    lines.append("\n파는 법: 다음 날 +2% 미만 전부 정리 / 이상이면 30%·30% / 나머지 최고 종가 -15%")
    return "\n".join(lines)


def summary_pending(db: Session) -> bool:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    return (latest == datetime.now(ZoneInfo("Asia/Seoul")).date() and bool(_get(db, "telegram_chats", {}))
            and _get(db, "telegram_last_summary", "") != latest.isoformat())


def market_status(db: Session) -> dict | None:
    """시장 상태 숫자 — 전체·코스피·코스닥 전종목 평균 국면, 삼전·하닉 vs 코스닥 20일 차이, 삼하 외국인 5일 순매수 (2026-10-06)."""
    from backend.screener.market_regime import regime_series  # noqa: PLC0415
    rows = db.execute(text(
        "select p.trading_date, s.market, avg(coalesce(p.change_pct, 0)), count(*) from spot_daily_prices p join stocks s on s.code = p.stock_code "
        "where p.trading_date >= current_date - 120 and p.change_pct <> 'NaN' group by 1, 2")).all()
    if not rows:
        return None
    agg: dict = {"전체": {}, "코스피": {}, "코스닥": {}}
    for d, m, a, n in rows:
        k = "코스피" if m == "KOSPI" else "코스닥"
        agg[k][d] = float(a)
        t = agg["전체"].setdefault(d, [0.0, 0])
        t[0] += float(a) * n
        t[1] += n
    agg["전체"] = {d: v[0] / v[1] for d, v in agg["전체"].items()}
    reg = {k: regime_series(v) for k, v in agg.items()}
    last = max(reg["전체"])
    out = {"as_of": last.isoformat(), **{k: reg[k][max(reg[k])] for k in reg}}
    sh = db.execute(text("select trading_date, avg(change_pct) from spot_daily_prices where stock_code in ('005930','000660') "
                         "and trading_date >= current_date - 60 group by 1 order by 1")).all()
    q = sorted(agg["코스닥"].items())
    if len(sh) >= 21 and len(q) >= 21:
        import math  # noqa: PLC0415
        r_sh = math.prod(1 + float(v or 0) / 100 for _, v in sh[-20:]) - 1
        r_q = math.prod(1 + v / 100 for _, v in q[-20:]) - 1
        out["sh20"], out["kq20"], out["rel"] = round(r_sh * 100, 1), round(r_q * 100, 1), round((r_sh - r_q) * 100, 1)
    f = db.execute(text("select coalesce(sum(foreign_net_buy), 0) from spot_investor_flows where stock_code in ('005930','000660') and trading_date in "
                        "(select distinct trading_date from spot_investor_flows order by 1 desc limit 5)")).scalar()
    out["sh_foreign5"] = round(float(f or 0) / 1e8)
    return out


def _st(x: dict) -> str:
    icon = {"상승": "🟢", "횡보": "🟡", "하락": "🔴"}.get(x["state"], "⚪")
    return f"{icon} {x['state']} {x['vs_ma20_pct']:+.1f}%"


def status_line(st: dict) -> str:
    """매일 요약 맨 위 시장 칸 — 폰에서 줄이 중간에 잘리지 않게 한 항목에 한 줄 (2026-10-06)."""
    out = ("📊 <b>시장</b> (20일선 대비)\n"
           f"• 전체  {_st(st['전체'])}\n• 코스피  {_st(st['코스피'])}\n• 코스닥  {_st(st['코스닥'])}")
    if "rel" in st:
        r = st["rel"]
        who = ("🧲 삼하 독주 — 코스닥 비중 줄이기" if r >= 15 else "삼하 쪽으로 기우는 중" if r >= 10
               else "코스닥 우세" if r <= -3 else "비슷")
        out += (f"\n\n⚖️ <b>최근 20일</b>\n• 삼전·하닉  {st['sh20']:+.1f}%\n• 코스닥 평균  {st['kq20']:+.1f}%"
                f"\n→ <b>{who}</b>")
    return out


def regime_alert(db: Session) -> str | None:
    """시장 경고 — 바뀐 날만 보낸다 (2026-10-06 "무조건 알려줘야", "가시성 좋게").
    ① 전체·코스피·코스닥 국면 전환(하락 진입·하락 끝) ② 하락 전환 가까움(20일선 1% 안)
    ③ 삼하 흡수: 삼전·하닉 20일 수익이 코스닥 평균보다 +15%p↑ → 3년: 다음 20일 코스닥 평균 -3.81% (해제는 +10%p 아래)
    ④ 외국인이 삼하를 5일 순매수로 돌아섬(그 반대도)."""
    st = market_status(db)
    if not st:
        return None
    prev = _get(db, "market_alert_state", {}) or {}
    first = not prev
    cur = {"전체": st["전체"]["state"], "코스피": st["코스피"]["state"], "코스닥": st["코스닥"]["state"],
           "suck": prev.get("suck", False), "fsign": (st["sh_foreign5"] > 0) - (st["sh_foreign5"] < 0),
           "near": prev.get("near") if prev.get("전체") == st["전체"]["state"] else None}
    blocks = []
    LINE = "━━━━━━━━━━━━"
    for k in ("전체", "코스피", "코스닥"):
        a, b = prev.get(k), cur[k]
        if first or not a or a == b:
            continue
        x = st[k]
        if b == "하락":
            blocks.append(f"🚨🚨 <b>[시장 경고] {k} 하락 전환</b>\n{LINE}\n• {k} 전종목 평균 지수: 20일선 대비 <b>{x['vs_ma20_pct']:+.1f}%</b> · 최근 20일 {x['cum20_pct']:+.1f}%"
                          f"\n👉 <b>할 일</b>: " + ("새 진입 멈춤 · 스윙·장기 보유 정리 · 손절선 점검" if k == "전체" else f"{k} 종목 새 진입 멈춤 · {k} 스윙 정리"))
        elif a == "하락":
            blocks.append(f"✅✅ <b>[시장] {k} 하락 끝 → {b}</b>\n{LINE}\n• 20일선 대비 <b>{x['vs_ma20_pct']:+.1f}%</b>"
                          f"\n👉 <b>할 일</b>: 첫 2~3일은 뜨는 섹터의 거래 붙은 양봉만, 비중 작게 (7/23처럼 하루 만에 다시 하락한 적 있음)")
    x = st["전체"]
    if not first and x["state"] != "하락" and x["vs_ma20_pct"] <= 1.0 and not cur["near"]:
        cur["near"] = st["as_of"]
        blocks.append(f"⚠️ <b>[주의] 하락 전환 가까움</b>\n{LINE}\n• 전종목 평균 지수가 20일선 <b>{x['vs_ma20_pct']:+.1f}%</b>까지 붙음"
                      f"\n👉 <b>할 일</b>: 빠지는 종목 줍기 금지 · 새 진입은 조건 B만")
    if "rel" in st:
        if not cur["suck"] and st["rel"] >= 15:
            cur["suck"] = True
            blocks.append(f"🧲 <b>[수급 경고] 삼전·하닉이 수급 흡수 중</b>\n{LINE}\n• 20일 수익: 삼하 <b>{st['sh20']:+.1f}%</b> vs 코스닥 평균 {st['kq20']:+.1f}% (차이 <b>{st['rel']:+.1f}%p</b>)"
                          f"\n• 3년: 이 구간 뒤 20일 코스닥 평균 <b>-3.8%</b>, 삼하는 +9.5% 더 감\n👉 <b>할 일</b>: 한 달간 코스닥 종베·스윙 비중 줄이기")
        elif cur["suck"] and st["rel"] < 10:
            cur["suck"] = False
            blocks.append(f"🧲 <b>[수급] 삼하 흡수 경고 해제</b> — 차이 {st['rel']:+.1f}%p로 줄어듦")
    if not first and prev.get("fsign") is not None and cur["fsign"] != prev.get("fsign") and cur["fsign"] != 0:
        blocks.append(("💰 <b>[수급] 외국인, 삼전·하닉 5일 순매수로 전환</b>" if cur["fsign"] > 0 else "💸 <b>[수급] 외국인, 삼전·하닉 5일 순매도로 전환</b>")
                      + f"\n{LINE}\n• 최근 5일 외국인 {st['sh_foreign5']:+,}억"
                      + ("\n👉 삼하로 돈이 돌아오는 신호일 수 있음 — 코스닥 비중 점검" if cur["fsign"] > 0 else ""))
    _put(db, "market_alert_state", {**cur, "as_of": st["as_of"]})
    if not blocks:
        return None
    return "\n\n".join(blocks) + "\n\n" + status_line(st)


def us_overnight_text() -> str | None:
    """어젯밤 미국 반도체(장비 3종·SOXX·NVDA) — 한국 소부장 다음 날과 상관 0.40 (usk.py·usgap.py, 2026-10-06).
    AI 랠리 중 장비 3종 -3%↓ 밤 다음 날 한국 소부장·기판: 시초 -1.7%, 시가→종가 -0.7% 더, 종가 -2.5%(오른 날 31%)."""
    import FinanceDataReader as fdr  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415
    start = (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=10)).strftime("%Y-%m-%d")
    ch, last = {}, None
    for t in ("AMAT", "KLAC", "LRCX", "SOXX", "NVDA"):
        try:
            c = fdr.DataReader(t, start)["Close"].dropna()
            ch[t] = (float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100
            last = c.index[-1].date()
        except Exception:  # noqa: BLE001
            continue
    eq = [ch[t] for t in ("AMAT", "LRCX") if t in ch]  # KLA는 한국 소부장과 덜 맞아 평균에서 뺌 (최근 60일 0.44 vs LRCX 0.60)
    if not eq:
        return None
    e = sum(eq) / len(eq)
    lines = [f"🌙 <b>어젯밤 미국 반도체</b> ({last:%m/%d} 마감)" if last else "🌙 <b>어젯밤 미국 반도체</b>",
             f"• 장비(AMAT·램리서치) 평균 <b>{e:+.1f}%</b> (AMAT {ch.get('AMAT', 0):+.1f} · LRCX {ch.get('LRCX', 0):+.1f} · 참고 KLAC {ch.get('KLAC', 0):+.1f})",
             f"• SOXX {ch.get('SOXX', 0):+.1f}% · NVDA {ch.get('NVDA', 0):+.1f}%"]
    if e <= -3:
        lines.append("\n⚠️ <b>소부장·기판 시초 대응</b>\n이런 밤 다음 날(1.5년 43번): 시초 평균 <b>-1.7%</b>, 종가 -2.5%, 오른 날 31%"
                     "\n시초 반등을 기다리면 평균 -0.7% 더 빠졌음 → 종베 물량은 시초에 정리 쪽")
    elif e <= -1:
        lines.append("\n🟡 소부장 약세 출발 가능 (장비 -1~-3% 밤 다음 날 소부장 평균 -0.1~-1%)")
    elif e >= 3:
        lines.append("\n🟢 소부장 강세 출발 가능 (장비 +3%↑ 밤 다음 날 소부장 평균 +1.8%, 오른 날 72%) → 시초 갭이면 일부 덜기")
    elif e >= 1:
        lines.append("\n🟢 소부장 무난 (장비 +1~3% 밤 다음 날 소부장 평균 +1.2%, 오른 날 73%)")
    return "\n".join(lines)


def _yahoo_last(sym: str) -> tuple[float, float] | None:
    """야후 차트(프리·애프터 포함)에서 (마지막 가격, 전일 정규장 종가)."""
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                         params={"interval": "5m", "range": "1d", "includePrePost": "true"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15).json()["chart"]["result"][0]
        closes = [x for x in r["indicators"]["quote"][0]["close"] if x]
        prev = r["meta"].get("chartPreviousClose") or r["meta"].get("previousClose")
        return (float(closes[-1]), float(prev)) if closes and prev else None
    except Exception:  # noqa: BLE001
        return None


# 섹터별로 같이 보는 미국 종목과 경고선 (랠리 기간 검증, 전날 밤 미국 → 다음 날 한국 섹터 평균)
#  소부장·기판 ← 장비3: 상관 0.42(나스닥 영향 빼고 0.24), -3%↓ 밤 → 다음 날 -2.3%
#  광통신 ← COHR·LITE·CIEN·AAOI·GLW: 0.38(0.27, 최근 60일 0.48), -4%↓ 밤 → -1.8%, +4%↑ 밤 → +3.6%
#  전력·전선 ← GEV·BE: 0.33(0.16 — 대부분 미국 시장 전체 영향), -4%↓ 밤 → -1.5%
_PRE_GROUPS = [
    ("소부장·기판", ("AMAT", "LRCX"), -2.0),  # KLA는 덜 맞아 뺌
    ("광통신", ("COHR", "LITE", "CIEN", "AAOI", "GLW"), -3.0),
    ("전력·전선", ("GEV", "BE"), -3.0),
    ("2차전지", ("ALB", "SQM", "TSLA"), -3.0),
]
#  2차전지 ← 리튬(ALB·SQM) 0.29(0.17) · TSLA 0.31(0.11), TSLA -4%↓ 밤 → -1.4%(오른 날 33%)
#  로봇은 미국 쪽 짝이 없다 — TSLA 0.26(0.06), SYM·TER·ROK 0.24(0.04): 나스닥 선물만 보면 된다


def _premarket_held(db: Session, today: date) -> dict[str, list[str]]:
    """오늘 종베 종목을 위 섹터별로 나눈다."""
    from backend.screener.rotation import family_members  # noqa: PLC0415
    fam = family_members(db)
    optic = {r[0] for r in db.execute(text("select distinct ss.stock_code from sector_stocks ss join sectors s on s.id = ss.sector_id "
                                            "where s.sector_name like '%광통신%'")).all()}
    sets = {"소부장·기판": {c for f in ("반도체 장비·재료", "AI메모리·기판") for c in fam.get(f, [])},
            "광통신": optic, "전력·전선": set(fam.get("전력·전선", [])),
            "2차전지": set(fam.get("2차전지", []))}
    out: dict[str, list[str]] = {}
    for c, n in db.execute(text("select code, name from user_jongbe where trading_date = :d"), {"d": today}).all():
        for g, cs in sets.items():
            if c in cs:
                out.setdefault(g, []).append(n)
                break
    return out


def send_us_premarket(db: Session) -> None:
    """평일 19:00 — 오늘 산 종베가 소부장·기판/광통신/전력이면 같이 움직이는 미국 종목 프리마켓을 알려 준다.
    크게 빠지면 20:00 넥스트레이드 애프터마켓 전에 정리 판단 (2026-10-06)."""
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    if not is_trading_day(today):
        return
    held = _premarket_held(db, today)
    if not held:
        return
    ch = {}
    for t in {t for g, ts, _ in _PRE_GROUPS if g in held for t in ts} | {"SOXX", "NVDA", "NQ=F"}:
        v = _yahoo_last(t)
        if v:
            ch[t] = (v[0] / v[1] - 1) * 100
    lines = ["🌆 <b>미국 프리마켓</b> (지금, 전일 종가 대비)",
             f"• 나스닥 선물 {ch.get('NQ=F', 0):+.1f}% · SOXX {ch.get('SOXX', 0):+.1f}% · NVDA {ch.get('NVDA', 0):+.1f}%"]
    warn = []
    for g, ts, th in _PRE_GROUPS:
        if g not in held:
            continue
        got = [t for t in ts if t in ch]
        if not got:
            continue
        e = sum(ch[t] for t in got) / len(got)
        mark = "⚠️" if e <= th else "🟢" if e >= 1 else "·"
        lines.append(f"\n{mark} <b>{g}</b> 미국 평균 <b>{e:+.1f}%</b>")
        lines.append("  " + " · ".join(f"{t} {ch[t]:+.1f}" for t in got))
        lines.append(f"  오늘 종베: {', '.join(held[g])}")
        if e <= th:
            warn.append(g)
    if warn:
        lines.append(f"\n⚠️ <b>{', '.join(warn)}</b> 프리마켓부터 약함 — 이대로 마감하면 내일 갭 하락 가능"
                     "\n→ <b>20:00 넥스트레이드 애프터마켓 전</b>에 일부라도 정리 검토")
    else:
        lines.append("\n· 크게 빠진 곳 없음 — 들고 내일 규칙대로 (프리마켓은 거래가 적어 정규장에서 바뀔 수 있음)")
    send(db, "\n".join(lines), html=True)


def send_us_overnight(db: Session) -> None:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    if not is_trading_day(datetime.now(ZoneInfo("Asia/Seoul")).date()):
        return
    msg = us_overnight_text()
    if msg:
        send(db, msg, html=True)     # 매일 알림 방(사용자)에만


def send_summary_once(db: Session) -> bool:
    """오늘 데이터가 들어왔고 아직 안 보냈으면 요약을 보낸다."""
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest != datetime.now(ZoneInfo("Asia/Seoul")).date() or _get(db, "telegram_last_summary", "") == latest.isoformat():
        return False
    if not _get(db, "telegram_chats", {}):
        return False
    # 섹터 종목(2천여 개) 종가 수집이 끝나기 전이면 기다린다 (15:41 수집이 15~16분 걸림, 16:40 넘으면 그냥 보냄)
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    if (now.hour, now.minute) < (16, 40):
        done = db.execute(text("select count(*) from spot_investor_flows where trading_date = :d"), {"d": latest}).scalar() or 0
        need = db.execute(text("select count(distinct stock_code) from sector_stocks")).scalar() or 0
        if done < need * 0.9:
            return False
    try:     # 시장 국면 바뀐 날 알림 — 모든 대화방에 먼저
        ra = regime_alert(db)
        if ra:
            send(db, ra, html=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("시장 국면 알림 실패: %s", type(exc).__name__)
    send(db, jongbe_summary(db))
    _put(db, "telegram_last_summary", latest.isoformat())
    try:      # 사용자가 남긴 종베 채점 (backend/services/jongbe_check.py) — 사용자 대화방에만
        from backend.services import jongbe_check as JC  # noqa: PLC0415
        msg = JC.daily_text(db, latest)
        try:     # 최적 조건 B·내 패턴 A·내일 후보 (backend/screener/my_pattern.py)
            from backend.screener.my_pattern import text_summary  # noqa: PLC0415
            mp = text_summary(db)
            msg = (mp + "\n\n" + msg) if (mp and msg) else (mp or msg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("내 패턴 요약 실패: %s", type(exc).__name__)
        if msg:
            for c in _get(db, "user_watchlist_chats", []) or list(_get(db, "telegram_chats", {}).keys())[:1]:
                send(db, msg, c, html=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("종베 채점 실패: %s", type(exc).__name__)
    return True


# ── 가격 알림 ──────────────────────────────────────────────────
def _live_price(code: str) -> float | None:
    from backend.services.toss_client import fetch_candles  # noqa: PLC0415
    c = fetch_candles(code, "1m", 1)
    try:
        return float(c[-1]["closePrice"]) if c else None
    except (KeyError, ValueError, TypeError):
        return None


def check_alerts(db: Session, close_check: bool = False) -> None:
    watches = _get(db, "telegram_watch", [])
    if not watches:
        return
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    changed = False
    for w in watches:
        p = _live_price(w["code"])
        if p is None:
            continue
        hit = p >= w["price"]
        if close_check:
            send(db, f"⏰ 종가 점검 {w['name']}: 현재 {p:,.0f}원 · 조건 {w['price']:,}원 {'위 ✅ (종가까지 유지되면 조건 충족)' if hit else '아래'}", w["chat"])
        elif hit and w.get("sent") != today:
            send(db, f"🔔 {w['name']} {p:,.0f}원 — 조건 {w['price']:,}원 돌파 (장중, 종가 확인 필요)", w["chat"])
            w["sent"] = today
            changed = True
        time.sleep(0.2)
    if changed:
        _put(db, "telegram_watch", watches)


def _find(db: Session, q: str):
    return db.execute(select(Stock.code, Stock.name).where((Stock.code == q) | (Stock.name == q))).first() or \
        db.execute(select(Stock.code, Stock.name).where(Stock.name.like(f"%{q}%")).limit(1)).first()


def _check_text(db: Session, q: str) -> str:
    row = _find(db, q)
    if not row:
        return f"'{q}' 종목을 못 찾았습니다."
    from backend.screener.rotation import family_members  # noqa: PLC0415
    from backend.screener.support_setups import _fundamentals  # noqa: PLC0415
    from backend.services.stock_flags import get as flags_get  # noqa: PLC0415
    px = db.execute(text("select trading_date, close_price, change_pct, trading_value from spot_daily_prices where stock_code=:c "
                         "order by trading_date desc limit 21"), {"c": row.code}).all()
    lines = [f"🔎 {row.name} ({row.code})"]
    if px:
        d0 = px[0]
        avg = sum(float(x[3] or 0) for x in px[1:]) / max(len(px) - 1, 1)
        ma20 = sum(float(x[1]) for x in px[:20]) / min(len(px), 20)
        lines.append(f"{d0[0]} 종가 {d0[1]:,.0f}원 ({float(d0[2]):+.1f}%) · 거래 평소 {float(d0[3] or 0) / avg:.1f}배 · 20일선 이격 {(float(d0[1]) / ma20 - 1) * 100:+.1f}%")
    live = _live_price(row.code)
    if live:
        lines.append(f"지금 {live:,.0f}원")
    fams = [f for f, m in family_members(db).items() if row.code in m]
    lines.append("섹터: " + (", ".join(fams[:3]) or "없음"))
    f = _fundamentals().get(row.code)
    if f:
        lines.append(f"실적 {f['period']}: 영업익 {f['op_yoy'] if f['op_yoy'] is not None else '-'}% · 매출 {f['rev_yoy'] if f['rev_yoy'] is not None else '-'}% · 이익률 {f['margin'] if f['margin'] is not None else '-'}%"
                     + (" · ⚠ 적자" if f["loss"] else ""))
    fl = flags_get([row.code]).get(row.code, {}).get("flags", [])
    if fl:
        lines.append("⚠ " + ", ".join(fl))
    return "\n".join(lines)


def poll(db: Session) -> None:
    """새 메시지 처리 (30초마다)."""
    if not _token():
        return
    off = _get(db, "telegram_offset", 0)
    res = _api("getUpdates", offset=off, timeout=0)
    ups = res.get("result") or []
    if not ups:
        return
    chats = _get(db, "telegram_chats", {})
    for u in ups:
        off = max(off, u["update_id"] + 1)
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        cid, txt = str(chat.get("id", "")), (msg.get("text") or "").strip()
        if not txt:
            txt = (msg.get("caption") or "").strip()
        if not cid or (not txt and not msg.get("photo")):
            continue
        who = chat.get("first_name") or chat.get("title") or chat.get("username") or cid
        if txt.split()[0].split("@")[0] in ("/board", "/board_off") if txt else False:
            # 게시판(종목토론·건의사항) 알림 전용 방 — 그룹을 만들어 봇을 넣고 /board (그룹에선 영문 명령만 봇에 전달됨)
            board = _get(db, "telegram_board_chats", [])
            if txt.split()[0].split("@")[0] == "/board":
                if cid not in board:
                    board.append(cid)
                _put(db, "telegram_board_chats", board)
                if chat.get("type") == "private" and cid in chats:
                    # 1:1 방에서 /board = 게시판 알림만 원함 → 매일 시장·종베 알림 목록에선 뺌 (2026-10-06 우라늄이 /start 후 /board)
                    chats.pop(cid, None)
                    _put(db, "telegram_chats", chats)
                send(db, "✅ 이 방에서 종목토론·건의사항 새 글·댓글 알림을 받습니다 (매일 시장 알림은 안 옴).\n"
                         "이름을 정해 주세요: /name 우라늄 또는 /name 감사하모니카 — 본인 글은 알림에서 빠지고, 알림에 답장하면 그 이름으로 댓글이 달립니다.", cid)
                for other in chats:
                    if other != cid:
                        send(db, f"ℹ️ '{who}' 방이 게시판 알림을 받습니다. 이 방에는 매일 시장·종베 알림만 옵니다.", other)
            else:
                board = [b for b in board if b != cid]
                _put(db, "telegram_board_chats", board)
                send(db, "게시판 알림 전용을 해제했습니다." + ("" if board else " 게시판 알림은 다시 기본 대화방으로 갑니다."), cid)
            continue
        if txt.startswith("/start"):
            if cid not in chats and len(chats) >= MAX_CHATS:
                send(db, "등록 인원이 꽉 찼습니다.", cid); continue
            new = cid not in chats
            chats[cid] = who
            _put(db, "telegram_chats", chats)
            send(db, "✅ 알림 등록 완료. 장 마감 뒤 종베 후보 요약을 보내 드립니다.\n\n" + HELP, cid)
            if new:
                for other in chats:
                    if other != cid:
                        send(db, f"ℹ️ 새 대화방이 알림에 등록됐습니다: {who}", other)
            continue
        if cid not in chats and cid not in _get(db, "telegram_board_chats", []):
            send(db, "먼저 /start 를 보내 주세요.", cid); continue
        rep = msg.get("reply_to_message") or {}
        if rep and not txt.startswith("/"):
            _put(db, "telegram_offset", off)     # 실패해도 같은 답장으로 댓글이 두 번 달리지 않게 먼저 저장
            try:
                _reply_comment(db, cid, rep.get("message_id"), msg)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.warning("텔레그램 답장 댓글 실패: %s", type(exc).__name__)
                send(db, "댓글을 못 달았습니다. 사이트에서 직접 달아 주세요.", cid)
            continue
        if txt.startswith("/stop"):
            chats.pop(cid, None); _put(db, "telegram_chats", chats)
            send(db, "알림을 껐습니다. 다시 받으려면 /start", cid)
        elif txt.startswith("/이름") or txt.split()[0].split("@")[0] == "/name":
            name = txt.split(maxsplit=1)[1].strip() if " " in txt else ""
            if name not in AUTHORS:
                send(db, f"예: /이름 우라늄 (가능한 이름: {', '.join(AUTHORS)})", cid); continue
            au = _get(db, "telegram_authors", {}); au[cid] = name; _put(db, "telegram_authors", au)
            send(db, f"✅ 이 대화방에서 답장으로 다는 댓글은 '{name}' 이름으로 올라갑니다.", cid)
        elif txt.startswith("/종베목록"):
            from backend.services import jongbe_check as JC  # noqa: PLC0415
            from backend.db.models import UserJongbe  # noqa: PLC0415
            xs = list(db.scalars(select(UserJongbe).where(UserJongbe.trading_date == JC.today_kst())))
            send(db, "\n".join(f"· {x.name} {x.entry_price:,.0f}원{(' — ' + x.note) if x.note else ''}" for x in xs) or "오늘 남긴 종베가 없습니다.", cid)
        elif txt.startswith("/종베삭제"):
            from backend.services import jongbe_check as JC  # noqa: PLC0415
            q = txt.split(maxsplit=1)[1].strip() if " " in txt else ""
            send(db, f"{JC.remove(db, q)}개 지웠습니다." if q else "예: /종베삭제 가온전선", cid)
        elif txt.startswith("/채점"):
            from backend.services import jongbe_check as JC  # noqa: PLC0415
            send(db, JC.daily_text(db) or "아직 남긴 종베가 없습니다. 예: /종베 가온전선 327500", cid, html=True)
        elif txt.startswith("/종베"):
            send(db, _jongbe_add(db, txt), cid)
        elif txt.startswith("/관심"):
            from backend.services.watchlist import send_report  # noqa: PLC0415
            send_report(db, force=True, chat_id=cid)
        elif txt.startswith("/후보"):
            send(db, jongbe_summary(db), cid)
        elif txt.startswith("/체크"):
            send(db, _check_text(db, txt.split(maxsplit=1)[1].strip()) if " " in txt else "예: /체크 가온전선", cid)
        elif txt.startswith("/알림목록"):
            ws = [w for w in _get(db, "telegram_watch", []) if w["chat"] == cid]
            send(db, "\n".join(f"· {w['name']} {w['price']:,}원 이상" for w in ws) or "걸어 둔 알림이 없습니다.", cid)
        elif txt.startswith("/알림삭제"):
            q = txt.split(maxsplit=1)[1].strip() if " " in txt else ""
            ws = _get(db, "telegram_watch", [])
            keep = [w for w in ws if not (w["chat"] == cid and (w["name"] == q or w["code"] == q))]
            _put(db, "telegram_watch", keep)
            send(db, f"{len(ws) - len(keep)}개 지웠습니다.", cid)
        elif txt.startswith("/알림"):
            parts = txt.split()
            if len(parts) < 3:
                send(db, "예: /알림 PS일렉트로닉스 9420", cid); continue
            row = _find(db, " ".join(parts[1:-1]))
            try:
                price = int(parts[-1].replace(",", "").replace("원", ""))
            except ValueError:
                row = None
            if not row:
                send(db, "종목이나 가격을 못 읽었습니다. 예: /알림 PS일렉트로닉스 9420", cid); continue
            ws = [w for w in _get(db, "telegram_watch", []) if not (w["chat"] == cid and w["code"] == row.code)]
            ws.append({"chat": cid, "code": row.code, "name": row.name, "price": price, "sent": ""})
            _put(db, "telegram_watch", ws)
            send(db, f"✅ {row.name} {price:,}원 이상이면 알려 드립니다 (장중 2분마다, 15:15 종가 점검).", cid)
        else:
            send(db, HELP, cid)
    _put(db, "telegram_offset", off)


def _jongbe_add(db: Session, txt: str) -> str:
    """/종베 종목 가격 [메모] — 여러 줄이면 줄마다 한 종목. 오늘(한국 날짜) 종베로 저장."""
    from backend.services import jongbe_check as JC  # noqa: PLC0415
    body = txt[len("/종베"):].strip()
    if not body:
        return "예: /종베 가온전선 327500 신고가 근처\n여러 종목은 줄을 바꿔서:\n/종베\n가온전선 327500\n월덱스 33100"
    ok, bad = [], []
    for line in body.split(chr(10)):
        parts = line.split()
        if not parts:
            continue
        idx = next((i for i, p in enumerate(parts) if p.replace(",", "").replace("원", "").replace(".", "", 1).isdigit()), None)
        if idx is None or idx == 0:
            bad.append(line.strip()); continue
        try:
            r = JC.add(db, " ".join(parts[:idx]), float(parts[idx].replace(",", "").replace("원", "")), " ".join(parts[idx + 1:]))
            ok.append(f"{r['name']} {r['entry']:,.0f}원")
        except ValueError:
            bad.append(line.strip())
    out = []
    if ok:
        out.append(f"✅ 오늘 종베로 기록: {', '.join(ok)}{chr(10)}장 마감 데이터가 들어오면(15:45쯤) 화면 후보였는지·빠진 이유를, 다음 날 결과까지 채점해 보내 드립니다.")
    if bad:
        out.append(f"못 읽은 줄: {' / '.join(bad)} (형식: 종목명 가격)")
    return chr(10).join(out)


def _tg_photo(file_id: str) -> str | None:
    """텔레그램 사진을 받아 data URI로 (종목토론 사진 형식)."""
    import base64  # noqa: PLC0415
    info = _api("getFile", file_id=file_id).get("result") or {}
    path = info.get("file_path")
    if not path:
        return None
    try:
        r = requests.get(f"https://api.telegram.org/file/bot{_token()}/{path}", timeout=20)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("텔레그램 사진 받기 실패: %s", type(exc).__name__)
        return None
    return "data:image/jpeg;base64," + base64.b64encode(r.content).decode()


def _ref_from_text(db: Session, t: str) -> dict | None:
    """기록이 없는 알림(답장 기능 전에 보낸 것)은 알림 글에서 찾는다: 링크의 글 번호 + 댓글 알림이면 작성자·내용 앞부분."""
    import re  # noqa: PLC0415
    from backend.db.models import DiscussionComment  # noqa: PLC0415
    m = re.search(r"discussion#(\d+)", t)
    if not m:
        return None
    pid = int(m.group(1))
    lines = t.split(chr(10))
    h = re.match(r"^(?:💬 댓글|↪ 답글) — (\S+)", lines[0])
    if not h or len(lines) < 2:
        return {"post": pid}
    body = lines[1].rstrip("…").strip()
    for c in db.scalars(select(DiscussionComment).where(DiscussionComment.post_id == pid, DiscussionComment.author == h.group(1))
                        .order_by(DiscussionComment.id.desc())):
        if body in ("(사진)", "") or _cut(c.content).rstrip("…").startswith(body[:40]):
            return {"post": pid, "comment": c.id}
    return {"post": pid}


def _reply_comment(db: Session, cid: str, reply_mid, msg: dict) -> None:
    """종목토론 알림에 답장 → 그 글에 댓글(댓글 알림이었으면 그 댓글에 답글). 2026-10-05 "텔레그램에서 바로 답변"."""
    ref = _get(db, "telegram_msgmap", {}).get(f"{cid}:{reply_mid}") or _ref_from_text(db, (msg.get("reply_to_message") or {}).get("text") or "")
    if not ref:
        logger.info("텔레그램 답장 댓글: 연결된 글 없음 (chat=%s, reply_to=%s)", cid, reply_mid)
        send(db, "이 메시지에는 답장으로 댓글을 달 수 없습니다. 종목토론 새 글·댓글 알림에 답장해 주세요.", cid); return
    author = _get(db, "telegram_authors", {}).get(cid)
    if not author:
        logger.info("텔레그램 답장 댓글: 이름 없음 (chat=%s)", cid)
        send(db, "댓글 이름을 먼저 정해 주세요: /name 우라늄 또는 /name 감사하모니카", cid); return
    text_ = (msg.get("text") or msg.get("caption") or "").strip()
    images = []
    if msg.get("photo"):
        img = _tg_photo(msg["photo"][-1]["file_id"])     # 가장 큰 크기
        if img:
            images.append(img)
    from fastapi import HTTPException  # noqa: PLC0415
    from backend.api.routes import CommentIn, create_comment  # noqa: PLC0415
    try:
        create_comment(int(ref["post"]), CommentIn(author=author, content=text_[:1000], images=images,
                                                    parent_id=ref.get("comment")), db)
    except HTTPException as exc:
        logger.info("텔레그램 답장 댓글 실패 (chat=%s): %s", cid, exc.detail)
        send(db, f"댓글을 못 달았습니다: {exc.detail}", cid); return
    logger.info("텔레그램 답장 댓글 등록 (chat=%s, %s, 글 %s)", cid, author, ref["post"])
    send(db, f"✅ {'답글' if ref.get('comment') else '댓글'} 달았습니다 ({author}){chr(10)}{SITE}/discussion#{ref['post']}", cid)


def is_market_time(now: datetime | None = None) -> bool:
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (15, 30)

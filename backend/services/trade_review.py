"""매매 복기 (2026-10-14 사용자 "관리 탭에 매매 복기란 — 내가 내용 올리고 니가 피드백하는 식으로").

사장님이 날짜별로 복기 글을 쓰면, 서버에 깔린 Claude Code(claude -p, 도구 전부 끔 — 글만 씀)가
그날 실제 체결(trade_executions) · 그날 시장 판단 · 사장님 매매 원칙(기억 파일 user_jongbe_conditions·user_trading_process)을 같이 보고 피드백을 단다.
피드백이 달리면 사장님 텔레그램으로 알림. 표 trade_reviews. 사장님(junp) 로그인에서만.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
CLAUDE = "/home/junp/.local/bin/claude"
WORKDIR = Path("/home/junp/tmp_claude/review_cli")       # 프로젝트 지침·훅이 없는 빈 폴더에서 돌림
MEMORY = Path("/home/junp/.claude/projects/-home-junp-stock/memory")
_busy: set[int] = set()


def _ensure(db: Session) -> None:
    db.execute(text("""create table if not exists trade_reviews (id serial primary key, owner varchar(40) not null, review_date date not null,
        content text not null, image_data text, feedback text, feedback_status varchar(20), feedback_at timestamptz,
        created_at timestamptz default now(), updated_at timestamptz default now())"""))
    db.execute(text("alter table trade_reviews add column if not exists items jsonb"))      # 종목별 매매·근거 (2026-10-14 "종목별로 적고 그 아래 근거")
    db.commit()


def _row(r) -> dict:
    return {"id": r.id, "date": str(r.review_date), "content": r.content, "images": r.image_data, "feedback": r.feedback, "items": r.items or [],
            "status": r.feedback_status, "feedback_at": r.feedback_at.astimezone(KST).strftime("%m/%d %H:%M") if r.feedback_at else None,
            "created_at": r.created_at.astimezone(KST).strftime("%m/%d %H:%M") if r.created_at else None}


def list_reviews(db: Session, owner: str, limit: int = 30) -> list[dict]:
    _ensure(db)
    rows = db.execute(text("select * from trade_reviews where owner = :o order by review_date desc, id desc limit :n"), {"o": owner, "n": limit}).all()
    return [_row(r) for r in rows]


def day_trades(db: Session, owner: str, day: date) -> list[dict]:
    """그날 매매 일지 체결을 종목별로 (복기 칸에 자동으로 띄움)."""
    import re  # noqa: PLC0415
    rows = db.execute(text("select code, name, side, qty, price, memo from trade_executions where owner = :o and trade_date = :d order by seq"),
                      {"o": owner, "d": day}).all()
    out: dict = {}
    for code, name, side, qty, price, memo in rows:
        m = re.search(r"(\d\d:\d\d)", memo or "")
        g = out.setdefault(code, {"code": code, "name": name, "trades": []})
        g["trades"].append({"side": side, "qty": int(qty), "price": float(price), "time": m.group(1) if m and "주문 08:50" not in (memo or "") else ("장중" if "장중" in (memo or "") else ""),
                            "auto": "자동 손절" in (memo or "")})
    return list(out.values())


def _items_text(items: list[dict]) -> str:
    lines = []
    for it in items or []:
        tr = " / ".join(f"{t['side']} {t['qty']}주 {t['price']:,.0f}" + (f"({t['time']})" if t.get("time") else "") + (" · 자동 손절" if t.get("auto") else "")
                        for t in it.get("trades") or [])
        lines.append(f"■ {it.get('name')} — {tr}\n  근거: {(it.get('reason') or '').strip() or '(안 적음)'}")
    return "\n".join(lines)


def save(db: Session, owner: str, day: date, content: str, image_data: str | None, rid: int | None = None, items: list | None = None) -> dict:
    import json  # noqa: PLC0415
    _ensure(db)
    it = json.dumps(items or [], ensure_ascii=False)
    if rid:
        r = db.execute(text("""update trade_reviews set review_date = :d, content = :c, image_data = coalesce(:i, image_data), items = cast(:it as jsonb), updated_at = now(),
            feedback_status = 'waiting' where id = :id and owner = :o returning *"""), {"d": day, "c": content, "i": image_data, "it": it, "id": rid, "o": owner}).first()
    else:
        r = db.execute(text("""insert into trade_reviews (owner, review_date, content, image_data, items, feedback_status) values (:o, :d, :c, :i, cast(:it as jsonb), 'waiting')
            returning *"""), {"o": owner, "d": day, "c": content, "i": image_data, "it": it}).first()
    db.commit()
    if r is None:
        raise ValueError("복기를 찾을 수 없습니다")
    start_feedback(r.id)
    return _row(r)


def delete(db: Session, owner: str, rid: int) -> None:
    _ensure(db)
    db.execute(text("delete from trade_reviews where id = :id and owner = :o"), {"id": rid, "o": owner})
    db.commit()


def _context(db: Session, owner: str, day: date) -> str:
    out = []
    rows = db.execute(text("""select side, name, qty, price, memo from trade_executions where owner = :o and trade_date = :d order by seq"""),
                      {"o": owner, "d": day}).all()
    if rows:
        out.append(f"[{day} 실제 체결 (매매 일지)]")
        out += [f"- {s} {n} {q}주 @ {p:,.0f} · {m}" for s, n, q, p, m in rows]
    else:
        out.append(f"[{day} 매매 일지에 체결 없음]")
    try:
        from backend.services.stock_signals import _bull_days, _market_chg  # noqa: PLC0415
        b, m = _bull_days(db).get(day), _market_chg(db).get(day)
        if b is not None:
            out.append(f"[{day} 사이트 시장 판단] {'상승·횡보 (매매 가능)' if b else '하락 (쉬는 날)'}" + (f" · 종목 같은 무게 평균 {m:+.2f}%" if m is not None else ""))
    except Exception:  # noqa: BLE001
        pass
    for f in ("user_trading_process.md", "user_jongbe_conditions.md"):
        p = MEMORY / f
        if p.exists():
            body = p.read_text(encoding="utf-8").split("---", 2)[-1].strip()
            out.append(f"[사장님 매매 원칙 — {f.split('.')[0]}]\n{body[:3000]}")
    return "\n".join(out)


PROMPT = """너는 사장님(한국 주식 개인 투자자, 추세추종·종가 베팅·차트로 직접 고름)의 매매 복기를 읽고 피드백하는 코치다.
규칙: 한국어 존댓말. 영어 문장 금지. 짧게(종목 수 + 8줄 안). 아래 형식만.
■ 종목마다 한두 줄: 사장님이 적은 매수·매도 근거가 원칙(시장 → 뜨는 섹터 → 좋은 차트, 종가 판단, 추격 금지, 손절 지키기)에 맞는지 ✅/⚠️ 로
- ✅ 오늘 잘한 점 (1~2개)
- ⚠️ 오늘 아쉬운 점 (1~2개, 실제 체결과 근거를 대어 구체적으로)
- ▶ 다음에 할 것 (1~2개, 바로 실행할 수 있게)
근거를 안 적은 종목은 '근거 없음'이라고만 짚는다. 자동 손절로 나간 건 사장님 판단이 아니라 규칙대로 나간 것이다.
신용·레버리지·이자·담보 비율 이야기는 하지 않는다. 계좌 금액·계좌번호는 적지 않는다. 확인 안 된 숫자를 지어내지 않는다.
사장님 글과 체결 내역이 다르면 그 점을 짚는다. 사장님 원칙을 그대로 되풀이하지 말고 이번 매매에 대어 본다.

{context}

[사장님 복기 — {day} · 종목별 매매와 근거]
{items}

[사장님 전체 소감]
{content}
"""


def _feedback(rid: int) -> None:
    from backend.db.database import SessionLocal  # noqa: PLC0415
    db = SessionLocal()
    try:
        r = db.execute(text("select * from trade_reviews where id = :id"), {"id": rid}).first()
        if r is None:
            return
        db.execute(text("update trade_reviews set feedback_status = 'running' where id = :id"), {"id": rid}); db.commit()
        prompt = PROMPT.format(context=_context(db, r.owner, r.review_date), day=r.review_date, items=_items_text(r.items)[:8000] or "(종목별 기록 없음)",
                               content=(r.content or "")[:4000] or "(없음)")
        WORKDIR.mkdir(parents=True, exist_ok=True)
        p = subprocess.run([CLAUDE, "-p", prompt, "--output-format", "text", "--tools", ""], cwd=WORKDIR, capture_output=True, text=True, timeout=240)
        fb = (p.stdout or "").strip()
        ok = p.returncode == 0 and len(fb) > 20
        db.execute(text("update trade_reviews set feedback = :f, feedback_status = :s, feedback_at = now() where id = :id"),
                   {"f": fb if ok else f"피드백을 만들지 못했습니다 ({(p.stderr or '').strip()[:200] or p.returncode})", "s": "done" if ok else "failed", "id": rid})
        db.commit()
        if ok:
            try:
                from backend.services.telegram import SITE, owner_chats, send  # noqa: PLC0415
                for c in owner_chats(db):
                    send(db, f"📝 매매 복기 피드백 ({r.review_date})\n{fb[:1500]}\n{SITE}/#journal", c)
            except Exception as exc:  # noqa: BLE001
                logger.warning("복기 피드백 알림 실패: %s", type(exc).__name__)
    except Exception as exc:  # noqa: BLE001
        logger.error("복기 피드백 실패 %s: %s", rid, exc)
        try:
            db.rollback()
            db.execute(text("update trade_reviews set feedback_status = 'failed', feedback = :f where id = :id"), {"f": f"피드백 오류: {type(exc).__name__}", "id": rid})
            db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        _busy.discard(rid)
        db.close()


def start_feedback(rid: int) -> bool:
    if rid in _busy:
        return False
    _busy.add(rid)
    threading.Thread(target=_feedback, args=(rid,), daemon=True).start()
    return True

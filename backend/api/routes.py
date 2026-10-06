from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.api.schemas import HealthResponse, JobResponse, MarketSignalResponse, RecommendationItem, RecommendationResponse, SectorFlowItem, SectorItem, SectorStockItem
from backend.collector.backfill import run_backfill as run_data_backfill
from backend.db.database import get_db
from backend.db.models import DiscussionComment, DiscussionPost, Suggestion, JobLog, MarketSignal, MarketSignalDetail, Recommendation, Sector, SectorFlowDaily, SectorStock, Setting, ShortSellingDaily, SpotDailyPrice, SpotInvestorFlow, Stock, StockSignal, StockSignalDetail
from backend.db.seed import refresh_universe
from backend.services.daily_pipeline import run_backfill_pipeline, run_daily_pipeline
from backend.services.toss_client import fetch_candles
from backend.services.quant_strategy import read_snapshot
from backend.services.earnings_screen import read_snapshot as read_earnings_snapshot
from backend.utils.dates import latest_trading_day


def _latest_data_date(db: Session, requested: date | None = None) -> date:
    """실제 수급 데이터가 있는 가장 최근 거래일.
    오늘 수급이 아직 없거나 전부 0이면 이전 유효일을 반환.
    requested가 명시되면 그대로 반환.
    """
    if requested is not None:
        return requested
    # 실수급이 있는 가장 최근 날짜를 DB에서 직접 조회 (calendar 불필요)
    last = db.scalar(
        select(func.max(SpotInvestorFlow.trading_date)).where(
            (SpotInvestorFlow.foreign_net_buy != 0) | (SpotInvestorFlow.institution_net_buy != 0)
        )
    )
    return last if last else latest_trading_day()


def _count_consecutive(flows: list, check) -> int:
    """flows는 최신 순으로 정렬된 SpotInvestorFlow 리스트.
    외국인/기관 수급이 둘 다 0인 날(주말·공휴일)은 건너뜀.
    """
    count = 0
    for f in flows:
        if f.foreign_net_buy == 0 and f.institution_net_buy == 0:
            continue  # 주말/공휴일 스킵
        if check(f):
            count += 1
        else:
            break
    return count


def _flow_ratio(flows: list, check, window: int = 10) -> str:
    """최근 window 영업일 중 check 조건 충족 일수 반환. 예: '7/10'"""
    real = [f for f in flows if not (f.foreign_net_buy == 0 and f.institution_net_buy == 0)]
    real = real[:window]
    if not real:
        return "0/0"
    hit = sum(1 for f in real if check(f))
    return f"{hit}/{len(real)}"


def _build_tags(
    inst: float,
    foreign: float,
    indiv: float,
    co_days: int,
    inst_days: int,
    foreign_days: int,
    short_squeeze_score: float = 0.0,
    stealth_score: float = 0.0,
) -> list[str]:
    tags: list[str] = []
    if short_squeeze_score >= 1.5:
        tags.append("숏스퀴즈 강")
    elif short_squeeze_score >= 0.8:
        tags.append("숏스퀴즈")
    if stealth_score >= 1.5:
        tags.append("스텔스축적 강")
    elif stealth_score >= 1.0:
        tags.append("스텔스축적")
    if inst > 0 and foreign > 0:
        tags.append("기관+외국인 동시매수")
    if abs(inst) >= 5_000_000_000 or abs(foreign) >= 10_000_000_000:
        tags.append("대규모 매집")
    if indiv < 0:
        tags.append("개인 매도 중")
    return tags


router = APIRouter()


@router.get('/screener/quant10')
def get_quant10():
    return read_snapshot()


@router.get('/screener/earnings')
def get_earnings_screen():
    return read_earnings_snapshot()


# ── 종목토론 ──────────────────────────────────────────────
MAX_IMAGE_CHARS = 3_000_000  # base64 문자열 기준 대략 2.2MB 원본 이미지까지 허용 (한 장당)
MAX_IMAGES = 20              # 글 하나당 사진 수 (2026-10-05 10→20, 종목 여러 개 정리 글용)
MAX_COMMENT_IMAGES = 5       # 댓글 하나당 사진 수


DISCUSSION_AUTHORS = ("우라늄", "감사하모니카")   # 작성자는 이 둘 중 하나만


def _check_author(author: str) -> str:
    author = (author or "").strip()
    if author not in DISCUSSION_AUTHORS:
        raise HTTPException(status_code=400, detail="작성자를 선택해 주세요.")
    return author


class DiscussionIn(BaseModel):
    author: str = Field("", max_length=40)
    title: str = Field("", max_length=100)
    content: str = Field("", max_length=5000)
    stock_code: str | None = Field(None, max_length=20)
    stock_name: str | None = Field(None, max_length=100)
    image_data: str | None = None          # 예전 화면 호환용 (한 장)
    images: list[str] | None = None         # 여러 장


class DiscussionEdit(BaseModel):
    title: str | None = Field(None, max_length=100)
    content: str | None = Field(None, max_length=5000)
    stock_code: str | None = Field(None, max_length=20)
    stock_name: str | None = Field(None, max_length=100)
    images: list[str] | None = None         # 주면 통째로 교체


class CommentIn(BaseModel):
    author: str = Field("", max_length=40)
    content: str = Field("", max_length=1000)
    images: list[str] | None = None
    parent_id: int | None = None      # 대댓글


class CommentEdit(BaseModel):
    content: str | None = Field(None, max_length=1000)
    images: list[str] | None = None


def _decode_images(raw: str | None) -> list[str]:
    """image_data 칸: 사진 한 장(data URI) 또는 여러 장(JSON 배열 문자열)."""
    if not raw:
        return []
    if raw.startswith("["):
        try:
            return [v for v in json.loads(raw) if isinstance(v, str)]
        except ValueError:
            return []
    return [raw]


def _encode_images(images: list[str]) -> str | None:
    if not images:
        return None
    return images[0] if len(images) == 1 else json.dumps(images)


def _check_images(images: list[str], limit: int) -> list[str]:
    images = [v for v in images if v]
    if len(images) > limit:
        raise HTTPException(status_code=400, detail=f"사진은 최대 {limit}장까지 올릴 수 있습니다.")
    for img in images:
        if not img.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="이미지 형식이 올바르지 않습니다.")
        if len(img) > MAX_IMAGE_CHARS:
            raise HTTPException(status_code=400, detail="이미지가 너무 큽니다 (한 장당 최대 약 2MB).")
    return images


def _edited(x) -> bool:
    return bool(x.updated_at and x.created_at and (x.updated_at - x.created_at).total_seconds() > 2)


def _comment_dict(c: DiscussionComment) -> dict:
    return {"id": c.id, "post_id": c.post_id, "author": c.author, "content": c.content,
            "images": _decode_images(c.image_data), "edited": _edited(c), "parent_id": c.parent_id,
            "created_at": c.created_at.isoformat() + "Z"}


def _discussion_dict(x: DiscussionPost, comments: list[DiscussionComment] | None = None) -> dict:
    images = _decode_images(x.image_data)
    return {
        "id": x.id, "author": x.author, "title": x.title or "", "content": x.content,
        "stock_code": x.stock_code, "stock_name": x.stock_name,
        "images": images, "image_data": images[0] if images else None, "edited": _edited(x),
        "created_at": x.created_at.isoformat() + "Z",
        "comments": [_comment_dict(c) for c in (comments or [])],
    }


@router.get('/discussion')
def list_discussion(stock_code: str | None = None, db: Session = Depends(get_db)):
    q = select(DiscussionPost).order_by(DiscussionPost.id.desc())
    if stock_code:
        q = q.where(DiscussionPost.stock_code == stock_code)
    posts = list(db.scalars(q.limit(300)))
    ids = [p.id for p in posts]
    comments_by_post: dict[int, list[DiscussionComment]] = defaultdict(list)
    if ids:
        for c in db.scalars(select(DiscussionComment).where(DiscussionComment.post_id.in_(ids)).order_by(DiscussionComment.id)):
            comments_by_post[c.post_id].append(c)
    return [_discussion_dict(p, comments_by_post.get(p.id, [])) for p in posts]


def _image_count_sql(col):
    """image_data 칸의 사진 수를 DB에서 센다 (사진 본문을 내려받지 않으려고). 한 장 = data URI, 여러 장 = JSON 배열."""
    n = (func.length(col) - func.length(func.replace(col, 'data:image', ''))) / 10
    return func.coalesce(n, 0)


@router.get('/discussion/board')
def discussion_board(db: Session = Depends(get_db)):
    """게시판 목록: 제목(본문 첫 줄)·댓글 수·사진 수만. 사진과 본문 전체는 글을 열 때 받는다."""
    n_comments = dict(db.execute(select(DiscussionComment.post_id, func.count()).group_by(DiscussionComment.post_id)).all())
    rows = db.execute(
        select(DiscussionPost.id, DiscussionPost.author, DiscussionPost.stock_code, DiscussionPost.stock_name,
               DiscussionPost.title, func.substr(DiscussionPost.content, 1, 200), _image_count_sql(DiscussionPost.image_data),
               DiscussionPost.created_at, DiscussionPost.updated_at)
        .order_by(DiscussionPost.id.desc()).limit(500)
    ).all()
    out = []
    for pid, author, code, name, title, head, n_img, created, updated in rows:
        title = (title or '').strip() or next((ln.strip() for ln in (head or '').splitlines() if ln.strip()), '')
        out.append({"id": pid, "author": author, "stock_code": code, "stock_name": name,
                    "title": title[:80] or '(사진)', "images": int(n_img or 0), "comments": n_comments.get(pid, 0),
                    "edited": bool(updated and created and (updated - created).total_seconds() > 2),
                    "created_at": created.isoformat() + "Z"})
    return out


@router.get('/discussion/{pid}')
def get_discussion(pid: int, db: Session = Depends(get_db)):
    x = db.get(DiscussionPost, pid)
    if x is None:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    comments = list(db.scalars(select(DiscussionComment).where(DiscussionComment.post_id == pid).order_by(DiscussionComment.id)))
    return _discussion_dict(x, comments)


@router.post('/discussion')
def create_discussion(body: DiscussionIn, db: Session = Depends(get_db)):
    images = _check_images(body.images or ([body.image_data] if body.image_data else []), MAX_IMAGES)
    author = _check_author(body.author)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="제목을 입력해 주세요.")
    if not body.content.strip() and not images:
        raise HTTPException(status_code=400, detail="내용이나 이미지를 입력해 주세요.")
    x = DiscussionPost(
        author=author, title=body.title.strip(), content=body.content.strip(),
        stock_code=(body.stock_code or "").strip().upper() or None,
        stock_name=(body.stock_name or "").strip() or None,
        image_data=_encode_images(images),
    )
    db.add(x)
    db.commit()
    from backend.services.telegram import SITE, _cut, notify_async  # noqa: PLC0415
    notify_async(f"💬 종목토론 새 글 — {x.author or '익명'}{chr(10)}[{x.title}]{(' · ' + x.stock_name) if x.stock_name else ''}"
                 f"{(chr(10) + _cut(x.content)) if x.content else ''}{(chr(10) + '🖼 사진 ' + str(len(images)) + '장') if images else ''}"
                 f"{chr(10)}{SITE}/discussion#{x.id}", author=x.author, ref={"post": x.id})
    return _discussion_dict(x)


@router.patch('/discussion/{pid}')
def update_discussion(pid: int, body: DiscussionEdit, db: Session = Depends(get_db)):
    x = db.get(DiscussionPost, pid)
    if x is None:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    content = x.content if body.content is None else body.content.strip()
    images = _decode_images(x.image_data) if body.images is None else _check_images(body.images, MAX_IMAGES)
    if not content and not images:
        raise HTTPException(status_code=400, detail="내용이나 이미지를 입력해 주세요.")
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(status_code=400, detail="제목을 입력해 주세요.")
        x.title = body.title.strip()
    x.content, x.image_data = content, _encode_images(images)
    if body.stock_code is not None:
        x.stock_code = body.stock_code.strip().upper() or None
    if body.stock_name is not None:
        x.stock_name = body.stock_name.strip() or None
    db.commit()
    return _discussion_dict(x)


@router.delete('/discussion/{pid}')
def delete_discussion(pid: int, db: Session = Depends(get_db)):
    x = db.get(DiscussionPost, pid)
    if x is None:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    db.query(DiscussionComment).filter(DiscussionComment.post_id == pid).delete()
    db.delete(x)
    db.commit()
    return {"ok": True}


@router.post('/discussion/{pid}/comments')
def create_comment(pid: int, body: CommentIn, db: Session = Depends(get_db)):
    if db.get(DiscussionPost, pid) is None:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    images = _check_images(body.images or [], MAX_COMMENT_IMAGES)
    if not body.content.strip() and not images:
        raise HTTPException(status_code=400, detail="댓글 내용이나 사진을 입력해 주세요.")
    parent = None
    if body.parent_id:
        parent = db.get(DiscussionComment, body.parent_id)
        if parent is None or parent.post_id != pid:
            raise HTTPException(status_code=404, detail="답글을 달 댓글을 찾을 수 없습니다.")
        if parent.parent_id:          # 대댓글의 대댓글은 같은 원 댓글 밑에 (한 단계만)
            parent = db.get(DiscussionComment, parent.parent_id) or parent
    c = DiscussionComment(post_id=pid, author=_check_author(body.author), content=body.content.strip(),
                          image_data=_encode_images(images), parent_id=parent.id if parent else None)
    db.add(c)
    db.commit()
    from backend.services.telegram import SITE, _cut, notify_async  # noqa: PLC0415
    post = db.get(DiscussionPost, pid)
    head = f"↪ 답글 — {c.author or '익명'} → {parent.author or '익명'}의 댓글" if parent else f"💬 댓글 — {c.author or '익명'}"
    notify_async(f"{head} → [{post.title or '제목 없음'}]{chr(10)}{_cut(c.content) or '(사진)'}"
                 f"{(chr(10) + '🖼 사진 ' + str(len(images)) + '장') if images else ''}{chr(10)}{SITE}/discussion#{pid}", author=c.author, ref={"post": pid, "comment": c.id})
    return _comment_dict(c)


@router.patch('/discussion/comments/{cid}')
def update_comment(cid: int, body: CommentEdit, db: Session = Depends(get_db)):
    c = db.get(DiscussionComment, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
    content = c.content if body.content is None else body.content.strip()
    images = _decode_images(c.image_data) if body.images is None else _check_images(body.images, MAX_COMMENT_IMAGES)
    if not content and not images:
        raise HTTPException(status_code=400, detail="댓글 내용이나 사진을 입력해 주세요.")
    c.content, c.image_data = content, _encode_images(images)
    db.commit()
    return _comment_dict(c)


@router.delete('/discussion/comments/{cid}')
def delete_comment(cid: int, db: Session = Depends(get_db)):
    c = db.get(DiscussionComment, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
    for r in db.scalars(select(DiscussionComment).where(DiscussionComment.parent_id == c.id)):   # 달린 답글도 같이
        db.delete(r)
    db.delete(c)
    db.commit()
    return {"ok": True}


# ── 건의사항 ──────────────────────────────────────────────
SUGGESTION_STATUS = ("접수", "진행 중", "완료", "보류")


class SuggestionIn(BaseModel):
    author: str = Field("", max_length=40)
    content: str = Field(..., min_length=1, max_length=2000)
    images: list[str] | None = None


class SuggestionPatch(BaseModel):
    status: str | None = None
    reply: str | None = Field(None, max_length=2000)


def _suggestion_dict(x: Suggestion) -> dict:
    return {"id": x.id, "author": x.author, "content": x.content, "status": x.status, "reply": x.reply,
            "images": _decode_images(x.image_data),
            "created_at": x.created_at.isoformat() + "Z", "updated_at": x.updated_at.isoformat() + "Z"}


@router.get('/suggestions')
def list_suggestions(db: Session = Depends(get_db)):
    return [_suggestion_dict(x) for x in db.scalars(select(Suggestion).order_by(Suggestion.id.desc()))]


@router.post('/suggestions')
def create_suggestion(body: SuggestionIn, db: Session = Depends(get_db)):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="내용을 입력해 주세요.")
    images = _check_images(body.images or [], MAX_COMMENT_IMAGES)
    x = Suggestion(author=body.author.strip(), content=body.content.strip(), status="접수", reply="", image_data=_encode_images(images))
    db.add(x)
    db.commit()
    from backend.services.telegram import SITE, _cut, notify_async  # noqa: PLC0415
    notify_async(f"📮 건의사항 새 글 — {x.author or '이름 없음'}{chr(10)}{_cut(x.content, 200)}"
                 f"{(chr(10) + '🖼 사진 ' + str(len(images)) + '장') if images else ''}{chr(10)}{SITE}/#suggest", author=x.author)
    return _suggestion_dict(x)


@router.patch('/suggestions/{sid}')
def update_suggestion(sid: int, body: SuggestionPatch, db: Session = Depends(get_db)):
    x = db.get(Suggestion, sid)
    if x is None:
        raise HTTPException(status_code=404, detail="건의를 찾을 수 없습니다.")
    if body.status is not None:
        if body.status not in SUGGESTION_STATUS:
            raise HTTPException(status_code=400, detail="상태 값이 올바르지 않습니다.")
        x.status = body.status
    if body.reply is not None:
        x.reply = body.reply.strip()
    db.commit()
    return _suggestion_dict(x)


@router.delete('/suggestions/{sid}')
def delete_suggestion(sid: int, db: Session = Depends(get_db)):
    x = db.get(Suggestion, sid)
    if x is None:
        raise HTTPException(status_code=404, detail="건의를 찾을 수 없습니다.")
    db.delete(x)
    db.commit()
    return {"ok": True}


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/market-signal", response_model=MarketSignalResponse)
def get_market_signal(trading_date: date | None = None, db: Session = Depends(get_db)) -> MarketSignalResponse:
    target_date = trading_date or _latest_data_date(db)
    signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == target_date))
    if signal is None:
        raise HTTPException(status_code=404, detail="시장 시그널 데이터가 없습니다.")
    return MarketSignalResponse(trading_date=target_date.isoformat(), score=signal.score, signal=signal.signal)


@router.get("/market-signal/history")
def get_market_signal_history(limit: int = 10, db: Session = Depends(get_db)) -> list[MarketSignalResponse]:
    signals = list(db.scalars(select(MarketSignal).order_by(desc(MarketSignal.trading_date)).limit(limit)))
    return [
        MarketSignalResponse(trading_date=item.trading_date.isoformat(), score=item.score, signal=item.signal)
        for item in signals
    ]


@router.get("/recommendations", response_model=RecommendationResponse)
def get_recommendations(trading_date: date | None = None, db: Session = Depends(get_db)) -> RecommendationResponse:
    target_date = trading_date or _latest_data_date(db)
    items = list(
        db.scalars(
            select(Recommendation).where(Recommendation.trading_date == target_date).order_by(Recommendation.rank)
        )
    )
    # 요청 날짜 데이터 없으면 최신 날짜로 폴백
    if not items and trading_date is not None:
        target_date = _latest_data_date(db)
        items = list(
            db.scalars(
                select(Recommendation).where(Recommendation.trading_date == target_date).order_by(Recommendation.rank)
            )
        )
    if not items:
        return RecommendationResponse(trading_date=target_date.isoformat(), items=[])

    codes = [item.stock_code for item in items]

    # 시장 구분 (KOSPI/KOSDAQ)
    stocks_map = {s.code: s for s in db.scalars(select(Stock).where(Stock.code.in_(codes)))}

    # 당일 투자자별 수급
    flows_today = {
        f.stock_code: f
        for f in db.scalars(
            select(SpotInvestorFlow).where(
                SpotInvestorFlow.trading_date == target_date,
                SpotInvestorFlow.stock_code.in_(codes),
            )
        )
    }

    # 연속일 계산용: 최근 10영업일치 수급 (최신 순)
    recent_raw = list(
        db.scalars(
            select(SpotInvestorFlow)
            .where(
                SpotInvestorFlow.stock_code.in_(codes),
                SpotInvestorFlow.trading_date <= target_date,
                SpotInvestorFlow.trading_date >= target_date - timedelta(days=14),
            )
            .order_by(SpotInvestorFlow.stock_code, desc(SpotInvestorFlow.trading_date))
        )
    )
    recent_flows: dict[str, list] = defaultdict(list)
    for f in recent_raw:
        if len(recent_flows[f.stock_code]) < 10:
            recent_flows[f.stock_code].append(f)

    result_items = []
    for item in items:
        flow = flows_today.get(item.stock_code)
        stock = stocks_map.get(item.stock_code)
        inst = flow.institution_net_buy if flow else 0.0
        foreign = flow.foreign_net_buy if flow else 0.0
        indiv = flow.individual_net_buy if flow else 0.0

        hist = recent_flows[item.stock_code]
        co_days = _count_consecutive(hist, lambda f: f.institution_net_buy > 0 and f.foreign_net_buy > 0)
        inst_days = _count_consecutive(hist, lambda f: f.institution_net_buy > 0)
        foreign_days = _count_consecutive(hist, lambda f: f.foreign_net_buy > 0)
        fr = _flow_ratio(hist, lambda f: f.institution_net_buy > 0 or f.foreign_net_buy > 0)

        result_items.append(
            RecommendationItem(
                rank=item.rank,
                code=item.stock_code,
                name=item.stock_name,
                total_score=item.total_score,
                market_score=item.market_score,
                stock_score=item.stock_score,
                close_price=item.close_price,
                change_pct=item.change_pct,
                market=stock.market if stock else "KOSPI",
                institution_net_buy=inst,
                foreign_net_buy=foreign,
                individual_net_buy=indiv,
                consecutive_days=co_days,
                foreign_consecutive_days=foreign_days,
                institution_consecutive_days=inst_days,
                flow_ratio=fr,
                tags=_build_tags(inst, foreign, indiv, co_days, inst_days, foreign_days),
                earnings_score=item.earnings_score,
                earnings_max=item.earnings_max,
            )
        )

    return RecommendationResponse(trading_date=target_date.isoformat(), items=result_items)


@router.get("/screener")
def get_screener(
    trading_date: date | None = None,
    show_all: bool = False,
    db: Session = Depends(get_db),
) -> list[RecommendationItem]:
    """전체 종목 점수 스크리너 — 점수 높은 순 정렬.
    show_all=true이면 시총/거래대금 필터 무시하고 전종목 반환.
    """
    from backend.config import get_config
    target_date = trading_date or _latest_data_date(db)
    config = get_config()

    market_signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == target_date))
    market_score = market_signal.score if market_signal else 0.0

    stock_signals = list(db.scalars(select(StockSignal).where(StockSignal.trading_date == target_date)))
    # 요청 날짜에 데이터가 없으면 (파이프라인 미실행 등) 최신 날짜로 폴백
    if not stock_signals and trading_date is not None:
        target_date = _latest_data_date(db)
        market_signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == target_date))
        market_score = market_signal.score if market_signal else 0.0
        stock_signals = list(db.scalars(select(StockSignal).where(StockSignal.trading_date == target_date)))
    if not stock_signals:
        return []

    codes = [s.stock_code for s in stock_signals]

    stocks_map = {s.code: s for s in db.scalars(select(Stock).where(Stock.code.in_(codes)))}
    prices_map = {
        p.stock_code: p
        for p in db.scalars(
            select(SpotDailyPrice).where(
                SpotDailyPrice.trading_date == target_date,
                SpotDailyPrice.stock_code.in_(codes),
            )
        )
    }
    flows_today = {
        f.stock_code: f
        for f in db.scalars(
            select(SpotInvestorFlow).where(
                SpotInvestorFlow.trading_date == target_date,
                SpotInvestorFlow.stock_code.in_(codes),
            )
        )
    }
    # 오늘 수급이 모두 0이면 가장 최근 유효 데이터로 fallback
    all_zero = all(
        f.foreign_net_buy == 0 and f.institution_net_buy == 0
        for f in flows_today.values()
    )
    if all_zero and flows_today:
        latest_flow_date = db.scalar(
            select(func.max(SpotInvestorFlow.trading_date)).where(
                SpotInvestorFlow.trading_date < target_date,
                SpotInvestorFlow.stock_code.in_(codes),
                (SpotInvestorFlow.foreign_net_buy != 0) | (SpotInvestorFlow.institution_net_buy != 0),
            )
        )
        if latest_flow_date:
            flows_map = {
                f.stock_code: f
                for f in db.scalars(
                    select(SpotInvestorFlow).where(
                        SpotInvestorFlow.trading_date == latest_flow_date,
                        SpotInvestorFlow.stock_code.in_(codes),
                    )
                )
            }
        else:
            flows_map = flows_today
    else:
        flows_map = flows_today
    shorts_map = {
        s.stock_code: s
        for s in db.scalars(
            select(ShortSellingDaily).where(
                ShortSellingDaily.trading_date == target_date,
                ShortSellingDaily.stock_code.in_(codes),
            )
        )
    }
    # 시그널 상세에서 ma_position, rsi_14, volume_surge 및 confluence 추출
    signal_details_raw = list(db.scalars(
        select(StockSignalDetail).where(
            StockSignalDetail.trading_date == target_date,
            StockSignalDetail.stock_code.in_(codes),
            StockSignalDetail.is_enabled.is_(True),
        )
    ))
    ma_scores: dict[str, float] = {}
    rsi_values: dict[str, float | None] = {}
    volume_surges: dict[str, float] = {}
    confluence_counts: dict[str, int] = {}
    short_squeeze_scores: dict[str, float] = {}
    stealth_scores: dict[str, float] = {}
    for d in signal_details_raw:
        if d.key == "ma_position":
            ma_scores[d.stock_code] = d.normalized_score
        elif d.key == "rsi_14":
            rsi_values[d.stock_code] = d.raw_value
        elif d.key == "volume_surge":
            volume_surges[d.stock_code] = d.raw_value if d.raw_value is not None else 1.0
        elif d.key == "short_squeeze":
            short_squeeze_scores[d.stock_code] = d.normalized_score
        elif d.key == "stealth_accumulation":
            stealth_scores[d.stock_code] = d.normalized_score
        # Count positive signals for confluence
        if d.normalized_score > 0:
            confluence_counts[d.stock_code] = confluence_counts.get(d.stock_code, 0) + 1

    recent_raw = list(
        db.scalars(
            select(SpotInvestorFlow)
            .where(
                SpotInvestorFlow.stock_code.in_(codes),
                SpotInvestorFlow.trading_date <= target_date,
                SpotInvestorFlow.trading_date >= target_date - timedelta(days=14),
            )
            .order_by(SpotInvestorFlow.stock_code, desc(SpotInvestorFlow.trading_date))
        )
    )
    recent_flows: dict[str, list] = defaultdict(list)
    for f in recent_raw:
        if len(recent_flows[f.stock_code]) < 10:
            recent_flows[f.stock_code].append(f)

    ranked: list[RecommendationItem] = []
    for ss in stock_signals:
        stock = stocks_map.get(ss.stock_code)
        price = prices_map.get(ss.stock_code)
        if stock is None or price is None:
            continue
        if not show_all and (stock.market_cap < config.min_market_cap or price.trading_value < config.min_trading_value):
            continue

        flow = flows_map.get(ss.stock_code)
        short = shorts_map.get(ss.stock_code)
        inst = flow.institution_net_buy if flow else 0.0
        foreign = flow.foreign_net_buy if flow else 0.0
        indiv = flow.individual_net_buy if flow else 0.0

        hist = recent_flows[ss.stock_code]
        co_days = _count_consecutive(hist, lambda f: f.institution_net_buy > 0 and f.foreign_net_buy > 0)
        inst_days = _count_consecutive(hist, lambda f: f.institution_net_buy > 0)
        foreign_days = _count_consecutive(hist, lambda f: f.foreign_net_buy > 0)
        fr = _flow_ratio(hist, lambda f: f.institution_net_buy > 0 or f.foreign_net_buy > 0)

        total_score = round(market_score * config.score_market_weight + ss.score * config.score_stock_weight, 2)
        ranked.append(
            RecommendationItem(
                rank=0,
                code=ss.stock_code,
                name=stock.name,
                total_score=total_score,
                market_score=market_score,
                stock_score=ss.score,
                close_price=price.close_price,
                change_pct=price.change_pct,
                market=stock.market,
                institution_net_buy=inst,
                foreign_net_buy=foreign,
                individual_net_buy=indiv,
                consecutive_days=co_days,
                foreign_consecutive_days=foreign_days,
                institution_consecutive_days=inst_days,
                flow_ratio=fr,
                tags=_build_tags(inst, foreign, indiv, co_days, inst_days, foreign_days,
                                 short_squeeze_score=short_squeeze_scores.get(ss.stock_code, 0.0),
                                 stealth_score=stealth_scores.get(ss.stock_code, 0.0)),
                short_ratio=short.short_ratio if short else 0.0,
                ma_score=ma_scores.get(ss.stock_code, 0.0),
                rsi_14=rsi_values.get(ss.stock_code),
                volume_surge=volume_surges.get(ss.stock_code, 1.0),
                market_cap=stock.market_cap or 0.0,
                signal_confluence=confluence_counts.get(ss.stock_code, 0),
            )
        )

    ranked.sort(key=lambda x: x.total_score, reverse=True)
    for i, item in enumerate(ranked, start=1):
        item.rank = i
    return ranked


@router.get("/recommendations/history")
def get_recommendation_history(db: Session = Depends(get_db)) -> list[RecommendationResponse]:
    dates = list({item.trading_date for item in db.scalars(select(Recommendation).order_by(desc(Recommendation.trading_date))).all()})
    responses: list[RecommendationResponse] = []
    for item_date in dates[:5]:
        items = list(db.scalars(select(Recommendation).where(Recommendation.trading_date == item_date).order_by(Recommendation.rank)))
        responses.append(
            RecommendationResponse(
                trading_date=item_date.isoformat(),
                items=[
                    RecommendationItem(
                        rank=item.rank,
                        code=item.stock_code,
                        name=item.stock_name,
                        total_score=item.total_score,
                        market_score=item.market_score,
                        stock_score=item.stock_score,
                        close_price=item.close_price,
                        change_pct=item.change_pct,
                    )
                    for item in items
                ],
            )
        )
    return responses


@router.get("/stock/{code}/history")
def get_stock_signal_history(code: str, limit: int = 10, db: Session = Depends(get_db)):
    """종목 시그널 점수 이력 (최근 N일)."""
    signals = list(db.scalars(
        select(StockSignal)
        .where(StockSignal.stock_code == code)
        .order_by(desc(StockSignal.trading_date))
        .limit(limit)
    ))
    stock = db.scalar(select(Stock).where(Stock.code == code))
    return {
        "code": code,
        "name": stock.name if stock else code,
        "history": [
            {"date": s.trading_date.isoformat(), "score": s.score}
            for s in reversed(signals)
        ],
    }


@router.get("/stock/{code}/flow-history")
def get_stock_flow_history(code: str, days: int = 20, db: Session = Depends(get_db)):
    """종목 일별 수급·가격 히스토리 (최근 N영업일)."""
    flows = list(db.scalars(
        select(SpotInvestorFlow)
        .where(SpotInvestorFlow.stock_code == code)
        .order_by(desc(SpotInvestorFlow.trading_date))
        .limit(days)
    ))
    prices = {
        p.trading_date: p for p in db.scalars(
            select(SpotDailyPrice)
            .where(SpotDailyPrice.stock_code == code)
            .order_by(desc(SpotDailyPrice.trading_date))
            .limit(days)
        )
    }
    result = []
    for f in reversed(flows):
        p = prices.get(f.trading_date)
        result.append({
            "date": f.trading_date.isoformat(),
            "foreign_net": f.foreign_net_buy,
            "institution_net": f.institution_net_buy,
            "close_price": p.close_price if p else None,
            "change_pct": p.change_pct if p else None,
            "volume": p.volume if p else None,
        })
    return result


@router.get("/stock/{code}/signals")
def get_stock_signal_details(code: str, trading_date: date | None = None, db: Session = Depends(get_db)):
    target_date = trading_date or _latest_data_date(db)
    details = list(
        db.scalars(
            select(StockSignalDetail).where(
                StockSignalDetail.trading_date == target_date,
                StockSignalDetail.stock_code == code,
            )
        )
    )
    if not details:
        raise HTTPException(status_code=404, detail="종목 시그널 상세 데이터가 없습니다.")
    return [
        {
            "key": item.key,
            "raw_value": item.raw_value,
            "normalized_score": item.normalized_score,
            "interpretation": item.interpretation,
            "is_enabled": item.is_enabled,
            "note": item.note,
        }
        for item in details
    ]


@router.get("/data-sources")
def get_data_sources(db: Session = Depends(get_db)):
    """각 데이터 항목의 현재 소스 상태 및 최근 수집 현황을 반환한다."""
    from backend.db.models import (
        DerivativesFuturesDaily, FuturesDailyPrice, IndexDaily,
        OpenInterestDaily, ProgramTradingDaily, ShortSellingDaily, SpotDailyPrice, SpotInvestorFlow
    )
    target_date = _latest_data_date(db)

    # 최근 수집 결과를 DB에서 실제로 확인
    spot_count = db.scalar(select(func.count()).select_from(SpotDailyPrice).where(SpotDailyPrice.trading_date == target_date)) or 0
    flow_count = db.scalar(select(func.count()).select_from(SpotInvestorFlow).where(
        SpotInvestorFlow.trading_date == target_date, SpotInvestorFlow.foreign_net_buy != 0
    )) or 0
    short_row = db.scalar(select(ShortSellingDaily).where(ShortSellingDaily.trading_date == target_date))
    idx_row = db.scalar(select(IndexDaily).where(IndexDaily.trading_date == target_date))
    futures_row = db.scalar(select(DerivativesFuturesDaily).where(DerivativesFuturesDaily.trading_date == target_date))
    program_row = db.scalar(select(ProgramTradingDaily).where(ProgramTradingDaily.trading_date == target_date))
    oi_row = db.scalar(select(OpenInterestDaily).where(OpenInterestDaily.trading_date == target_date))
    fp_row = db.scalar(select(FuturesDailyPrice).where(FuturesDailyPrice.trading_date == target_date))

    def _status(condition: bool, real_label: str = "real") -> str:
        return real_label if condition else "fallback"

    return {
        "spot_price": {"source": "FinanceDataReader", "status": _status(spot_count > 0), "note": f"오늘 {spot_count}종목 수집"},
        "investor_flow": {"source": "KIS API", "status": _status(flow_count > 0, "real_with_fallback"), "note": f"외국인/기관 비제로 {flow_count}종목 (0이면 KIS 실패)"},
        "short_selling": {"source": "KIS API", "status": "real_with_fallback", "note": f"공매도 데이터 {'수집됨' if short_row else '없음'}"},
        "kospi200_index": {"source": "FinanceDataReader/^KS200", "status": _status(idx_row is not None), "note": f"종가: {idx_row.close_price:.2f}" if idx_row else "없음"},
        "futures_investor_flow": {"source": "없음 (0)", "status": _status(futures_row is not None and futures_row.foreign_net_contracts != 0, "real_with_fallback"), "note": f"외국인 선물: {futures_row.foreign_net_contracts:.0f}계약" if futures_row else "없음"},
        "program_trading": {"source": "KIS API", "status": _status(program_row is not None and (program_row.non_arbitrage_net_buy != 0 or program_row.arbitrage_net_buy != 0), "real_with_fallback"), "note": f"비차익 {program_row.non_arbitrage_net_buy/1e8:.0f}억" if program_row else "없음"},
        "open_interest": {"source": "없음 (0)", "status": _status(oi_row is not None and (oi_row.call_oi > 0 or oi_row.put_oi > 0), "real_with_fallback"), "note": f"콜OI={oi_row.call_oi:.0f} 풋OI={oi_row.put_oi:.0f}" if oi_row else "없음"},
        "kospi200_futures_price": {"source": "KS200 지수로 대신", "status": _status(fp_row is not None, "real_with_fallback"), "note": f"종가: {fp_row.close_price:.2f}" if fp_row else "없음"},
    }


@router.get("/derivatives/overview")
def get_derivatives_overview(trading_date: date | None = None, db: Session = Depends(get_db)):
    target_date = trading_date or _latest_data_date(db)
    signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == target_date))
    return {"trading_date": target_date.isoformat(), "market_signal": signal.signal if signal else "중립", "score": signal.score if signal else 0.0}


@router.get("/recommendations/performance")
def get_recommendation_performance(days: int = 30, db: Session = Depends(get_db)):
    """과거 T+1 추천 종목의 실제 성과.
    추천일 종가 → 다음 거래일 종가 수익률 계산.
    """
    from_date = date.today() - timedelta(days=days)
    recs = list(db.scalars(
        select(Recommendation)
        .where(Recommendation.trading_date >= from_date)
        .order_by(desc(Recommendation.trading_date), Recommendation.rank)
    ))

    results = []
    for rec in recs:
        # 다음 거래일 가격 조회
        next_price = db.scalar(
            select(SpotDailyPrice.close_price)
            .where(
                SpotDailyPrice.stock_code == rec.stock_code,
                SpotDailyPrice.trading_date > rec.trading_date,
            )
            .order_by(SpotDailyPrice.trading_date)
            .limit(1)
        )
        if next_price and rec.close_price and rec.close_price > 0:
            ret_pct = round((next_price - rec.close_price) / rec.close_price * 100, 2)
        else:
            ret_pct = None

        results.append({
            "trading_date": rec.trading_date.isoformat(),
            "stock_code": rec.stock_code,
            "stock_name": rec.stock_name,
            "rank": rec.rank,
            "entry_price": rec.close_price,
            "next_price": next_price,
            "return_pct": ret_pct,
            "score": rec.total_score,
        })

    # 요약 통계
    valid = [r for r in results if r["return_pct"] is not None]
    summary = {}
    if valid:
        rets = [r["return_pct"] for r in valid]
        summary = {
            "total": len(valid),
            "win_count": sum(1 for r in rets if r > 0),
            "win_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
            "avg_return": round(sum(rets) / len(rets), 2),
            "best": round(max(rets), 2),
            "worst": round(min(rets), 2),
        }

    return {"summary": summary, "records": results}


@router.put("/settings/weights")
def update_settings(payload: dict[str, object], db: Session = Depends(get_db)):
    for key, value in payload.items():
        db.merge(Setting(key=key, value=json.dumps(value, ensure_ascii=True)))
    db.commit()
    return {"status": "ok"}


@router.post("/universe/refresh")
def refresh_universe_endpoint(db: Session = Depends(get_db)):
    """FDR로 유니버스를 최신 KOSPI 시총 상위 30종목으로 갱신."""
    added = refresh_universe(db)
    total = db.query(Stock).count()
    return {"status": "ok", "added": added, "total": total}


@router.post("/jobs/run-daily", response_model=JobResponse)
def run_daily_job(trading_date: date | None = None, db: Session = Depends(get_db)) -> JobResponse:
    result = run_daily_pipeline(db, trading_date)
    return JobResponse(**result)


@router.post("/jobs/backfill")
def run_backfill(start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db)):
    """start_date ~ end_date 범위 전체 파이프라인 순차 실행.
    둘 다 없으면 오늘 하루만 실행. end_date만 있으면 그날 하루만 실행.
    """
    s = start_date or latest_trading_day()
    e = end_date or s
    if s > e:
        s, e = e, s
    results = run_backfill_pipeline(db, s, e)
    return {"status": "ok", "days_processed": len(results), "results": results}


_backfill_status: dict = {"running": False, "result": None, "error": None}

@router.post("/data/backfill")
def trigger_data_backfill(start_date: date, end_date: date):
    """과거 가격·수급 데이터 일괄 백필. 백그라운드 실행 후 즉시 반환."""
    import threading
    from backend.db.database import SessionLocal

    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")
    if (end_date - start_date).days > 730:
        raise HTTPException(status_code=400, detail="최대 2년 범위까지 지원합니다")
    if _backfill_status["running"]:
        raise HTTPException(status_code=409, detail="이미 백필이 실행 중입니다")

    _backfill_status["running"] = True
    _backfill_status["result"] = None
    _backfill_status["error"] = None

    def _run():
        db = SessionLocal()
        try:
            result = run_data_backfill(db, start_date, end_date)
            _backfill_status["result"] = result
        except Exception as exc:  # noqa: BLE001
            _backfill_status["error"] = str(exc)
        finally:
            db.close()
            _backfill_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": f"{start_date} ~ {end_date} 백필 시작됨. /data/backfill/status 로 진행 확인"}


@router.get("/data/backfill/status")
def get_backfill_status():
    """백필 진행 상태 조회."""
    return {
        "running": _backfill_status["running"],
        "result": _backfill_status["result"],
        "error": _backfill_status["error"],
    }


_market_backfill_status: dict = {"running": False, "result": None, "error": None, "progress": ""}

@router.post("/data/market-signal-backfill")
def trigger_market_signal_backfill(skip_existing: bool = True):
    """DB 수급 데이터로 과거 시장 시그널 일괄 재계산."""
    import threading
    from backend.db.database import SessionLocal
    from backend.db.models import SpotInvestorFlow, MarketSignal
    from backend.signal_engine.market_signal import calculate_market_signal

    if _market_backfill_status["running"]:
        raise HTTPException(status_code=409, detail="이미 실행 중")

    _market_backfill_status.update({"running": True, "result": None, "error": None, "progress": "시작 중..."})

    def _run():
        db = SessionLocal()
        try:
            flow_dates = sorted(set(
                row[0] for row in db.execute(select(SpotInvestorFlow.trading_date).distinct())
            ))
            signal_dates = set(
                row[0] for row in db.execute(select(MarketSignal.trading_date).distinct())
            )
            targets = [d for d in flow_dates if not skip_existing or d not in signal_dates]
            total = len(targets)
            done = 0
            errors = []
            _market_backfill_status["progress"] = f"0 / {total} 일 완료"
            for d in targets:
                fresh = SessionLocal()
                try:
                    calculate_market_signal(fresh, d)
                    done += 1
                    if done % 20 == 0 or done == total:
                        _market_backfill_status["progress"] = f"{done} / {total} 일 완료"
                except Exception as exc:
                    errors.append(f"{d}: {exc}")
                finally:
                    fresh.close()
            _market_backfill_status["result"] = {"total": total, "done": done, "errors": errors[:5]}
        except Exception as exc:
            _market_backfill_status["error"] = str(exc)
        finally:
            db.close()
            _market_backfill_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


@router.get("/data/market-signal-backfill/status")
def get_market_signal_backfill_status():
    return _market_backfill_status


_signal_backfill_status: dict = {"running": False, "result": None, "error": None, "progress": ""}

@router.post("/data/signal-backfill")
def trigger_signal_backfill(skip_existing: bool = True):
    """DB 가격+수급 데이터로 과거 시그널 점수 일괄 재계산. 백그라운드 실행."""
    import threading
    from backend.db.database import SessionLocal
    from backend.db.models import SpotDailyPrice, StockSignal
    from backend.signal_engine.stock_signal import calculate_stock_signals
    from backend.utils.dates import is_trading_day

    if _signal_backfill_status["running"]:
        raise HTTPException(status_code=409, detail="이미 시그널 재계산이 실행 중입니다")

    _signal_backfill_status["running"] = True
    _signal_backfill_status["result"] = None
    _signal_backfill_status["error"] = None
    _signal_backfill_status["progress"] = "시작 중..."

    def _run():
        # 대상 날짜만 빠르게 조회 후 즉시 연결 닫기 (Supabase 장기 연결 방지)
        try:
            db = SessionLocal()
            try:
                price_dates = sorted(set(
                    row[0] for row in db.execute(select(SpotDailyPrice.trading_date).distinct())
                ))
                signal_dates = set(
                    row[0] for row in db.execute(select(StockSignal.trading_date).distinct())
                )
            finally:
                db.close()

            target_dates = [d for d in price_dates if not skip_existing or d not in signal_dates]
            total = len(target_dates)
            done = 0
            errors = []
            _signal_backfill_status["progress"] = f"0 / {total} 일 완료"

            for d in target_dates:
                fresh_db = SessionLocal()
                try:
                    calculate_stock_signals(fresh_db, d)
                    done += 1
                    _signal_backfill_status["progress"] = f"{done} / {total} 일 완료"
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{d}: {exc}")
                finally:
                    fresh_db.close()

            _signal_backfill_status["result"] = {
                "total": total,
                "done": done,
                "errors": errors[:10],
            }
        except Exception as exc:  # noqa: BLE001
            _signal_backfill_status["error"] = str(exc)
        finally:
            _signal_backfill_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": "시그널 재계산 시작. /data/signal-backfill/status 로 확인"}


@router.get("/data/signal-backfill/status")
def get_signal_backfill_status():
    return {
        "running": _signal_backfill_status["running"],
        "progress": _signal_backfill_status["progress"],
        "result": _signal_backfill_status["result"],
        "error": _signal_backfill_status["error"],
    }




@router.get("/jobs/logs")
def get_job_logs(limit: int = 50, db: Session = Depends(get_db)):
    """최근 파이프라인 실행 이력."""
    logs = list(db.scalars(select(JobLog).order_by(desc(JobLog.created_at)).limit(limit)))
    return [
        {
            "id": l.id,
            "trading_date": l.trading_date.isoformat() if l.trading_date else None,
            "stage": l.stage,
            "status": l.status,
            "message": l.message,
            "created_at": l.created_at.isoformat(),
        }
        for l in logs
    ]


@router.get("/market-signal/details")
def get_market_signal_details(trading_date: date | None = None, db: Session = Depends(get_db)):
    """시장 시그널 지표별 상세 점수."""
    target_date = trading_date or _latest_data_date(db)
    details = list(db.scalars(
        select(MarketSignalDetail).where(MarketSignalDetail.trading_date == target_date)
    ))
    return [
        {
            "key": d.key,
            "raw_value": d.raw_value,
            "normalized_score": d.normalized_score,
            "interpretation": d.interpretation,
            "is_enabled": d.is_enabled,
            "source": d.source,
            "note": d.note,
        }
        for d in details
    ]


@router.get("/screener/trending")
def get_trending_stocks(top_n: int = 10, db: Session = Depends(get_db)):
    """전일 대비 종목 점수가 가장 많이 상승한 종목 (최근 2 거래일 비교)."""
    target_date = _latest_data_date(db)
    prev_date = latest_trading_day(target_date - timedelta(days=1))

    today_signals = {s.stock_code: s.score for s in db.scalars(
        select(StockSignal).where(StockSignal.trading_date == target_date)
    )}
    prev_signals = {s.stock_code: s.score for s in db.scalars(
        select(StockSignal).where(StockSignal.trading_date == prev_date)
    )}

    common_codes = set(today_signals) & set(prev_signals)
    changes = []
    for code in common_codes:
        delta = today_signals[code] - prev_signals[code]
        if delta > 0:
            stock = db.scalar(select(Stock).where(Stock.code == code))
            changes.append({
                "code": code,
                "name": stock.name if stock else code,
                "today_score": today_signals[code],
                "prev_score": prev_signals[code],
                "delta": round(delta, 3),
            })

    changes.sort(key=lambda x: x["delta"], reverse=True)
    return changes[:top_n]


@router.get("/screener/tomorrow-picks")
def get_tomorrow_picks(top_n: int = 7, db: Session = Depends(get_db)):
    """내일 매수 후보 추천 — Recommendation 테이블 기준 (build_recommendations와 동일한 순위)."""
    target_date = _latest_data_date(db)

    recs = list(db.scalars(
        select(Recommendation)
        .where(Recommendation.trading_date == target_date)
        .order_by(Recommendation.rank)
        .limit(top_n)
    ))
    # 오늘 추천 없으면 가장 최근 추천 날짜로 폴백
    if not recs:
        from sqlalchemy import func  # noqa: PLC0415
        latest_rec_date = db.scalar(select(func.max(Recommendation.trading_date)))
        if latest_rec_date:
            recs = list(db.scalars(
                select(Recommendation)
                .where(Recommendation.trading_date == latest_rec_date)
                .order_by(Recommendation.rank)
                .limit(top_n)
            ))
    if not recs:
        return []

    codes = [r.stock_code for r in recs]

    stocks_map = {s.code: s for s in db.scalars(select(Stock).where(Stock.code.in_(codes)))}
    recent_raw = list(db.scalars(
        select(SpotInvestorFlow)
        .where(
            SpotInvestorFlow.stock_code.in_(codes),
            SpotInvestorFlow.trading_date <= target_date,
            SpotInvestorFlow.trading_date >= target_date - timedelta(days=14),
        )
        .order_by(SpotInvestorFlow.stock_code, desc(SpotInvestorFlow.trading_date))
    ))
    recent_flows: dict[str, list] = defaultdict(list)
    for f in recent_raw:
        if len(recent_flows[f.stock_code]) < 10:
            recent_flows[f.stock_code].append(f)

    picks = []
    for rec in recs:
        stock = stocks_map.get(rec.stock_code)
        hist = recent_flows.get(rec.stock_code, [])

        foreign_net = 0.0
        institution_net = 0.0
        if hist and hist[0].trading_date == target_date:
            foreign_net = float(hist[0].foreign_net_buy or 0)
            institution_net = float(hist[0].institution_net_buy or 0)

        fc = _count_consecutive(hist, lambda f: f.foreign_net_buy > 0)
        ic = _count_consecutive(hist, lambda f: f.institution_net_buy > 0)
        co = _count_consecutive(hist, lambda f: f.foreign_net_buy > 0 and f.institution_net_buy > 0)
        fr_str = _flow_ratio(hist, lambda f: f.foreign_net_buy > 0 or f.institution_net_buy > 0)

        change_pct = float(rec.change_pct or 0)
        if change_pct >= 8:
            risk = "고"
        elif change_pct >= 5:
            risk = "중"
        else:
            risk = "저"
        if fc >= 5 or co >= 3:
            if risk == "고":
                risk = "중"
            elif risk == "중":
                risk = "저"

        picks.append({
            "code": rec.stock_code,
            "name": rec.stock_name,
            "market": stock.market if stock else "KOSPI",
            "base_score": float(rec.total_score or 0),
            "t1_score": float(rec.total_score or 0),
            "close_price": float(rec.close_price or 0),
            "change_pct": change_pct,
            "foreign_consecutive_days": fc,
            "institution_consecutive_days": ic,
            "co_consecutive_days": co,
            "flow_ratio": fr_str,
            "foreign_net_buy": foreign_net,
            "institution_net_buy": institution_net,
            "both_buying": foreign_net > 0 and institution_net > 0,
            "risk": risk,
            "earnings_score": rec.earnings_score,
            "earnings_max": rec.earnings_max,
        })

    return picks


@router.get("/data-quality")
def get_data_quality(db: Session = Depends(get_db)):
    """오늘 데이터 수집 품질 요약 (실데이터 비율)."""
    from backend.db.models import (
        DerivativesFuturesDaily, IndexDaily, OpenInterestDaily,
        ProgramTradingDaily, ShortSellingDaily, SpotDailyPrice, SpotInvestorFlow, Stock
    )
    target_date = _latest_data_date(db)
    total_stocks = db.scalar(select(func.count()).select_from(Stock).where(Stock.is_active.is_(True))) or 1

    spot_count = db.scalar(select(func.count()).select_from(SpotDailyPrice).where(SpotDailyPrice.trading_date == target_date)) or 0
    flow_nonzero = db.scalar(select(func.count()).select_from(SpotInvestorFlow).where(
        SpotInvestorFlow.trading_date == target_date,
        (SpotInvestorFlow.foreign_net_buy != 0) | (SpotInvestorFlow.institution_net_buy != 0) | (SpotInvestorFlow.individual_net_buy != 0)
    )) or 0
    short_count = db.scalar(select(func.count()).select_from(ShortSellingDaily).where(ShortSellingDaily.trading_date == target_date)) or 0

    futures_row = db.scalar(select(DerivativesFuturesDaily).where(DerivativesFuturesDaily.trading_date == target_date))
    program_row = db.scalar(select(ProgramTradingDaily).where(ProgramTradingDaily.trading_date == target_date))
    oi_row = db.scalar(select(OpenInterestDaily).where(OpenInterestDaily.trading_date == target_date))
    idx_row = db.scalar(select(IndexDaily).where(IndexDaily.trading_date == target_date))

    futures_real = 1.0 if futures_row and futures_row.foreign_net_contracts != 0 else 0.0
    program_real = 1.0 if program_row and (program_row.non_arbitrage_net_buy != 0 or program_row.arbitrage_net_buy != 0) else 0.0
    oi_real = 1.0 if oi_row and (oi_row.call_oi > 0 or oi_row.put_oi > 0) else 0.0
    index_real = 1.0 if idx_row else 0.0

    checks = {
        "spot_coverage": spot_count / total_stocks,
        "flow_coverage": flow_nonzero / total_stocks,
        "short_coverage": short_count / total_stocks,
        "futures_real": futures_real,
        "program_real": program_real,
        "oi_real": oi_real,
        "index_real": index_real,
    }
    # 핵심 데이터(주가·수급·공매도) 가중 60%, 파생 보조 데이터 40%
    core_score = (checks["spot_coverage"] + checks["flow_coverage"] + checks["short_coverage"]) / 3
    deriv_score = (futures_real + program_real + oi_real + index_real) / 4
    overall = core_score * 0.6 + deriv_score * 0.4
    return {
        "trading_date": target_date.isoformat(),
        "overall_score": round(overall * 100, 1),
        "checks": checks,
    }


@router.get("/heatmap")
def get_heatmap(limit: int = 250, db: Session = Depends(get_db)):
    """시총 상위 종목의 업종별 등락률 히트맵(트리맵)용 데이터."""
    target_date = _latest_data_date(db)

    stocks = list(
        db.scalars(
            select(Stock)
            .where(Stock.is_active.is_(True), Stock.market_cap > 0)
            .order_by(desc(Stock.market_cap))
            .limit(limit)
        )
    )
    codes = [s.code for s in stocks]

    prices = {
        p.stock_code: p
        for p in db.scalars(
            select(SpotDailyPrice).where(
                SpotDailyPrice.trading_date == target_date, SpotDailyPrice.stock_code.in_(codes)
            )
        )
    }

    # 섹터는 수동 큐레이션(custom)만 있고 커버리지가 낮아, 매핑 안 된 종목은 전부 "기타"로 묶임.
    sector_map: dict[str, str] = {}
    rows = db.execute(
        select(SectorStock.stock_code, Sector.sector_name)
        .join(Sector, SectorStock.sector_id == Sector.id)
        .where(SectorStock.stock_code.in_(codes), Sector.source == "custom", Sector.is_active.is_(True))
    )
    for code, sector_name in rows:
        sector_map.setdefault(code, sector_name)

    items = []
    for s in stocks:
        price = prices.get(s.code)
        if price is None:
            continue
        items.append({
            "code": s.code,
            "name": s.name,
            "market": s.market,
            "sector": sector_map.get(s.code, "기타"),
            "market_cap": s.market_cap,
            "change_pct": float(price.change_pct or 0),
        })

    return {"trading_date": target_date.isoformat(), "items": items}


@router.get("/screener/pullback")
def get_pullback_candidates(top_n: int = 30, min_market_cap: float = 0, db: Session = Depends(get_db)):
    """장대양봉(거래량 급증+상승) 이후 지지선을 지키며 조용히 눌린(눌림목) 종목 스캔.
    거래량 급증 탐지가 1순위라 유니버스(is_active) 제한 없이 전체 종목을 스캔하며,
    min_market_cap(원 단위)은 그 다음 단계의 선택적 필터."""
    from backend.screener.radar import build_radar  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    # 전 종목(시총 0)으로 한 번만 계산해 두고, 시총 조건은 결과에 거르기만 한다 (시총마다 재계산하면 7~11초)
    base = cached("radar", (top_n,), db, lambda: build_radar(db, _latest_data_date(db), top_n=top_n, min_market_cap=0))
    if min_market_cap <= 0:
        return base
    return {**base, "items": [it for it in base["items"] if (it["market_cap"] or 0) >= min_market_cap]}


@router.get("/screener/top-value")
def get_top_value(market: str = "KOSPI", limit: int = 100, sort: str = "value", min_value: float = 0,
                  db: Session = Depends(get_db)):
    """거래대금 순위 탭: 최근 거래일 코스피/코스닥 종목 정렬.

    sort: value(거래대금) · cap(시총) · up(상승률) · down(하락률) · turnover(회전율 = 거래대금 / 시총).
    min_value: 최소 거래대금(억 원). KOSDAQ에는 KOSDAQ GLOBAL을 포함한다.
    """
    from backend.services.marcap_caps import caps as marcap_caps  # noqa: PLC0415
    market = "KOSDAQ" if market.upper().startswith("KOSDAQ") else "KOSPI"
    limit = max(1, min(limit, 300))
    latest = db.scalar(select(func.max(SpotDailyPrice.trading_date)))
    if latest is None:
        return {"trading_date": None, "market": market, "sort": sort, "items": []}
    rows = db.execute(
        select(SpotDailyPrice.stock_code, SpotDailyPrice.close_price, SpotDailyPrice.change_pct, SpotDailyPrice.volume,
               SpotDailyPrice.trading_value, Stock.name, Stock.market_cap, Stock.shares_outstanding)
        .join(Stock, Stock.code == SpotDailyPrice.stock_code)
        .where(SpotDailyPrice.trading_date == latest, Stock.market.like(f"{market}%"),
               SpotDailyPrice.trading_value > max(min_value, 0) * 1e8)
    ).all()
    caps = marcap_caps()
    items = []
    for r in rows:
        chg = r.change_pct if r.change_pct is not None and r.change_pct == r.change_pct else 0.0  # NaN 방어
        cap = r.market_cap or (r.shares_outstanding or 0) * r.close_price or caps.get(r.stock_code) or None
        tv = r.trading_value or 0
        items.append({"code": r.stock_code, "name": r.name, "close_price": r.close_price, "change_pct": round(float(chg), 2),
                      "volume": r.volume or 0, "trading_value": tv, "market_cap": cap,
                      "turnover_pct": round(tv / cap * 100, 2) if cap else None})
    keys = {"value": lambda x: -x["trading_value"], "cap": lambda x: -(x["market_cap"] or 0),
            "up": lambda x: -x["change_pct"], "down": lambda x: x["change_pct"],
            "turnover": lambda x: -(x["turnover_pct"] or 0)}
    sort = sort if sort in keys else "value"
    if sort in ("cap", "turnover"):
        items = [x for x in items if x["market_cap"]]
    items.sort(key=keys[sort])
    items = items[:limit]
    for i, x in enumerate(items, 1):
        x["rank"] = i
    return {"trading_date": latest.isoformat(), "market": market, "sort": sort, "items": items}


@router.get("/screener/jongbe")
def get_jongbe(db: Session = Depends(get_db)):
    """오늘의 종베 후보: 뜨거운 줄기 + 줄기 돈 몰림 + 거래 실린 양봉 (A/B 등급, 상한가 따로)."""
    from backend.screener.jongbe import scan  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    return cached("jongbe", (), db, lambda: scan(db))


@router.get("/screener/jongbe/check")
def get_jongbe_check(q: str = "", db: Session = Depends(get_db)):
    """보유·관심 종목(이름 또는 코드, 쉼표 구분)이 종베 단계를 통과하는지."""
    from backend.screener.jongbe import check  # noqa: PLC0415
    queries = [x for x in q.replace(chr(10), ",").split(",") if x.strip()][:30]
    return check(db, queries)


class SectorOverrideIn(BaseModel):
    stock: str = Field(..., max_length=100)     # 종목명 또는 코드
    sector: str = Field("", max_length=50)      # 빈 값이면 지정 해제


@router.post("/sectors/override")
def post_sector_override(body: SectorOverrideIn, db: Session = Depends(get_db)):
    """종목을 섹터에 직접 지정 (네이버 테마 분류에 더해진다)."""
    from backend.screener.rotation import FAMILIES, set_override  # noqa: PLC0415
    q = body.stock.strip()
    code = db.scalar(select(Stock.code).where((Stock.code == q) | (Stock.name == q)))
    if not code:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다.")
    if body.sector and body.sector not in FAMILIES:
        raise HTTPException(status_code=400, detail="없는 섹터입니다.")
    return {"code": code, "overrides": set_override(db, code, body.sector or None)}


@router.get("/screener/jongbe/performance")
def get_jongbe_performance(db: Session = Depends(get_db)):
    """저장된 종베 후보의 다음 거래일 실제 결과."""
    from backend.screener.jongbe import performance  # noqa: PLC0415
    return performance(db)


class LabelIn(BaseModel):
    owner: str = Field("", max_length=40)
    date: str = Field(..., max_length=10)
    stock: str = Field(..., max_length=100)     # 코드 또는 이름
    label: int = 1                              # 1 / -1 / 0(지우기)
    reason: str = Field("", max_length=200)
    source: str = Field("", max_length=40)
    hindsight: bool = False


@router.post("/labels")
def post_label(body: LabelIn, db: Session = Depends(get_db)):
    """차트 판단 👍/👎 또는 놓친 종목 기록."""
    from backend.db.models import ChartLabel  # noqa: PLC0415
    q = body.stock.strip()
    row = db.execute(select(Stock.code, Stock.name).where((Stock.code == q) | (Stock.name == q))).first()
    if not row:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다.")
    try:
        d = date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식이 잘못됐습니다.")
    owner = body.owner.strip()[:40]
    x = db.scalar(select(ChartLabel).where(ChartLabel.owner == owner, ChartLabel.trading_date == d, ChartLabel.code == row.code,
                                           ChartLabel.hindsight == body.hindsight))
    if body.label == 0:
        if x:
            db.delete(x)
            db.commit()
        return {"ok": True, "removed": True}
    if x is None:
        x = ChartLabel(owner=owner, trading_date=d, code=row.code, name=row.name, hindsight=body.hindsight)
        db.add(x)
    x.label, x.reason, x.source = (1 if body.label > 0 else -1), body.reason.strip(), body.source
    db.commit()
    return {"ok": True, "code": row.code, "name": row.name}


@router.get("/labels")
def get_labels(owner: str = "", day: str = "", db: Session = Depends(get_db)):
    """내 판단 기록: 전체 개수, 그날 누른 것, 최근 놓친 종목."""
    from backend.db.models import ChartLabel  # noqa: PLC0415
    rows = db.scalars(select(ChartLabel).where(ChartLabel.owner == owner)).all()
    stats = {"up": sum(1 for r in rows if r.label > 0 and not r.hindsight), "down": sum(1 for r in rows if r.label < 0 and not r.hindsight),
             "missed": sum(1 for r in rows if r.hindsight)}
    today = [{"code": r.code, "label": r.label} for r in rows if r.trading_date.isoformat() == day and not r.hindsight]
    missed = [{"date": r.trading_date.isoformat(), "name": r.name, "reason": r.reason}
              for r in sorted(rows, key=lambda r: r.trading_date, reverse=True) if r.hindsight][:10]
    return {"stats": stats, "day": today, "missed": missed}


@router.get("/stocks/short-watch")
def get_short_watch(q: str = "", db: Session = Depends(get_db)):
    """공매도·대차잔고 감시: 종목명이나 코드(쉼표, 최대 8개)."""
    from backend.services.float_ratio import get as float_get  # noqa: PLC0415
    from backend.services.short_watch import watch  # noqa: PLC0415
    out = []
    for t in [x.strip() for x in q.replace(chr(10), ",").split(",") if x.strip()][:8]:
        row = db.execute(select(Stock.code, Stock.name).where((Stock.code == t) | (Stock.name == t))).first()
        if not row:
            out.append({"query": t, "found": False}); continue
        fr = float_get([row.code]).get(row.code)
        w = watch(row.code, fr[0] if fr else None, fr[1] if fr else None)
        out.append({"query": t, "found": True, "name": row.name, "float_ratio": fr[1] if fr else None, **w})
    return {"items": out}


@router.get("/screener/support-setups")
def get_support_setups(db: Session = Depends(get_db)):
    """손절 짧은 자리: 추세선 지지(전진건설로봇형) · 수평 지지 수렴(SK이터닉스형)."""
    from backend.screener.support_setups import scan  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    return cached("support_setups", (), db, lambda: scan(db))


@router.get("/screener/bottom-box")
def get_bottom_box(db: Session = Depends(get_db)):
    """바닥 박스 감시 (한선엔지니어링형) + 오늘 박스에서 터진 종목."""
    from backend.screener.bottom_box import scan  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    return cached("bottom_box", (), db, lambda: scan(db))


@router.get("/screener/value-records")
def get_value_records(db: Session = Depends(get_db)):
    """오늘 거래대금이 6개월 넘게 만의 최고인 종목 ('25년 3월 이후 최고')."""
    from backend.screener.value_records import scan  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    return cached("value_records", (), db, lambda: scan(db))


@router.get("/screener/my-pattern")
def get_my_pattern(db: Session = Depends(get_db)):
    """종베: 최적 조건 B · 내 패턴 A(사용자 매수 501건에서 번 자리) · 내일 후보 (2026-10-06)."""
    from backend.screener.my_pattern import scan  # noqa: PLC0415
    return scan(db)


@router.get("/screener/volume-records")
def get_volume_records(db: Session = Depends(get_db)):
    """대량거래 관심종목: 최근 약 4개월 안 몇 년 만의 최대 거래대금이 터진 종목과 지금 단계 (신규·숨고르기·진행 중·무너짐)."""
    from backend.screener.volume_record import scan  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    return cached("volume_records", (), db, lambda: scan(db))


@router.get("/screener/chart-candidates")
def get_chart_candidates(min_cap: float = 0, db: Session = Depends(get_db)):
    """차트 후보 (불플래그·상승삼각형·기준봉 눌림) + 섹터 점수. min_cap은 억원 단위."""
    from backend.screener.chart_candidates import scan  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    base = cached("chart_candidates", (), db, lambda: scan(db))
    if min_cap <= 0:
        return base
    return {**base, "items": [it for it in base["items"] if (it["market_cap"] or 0) >= min_cap * 1e8]}


def warm_caches(db: Session) -> None:
    """화면 기본값으로 미리 계산해 둔다. 데이터가 그대로면 즉시 끝난다."""
    get_chart_candidates(min_cap=0, db=db)
    get_volume_records(db=db)
    get_sector_rotation(db=db)
    get_sector_calendar(db=db)
    get_jongbe(db=db)
    get_value_records(db=db)
    get_bottom_box(db=db)
    get_support_setups(db=db)


@router.get("/screener/picks/performance")
def get_pick_performance(min_cap: float = 1000, db: Session = Depends(get_db)):
    """레이더가 실제로 보여준 종목들의 이후 성과 (튜닝에 안 쓴 실전 데이터). min_cap은 억원 단위."""
    from backend.screener.radar import pick_performance  # noqa: PLC0415
    return pick_performance(db, min_market_cap=min_cap * 1e8)


@router.post("/screener/picks/record")
def post_record_picks(db: Session = Depends(get_db)):
    """오늘 레이더 신호 종목을 기록 (이미 기록된 날이면 아무것도 안 함)."""
    from backend.screener.radar import record_picks  # noqa: PLC0415
    return record_picks(db)


@router.get("/screener/backtest")
def get_backtest(months: int = 6, min_score: int = 60, min_cap: float = 1000, db: Session = Depends(get_db)):
    """세력 신호 백테스팅 결과 (승률 + 모의 매매). 스크리너 점수+시총 필터 적용."""
    from backend.screener.backtest import run_backtest  # noqa: PLC0415
    return run_backtest(db, lookback_months=months, min_score=min_score, min_market_cap=min_cap * 1e8)


@router.get("/toss/candles/{code}")
def get_toss_candles(code: str, interval: str = "1d", count: int = 60):
    """토스증권 Open API로 실시간 일봉 캔들 조회 (차트 렌더링용)."""
    candles = fetch_candles(code, interval=interval, count=count)
    if candles is None:
        raise HTTPException(status_code=502, detail="토스 API에서 캔들 데이터를 가져오지 못했습니다")
    return {"code": code, "interval": interval, "candles": candles}


@router.get("/universe")
def get_universe(db: Session = Depends(get_db)):
    """현재 유니버스 종목 목록."""
    stocks = list(db.scalars(select(Stock).where(Stock.is_active.is_(True)).order_by(desc(Stock.market_cap))))
    return [
        {"code": s.code, "name": s.name, "market": s.market, "market_cap": s.market_cap}
        for s in stocks
    ]


# ─────────────────────────── 섹터 수급 ───────────────────────────

@router.get("/sectors", response_model=list[SectorItem])
def get_sectors(source: str | None = None, db: Session = Depends(get_db)):
    """전체 섹터 목록. source 파라미터로 필터 (custom / naver_theme)."""
    q = select(Sector).where(Sector.is_active == True)  # noqa: E712
    if source:
        q = q.where(Sector.source == source)
    rows = list(db.scalars(q.order_by(Sector.sector_name)))
    return [
        SectorItem(
            id=r.id,
            sector_code=r.sector_code,
            sector_name=r.sector_name,
            source=r.source,
            is_active=r.is_active,
        )
        for r in rows
    ]


@router.get("/sectors/calendar")
def get_sector_calendar(db: Session = Depends(get_db)):
    """강한 섹터 캘린더: 최근 약 6개월, 날짜마다 그날 가장 강했던 섹터·테마."""
    from backend.screener.sector_calendar import scan  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    return cached("sector_calendar_v2", (), db, lambda: scan(db))


@router.get("/sectors/rotation")
def get_sector_rotation(db: Session = Depends(get_db)):
    """순환매 모니터: 이야기 줄기 16개의 순위·확산·자금 흐름과 과열/유입 표시."""
    from backend.screener.rotation import scan  # noqa: PLC0415
    from backend.services.result_cache import cached  # noqa: PLC0415
    return cached("sector_rotation", (), db, lambda: scan(db))


@router.get("/sectors/live")
def get_sectors_live(limit: int = 30, db: Session = Depends(get_db)):
    """오늘 강한 테마 (토스 현재가 기준 실시간, 1분 캐시)."""
    from backend.services.live_themes import live_themes  # noqa: PLC0415
    data = live_themes(db)
    return {**data, "items": data["items"][:limit]}


@router.get("/sectors/flow", response_model=list[SectorFlowItem])
def get_sector_flow(
    sort: str = "stealth",
    source: str | None = None,
    limit: int = 30,
    db: Session = Depends(get_db),
):
    """당일 섹터 수급 랭킹. sort: stealth(기본) / flow / foreign / inst."""
    latest_date = db.scalar(select(func.max(SectorFlowDaily.date)))
    if not latest_date:
        return []

    q = (
        select(SectorFlowDaily, Sector)
        .join(Sector, SectorFlowDaily.sector_id == Sector.id)
        .where(SectorFlowDaily.date == latest_date, Sector.is_active == True)  # noqa: E712
    )
    if source:
        q = q.where(Sector.source == source)

    sort_col = {
        "stealth": desc(SectorFlowDaily.stealth_score),
        "flow": desc(SectorFlowDaily.flow_score),
        "foreign": desc(SectorFlowDaily.foreign_net_buy),
        "inst": desc(SectorFlowDaily.inst_net_buy),
    }.get(sort, desc(SectorFlowDaily.stealth_score))

    rows = list(db.execute(q.order_by(sort_col).limit(limit)))

    result = []
    for flow, sector in rows:
        result.append(SectorFlowItem(
            sector_id=sector.id,
            sector_code=sector.sector_code,
            sector_name=sector.sector_name,
            source=sector.source,
            date=flow.date.isoformat(),
            foreign_net_buy=flow.foreign_net_buy,
            inst_net_buy=flow.inst_net_buy,
            combined_net_buy=flow.combined_net_buy,
            stock_count=flow.stock_count,
            up_count=flow.up_count,
            down_count=flow.down_count,
            avg_change_pct=flow.avg_change_pct,
            max_change_pct=flow.max_change_pct,
            flow_score=flow.flow_score,
            stealth_score=flow.stealth_score,
            buy_streak=flow.buy_streak,
            top_contributor_code=flow.top_contributor_code,
            top_contributor_name=flow.top_contributor_name,
            top_contributor_amount=flow.top_contributor_amount,
            is_surged=flow.avg_change_pct >= 5.0,
        ))
    return result


@router.get("/sectors/for-stock/{code}")
def get_sector_for_stock(code: str, db: Session = Depends(get_db)):
    """종목 코드 -> 소속 업종의 당일 수급 상태 (외부 서비스의 업종 체크리스트 자동 채움용)."""
    mapping = db.scalar(select(SectorStock).where(SectorStock.stock_code == code))
    if not mapping:
        return None
    sector = db.scalar(select(Sector).where(Sector.id == mapping.sector_id))
    if not sector:
        return None

    latest_date = db.scalar(select(func.max(SectorFlowDaily.date)))
    if not latest_date:
        return None

    flow = db.scalar(
        select(SectorFlowDaily).where(
            SectorFlowDaily.sector_id == sector.id, SectorFlowDaily.date == latest_date
        )
    )
    if not flow:
        return None

    all_scores = list(
        db.scalars(
            select(SectorFlowDaily.flow_score).where(SectorFlowDaily.date == latest_date)
        )
    )
    rank_pct = 0.0
    if all_scores:
        below = sum(1 for s in all_scores if s <= flow.flow_score)
        rank_pct = round(below / len(all_scores) * 100, 1)

    return {
        "sector_id": sector.id,
        "sector_name": sector.sector_name,
        "date": flow.date.isoformat(),
        "flow_score": flow.flow_score,
        "stealth_score": flow.stealth_score,
        "foreign_net_buy": flow.foreign_net_buy,
        "inst_net_buy": flow.inst_net_buy,
        "combined_net_buy": flow.combined_net_buy,
        "up_count": flow.up_count,
        "down_count": flow.down_count,
        "buy_streak": flow.buy_streak,
        "flow_score_rank_pct": rank_pct,
    }


@router.get("/sectors/{sector_id}/history")
def get_sector_history(sector_id: int, days: int = 20, db: Session = Depends(get_db)):
    """특정 섹터 일별 수급 추이."""
    sector = db.scalar(select(Sector).where(Sector.id == sector_id))
    if not sector:
        raise HTTPException(status_code=404, detail="섹터를 찾을 수 없습니다")

    rows = list(db.scalars(
        select(SectorFlowDaily)
        .where(SectorFlowDaily.sector_id == sector_id)
        .order_by(desc(SectorFlowDaily.date))
        .limit(days)
    ))
    return {
        "sector_id": sector_id,
        "sector_name": sector.sector_name,
        "history": [
            {
                "date": r.date.isoformat(),
                "foreign_net_buy": r.foreign_net_buy,
                "inst_net_buy": r.inst_net_buy,
                "combined_net_buy": r.combined_net_buy,
                "avg_change_pct": r.avg_change_pct,
                "flow_score": r.flow_score,
                "stealth_score": r.stealth_score,
                "buy_streak": r.buy_streak,
            }
            for r in reversed(rows)
        ],
    }


@router.get("/sectors/{sector_id}/stocks", response_model=list[SectorStockItem])
def get_sector_stocks(sector_id: int, db: Session = Depends(get_db)):
    """특정 섹터 소속 종목 + 당일 수급."""
    sector = db.scalar(select(Sector).where(Sector.id == sector_id))
    if not sector:
        raise HTTPException(status_code=404, detail="섹터를 찾을 수 없습니다")

    mappings = list(db.scalars(select(SectorStock).where(SectorStock.sector_id == sector_id)))
    codes = [m.stock_code for m in mappings]
    if not codes:
        return []

    target_date = _latest_data_date(db)
    stocks_map = {s.code: s for s in db.scalars(select(Stock).where(Stock.code.in_(codes)))}
    flows_map = {
        f.stock_code: f
        for f in db.scalars(
            select(SpotInvestorFlow)
            .where(SpotInvestorFlow.stock_code.in_(codes), SpotInvestorFlow.trading_date == target_date)
        )
    }
    prices_map = {
        p.stock_code: p
        for p in db.scalars(
            select(SpotDailyPrice)
            .where(SpotDailyPrice.stock_code.in_(codes), SpotDailyPrice.trading_date == target_date)
        )
    }

    name_fallback: dict[str, str] = {}   # Stock 표에 없는 종목은 코드로 표시 (pykrx 이름 조회는 2026-10-03 제거)
    from backend.services.float_ratio import get as float_get  # noqa: PLC0415
    floats = float_get(codes)

    result = []
    for code in codes:
        stock = stocks_map.get(code)
        flow = flows_map.get(code)
        price = prices_map.get(code)
        if stock is None and flow is None:
            continue
        f_net = float(flow.foreign_net_buy or 0) if flow else 0.0
        i_net = float(flow.institution_net_buy or 0) if flow else 0.0
        display_name = stock.name if stock else name_fallback.get(code, code)
        result.append(SectorStockItem(
            stock_code=code,
            stock_name=display_name,
            market=stock.market if stock else "",
            foreign_net_buy=f_net,
            inst_net_buy=i_net,
            combined_net_buy=f_net + i_net,
            change_pct=float(price.change_pct or 0) if price else 0.0,
            close_price=float(price.close_price or 0) if price else 0.0,
            trading_value=float(price.trading_value or 0) if price else 0.0,
            float_ratio=floats[code][1] if code in floats else None,
            float_turnover_pct=round(float(price.volume or 0) / (floats[code][0] * floats[code][1] / 100) * 100, 1)
            if price and code in floats and floats[code][0] and floats[code][1] else None,
        ))
    result.sort(key=lambda x: -(x.float_turnover_pct or 0))   # 유통 물량을 많이 돌린 순
    return result


@router.post("/sectors/refresh")
def refresh_sectors(db: Session = Depends(get_db)):
    """섹터 매핑 수동 갱신 (custom_sectors.json + 네이버 테마)."""
    from backend.collector.sector import refresh_sector_mapping  # noqa: PLC0415
    try:
        result = refresh_sector_mapping(db)
        return {"status": "ok", **result}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/screener/volume-anomaly")
def screener_volume_anomaly(top_n: int | None = None, db: Session = Depends(get_db)):
    """세력 포착 스크리너 — 비정상 거래량 이벤트 기반 코어라인 분석.
    top_n: 최근 5일 거래대금 상위 N 종목으로 제한 (예: top_n=100).
    """
    from backend.screener.volume_anomaly import scan  # noqa: PLC0415
    return scan(db, top_n_by_value=top_n)


# ── 매매 일지 (이름 + 비밀번호로 사람별 기록) ─────────────────────
_journal_fails: dict = {}


def _journal_owner(request: Request, db: Session) -> str:
    import time  # noqa: PLC0415
    from urllib.parse import unquote  # noqa: PLC0415
    from backend.services.trade_journal import auth  # noqa: PLC0415
    owner = unquote(request.headers.get("x-owner", "")).strip()[:20]
    pin = unquote(request.headers.get("x-pin", ""))
    now = time.time()
    fails = [t for t in _journal_fails.get(owner, []) if now - t < 600]
    if len(fails) >= 10:
        raise HTTPException(status_code=429, detail="비밀번호를 여러 번 틀려서 10분간 잠겼습니다.")
    if auth(db, owner, pin) != "ok":
        _journal_fails[owner] = fails + [now]
        raise HTTPException(status_code=401, detail="이름 또는 비밀번호가 맞지 않습니다.")
    _journal_fails.pop(owner, None)
    return owner


class JournalLoginIn(BaseModel):
    owner: str = Field(..., max_length=20)
    pin: str = Field(..., max_length=40)
    create: bool = False


@router.get("/journal/owners")
def get_journal_owners(db: Session = Depends(get_db)):
    from backend.services.trade_journal import owners  # noqa: PLC0415
    return {"owners": owners(db)}


@router.post("/journal/login")
def post_journal_login(body: JournalLoginIn, db: Session = Depends(get_db)):
    """처음 쓰는 이름이면 create=True로 비밀번호를 정한다 (4자 이상)."""
    import time  # noqa: PLC0415
    from backend.services.trade_journal import auth  # noqa: PLC0415
    owner = body.owner.strip()
    now = time.time()
    fails = [t for t in _journal_fails.get(owner, []) if now - t < 600]
    if len(fails) >= 10:
        raise HTTPException(status_code=429, detail="비밀번호를 여러 번 틀려서 10분간 잠겼습니다.")
    r = auth(db, owner, body.pin, create=body.create)
    if r == "bad":
        _journal_fails[owner] = fails + [now]
        raise HTTPException(status_code=401, detail="비밀번호가 맞지 않습니다 (4자 이상).")
    if r == "none":
        raise HTTPException(status_code=404, detail="처음 쓰는 이름입니다.")
    return {"owner": owner, "result": r}


@router.get("/journal")
def get_journal(request: Request, db: Session = Depends(get_db)):
    from backend.services.trade_journal import analyze  # noqa: PLC0415
    return analyze(db, _journal_owner(request, db))


class JournalImportIn(BaseModel):
    text: str = Field(..., max_length=300_000)
    date: str = ""     # 자유 형식 줄에 날짜가 없을 때 쓸 날짜 (비면 최근 거래일)
    preview: bool = False


@router.post("/journal/import")
def post_journal_import(body: JournalImportIn, request: Request, db: Session = Depends(get_db)):
    from backend.services.trade_journal import add, parse  # noqa: PLC0415
    owner = _journal_owner(request, db)
    try:
        d = date.fromisoformat(body.date) if body.date else latest_trading_day()
    except ValueError:
        d = latest_trading_day()
    rows, bad, shift = parse(db, body.text, d)
    if body.preview:
        return {"rows": [{**r, "trade_date": r["trade_date"].isoformat()} for r in rows], "bad": bad, "shift": shift}
    return {**add(db, owner, rows), "bad": bad, "shift": shift}


class JournalEditIn(BaseModel):
    tag: str | None = Field(None, max_length=40)
    memo: str | None = Field(None, max_length=200)
    kind: str | None = Field(None, max_length=10)


@router.patch("/journal/{ex_id}")
def patch_journal(ex_id: int, body: JournalEditIn, request: Request, db: Session = Depends(get_db)):
    from backend.services.trade_journal import update_exec  # noqa: PLC0415
    if not update_exec(db, _journal_owner(request, db), ex_id, body.model_dump()):
        raise HTTPException(status_code=404, detail="없는 기록입니다.")
    return {"ok": True}


@router.delete("/journal/{ex_id}")
def delete_journal(ex_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.services.trade_journal import delete_exec  # noqa: PLC0415
    if not delete_exec(db, _journal_owner(request, db), ex_id):
        raise HTTPException(status_code=404, detail="없는 기록입니다.")
    return {"ok": True}


class JournalCfgIn(BaseModel):
    exclude: list[str] | None = Field(default=None, max_length=100)
    cash: float | None = Field(default=None, ge=0, le=1e13)   # 예수금 — 보유 비중 계산용


@router.post("/journal/config")
def post_journal_config(body: JournalCfgIn, request: Request, db: Session = Depends(get_db)):
    """분석에서 뺄 종목 코드(장투 종목 등)·예수금. 보낸 항목만 바꾼다."""
    from backend.services.trade_journal import get_cfg, set_cfg  # noqa: PLC0415
    owner = _journal_owner(request, db)
    cfg = get_cfg(db, owner)
    if body.exclude is not None:
        cfg["exclude"] = [x.strip()[:20] for x in body.exclude if x.strip()]
    if body.cash is not None:
        cfg["cash"] = round(body.cash)
    return set_cfg(db, owner, cfg)

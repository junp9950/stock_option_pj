"""배포 안전장치 — 새 코드를 받은 뒤, 재시작 전에 돌린다. 실패하면 종료코드 1 + 텔레그램 "배포 실패: 파일·줄".

1) backend·scripts 전 파일 문법 검사(compile)
2) 새 코드를 불러와 주요 화면·API가 200인지 시험 (TestClient — startup 이벤트를 안 돌리므로 스케줄러·텔레그램 폴링이 중복으로 뜨지 않는다)
사용: cd ~/stock_option_pj && set -a && . ./.env && set +a && .venv/bin/python scripts/deploy_check.py [커밋 이름]
"""
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

CHECKS = ["/", "/api/stock/096770/panel", "/api/stock/096770/chart-signals"]


def _compile() -> str | None:
    for d in ("backend", "scripts"):
        for f in sorted((ROOT / d).rglob("*.py")):
            try:
                compile(f.read_bytes(), str(f), "exec")          # py_compile과 같은 검사 (파일은 안 만든다)
            except SyntaxError as e:
                return f"문법 오류 {f.relative_to(ROOT)}:{e.lineno} {e.msg}"
    return None


def _where(exc: BaseException) -> str:
    frames = [x for x in traceback.extract_tb(exc.__traceback__) if str(ROOT) in x.filename and ".venv" not in x.filename]
    f = frames[-1] if frames else None
    where = f"{Path(f.filename).relative_to(ROOT)}:{f.lineno}" if f else "위치 모름"
    return f"{where} {type(exc).__name__}: {str(exc)[:150]}"


def _http() -> str | None:
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from backend.main import app  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return "불러오기 실패 " + _where(exc)
    client = TestClient(app, raise_server_exceptions=True)     # with 없이 — startup 이벤트(스케줄러 등)를 돌리지 않는다
    for path in CHECKS:
        try:
            r = client.get(path)
        except Exception as exc:  # noqa: BLE001
            return f"{path} 오류 " + _where(exc)
        if r.status_code != 200:
            return f"{path} 응답 {r.status_code}"
    return None


def _notify(msg: str) -> None:
    try:
        from backend.db.database import SessionLocal  # noqa: PLC0415
        from backend.services import telegram  # noqa: PLC0415
        db = SessionLocal()
        try:
            telegram.send(db, msg)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        print("텔레그램 알림 실패:", type(exc).__name__)


def main() -> int:
    commit = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        err = _compile() or _http()
    except Exception as exc:  # noqa: BLE001
        err = "점검 중 오류 " + _where(exc)
    if err is None:
        print("배포 점검 통과")
        return 0
    print("배포 점검 실패:", err)
    _notify(f"⛔ 배포 실패 {commit}\n{err}\n→ 이전 버전으로 되돌렸고, 사이트는 그대로 돌고 있습니다.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

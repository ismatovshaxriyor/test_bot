import json
import os
import urllib.request
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import BOT_TOKEN, BOT_USERNAME
from database import Test, TestSubmission, User, init_db


init_db()
app = FastAPI(title="TestBot WebApp API")

# Setup template logic
templates_dir = os.path.join(os.path.dirname(__file__), "webapp")
templates = Jinja2Templates(directory=templates_dir)


def _resolve_bot_username() -> str:
    """Redirect uchun bot username ni olish (env yoki Telegram getMe orqali)."""
    if BOT_USERNAME:
        return BOT_USERNAME

    if not BOT_TOKEN:
        return ""

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("ok"):
            username = str(payload.get("result", {}).get("username", "")).strip()
            return username.lstrip("@")
    except Exception:
        pass
    return ""


RESOLVED_BOT_USERNAME = _resolve_bot_username()


def _is_mixed_test(test: Test) -> bool:
    return bool(test.correct_answers) and test.correct_answers.startswith("[{")


def _build_test_structure(test: Test) -> list[dict]:
    """Test tuzilmasini xavfsiz ko'rinishda qaytarish (javobsiz)."""
    is_mixed = _is_mixed_test(test)
    if not is_mixed:
        return [{"type": "closed"} for _ in range(test.total_questions)]

    try:
        data = json.loads(test.correct_answers)
        if isinstance(data, list):
            return [{"type": str((q or {}).get("type", "closed")) if isinstance(q, dict) else "closed"} for q in data]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    return [{"type": "closed"} for _ in range(test.total_questions)]


def _empty_solve_context(test_id: int = 0, error: Optional[str] = None) -> dict:
    return {
        "test_id": test_id,
        "total_questions": 0,
        "test_structure": "[]",
        "is_mixed": False,
        "bot_username": RESOLVED_BOT_USERNAME,
        "error": error,
    }


def _validate_solver_access(test: Test, user_id: Optional[int]) -> None:
    """Foydalanuvchi testni yecha olish/olmasligini tekshirish."""
    if not user_id:
        return

    if test.creator.telegram_id == user_id:
        raise HTTPException(status_code=403, detail="O'zingiz yaratgan testni yecha olmaysiz!")

    user = User.get_or_none(User.telegram_id == user_id)
    if not user:
        return

    existing = TestSubmission.select().where(
        (TestSubmission.test == test) & (TestSubmission.user == user)
    ).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Siz bu testni allaqachon ishlagansiz!",
        )


def _solve_context_from_test(test: Test) -> dict:
    structure = _build_test_structure(test)
    return {
        "test_id": test.id,
        "total_questions": len(structure),
        "test_structure": json.dumps(structure, ensure_ascii=False),
        "is_mixed": _is_mixed_test(test),
        "bot_username": RESOLVED_BOT_USERNAME,
        "error": None,
    }


async def _render_solve(request: Request, test_id: Optional[int], is_rasch: bool = False) -> HTMLResponse:
    template_name = "solve_rasch.html" if is_rasch else "index.html"
    if test_id is None:
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context=_empty_solve_context(),
        )

    try:
        test = Test.get_by_id(test_id)
    except Test.DoesNotExist:
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context=_empty_solve_context(test_id=test_id, error="Test topilmadi!"),
        )

    if not test.is_active:
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context=_empty_solve_context(test_id=test_id, error="Bu test yakunlangan."),
        )

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=_solve_context_from_test(test),
    )


@app.get("/", response_class=HTMLResponse)
async def serve_webapp(request: Request, test_id: Optional[int] = None):
    """Yechish WebApp (eski route bilan compatibility saqlanadi)."""
    return await _render_solve(request, test_id)


@app.get("/solve", response_class=HTMLResponse)
async def serve_solve_webapp(request: Request, test_id: Optional[int] = None):
    """Test yechish WebApp sahifasi (Oddiy)."""
    return await _render_solve(request, test_id, is_rasch=False)


@app.get("/solve_rasch", response_class=HTMLResponse)
async def serve_solve_rasch_webapp(request: Request, test_id: Optional[int] = None):
    """Rash testi uchun yechish WebApp sahifasi."""
    return await _render_solve(request, test_id, is_rasch=True)


@app.get("/create", response_class=HTMLResponse)
async def serve_create_webapp(request: Request):
    """Oddiy Test yaratish WebApp sahifasi."""
    return templates.TemplateResponse(
        request=request,
        name="create.html",
        context={"bot_username": RESOLVED_BOT_USERNAME},
    )


@app.get("/create_rasch", response_class=HTMLResponse)
async def serve_create_rasch_webapp(request: Request):
    """Rash Test yaratish WebApp sahifasi."""
    return templates.TemplateResponse(
        request=request,
        name="create_rasch.html",
        context={"bot_username": RESOLVED_BOT_USERNAME},
    )


@app.get("/api/test/{test_id}")
def get_test_for_solve(test_id: int, user_id: Optional[int] = None):
    """Berilgan test kodi bo'yicha yechish uchun xavfsiz metadata."""
    try:
        test = Test.get_by_id(test_id)
    except Test.DoesNotExist as exc:
        raise HTTPException(status_code=404, detail="Test topilmadi!") from exc

    if not test.is_active:
        raise HTTPException(status_code=400, detail="Bu test yakunlangan.")

    _validate_solver_access(test, user_id)

    structure = _build_test_structure(test)
    return {
        "test_id": test.id,
        "total_questions": len(structure),
        "test_structure": structure,
        "is_mixed": _is_mixed_test(test),
    }


@app.get("/api/ping")
def ping():
    return {"status": "ok"}

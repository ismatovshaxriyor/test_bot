import hashlib
import hmac
import json
import logging
import os
import time
import urllib.request
from dataclasses import asdict
from typing import Optional
from urllib.parse import parse_qsl, quote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

import services
from ai_extract import ExtractionError, normalize_extracted
from config import ADMIN_ID, BOT_TOKEN, BOT_USERNAME
from database import Question, Test, TestSubmission, User, get_or_create_user, init_db


# initData imzosining maksimal yaroqlilik muddati (sekundlarda)
INIT_DATA_MAX_AGE = 24 * 60 * 60  # 24 soat


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


def _extract_init_data(authorization: Optional[str]) -> str:
    """Authorization sarlavhasidan Telegram initData ni ajratib olish.

    Telegram konvensiyasi: `Authorization: tma <init-data>`
    """
    if not authorization:
        return ""
    prefix = "tma "
    if authorization.startswith(prefix):
        return authorization[len(prefix):].strip()
    return ""


def _verify_init_data(init_data: str) -> Optional[int]:
    """Telegram WebApp initData ni HMAC-SHA256 bilan tekshirish.

    Returns:
        - ishonchli telegram user_id (int) — imzo to'g'ri va user mavjud bo'lsa
        - None — initData umuman yuborilmagan (brauzer/preview rejimi)

    Raises:
        HTTPException(401) — initData yuborilgan, lekin imzo yaroqsiz/eskirgan
    """
    if not init_data:
        return None

    if not BOT_TOKEN:
        # Token bo'lmasa imzoni tekshirib bo'lmaydi — ishonchsiz ma'lumotni qabul qilmaymiz.
        raise HTTPException(status_code=503, detail="Server autentifikatsiyaga sozlanmagan.")

    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True, keep_blank_values=True))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="initData formati noto'g'ri.") from exc

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="initData imzosi topilmadi.")

    # data_check_string: hash dan tashqari barcha kalitlar alifbo tartibida "key=value"
    data_check_string = "\n".join(f"{key}={parsed[key]}" for key in sorted(parsed))

    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail="initData imzosi yaroqsiz.")

    # auth_date orqali eskirganlikni tekshirish (replay hujumlariga qarshi)
    auth_date = parsed.get("auth_date", "")
    if auth_date.isdigit():
        if time.time() - int(auth_date) > INIT_DATA_MAX_AGE:
            raise HTTPException(status_code=401, detail="initData muddati o'tgan.")

    user_raw = parsed.get("user")
    if not user_raw:
        return None

    try:
        user_obj = json.loads(user_raw)
        return int(user_obj["id"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=401, detail="initData foydalanuvchi ma'lumoti noto'g'ri."
        ) from exc


def _is_mixed_test(test: Test) -> bool:
    return bool(test.correct_answers) and test.correct_answers.startswith("[{")


def _build_test_structure(test: Test) -> list[dict]:
    """Test tuzilmasini xavfsiz ko'rinishda qaytarish.

    Boy savollar (Question qatorlari) bo'lsa — savol matni + variantlar + rasm
    belgisi ham qaytariladi. To'g'ri javob HECH QACHON yuborilmaydi.
    Aks holda (eski/legacy testlar) — faqat tur (type-only) qaytariladi.
    """
    rich = list(Question.select().where(Question.test == test).order_by(Question.num))
    if rich:
        structure = []
        for q in rich:
            opts = None
            if q.options:
                try:
                    opts = json.loads(q.options)
                except (TypeError, ValueError, json.JSONDecodeError):
                    opts = None
            structure.append({
                "num": q.num,
                "type": q.type,
                "text": q.text or "",
                "options": opts,
                "has_image": bool(q.has_image and q.image_file_id),
            })
        return structure

    # Fallback: matn saqlanmagan eski testlar (faqat tur)
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


def _safe_json_for_script(obj) -> str:
    """JSON'ni inline <script> ichiga xavfsiz joylash uchun.

    `<`, `>`, `&` va U+2028/U+2029 ni \\uXXXX ga aylantiradi — shunda savol matni
    ichidagi `</script>` kabi belgilar script tegini buza olmaydi (XSS oldini olish).
    Natija to'g'ri JSON bo'lib qoladi (JSON satr ichida \\u003c == `<`).
    """
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _solve_context_from_test(test: Test) -> dict:
    structure = _build_test_structure(test)
    return {
        "test_id": test.id,
        "total_questions": len(structure),
        "test_structure": _safe_json_for_script(structure),
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


@app.get("/create_rich", response_class=HTMLResponse)
async def serve_create_rich_webapp(request: Request):
    """Qo'lda to'liq (matn + variant + javob) test yaratish WebApp sahifasi."""
    return templates.TemplateResponse(
        request=request,
        name="create_rich.html",
        context={"bot_username": RESOLVED_BOT_USERNAME},
    )


@app.get("/api/test/{test_id}")
def get_test_for_solve(test_id: int, authorization: Optional[str] = Header(default=None)):
    """Berilgan test kodi bo'yicha yechish uchun xavfsiz metadata.

    Foydalanuvchi identifikatsiyasi `Authorization: tma <initData>` sarlavhasidagi
    Telegram imzosidan olinadi (ishonchsiz `user_id` query parametri emas).
    """
    user_id = _verify_init_data(_extract_init_data(authorization))

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


class RichQuestionIn(BaseModel):
    num: int
    type: str = "closed"
    text: str = Field(default="", max_length=4000)
    options: Optional[dict] = None
    answer: str = Field(default="", max_length=2000)
    has_image: bool = False


class RichTestCreateRequest(BaseModel):
    scoring_mode: str = "simple"
    # Server tomonda savollar soni cheklangan (DoS/resurs himoyasi)
    questions: list[RichQuestionIn] = Field(..., min_length=1, max_length=200)


def _is_admin_uid(user_id: int) -> bool:
    """Foydalanuvchi admin ekanligini tekshirish (.env ADMIN_ID yoki User.is_admin)."""
    if user_id == ADMIN_ID:
        return True
    user = User.get_or_none(User.telegram_id == user_id)
    return bool(user and user.is_admin)


def _verified_user_from_init_data(authorization: Optional[str]) -> Optional[dict]:
    """initData ni HMAC bilan tekshirib, ishonchli user dict (id + ism) qaytaradi.

    Imzo to'g'ri (yoki yo'q) bo'lsa user dict yoki None; yaroqsiz imzoda
    `_verify_init_data` HTTPException(401) ko'taradi.
    """
    init_data = _extract_init_data(authorization)
    user_id = _verify_init_data(init_data)  # imzoni tekshiradi (yaroqsizda 401)
    if not user_id:
        return None
    # init_data allaqachon tasdiqlangan — ismlarni xavfsiz ajratib olamiz
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        user_obj = json.loads(parsed.get("user", "{}"))
    except (ValueError, json.JSONDecodeError):
        user_obj = {}
    return {
        "id": user_id,
        "username": user_obj.get("username"),
        "full_name": (
            f"{user_obj.get('first_name', '')} {user_obj.get('last_name', '')}".strip()
        ),
    }


@app.post("/api/test/create_rich")
def create_rich_test_endpoint(
    payload: RichTestCreateRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Qo'lda to'liq kiritilgan testni yaratish (WebApp → API).

    Avtorizatsiya `Authorization: tma <initData>` orqali — yaratuvchi ishonchli
    Telegram imzosidan aniqlanadi. Javoblar serverda qayta validatsiya qilinadi.
    """
    user = _verified_user_from_init_data(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Avtorizatsiya talab qilinadi.")

    # Hozircha test yaratish faqat adminlar uchun
    if not _is_admin_uid(user["id"]):
        raise HTTPException(status_code=403, detail="Bu funksiya hozircha faqat adminlar uchun.")

    scoring_mode = payload.scoring_mode if payload.scoring_mode in {"simple", "rasch"} else "simple"

    # Serverda qayta normalizatsiya/validatsiya (clientga ishonmaymiz)
    raw = [q.model_dump() for q in payload.questions]
    try:
        result = normalize_extracted(raw)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    questions = [asdict(q) for q in result.questions]

    try:
        db_user = get_or_create_user(
            telegram_id=user["id"],
            username=user.get("username"),
            full_name=user.get("full_name") or "",
        )
        test = services.create_rich_test(
            db_user, questions, scoring_mode=scoring_mode, source="manual"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("create_rich_test_endpoint: DB xatolik")
        raise HTTPException(status_code=503, detail="Vaqtincha band, qayta urining.") from exc

    return {
        "test_id": test.id,
        "total_questions": test.total_questions,
        "image_questions": services.image_question_nums(test),
    }


@app.get("/api/test/{test_id}/image/{num}")
def get_question_image(test_id: int, num: int):
    """Savolga biriktirilgan rasmni Telegram'dan olib stream qiladi.

    To'g'ri javob emas — savol mazmunining bir qismi, shuning uchun test_id+num
    bo'yicha ochiq (savol matni/variantlari kabi).
    """
    test = Test.get_or_none(Test.id == test_id)
    if not test or not test.is_active:
        raise HTTPException(status_code=404, detail="Rasm topilmadi.")

    q = Question.get_or_none((Question.test == test_id) & (Question.num == num))
    if not q or not q.image_file_id:
        raise HTTPException(status_code=404, detail="Rasm topilmadi.")
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Server sozlanmagan.")

    try:
        meta_url = (
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile"
            f"?file_id={quote(q.image_file_id)}"
        )
        with urllib.request.urlopen(meta_url, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not payload.get("ok"):
            raise ValueError("getFile ok=false")
        file_path = payload["result"]["file_path"]

        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        with urllib.request.urlopen(file_url, timeout=15) as resp:
            content = resp.read()
            ctype = resp.headers.get("Content-Type", "image/jpeg")
    except Exception as exc:
        logger.exception("get_question_image: rasmni olishda xatolik")
        raise HTTPException(status_code=502, detail="Rasmni olishda xatolik.") from exc

    return Response(
        content=content,
        media_type=ctype,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/ping")
def ping():
    return {"status": "ok"}

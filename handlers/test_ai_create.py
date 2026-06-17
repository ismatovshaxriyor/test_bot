"""Fayldan (PDF/rasm) AI orqali test yaratish + rasm biriktirish.

Oqim:
  1. Menyu "📸 Fayldan test" → WAITING_FILE
  2. Foydalanuvchi PDF/rasm yuboradi → AI ajratadi → PREVIEW_CONFIRM
  3. Tasdiqlash → test yaratiladi → rasm biriktirish (global handlerlar) → tayyor

Rasm biriktirish suhbatdan TASHQARIDA, global handlerlar + user_data orqali ishlaydi —
shu tufayli AI oqimi ham, qo'lda (WebApp) oqimi ham bir xil mexanizmga keladi.
"""
import asyncio
import json
import logging
from dataclasses import asdict
from html import escape

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
)
from telegram.ext import (
    ContextTypes, MessageHandler, CommandHandler,
    ConversationHandler, CallbackQueryHandler, filters,
)

from config import ADMIN_ID, WEBAPP_URL, WEBAPP_VERSION
from database import get_or_create_user, Test, Question
from keyboards import main_menu_keyboard, test_created_keyboard
from membership import membership_required
from ai_extract import get_default_extractor, ExtractionError, DOCX_MIME
from utils import latex_to_text
import services

logger = logging.getLogger(__name__)

# Conversation states
WAITING_FILE = 0
PREVIEW_CONFIRM = 1
ANSWER_ENTRY = 2

MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram getFile cheki ~20MB
_PREVIEW_MAX_QUESTIONS = 25         # preview'da ko'rsatiladigan maksimal savol


def _answer_letters(q: dict) -> list:
    """Savol uchun ruxsat etilgan javob harflari (turga ko'ra kanonik to'plam)."""
    t = q.get("type")
    if t == "closed6":
        return ["a", "b", "c", "d", "e", "f"]
    if t == "closed":
        return ["a", "b", "c", "d"]
    opts = q.get("options")
    return sorted(opts.keys()) if opts else ["a", "b", "c", "d"]


def _is_answer_missing(q: dict) -> bool:
    """Savol javobi yo'q yoki yaroqsizmi (kalitsiz hujjatdan kelganda)."""
    ans = str(q.get("answer", "") or "").strip().lower()
    if q.get("type") in ("closed", "closed6"):
        return ans not in _answer_letters(q)
    return not ans  # open


def _first_missing_index(questions: list):
    for i, q in enumerate(questions):
        if _is_answer_missing(q):
            return i
    return None


def _count_missing(questions: list) -> int:
    return sum(1 for q in questions if _is_answer_missing(q))


def _ai_keyboard() -> ReplyKeyboardMarkup:
    """WAITING_FILE keyboardi: fayl yuborish yoki qo'lda WebApp."""
    rows = []
    if WEBAPP_URL:
        rows.append([KeyboardButton(
            "✍️ Qo'lda to'liq kiritish",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/create_rich?v={WEBAPP_VERSION}"),
        )])
    rows.append([KeyboardButton("Ortga")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ─────────────────────────────── Entry ───────────────────────────────

@membership_required
async def file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'📸 Fayldan test' — fayl kutish holatini boshlash."""
    # Hozircha bu funksiya faqat adminlar uchun
    from handlers.admin import is_admin
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "🔒 Bu funksiya hozircha faqat adminlar uchun.",
            reply_markup=main_menu_keyboard(update.effective_user.id),
        )
        return ConversationHandler.END

    # Avvalgi tugallanmagan rasm-biriktirish holatini tozalash
    context.user_data.pop("img_test_id", None)
    context.user_data.pop("img_num", None)
    context.user_data.pop("ai_questions", None)

    await update.message.reply_html(
        "📸 <b>Fayldan test yaratish</b>\n\n"
        "Savollar <b>va javoblar kaliti</b> bo'lgan <b>PDF, DOCX yoki rasm</b> yuboring — "
        "AI uni o'qib testni avtomatik tuzadi.\n\n"
        "💡 Savol ichidagi rasm/diagrammalar bo'lsa, AI ularni belgilaydi va "
        "keyin ulardan rasm so'rayman.\n\n"
        "✍️ Yoki savollarni o'zingiz yozmoqchi bo'lsangiz — pastdagi "
        "<b>Qo'lda to'liq kiritish</b> tugmasini bosing.\n\n"
        "❌ Bekor qilish: /cancel yoki Ortga",
        reply_markup=_ai_keyboard(),
    )
    return WAITING_FILE


# ──────────────────────────── Fayl qabul qilish ────────────────────────────

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """PDF/rasm faylni qabul qilib, AI orqali ajratish."""
    message = update.message

    # Fayl turini va hajmini aniqlash
    file_id = None
    mime = None
    if message.document:
        doc = message.document
        raw_mime = (doc.mime_type or "").lower()
        fname = (doc.file_name or "").lower()
        size = doc.file_size or 0
        is_docx = raw_mime == DOCX_MIME or fname.endswith(".docx")
        if not (raw_mime == "application/pdf" or raw_mime.startswith("image/") or is_docx):
            await message.reply_text(
                "❌ Faqat PDF, DOCX yoki rasm yuboring. Qaytadan urinib ko'ring yoki /cancel."
            )
            return WAITING_FILE
        if size > MAX_FILE_BYTES:
            await message.reply_text("❌ Fayl juda katta (20MB dan oshmasligi kerak).")
            return WAITING_FILE
        file_id = doc.file_id
        # docx bo'lsa extraction modulida PDF'ga aylantiriladi
        mime = DOCX_MIME if is_docx else raw_mime
    elif message.photo:
        mime = "image/jpeg"
        file_id = message.photo[-1].file_id
    else:
        await message.reply_text("❌ PDF, DOCX yoki rasm yuboring.")
        return WAITING_FILE

    status_msg = await message.reply_text("⏳ AI tahlil qilmoqda... (bir necha soniya)")

    # Faylni yuklab olish (vaqtinchalik faylsiz — to'g'ridan-to'g'ri bytes)
    try:
        tg_file = await context.bot.get_file(file_id)
        data = await tg_file.download_as_bytearray()
    except Exception:
        logger.exception("AI CREATE: faylni yuklab bo'lmadi")
        await status_msg.edit_text("❌ Faylni yuklab bo'lmadi. Qaytadan urinib ko'ring.")
        return WAITING_FILE

    # AI ajratish (bloklovchi chaqiruv — alohida thread'da)
    try:
        extractor = get_default_extractor()
        result = await asyncio.to_thread(extractor.extract, bytes(data), mime)
    except ExtractionError as e:
        await status_msg.edit_text(f"❌ {e}\n\nBoshqa fayl yuboring yoki /cancel.")
        return WAITING_FILE
    except Exception as e:
        logger.exception("AI CREATE: kutilmagan extraction xatosi")
        await status_msg.edit_text(f"❌ Tahlilda xatolik: {e}\n\nQaytadan urinib ko'ring yoki /cancel.")
        return WAITING_FILE

    # Savollarni user_data ga saqlash (dict ko'rinishida)
    questions = [asdict(q) for q in result.questions]
    context.user_data["ai_questions"] = questions

    try:
        await status_msg.delete()
    except Exception:
        pass

    missing = _count_missing(questions)
    if missing > 0:
        action_row = [InlineKeyboardButton(
            f"✏️ Javoblarni belgilash ({missing} ta)", callback_data="aicreate_answers"
        )]
    else:
        action_row = [InlineKeyboardButton(
            "✅ Tasdiqlash va yaratish", callback_data="aicreate_confirm"
        )]

    await message.reply_html(
        _build_preview(questions, result.warnings),
        reply_markup=InlineKeyboardMarkup([
            action_row,
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="aicreate_cancel")],
        ]),
    )
    return PREVIEW_CONFIRM


def _build_preview(questions: list, warnings: list) -> str:
    total = len(questions)
    closed = sum(1 for q in questions if q["type"] in ("closed", "closed6"))
    open_n = sum(1 for q in questions if q["type"] == "open")
    img_nums = [q["num"] for q in questions if q.get("has_image")]

    missing = _count_missing(questions)

    lines = [
        "🔍 <b>AI ajratdi — tekshirib tasdiqlang:</b>\n",
        f"❓ Jami: <b>{total}</b> ta savol  (yopiq: {closed}, ochiq: {open_n})",
    ]
    if missing > 0:
        lines.append(
            f"⚠️ <b>{missing} ta savolda javob aniqlanmadi</b> — bu hujjatda javoblar "
            f"kaliti yo'q ko'rinadi. «Javoblarni belgilash» orqali o'zingiz kiritasiz."
        )
    if img_nums:
        lines.append(f"🖼 Rasm kerak: {', '.join(map(str, img_nums))}-savol(lar)")
    lines.append("")

    shown = questions[:_PREVIEW_MAX_QUESTIONS]
    for q in shown:
        ans_raw = str(q.get("answer", "") or "")
        if q["type"] in ("closed", "closed6"):
            ans = escape(ans_raw.upper()) if ans_raw else "—"
        else:
            ans = escape(latex_to_text(ans_raw)) if ans_raw else "—"
        img = " 🖼" if q.get("has_image") else ""
        text = latex_to_text(q.get("text") or "")
        text = text if len(text) <= 60 else text[:57] + "..."
        text = escape(text)
        lines.append(f"<b>{q['num']}.</b> [{q['type']}] → <code>{ans}</code>{img}")
        if text:
            lines.append(f"   <i>{text}</i>")

    if total > _PREVIEW_MAX_QUESTIONS:
        lines.append(f"\n... va yana {total - _PREVIEW_MAX_QUESTIONS} ta savol.")

    if warnings:
        lines.append("\n⚠️ <b>Diqqat:</b>")
        for w in warnings[:8]:
            lines.append(f"  • {escape(w)}")
        if len(warnings) > 8:
            lines.append(f"  • ... va yana {len(warnings) - 8} ta.")

    return "\n".join(lines)


# ──────────────────────────── Tasdiqlash ────────────────────────────

async def _finalize_creation(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, questions: list):
    """Boy testni yaratib, adminga xabar berib, rasm biriktirishni boshlaydi.

    confirm_callback (javoblar to'liq) va javob-kiritish yakuni — ikkalasi chaqiradi.
    """
    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name,
    )
    try:
        test = services.create_rich_test(
            db_user, questions, scoring_mode="simple", source="file"
        )
    except Exception as e:
        logger.exception("AI CREATE: test yaratishda xatolik")
        await context.bot.send_message(chat_id, f"❌ Test yaratishda xatolik: {e}")
        context.user_data.pop("ai_questions", None)
        return None

    context.user_data.pop("ai_questions", None)

    if ADMIN_ID and user.id != ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"📢 <b>Yangi test yaratildi! (AI/fayl)</b>\n\n"
                    f"👤 Yaratuvchi: {db_user.full_name or db_user.username}\n"
                    f"📝 Kod: <code>{test.id}</code>\n"
                    f"❓ Savollar: {test.total_questions} ta"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await context.bot.send_message(
        chat_id, f"✅ <b>Test yaratildi!</b>  Kod: <code>{test.id}</code>", parse_mode="HTML"
    )
    await start_image_collection(context, chat_id, test)
    return test


@membership_required
async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview tasdiqlandi (javoblar to'liq) — testni yaratish."""
    query = update.callback_query
    await query.answer()

    questions = context.user_data.get("ai_questions")
    if not questions:
        await query.message.edit_text("❌ Sessiya muddati tugadi. Qaytadan boshlang.")
        return ConversationHandler.END

    await query.message.edit_text("⏳ Test yaratilmoqda...")
    await _finalize_creation(context, query.message.chat_id, update.effective_user, questions)
    return ConversationHandler.END


# ─────────────────────── Javob-kiritish (kalitsiz hujjat) ───────────────────────

async def _prompt_next_missing(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Keyingi javobsiz savolni so'rash. Hammasi to'lgan bo'lsa None qaytaradi."""
    questions = context.user_data.get("ai_questions", [])
    idx = _first_missing_index(questions)
    if idx is None:
        return None

    q = questions[idx]
    # Qaysi savol so'ralayotganini eslab qolamiz (ochiq javob matni shu savolga yoziladi)
    context.user_data["answer_pending_num"] = q["num"]
    remaining = _count_missing(questions)
    head = (
        f"✏️ <b>{q['num']}-savol javobini belgilang</b>  (yana {remaining} ta)\n\n"
        f"{escape(latex_to_text(q.get('text') or ''))}"
    )
    cancel_btn = InlineKeyboardButton("❌ Bekor qilish", callback_data="aicreate_cancel")

    if q["type"] in ("closed", "closed6"):
        letters = _answer_letters(q)
        opts = q.get("options") or {}
        opt_lines = [f"{l.upper()}) {escape(latex_to_text(str(opts.get(l, ''))))}" for l in letters]
        text = head + "\n\n" + "\n".join(opt_lines)
        # callback'da savol raqami ham bor — javob aynan shu savolga yoziladi
        buttons = [InlineKeyboardButton(l.upper(), callback_data=f"ansset_{q['num']}_{l}") for l in letters]
        rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
        rows.append([cancel_btn])
        await context.bot.send_message(chat_id, text, parse_mode="HTML",
                                       reply_markup=InlineKeyboardMarkup(rows))
    else:
        await context.bot.send_message(
            chat_id, head + "\n\n💬 To'g'ri javobni matn ko'rinishida yuboring.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[cancel_btn]]),
        )
    return idx


@membership_required
async def start_answer_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«Javoblarni belgilash» — javob-kiritishni boshlash."""
    query = update.callback_query
    await query.answer()

    questions = context.user_data.get("ai_questions")
    if not questions:
        await query.message.edit_text("❌ Sessiya muddati tugadi. Qaytadan boshlang.")
        return ConversationHandler.END

    await query.message.edit_text("✏️ Javoblarni birma-bir belgilaymiz...")
    idx = await _prompt_next_missing(context, query.message.chat_id)
    if idx is None:
        await _finalize_creation(context, query.message.chat_id, update.effective_user, questions)
        return ConversationHandler.END
    return ANSWER_ENTRY


async def _advance_or_finish(update, context, questions) -> int:
    """Keyingi javobsiz savolga o'tish yoki hammasi tugagan bo'lsa testni yaratish."""
    chat_id = update.effective_chat.id
    if _first_missing_index(questions) is None:
        await _finalize_creation(context, chat_id, update.effective_user, questions)
        return ConversationHandler.END
    await _prompt_next_missing(context, chat_id)
    return ANSWER_ENTRY


async def answer_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yopiq savol javobi tanlandi (inline harf) — aynan callback'dagi savolga yoziladi."""
    query = update.callback_query
    parts = query.data.split("_")  # ansset_<num>_<letter>
    if len(parts) != 3 or not parts[1].isdigit():
        await query.answer("Xato", show_alert=True)
        return ANSWER_ENTRY
    num = int(parts[1])
    letter = parts[2]

    questions = context.user_data.get("ai_questions")
    if not questions:
        await query.answer("Sessiya tugadi", show_alert=True)
        return ConversationHandler.END

    q = next((x for x in questions if x.get("num") == num), None)
    if q is None:
        await query.answer("Savol topilmadi", show_alert=True)
        return ANSWER_ENTRY
    if q["type"] not in ("closed", "closed6"):
        await query.answer("Bu savol uchun matn yuboring", show_alert=True)
        return ANSWER_ENTRY
    if letter not in _answer_letters(q):
        await query.answer("Noto'g'ri variant", show_alert=True)
        return ANSWER_ENTRY

    q["answer"] = letter
    await query.answer(f"{num}: {letter.upper()} ✓")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    return await _advance_or_finish(update, context, questions)


async def answer_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ochiq savol javobi matn ko'rinishida kiritildi — so'ralgan savolga yoziladi."""
    text = (update.message.text or "").strip()
    if text.lower() in ("ortga", "❌ bekor qilish"):
        return await cancel_command(update, context)

    questions = context.user_data.get("ai_questions")
    if not questions:
        await update.message.reply_text("❌ Sessiya tugadi.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    # So'ralgan savolni num bo'yicha topamiz (first-missing emas — aniqlik uchun)
    num = context.user_data.get("answer_pending_num")
    q = next((x for x in questions if x.get("num") == num), None)
    if q is None:
        idx = _first_missing_index(questions)
        q = questions[idx] if idx is not None else None
    if q is None:
        await _finalize_creation(context, update.message.chat_id, update.effective_user, questions)
        return ConversationHandler.END

    if q["type"] in ("closed", "closed6"):
        await update.message.reply_text("Bu savol uchun yuqoridagi tugmalardan birini tanlang.")
        return ANSWER_ENTRY
    if not text:
        await update.message.reply_text("Javob bo'sh bo'lmasin.")
        return ANSWER_ENTRY

    q["answer"] = text
    context.user_data.pop("answer_pending_num", None)
    return await _advance_or_finish(update, context, questions)


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview'da bekor qilish."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("ai_questions", None)
    await query.message.edit_text("❌ Bekor qilindi.")
    await query.message.reply_text("🏠 Asosiy menyu:", reply_markup=main_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel yoki 'Ortga' — oqimni bekor qilish."""
    context.user_data.pop("ai_questions", None)
    await update.message.reply_text(
        "❌ Fayldan test yaratish bekor qilindi.",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    return ConversationHandler.END


async def _ortga_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WAITING_FILE da 'Ortga' matni."""
    if (update.message.text or "").strip().lower() in ("ortga", "❌ bekor qilish"):
        return await cancel_command(update, context)
    # Aks holda — yana fayl kutamiz
    await update.message.reply_text(
        "📎 Iltimos, PDF yoki rasm yuboring (yoki /cancel)."
    )
    return WAITING_FILE


# ───────────────────── Manual (WebApp) rich_test_created ─────────────────────

async def handle_rich_test_created(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   test_id: int) -> None:
    """WebApp (qo'lda to'liq) testni yaratgach, rasm biriktirishni boshlash.

    Bot tomonida (suhbat ichida yoki global routerda) chaqiriladi.
    """
    user = update.effective_user
    try:
        test = Test.get_by_id(int(test_id))
    except (ValueError, Test.DoesNotExist):
        await update.message.reply_text(
            "❌ Test topilmadi.", reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return

    # Faqat egasi davom ettira oladi
    if not user or test.creator.telegram_id != user.id:
        await update.message.reply_text(
            "❌ Bu test sizga tegishli emas.", reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return

    # Adminga xabar (AI oqimi bilan bir xil — boshqa odam yaratganda)
    if ADMIN_ID and user.id != ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"📢 <b>Yangi test yaratildi! (qo'lda)</b>\n\n"
                    f"👤 Yaratuvchi: {test.creator.full_name or test.creator.username}\n"
                    f"📝 Kod: <code>{test.id}</code>\n"
                    f"❓ Savollar: {test.total_questions} ta"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await update.message.reply_html(
        f"✅ <b>Test yaratildi!</b>  Kod: <code>{test.id}</code>"
    )
    await start_image_collection(context, update.message.chat_id, test)


async def webapp_rich_created_in_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WAITING_FILE state ichida WebApp'dan kelgan rich_test_created."""
    try:
        data = json.loads(update.message.web_app_data.data)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return WAITING_FILE

    if data.get("action") != "rich_test_created":
        return WAITING_FILE

    test_id = data.get("test_id")
    if not str(test_id).isdigit():
        await update.message.reply_text("❌ Noto'g'ri test ID.")
        return ConversationHandler.END

    await handle_rich_test_created(update, context, int(test_id))
    return ConversationHandler.END


# ─────────────────────── Rasm biriktirish (global) ───────────────────────

def _image_collection_view(test: Test):
    """Rasm biriktirish ko'rinishi: (text, keyboard|None). None = rasm kerak emas."""
    pending = services.questions_needing_images(test)
    all_img = services.image_question_nums(test)

    if not all_img:
        return None, None

    done = [n for n in all_img if n not in {q.num for q in pending}]

    text_lines = [
        "🖼 <b>Rasm biriktirish</b>\n",
        f"Quyidagi savollarda rasm bor. Har biriga rasm yuklash uchun raqamini bosing.\n",
    ]
    if done:
        text_lines.append(f"✅ Tayyor: {', '.join(map(str, done))}")
    if pending:
        text_lines.append(f"⏳ Kutilmoqda: {', '.join(str(q.num) for q in pending)}")
    text_lines.append("\nTugatish uchun «✅ Tayyor» ni bosing.")

    rows = []
    row = []
    for q in pending:
        row.append(InlineKeyboardButton(
            f"🖼 {q.num}-savol", callback_data=f"aiimgp_{test.id}_{q.num}"
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✅ Tayyor", callback_data=f"aiimgd_{test.id}")])

    return "\n".join(text_lines), InlineKeyboardMarkup(rows)


async def start_image_collection(context: ContextTypes.DEFAULT_TYPE, chat_id: int, test: Test):
    """Rasm biriktirish bosqichini boshlash yoki (rasm kerak bo'lmasa) yakunlash."""
    text, keyboard = _image_collection_view(test)

    if keyboard is None:
        # Rasm kerak emas — darrov yakunlaymiz
        await _finalize(context, chat_id, test)
        return

    context.user_data["img_test_id"] = test.id
    context.user_data.pop("img_num", None)
    await context.bot.send_message(
        chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=keyboard
    )


async def _finalize(context: ContextTypes.DEFAULT_TYPE, chat_id: int, test: Test):
    """Yakuniy xabar — test kodi va ulashish tugmalari."""
    context.user_data.pop("img_test_id", None)
    context.user_data.pop("img_num", None)

    try:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = ""

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🎉 <b>Test tayyor!</b>\n\n"
            f"📝 Test kodi: <code>{test.id}</code>\n"
            f"❓ Savollar soni: {test.total_questions} ta\n\n"
            f"Bu kodni boshqalarga yuboring!"
        ),
        parse_mode="HTML",
        reply_markup=test_created_keyboard(str(test.id), bot_username, test.total_questions),
    )
    await context.bot.send_message(
        chat_id=chat_id, text="🏠 Asosiy menyu:", reply_markup=main_menu_keyboard(chat_id)
    )


def _load_owned_test(test_id: int, user_id: int):
    """Testni yuklab, egasini tekshirish. (test|None, xato_matni|None)"""
    try:
        test = Test.get_by_id(int(test_id))
    except (ValueError, Test.DoesNotExist):
        return None, "Test topilmadi."
    if test.creator.telegram_id != user_id:
        return None, "Bu test sizga tegishli emas."
    return test, None


async def image_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rasm biriktirish uchun savol raqami tanlandi."""
    query = update.callback_query
    try:
        _, test_id, num = query.data.split("_")  # aiimgp_<tid>_<num>
        test_id, num = int(test_id), int(num)
    except (ValueError, AttributeError):
        await query.answer("❌ Xato", show_alert=True)
        return

    test, err = _load_owned_test(test_id, update.effective_user.id)
    if err:
        await query.answer(f"❌ {err}", show_alert=True)
        return

    await query.answer()
    context.user_data["img_test_id"] = test_id
    context.user_data["img_num"] = num

    await query.message.reply_text(
        f"📷 {num}-savol uchun rasmni yuboring.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data=f"aiimgs_{test_id}")
        ]]),
    )


async def image_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Joriy savol rasmini o'tkazib yuborish — ro'yxatga qaytish."""
    query = update.callback_query
    try:
        test_id = int(query.data.split("_")[1])  # aiimgs_<tid>
    except (ValueError, IndexError):
        await query.answer("❌ Xato", show_alert=True)
        return

    test, err = _load_owned_test(test_id, update.effective_user.id)
    if err:
        await query.answer(f"❌ {err}", show_alert=True)
        return

    await query.answer("O'tkazib yuborildi")
    context.user_data.pop("img_num", None)
    text, keyboard = _image_collection_view(test)
    if keyboard is None:
        await _finalize(context, query.message.chat_id, test)
    else:
        await query.message.reply_html(text, reply_markup=keyboard)


async def image_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«Tayyor» — rasm biriktirishni yakunlash."""
    query = update.callback_query
    try:
        test_id = int(query.data.split("_")[1])  # aiimgd_<tid>
    except (ValueError, IndexError):
        await query.answer("❌ Xato", show_alert=True)
        return

    test, err = _load_owned_test(test_id, update.effective_user.id)
    if err:
        await query.answer(f"❌ {err}", show_alert=True)
        return

    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _finalize(context, query.message.chat_id, test)


async def image_receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tanlangan savolga rasmni biriktirish (global, user_data bilan boshqariladi)."""
    test_id = context.user_data.get("img_test_id")
    num = context.user_data.get("img_num")

    # Rasm biriktirish umuman kutilmayotgan bo'lsa — jim e'tibor bermaymiz
    if not test_id:
        return

    test, err = _load_owned_test(test_id, update.effective_user.id)
    if err:
        # Eskirgan/begona holat — tozalaymiz
        context.user_data.pop("img_test_id", None)
        context.user_data.pop("img_num", None)
        return

    # Holat bor, lekin qaysi savol ekani tanlanmagan — yo'l-yo'riq beramiz
    if not num:
        await update.message.reply_text(
            "📷 Avval yuqoridagi ro'yxatdan savol raqamini tanlang."
        )
        return

    if not update.message.photo:
        await update.message.reply_text("❌ Iltimos, rasm yuboring.")
        return

    file_id = update.message.photo[-1].file_id
    q = Question.get_or_none((Question.test == test) & (Question.num == num))
    if q:
        q.image_file_id = file_id
        q.has_image = True
        q.save()

    context.user_data.pop("img_num", None)

    await update.message.reply_text(f"✅ {num}-savol rasmi saqlandi.")

    text, keyboard = _image_collection_view(test)
    if keyboard is None:
        await _finalize(context, update.message.chat_id, test)
    else:
        await update.message.reply_html(text, reply_markup=keyboard)


# ─────────────────────────────── Handlers ───────────────────────────────

def get_handlers():
    """AI suhbat + global rasm-biriktirish handlerlari.

    Tartib muhim: suhbat (WAITING_FILE da photo/document handleri bor) global
    photo handleridan OLDIN ro'yxatga olinishi kerak.
    """
    conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r"^📸 Fayldan test$"),
                file_command,
            ),
        ],
        states={
            WAITING_FILE: [
                MessageHandler(
                    (filters.Document.ALL | filters.PHOTO) & filters.ChatType.PRIVATE,
                    receive_file,
                ),
                MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_rich_created_in_conv),
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, _ortga_handler),
            ],
            PREVIEW_CONFIRM: [
                CallbackQueryHandler(confirm_callback, pattern=r"^aicreate_confirm$"),
                CallbackQueryHandler(start_answer_entry, pattern=r"^aicreate_answers$"),
                CallbackQueryHandler(cancel_callback, pattern=r"^aicreate_cancel$"),
            ],
            ANSWER_ENTRY: [
                CallbackQueryHandler(answer_pick_callback, pattern=r"^ansset_\d+_[a-f]$"),
                CallbackQueryHandler(cancel_callback, pattern=r"^aicreate_cancel$"),
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    answer_type_handler,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command, filters=filters.ChatType.PRIVATE),
        ],
        allow_reentry=True,
    )

    return [
        conv,
        # Global rasm-biriktirish handlerlari (suhbatdan tashqari)
        CallbackQueryHandler(image_pick_callback, pattern=r"^aiimgp_\d+_\d+$"),
        CallbackQueryHandler(image_skip_callback, pattern=r"^aiimgs_\d+$"),
        CallbackQueryHandler(image_done_callback, pattern=r"^aiimgd_\d+$"),
        MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, image_receive_photo),
    ]

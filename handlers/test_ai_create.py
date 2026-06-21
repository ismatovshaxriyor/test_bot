"""Fayldan (PDF/rasm) AI orqali test yaratish + rasm biriktirish.

Oqim (AI/fayl):
  1. Menyu "📸 Fayldan test" → WAITING_FILE
  2. Foydalanuvchi PDF/DOCX/rasm yuboradi → AI ajratadi → FILLING
  3. FILLING: to'ldirilishi kerak (javobi yo'q YOKI AI rasm bor degan) har bir savol
     birma-bir so'raladi — avval javobi, keyin (kerak bo'lsa) rasmi; navbat bilan
     keyingisiga o'tiladi. AI rasm bor deb xato belgilagan bo'lsa egasi «Rasm yo'q»
     deydi. Oxirida yakuniy tasdiq → test BIR MARTA yaratiladi (rasm bilan birga).

Qo'lda (WebApp) oqimi esa testni API orqali yaratadi, so'ng rasm biriktirish
suhbatdan TASHQARIDA, global handlerlar + user_data orqali ishlaydi
(handle_rich_test_created → start_image_collection).
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
FILLING = 1          # javob/rasm to'ldirish (savol-ma-savol)

MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram getFile cheki ~20MB


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


def _needs_image(q: dict) -> bool:
    """AI rasm kerak deb belgilagan, lekin hali hal qilinmagan (rasm/skip) savol."""
    return bool(q.get("has_image")) and not q.get("image_decided")


def _count_pending(questions: list) -> int:
    """To'ldirilishi kerak savollar soni (javob yo'q yoki rasm hali hal qilinmagan)."""
    return sum(1 for q in questions if _is_answer_missing(q) or _needs_image(q))


def _next_action(questions: list):
    """Keyingi to'ldirilishi kerak (savol, amal). amal: 'answer' | 'image'.

    Har savol oldin javobini, keyin (kerak bo'lsa) rasmini oladi — shu sabab
    bitta savol to'liq tugagach keyingisiga o'tiladi.
    """
    for q in questions:
        if _is_answer_missing(q):
            return q, "answer"
        if _needs_image(q):
            return q, "image"
    return None, None


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

    total = len(questions)
    pending = _count_pending(questions)
    closed = sum(1 for q in questions if q["type"] in ("closed", "closed6"))
    open_n = sum(1 for q in questions if q["type"] == "open")

    # AI yopiq savol uchun variantlarni topa olmagan bo'lishi mumkin — bu wizard'da
    # so'ralmaydi (javob bor), shuning uchun bir marta qisqa ogohlantirib qo'yamiz.
    no_opts = [q["num"] for q in questions
               if q["type"] in ("closed", "closed6") and not q.get("options")]
    warn = (f"\n\n⚠️ Variantlari topilmagan savollar: {', '.join(map(str, no_opts))} — "
            f"yaratilgandan keyin tekshiring." if no_opts else "")

    if pending == 0:
        # Hammasi tayyor — to'g'ridan-to'g'ri yakuniy tasdiqqa o'tamiz
        await message.reply_html(
            f"🔍 <b>AI {total} ta savol topdi</b>  (yopiq: {closed}, ochiq: {open_n})\n"
            f"Hamma javob aniqlandi, rasm kerak emas.{warn}"
        )
        await _show_final_confirm(context, message.chat_id, questions)
        return FILLING

    await message.reply_html(
        f"🔍 <b>AI {total} ta savol topdi</b>  (yopiq: {closed}, ochiq: {open_n})\n\n"
        f"Endi <b>{pending} ta savolni</b> birgalikda to'ldiramiz — har biriga "
        f"javobini (kerak bo'lsa rasmini ham) belgilab, navbat bilan keyingisiga o'tamiz.{warn}"
    )
    await _prompt_next_action(context, message.chat_id)
    return FILLING


# ──────────────────────── Savol-ma-savol to'ldirish ────────────────────────

def _q_text_short(q: dict, limit: int = 200) -> str:
    """Savol matnini (LaTeX→o'qiladigan) qisqartirilgan, HTML-escape qilingan ko'rinishi."""
    text = latex_to_text(q.get("text") or "")
    if len(text) > limit:
        text = text[:limit - 1] + "…"
    return escape(text)


async def _prompt_next_action(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Keyingi to'ldirilishi kerak savolni so'rash. Hammasi tugagan bo'lsa None qaytaradi."""
    questions = context.user_data.get("ai_questions", [])
    q, action = _next_action(questions)
    if q is None:
        return None

    remaining = _count_pending(questions)  # joriy savolni ham hisoblaydi → "qoldi"
    cancel_btn = InlineKeyboardButton("❌ Bekor qilish", callback_data="aicreate_cancel")
    head = f"<b>{q['num']}-savol</b>  (qoldi: {remaining})\n\n{_q_text_short(q)}"

    if action == "answer":
        if q["type"] in ("closed", "closed6"):
            letters = _answer_letters(q)
            opts = q.get("options") or {}
            opt_lines = [
                f"{l.upper()}) {escape(latex_to_text(str(opts.get(l, ''))))}"
                for l in letters if opts.get(l)
            ]
            body = ("\n\n" + "\n".join(opt_lines)) if opt_lines else ""
            buttons = [
                InlineKeyboardButton(l.upper(), callback_data=f"ansset_{q['num']}_{l}")
                for l in letters
            ]
            rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
            rows.append([cancel_btn])
            await context.bot.send_message(
                chat_id,
                f"✏️ {head}{body}\n\n✅ To'g'ri javobni tanlang:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(rows),
            )
        else:
            await context.bot.send_message(
                chat_id,
                f"✏️ {head}\n\n💬 To'g'ri javobni matn ko'rinishida yuboring.\n"
                f"<i>Agar bu aslida variantli (A–E) savol bo'lsa — pastdagi tugmani bosing.</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔤 Variantli savol (A–E)",
                                          callback_data=f"aimkclosed_{q['num']}")],
                    [cancel_btn],
                ]),
            )
    else:  # image
        await context.bot.send_message(
            chat_id,
            f"🖼 {head}\n\n📷 Shu savol uchun <b>rasmni yuboring</b>.\n"
            f"Agar bu savolda aslida rasm bo'lmasa (AI xato belgilagan bo'lsa) — "
            f"«🚫 Rasm yo'q» tugmasini bosing.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚫 Rasm yo'q", callback_data=f"aiskip_{q['num']}")],
                [cancel_btn],
            ]),
        )
    return action


async def _advance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Keyingi amalni so'rash yoki hammasi tugagan bo'lsa yakuniy tasdiqni ko'rsatish."""
    chat_id = update.effective_chat.id
    action = await _prompt_next_action(context, chat_id)
    if action is None:
        questions = context.user_data.get("ai_questions", [])
        await _show_final_confirm(context, chat_id, questions)
    return FILLING


async def _show_final_confirm(context: ContextTypes.DEFAULT_TYPE, chat_id: int, questions: list):
    """To'ldirish tugagach — yakuniy ko'rib chiqish + testni yaratish tugmasi."""
    total = len(questions)
    closed = sum(1 for q in questions if q["type"] in ("closed", "closed6"))
    open_n = sum(1 for q in questions if q["type"] == "open")
    img_nums = [q["num"] for q in questions if q.get("image_file_id")]

    lines = [
        "✅ <b>Hammasi to'ldirildi — tasdiqlang</b>\n",
        f"❓ Jami: <b>{total}</b> ta savol  (yopiq: {closed}, ochiq: {open_n})",
        (f"🖼 Rasmli: {', '.join(map(str, img_nums))}-savol(lar)" if img_nums
         else "🖼 Rasm biriktirilmadi"),
    ]
    await context.bot.send_message(
        chat_id, "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Testni yaratish", callback_data="aicreate_confirm")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="aicreate_cancel")],
        ]),
    )


# ──────────────────────────── Tasdiqlash ────────────────────────────

async def _finalize_creation(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, questions: list):
    """Boy testni yaratib, adminga xabar berib, rasm biriktirishni boshlaydi.

    confirm_callback (javoblar to'liq) va javob-kiritish yakuni — ikkalasi chaqiradi.
    """
    # Rasm holatini yakuniy haqiqatga keltiramiz: rasm biriktirilgan bo'lsa True;
    # AI rasm bor degan, lekin egasi «Rasm yo'q» degan savol — False bo'ladi.
    for q in questions:
        q["has_image"] = bool(q.get("image_file_id"))

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
                    f"👤 Yaratuvchi: {escape(db_user.full_name or db_user.username or '')}\n"
                    f"📝 Kod: <code>{test.id}</code>\n"
                    f"❓ Savollar: {test.total_questions} ta"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Rasm allaqachon suhbat ichida yig'ilgan — to'g'ridan-to'g'ri yakunlaymiz.
    await _finalize(context, chat_id, test)
    return test


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yakuniy tasdiq — testni yaratish.

    A'zolik darvozasi kirishda (`file_command`) tekshirilgan; bu yerda
    @membership_required QO'YILMAYDI — aks holda a'zolik keshi muddati o'tsa
    yakuniy o'tish None qaytarib, tugma «osilib» qolardi.
    """
    query = update.callback_query
    await query.answer()

    # Re-entrancy himoyasi: tugma ikki marta tez bosilsa dublikat test yaratilmasin.
    # Savollarni darrov olib (pop) qo'yamiz — ikkinchi bosish bo'sh topadi va to'xtaydi.
    questions = context.user_data.pop("ai_questions", None)
    if not questions:
        try:
            await query.message.edit_text("❌ Sessiya muddati tugadi. Qaytadan boshlang.")
        except Exception:
            pass
        return ConversationHandler.END

    try:
        await query.message.edit_text("⏳ Test yaratilmoqda...")
    except Exception:
        pass
    await _finalize_creation(context, update.effective_chat.id, update.effective_user, questions)
    return ConversationHandler.END


# ─────────────────────── Javob/rasm to'ldirish handlerlari ───────────────────────

async def answer_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yopiq savol javobi tanlandi (inline harf) — aynan callback'dagi savolga yoziladi."""
    query = update.callback_query
    parts = query.data.split("_")  # ansset_<num>_<letter>
    if len(parts) != 3 or not parts[1].isdigit():
        await query.answer("Xato", show_alert=True)
        return FILLING
    num = int(parts[1])
    letter = parts[2]

    questions = context.user_data.get("ai_questions")
    if not questions:
        await query.answer("Sessiya tugadi", show_alert=True)
        return ConversationHandler.END

    q = next((x for x in questions if x.get("num") == num), None)
    if q is None:
        await query.answer("Savol topilmadi", show_alert=True)
        return FILLING
    if q["type"] not in ("closed", "closed6"):
        await query.answer("Bu savol uchun matn yuboring", show_alert=True)
        return FILLING
    if letter not in _answer_letters(q):
        await query.answer("Noto'g'ri variant", show_alert=True)
        return FILLING
    if not _is_answer_missing(q):
        # Eskirgan/takroriy tugma bosildi — javob allaqachon belgilangan, qayta yozmaymiz
        await query.answer("Bu savol allaqachon javoblangan")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return FILLING

    q["answer"] = letter
    await query.answer(f"{num}: {letter.upper()} ✓")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    return await _advance(update, context)


async def answer_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Matn xabari — ochiq javob yoki 'Ortga'. Joriy amalni _next_action belgilaydi."""
    text = (update.message.text or "").strip()

    questions = context.user_data.get("ai_questions")
    if not questions:
        await update.message.reply_text(
            "❌ Sessiya tugadi.", reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    # Manba — _next_action: hozir aynan nimani kutayotganimizni shu aytadi.
    q, action = _next_action(questions)
    is_open_answer = (q is not None and action == "answer"
                      and q["type"] not in ("closed", "closed6"))

    # 'Ortga'/'Bekor' → bekor qilish, FAQAT ochiq javob kutilmayotgan bo'lsa
    # (ochiq savol javobi aynan "ortga" bo'lishi mumkin — uni bekor deb hisoblamaymiz;
    #  bunday paytda bekor qilish uchun /cancel yoki «❌ Bekor qilish» tugmasi bor).
    if text.lower() in ("ortga", "❌ bekor qilish") and not is_open_answer:
        return await cancel_command(update, context)

    if q is None:
        await update.message.reply_text(
            "✅ Hammasi to'ldirildi — pastdagi «✅ Testni yaratish» tugmasini bosing."
        )
        return FILLING
    if action == "image":
        await update.message.reply_text(
            "📷 Hozir rasm kutilmoqda — rasmni yuboring yoki «🚫 Rasm yo'q» tugmasini bosing."
        )
        return FILLING
    if q["type"] in ("closed", "closed6"):
        await update.message.reply_text("Bu savol uchun yuqoridagi tugmalardan birini tanlang.")
        return FILLING
    if not text:
        await update.message.reply_text("Javob bo'sh bo'lmasin.")
        return FILLING

    q["answer"] = text
    return await _advance(update, context)


async def wizard_receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suhbat ichida rasm — joriy savolga biriktiriladi (image amali kutilganda).

    Oddiy rasm ham, rasm-fayl (Document.IMAGE) ham qabul qilinadi.
    """
    questions = context.user_data.get("ai_questions")
    if not questions:
        return ConversationHandler.END

    q, action = _next_action(questions)
    if q is None:
        await update.message.reply_text(
            "✅ Hammasi to'ldirildi — pastdagi «✅ Testni yaratish» tugmasini bosing."
        )
        return FILLING
    if action != "image":
        await update.message.reply_text(
            "ℹ️ Hozir rasm kutilmayapti. Avval so'ralgan javobni kiriting."
        )
        return FILLING

    # file_id: oddiy rasm yoki rasm-fayl (mime image/*)
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        file_id = update.message.document.file_id
    if not file_id:
        await update.message.reply_text("❌ Iltimos, rasm yuboring.")
        return FILLING

    q["image_file_id"] = file_id
    q["image_decided"] = True
    await update.message.reply_text(f"✅ {q['num']}-savol rasmi qabul qilindi.")
    return await _advance(update, context)


async def wizard_image_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«🚫 Rasm yo'q» — joriy savolda rasm yo'q deb belgilash (AI xatosini tuzatish)."""
    query = update.callback_query
    parts = query.data.split("_")  # aiskip_<num>
    if len(parts) != 2 or not parts[1].isdigit():
        await query.answer("Xato", show_alert=True)
        return FILLING
    num = int(parts[1])

    questions = context.user_data.get("ai_questions")
    if not questions:
        await query.answer("Sessiya tugadi", show_alert=True)
        return ConversationHandler.END

    q = next((x for x in questions if x.get("num") == num), None)
    cur, action = _next_action(questions)

    # Eskirgan/takroriy bosish himoyasi: faqat hozir AYNAN shu savol uchun rasm
    # kutilayotgan bo'lsa skip qilamiz. Aks holda (rasm allaqachon biriktirilgan yoki
    # navbat boshqa savolda) tegmaymiz — yuborilgan rasm jim yo'qolib qolmasin.
    is_current_image = (q is not None and cur is not None
                        and action == "image" and cur.get("num") == num)
    if not is_current_image or q.get("image_file_id"):
        await query.answer("Bu savol allaqachon hal qilingan")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return FILLING

    q["image_decided"] = True
    q["image_file_id"] = None
    await query.answer("Rasm o'tkazib yuborildi")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    return await _advance(update, context)


async def wizard_make_closed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«🔤 Variantli savol» — AI ochiq deb xato qilgan savolni yopiq (A–F) ga o'tkazadi.

    Ko'p ustunli hujjatda variantlar savol matnidan ajralib qolsa, AI uni "open"
    deb belgilashi mumkin. Bu yerda egasi uni variantli savolga aylantirib, to'g'ri
    javob harfini tanlaydi (variant matnlari saqlanmaydi — javob harf bo'yicha baholanadi).
    """
    query = update.callback_query
    parts = query.data.split("_")  # aimkclosed_<num>
    if len(parts) != 2 or not parts[1].isdigit():
        await query.answer("Xato", show_alert=True)
        return FILLING
    num = int(parts[1])

    questions = context.user_data.get("ai_questions")
    if not questions:
        await query.answer("Sessiya tugadi", show_alert=True)
        return ConversationHandler.END

    q = next((x for x in questions if x.get("num") == num), None)
    if q is None:
        await query.answer("Savol topilmadi", show_alert=True)
        return FILLING

    q["type"] = "closed6"   # A–F tugmalari ko'rsatiladi (5-6 variantni qoplaydi)
    q["answer"] = ""        # javob endi harf — qaytadan so'raymiz
    await query.answer("Variantli savolga o'tkazildi")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    return await _advance(update, context)


async def wizard_other_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """FILLING ichidagi qo'llab-quvvatlanmaydigan media (stiker/ovoz/video/h.k.) — yo'l-yo'riq."""
    questions = context.user_data.get("ai_questions")
    if not questions:
        return ConversationHandler.END

    q, action = _next_action(questions)
    if q is not None and action == "image":
        await update.message.reply_text(
            "📷 Rasmni oddiy rasm (yoki rasm-fayl) sifatida yuboring, "
            "yoki «🚫 Rasm yo'q» tugmasini bosing."
        )
    else:
        await update.message.reply_text(
            "ℹ️ Bu turdagi xabar qabul qilinmaydi. Javobni tugma yoki matn bilan kiriting."
        )
    return FILLING


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview'da bekor qilish."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("ai_questions", None)
    try:
        await query.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        pass
    await context.bot.send_message(
        update.effective_chat.id, "🏠 Asosiy menyu:",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
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
                    f"👤 Yaratuvchi: {escape(test.creator.full_name or test.creator.username or '')}\n"
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
            FILLING: [
                CallbackQueryHandler(answer_pick_callback, pattern=r"^ansset_\d+_[a-f]$"),
                CallbackQueryHandler(wizard_image_skip_callback, pattern=r"^aiskip_\d+$"),
                CallbackQueryHandler(wizard_make_closed_callback, pattern=r"^aimkclosed_\d+$"),
                CallbackQueryHandler(confirm_callback, pattern=r"^aicreate_confirm$"),
                CallbackQueryHandler(cancel_callback, pattern=r"^aicreate_cancel$"),
                MessageHandler(
                    (filters.PHOTO | filters.Document.IMAGE) & filters.ChatType.PRIVATE,
                    wizard_receive_photo,
                ),
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    answer_type_handler,
                ),
                # Qolgan media (stiker/ovoz/video/rasm bo'lmagan fayl) — yo'l-yo'riq beramiz
                # (service xabarlarni emas: ular global routerga o'tsin).
                MessageHandler(
                    filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
                    wizard_other_media,
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

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
from ai_extract import get_default_extractor, ExtractionError
import services

logger = logging.getLogger(__name__)

# Conversation states
WAITING_FILE = 0
PREVIEW_CONFIRM = 1

MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram getFile cheki ~20MB
_PREVIEW_MAX_QUESTIONS = 25         # preview'da ko'rsatiladigan maksimal savol


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
    # Avvalgi tugallanmagan rasm-biriktirish holatini tozalash
    context.user_data.pop("img_test_id", None)
    context.user_data.pop("img_num", None)
    context.user_data.pop("ai_questions", None)

    await update.message.reply_html(
        "📸 <b>Fayldan test yaratish</b>\n\n"
        "Savollar <b>va javoblar kaliti</b> bo'lgan <b>PDF yoki rasm</b> yuboring — "
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
        mime = (message.document.mime_type or "").lower()
        size = message.document.file_size or 0
        if not (mime == "application/pdf" or mime.startswith("image/")):
            await message.reply_text(
                "❌ Faqat PDF yoki rasm yuboring. Qaytadan urinib ko'ring yoki /cancel."
            )
            return WAITING_FILE
        if size > MAX_FILE_BYTES:
            await message.reply_text("❌ Fayl juda katta (20MB dan oshmasligi kerak).")
            return WAITING_FILE
        file_id = message.document.file_id
    elif message.photo:
        mime = "image/jpeg"
        file_id = message.photo[-1].file_id
    else:
        await message.reply_text("❌ PDF yoki rasm yuboring.")
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

    await message.reply_html(
        _build_preview(questions, result.warnings),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Tasdiqlash va yaratish", callback_data="aicreate_confirm")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="aicreate_cancel")],
        ]),
    )
    return PREVIEW_CONFIRM


def _build_preview(questions: list, warnings: list) -> str:
    total = len(questions)
    closed = sum(1 for q in questions if q["type"] in ("closed", "closed6"))
    open_n = sum(1 for q in questions if q["type"] == "open")
    img_nums = [q["num"] for q in questions if q.get("has_image")]

    lines = [
        "🔍 <b>AI ajratdi — tekshirib tasdiqlang:</b>\n",
        f"❓ Jami: <b>{total}</b> ta savol  (yopiq: {closed}, ochiq: {open_n})",
    ]
    if img_nums:
        lines.append(f"🖼 Rasm kerak: {', '.join(map(str, img_nums))}-savol(lar)")
    lines.append("")

    shown = questions[:_PREVIEW_MAX_QUESTIONS]
    for q in shown:
        ans = escape(str(q.get("answer", "") or "—"))
        if q["type"] in ("closed", "closed6"):
            ans = ans.upper()
        img = " 🖼" if q.get("has_image") else ""
        text = q.get("text") or ""
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

@membership_required
async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview tasdiqlandi — testni yaratish."""
    query = update.callback_query
    await query.answer()

    questions = context.user_data.get("ai_questions")
    if not questions:
        await query.message.edit_text("❌ Sessiya muddati tugadi. Qaytadan boshlang.")
        return ConversationHandler.END

    user = update.effective_user
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
        await query.message.edit_text(f"❌ Test yaratishda xatolik: {e}")
        context.user_data.pop("ai_questions", None)
        return ConversationHandler.END

    context.user_data.pop("ai_questions", None)

    # Adminga xabar (boshqa odam yaratganda)
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

    await query.message.edit_text(
        f"✅ <b>Test yaratildi!</b>  Kod: <code>{test.id}</code>",
        parse_mode="HTML",
    )

    # Rasm biriktirish bosqichini boshlash (global handlerlar davom ettiradi)
    await start_image_collection(context, query.message.chat_id, test)
    return ConversationHandler.END


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview'da bekor qilish."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("ai_questions", None)
    await query.message.edit_text("❌ Bekor qilindi.")
    await query.message.reply_text("🏠 Asosiy menyu:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel yoki 'Ortga' — oqimni bekor qilish."""
    context.user_data.pop("ai_questions", None)
    await update.message.reply_text(
        "❌ Fayldan test yaratish bekor qilindi.",
        reply_markup=main_menu_keyboard(),
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
            "❌ Test topilmadi.", reply_markup=main_menu_keyboard()
        )
        return

    # Faqat egasi davom ettira oladi
    if not user or test.creator.telegram_id != user.id:
        await update.message.reply_text(
            "❌ Bu test sizga tegishli emas.", reply_markup=main_menu_keyboard()
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
        chat_id=chat_id, text="🏠 Asosiy menyu:", reply_markup=main_menu_keyboard()
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
                CallbackQueryHandler(cancel_callback, pattern=r"^aicreate_cancel$"),
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

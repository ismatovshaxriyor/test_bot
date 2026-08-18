"""Test yaratish handleri"""
import logging
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes, CommandHandler,
    MessageHandler, ConversationHandler, CallbackQueryHandler, filters
)

from database import get_or_create_user, User, Test
from config import ADMIN_ID, WEBAPP_URL, WEBAPP_VERSION
from keyboards import test_created_keyboard, main_menu_keyboard
from membership import membership_required
from utils import parse_simple_answers
from handlers.start import _ask_full_name, _is_valid_full_name
import json
import re

logger = logging.getLogger(__name__)

# Conversation states
CHOOSING_MODE = 0
WAITING_ANSWERS = 1
WAITING_FULL_NAME_FOR_CREATE = 2
WAITING_TEST_NAME = 3

MAX_TEST_NAME_LEN = 150


def _normalize_rasch_questions(questions: list) -> list:
    """
    Rash uchun qat'iy format:
    1-32  -> closed4 (A-D)
    33-35 -> closed6 (A-F)
    36-45 -> open2   (har savolga a/b juft javob)
    """
    if len(questions) != 45:
        raise ValueError("Rash testda jami 45 ta savol bo'lishi shart.")

    normalized = []
    for idx, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            raise ValueError(f"{idx}-savol formati noto'g'ri.")

        if idx <= 32:
            answer = str(q.get("answer", "")).strip().lower()
            if answer not in {"a", "b", "c", "d"}:
                raise ValueError(f"{idx}-savol javobi A, B, C yoki D bo'lishi kerak.")
            normalized.append({
                "num": idx,
                "type": "closed4",
                "answer": answer
            })
            continue

        if idx <= 35:
            answer = str(q.get("answer", "")).strip().lower()
            if answer not in {"a", "b", "c", "d", "e", "f"}:
                raise ValueError(f"{idx}-savol javobi A, B, C, D, E yoki F bo'lishi kerak.")
            normalized.append({
                "num": idx,
                "type": "closed6",
                "answer": answer
            })
            continue

        raw_answer = q.get("answer", {})
        if not isinstance(raw_answer, dict):
            raw_answer = {
                "a": q.get("answer_a", q.get("a", "")),
                "b": q.get("answer_b", q.get("b", "")),
            }

        ans_a = str(raw_answer.get("a", "")).strip()
        ans_b = str(raw_answer.get("b", "")).strip()
        if not ans_a or not ans_b:
            raise ValueError(f"{idx}-savol uchun a va b javoblari to'ldirilishi shart.")

        normalized.append({
            "num": idx,
            "type": "open2",
            "answer": {
                "a": ans_a,
                "b": ans_b,
            }
        })

    return normalized


async def _ask_test_name(message, context: ContextTypes.DEFAULT_TYPE, mode: str):
    """Test nomini so'rash — WAITING_TEST_NAME holatiga o'tadi.

    `mode` keyinchalik nom qabul qilingach `_show_mode_instructions`ga
    uzatilishi uchun user_data'da saqlanadi.
    """
    context.user_data["pending_test_mode"] = mode
    keyboard = ReplyKeyboardMarkup([[KeyboardButton("Ortga")]], resize_keyboard=True)
    await message.reply_html(
        "✏️ <b>Avval test uchun nom kiriting</b>\n\n"
        "Masalan: <code>9-sinf Matematika, 2-chorak</code>\n\n"
        "❌ Bekor qilish: /cancel yoki Ortga",
        reply_markup=keyboard,
    )
    return WAITING_TEST_NAME


async def receive_test_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WAITING_TEST_NAME — test nomini qabul qilish (majburiy)."""
    text = (update.message.text or "").strip()

    if text.lower() in ("ortga", "❌ bekor qilish"):
        return await cancel_command(update, context)

    if not text:
        await update.message.reply_html("❌ Nom bo'sh bo'lmasligi kerak. Qaytadan kiriting.")
        return WAITING_TEST_NAME

    if len(text) > MAX_TEST_NAME_LEN:
        await update.message.reply_html(
            f"❌ Nom juda uzun (maksimal {MAX_TEST_NAME_LEN} belgi). Qaytadan kiriting."
        )
        return WAITING_TEST_NAME

    context.user_data["pending_test_name"] = text
    mode = context.user_data.pop("pending_test_mode", "simple")
    return await _show_mode_instructions(update.message, mode)


async def _show_mode_instructions(message, mode: str):
    """Tanlangan test rejimiga mos ko'rsatma va tugmalarni ko'rsatish."""
    if mode == "rasch":
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("📲 Ilova", web_app=WebAppInfo(url=f"{WEBAPP_URL}/create_rasch?v={WEBAPP_VERSION}"))],
            [KeyboardButton("Ortga")]
        ], resize_keyboard=True)

        await message.reply_html(
            "📐 <b>Rash test yaratish</b>\n\n"
            "Pastdagi «📲 Ilova» tugmasini bosib yarating.",
            reply_markup=keyboard
        )
    else:
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("📲 Ilova", web_app=WebAppInfo(url=f"{WEBAPP_URL}/create?v={WEBAPP_VERSION}"))],
            [KeyboardButton("Ortga")]
        ], resize_keyboard=True)

        await message.reply_html(
            "📊 <b>Oddiy test yaratish</b>\n\n"
            "To'g'ri javoblarni quyidagi ikki usuldan birida yuboring:\n\n"
            "1️⃣ <b>Klassik usul</b> — harflarni ketma-ket yozing:\n"
            "   <code>aabbcabacbad</code>\n\n"
            "2️⃣ <b>Raqamli usul</b> — raqam + harf bilan yozing:\n"
            "   <code>1a2a3b4c5a6b</code>\n"
            "   <code>1-a 2-a 3-b 4-c</code>\n\n"
            "📌 Faqat <b>A, B, C, D</b> harflari bo'lishi kerak.\n"
            "📌 Yoki pastdagi «📲 Ilova» tugmasi orqali yarating.\n\n"
            "❌ Bekor qilish: /cancel yoki Ortga",
            reply_markup=keyboard
        )
    return WAITING_ANSWERS


@membership_required
async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test yaratish tugmalari (Oddiy yoki Rash test yaratish) bosilganda."""
    text = (update.message.text or "").strip()
    mode = "rasch" if "rash" in text.lower() else "simple"

    user = update.effective_user
    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    if not db_user.full_name_confirmed:
        context.user_data["pending_test_mode"] = mode
        await _ask_full_name(update.message)
        return WAITING_FULL_NAME_FOR_CREATE

    return await _ask_test_name(update.message, context, mode)


async def receive_full_name_for_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test yaratishdan oldin ism-familiya so'ralganda qabul qilish."""
    text = (update.message.text or "").strip()

    if not _is_valid_full_name(text):
        await update.message.reply_html(
            "❌ Noto'g'ri format. Ism va familiyangizni kamida 2 ta so'z bilan kiriting.\n\n"
            "Masalan: <code>Aziz Karimov</code>"
        )
        return WAITING_FULL_NAME_FOR_CREATE

    normalized = " ".join(w.capitalize() for w in text.split())

    user = update.effective_user
    db_user = User.get(User.telegram_id == user.id)
    db_user.full_name = normalized
    db_user.full_name_confirmed = True
    db_user.save()

    await update.message.reply_html(f"✅ Rahmat, <b>{escape(normalized)}</b>!")

    mode = context.user_data.pop("pending_test_mode", "simple")
    return await _ask_test_name(update.message, context, mode)


async def remind_full_name_needed_for_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WAITING_FULL_NAME_FOR_CREATE holatida matndan boshqa narsa kelsa."""
    await update.message.reply_html(
        "✍️ Iltimos, ism-familiyangizni <b>matn</b> ko'rinishida yuboring."
    )
    return WAITING_FULL_NAME_FOR_CREATE


async def choose_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """CHOOSING_MODE — test turini reply tugma matni orqali tanlash."""
    text = (update.message.text or "").strip()

    if text.lower() in ("ortga", "❌ bekor qilish"):
        return await cancel_command(update, context)

    if text == "📐 Rash test":
        return await _show_mode_instructions(update.message, "rasch")

    if text == "📊 Oddiy test":
        return await _show_mode_instructions(update.message, "simple")

    await update.message.reply_html("Yuqoridagi tugmalardan birini tanlang.")
    return CHOOSING_MODE


@membership_required
async def receive_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Javoblarni qabul qilish"""
    raw = update.message.text.strip()

    if raw.lower() == "ortga":
        return await cancel_command(update, context)

    # Ikkala formatni qabul qiluvchi parse
    answers, error = parse_simple_answers(raw)
    if error:
        await update.message.reply_html(error)
        return WAITING_ANSWERS

    user = update.effective_user
    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    # Bot ichidagi tezkor rejim faqat oddiy test uchun
    scoring_mode = "simple"
    test_name = context.user_data.pop("pending_test_name", "Test")

    # Testni saqlash
    try:
        test = Test.create(
            name=test_name,
            correct_answers=answers,
            creator=db_user,
            is_active=True,
            scoring_mode=scoring_mode
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik yuz berdi! DB yangilanmagan bo'lishi mumkin.\n\n`{str(e)}`", parse_mode="Markdown")
        context.user_data.pop('scoring_mode', None)
        return ConversationHandler.END

    test_id = str(test.id)

    # Adminga xabar yuborish (faqat boshqa odam yaratganda)
    mode_text = "📊 Oddiy"
    if ADMIN_ID and user.id != ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📢 <b>Yangi test yaratildi!</b>\n\n"
                     f"👤 Yaratuvchi: {escape(db_user.full_name or db_user.username or '')}\n"
                     f"📌 Nomi: {escape(test_name)}\n"
                     f"📝 Kod: <code>{test_id}</code>\n"
                     f"❓ Savollar: {len(answers)} ta\n"
                     f"📐 Baholash: {mode_text}",
                parse_mode="HTML"
            )
        except Exception:
            pass

    # Bot username olish
    try:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = ""

    await update.message.reply_html(
        f"✅ <b>Test yaratildi!</b>\n\n"
        f"📌 Nomi: <b>{escape(test_name)}</b>\n"
        f"📝 Test kodi: <code>{test_id}</code>\n"
        f"❓ Savollar soni: {len(answers)} ta\n"
        f"📐 Baholash: {mode_text}\n\n"
        f"Bu kodni boshqalarga yuboring!",
        reply_markup=test_created_keyboard(test_id, bot_username, len(answers), test_name)
    )

    await update.message.reply_text("🏠 Asosiy menyu:", reply_markup=main_menu_keyboard(update.effective_user.id))

    return ConversationHandler.END


async def webapp_create_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WebApp orqali yaratilgan testni qabul qilish"""
    try:
        if not update.message or not update.message.web_app_data:
            logger.warning("WEBAPP CREATE: web_app_data missing")
            return ConversationHandler.END

        data = json.loads(update.message.web_app_data.data)
        if data.get("action") != "create_test":
            return ConversationHandler.END

        scoring_mode = data.get("scoring_mode", "simple")
        answers_format = data.get("answers_format", "simple")

        if scoring_mode not in {"simple", "rasch"}:
            await update.message.reply_text("❌ Baholash turi noto'g'ri!")
            return ConversationHandler.END

        if scoring_mode == "rasch":
            if answers_format != "mixed":
                await update.message.reply_text("❌ Rash test uchun qat'iy format yuborilishi kerak.")
                return ConversationHandler.END

            questions = data.get("questions", [])
            if not isinstance(questions, list) or not questions:
                await update.message.reply_text("❌ Rash test savollari bo'sh!")
                return ConversationHandler.END

            try:
                normalized_questions = _normalize_rasch_questions(questions)
            except ValueError as e:
                await update.message.reply_text(f"❌ {e}")
                return ConversationHandler.END

            answers_str = json.dumps(normalized_questions, ensure_ascii=False)
            questions_count = len(normalized_questions)
        elif answers_format == "mixed":
            # JSON array
            questions = data.get("questions", [])
            if not isinstance(questions, list) or not questions:
                await update.message.reply_text("❌ Javoblar bo'sh!")
                return ConversationHandler.END

            normalized_questions = []
            for i, q in enumerate(questions):
                if not isinstance(q, dict):
                    await update.message.reply_text("❌ Savollar formati noto'g'ri!")
                    return ConversationHandler.END

                q_type = str(q.get("type", "closed")).strip().lower()
                if q_type not in {"closed", "open"}:
                    q_type = "closed"

                answer = str(q.get("answer", "")).strip()
                if not answer:
                    await update.message.reply_text(f"❌ {i + 1}-savol javobi bo'sh bo'lmasligi kerak.")
                    return ConversationHandler.END

                if q_type == "closed":
                    answer = answer.lower()
                    if answer not in {"a", "b", "c", "d"}:
                        await update.message.reply_text(
                            f"❌ {i + 1}-savol uchun yopiq javob faqat A, B, C yoki D bo'lishi kerak."
                        )
                        return ConversationHandler.END

                normalized_questions.append({
                    "num": i + 1,
                    "type": q_type,
                    "answer": answer
                })

            answers_str = json.dumps(normalized_questions, ensure_ascii=False)
            questions_count = len(normalized_questions)
        else:
            # Simple string — faqat A, B, C, D harflari (yechish interfeysi ham shularni qabul qiladi)
            answers_str = data.get("answers", "").strip().lower()
            if not answers_str or not re.fullmatch(r"[a-d]+", answers_str):
                await update.message.reply_text(
                    "❌ Javoblar faqat A, B, C, D harflaridan iborat bo'lishi kerak!"
                )
                return ConversationHandler.END
            questions_count = len(answers_str)

        user = update.effective_user
        db_user = get_or_create_user(
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name or user.first_name
        )

        test_name = context.user_data.pop("pending_test_name", "Test")

        test = Test.create(
            name=test_name,
            correct_answers=answers_str,
            creator=db_user,
            is_active=True,
            scoring_mode=scoring_mode
        )

        test_id = str(test.id)
        mode_text = "📊 Oddiy" if scoring_mode == "simple" else "📐 Rash"

        # Adminga xabar
        if ADMIN_ID and user.id != ADMIN_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"📢 <b>Yangi test yaratildi!</b>\n\n"
                         f"👤 Yaratuvchi: {escape(db_user.full_name or db_user.username or '')}\n"
                         f"📌 Nomi: {escape(test_name)}\n"
                         f"📝 Kod: <code>{test_id}</code>\n"
                         f"❓ Savollar: {questions_count} ta\n"
                         f"📐 Baholash: {mode_text}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # Bot username
        try:
            bot_info = await context.bot.get_me()
            bot_username = bot_info.username
        except Exception:
            bot_username = ""

        await update.message.reply_html(
            f"✅ <b>Test yaratildi!</b> 🚀\n\n"
            f"📌 Nomi: <b>{escape(test_name)}</b>\n"
            f"📝 Test kodi: <code>{test_id}</code>\n"
            f"❓ Savollar soni: {questions_count} ta\n"
            f"📐 Baholash: {mode_text}\n\n"
            f"Bu kodni boshqalarga yuboring!",
            reply_markup=test_created_keyboard(test_id, bot_username, questions_count, test_name)
        )

        await update.message.reply_text("🏠 Asosiy menyu:", reply_markup=main_menu_keyboard(update.effective_user.id))

        logger.info("WEBAPP CREATE: created test_id=%s user_id=%s mode=%s", test_id, user.id, scoring_mode)
        return ConversationHandler.END

    except json.JSONDecodeError:
        logger.exception("WEBAPP CREATE: JSONDecodeError")
        await update.message.reply_text("❌ Yuborilgan ma'lumot noto'g'ri!")
        return ConversationHandler.END
    except Exception as e:
        logger.exception("WEBAPP CREATE: unexpected error: %s", e)
        await update.message.reply_text(f"❌ Xatolik: {e}")
        return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bekor qilish"""
    context.user_data.pop("pending_test_mode", None)
    context.user_data.pop("pending_test_name", None)
    await update.message.reply_text(
        "❌ Test yaratish bekor qilindi.",
        reply_markup=main_menu_keyboard(update.effective_user.id)
    )
    return ConversationHandler.END


def get_handlers():
    """Bot ichida test yaratish handlerlari"""
    conversation_handler = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(
                    r"^(📊 Oddiy test yaratish|📐 Rash test yaratish|📊 Oddiy test|📐 Rash test|📝 Test yaratish)$"
                ),
                create_command
            ),
        ],
        states={
            WAITING_FULL_NAME_FOR_CREATE: [
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    receive_full_name_for_create
                ),
                MessageHandler(
                    filters.ChatType.PRIVATE & ~filters.COMMAND,
                    remind_full_name_needed_for_create
                ),
            ],
            CHOOSING_MODE: [
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    choose_mode_handler
                ),
            ],
            WAITING_TEST_NAME: [
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    receive_test_name
                ),
            ],
            WAITING_ANSWERS: [
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    receive_answers
                ),
                MessageHandler(
                    filters.StatusUpdate.WEB_APP_DATA,
                    webapp_create_handler
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command, filters=filters.ChatType.PRIVATE),
        ],
        allow_reentry=True,
    )
    return [conversation_handler]

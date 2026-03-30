"""Test yaratish handleri"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ContextTypes, CommandHandler,
    MessageHandler, ConversationHandler, CallbackQueryHandler, filters
)

from database import get_or_create_user, Test
from config import ADMIN_ID, WEBAPP_URL, WEBAPP_VERSION
from keyboards import test_created_keyboard, main_menu_keyboard
from membership import membership_required
import json

# Conversation states
WAITING_SCORING_MODE = 0
WAITING_ANSWERS = 1


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


@membership_required
async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test yaratishni boshlash — baholash turini tanlash"""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Oddiy", callback_data="scoring_simple"),
            InlineKeyboardButton("📐 Rash", callback_data="scoring_rasch"),
        ],
        [
            InlineKeyboardButton("🚀 Testni yaratish", web_app=WebAppInfo(url=f"{WEBAPP_URL}/create?v={WEBAPP_VERSION}"))
        ]
    ])

    await update.message.reply_html(
        "📝 <b>Yangi test yaratish</b>\n\n"
        "Baholash turini tanlang:\n\n"
        "📊 <b>Oddiy</b> — to'g'ri javoblar soni bo'yicha\n"
        "📐 <b>Rash</b> — savol qiyinligini hisobga oladi\n\n"
        "Yoki pastdagi tugma orqali yarating 👇\n\n"
        "❌ Bekor qilish: /cancel",
        reply_markup=keyboard
    )
    return WAITING_SCORING_MODE


async def scoring_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Baholash turini saqlash"""
    query = update.callback_query
    await query.answer()

    mode = query.data.replace("scoring_", "")  # 'simple' yoki 'rasch'
    context.user_data['scoring_mode'] = mode

    mode_text = "📊 Oddiy" if mode == "simple" else "📐 Rash"

    await query.message.edit_text(
        f"📝 <b>Yangi test yaratish</b>\n\n"
        f"Baholash: <b>{mode_text}</b>\n\n"
        f"To'g'ri javoblarni kiriting.\n"
        f"Masalan: <code>abbacabbac</code>\n\n"
        f"❌ Bekor qilish: /cancel",
        parse_mode="HTML"
    )
    return WAITING_ANSWERS


async def receive_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Javoblarni qabul qilish"""
    answers = update.message.text.strip().lower()

    # Validatsiya
    if not answers:
        await update.message.reply_text("❌ Javoblar bo'sh bo'lmasligi kerak!")
        return WAITING_ANSWERS

    # Faqat harflarni tekshirish
    if not answers.isalpha():
        await update.message.reply_html(
            "❌ Javoblar faqat harflardan iborat bo'lishi kerak!\n"
            "Masalan: <code>abbacabbac</code>"
        )
        return WAITING_ANSWERS

    user = update.effective_user
    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    # Baholash turini olish
    scoring_mode = context.user_data.get('scoring_mode', 'simple')

    # Testni saqlash
    try:
        test = Test.create(
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
    mode_text = "📊 Oddiy" if scoring_mode == "simple" else "📐 Rash"
    if ADMIN_ID and user.id != ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📢 <b>Yangi test yaratildi!</b>\n\n"
                     f"👤 Yaratuvchi: {db_user.full_name or db_user.username}\n"
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
        f"📝 Test kodi: <code>{test_id}</code>\n"
        f"❓ Savollar soni: {len(answers)} ta\n"
        f"📐 Baholash: {mode_text}\n\n"
        f"Bu kodni boshqalarga yuboring!",
        reply_markup=test_created_keyboard(test_id, bot_username, len(answers))
    )

    # user_data ni tozalash
    context.user_data.pop('scoring_mode', None)
    return ConversationHandler.END


async def webapp_create_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WebApp orqali yaratilgan testni qabul qilish"""
    try:
        data = json.loads(update.message.web_app_data.data)
        if data.get("action") != "create_test":
            return

        scoring_mode = data.get("scoring_mode", "simple")
        answers_format = data.get("answers_format", "simple")

        if scoring_mode not in {"simple", "rasch"}:
            await update.message.reply_text("❌ Baholash turi noto'g'ri!")
            return
        
        if scoring_mode == "rasch":
            if answers_format != "mixed":
                await update.message.reply_text("❌ Rash test uchun qat'iy format yuborilishi kerak.")
                return

            questions = data.get("questions", [])
            if not isinstance(questions, list) or not questions:
                await update.message.reply_text("❌ Rash test savollari bo'sh!")
                return

            try:
                normalized_questions = _normalize_rasch_questions(questions)
            except ValueError as e:
                await update.message.reply_text(f"❌ {e}")
                return

            answers_str = json.dumps(normalized_questions, ensure_ascii=False)
            questions_count = len(normalized_questions)
        elif answers_format == "mixed":
            # JSON array
            questions = data.get("questions", [])
            if not isinstance(questions, list) or not questions:
                await update.message.reply_text("❌ Javoblar bo'sh!")
                return

            normalized_questions = []
            for i, q in enumerate(questions):
                if not isinstance(q, dict):
                    await update.message.reply_text("❌ Savollar formati noto'g'ri!")
                    return

                q_type = str(q.get("type", "closed")).strip().lower()
                if q_type not in {"closed", "open"}:
                    q_type = "closed"

                answer = str(q.get("answer", "")).strip()
                if not answer:
                    await update.message.reply_text(f"❌ {i + 1}-savol javobi bo'sh bo'lmasligi kerak.")
                    return

                if q_type == "closed":
                    answer = answer.lower()
                    if answer not in {"a", "b", "c", "d"}:
                        await update.message.reply_text(
                            f"❌ {i + 1}-savol uchun yopiq javob faqat A, B, C yoki D bo'lishi kerak."
                        )
                        return

                normalized_questions.append({
                    "num": i + 1,
                    "type": q_type,
                    "answer": answer
                })

            answers_str = json.dumps(normalized_questions, ensure_ascii=False)
            questions_count = len(normalized_questions)
        else:
            # Simple string
            answers_str = data.get("answers", "").strip().lower()
            if not answers_str or not answers_str.isalpha():
                await update.message.reply_text("❌ Javoblar noto'g'ri formatda!")
                return
            questions_count = len(answers_str)

        user = update.effective_user
        db_user = get_or_create_user(
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name or user.first_name
        )

        test = Test.create(
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
                         f"👤 Yaratuvchi: {db_user.full_name or db_user.username}\n"
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
            f"📝 Test kodi: <code>{test_id}</code>\n"
            f"❓ Savollar soni: {questions_count} ta\n"
            f"📐 Baholash: {mode_text}\n\n"
            f"Bu kodni boshqalarga yuboring!",
            reply_markup=test_created_keyboard(test_id, bot_username, questions_count)
        )

    except json.JSONDecodeError:
        await update.message.reply_text("❌ Yuborilgan ma'lumot noto'g'ri!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        await update.message.reply_text(f"❌ Xatolik: {e}")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bekor qilish"""
    context.user_data.pop('scoring_mode', None)
    await update.message.reply_text(
        "❌ Test yaratish bekor qilindi.",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


def get_handlers():
    """Yaratish oqimi to'liq WebApp ga ko'chirilgan."""
    return []

"""Test yechish handleri"""
import logging

from telegram import Update
from telegram.ext import (
    ContextTypes, CommandHandler,
    MessageHandler, ConversationHandler, filters
)

from database import get_or_create_user, Test, TestSubmission
from utils import check_answers
from config import ADMIN_ID
from keyboards import main_menu_keyboard
from membership import membership_required
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from config import WEBAPP_URL, WEBAPP_VERSION
import json

logger = logging.getLogger(__name__)

WAITING_TEST_CODE = 0
WAITING_USER_ANSWERS = 1


@membership_required
async def solve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testni yechishni boshlash"""
    # Argumentdan kodni olish
    if not context.args:
        await update.message.reply_html(
            "✍️ <b>Test yechish</b>\n\n"
            "Hozir siz oddiy test yechish holatidasiz.\n\n"
            "Test egasi sizga yuborgan <b>test raqamini (ID)</b> kiriting:\n\n"
            "💡 Kod faqat raqamlardan iborat\n"
            "(masalan: <code>15</code> yoki <code>42</code>)\n\n"
            "❌ Bekor qilish: /cancel yoki Ortga"
        )
        return WAITING_TEST_CODE

    code = context.args[0].upper()
    return await process_test_code(update, context, code)


@membership_required
async def receive_test_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test kodini qabul qilish"""
    code = update.message.text.strip().upper()
    if code == "ORTGA":
        return await cancel_solve(update, context)
        
    return await process_test_code(update, context, code)


async def process_test_code(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    """Test kodini qayta ishlash"""
    if not code.isdigit():
        await update.message.reply_text("❌ Kod faqat raqamlardan iborat bo'lishi kerak!")
        return WAITING_TEST_CODE

    # Testni topish
    try:
        test = Test.get_by_id(int(code))
    except Test.DoesNotExist:
        await update.message.reply_text(
            f"❌ '{code}' kodli test topilmadi!\n\n"
            "Qaytadan urinib ko'ring yoki /cancel bosing."
        )
        return WAITING_TEST_CODE

    # Test faolligini tekshirish
    if not test.is_active:
        await update.message.reply_text(
            f"❌ Bu test allaqachon yakunlangan!",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    user = update.effective_user
    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    # O'zi yaratgan testini yecha olmasligini tekshirish
    if test.creator.telegram_id == user.id:
        await update.message.reply_text(
            "❌ O'zingiz yaratgan testni yecha olmaysiz!",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # Avval yechganligini tekshirish
    existing = TestSubmission.select().where(
        (TestSubmission.test == test) &
        (TestSubmission.user == db_user)
    ).first()

    if existing:
        await update.message.reply_text(
            "⚠️ Siz bu testni allaqachon ishlagansiz!",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # Contextga test ma'lumotini saqlash
    context.user_data['current_test'] = test
    context.user_data['db_user'] = db_user

    # Solve url
    solve_path = "/solve_rasch" if test.scoring_mode == "rasch" else "/solve"

    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("🚀 Interaktiv yechish", web_app=WebAppInfo(url=f"{WEBAPP_URL}{solve_path}?test_id={test.id}&v={WEBAPP_VERSION}"))],
        [KeyboardButton("Ortga")]
    ], resize_keyboard=True)

    await update.message.reply_html(
        f"📝 <b>Test: {code}</b>\n\n"
        f"❓ Savollar soni: {test.total_questions} ta\n\n"
        f"Javoblaringizni kiriting.\n"
        f"Masalan: <code>{'a' * min(test.total_questions, 10)}</code>\n\n"
        f"Yoki pastdagi maxsus tugma orqali WebApp da ishlashingiz mumkin\n\n"
        f"❌ Bekor qilish: /cancel yoki Ortga",
        reply_markup=keyboard
    )

    return WAITING_USER_ANSWERS


@membership_required
async def receive_user_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi javoblarini qabul qilish"""
    test = context.user_data.get('current_test')
    db_user = context.user_data.get('db_user')

    if not test or not db_user:
        await update.message.reply_text(
            "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # Test hali ham faol ekanligini tekshirish
    test = Test.get_by_id(test.id)
    if not test.is_active:
        await update.message.reply_text(
            "❌ Bu test yakunlangan!",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    if test.correct_answers and test.correct_answers.startswith("[{"):
        await update.message.reply_html(
            "⚠️ <b>Ushbu testni faqat matn yozib yechib bo'lmaydi!</b>\n"
            "Testda ochiq savollar bor. Iltimos, pastdagi <b>🚀 Interaktiv yechish</b> tugmasidan foydalaning!"
        )
        return WAITING_USER_ANSWERS

    if not update.message or not update.message.text:
        await update.message.reply_text("❌ Faqat matn yuboring!")
        return WAITING_USER_ANSWERS

    answers = update.message.text.strip().lower()

    if answers == "ortga":
        return await cancel_solve(update, context)

    # Validatsiya
    if not answers.isalpha():
        await update.message.reply_html(
            "❌ Javoblar faqat harflardan iborat bo'lishi kerak!\n"
            "Masalan: <code>abbacabbac</code>"
        )
        return WAITING_USER_ANSWERS

    # Javoblar sonini tekshirish
    if len(answers) != test.total_questions:
        await update.message.reply_html(
            f"❌ Javoblar soni to'g'ri kelmadi!\n"
            f"Kutilgan: {test.total_questions} ta\n"
            f"Kiritilgan: {len(answers)} ta"
        )
        return WAITING_USER_ANSWERS

    # Javoblarni tekshirish
    correct_count, total, results = check_answers(test.correct_answers, answers)

    # Natijani saqlash
    submission = TestSubmission.create(
        test=test,
        user=db_user,
        answers=answers,
        correct_count=correct_count,
        total_count=total
    )

    # Foydalanuvchiga qabul qilinganini yuborish (yakuniy natija test yakunlangach yuboriladi)
    await update.message.reply_html(
        "✅ <b>Javobingiz qabul qilindi.</b>\n\n"
        "📌 Natija test yakunlangach yuboriladi.",
        reply_markup=main_menu_keyboard()
    )

    # Test egasiga xabar yuborish (faqat boshqa odam yechganda)
    if test.creator.telegram_id != db_user.telegram_id:
        try:
            creator = test.creator
            await context.bot.send_message(
                chat_id=creator.telegram_id,
                text=f"📢 <b>Yangi natija!</b>\n\n"
                     f"📝 Test: <code>{test.id}</code>\n"
                     f"👤 Foydalanuvchi: {db_user.full_name or db_user.username}\n"
                     f"✅ Natija: {correct_count}/{total} ({submission.percentage}%)",
                parse_mode="HTML"
            )
        except Exception:
            pass

    # Context tozalash
    context.user_data.pop('current_test', None)
    context.user_data.pop('db_user', None)

    return ConversationHandler.END


async def cancel_solve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testni yechishni bekor qilish"""
    context.user_data.pop('current_test', None)
    context.user_data.pop('db_user', None)
    await update.message.reply_text(
        "❌ Test yechish bekor qilindi.",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


@membership_required
async def webapp_receive_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WebApp orqali kelgan barcha amallarni qabul qilish (router)"""
    try:
        if not update.message or not update.message.web_app_data:
            logger.warning("WEBAPP DATA: message/web_app_data missing")
            return ConversationHandler.END

        data = json.loads(update.message.web_app_data.data)
        action = data.get("action")
        logger.info("WEBAPP DATA RECEIVED: action=%s user_id=%s", action, update.effective_user.id if update.effective_user else None)
        
        if action == "create_test":
            # Test yaratish — alohida handler ga yo'naltirish
            from handlers.test_create import webapp_create_handler
            return await webapp_create_handler(update, context)
        
        if action != "submit_test":
            return ConversationHandler.END
            
        test_id = data.get("test_id")
        answers = data.get("answers", "")

        if not str(test_id).isdigit():
            await update.message.reply_text("❌ Test kodi noto'g'ri formatda!", reply_markup=main_menu_keyboard())
            return ConversationHandler.END

        if not isinstance(answers, str):
            answers = str(answers or "")
        
        # User auth details
        telegram_id = update.effective_user.id
        db_user = get_or_create_user(
            telegram_id=telegram_id,
            username=update.effective_user.username,
            full_name=update.effective_user.full_name
        )
        
        try:
            test = Test.get_by_id(int(test_id))
        except Test.DoesNotExist:
            await update.message.reply_text("❌ Kutilmagan xatolik: Test topilmadi.", reply_markup=main_menu_keyboard())
            return ConversationHandler.END
            
        if not test.is_active:
            await update.message.reply_text("❌ Uzr, bu test allaqachon yakunlangan!", reply_markup=main_menu_keyboard())
            return ConversationHandler.END

        if test.creator.telegram_id == telegram_id:
            await update.message.reply_text("❌ O'zingiz yaratgan testni yecha olmaysiz!", reply_markup=main_menu_keyboard())
            return ConversationHandler.END
            
        existing = TestSubmission.select().where(
            (TestSubmission.test == test) & 
            (TestSubmission.user == db_user)
        ).first()
        
        if existing:
            await update.message.reply_text(
                "⚠️ Siz bu testni allaqachon ishlagansiz!",
                reply_markup=main_menu_keyboard()
            )
            return ConversationHandler.END
            
        # check
        is_mixed = test.correct_answers and test.correct_answers.startswith("[{")
        safe_answers = answers.strip()
        if not is_mixed:
            safe_answers = safe_answers.lower()

        correct_count, total, _ = check_answers(test.correct_answers, safe_answers)

        submission = TestSubmission.create(
            test=test,
            user=db_user,
            answers=safe_answers,
            correct_count=correct_count,
            total_count=total
        )

        # Foydalanuvchiga qabul qilinganini yuborish (yakuniy natija test yakunlangach yuboriladi)
        await update.message.reply_html(
            "✅ <b>Javobingiz qabul qilindi.</b>\n\n"
            "📌 Natija test yakunlangach yuboriladi.",
            reply_markup=main_menu_keyboard()
        )

        # Test egasiga xabar yuborish
        if test.creator.telegram_id != db_user.telegram_id:
            try:
                creator = test.creator
                await context.bot.send_message(
                    chat_id=creator.telegram_id,
                    text=f"📢 <b>Yangi natija!</b>\n\n"
                     f"📝 Test: <code>{test.id}</code>\n"
                     f"👤 Foydalanuvchi: {db_user.full_name or db_user.username}\n"
                     f"✅ Natija: {correct_count}/{total} ({submission.percentage}%)",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    except json.JSONDecodeError:
        logger.exception("WEBAPP DATA: JSONDecodeError")
        return ConversationHandler.END
    except Exception as e:
        logger.exception("WEBAPP DATA: unexpected error: %s", e)
        await update.message.reply_text(f"Xatolik: {e}", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    # Context tozalash
    context.user_data.pop('current_test', None)
    context.user_data.pop('db_user', None)
    return ConversationHandler.END


def get_handlers():
    """Bot ichida yechish + WebApp data handlerlari"""
    conversation_handler = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r"^(✍️ Test yechish|✍️ Oddiy test yechish)$"),
                solve_command
            ),
        ],
        states={
            WAITING_TEST_CODE: [
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    receive_test_code
                ),
                MessageHandler(
                    filters.StatusUpdate.WEB_APP_DATA,
                    webapp_receive_data
                )
            ],
            WAITING_USER_ANSWERS: [
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    receive_user_answers
                ),
                MessageHandler(
                    filters.StatusUpdate.WEB_APP_DATA,
                    webapp_receive_data
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_solve, filters=filters.ChatType.PRIVATE),
        ],
        allow_reentry=True,
    )

    return [conversation_handler]

"""Test yaratish handleri"""
from telegram import Update
from telegram.ext import (
    ContextTypes, CommandHandler,
    MessageHandler, ConversationHandler, filters
)

from database import get_or_create_user, Test
from utils import generate_unique_code
from config import ADMIN_ID
from keyboards import test_created_keyboard, main_menu_keyboard
from membership import membership_required

# Conversation states
WAITING_ANSWERS = 0


@membership_required
async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test yaratishni boshlash"""
    await update.message.reply_html(
        "📝 <b>Yangi test yaratish</b>\n\n"
        "To'g'ri javoblarni kiriting.\n"
        "Masalan: <code>abbacabbac</code>\n\n"
        "❌ Bekor qilish: /cancel"
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

    # Unikal kod yaratish
    unique_code = generate_unique_code()

    # Testni saqlash
    test = Test.create(
        unique_code=unique_code,
        correct_answers=answers,
        creator=db_user,
        is_active=True
    )

    # Adminga xabar yuborish (faqat boshqa odam yaratganda)
    if ADMIN_ID and user.id != ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📢 <b>Yangi test yaratildi!</b>\n\n"
                     f"👤 Yaratuvchi: {db_user.full_name or db_user.username}\n"
                     f"📝 Kod: <code>{unique_code}</code>\n"
                     f"❓ Savollar: {len(answers)} ta",
                parse_mode="HTML"
            )
        except Exception:
            pass

    # Bot username olish
    bot_info = await context.bot.get_me()
    bot_username = bot_info.username

    await update.message.reply_html(
        f"✅ <b>Test yaratildi!</b>\n\n"
        f"📝 Unikal kod: <code>{unique_code}</code>\n"
        f"❓ Savollar soni: {len(answers)} ta\n\n"
        f"Bu kodni boshqalarga yuboring!",
        reply_markup=test_created_keyboard(unique_code, bot_username, len(answers))
    )

    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bekor qilish"""
    await update.message.reply_text(
        "❌ Test yaratish bekor qilindi.",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


def get_handlers():
    """Handlerlarni qaytarish"""
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("create", create_command, filters=filters.ChatType.PRIVATE),
            MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r'^📝 Test yaratish$'), create_command),
        ],
        states={
            WAITING_ANSWERS: [
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^(📝 Test yaratish|✍️ Test yechish|📋 Mening testlarim|📊 Mening statistikam)$'), receive_answers)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    return [conv_handler]


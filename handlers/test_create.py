"""Test yaratish handleri"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler,
    MessageHandler, ConversationHandler, CallbackQueryHandler, filters
)

from database import get_or_create_user, Test
from utils import generate_unique_code
from config import ADMIN_ID
from keyboards import test_created_keyboard, main_menu_keyboard
from membership import membership_required

# Conversation states
WAITING_SCORING_MODE = 0
WAITING_ANSWERS = 1


@membership_required
async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test yaratishni boshlash — baholash turini tanlash"""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Oddiy", callback_data="scoring_simple"),
            InlineKeyboardButton("📐 Rasch", callback_data="scoring_rasch"),
        ]
    ])

    await update.message.reply_html(
        "📝 <b>Yangi test yaratish</b>\n\n"
        "Baholash turini tanlang:\n\n"
        "📊 <b>Oddiy</b> — to'g'ri javoblar soni bo'yicha\n"
        "📐 <b>Rasch</b> — savol qiyinligini hisobga oladi\n\n"
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

    mode_text = "📊 Oddiy" if mode == "simple" else "📐 Rasch"

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

    # Unikal kod yaratish
    unique_code = generate_unique_code()

    # Baholash turini olish
    scoring_mode = context.user_data.get('scoring_mode', 'simple')

    # Testni saqlash
    test = Test.create(
        unique_code=unique_code,
        correct_answers=answers,
        creator=db_user,
        is_active=True,
        scoring_mode=scoring_mode
    )

    # Adminga xabar yuborish (faqat boshqa odam yaratganda)
    mode_text = "📊 Oddiy" if scoring_mode == "simple" else "📐 Rasch"
    if ADMIN_ID and user.id != ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📢 <b>Yangi test yaratildi!</b>\n\n"
                     f"👤 Yaratuvchi: {db_user.full_name or db_user.username}\n"
                     f"📝 Kod: <code>{unique_code}</code>\n"
                     f"❓ Savollar: {len(answers)} ta\n"
                     f"📐 Baholash: {mode_text}",
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
        f"❓ Savollar soni: {len(answers)} ta\n"
        f"📐 Baholash: {mode_text}\n\n"
        f"Bu kodni boshqalarga yuboring!",
        reply_markup=test_created_keyboard(unique_code, bot_username, len(answers))
    )

    # user_data ni tozalash
    context.user_data.pop('scoring_mode', None)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bekor qilish"""
    context.user_data.pop('scoring_mode', None)
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
            WAITING_SCORING_MODE: [
                CallbackQueryHandler(scoring_mode_callback, pattern=r"^scoring_(simple|rasch)$")
            ],
            WAITING_ANSWERS: [
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^(📝 Test yaratish|✍️ Test yechish|📋 Mening testlarim|📊 Mening statistikam)$'), receive_answers)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    return [conv_handler]

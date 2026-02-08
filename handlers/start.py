"""Start va Help buyruqlari"""
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from database import get_or_create_user
from config import ADMIN_ID
from keyboards import main_menu_keyboard


HELP_TEXT = """
🤖 <b>Test Bot - Yordam</b>

<b>📝 Test yaratish:</b>
1. "📝 Test yaratish" tugmasini bosing
2. To'g'ri javoblarni kiriting (masalan: abbacabbac)
3. Bot sizga unikal kod beradi
4. Bu kodni boshqalarga yuboring

<b>✍️ Test yechish:</b>
1. "✍️ Test yechish" tugmasini bosing
2. Test kodini kiriting
3. Javoblaringizni yuboring
4. Natijangizni ko'ring

<b>📋 Mening testlarim:</b>
O'zingiz yaratgan testlarni ko'rish va boshqarish

<b>📊 Mening statistikam:</b>
Yechgan testlaringiz statistikasi
"""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start buyrug'i"""
    user = update.effective_user

    # Foydalanuvchini databasega saqlash
    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    # Admin tekshirish
    if user.id == ADMIN_ID:
        db_user.is_admin = True
        db_user.save()

    await update.message.reply_html(
        f"👋 Salom, <b>{user.first_name}</b>!\n\n"
        f"🎯 Bu bot test javoblarini tekshirish uchun yaratilgan.\n\n"
        f"Quyidagi tugmalardan foydalaning:",
        reply_markup=main_menu_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help buyrug'i"""
    await update.message.reply_html(HELP_TEXT, reply_markup=main_menu_keyboard())


async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menyu tugmalarini qayta ishlash (📋, 📊)"""
    text = update.message.text

    if text == "📋 Mening testlarim":
        from handlers.test_manage import mytests_command
        return await mytests_command(update, context)

    elif text == "📊 Mening statistikam":
        from handlers.test_manage import mystats_command
        return await mystats_command(update, context)


def get_handlers():
    """Handlerlarni qaytarish"""
    return [
        CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE),
        CommandHandler("help", help_command, filters=filters.ChatType.PRIVATE),
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r'^(📋 Mening testlarim|📊 Mening statistikam)$'),
            handle_menu_buttons
        ),
    ]



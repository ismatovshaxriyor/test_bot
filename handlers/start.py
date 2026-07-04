"""Start, Help va Profil buyruqlari"""
from html import escape
from telegram import Update
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, ConversationHandler, filters
)

from database import get_or_create_user, User, Test, TestSubmission
from config import ADMIN_ID
from keyboards import main_menu_keyboard, profile_menu_keyboard
from membership import membership_required

# Conversation state — ism-familiya kiritilishini kutish
WAITING_FULL_NAME = 0


HELP_TEXT = """
🤖 <b>Test Bot - Yordam</b>

<b>📝 Test yaratish:</b>
1. "📝 Test yaratish" tugmasini bosing
2. Variantlarni kiriting (masalan: <code>aabbccdd...</code>)
3. Bot test kodini yuboradi
4. Pastdagi "🚀 Kengaytirilgan yaratish" tugmasi bilan ilovaga o'ting

<b>✍️ Test yechish:</b>
1. "✍️ Test yechish" tugmasini bosing
2. Test kodini kiriting
3. Oddiy test bo'lsa, javob qatorini yuboring
4. Pastdagi "🚀 Kengaytirilgan yechish" tugmasi bilan ilovaga o'ting

<b>👤 Profil:</b>
Ism-familyangiz va statistikangiz — shu yerdan "📋 Mening testlarim",
"📊 Mening statistikam" bo'limlariga o'tasiz va "✏️ Ismni o'zgartirish"
orqali ismingizni yangilashingiz mumkin.
"""


def _is_valid_full_name(text: str) -> bool:
    """To'liq ism-familiya kamida 2 ta so'zdan iborat bo'lishi kerak."""
    words = [w for w in text.split() if w.strip()]
    if len(words) < 2:
        return False
    if len(text) > 80:
        return False
    return all(any(ch.isalpha() for ch in w) for w in words)


async def _ask_full_name(message):
    await message.reply_html(
        "✍️ <b>Botdan foydalanish uchun to'liq ism familiyangizni kiriting.</b>\n\n"
        "Masalan: <code>Aziz Karimov</code>"
    )


def _first_name_of(full_name: str, fallback: str = "") -> str:
    """To'liq ism-familiyadan birinchi so'zni (ismni) ajratib olish."""
    parts = (full_name or "").split()
    return parts[0] if parts else (fallback or "")


async def _continue_start(message, user, db_user, start_args):
    """Ism tasdiqlangandan keyin (yoki darrov) asosiy /start oqimi."""
    if start_args and str(start_args[0]).isdigit():
        test_code = start_args[0]
        await message.reply_html(
            f"🎯 <b>{test_code} - testni yechish uchun keldingiz!</b>\n\n"
            f"Testni boshlash uchun quyidagi menyudan <b>✍️ Test yechish</b> tugmasini bosing va <code>{test_code}</code> kodini yuboring.",
            reply_markup=main_menu_keyboard(user.id)
        )
        return

    display_name = _first_name_of(db_user.full_name, user.first_name)
    await message.reply_html(
        f"👋 Salom, <b>{escape(display_name)}</b>!\n\n"
        f"🎯 Bu bot test javoblarini tekshirish uchun yaratilgan.\n\n"
        f"Quyidagi tugmalardan foydalaning:",
        reply_markup=main_menu_keyboard(user.id)
    )


async def _send_profile(message, user, db_user):
    created_tests = Test.select().where(Test.creator == db_user).count()
    solved_tests = TestSubmission.select().where(TestSubmission.user == db_user).count()
    username_line = f"@{db_user.username}" if db_user.username else "—"

    text = (
        f"👤 <b>Profil</b>\n\n"
        f"👨‍💼 Ism: {escape(db_user.full_name or '—')}\n"
        f"🔗 Username: {escape(username_line)}\n"
        f"🆔 ID: <code>{db_user.telegram_id}</code>\n"
        f"📅 Ro'yxatdan o'tgan: {db_user.created_at.strftime('%d.%m.%Y')}\n\n"
        f"📝 Yaratgan testlar: {created_tests} ta\n"
        f"✍️ Yechgan testlar: {solved_tests} ta"
    )
    await message.reply_html(text, reply_markup=profile_menu_keyboard())


@membership_required
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start buyrug'i"""
    user = update.effective_user

    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    if user.id == ADMIN_ID:
        db_user.is_admin = True
        db_user.save()

    if not db_user.full_name_confirmed:
        context.user_data["name_prompt_source"] = "start"
        context.user_data["pending_start_args"] = list(context.args) if context.args else []
        await _ask_full_name(update.message)
        return WAITING_FULL_NAME

    await _continue_start(update.message, user, db_user, context.args)
    return ConversationHandler.END


@membership_required
async def profile_entry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """"👤 Profil" tugmasi — ism tasdiqlanmagan bo'lsa avval so'raydi."""
    user = update.effective_user

    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    if not db_user.full_name_confirmed:
        context.user_data["name_prompt_source"] = "profile"
        context.user_data["pending_start_args"] = []
        await _ask_full_name(update.message)
        return WAITING_FULL_NAME

    await _send_profile(update.message, user, db_user)
    return ConversationHandler.END


@membership_required
async def edit_name_entry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """"✏️ Ismni o'zgartirish" tugmasi — Profil ichidan yangi ism so'raladi."""
    context.user_data["name_prompt_source"] = "profile"
    context.user_data["pending_start_args"] = []
    await update.message.reply_html(
        "✍️ <b>Yangi to'liq ism-familiyangizni kiriting.</b>\n\n"
        "Masalan: <code>Aziz Karimov</code>"
    )
    return WAITING_FULL_NAME


async def receive_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi yuborgan to'liq ism-familiyani qabul qilish va saqlash."""
    text = (update.message.text or "").strip()

    if not _is_valid_full_name(text):
        await update.message.reply_html(
            "❌ Noto'g'ri format. Ism va familiyangizni kamida 2 ta so'z bilan kiriting.\n\n"
            "Masalan: <code>Aziz Karimov</code>"
        )
        return WAITING_FULL_NAME

    normalized = " ".join(w.capitalize() for w in text.split())

    user = update.effective_user
    db_user = User.get(User.telegram_id == user.id)
    db_user.full_name = normalized
    db_user.full_name_confirmed = True
    db_user.save()

    await update.message.reply_html(f"✅ Rahmat, <b>{escape(normalized)}</b>!")

    source = context.user_data.pop("name_prompt_source", "start")
    pending_args = context.user_data.pop("pending_start_args", [])

    if source == "profile":
        await _send_profile(update.message, user, db_user)
    else:
        await _continue_start(update.message, user, db_user, pending_args)

    return ConversationHandler.END


async def remind_full_name_needed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WAITING_FULL_NAME holatida matndan boshqa narsa kelsa."""
    await update.message.reply_html(
        "✍️ Iltimos, ism-familiyangizni <b>matn</b> ko'rinishida yuboring."
    )
    return WAITING_FULL_NAME


async def cancel_full_name_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ism-familiya kiritish majburiy — /cancel bilan chetlab bo'lmaydi."""
    await update.message.reply_html(
        "⚠️ Botdan foydalanish uchun avval to'liq ism-familiyangizni kiritish shart.\n\n"
        "✍️ Masalan: <code>Aziz Karimov</code>"
    )
    return WAITING_FULL_NAME


@membership_required
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help buyrug'i"""
    await update.message.reply_html(HELP_TEXT, reply_markup=main_menu_keyboard(update.effective_user.id))


@membership_required
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
    # /start va "👤 Profil" — ikkalasi ham to'liq ism-familiya tasdiqlanishini talab qiladi
    full_name_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE),
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r'^👤 Profil$'),
                profile_entry_callback,
            ),
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r"^✏️ Ismni o'zgartirish$"),
                edit_name_entry_callback,
            ),
        ],
        states={
            WAITING_FULL_NAME: [
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receive_full_name),
                MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, remind_full_name_needed),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_full_name_prompt, filters=filters.ChatType.PRIVATE)],
        allow_reentry=True,
    )

    return [
        full_name_conv,
        CommandHandler("help", help_command, filters=filters.ChatType.PRIVATE),
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r'^(📋 Mening testlarim|📊 Mening statistikam)$'),
            handle_menu_buttons
        ),
    ]

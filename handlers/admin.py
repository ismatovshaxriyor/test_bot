"""Admin handlerlari"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from telegram.error import TelegramError

from database import User, Test, TestSubmission, Channel
from config import ADMIN_ID

# Conversation states
WAITING_CHANNEL_ID = 0
WAITING_ADMIN_ID = 1


def is_admin(user_id: int) -> bool:
    """Foydalanuvchi admin ekanligini tekshirish"""
    # .env dan asosiy admin
    if user_id == ADMIN_ID:
        return True
    # Database'dan qo'shimcha adminlar
    try:
        user = User.get(User.telegram_id == user_id)
        return user.is_admin
    except User.DoesNotExist:
        return False


def admin_only(func):
    """Admin tekshirish decorator"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_admin(user_id):
            if update.callback_query:
                await update.callback_query.answer("❌ Bu faqat admin uchun!", show_alert=True)
            else:
                await update.message.reply_text("❌ Bu buyruq faqat admin uchun!")
            return
        return await func(update, context)
    return wrapper


def admin_keyboard():
    """Admin panel tugmalari"""
    keyboard = [
        [InlineKeyboardButton("📢 Kanallar", callback_data="admin_channels")],
        [InlineKeyboardButton("👑 Adminlar", callback_data="admin_admins")],
        [InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="admin_users")],
        [InlineKeyboardButton("📝 Testlar", callback_data="admin_tests")],
    ]
    return InlineKeyboardMarkup(keyboard)


def admins_keyboard():
    """Adminlar boshqaruvi tugmalari"""
    keyboard = [
        [InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_admin")],
        [InlineKeyboardButton("📋 Adminlar ro'yxati", callback_data="list_admins")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def channels_keyboard():
    """Kanallar boshqaruvi tugmalari"""
    keyboard = [
        [InlineKeyboardButton("➕ Kanal qo'shish", callback_data="add_channel")],
        [InlineKeyboardButton("📋 Kanallar ro'yxati", callback_data="list_channels")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


@admin_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    total_users = User.select().count()
    total_tests = Test.select().count()
    active_tests = Test.select().where(Test.is_active == True).count()
    total_channels = Channel.select().where(Channel.is_active == True).count()

    text = f"👑 <b>Admin Panel</b>\n\n"
    text += f"👥 Foydalanuvchilar: {total_users} ta\n"
    text += f"📝 Barcha testlar: {total_tests} ta\n"
    text += f"🟢 Faol testlar: {active_tests} ta\n"
    text += f"📢 Majburiy kanallar: {total_channels} ta\n"

    await update.message.reply_html(text, reply_markup=admin_keyboard())


@admin_only
async def admin_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panelga qaytish"""
    query = update.callback_query
    await query.answer()

    total_users = User.select().count()
    total_tests = Test.select().count()
    active_tests = Test.select().where(Test.is_active == True).count()
    total_channels = Channel.select().where(Channel.is_active == True).count()

    text = f"👑 <b>Admin Panel</b>\n\n"
    text += f"👥 Foydalanuvchilar: {total_users} ta\n"
    text += f"📝 Barcha testlar: {total_tests} ta\n"
    text += f"🟢 Faol testlar: {active_tests} ta\n"
    text += f"📢 Majburiy kanallar: {total_channels} ta\n"

    await query.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())


@admin_only
async def channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanallar boshqaruvi"""
    query = update.callback_query
    await query.answer()

    text = "📢 <b>Kanallar boshqaruvi</b>\n\n"
    text += "Majburiy a'zolik kanallarini bu yerda boshqarishingiz mumkin."

    await query.message.edit_text(text, parse_mode="HTML", reply_markup=channels_keyboard())


@admin_only
async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal qo'shishni boshlash"""
    query = update.callback_query
    await query.answer()

    await query.message.edit_text(
        "📢 <b>Kanal qo'shish</b>\n\n"
        "Kanalni qo'shish uchun quyidagilardan birini yuboring:\n\n"
        "• Kanal ID: <code>-1001234567890</code>\n"
        "• Username: <code>@kanalname</code>\n\n"
        "⚠️ <b>Muhim:</b> Bot kanalda admin bo'lishi kerak!\n\n"
        "❌ Bekor qilish: /cancel",
        parse_mode="HTML"
    )

    return WAITING_CHANNEL_ID


async def receive_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal ID yoki username ni qabul qilish"""
    text = update.message.text.strip()

    try:
        # ID yoki username ni aniqlash
        if text.startswith('-100') or text.lstrip('-').isdigit():
            chat_id = int(text)
        elif text.startswith('@'):
            chat_id = text
        else:
            chat_id = f"@{text}"

        # Kanalda bot admin ekanligini tekshirish
        try:
            chat = await context.bot.get_chat(chat_id)
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)

            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_html(
                    "❌ <b>Bot bu kanalda admin emas!</b>\n\n"
                    "Avval botni kanalga admin qilib qo'shing, keyin qaytadan urinib ko'ring.\n\n"
                    "❌ Bekor qilish: /cancel"
                )
                return WAITING_CHANNEL_ID

        except TelegramError as e:
            await update.message.reply_html(
                f"❌ <b>Kanal topilmadi yoki bot admin emas!</b>\n\n"
                f"Xato: {e.message}\n\n"
                "❌ Bekor qilish: /cancel"
            )
            return WAITING_CHANNEL_ID

        # Allaqachon mavjudligini tekshirish
        existing = Channel.select().where(Channel.channel_id == chat.id).first()
        if existing:
            if existing.is_active:
                await update.message.reply_text("⚠️ Bu kanal allaqachon qo'shilgan!")
                return ConversationHandler.END
            else:
                # Qayta faollashtirish
                existing.is_active = True
                existing.title = chat.title
                existing.username = chat.username
                existing.save()

                await update.message.reply_html(
                    f"✅ <b>Kanal qayta faollashtirildi!</b>\n\n"
                    f"📢 {chat.title}\n"
                    f"🆔 <code>{chat.id}</code>"
                )
                return ConversationHandler.END

        # Yangi kanal qo'shish
        Channel.create(
            channel_id=chat.id,
            username=chat.username,
            title=chat.title,
            is_active=True
        )

        await update.message.reply_html(
            f"✅ <b>Kanal qo'shildi!</b>\n\n"
            f"📢 {chat.title}\n"
            f"🆔 <code>{chat.id}</code>\n\n"
            f"Endi foydalanuvchilar bu kanalga a'zo bo'lishi kerak."
        )

        return ConversationHandler.END

    except Exception as e:
        await update.message.reply_html(
            f"❌ <b>Xatolik:</b> {str(e)}\n\n"
            "Qaytadan urinib ko'ring yoki /cancel bosing."
        )
        return WAITING_CHANNEL_ID


async def cancel_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal qo'shishni bekor qilish"""
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


@admin_only
async def list_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanallar ro'yxati"""
    query = update.callback_query
    await query.answer()

    channels = list(Channel.select().where(Channel.is_active == True))

    if not channels:
        await query.message.edit_text(
            "📢 <b>Kanallar ro'yxati</b>\n\n"
            "Hali kanal qo'shilmagan.",
            parse_mode="HTML",
            reply_markup=channels_keyboard()
        )
        return

    text = "📢 <b>Majburiy kanallar</b>\n\n"

    keyboard = []
    for channel in channels:
        text += f"• {channel.title}\n"
        text += f"  🆔 <code>{channel.channel_id}</code>\n\n"

        keyboard.append([
            InlineKeyboardButton(
                f"🗑 {channel.title[:20]}",
                callback_data=f"del_channel_{channel.id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_channels")])

    await query.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@admin_only
async def delete_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanalni o'chirish"""
    query = update.callback_query
    await query.answer()

    channel_id = int(query.data.replace("del_channel_", ""))

    try:
        channel = Channel.get_by_id(channel_id)
        channel.is_active = False
        channel.save()

        await query.answer(f"✅ {channel.title} o'chirildi!", show_alert=True)
    except Channel.DoesNotExist:
        await query.answer("❌ Kanal topilmadi!", show_alert=True)

    # Ro'yxatni yangilash
    await list_channels_callback(update, context)


@admin_only
async def users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchilar"""
    query = update.callback_query
    await query.answer()

    users = list(User.select().order_by(User.created_at.desc()).limit(15))

    text = f"👥 <b>Foydalanuvchilar</b> (so'nggi 15 ta)\n\n"

    for user in users:
        admin_badge = "👑 " if user.is_admin else ""
        text += f"{admin_badge}<code>{user.telegram_id}</code> - {user.full_name or 'Nomsiz'}\n"

    total = User.select().count()
    text += f"\n<b>Jami:</b> {total} ta"

    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def tests_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testlar"""
    query = update.callback_query
    await query.answer()

    tests = list(Test.select().order_by(Test.created_at.desc()).limit(15))

    text = f"📝 <b>Testlar</b> (so'nggi 15 ta)\n\n"

    for test in tests:
        status = "🟢" if test.is_active else "🔴"
        text += f"{status} <code>{test.unique_code}</code> - {test.total_questions} savol\n"

    total = Test.select().count()
    text += f"\n<b>Jami:</b> {total} ta"

    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha foydalanuvchilarga xabar yuborish"""
    if not context.args:
        await update.message.reply_html(
            "❌ Xabar matnini kiriting!\n"
            "Masalan: <code>/broadcast Salom, yangilik bor!</code>"
        )
        return

    message = ' '.join(context.args)
    users = list(User.select())

    sent = 0
    failed = 0

    status_msg = await update.message.reply_text(f"📤 Xabar yuborilmoqda... 0/{len(users)}")

    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=f"📢 <b>Admin xabari:</b>\n\n{message}",
                parse_mode="HTML"
            )
            sent += 1
        except Exception:
            failed += 1

        if (sent + failed) % 10 == 0:
            try:
                await status_msg.edit_text(f"📤 Xabar yuborilmoqda... {sent + failed}/{len(users)}")
            except Exception:
                pass

    await status_msg.edit_text(
        f"✅ Xabar yuborildi!\n\n"
        f"📤 Yuborildi: {sent} ta\n"
        f"❌ Xato: {failed} ta"
    )


# ============ ADMIN MANAGEMENT ============

@admin_only
async def admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adminlar boshqaruvi"""
    query = update.callback_query
    await query.answer()

    text = "👑 <b>Adminlar boshqaruvi</b>\n\n"
    text += "Bot adminlarini bu yerda boshqarishingiz mumkin."

    await query.message.edit_text(text, parse_mode="HTML", reply_markup=admins_keyboard())


@admin_only
async def add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin qo'shishni boshlash"""
    query = update.callback_query
    await query.answer()

    await query.message.edit_text(
        "👑 <b>Admin qo'shish</b>\n\n"
        "Admin qilmoqchi bo'lgan foydalanuvchining Telegram ID sini kiriting:\n\n"
        "Masalan: <code>123456789</code>\n\n"
        "💡 ID ni olish uchun foydalanuvchi botga /start yuborishi kerak.\n\n"
        "❌ Bekor qilish: /cancel",
        parse_mode="HTML"
    )

    return WAITING_ADMIN_ID


async def receive_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin ID ni qabul qilish"""
    text = update.message.text.strip()

    try:
        admin_id = int(text)

        # Foydalanuvchini topish
        try:
            user = User.get(User.telegram_id == admin_id)
        except User.DoesNotExist:
            await update.message.reply_html(
                "❌ <b>Foydalanuvchi topilmadi!</b>\n\n"
                "Bu foydalanuvchi hali botga /start yubormagan.\n\n"
                "❌ Bekor qilish: /cancel"
            )
            return WAITING_ADMIN_ID

        # Allaqachon admin ekanligini tekshirish
        if user.is_admin or admin_id == ADMIN_ID:
            await update.message.reply_text("⚠️ Bu foydalanuvchi allaqachon admin!")
            return ConversationHandler.END

        # Admin qilish
        user.is_admin = True
        user.save()

        await update.message.reply_html(
            f"✅ <b>Admin qo'shildi!</b>\n\n"
            f"👤 {user.full_name or user.username or 'Nomsiz'}\n"
            f"🆔 <code>{user.telegram_id}</code>"
        )

        # Yangi adminga xabar yuborish
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text="👑 Siz admin qilindingiz! Endi /admin buyrug'ini ishlatishingiz mumkin.",
            )
        except Exception:
            pass

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_html(
            "❌ <b>Noto'g'ri format!</b>\n\n"
            "Faqat raqam kiriting.\n\n"
            "❌ Bekor qilish: /cancel"
        )
        return WAITING_ADMIN_ID


async def cancel_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin qo'shishni bekor qilish"""
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


@admin_only
async def list_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adminlar ro'yxati"""
    query = update.callback_query
    await query.answer()

    admins = list(User.select().where(User.is_admin == True))

    text = "👑 <b>Adminlar ro'yxati</b>\n\n"

    # Asosiy admin (.env dan)
    text += f"🔒 <b>Asosiy admin:</b> <code>{ADMIN_ID}</code>\n\n"

    if not admins:
        text += "📋 Qo'shimcha admin yo'q."
        keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_admins")]]
    else:
        text += "<b>Qo'shimcha adminlar:</b>\n"
        keyboard = []
        for admin in admins:
            if admin.telegram_id == ADMIN_ID:
                continue  # Asosiy adminni o'tkazib yuborish
            text += f"• {admin.full_name or 'Nomsiz'} - <code>{admin.telegram_id}</code>\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑 {admin.full_name or admin.telegram_id}",
                    callback_data=f"del_admin_{admin.id}"
                )
            ])

        keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_admins")])

    await query.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@admin_only
async def delete_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adminni o'chirish"""
    query = update.callback_query
    user_id = update.effective_user.id

    # Faqat asosiy admin o'chira oladi
    if user_id != ADMIN_ID:
        await query.answer("❌ Faqat asosiy admin o'chira oladi!", show_alert=True)
        return

    admin_db_id = int(query.data.replace("del_admin_", ""))

    try:
        admin = User.get_by_id(admin_db_id)
        admin.is_admin = False
        admin.save()

        await query.answer(f"✅ {admin.full_name or 'Admin'} o'chirildi!", show_alert=True)

        # Xabar yuborish
        try:
            await context.bot.send_message(
                chat_id=admin.telegram_id,
                text="ℹ️ Sizning admin huquqlaringiz olib tashlandi.",
            )
        except Exception:
            pass

    except User.DoesNotExist:
        await query.answer("❌ Admin topilmadi!", show_alert=True)

    # Ro'yxatni yangilash
    await list_admins_callback(update, context)


def get_handlers():
    """Handlerlarni qaytarish"""
    # Kanal qo'shish conversation
    add_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_channel_callback, pattern=r"^add_channel$")],
        states={
            WAITING_CHANNEL_ID: [
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receive_channel_id)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add_channel)],
    )

    # Admin qo'shish conversation
    add_admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_admin_callback, pattern=r"^add_admin$")],
        states={
            WAITING_ADMIN_ID: [
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receive_admin_id)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add_admin)],
    )

    return [
        CommandHandler("admin", admin_command, filters=filters.ChatType.PRIVATE),
        CommandHandler("broadcast", broadcast_command, filters=filters.ChatType.PRIVATE),
        add_channel_conv,
        add_admin_conv,
        CallbackQueryHandler(admin_back_callback, pattern=r"^admin_back$"),
        CallbackQueryHandler(channels_callback, pattern=r"^admin_channels$"),
        CallbackQueryHandler(list_channels_callback, pattern=r"^list_channels$"),
        CallbackQueryHandler(delete_channel_callback, pattern=r"^del_channel_"),
        CallbackQueryHandler(admins_callback, pattern=r"^admin_admins$"),
        CallbackQueryHandler(list_admins_callback, pattern=r"^list_admins$"),
        CallbackQueryHandler(delete_admin_callback, pattern=r"^del_admin_"),
        CallbackQueryHandler(users_callback, pattern=r"^admin_users$"),
        CallbackQueryHandler(tests_callback, pattern=r"^admin_tests$"),
    ]



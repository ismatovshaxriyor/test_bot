"""Admin handlerlari"""
import asyncio
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from telegram.error import TelegramError

from database import User, Test, TestSubmission, Channel, AdminTestWatch
from config import ADMIN_ID
from backup import send_backup
from utils import get_question_stats, format_stats

# Conversation states
WAITING_CHANNEL_ID = 0
WAITING_ADMIN_ID = 1
WAITING_BROADCAST_MSG = 2      # admin yubormoqchi bo'lgan xabarni kutish
WAITING_BROADCAST_CONFIRM = 3  # preview + tasdiq
WAITING_RESULT_CODE = 4        # natija qidirish — test kodini kutish


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
        [InlineKeyboardButton("📨 Xabar yuborish", callback_data="admin_broadcast")],
        [
            InlineKeyboardButton("📝 Testlar", callback_data="admin_tests"),
            InlineKeyboardButton("🟢 Faol testlar", callback_data="admin_active_tests"),
        ],
        [InlineKeyboardButton("💾 Zaxira olish (Backup)", callback_data="admin_backup")],
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


def _admin_panel_text() -> str:
    """Admin panel sarlavhasi + qisqa statistika."""
    total_users = User.select().count()
    total_tests = Test.select().count()
    active_tests = Test.select().where(Test.is_active == True).count()
    total_channels = Channel.select().where(Channel.is_active == True).count()

    text = f"👑 <b>Admin Panel</b>\n\n"
    text += f"👥 Foydalanuvchilar: {total_users} ta\n"
    text += f"📝 Barcha testlar: {total_tests} ta\n"
    text += f"🟢 Faol testlar: {active_tests} ta\n"
    text += f"📢 Majburiy kanallar: {total_channels} ta\n"
    return text


async def _show_admin_panel_edit(query):
    """Mavjud xabarni admin panelga aylantirib tahrirlaydi (bekor/qaytish uchun)."""
    try:
        await query.message.edit_text(
            _admin_panel_text(), parse_mode="HTML", reply_markup=admin_keyboard()
        )
    except Exception:
        # Tahrirlab bo'lmasa (masalan, media xabari) — yangi xabar bilan ko'rsatamiz
        await query.message.reply_html(_admin_panel_text(), reply_markup=admin_keyboard())


async def _edit_message_to_panel(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id) -> bool:
    """Saqlangan xabarni (chat_id+message_id) admin panelga tahrirlaydi.

    `/cancel` buyrug'i orqali bekor qilinganda ishlatiladi: bot avval ko'rsatgan
    so'rov xabarini panelga aylantiramiz (yangi "Bekor qilindi" xabari o'rniga).
    """
    if not chat_id or not message_id:
        return False
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=_admin_panel_text(),
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )
        return True
    except Exception:
        return False


@admin_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    await update.message.reply_html(_admin_panel_text(), reply_markup=admin_keyboard())


@admin_only
async def admin_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panelga qaytish"""
    query = update.callback_query
    await query.answer()
    await _show_admin_panel_edit(query)


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
            if chat.type != "channel":
                await update.message.reply_html(
                    "❌ <b>Bu chat kanal emas!</b>\n\n"
                    "Iltimos, faqat kanal ID yoki @username yuboring.\n\n"
                    "❌ Bekor qilish: /cancel"
                )
                return WAITING_CHANNEL_ID

            bot_info = await context.bot.get_me()
            bot_member = await context.bot.get_chat_member(chat.id, bot_info.id)

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
                    f"📢 {escape(chat.title or '')}\n"
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
            f"📢 {escape(chat.title or '')}\n"
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
        text += f"• {escape(channel.title or '')}\n"
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

    try:
        channel_id = int(query.data.replace("del_channel_", ""))
        channel = Channel.get_by_id(channel_id)
        channel.is_active = False
        channel.save()

        await query.answer(f"✅ {channel.title} o'chirildi!", show_alert=True)
    except (ValueError, Channel.DoesNotExist):
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
        text += f"{admin_badge}<code>{user.telegram_id}</code> - {escape(user.full_name or 'Nomsiz')}\n"

    total = User.select().count()
    text += f"\n<b>Jami:</b> {total} ta"

    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def tests_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testlar — so'nggi 15 ta"""
    query = update.callback_query
    await query.answer()

    tests = list(Test.select().order_by(Test.created_at.desc()).limit(15))

    text = f"📝 <b>Testlar</b> (so'nggi 15 ta)\n\n"

    for test in tests:
        status = "🟢" if test.is_active else "🔴"
        text += f"{status} <code>{test.id}</code> - {test.total_questions} savol\n"

    total = Test.select().count()
    text += f"\n<b>Jami:</b> {total} ta"

    keyboard = [
        [InlineKeyboardButton("🔍 Natija qidirish", callback_data="admin_search_result")],
        [InlineKeyboardButton("🟢 Faol testlar (kuzatuv)", callback_data="admin_active_tests")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")],
    ]
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


@admin_only
async def admin_active_tests_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Faol testlar ro'yxati — kuzatuv tugmalari bilan"""
    query = update.callback_query
    await query.answer()
    admin_user_id = update.effective_user.id

    try:
        admin_db = User.get(User.telegram_id == admin_user_id)
    except User.DoesNotExist:
        await query.answer("❌ Admin topilmadi!", show_alert=True)
        return

    active_tests = list(Test.select().where(Test.is_active == True).order_by(Test.created_at.desc()))

    if not active_tests:
        await query.message.edit_text(
            "🟢 <b>Faol testlar</b>\n\nHozircha faol test yo'q.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_tests")]])
        )
        return

    # Admin kuzatayotgan test IDlari
    watching_ids = set(
        w.test_id for w in AdminTestWatch.select().where(AdminTestWatch.admin == admin_db)
    )

    text = "🟢 <b>Faol testlar</b>\n"
    text += "🔔 = kuzatilmoqda | 🔕 = kuzatilmayapti\n\n"

    keyboard = []
    for test in active_tests:
        watching = test.id in watching_ids
        bell = "🔔" if watching else "🔕"
        creator_name = test.creator.full_name or test.creator.username or str(test.creator.telegram_id)
        text += f"{bell} <code>{test.id}</code> — {test.total_questions} savol | {escape(creator_name)}\n"

        toggle_label = "🔕 Bekor qilish" if watching else "🔔 Kuzatish"
        keyboard.append([
            InlineKeyboardButton(
                f"🔴 Tugatish (#{test.id})",
                callback_data=f"admin_end_{test.id}"
            ),
            InlineKeyboardButton(
                f"{toggle_label} (#{test.id})",
                callback_data=f"watch_test_{test.id}"
            ),
        ])

    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_tests")])

    await query.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@admin_only
async def admin_watch_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test kuzatuvini yoqish/o'chirish"""
    query = update.callback_query
    admin_user_id = update.effective_user.id

    try:
        test_id = int(query.data.replace("watch_test_", ""))
    except ValueError:
        await query.answer("❌ Noto'g'ri ma'lumot.", show_alert=True)
        return

    try:
        admin_db = User.get(User.telegram_id == admin_user_id)
    except User.DoesNotExist:
        await query.answer("❌ Admin topilmadi!", show_alert=True)
        return

    try:
        test = Test.get_by_id(test_id)
    except Test.DoesNotExist:
        await query.answer("❌ Test topilmadi!", show_alert=True)
        return

    existing = AdminTestWatch.get_or_none(
        (AdminTestWatch.admin == admin_db) & (AdminTestWatch.test == test)
    )

    if existing:
        existing.delete_instance()
        await query.answer(f"🔕 #{test_id} kuzatuv bekor qilindi", show_alert=False)
    else:
        AdminTestWatch.create(admin=admin_db, test=test)
        await query.answer(f"🔔 #{test_id} kuzatuvga qo'shildi!", show_alert=False)

    # Ro'yxatni yangilash
    await admin_active_tests_callback(update, context)


@admin_only
async def admin_end_test_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test tugatish — tasdiqlash so'rash"""
    query = update.callback_query
    # query.answer() ni HALI chaqirmaymiz — test topilmasa xato ko'ramiz

    test_id_str = query.data.replace("admin_end_", "")
    try:
        test_id = int(test_id_str)
        test = Test.get_by_id(test_id)
    except (ValueError, Test.DoesNotExist):
        await query.answer("❌ Test topilmadi!", show_alert=True)
        return

    await query.answer()  # Endi xavfsiz ravishda javob beramiz

    creator_name = test.creator.full_name or test.creator.username or str(test.creator.telegram_id)
    keyboard = [
        [
            InlineKeyboardButton("✅ Ha, tugatish", callback_data=f"admin_confirm_end_{test_id}"),
            InlineKeyboardButton("❌ Bekor", callback_data="admin_active_tests"),
        ]
    ]
    await query.message.edit_text(
        f"🔴 <b>Testni tugatish</b>\n\n"
        f"📝 Test: <code>{test_id}</code>\n"
        f"👤 Yaratuvchi: {escape(creator_name)}\n"
        f"📊 Savollar: {test.total_questions}\n\n"
        f"Testni tugatishni tasdiqlaysizmi?\n"
        f"⚠️ Tugatilgan test yangi javoblarni qabul qilmaydi!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@admin_only
async def admin_confirm_end_test_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test tugatishni tasdiqlash"""
    from datetime import datetime
    query = update.callback_query

    test_id_str = query.data.replace("admin_confirm_end_", "")
    try:
        test_id = int(test_id_str)
        test = Test.get_by_id(test_id)
    except (ValueError, Test.DoesNotExist):
        await query.answer("❌ Test topilmadi!", show_alert=True)
        return

    test.is_active = False
    test.ended_at = datetime.now()
    test.save()

    # Kuzatuvchilarni ham o'chirish (test tugadi)
    AdminTestWatch.delete().where(AdminTestWatch.test == test).execute()

    await query.answer(f"✅ #{test_id} test tugatildi!", show_alert=True)

    # Ishtirokchilarga yakuniy natijalarni yuborish (creator yakunlagandagi kabi)
    from handlers.test_manage import _notify_participants_final_results
    await _notify_participants_final_results(context, test)

    # Test egasiga xabar (admin tugatgani haqida)
    if test.creator.telegram_id != update.effective_user.id:
        try:
            await context.bot.send_message(
                chat_id=test.creator.telegram_id,
                text=(
                    f"ℹ️ <b>Sizning testingiz admin tomonidan yakunlandi.</b>\n\n"
                    f"📝 Test: <code>{test.id}</code>"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await admin_active_tests_callback(update, context)


@admin_only
async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Database'ning zaxira nusxasini olib, adminga yuborish (manual tugma)"""
    query = update.callback_query
    await query.answer("💾 Zaxira tayyorlanmoqda...")

    try:
        await send_backup(context.bot, update.effective_user.id)
    except Exception as e:
        await query.message.reply_text(f"❌ Zaxira olishda xatolik: {e}")


# ============ BROADCAST (hamma foydalanuvchilarga xabar) ============

@admin_only
async def broadcast_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xabar yuborishni boshlash — admindan xabarni so'rash."""
    query = update.callback_query
    await query.answer()

    context.user_data.pop("broadcast_from_chat_id", None)
    context.user_data.pop("broadcast_message_id", None)

    total_users = User.select().count()
    await query.message.edit_text(
        "📨 <b>Xabar yuborish</b>\n\n"
        f"Bu xabar barcha <b>{total_users} ta</b> foydalanuvchiga yuboriladi.\n\n"
        "Yubormoqchi bo'lgan xabaringizni hozir shu yerga yuboring — "
        "<b>matn, rasm, video yoki fayl</b> bo'lishi mumkin. Xabar foydalanuvchilarga "
        "aynan o'zingiz yuborgan ko'rinishda yetkaziladi.\n\n"
        "❌ Bekor qilish: /cancel",
        parse_mode="HTML",
    )
    # Bekor qilinganda shu so'rov xabarini admin panelga qaytarish uchun saqlaymiz
    context.user_data["broadcast_prompt_chat_id"] = query.message.chat_id
    context.user_data["broadcast_prompt_message_id"] = query.message.message_id
    return WAITING_BROADCAST_MSG


async def broadcast_receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adminning xabarini olib, preview + tasdiq ko'rsatish.

    Xabarning manzili (chat_id + message_id) saqlanadi — tasdiqlangach
    `copy_message` orqali har bir foydalanuvchiga aynan shu xabar nusxalanadi.
    """
    msg = update.message
    context.user_data["broadcast_from_chat_id"] = msg.chat_id
    context.user_data["broadcast_message_id"] = msg.message_id

    total_users = User.select().count()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Ha, yuborish", callback_data="broadcast_send"),
            InlineKeyboardButton("❌ Bekor", callback_data="broadcast_cancel"),
        ]
    ])
    await msg.reply_html(
        f"☝️ <b>Yuqoridagi xabar</b> {total_users} ta foydalanuvchiga yuboriladi.\n\n"
        f"Tasdiqlaysizmi?",
        reply_markup=keyboard,
    )
    return WAITING_BROADCAST_CONFIRM


async def _run_broadcast(bot, from_chat_id: int, message_id: int, status_message):
    """Xabarni barcha foydalanuvchilarga ORQA FONDA yuboradi.

    Bu korutina alohida vazifa (task) sifatida ishga tushiriladi — shuning uchun
    yuborish minutlab cho'zilsa ham botning asosiy update oqimini bloklamaydi,
    bot boshqa foydalanuvchilarga javob berishda davom etadi. Jarayon davomida
    `status_message` (tasdiq xabari) progress bilan yangilanadi.
    """
    users = list(User.select())
    total = len(users)

    sent = 0
    failed = 0
    for user in users:
        try:
            await bot.copy_message(
                chat_id=user.telegram_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            sent += 1
        except Exception:
            failed += 1

        # Telegram flood limitiga (~30 msg/sek) tushmaslik uchun
        await asyncio.sleep(0.05)

        if (sent + failed) % 25 == 0:
            try:
                await status_message.edit_text(f"📤 Xabar yuborilmoqda... {sent + failed}/{total}")
            except Exception:
                pass

    try:
        await status_message.edit_text(
            f"✅ <b>Xabar yuborildi!</b>\n\n"
            f"📤 Yuborildi: {sent} ta\n"
            f"❌ Yetib bormadi: {failed} ta",
            parse_mode="HTML",
        )
    except Exception:
        pass


@admin_only
async def broadcast_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tasdiq — yuborishni orqa fon vazifasi sifatida boshlash (botni bloklamaydi)."""
    query = update.callback_query
    await query.answer()

    from_chat_id = context.user_data.pop("broadcast_from_chat_id", None)
    message_id = context.user_data.pop("broadcast_message_id", None)
    context.user_data.pop("broadcast_prompt_chat_id", None)
    context.user_data.pop("broadcast_prompt_message_id", None)

    if not from_chat_id or not message_id:
        await query.message.edit_text("❌ Sessiya muddati tugadi. Qaytadan boshlang.")
        return ConversationHandler.END

    total = User.select().count()
    try:
        await query.message.edit_text(f"📤 Xabar yuborish boshlandi (orqa fonda)... 0/{total}")
    except Exception:
        pass

    # Yuborish sikli alohida task'da ishlaydi: handler darrov tugaydi, bot
    # boshqa so'rovlarga javob berishda davom etadi. Task application tomonidan
    # kuzatiladi (yo'qolib ketmaydi, to'xtaganda kutiladi).
    context.application.create_task(
        _run_broadcast(context.bot, from_chat_id, message_id, query.message)
    )
    return ConversationHandler.END


async def broadcast_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tasdiq bosqichida bekor qilish (tugma) — darrov admin panelga qaytadi."""
    query = update.callback_query
    await query.answer("❌ Bekor qilindi")
    context.user_data.pop("broadcast_from_chat_id", None)
    context.user_data.pop("broadcast_message_id", None)
    context.user_data.pop("broadcast_prompt_chat_id", None)
    context.user_data.pop("broadcast_prompt_message_id", None)
    await _show_admin_panel_edit(query)
    return ConversationHandler.END


async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel — xabar yuborishni bekor qilib, admin panelga qaytish.

    Yangi "Bekor qilindi" xabari o'rniga, bot avval ko'rsatgan so'rov xabarini
    admin panelga aylantiramiz (tahrirlab). Tahrir imkonsiz bo'lsa — yangi panel.
    """
    context.user_data.pop("broadcast_from_chat_id", None)
    context.user_data.pop("broadcast_message_id", None)
    prompt_chat_id = context.user_data.pop("broadcast_prompt_chat_id", None)
    prompt_message_id = context.user_data.pop("broadcast_prompt_message_id", None)

    chat_id = update.effective_chat.id

    # Foydalanuvchi yuborgan /cancel xabarini o'chiramiz (private chatda bot
    # kiruvchi xabarni o'chira oladi) — chat toza qolsin.
    try:
        await update.message.delete()
    except Exception:
        pass

    edited = await _edit_message_to_panel(context, prompt_chat_id, prompt_message_id)
    if not edited:
        await context.bot.send_message(
            chat_id=chat_id,
            text=_admin_panel_text(),
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )
    return ConversationHandler.END


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
            f"👤 {escape(user.full_name or user.username or 'Nomsiz')}\n"
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
            text += f"• {escape(admin.full_name or 'Nomsiz')} - <code>{admin.telegram_id}</code>\n"
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

    try:
        admin_db_id = int(query.data.replace("del_admin_", ""))
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

    except (ValueError, User.DoesNotExist):
        await query.answer("❌ Admin topilmadi!", show_alert=True)

    # Ro'yxatni yangilash
    await list_admins_callback(update, context)


@admin_only
async def whois_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/whois <id> — ID'ni bosiladigan Telegram mention'iga aylantiradi.

    `<a href="tg://user?id=...">` havolasini bosganda Telegram o'sha foydalanuvchi
    profilini ochadi (mijoz ID'ni hal qila olsa). Bot o'sha odamni ilgari ko'rgan
    bo'lsa, ism/username ham qo'shiladi.
    """
    args = context.args
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "Foydalanish: /whois <telegram_id>\nMasalan: /whois 123456789"
        )
        return

    uid = int(args[0])
    lines = [
        f"🆔 <code>{uid}</code>",
        "",
        f'<a href="tg://user?id={uid}">👤 Profilni ochish</a>  '
        f'(havolani bosing — profil ochiladi)',
    ]

    # Bizning bazada bormi?
    try:
        u = User.get(User.telegram_id == uid)
        uname = f"@{u.username}" if u.username else "—"
        lines += ["", "📂 <b>Botda mavjud:</b>",
                  f"• Ism: {escape(u.full_name or '—')}",
                  f"• Username: {escape(uname)}"]
    except User.DoesNotExist:
        pass

    # Telegram'dan (bot bu chatni ko'ra olsa — odam botga yozgan bo'lsa)
    try:
        chat = await context.bot.get_chat(uid)
        nm = " ".join(filter(None, [chat.first_name, chat.last_name])) or "—"
        cu = f"@{chat.username}" if chat.username else "—"
        lines += ["", "🌐 <b>Telegram:</b>",
                  f"• Ism: {escape(nm)}",
                  f"• Username: {escape(cu)}"]
    except TelegramError:
        lines += ["", "ℹ️ Bot bu foydalanuvchini to'g'ridan-to'g'ri ko'ra olmadi "
                  "(u botga yozmagan bo'lishi mumkin) — havolani bosib ko'ring."]

    await update.message.reply_html("\n".join(lines), disable_web_page_preview=True)


# ============ TEST NATIJASINI QIDIRISH (faqat admin) ============

async def _send_test_result(message, code: str) -> bool:
    """Test kodi bo'yicha natijani (statistikani) ko'rsatadi.

    Admin uchun — yaratuvchi cheklovi yo'q (kirish allaqachon @admin_only bilan
    himoyalangan). Test topilmasa False qaytaradi (chaqiruvchi qayta so'raydi).
    """
    try:
        if not str(code).isdigit():
            raise Test.DoesNotExist
        test = Test.get_by_id(int(code))
    except Test.DoesNotExist:
        return False

    creator_name = (
        test.creator.full_name or test.creator.username or str(test.creator.telegram_id)
    )

    if test.is_active:
        # Faol test — to'liq natija hali yo'q (ishtirokchilar sonini ko'rsatamiz)
        subs_count = TestSubmission.select().where(TestSubmission.test == test).count()
        text = (
            f"📊 <b>Test natijasi</b>\n\n"
            f"📝 Test kodi: <code>{test.id}</code>\n"
            f"👤 Yaratuvchi: {escape(creator_name)}\n"
            f"❓ Savollar soni: {test.total_questions} ta\n"
            f"👥 Ishtirokchilar: {subs_count} ta\n\n"
            f"🟢 Test faol\n\n"
            f"⚠️ To'liq natija test yakunlangandan keyin ko'rsatiladi."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Testlarga qaytish", callback_data="admin_tests")],
        ])
    else:
        # Yakunlangan test — to'liq statistika
        stats = get_question_stats(test)
        text = format_stats(stats, test)
        text += "\n\n🔴 Test yakunlangan"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📥 Excel", callback_data=f"export_excel_{test.id}"),
                InlineKeyboardButton("📥 PDF", callback_data=f"export_pdf_{test.id}"),
                InlineKeyboardButton("📊 Grafik", callback_data=f"export_chart_{test.id}"),
            ],
            [InlineKeyboardButton("🔙 Testlarga qaytish", callback_data="admin_tests")],
        ])

    await message.reply_html(text, reply_markup=keyboard)
    return True


@admin_only
async def search_result_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔍 Natija qidirish — admindan test kodini so'rash."""
    query = update.callback_query
    await query.answer()

    await query.message.edit_text(
        "🔍 <b>Test natijasini qidirish</b>\n\n"
        "Natijasini ko'rmoqchi bo'lgan test <b>kodini</b> kiriting:\n\n"
        "Masalan: <code>123</code>\n\n"
        "❌ Bekor qilish: /cancel",
        parse_mode="HTML",
    )
    # Bekor qilinganda shu so'rov xabarini admin panelga qaytarish uchun saqlaymiz
    context.user_data["result_prompt_chat_id"] = query.message.chat_id
    context.user_data["result_prompt_message_id"] = query.message.message_id
    return WAITING_RESULT_CODE


async def receive_result_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kiritilgan test kodi bo'yicha natijani chiqarish."""
    raw = (update.message.text or "").strip().lstrip("#").strip()

    if not raw.isdigit():
        await update.message.reply_html(
            "❌ Test kodi raqamlardan iborat bo'lishi kerak.\n"
            "Qaytadan kiriting yoki /cancel."
        )
        return WAITING_RESULT_CODE

    found = await _send_test_result(update.message, raw)
    if not found:
        await update.message.reply_html(
            f"❌ <code>{escape(raw)}</code> kodli test topilmadi.\n"
            "Boshqa kod kiriting yoki /cancel."
        )
        return WAITING_RESULT_CODE

    context.user_data.pop("result_prompt_chat_id", None)
    context.user_data.pop("result_prompt_message_id", None)
    return ConversationHandler.END


async def cancel_search_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel — natija qidirishni bekor qilib, admin panelga qaytish."""
    prompt_chat_id = context.user_data.pop("result_prompt_chat_id", None)
    prompt_message_id = context.user_data.pop("result_prompt_message_id", None)
    chat_id = update.effective_chat.id

    # Foydalanuvchi yuborgan /cancel xabarini o'chiramiz — chat toza qolsin.
    try:
        await update.message.delete()
    except Exception:
        pass

    edited = await _edit_message_to_panel(context, prompt_chat_id, prompt_message_id)
    if not edited:
        await context.bot.send_message(
            chat_id=chat_id,
            text=_admin_panel_text(),
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )
    return ConversationHandler.END


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

    # Xabar yuborish (broadcast) conversation
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_start_callback, pattern=r"^admin_broadcast$")],
        states={
            WAITING_BROADCAST_MSG: [
                # Istalgan turdagi xabar (matn/rasm/video/fayl), buyruq va service xabarlardan tashqari
                MessageHandler(
                    filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
                    broadcast_receive_message,
                ),
            ],
            WAITING_BROADCAST_CONFIRM: [
                CallbackQueryHandler(broadcast_confirm_callback, pattern=r"^broadcast_send$"),
                CallbackQueryHandler(broadcast_cancel_callback, pattern=r"^broadcast_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_broadcast, filters=filters.ChatType.PRIVATE)],
        allow_reentry=True,
    )

    # Test natijasini qidirish (faqat admin) conversation
    search_result_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(search_result_start_callback, pattern=r"^admin_search_result$")],
        states={
            WAITING_RESULT_CODE: [
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, receive_result_code),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_search_result, filters=filters.ChatType.PRIVATE)],
        allow_reentry=True,
    )

    return [
        CommandHandler("admin", admin_command, filters=filters.ChatType.PRIVATE),
        CommandHandler("whois", whois_command, filters=filters.ChatType.PRIVATE),
        add_channel_conv,
        add_admin_conv,
        broadcast_conv,
        search_result_conv,
        CallbackQueryHandler(admin_back_callback, pattern=r"^admin_back$"),
        CallbackQueryHandler(admin_backup_callback, pattern=r"^admin_backup$"),
        CallbackQueryHandler(channels_callback, pattern=r"^admin_channels$"),
        CallbackQueryHandler(list_channels_callback, pattern=r"^list_channels$"),
        CallbackQueryHandler(delete_channel_callback, pattern=r"^del_channel_"),
        CallbackQueryHandler(admins_callback, pattern=r"^admin_admins$"),
        CallbackQueryHandler(list_admins_callback, pattern=r"^list_admins$"),
        CallbackQueryHandler(delete_admin_callback, pattern=r"^del_admin_"),
        CallbackQueryHandler(users_callback, pattern=r"^admin_users$"),
        CallbackQueryHandler(tests_callback, pattern=r"^admin_tests$"),
        CallbackQueryHandler(admin_active_tests_callback, pattern=r"^admin_active_tests$"),
        CallbackQueryHandler(admin_watch_toggle_callback, pattern=r"^watch_test_"),
        CallbackQueryHandler(admin_end_test_callback, pattern=r"^admin_end_"),
        CallbackQueryHandler(admin_confirm_end_test_callback, pattern=r"^admin_confirm_end_"),
    ]


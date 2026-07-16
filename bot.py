"""
Telegram Test Bot
Test javoblarini tekshirish va statistika ko'rsatish
"""
import asyncio
import logging
from telegram import BotCommand
from telegram.ext import Application

from config import BOT_TOKEN, ADMIN_ID, BACKUP_INTERVAL_HOURS
from database import init_db, SystemSetting
from backup import send_backup

# Handlerlarni import qilish
from handlers import start, test_create, test_solve, test_manage, admin, inline, test_ai_create
from membership import check_membership_callback
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters
from keyboards import main_menu_keyboard

# Logging sozlash
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# Bot buyruqlari
BOT_COMMANDS = [
    BotCommand("start", "Botni boshlash"),
    BotCommand("cancel", "Jarayonni bekor qilish"),
    BotCommand("help", "Yordam"),
]


async def global_ortga_handler(update, context):
    """Global levelda (Conversationdan tashqari) kelgan 'Ortga' ni ushlab, menyuni ko'rsatadi"""
    await update.message.reply_text("🏠 Asosiy menyu:", reply_markup=main_menu_keyboard(update.effective_user.id))


async def global_cancel_handler(update, context):
    """Suhbatdan tashqarida /cancel kelganda menyuni ko'rsatadi (suhbat ichida fallback ishlaydi)"""
    await update.message.reply_text("🏠 Asosiy menyu:", reply_markup=main_menu_keyboard(update.effective_user.id))


async def backup_scheduler(application):
    """Belgilangan vaqt oralig'ida adminga avtomatik DB zaxirasini yuboradi.

    Sozlamalarni (yoqilganlik holati va interval) har safar DB dan o'qiydi.
    """
    if not ADMIN_ID:
        logger.info("ADMIN_ID topilmadi, avtomatik zaxira o'chirilgan")
        return

    logger.info("Avtomatik zaxira scheduleri ishga tushdi")

    # Avvalgi yuborilgan vaqtni saqlab turish uchun (bot ishga tushganda birinchi interval o'tgach zaxira olinadi)
    last_backup_time = asyncio.get_event_loop().time()

    while True:
        try:
            # Sozlamalarni DB dan olish
            try:
                enabled_setting = SystemSetting.get(SystemSetting.key == "backup_enabled")
                interval_setting = SystemSetting.get(SystemSetting.key == "backup_interval")
                enabled = enabled_setting.value == "1"
                interval_hours = float(interval_setting.value)
            except Exception:
                enabled = True
                interval_hours = 12.0

            if not enabled or interval_hours <= 0:
                await asyncio.sleep(30)
                continue

            current_time = asyncio.get_event_loop().time()
            elapsed_seconds = current_time - last_backup_time
            interval_seconds = interval_hours * 3600

            if elapsed_seconds >= interval_seconds:
                await send_backup(application.bot, ADMIN_ID, title="🤖 Avtomatik zaxira nusxasi")
                logger.info("✅ Avtomatik zaxira adminga yuborildi")
                last_backup_time = current_time

            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Avtomatik zaxira yuborishda xatolik")
            await asyncio.sleep(30)


async def main():
    """Botni ishga tushirish"""
    # Token tekshirish
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN topilmadi!")
        print("📝 .env faylini yarating va BOT_TOKEN ni kiriting.")
        print("📄 .env.example faylidan namuna oling.")
        return

    # Databaseni ishga tushirish
    init_db()

    # Application yaratish
    application = Application.builder().token(BOT_TOKEN).build()

    # (Global WebApp handler moved to the bottom so that conversation handlers can intercept it first)


    # Handlerlarni qo'shish
    # Start va help
    for handler in start.get_handlers():
        application.add_handler(handler)

    # Test yaratish (ConversationHandler)
    for handler in test_create.get_handlers():
        application.add_handler(handler)

    # Test yechish (ConversationHandler)
    for handler in test_solve.get_handlers():
        application.add_handler(handler)

    # Test boshqarish
    for handler in test_manage.get_handlers():
        application.add_handler(handler)

    # Admin
    for handler in admin.get_handlers():
        application.add_handler(handler)

    # Inline query
    for handler in inline.get_handlers():
        application.add_handler(handler)

    # Fayldan AI test yaratish + rasm biriktirish
    # Global WEB_APP_DATA / photo catch-all'lardan OLDIN qo'shiladi: suhbat ichidagi
    # fayl/rasm handlerlari ustun bo'lsin.
    for handler in test_ai_create.get_handlers():
        application.add_handler(handler)

    # Membership tekshirish callback
    application.add_handler(CallbackQueryHandler(check_membership_callback, pattern=r"^check_membership$"))

    # Global WebApp catch-all
    # Ushbu handler eng oxirida qo'shiladi, shunday qilib agar foydalanuvchi qandaydir Conversation
    # ichida WebApp ishlatgan bo'lsa, Conversation o'zi uni tutib oladi, agar yo'q bo'lsa, shunda global ushlaydi.
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, test_solve.webapp_receive_data))

    # Global Ortga catch-all (agar user Conversation ichida bo'lmasa ishlashi uchun oxirida qo'shildi!)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r'^(Ortga|❌ Bekor qilish)$'), global_ortga_handler))

    # Global /cancel catch-all (suhbat ichidagi fallback birinchi ishlaydi, bu faqat tashqarida)
    application.add_handler(CommandHandler("cancel", global_cancel_handler, filters=filters.ChatType.PRIVATE))

    # Botni ishga tushirish
    logger.info("🚀 Bot ishga tushmoqda...")
    print("🚀 Bot ishga tushdi!")
    print("📝 Testlarni yaratish va tekshirish uchun tayyor.")
    print("⏹️  To'xtatish uchun Ctrl+C bosing.")

    # Initialize and start polling
    await application.initialize()

    # Bot buyruqlarini o'rnatish
    await application.bot.set_my_commands(BOT_COMMANDS)
    logger.info("✅ Bot buyruqlari o'rnatildi")

    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    # Avtomatik zaxira jadvalini fon vazifasi sifatida ishga tushirish
    backup_task = asyncio.create_task(backup_scheduler(application))

    # Run until stopped
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        backup_task.cancel()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

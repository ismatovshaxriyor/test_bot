"""
Telegram Test Bot
Test javoblarini tekshirish va statistika ko'rsatish
"""
import asyncio
import logging
from telegram import BotCommand
from telegram.ext import Application

from config import BOT_TOKEN, ADMIN_ID, BACKUP_INTERVAL_HOURS
from database import init_db
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

    Birinchi zaxira bir interval o'tgach yuboriladi (bot qayta ishga tushganda
    darrov spam bo'lmasligi uchun).
    """
    if not ADMIN_ID or BACKUP_INTERVAL_HOURS <= 0:
        logger.info("Avtomatik zaxira o'chirilgan (ADMIN_ID yoki interval yo'q)")
        return

    interval_seconds = BACKUP_INTERVAL_HOURS * 3600
    logger.info("Avtomatik zaxira yoqildi: har %s soatda", BACKUP_INTERVAL_HOURS)

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await send_backup(application.bot, ADMIN_ID, title="🤖 Avtomatik zaxira nusxasi")
            logger.info("✅ Avtomatik zaxira adminga yuborildi")
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Avtomatik zaxira yuborishda xatolik")


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

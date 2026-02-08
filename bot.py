"""
Telegram Test Bot
Test javoblarini tekshirish va statistika ko'rsatish
"""
import asyncio
import logging
from telegram import BotCommand
from telegram.ext import Application

from config import BOT_TOKEN
from database import init_db

# Handlerlarni import qilish
from handlers import start, test_create, test_solve, test_manage, admin, inline
from membership import check_membership_callback
from telegram.ext import CallbackQueryHandler

# Logging sozlash
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# Bot buyruqlari
BOT_COMMANDS = [
    BotCommand("start", "Botni boshlash"),
    BotCommand("help", "Yordam"),
]


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

    # Membership tekshirish callback
    application.add_handler(CallbackQueryHandler(check_membership_callback, pattern=r"^check_membership$"))

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

    # Run until stopped
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())


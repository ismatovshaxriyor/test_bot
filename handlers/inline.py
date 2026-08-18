"""Inline query handler"""
from html import escape
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes, InlineQueryHandler
from uuid import uuid4

from database import Test


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline query orqali testni ulashish"""
    query = update.inline_query.query.strip()

    results = []

    # "test CODE" formatini tekshirish
    if query.startswith("test "):
        code = query.replace("test ", "").upper()

        if code.isdigit():
            try:
                test = Test.get_by_id(int(code))
                if test.is_active:
                    bot_info = await context.bot.get_me()
                    bot_username = bot_info.username

                    results.append(
                        InlineQueryResultArticle(
                            id=str(uuid4()),
                            title=f"📝 {test.name}",
                            description=f"❓ {test.total_questions} ta savol • Ulashish uchun bosing",
                            input_message_content=InputTextMessageContent(
                                message_text=(
                                    f"🎯 <b>Test Yechish Taklifi</b>\n"
                                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"📌 <b>Nomi:</b> {escape(test.name)}\n"
                                    f"📋 <b>Test kodi:</b> <code>{code}</code>\n"
                                    f"❓ <b>Savollar:</b> {test.total_questions} ta\n\n"
                                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"👉 <b>Boshlash:</b> https://t.me/{bot_username}?start={code}\n\n"
                                    f"🍀 Omad tilaymiz!"
                                ),
                                parse_mode="HTML"
                            )
                        )
                    )
            except Test.DoesNotExist:
                pass

    await update.inline_query.answer(results, cache_time=10)


def get_handlers():
    """Handlerlarni qaytarish"""
    return [
        InlineQueryHandler(inline_query_handler),
    ]

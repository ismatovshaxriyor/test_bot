"""Inline query handler"""
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
                            title=f"📝 Test: {code}",
                            description=f"❓ {test.total_questions} ta savol • Ulashish uchun bosing",
                            input_message_content=InputTextMessageContent(
                                message_text=(
                                    f"🎯 <b>Test Yechish Taklifi</b>\n"
                                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"📋 <b>Test kodi:</b> <code>{code}</code>\n"
                                    f"❓ <b>Savollar:</b> {test.total_questions} ta\n\n"
                                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"📲 <b>Qanday yechish:</b>\n"
                                    f"1️⃣ @{bot_username} botiga o'ting\n"
                                    f"2️⃣ <b>✍️ Test yechish</b> tugmasini bosing\n"
                                    f"3️⃣ Kodini kiriting: <code>{code}</code>\n\n"
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

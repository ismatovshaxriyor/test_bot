"""Test yechish handleri"""
from telegram import Update
from telegram.ext import (
    ContextTypes, CommandHandler,
    MessageHandler, ConversationHandler, filters
)

from database import get_or_create_user, Test, TestSubmission
from utils import check_answers, format_result
from config import ADMIN_ID
from keyboards import main_menu_keyboard
from membership import membership_required

# Conversation states
WAITING_TEST_CODE = 0
WAITING_USER_ANSWERS = 1


@membership_required
async def solve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testni yechishni boshlash"""
    # Argumentdan kodni olish
    if not context.args:
        await update.message.reply_html(
            "✍️ <b>Test yechish</b>\n\n"
            "Test egasi sizga yuborgan <b>6 xonali kodni</b> kiriting:\n\n"
            "💡 Kod harflar va raqamlardan iborat\n"
            "(masalan: <code>5NI7HB</code> yoki <code>K9X2LM</code>)\n\n"
            "❌ Bekor qilish: /cancel"
        )
        return WAITING_TEST_CODE

    code = context.args[0].upper()
    return await process_test_code(update, context, code)


async def receive_test_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test kodini qabul qilish"""
    code = update.message.text.strip().upper()
    return await process_test_code(update, context, code)


async def process_test_code(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    """Test kodini qayta ishlash"""
    # Testni topish
    try:
        test = Test.get(Test.unique_code == code)
    except Test.DoesNotExist:
        await update.message.reply_text(
            f"❌ '{code}' kodli test topilmadi!\n\n"
            "Qaytadan urinib ko'ring yoki /cancel bosing."
        )
        return WAITING_TEST_CODE

    # Test faolligini tekshirish
    if not test.is_active:
        await update.message.reply_text(
            f"❌ Bu test allaqachon yakunlangan!",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    user = update.effective_user
    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    # O'zi yaratgan testini yecha olmasligini tekshirish
    if test.creator.telegram_id == user.id:
        await update.message.reply_text(
            "❌ O'zingiz yaratgan testni yecha olmaysiz!",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # Avval yechganligini tekshirish
    existing = TestSubmission.select().where(
        (TestSubmission.test == test) &
        (TestSubmission.user == db_user)
    ).first()

    if existing:
        await update.message.reply_html(
            f"⚠️ Siz bu testni avval yechgansiz!\n\n"
            f"Natijangiz: {existing.correct_count}/{existing.total_count} ({existing.percentage}%)",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # Contextga test ma'lumotini saqlash
    context.user_data['current_test'] = test
    context.user_data['db_user'] = db_user

    await update.message.reply_html(
        f"📝 <b>Test: {code}</b>\n\n"
        f"❓ Savollar soni: {test.total_questions} ta\n\n"
        f"Javoblaringizni kiriting.\n"
        f"Masalan: <code>{'a' * min(test.total_questions, 10)}</code>\n\n"
        f"❌ Bekor qilish: /cancel"
    )

    return WAITING_USER_ANSWERS


async def receive_user_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi javoblarini qabul qilish"""
    test = context.user_data.get('current_test')
    db_user = context.user_data.get('db_user')

    if not test or not db_user:
        await update.message.reply_text(
            "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # Test hali ham faol ekanligini tekshirish
    test = Test.get_by_id(test.id)
    if not test.is_active:
        await update.message.reply_text(
            "❌ Bu test yakunlangan!",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    if not update.message or not update.message.text:
        await update.message.reply_text("❌ Faqat matn yuboring!")
        return WAITING_USER_ANSWERS

    answers = update.message.text.strip().lower()

    # Validatsiya
    if not answers.isalpha():
        await update.message.reply_html(
            "❌ Javoblar faqat harflardan iborat bo'lishi kerak!\n"
            "Masalan: <code>abbacabbac</code>"
        )
        return WAITING_USER_ANSWERS

    # Javoblar sonini tekshirish
    if len(answers) != test.total_questions:
        await update.message.reply_html(
            f"❌ Javoblar soni to'g'ri kelmadi!\n"
            f"Kutilgan: {test.total_questions} ta\n"
            f"Kiritilgan: {len(answers)} ta"
        )
        return WAITING_USER_ANSWERS

    # Javoblarni tekshirish
    correct_count, total, results = check_answers(test.correct_answers, answers)

    # Natijani saqlash
    submission = TestSubmission.create(
        test=test,
        user=db_user,
        answers=answers,
        correct_count=correct_count,
        total_count=total
    )

    # Natijani formatlash va yuborish
    result_text = format_result(correct_count, total, results)
    await update.message.reply_html(result_text, reply_markup=main_menu_keyboard())

    # Test egasiga xabar yuborish (faqat boshqa odam yechganda)
    if test.creator.telegram_id != db_user.telegram_id:
        try:
            creator = test.creator
            await context.bot.send_message(
                chat_id=creator.telegram_id,
                text=f"📢 <b>Yangi natija!</b>\n\n"
                     f"📝 Test: <code>{test.unique_code}</code>\n"
                     f"👤 Foydalanuvchi: {db_user.full_name or db_user.username}\n"
                     f"✅ Natija: {correct_count}/{total} ({submission.percentage}%)",
                parse_mode="HTML"
            )
        except Exception:
            pass

    # Context tozalash
    context.user_data.pop('current_test', None)
    context.user_data.pop('db_user', None)

    return ConversationHandler.END


async def cancel_solve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testni yechishni bekor qilish"""
    context.user_data.pop('current_test', None)
    context.user_data.pop('db_user', None)
    await update.message.reply_text(
        "❌ Test yechish bekor qilindi.",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


def get_handlers():
    """Handlerlarni qaytarish"""
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("solve", solve_command, filters=filters.ChatType.PRIVATE),
            MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r'^✍️ Test yechish$'), solve_command),
        ],
        states={
            WAITING_TEST_CODE: [
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^(📝 Test yaratish|✍️ Test yechish|📋 Mening testlarim|📊 Mening statistikam)$'), receive_test_code)
            ],
            WAITING_USER_ANSWERS: [
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^(📝 Test yaratish|✍️ Test yechish|📋 Mening testlarim|📊 Mening statistikam)$'), receive_user_answers)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_solve)],
    )

    return [conv_handler]


"""Test boshqarish handlerlari"""
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from database import get_or_create_user, Test, TestSubmission, User
from utils import get_question_stats, format_stats, format_stats_simple
from export import export_to_excel, export_to_pdf, export_chart
from config import ADMIN_ID
from keyboards import (
    main_menu_keyboard, my_tests_keyboard, test_detail_keyboard,
    test_active_stats_keyboard, confirm_end_keyboard, back_to_test_keyboard
)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test statistikasini ko'rsatish (command)"""
    if not context.args:
        await update.message.reply_html(
            "❌ Test kodini kiriting!\n"
            "Masalan: <code>/stats ABC123</code>"
        )
        return

    code = context.args[0].upper()
    user = update.effective_user
    await show_stats(update.message, context, code, user.id)


async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test statistikasini ko'rsatish (callback)"""
    query = update.callback_query
    await query.answer()

    code = query.data.replace("stats_", "")
    user = update.effective_user
    await show_stats(query.message, context, code, user.id, edit=True)


async def show_stats(message, context, code: str, user_id: int, edit: bool = False):
    """Statistikani ko'rsatish"""
    # Testni topish
    try:
        test = Test.get(Test.unique_code == code)
    except Test.DoesNotExist:
        text = f"❌ '{code}' kodli test topilmadi!"
        if edit:
            await message.edit_text(text)
        else:
            await message.reply_text(text)
        return

    # Faqat test egasi yoki admin ko'ra oladi
    if test.creator.telegram_id != user_id and user_id != ADMIN_ID:
        text = "❌ Siz bu testning statistikasini ko'ra olmaysiz!"
        if edit:
            await message.edit_text(text)
        else:
            await message.reply_text(text)
        return

    # Test hali faol bo'lsa, faqat ishtirokchilar sonini ko'rsatish
    if test.is_active:
        subs_count = TestSubmission.select().where(TestSubmission.test == test).count()
        text = (
            f"📊 <b>Test statistikasi</b>\n\n"
            f"📝 Kod: <code>{test.unique_code}</code>\n"
            f"❓ Savollar soni: {test.total_questions} ta\n"
            f"👥 Ishtirokchilar: {subs_count} ta\n\n"
            f"🟢 Test faol\n\n"
            f"⚠️ To'liq statistika test yakunlangandan keyin ko'rsatiladi."
        )
        keyboard = test_active_stats_keyboard(code)
    else:
        # Test yakunlangan - to'liq statistikani ko'rsatish
        stats = get_question_stats(test)
        text = format_stats(stats, test)
        text += f"\n\n🔴 Test yakunlangan"
        keyboard = back_to_test_keyboard(code)

    if edit:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass
    else:
        await message.reply_html(text, reply_markup=keyboard)


async def end_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testni yakunlash (command)"""
    if not context.args:
        await update.message.reply_html(
            "❌ Test kodini kiriting!\n"
            "Masalan: <code>/end ABC123</code>"
        )
        return

    code = context.args[0].upper()
    user = update.effective_user
    await show_end_confirmation(update.message, context, code, user.id)


async def end_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testni yakunlash so'rovi (callback)"""
    query = update.callback_query
    await query.answer()

    code = query.data.replace("end_", "")
    user = update.effective_user
    await show_end_confirmation(query.message, context, code, user.id, edit=True)


async def show_end_confirmation(message, context, code: str, user_id: int, edit: bool = False):
    """Yakunlash tasdig'ini ko'rsatish"""
    try:
        test = Test.get(Test.unique_code == code)
    except Test.DoesNotExist:
        text = f"❌ '{code}' kodli test topilmadi!"
        if edit:
            await message.edit_text(text)
        else:
            await message.reply_text(text)
        return

    if test.creator.telegram_id != user_id and user_id != ADMIN_ID:
        text = "❌ Siz bu testni yakunlay olmaysiz!"
        if edit:
            await message.edit_text(text)
        else:
            await message.reply_text(text)
        return

    if not test.is_active:
        text = "❌ Bu test allaqachon yakunlangan!"
        if edit:
            await message.edit_text(text)
        else:
            await message.reply_text(text)
        return

    subs_count = TestSubmission.select().where(TestSubmission.test == test).count()
    mode_text = "📐 Rasch" if test.scoring_mode == "rasch" else "📊 Oddiy"
    text = (
        f"⚠️ <b>Testni yakunlashni tasdiqlang</b>\n\n"
        f"📝 Kod: <code>{code}</code>\n"
        f"👥 Ishtirokchilar: {subs_count} ta\n"
        f"📐 Baholash: {mode_text}\n\n"
        f"Yakunlangandan keyin hech kim bu testni yecha olmaydi."
    )

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=confirm_end_keyboard(code))
    else:
        await message.reply_html(text, reply_markup=confirm_end_keyboard(code))


async def confirm_end_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yakunlashni tasdiqlash"""
    query = update.callback_query
    await query.answer()

    code = query.data.replace("confirm_end_", "")
    user = update.effective_user

    try:
        test = Test.get(Test.unique_code == code)
    except Test.DoesNotExist:
        await query.message.edit_text(f"❌ '{code}' kodli test topilmadi!")
        return

    if test.creator.telegram_id != user.id and user.id != ADMIN_ID:
        await query.message.edit_text("❌ Siz bu testni yakunlay olmaysiz!")
        return

    if not test.is_active:
        await query.message.edit_text("❌ Bu test allaqachon yakunlangan!")
        return

    # Testni yakunlash
    test.is_active = False
    test.ended_at = datetime.now()
    test.save()

    # Yakuniy statistikani olish
    stats = get_question_stats(test)
    text = f"🔚 <b>Test yakunlandi!</b>\n\n"

    # Saqlangan baholash turini ishlatish
    if test.scoring_mode == 'rasch':
        text += format_stats(stats, test)
    else:
        text += format_stats_simple(stats, test)

    await query.message.edit_text(text, parse_mode="HTML")

    # Adminga xabar yuborish
    if ADMIN_ID and user.id != ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📢 <b>Test yakunlandi!</b>\n\n"
                     f"📝 Kod: <code>{code}</code>\n"
                     f"👤 Yaratuvchi: {test.creator.full_name}\n"
                     f"👥 Ishtirokchilar: {stats['total_submissions']} ta",
                parse_mode="HTML"
            )
        except Exception:
            pass


async def mytests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchining testlari"""
    user = update.effective_user

    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    tests = list(Test.select().where(Test.creator == db_user).order_by(Test.created_at.desc()))

    if not tests:
        await update.message.reply_text(
            "📭 Siz hali test yaratmagansiz.\n\n"
            "\"📝 Test yaratish\" tugmasini bosing.",
            reply_markup=main_menu_keyboard()
        )
        return

    text = f"📋 <b>Sizning testlaringiz</b>\n\n"
    text += "Batafsil ko'rish uchun tanlang:"

    await update.message.reply_html(text, reply_markup=my_tests_keyboard(tests))


async def mytests_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mening testlarim callback"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    tests = list(Test.select().where(Test.creator == db_user).order_by(Test.created_at.desc()))

    if not tests:
        await query.message.edit_text("📭 Siz hali test yaratmagansiz.")
        return

    text = f"📋 <b>Sizning testlaringiz</b>\n\nBatafsil ko'rish uchun tanlang:"
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=my_tests_keyboard(tests))


async def test_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test tafsilotlari"""
    query = update.callback_query
    await query.answer()

    code = query.data.replace("test_", "")
    user = update.effective_user

    try:
        test = Test.get(Test.unique_code == code)
    except Test.DoesNotExist:
        await query.message.edit_text(f"❌ '{code}' kodli test topilmadi!")
        return

    if test.creator.telegram_id != user.id and user.id != ADMIN_ID:
        await query.message.edit_text("❌ Bu sizning testingiz emas!")
        return

    subs_count = TestSubmission.select().where(TestSubmission.test == test).count()
    status = "🟢 Faol" if test.is_active else "🔴 Yakunlangan"

    text = (
        f"📝 <b>Test: {code}</b>\n\n"
        f"❓ Savollar: {test.total_questions} ta\n"
        f"👥 Ishtirokchilar: {subs_count} ta\n"
        f"📊 Holat: {status}\n"
        f"📅 Yaratilgan: {test.created_at.strftime('%d.%m.%Y %H:%M')}"
    )

    await query.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=test_detail_keyboard(code, test.is_active)
    )


async def mystats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchining shaxsiy statistikasi"""
    user = update.effective_user

    db_user = get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name or user.first_name
    )

    submissions = list(TestSubmission.select().where(TestSubmission.user == db_user))

    if not submissions:
        await update.message.reply_text(
            "📭 Siz hali test yechmadingiz.\n\n"
            "\"✍️ Test yechish\" tugmasini bosing.",
            reply_markup=main_menu_keyboard()
        )
        return

    total_tests = len(submissions)
    total_correct = sum(s.correct_count for s in submissions)
    total_questions = sum(s.total_count for s in submissions)
    avg_percentage = round((total_correct / total_questions) * 100, 1) if total_questions > 0 else 0

    text = f"📊 <b>Sizning statistikangiz</b>\n\n"
    text += f"📝 Yechilgan testlar: {total_tests} ta\n"
    text += f"✅ To'g'ri javoblar: {total_correct}/{total_questions}\n"
    text += f"📈 O'rtacha natija: {avg_percentage}%\n\n"

    text += "<b>So'nggi natijalar:</b>\n"
    for sub in sorted(submissions, key=lambda s: s.submitted_at, reverse=True)[:5]:
        text += f"  • <code>{sub.test.unique_code}</code>: {sub.correct_count}/{sub.total_count} ({sub.percentage}%)\n"

    await update.message.reply_html(text, reply_markup=main_menu_keyboard())


async def export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Natijalarni faylga eksport qilish"""
    query = update.callback_query
    await query.answer("📥 Fayl tayyorlanmoqda...")

    # export_excel_CODE yoki export_pdf_CODE
    parts = query.data.split("_", 2)  # ['export', 'excel/pdf', 'CODE']
    fmt = parts[1]  # 'excel' yoki 'pdf'
    code = parts[2]
    user = update.effective_user

    try:
        test = Test.get(Test.unique_code == code)
    except Test.DoesNotExist:
        await query.message.reply_text(f"❌ '{code}' kodli test topilmadi!")
        return

    if test.creator.telegram_id != user.id and user.id != ADMIN_ID:
        await query.message.reply_text("❌ Siz bu testning natijalarini yuklab ololmaysiz!")
        return

    # Statistikani olish
    stats = get_question_stats(test)
    if stats['total_submissions'] == 0:
        await query.message.reply_text("📭 Hali hech kim test yechmagan.")
        return

    try:
        import os
        if fmt == 'excel':
            filepath = export_to_excel(stats, test)
            await query.message.reply_document(
                document=open(filepath, 'rb'),
                filename=f"test_{code}.xlsx",
                caption=f"📊 Test {code} natijalari (Excel)"
            )
        elif fmt == 'pdf':
            filepath = export_to_pdf(stats, test)
            await query.message.reply_document(
                document=open(filepath, 'rb'),
                filename=f"test_{code}.pdf",
                caption=f"📊 Test {code} natijalari (PDF)"
            )
        elif fmt == 'chart':
            filepath = export_chart(stats, test)
            await query.message.reply_photo(
                photo=open(filepath, 'rb'),
                caption=f"📊 Test {code} — Tahlil grafigi"
            )
        # Vaqtinchalik faylni o'chirish
        os.remove(filepath)
    except Exception as e:
        await query.message.reply_text(f"❌ Fayl yaratishda xatolik: {str(e)}")


def get_handlers():
    """Handlerlarni qaytarish"""
    return [
        CommandHandler("stats", stats_command),
        CommandHandler("end", end_command),
        CommandHandler("mytests", mytests_command),
        CommandHandler("mystats", mystats_command),
        # Callback handlers
        CallbackQueryHandler(stats_callback, pattern=r"^stats_"),
        CallbackQueryHandler(end_callback, pattern=r"^end_(?!confirm)"),
        CallbackQueryHandler(confirm_end_callback, pattern=r"^confirm_end_"),
        CallbackQueryHandler(export_callback, pattern=r"^export_(excel|pdf|chart)_"),
        CallbackQueryHandler(mytests_callback, pattern=r"^mytests$"),
        CallbackQueryHandler(test_detail_callback, pattern=r"^test_"),
    ]

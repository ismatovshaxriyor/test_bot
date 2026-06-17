"""Test yechish handleri"""
import logging
from html import escape

from telegram import Update
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)

from peewee import IntegrityError

from database import get_or_create_user, Test, TestSubmission, AdminTestWatch, Question
from utils import check_answers, parse_simple_answers, latex_to_text
from config import ADMIN_ID
from keyboards import main_menu_keyboard
from membership import membership_required
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from config import WEBAPP_URL, WEBAPP_VERSION
import json

logger = logging.getLogger(__name__)

WAITING_TEST_CODE = 0
WAITING_USER_ANSWERS = 1
CHAT_SOLVING = 2

CHAT_SOLVE_BTN = "💬 Chatda yechish"


async def _notify_result(context, test, db_user, correct_count, total, percentage):
    """Test egasiga va kuzatuvchi adminlarga yangi natija haqida xabar."""
    if test.creator.telegram_id != db_user.telegram_id:
        try:
            await context.bot.send_message(
                chat_id=test.creator.telegram_id,
                text=f"📢 <b>Yangi natija!</b>\n\n"
                     f"📝 Test: <code>{test.id}</code>\n"
                     f"👤 Foydalanuvchi: {db_user.full_name or db_user.username}\n"
                     f"✅ Natija: {correct_count}/{total} ({percentage}%)",
                parse_mode="HTML",
            )
        except Exception:
            pass

    skip_ids = {db_user.telegram_id, test.creator.telegram_id}
    for watch in AdminTestWatch.select().where(AdminTestWatch.test == test):
        try:
            watcher_tg_id = watch.admin.telegram_id
            if watcher_tg_id in skip_ids:
                continue
            await context.bot.send_message(
                chat_id=watcher_tg_id,
                text=f"🔔 <b>Kuzatuv: Yangi natija!</b>\n\n"
                     f"📝 Test: <code>{test.id}</code>\n"
                     f"👤 Foydalanuvchi: {db_user.full_name or db_user.username}\n"
                     f"✅ Natija: {correct_count}/{total} ({percentage}%)",
                parse_mode="HTML",
            )
        except Exception:
            pass


@membership_required
async def solve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testni yechishni boshlash"""
    # Argumentdan kodni olish
    if not context.args:
        await update.message.reply_html(
            "✍️ <b>Test yechish</b>\n\n"
            "Hozir siz oddiy test yechish holatidasiz.\n\n"
            "Test egasi sizga yuborgan <b>test raqamini (ID)</b> kiriting:\n\n"
            "💡 Kod faqat raqamlardan iborat\n"
            "(masalan: <code>15</code> yoki <code>42</code>)\n\n"
            "❌ Bekor qilish: /cancel yoki Ortga"
        )
        return WAITING_TEST_CODE

    code = context.args[0].upper()
    return await process_test_code(update, context, code)


@membership_required
async def receive_test_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test kodini qabul qilish"""
    code = update.message.text.strip().upper()
    if code == "ORTGA":
        return await cancel_solve(update, context)
        
    return await process_test_code(update, context, code)


async def process_test_code(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    """Test kodini qayta ishlash"""
    if not code.isdigit():
        await update.message.reply_text("❌ Kod faqat raqamlardan iborat bo'lishi kerak!")
        return WAITING_TEST_CODE

    # Testni topish
    try:
        test = Test.get_by_id(int(code))
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
            reply_markup=main_menu_keyboard(update.effective_user.id)
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
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    # Avval yechganligini tekshirish
    existing = TestSubmission.select().where(
        (TestSubmission.test == test) &
        (TestSubmission.user == db_user)
    ).first()

    if existing:
        await update.message.reply_text(
            "⚠️ Siz bu testni allaqachon ishlagansiz!",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    # Contextga test ma'lumotini saqlash
    context.user_data['current_test'] = test
    context.user_data['db_user'] = db_user

    # Solve url
    solve_path = "/solve_rasch" if test.scoring_mode == "rasch" else "/solve"

    # Aralash/Rash testlarda ochiq savollar bor — matn bilan yechib bo'lmaydi
    is_mixed = bool(test.correct_answers) and test.correct_answers.startswith("[{")
    # Boy savol mazmuni (Question qatorlari) bo'lsa — chatda birma-bir yechish mumkin
    has_questions = Question.select().where(Question.test == test).exists()

    kb_rows = [[KeyboardButton("🚀 Interaktiv yechish", web_app=WebAppInfo(url=f"{WEBAPP_URL}{solve_path}?test_id={test.id}&v={WEBAPP_VERSION}"))]]
    if has_questions:
        kb_rows.append([KeyboardButton(CHAT_SOLVE_BTN)])
    kb_rows.append([KeyboardButton("Ortga")])
    keyboard = ReplyKeyboardMarkup(kb_rows, resize_keyboard=True)

    if is_mixed and has_questions:
        await update.message.reply_html(
            f"📝 <b>Test: {code}</b>\n\n"
            f"❓ Savollar soni: {test.total_questions} ta\n\n"
            f"Ikki usuldan birini tanlang:\n"
            f"• <b>🚀 Interaktiv yechish</b> — WebApp (formulalar chiroyli ko'rinadi)\n"
            f"• <b>{CHAT_SOLVE_BTN}</b> — savollar shu chatda birma-bir ko'rsatiladi\n\n"
            f"❌ Bekor qilish: /cancel yoki Ortga",
            reply_markup=keyboard
        )
    elif is_mixed:
        await update.message.reply_html(
            f"📝 <b>Test: {code}</b>\n\n"
            f"❓ Savollar soni: {test.total_questions} ta\n\n"
            f"⚠️ Bu testda ochiq savollar bor — uni faqat WebApp orqali yechish mumkin.\n"
            f"Pastdagi <b>🚀 Interaktiv yechish</b> tugmasini bosing.\n\n"
            f"❌ Bekor qilish: /cancel yoki Ortga",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_html(
            f"📝 <b>Test: {code}</b>\n\n"
            f"❓ Savollar soni: {test.total_questions} ta\n\n"
            f"Javoblaringizni ikki usuldan birida kiriting:\n"
            f"1️⃣ Klassik: <code>{('abcd' * (test.total_questions // 4 + 1))[:test.total_questions]}</code>\n"
            f"2️⃣ Raqamli: <code>1a 2b 3c 4d</code> yoki <code>1a2b3c4d</code>\n\n"
            f"Yoki pastdagi maxsus tugma orqali WebApp da ishlashingiz mumkin\n\n"
            f"❌ Bekor qilish: /cancel yoki Ortga",
            reply_markup=keyboard
        )

    return WAITING_USER_ANSWERS


@membership_required
async def receive_user_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi javoblarini qabul qilish"""
    test = context.user_data.get('current_test')
    db_user = context.user_data.get('db_user')

    if not test or not db_user:
        await update.message.reply_text(
            "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    # Test hali ham faol ekanligini tekshirish
    test = Test.get_by_id(test.id)
    if not test.is_active:
        await update.message.reply_text(
            "❌ Bu test yakunlangan!",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    # "Chatda yechish" tugmasi bosildi — interaktiv yechishni boshlash
    if (update.message.text or "").strip() == CHAT_SOLVE_BTN:
        return await start_chat_solving(update, context)

    if test.correct_answers and test.correct_answers.startswith("[{"):
        await update.message.reply_html(
            "⚠️ <b>Ushbu testni faqat matn yozib yechib bo'lmaydi!</b>\n"
            "Testda ochiq savollar bor. Iltimos, pastdagi <b>🚀 Interaktiv yechish</b> tugmasidan foydalaning!"
        )
        return WAITING_USER_ANSWERS

    if not update.message or not update.message.text:
        await update.message.reply_text("❌ Faqat matn yuboring!")
        return WAITING_USER_ANSWERS

    answers = update.message.text.strip()

    if answers.lower() == "ortga":
        return await cancel_solve(update, context)

    # Ikkala formatni qabul qiluvchi parse
    answers, error = parse_simple_answers(answers)
    if error:
        await update.message.reply_html(error)
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

    # Natijani saqlash (unique indeks poyga holatidagi takroriy topshirishni bloklaydi)
    try:
        submission = TestSubmission.create(
            test=test,
            user=db_user,
            answers=answers,
            correct_count=correct_count,
            total_count=total
        )
    except IntegrityError:
        await update.message.reply_text(
            "⚠️ Siz bu testni allaqachon ishlagansiz!",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        context.user_data.pop('current_test', None)
        context.user_data.pop('db_user', None)
        return ConversationHandler.END

    # Foydalanuvchiga qabul qilinganini yuborish (yakuniy natija test yakunlangach yuboriladi)
    await update.message.reply_html(
        "✅ <b>Javobingiz qabul qilindi.</b>\n\n"
        "📌 Natija test yakunlangach yuboriladi.",
        reply_markup=main_menu_keyboard(update.effective_user.id)
    )

    await _notify_result(context, test, db_user, correct_count, total, submission.percentage)

    # Context tozalash
    context.user_data.pop('current_test', None)
    context.user_data.pop('db_user', None)

    return ConversationHandler.END


# ─────────────────────── Chatda interaktiv yechish ───────────────────────

def _clear_chat_solving(context: ContextTypes.DEFAULT_TYPE):
    for key in ("cs_qlist", "cs_answers", "cs_idx", "current_test", "db_user"):
        context.user_data.pop(key, None)


async def start_chat_solving(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Boy testni chatda birma-bir yechishni boshlash."""
    test = context.user_data.get("current_test")
    db_user = context.user_data.get("db_user")
    if not test or not db_user:
        await update.message.reply_text("❌ Xatolik. Qaytadan urinib ko'ring.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    rows = list(Question.select().where(Question.test == test).order_by(Question.num))
    if not rows:
        await update.message.reply_text(
            "Bu testda chatda ko'rsatish uchun mazmun yo'q. WebApp'dan foydalaning."
        )
        return WAITING_USER_ANSWERS

    qlist = []
    for q in rows:
        opts = None
        if q.options:
            try:
                opts = json.loads(q.options)
            except (TypeError, ValueError, json.JSONDecodeError):
                opts = None
        qlist.append({
            "num": q.num, "type": q.type, "text": q.text or "",
            "options": opts, "image_file_id": q.image_file_id,
        })

    context.user_data["cs_qlist"] = qlist
    context.user_data["cs_answers"] = [None] * len(qlist)
    context.user_data["cs_idx"] = 0

    await update.message.reply_text(
        f"💬 <b>Chatda yechish</b> — {len(qlist)} ta savol.\n"
        f"Har savolga javob bering. Bekor qilish: /cancel",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await _show_chat_question(context, update.effective_chat.id)
    return CHAT_SOLVING


def _chat_letters(q: dict) -> list:
    if q.get("type") == "closed6":
        return ["a", "b", "c", "d", "e", "f"]
    return ["a", "b", "c", "d"]


async def _show_chat_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    qlist = context.user_data["cs_qlist"]
    idx = context.user_data["cs_idx"]
    q = qlist[idx]

    # Rasm (agar bor) — bot file_id orqali to'g'ridan-to'g'ri yuboradi
    if q.get("image_file_id"):
        try:
            await context.bot.send_photo(chat_id, photo=q["image_file_id"])
        except Exception:
            pass

    header = f"<b>Savol {idx + 1}/{len(qlist)}</b>"
    body = escape(latex_to_text(q.get("text") or ""))
    text = f"{header}\n\n{body}" if body else header

    if q["type"] in ("closed", "closed6"):
        letters = _chat_letters(q)
        opts = q.get("options") or {}
        opt_lines = [f"{l.upper()}) {escape(latex_to_text(str(opts.get(l, ''))))}" for l in letters]
        if any(opts.get(l) for l in letters):
            text += "\n\n" + "\n".join(opt_lines)
        buttons = [InlineKeyboardButton(l.upper(), callback_data=f"csolve_{idx}_{l}") for l in letters]
        rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
        await context.bot.send_message(chat_id, text, parse_mode="HTML",
                                       reply_markup=InlineKeyboardMarkup(rows))
    else:
        text += "\n\n💬 Javobni matn ko'rinishida yuboring."
        await context.bot.send_message(chat_id, text, parse_mode="HTML")


async def _advance_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cs_idx"] += 1
    qlist = context.user_data["cs_qlist"]
    if context.user_data["cs_idx"] < len(qlist):
        await _show_chat_question(context, update.effective_chat.id)
        return CHAT_SOLVING
    return await _submit_chat(update, context)


async def chat_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yopiq savol javobi (inline harf) chatda tanlandi."""
    query = update.callback_query
    parts = query.data.split("_")  # csolve_<idx>_<letter>
    if len(parts) != 3 or not parts[1].isdigit():
        await query.answer("Xato", show_alert=True)
        return CHAT_SOLVING
    idx, letter = int(parts[1]), parts[2]

    qlist = context.user_data.get("cs_qlist")
    cur = context.user_data.get("cs_idx")
    answers = context.user_data.get("cs_answers")
    if qlist is None or cur is None:
        await query.answer("Sessiya tugadi", show_alert=True)
        return ConversationHandler.END
    if idx != cur:
        await query.answer("Bu savol o'tib ketgan")
        return CHAT_SOLVING

    q = qlist[idx]
    if q["type"] not in ("closed", "closed6"):
        await query.answer("Bu savolga matn yuboring", show_alert=True)
        return CHAT_SOLVING
    if letter not in _chat_letters(q):
        await query.answer("Noto'g'ri variant", show_alert=True)
        return CHAT_SOLVING

    answers[idx] = letter
    await query.answer(f"{letter.upper()} ✓")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    return await _advance_chat(update, context)


async def chat_answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ochiq savol javobi chatda matn ko'rinishida kiritildi."""
    text = (update.message.text or "").strip()
    if text.lower() in ("ortga", "❌ bekor qilish"):
        return await cancel_solve(update, context)

    qlist = context.user_data.get("cs_qlist")
    cur = context.user_data.get("cs_idx")
    answers = context.user_data.get("cs_answers")
    if qlist is None or cur is None:
        await update.message.reply_text("❌ Sessiya tugadi.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    q = qlist[cur]
    if q["type"] in ("closed", "closed6"):
        await update.message.reply_text("Bu savol uchun yuqoridagi tugmalardan birini tanlang.")
        return CHAT_SOLVING
    if not text:
        await update.message.reply_text("Javob bo'sh bo'lmasin.")
        return CHAT_SOLVING

    answers[cur] = text
    return await _advance_chat(update, context)


async def _submit_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chatda yig'ilgan javoblarni saqlash va baholash."""
    test = context.user_data.get("current_test")
    db_user = context.user_data.get("db_user")
    qlist = context.user_data.get("cs_qlist")
    answers = context.user_data.get("cs_answers")
    chat_id = update.effective_chat.id

    if not test or not db_user or qlist is None:
        _clear_chat_solving(context)
        await context.bot.send_message(chat_id, "❌ Sessiya tugadi.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    test = Test.get_by_id(test.id)
    if not test.is_active:
        _clear_chat_solving(context)
        await context.bot.send_message(chat_id, "❌ Bu test yakunlangan!", reply_markup=main_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    submitted = json.dumps(
        [{"num": qlist[i]["num"], "type": qlist[i]["type"], "answer": (answers[i] or "")}
         for i in range(len(qlist))],
        ensure_ascii=False,
    )
    correct_count, total, _ = check_answers(test.correct_answers, submitted)

    try:
        submission = TestSubmission.create(
            test=test, user=db_user, answers=submitted,
            correct_count=correct_count, total_count=total,
        )
    except IntegrityError:
        _clear_chat_solving(context)
        await context.bot.send_message(chat_id, "⚠️ Siz bu testni allaqachon ishlagansiz!",
                                       reply_markup=main_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    await context.bot.send_message(
        chat_id,
        "✅ <b>Javobingiz qabul qilindi.</b>\n\n📌 Natija test yakunlangach yuboriladi.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(update.effective_user.id),
    )
    await _notify_result(context, test, db_user, correct_count, total, submission.percentage)
    _clear_chat_solving(context)
    return ConversationHandler.END


async def cancel_solve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testni yechishni bekor qilish"""
    _clear_chat_solving(context)
    await update.message.reply_text(
        "❌ Test yechish bekor qilindi.",
        reply_markup=main_menu_keyboard(update.effective_user.id)
    )
    return ConversationHandler.END


@membership_required
async def webapp_receive_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WebApp orqali kelgan barcha amallarni qabul qilish (router)"""
    try:
        if not update.message or not update.message.web_app_data:
            logger.warning("WEBAPP DATA: message/web_app_data missing")
            return ConversationHandler.END

        data = json.loads(update.message.web_app_data.data)
        action = data.get("action")
        logger.info("WEBAPP DATA RECEIVED: action=%s user_id=%s", action, update.effective_user.id if update.effective_user else None)
        
        if action == "create_test":
            # Test yaratish — alohida handler ga yo'naltirish
            from handlers.test_create import webapp_create_handler
            return await webapp_create_handler(update, context)

        if action == "rich_test_created":
            # Qo'lda to'liq test API orqali yaratildi — rasm biriktirishni boshlash
            # (fallback: foydalanuvchi AI suhbatida bo'lmasa shu yerda ushlanadi)
            from handlers.test_ai_create import handle_rich_test_created
            test_id = data.get("test_id")
            if str(test_id).isdigit():
                await handle_rich_test_created(update, context, int(test_id))
            return ConversationHandler.END

        if action != "submit_test":
            return ConversationHandler.END
            
        test_id = data.get("test_id")
        answers = data.get("answers", "")

        if not str(test_id).isdigit():
            await update.message.reply_text("❌ Test kodi noto'g'ri formatda!", reply_markup=main_menu_keyboard(update.effective_user.id))
            return ConversationHandler.END

        if not isinstance(answers, str):
            answers = str(answers or "")
        
        # User auth details
        telegram_id = update.effective_user.id
        db_user = get_or_create_user(
            telegram_id=telegram_id,
            username=update.effective_user.username,
            full_name=update.effective_user.full_name
        )
        
        try:
            test = Test.get_by_id(int(test_id))
        except Test.DoesNotExist:
            await update.message.reply_text("❌ Kutilmagan xatolik: Test topilmadi.", reply_markup=main_menu_keyboard(update.effective_user.id))
            return ConversationHandler.END
            
        if not test.is_active:
            await update.message.reply_text("❌ Uzr, bu test allaqachon yakunlangan!", reply_markup=main_menu_keyboard(update.effective_user.id))
            return ConversationHandler.END

        if test.creator.telegram_id == telegram_id:
            await update.message.reply_text("❌ O'zingiz yaratgan testni yecha olmaysiz!", reply_markup=main_menu_keyboard(update.effective_user.id))
            return ConversationHandler.END
            
        existing = TestSubmission.select().where(
            (TestSubmission.test == test) & 
            (TestSubmission.user == db_user)
        ).first()
        
        if existing:
            await update.message.reply_text(
                "⚠️ Siz bu testni allaqachon ishlagansiz!",
                reply_markup=main_menu_keyboard(update.effective_user.id)
            )
            return ConversationHandler.END
            
        # check
        is_mixed = test.correct_answers and test.correct_answers.startswith("[{")
        safe_answers = answers.strip()
        if not is_mixed:
            safe_answers = safe_answers.lower()

        correct_count, total, _ = check_answers(test.correct_answers, safe_answers)

        # Unique indeks poyga holatidagi takroriy topshirishni bazaviy darajada bloklaydi
        try:
            submission = TestSubmission.create(
                test=test,
                user=db_user,
                answers=safe_answers,
                correct_count=correct_count,
                total_count=total
            )
        except IntegrityError:
            await update.message.reply_text(
                "⚠️ Siz bu testni allaqachon ishlagansiz!",
                reply_markup=main_menu_keyboard(update.effective_user.id)
            )
            return ConversationHandler.END

        # Foydalanuvchiga qabul qilinganini yuborish (yakuniy natija test yakunlangach yuboriladi)
        await update.message.reply_html(
            "✅ <b>Javobingiz qabul qilindi.</b>\n\n"
            "📌 Natija test yakunlangach yuboriladi.",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )

        # Test egasiga xabar yuborish
        if test.creator.telegram_id != db_user.telegram_id:
            try:
                creator = test.creator
                await context.bot.send_message(
                    chat_id=creator.telegram_id,
                    text=f"📢 <b>Yangi natija!</b>\n\n"
                     f"📝 Test: <code>{test.id}</code>\n"
                     f"👤 Foydalanuvchi: {db_user.full_name or db_user.username}\n"
                     f"✅ Natija: {correct_count}/{total} ({submission.percentage}%)",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # Kuzatayotgan adminlarga bildirishnoma
        skip_ids = {db_user.telegram_id, test.creator.telegram_id}
        for watch in AdminTestWatch.select().where(AdminTestWatch.test == test):
            try:
                watcher_tg_id = watch.admin.telegram_id
                if watcher_tg_id in skip_ids:
                    continue
                await context.bot.send_message(
                    chat_id=watcher_tg_id,
                    text=f"🔔 <b>Kuzatuv: Yangi natija!</b>\n\n"
                         f"📝 Test: <code>{test.id}</code>\n"
                         f"👤 Foydalanuvchi: {db_user.full_name or db_user.username}\n"
                         f"✅ Natija: {correct_count}/{total} ({submission.percentage}%)",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    except json.JSONDecodeError:
        logger.exception("WEBAPP DATA: JSONDecodeError")
        return ConversationHandler.END
    except Exception as e:
        logger.exception("WEBAPP DATA: unexpected error: %s", e)
        await update.message.reply_text(f"Xatolik: {e}", reply_markup=main_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    # Context tozalash
    context.user_data.pop('current_test', None)
    context.user_data.pop('db_user', None)
    return ConversationHandler.END


def get_handlers():
    """Bot ichida yechish + WebApp data handlerlari"""
    conversation_handler = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & filters.Regex(r"^(✍️ Test yechish|✍️ Oddiy test yechish)$"),
                solve_command
            ),
        ],
        states={
            WAITING_TEST_CODE: [
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    receive_test_code
                ),
                MessageHandler(
                    filters.StatusUpdate.WEB_APP_DATA,
                    webapp_receive_data
                )
            ],
            WAITING_USER_ANSWERS: [
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    receive_user_answers
                ),
                MessageHandler(
                    filters.StatusUpdate.WEB_APP_DATA,
                    webapp_receive_data
                )
            ],
            CHAT_SOLVING: [
                CallbackQueryHandler(chat_answer_callback, pattern=r"^csolve_\d+_[a-f]$"),
                MessageHandler(
                    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                    chat_answer_text
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_solve, filters=filters.ChatType.PRIVATE),
        ],
        allow_reentry=True,
    )

    return [conversation_handler]

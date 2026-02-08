"""Membership tekshirish decorator va yordamchi funksiyalar"""
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from database import Channel


async def check_user_membership(bot, user_id: int) -> tuple[bool, list]:
    """
    Foydalanuvchi barcha kanallarga a'zo ekanligini tekshirish

    Returns:
        (all_joined: bool, not_joined_channels: list)
    """
    channels = list(Channel.select().where(Channel.is_active == True))

    if not channels:
        return True, []

    not_joined = []

    for channel in channels:
        try:
            member = await bot.get_chat_member(
                chat_id=channel.channel_id,
                user_id=user_id
            )
            # left, kicked yoki restricted bo'lsa - a'zo emas
            if member.status in ['left', 'kicked']:
                not_joined.append(channel)
        except TelegramError:
            # Xatolik bo'lsa (bot admin emas va h.k.) - o'tkazib yuborish
            pass

    return len(not_joined) == 0, not_joined


def get_join_keyboard(channels: list) -> InlineKeyboardMarkup:
    """Kanallarga qo'shilish tugmalari"""
    keyboard = []

    for channel in channels:
        if channel.username:
            url = f"https://t.me/{channel.username.lstrip('@')}"
        else:
            # Private kanal - ID orqali
            url = f"https://t.me/c/{str(channel.channel_id)[4:]}"

        keyboard.append([
            InlineKeyboardButton(f"📢 {channel.title}", url=url)
        ])

    keyboard.append([
        InlineKeyboardButton("✅ Tekshirish", callback_data="check_membership")
    ])

    return InlineKeyboardMarkup(keyboard)


def membership_required(func):
    """
    Kanal a'zoligini tekshirish decorator

    Agar foydalanuvchi kanallarga a'zo bo'lmasa,
    qo'shilish tugmalarini ko'rsatadi
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user

        # A'zolikni tekshirish
        all_joined, not_joined = await check_user_membership(context.bot, user.id)

        if not all_joined:
            # Kanallarga a'zo emas
            text = (
                "⚠️ <b>A'zolik talab qilinadi!</b>\n\n"
                "Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:\n"
            )

            keyboard = get_join_keyboard(not_joined)

            if update.callback_query:
                await update.callback_query.answer("Avval kanallarga a'zo bo'ling!", show_alert=True)
                await update.callback_query.message.reply_html(text, reply_markup=keyboard)
            else:
                await update.message.reply_html(text, reply_markup=keyboard)

            return None

        # A'zo - funksiyani ishlatish
        return await func(update, context, *args, **kwargs)

    return wrapper


async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A'zolikni qayta tekshirish callback"""
    query = update.callback_query
    user = update.effective_user

    all_joined, not_joined = await check_user_membership(context.bot, user.id)

    if all_joined:
        await query.answer("✅ Rahmat! Endi botdan foydalanishingiz mumkin.", show_alert=True)
        await query.message.delete()
    else:
        await query.answer("❌ Hali barcha kanallarga a'zo bo'lmagansiz!", show_alert=True)

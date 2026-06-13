"""Membership tekshirish decorator va yordamchi funksiyalar"""
import logging
import time
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from database import Channel

logger = logging.getLogger(__name__)

# Tasdiqlangan a'zolik keshi: {user_id: muddat_tugashi (epoch)}
# Faqat "barcha kanallarga a'zo" holati keshlanadi — bu har bosishda Telegram
# API'siga so'rov yuborishni kamaytiradi. A'zo bo'lmagan foydalanuvchi keshlanmaydi,
# shuning uchun kanalga qo'shilgach darhol ("✅ Tekshirish" bilan) ochiladi.
_membership_cache: dict[int, float] = {}
_MEMBERSHIP_CACHE_TTL = 180  # 3 daqiqa


async def check_user_membership(bot, user_id: int, use_cache: bool = True) -> tuple[bool, list]:
    """
    Foydalanuvchi barcha kanallarga a'zo ekanligini tekshirish

    Args:
        use_cache: True bo'lsa, yaqinda tasdiqlangan a'zolikni keshdan oladi.

    Returns:
        (all_joined: bool, not_joined_channels: list)
    """
    if use_cache:
        expires_at = _membership_cache.get(user_id)
        if expires_at and expires_at > time.time():
            return True, []

    channels = list(Channel.select().where(Channel.is_active == True))
    logger.info("MEMBERSHIP CHECK: user_id=%s active_channels=%s", user_id, len(channels))

    if not channels:
        return True, []

    not_joined = []

    allowed_statuses = {"member", "administrator", "creator"}

    for channel in channels:
        try:
            member = await bot.get_chat_member(
                chat_id=channel.channel_id,
                user_id=user_id
            )
            # Ruxsat etilgan holatlar tashqarisida bo'lsa - a'zo emas
            if member.status not in allowed_statuses:
                not_joined.append(channel)
                logger.info(
                    "MEMBERSHIP CHECK: user_id=%s channel_id=%s status=%s -> not joined",
                    user_id, channel.channel_id, member.status
                )
        except TelegramError:
            # Tekshiruv xatoligi bo'lsa xavfsiz yo'l:
            # foydalanuvchini tekshirilmagan deb hisoblaymiz.
            not_joined.append(channel)
            logger.exception(
                "MEMBERSHIP CHECK ERROR: user_id=%s channel_id=%s",
                user_id, channel.channel_id
            )

    all_joined = len(not_joined) == 0
    if all_joined:
        _membership_cache[user_id] = time.time() + _MEMBERSHIP_CACHE_TTL
    else:
        # A'zolik buzilgan bo'lsa eski keshni tozalaymiz
        _membership_cache.pop(user_id, None)

    return all_joined, not_joined


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
        if not user:
            logger.warning("MEMBERSHIP CHECK: effective_user missing")
            return None

        # A'zolikni tekshirish
        all_joined, not_joined = await check_user_membership(context.bot, user.id)
        logger.info("MEMBERSHIP RESULT: user_id=%s all_joined=%s not_joined=%s", user.id, all_joined, len(not_joined))

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

    # Keshni chetlab, yangi holatni tekshiramiz (foydalanuvchi hozirgina qo'shilgan bo'lishi mumkin)
    all_joined, not_joined = await check_user_membership(context.bot, user.id, use_cache=False)

    if all_joined:
        await query.answer("✅ Rahmat! Endi botdan foydalanishingiz mumkin.", show_alert=True)
        await query.message.delete()
    else:
        await query.answer("❌ Hali barcha kanallarga a'zo bo'lmagansiz!", show_alert=True)

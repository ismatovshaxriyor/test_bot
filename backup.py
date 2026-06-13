"""Database zaxira nusxasini yaratish va yuborish (manual tugma + avtomatik jadval)"""
import logging
import os
import sqlite3
import tempfile
from datetime import datetime

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


def create_backup_file() -> tuple[str, int]:
    """Izchil SQLite snapshot yaratadi.

    SQLite backup API bot/FastAPI bir vaqtda yozayotgan bo'lsa ham buzilmagan
    nusxa beradi (oddiy fayl nusxalashdan farqli).

    Returns:
        (backup_path, size_bytes)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(tempfile.gettempdir(), f"test_bot_backup_{timestamp}.db")

    src = sqlite3.connect(DATABASE_PATH)
    try:
        dst = sqlite3.connect(backup_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    return backup_path, os.path.getsize(backup_path)


async def send_backup(bot, chat_id: int, title: str = "💾 Database zaxira nusxasi") -> None:
    """Zaxira nusxasini berilgan chatga yuboradi va vaqtinchalik faylni o'chiradi."""
    backup_path, size = create_backup_file()
    size_mb = size / (1024 * 1024)
    now_text = datetime.now().strftime("%d.%m.%Y %H:%M")

    try:
        with open(backup_path, "rb") as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=os.path.basename(backup_path),
                caption=(
                    f"<b>{title}</b>\n\n"
                    f"📅 Sana: {now_text}\n"
                    f"📦 Hajmi: {size_mb:.2f} MB"
                ),
                parse_mode="HTML",
            )
    finally:
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                pass

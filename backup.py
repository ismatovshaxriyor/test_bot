"""Database zaxira nusxasini yaratish, yuborish va tiklash (manual tugma + avtomatik jadval)"""
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


def restore_backup_file(downloaded_path: str) -> dict:
    """Yuklangan .db faylni joriy bazaga tiklaydi.

    Xavfsizlik uchun avval joriy bazaning zaxira nusxasi olinadi, keyin
    yuklangan fayl SQLite backup API orqali joriy bazaga yoziladi.

    Args:
        downloaded_path: Telegramdan yuklangan .db fayl manzili.

    Returns:
        dict: {
            "success": bool,
            "safety_backup": str | None,   — xavfsizlik nusxasi yo'li
            "error": str | None,
            "tables": dict | None,         — tiklangan jadval: yozuvlar soni
        }

    Raises:
        Hech narsa — barcha xatolar dict ichida qaytadi.
    """
    result = {"success": False, "safety_backup": None, "error": None, "tables": None}

    # 1) Yuklangan fayl haqiqiy SQLite bazasimi — tekshirish
    try:
        check = sqlite3.connect(downloaded_path)
        try:
            check.execute("SELECT count(*) FROM sqlite_master")
        finally:
            check.close()
    except sqlite3.DatabaseError as e:
        result["error"] = f"Fayl yaroqli SQLite bazasi emas: {e}"
        return result

    # 2) Joriy bazaning xavfsizlik nusxasini olish
    try:
        safety_path, _ = create_backup_file()
        result["safety_backup"] = safety_path
    except Exception as e:
        result["error"] = f"Xavfsizlik nusxasi olinmadi: {e}"
        return result

    # 3) Yuklangan faylni joriy bazaga tiklash (SQLite backup API)
    try:
        src = sqlite3.connect(downloaded_path)
        try:
            dst = sqlite3.connect(DATABASE_PATH)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except Exception as e:
        result["error"] = f"Bazani tiklashda xatolik: {e}"
        return result

    # 4) Tiklangan baza tarkibini o'qish (jadval — yozuvlar soni)
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        try:
            tables = {}
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for (tbl,) in rows:
                cnt = conn.execute(f"SELECT count(*) FROM [{tbl}]").fetchone()[0]
                tables[tbl] = cnt
            result["tables"] = tables
        finally:
            conn.close()
    except Exception:
        pass  # jadval ma'lumoti yo'q — jiddiy emas

    result["success"] = True
    return result


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

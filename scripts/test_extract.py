#!/usr/bin/env python3
"""AI extraction aniqligini sinash uchun standalone skript (botga ulanmagan).

Ishlatish:
    python scripts/test_extract.py path/to/test.pdf
    python scripts/test_extract.py path/to/rasm.jpg

Ajratilgan savollar, turlar, javoblar, has_image flaglari va ogohlantirishlarni
chop etadi. Bu — Faza 1 aniqlik darvozasi: natijani ko'z bilan baholang.
"""
import argparse
import mimetypes
import os
import sys

# Loyiha ildizini import yo'liga qo'shish (skript scripts/ ichida)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_extract import ExtractionError, get_default_extractor  # noqa: E402


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if mime:
        return mime
    ext = os.path.splitext(path)[1].lower()
    return {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(ext, "application/octet-stream")


def main() -> int:
    parser = argparse.ArgumentParser(description="AI test extraction sinovi")
    parser.add_argument("file", help="PDF yoki rasm fayl yo'li")
    parser.add_argument("--raw", action="store_true", help="Xom model javobini ham chop etish")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"❌ Fayl topilmadi: {args.file}")
        return 1

    mime = _guess_mime(args.file)
    size_mb = os.path.getsize(args.file) / (1024 * 1024)
    print(f"📄 Fayl: {args.file}")
    print(f"   Turi: {mime} | Hajmi: {size_mb:.2f} MB\n")
    print("⏳ AI tahlil qilmoqda...\n")

    with open(args.file, "rb") as f:
        file_bytes = f.read()

    try:
        extractor = get_default_extractor()
        result = extractor.extract(file_bytes, mime)
    except ExtractionError as e:
        print(f"❌ {e}")
        return 1

    print(f"✅ {len(result.questions)} ta savol ajratildi\n")
    print("─" * 70)

    img_nums = []
    for q in result.questions:
        img_flag = "  🖼 RASM" if q.has_image else ""
        if q.has_image:
            img_nums.append(q.num)
        print(f"#{q.num}  [{q.type}]  javob: {q.answer!r}{img_flag}")
        if q.text:
            text = q.text if len(q.text) <= 120 else q.text[:117] + "..."
            print(f"     S: {text}")
        if q.options:
            for label, val in q.options.items():
                mark = "✓" if str(label).lower() == str(q.answer).lower() else " "
                val = val if len(val) <= 60 else val[:57] + "..."
                print(f"       {mark} {label}) {val}")
        print()

    print("─" * 70)
    if img_nums:
        print(f"🖼  Rasm bor savollar: {img_nums}")
    if result.warnings:
        print(f"\n⚠️  Ogohlantirishlar ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"   - {w}")

    if args.raw:
        print("\n" + "=" * 70)
        print("XOM MODEL JAVOBI:")
        print(result.raw_model_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

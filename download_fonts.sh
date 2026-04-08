#!/bin/bash
# Barcha asosiy Noto fontlarini fonts/ papkasiga yuklab olish
# Ishlatish: bash download_fonts.sh

FONTS_DIR="$(dirname "$0")/fonts"
mkdir -p "$FONTS_DIR"

BASE="https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf"
BASE2="https://github.com/google/fonts/raw/main/ofl"

echo "📥 Fontlar yuklanmoqda..."

download() {
    local url="$1"
    local name="$2"
    if [ -f "$FONTS_DIR/$name" ]; then
        echo "  ✅ $name (allaqachon mavjud)"
    else
        echo "  ⬇️  $name ..."
        curl -fL "$url" -o "$FONTS_DIR/$name" --retry 3 --silent --show-error \
            && echo "  ✅ $name" \
            || echo "  ❌ $name yuklanmadi"
    fi
}

# ─── Noto Sans (lotin, kirill, yunon) ─────────────────────────────────
download "$BASE/NotoSans/NotoSans-Regular.ttf"      "NotoSans-Regular.ttf"
download "$BASE/NotoSans/NotoSans-Bold.ttf"          "NotoSans-Bold.ttf"
download "$BASE/NotoSans/NotoSans-Italic.ttf"        "NotoSans-Italic.ttf"
download "$BASE/NotoSans/NotoSans-BoldItalic.ttf"    "NotoSans-BoldItalic.ttf"

# ─── Noto Sans Math (fancy text: italic, script, bold unicode) ────────
download "$BASE/NotoSansMath/NotoSansMath-Regular.ttf" "NotoSansMath-Regular.ttf"

# ─── Noto Sans Arabic ─────────────────────────────────────────────────
download "$BASE/NotoSansArabic/NotoSansArabic-Regular.ttf" "NotoSansArabic-Regular.ttf"
download "$BASE/NotoSansArabic/NotoSansArabic-Bold.ttf"    "NotoSansArabic-Bold.ttf"

# ─── Noto Sans Hebrew ─────────────────────────────────────────────────
download "$BASE/NotoSansHebrew/NotoSansHebrew-Regular.ttf" "NotoSansHebrew-Regular.ttf"

# ─── Noto Sans Devanagari (hind, sanskrit) ────────────────────────────
download "$BASE/NotoSansDevanagari/NotoSansDevanagari-Regular.ttf" "NotoSansDevanagari-Regular.ttf"

# ─── Noto Sans Thai ───────────────────────────────────────────────────
download "$BASE/NotoSansThai/NotoSansThai-Regular.ttf" "NotoSansThai-Regular.ttf"

# ─── Noto Sans CJK (xitoy, yapon, koreys) — kichik subset ────────────
# To'liq CJK 30MB+ — faqat kerak bo'lsa yuklab oling:
download "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf" "NotoSansCJKsc-Regular.otf"

# ─── Noto Emoji (mono, rang chiqmasa ham ko'rinadi) ───────────────────
download "$BASE/NotoEmoji/NotoEmoji-Regular.ttf" "NotoEmoji-Regular.ttf"

echo ""
echo "📊 Fonts papkasi:"
ls -lh "$FONTS_DIR"
echo ""
echo "✅ Tayyor! Font cache ni yangilang:"
echo "   sudo fc-cache -fv"
echo "   (yoki botni qayta ishga tushiring)"

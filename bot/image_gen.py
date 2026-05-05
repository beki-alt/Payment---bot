"""
image_gen.py - Membership Card Generator
Uses Pillow to draw Amharic text on template.png using Nyala.ttf font.
"""

import os
import io
import logging
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "assets", "template.png")
FONT_PATH = os.path.join(BASE_DIR, "assets", "Nyala.ttf")

NAME_FONT_SIZE   = 52
ID_FONT_SIZE     = 30
STATUS_FONT_SIZE = 34
DATE_FONT_SIZE   = 26
LABEL_FONT_SIZE  = 22

# ─── Text positions tuned for the PAYMENT122-style dark card ──────────────────
# The right-hand clean navy area spans roughly x=420..980, y=140..520
# A thin gold divider line is drawn under each field for polish.
CARD_CONFIG = {
    # (x, y) anchors — left-aligned in the clean right panel
    "name_pos":   (450, 195),
    "id_pos":     (450, 300),
    "status_pos": (450, 375),
    "date_pos":   (450, 450),

    # Label text shown above each value (smaller, gold)
    "label_name":   "ስም",
    "label_id":     "Telegram ID",
    "label_status": "ሁኔታ",
    "label_date":   "ቀን",

    # Colours — bright so they show on dark navy
    "label_color":         (212, 175, 55),   # gold
    "name_color":          (255, 255, 255),  # white
    "id_color":            (200, 210, 230),  # light blue-white
    "status_paid_color":   (72, 220, 120),   # bright green
    "status_unpaid_color": (255, 90, 90),    # bright red
    "date_color":          (180, 190, 210),  # soft blue-white

    # Gold divider line drawn under name and ID
    "divider_color": (212, 175, 55),
    "divider_height": 1,
    "divider_width": 480,   # px wide (fits within the right panel)
}


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load Nyala.ttf with fallback to default font."""
    if os.path.exists(FONT_PATH):
        return ImageFont.truetype(FONT_PATH, size)
    logger.warning(f"Nyala.ttf not found at {FONT_PATH}, using default font.")
    return ImageFont.load_default()


def _ensure_template() -> Image.Image:
    """Load template or create a default card background."""
    if os.path.exists(TEMPLATE_PATH):
        img = Image.open(TEMPLATE_PATH).convert("RGBA")
        # Resize to a consistent working size while preserving aspect ratio
        img = img.resize((1024, 640), Image.LANCZOS)
        return img

    # Fallback: generate a dark navy card if template.png is missing
    logger.warning(f"template.png not found at {TEMPLATE_PATH}. Generating default card.")
    card = Image.new("RGBA", (1024, 640), color=(10, 20, 50))
    draw = ImageDraw.Draw(card)
    draw.rectangle([(0, 0), (1024, 90)], fill=(20, 40, 90))
    draw.rectangle([(0, 90), (1024, 96)], fill=(212, 175, 55))
    draw.rectangle([(8, 8), (1016, 632)], outline=(212, 175, 55), width=3)
    try:
        draw.text((30, 22), "የደንበኝነት ካርድ", font=_load_font(36), fill=(255, 255, 255))
    except Exception:
        pass
    return card


def _draw_field(
    draw: ImageDraw.ImageDraw,
    label: str,
    value: str,
    pos: tuple,
    label_font,
    value_font,
    value_color: tuple,
    cfg: dict,
):
    """Draw a gold label + white value + gold divider line."""
    x, y = pos
    # Label (small gold text above the value)
    draw.text((x, y - 26), label, font=label_font, fill=cfg["label_color"])
    # Value
    draw.text((x, y), value, font=value_font, fill=value_color)
    # Thin gold divider below the value
    line_y = y + value_font.size + 6
    draw.rectangle(
        [(x, line_y), (x + cfg["divider_width"], line_y + cfg["divider_height"])],
        fill=cfg["divider_color"],
    )


def generate_membership_card(
    telegram_id: int,
    name: str,
    status: str,
) -> io.BytesIO:
    """
    Generate a membership card image as a BytesIO object.

    Args:
        telegram_id: The user's Telegram ID
        name:        The user's display name (Amharic supported)
        status:      "paid" or "unpaid"

    Returns:
        BytesIO containing the PNG image
    """
    try:
        from utils import now_eth, to_ethiopian, eth_month_name

        card = _ensure_template()
        draw = ImageDraw.Draw(card)

        label_font  = _load_font(LABEL_FONT_SIZE)
        name_font   = _load_font(NAME_FONT_SIZE)
        id_font     = _load_font(ID_FONT_SIZE)
        status_font = _load_font(STATUS_FONT_SIZE)
        date_font   = _load_font(DATE_FONT_SIZE)

        cfg = CARD_CONFIG

        # Ethiopian date
        eth_yr, eth_mo, eth_day = to_ethiopian(now_eth())
        date_text = f"{eth_day} {eth_month_name(eth_mo)} {eth_yr} ዓ.ም"

        # Status
        if status == "paid":
            status_text  = "✅  ተከፍሏል"
            status_color = cfg["status_paid_color"]
        else:
            status_text  = "❌  አልተከፈለም"
            status_color = cfg["status_unpaid_color"]

        # Draw all four fields with labels + dividers
        _draw_field(draw, cfg["label_name"],   name,
                    cfg["name_pos"],   label_font, name_font,
                    cfg["name_color"], cfg)

        _draw_field(draw, cfg["label_id"],     f"ID: {telegram_id}",
                    cfg["id_pos"],     label_font, id_font,
                    cfg["id_color"],   cfg)

        _draw_field(draw, cfg["label_status"], status_text,
                    cfg["status_pos"], label_font, status_font,
                    status_color,      cfg)

        _draw_field(draw, cfg["label_date"],   date_text,
                    cfg["date_pos"],   label_font, date_font,
                    cfg["date_color"], cfg)

        # Flatten RGBA → RGB on white, then save as PNG
        output = io.BytesIO()
        if card.mode == "RGBA":
            bg = Image.new("RGB", card.size, (255, 255, 255))
            bg.paste(card, mask=card.split()[3])
            bg.save(output, format="PNG", optimize=True)
        else:
            card.save(output, format="PNG", optimize=True)

        output.seek(0)
        return output

    except Exception as e:
        logger.error(f"Card generation error for user {telegram_id}: {e}")
        fallback = Image.new("RGB", (500, 250), color=(10, 20, 50))
        draw = ImageDraw.Draw(fallback)
        draw.text((20, 100), f"ካርድ ማምረት አልተቻለም — {name}", fill=(200, 200, 200))
        output = io.BytesIO()
        fallback.save(output, format="PNG")
        output.seek(0)
        return output

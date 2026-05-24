from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw

from voice_task_board.paths import app_data_dir


logger = logging.getLogger(__name__)

_BLUE = (41, 128, 185, 255)
_WHITE = (255, 255, 255, 255)


def _draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(1, size // 16)
    draw.ellipse((pad, pad, size - pad, size - pad), fill=_BLUE)

    mic_w = size // 4
    mic_h = size // 2 - size // 8
    cx = size // 2
    top = size // 5
    draw.rounded_rectangle(
        (cx - mic_w // 2, top, cx + mic_w // 2, top + mic_h),
        radius=mic_w // 2,
        fill=_WHITE,
    )

    stroke = max(2, size // 24)
    arc_box = (cx - mic_w, top + mic_h // 3, cx + mic_w, top + mic_h + mic_w)
    draw.arc(arc_box, 0, 180, fill=_WHITE, width=stroke)
    stand_top = top + mic_h + mic_w // 2
    draw.line((cx, stand_top, cx, stand_top + size // 8), fill=_WHITE, width=stroke)
    base_w = size // 5
    draw.line((cx - base_w // 2, stand_top + size // 8, cx + base_w // 2, stand_top + size // 8), fill=_WHITE, width=stroke)

    return img


def get_icon_image(size: int = 256) -> Image.Image:
    """In-memory PIL image for pystray."""
    return _draw(size)


def get_icon_ico_path() -> Path:
    """Generate (once) and return path to a multi-resolution .ico file for the Windows taskbar."""
    path = app_data_dir() / "app_icon.ico"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        base = _draw(256)
        base.save(path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        logger.info(f"Generated app icon at {path}")
    return path

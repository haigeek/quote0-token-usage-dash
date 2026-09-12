"""
Render a 296×152 black/white PNG image showing Claude, OpenAI Codex and
OpenCode Go usage.

Uses Terminus bitmap font — pure B&W pixels, no anti-aliasing, no grey.
No supersampling needed.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 296, 152
PAD  = 6

_HERE        = Path(__file__).parent
FONT_REGULAR = str(_HERE / "fonts" / "terminus-normal.otb")
FONT_BOLD    = str(_HERE / "fonts" / "terminus-bold.otb")

BLACK = 0
WHITE = 255


def _local_tz():
    """Resolve the local timezone for the header clock.

    `datetime.now().astimezone()` honours the host's TZ setting and falls back
    to UTC when the zone cannot be determined, so this never raises.
    """
    return datetime.now().astimezone().tzinfo

LABEL_W = 22   # px reserved for row label ("5h", "7d", "Wk")
NOTE_W  = 90   # px reserved for right-side text ("87%  2h37m")


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _lsize(font: ImageFont.FreeTypeFont) -> int:
    return font.size


def _lw(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    return int(draw.textlength(text, font=font))


def _text_tracked(draw: ImageDraw.ImageDraw, pos: tuple[int, int], text: str,
                  font: ImageFont.FreeTypeFont, spacing: int = 1) -> None:
    """Draw text with extra letter spacing (tracking)."""
    x, y = pos
    for ch in text:
        draw.text((x, y), ch, font=font, fill=BLACK)
        x += _lw(draw, ch, font) + spacing


DOT_SPACING = 4  # one dot per NxN grid in the empty bar area

def _bar(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, used_pct: float) -> None:
    draw.rectangle([x, y, x + w - 1, y + h - 1], outline=BLACK, width=1)
    # Filled portion
    filled = int((w - 2) * min(used_pct, 100) / 100)
    if filled > 0:
        draw.rectangle([x + 1, y + 1, x + filled, y + h - 2], fill=BLACK)
    # Empty portion: dot grid anchored to bar left so pattern is consistent
    grid_x0 = x + 1         # anchor — same for every bar
    grid_x1 = x + w - 2
    grid_y0 = y + 1
    grid_y1 = y + h - 2
    empty_x0 = grid_x0 + filled  # clip: only draw in empty region
    margin = DOT_SPACING // 2
    for dy in range(grid_y0 + margin, grid_y1 - margin + 1, DOT_SPACING):
        for dx in range(grid_x0 + margin, grid_x1 - margin + 1, DOT_SPACING):
            if dx >= empty_x0:
                draw.point((dx, dy), fill=BLACK)


def _draw_row(
    draw: ImageDraw.ImageDraw,
    y: int,
    row_h: int,
    label: str,
    used_pct: float,
    note: Optional[str],
    fonts: dict,
) -> None:
    lbl_font  = fonts["label"]
    note_font = fonts["note"]

    bar_h = max(8, row_h - 4)
    bar_y = y + (row_h - bar_h) // 2

    lbl_h  = _lsize(lbl_font)
    note_h = _lsize(note_font)

    # Label
    draw.text((PAD, bar_y + (bar_h - lbl_h) // 2), label, font=lbl_font, fill=BLACK)

    # Note (right-aligned). Shows consumption, matching how the bar fills.
    note_text = f"{used_pct:.0f}%"
    if note:
        note_text += f"  {note}"
    note_x = W - PAD - NOTE_W
    draw.text((note_x, bar_y + (bar_h - note_h) // 2), note_text, font=note_font, fill=BLACK)

    # Bar
    bar_x = PAD + LABEL_W
    bar_w = note_x - 4 - bar_x
    _bar(draw, bar_x, bar_y, bar_w, bar_h, used_pct)


def render_image(
    claude_usage: Optional[dict],
    openai_usage=None,
    opencode_usage=None,
) -> bytes:
    img  = Image.new("L", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    fonts = {
        "title":   _font(FONT_BOLD,    14),
        "ts":      _font(FONT_REGULAR, 12),
        "section": _font(FONT_BOLD,    12),
        "label":   _font(FONT_BOLD,    12),
        "note":    _font(FONT_REGULAR, 12),
    }

    # ── Header ────────────────────────────────────────────────────────────
    now      = datetime.now(_local_tz())
    date_str = now.strftime("%b %-d")
    time_str = now.strftime("%-I:%M %p")

    _text_tracked(draw, (PAD, PAD), "Token Usage", fonts["title"], spacing=2)

    ts_w   = _lw(draw, time_str, fonts["ts"])
    date_w = _lw(draw, date_str, fonts["ts"])
    ts_y   = PAD + (_lsize(fonts["title"]) - _lsize(fonts["ts"])) // 2
    draw.text((W - PAD - ts_w, ts_y), time_str, font=fonts["ts"], fill=BLACK)
    draw.text((W - PAD - ts_w - 6 - date_w, ts_y), date_str, font=fonts["ts"], fill=BLACK)

    header_bottom = PAD + _lsize(fonts["title"]) + 4
    draw.line([(0, header_bottom), (W, header_bottom)], fill=BLACK, width=1)

    # ── Collect sections ──────────────────────────────────────────────────
    from display import format_time_until, format_time_until_iso

    claude_rows: list[tuple[str, float, Optional[str]]] = []
    if claude_usage:
        # Only the 5-hour and 7-day windows: the 7dS/7dO sub-limit rows are
        # dropped so three provider sections still fit the 296×152 canvas.
        for key, lbl in [("five_hour", "5h"), ("seven_day", "7d")]:
            w = claude_usage.get(key)
            if w:
                try:
                    note = format_time_until_iso(w["resets_at"])
                except Exception:
                    note = None
                claude_rows.append((lbl, w["utilization"], note))

    openai_rows: list[tuple[str, float, Optional[str]]] = []
    if openai_usage:
        if openai_usage.primary_limit:
            w = openai_usage.primary_limit
            openai_rows.append(("5h", w.used_percent,
                                 format_time_until(w.resets_at) if w.resets_at else None))
        if openai_usage.secondary_limit:
            w = openai_usage.secondary_limit
            openai_rows.append(("Wk", w.used_percent,
                                 format_time_until(w.resets_at) if w.resets_at else None))

    opencode_rows: list[tuple[str, float, Optional[str]]] = []
    if opencode_usage:
        for lbl, w in [("5h", opencode_usage.rolling),
                       ("Wk", opencode_usage.weekly),
                       ("Mo", opencode_usage.monthly)]:
            if w:
                opencode_rows.append((lbl, w.used_percent,
                                      format_time_until(w.resets_at) if w.resets_at else None))

    sections: list[tuple[str, list[tuple[str, float, Optional[str]]]]] = []
    if claude_rows:
        sections.append(("Claude", claude_rows))
    if openai_rows:
        label = "OpenAI Codex"
        if openai_usage and openai_usage.credits_remaining is not None:
            label += f"  ({openai_usage.credits_remaining:.0f} cr)"
        sections.append((label, openai_rows))
    if opencode_rows:
        sections.append(("OpenCode Go", opencode_rows))

    # ── Layout ────────────────────────────────────────────────────────────
    SECTION_H = _lsize(fonts["section"]) + 5
    DIVIDER_H = 8
    MIN_BAR_H = 8          # matches the floor in _draw_row
    MIN_ROW_H = MIN_BAR_H + 4

    content_h = H - header_bottom - 2

    def _measure(n_rows: int, n_sections: int) -> tuple[int, int]:
        fixed_h = n_sections * SECTION_H
        if n_sections > 1:
            fixed_h += DIVIDER_H * (n_sections - 1)
        if n_rows <= 0:
            return content_h, content_h
        row_h = min((content_h - fixed_h) // n_rows, 28)
        return row_h, fixed_h + row_h * n_rows

    def _fit(secs):
        """Trim trailing rows until the block fits, and keep bars drawable."""
        secs = [(title, list(rows)) for title, rows in secs if rows]
        while secs:
            n_rows = sum(len(rows) for _, rows in secs)
            row_h, total_h = _measure(n_rows, len(secs))
            if row_h >= MIN_ROW_H and total_h <= content_h:
                return secs, row_h, total_h
            # Trim one row at a time, preferring sections that have spares so
            # every provider heading survives as long as possible.
            trimmed = False
            for i in range(len(secs) - 1, -1, -1):
                if len(secs[i][1]) > 1:
                    secs[i][1].pop()
                    trimmed = True
                    break
            if not trimmed:
                secs.pop()
        return [], 0, 0

    sections, row_h, total_h = _fit(sections)

    # Vertically center the content block when it doesn't fill the space
    y = header_bottom + 2 + (content_h - total_h) // 2

    for idx, (title, rows) in enumerate(sections):
        if idx > 0:
            # ── Dashed divider ────────────────────────────────────────────
            y += DIVIDER_H // 2
            dash, gap, x = 6, 4, 0
            while x < W:
                draw.line([(x, y), (min(x + dash - 1, W), y)], fill=BLACK, width=1)
                x += dash + gap
            y += DIVIDER_H // 2

        draw.text((PAD, y), title, font=fonts["section"], fill=BLACK)
        y += SECTION_H
        for label, used_pct, note in rows:
            _draw_row(draw, y, row_h, label, used_pct, note, fonts)
            y += row_h

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    from usage import get_claude_usage, get_openai_usage, get_opencode_go_usage
    from display import CLAUDE_ENABLED, OPENAI_ENABLED, OPENCODE_ENABLED

    claude, openai, opencode = None, None, None
    if CLAUDE_ENABLED:
        try:
            claude = get_claude_usage()
        except Exception as e:
            print(f"Claude error: {e}")
    if OPENAI_ENABLED:
        try:
            openai = get_openai_usage()
        except Exception as e:
            print(f"OpenAI error: {e}")
    if OPENCODE_ENABLED:
        try:
            opencode = get_opencode_go_usage()
        except Exception as e:
            print(f"OpenCode Go error: {e}")

    png = render_image(claude, openai, opencode)
    with open("/tmp/usage_preview.png", "wb") as f:
        f.write(png)
    print(f"Saved /tmp/usage_preview.png ({len(png)} bytes)")

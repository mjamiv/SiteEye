#!/usr/bin/env python3
"""SiteEye v2 LCD UI — Cozmo-style animated face on Whisplay 240×280 ST7789

Features:
  - Expressive eyes with blinks, saccades, squints, wide-open
  - Animated mouth (speaking shapes, smile, neutral, surprised)
  - Eyebrows for emotion
  - State-driven expressions with smooth transitions
  - RGB LED sync
"""

import sys
import time
import math
import random
import threading

sys.path.insert(0, '/home/pi-molt/Whisplay/Driver')

from PIL import Image, ImageDraw, ImageFont
from WhisPlay import WhisPlayBoard

# Display constants
WIDTH = 240
HEIGHT = 280
# Whisplay LCD has 20px rounded corners top and bottom.
# Safe zone: avoid placing content in the corner triangles.
CORNER_H = 20  # corner chamfer height in px
SAFE_TOP = CORNER_H + 2  # safe y for text at top
SAFE_BOT = HEIGHT - CORNER_H - 2  # safe y for text at bottom
SAFE_LEFT = 12  # inset from left edge near corners
SAFE_RIGHT = WIDTH - 12

# Colors
BG = (10, 10, 26)
EYE_WHITE = (255, 255, 255)
PUPIL = (26, 26, 46)
HIGHLIGHT = (136, 204, 255)
TEXT_PRIMARY = (255, 255, 255)
TEXT_DIM = (102, 102, 136)
BLUE_ACCENT = (0, 100, 255)
YELLOW_ACCENT = (255, 200, 0)
PURPLE_ACCENT = (180, 0, 255)
RED_ACCENT = (255, 51, 51)
GREEN_ACCENT = (0, 204, 68)
MOUTH_COLOR = (220, 220, 240)
MOUTH_INSIDE = (40, 20, 60)
BROW_COLOR = (200, 200, 220)

# Face geometry — centered on full 240×280 display
EYE_Y = 105  # vertical center for eyes (shifted down to clear top chamfer)
LEFT_EYE_X = 72
RIGHT_EYE_X = 168
EYE_W = 38  # slightly wider for bigger screen presence
EYE_H = 32
PUPIL_R = 11
CORNER_R = 10
MOUTH_Y = 160  # mouth below eyes
MOUTH_CX = 120

# States
STATE_BOOT = "boot"
STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_THINKING = "thinking"
STATE_SPEAKING = "speaking"
STATE_CAMERA = "camera"
STATE_ERROR = "error"
STATE_HAPPY = "happy"


class LcdUI:
    def __init__(self):
        self.board = WhisPlayBoard()
        self.board.set_backlight(70)
        self.state = STATE_BOOT
        self.response_text = ""
        self.status_text = ""
        self._running = True

        # Animation state
        self._blink_amount = 0.0
        self._next_blink = time.time() + random.uniform(2, 5)
        self._saccade_x = 0.0
        self._saccade_y = 0.0
        self._next_saccade = time.time() + random.uniform(1, 3)
        self._anim_frame = 0
        self._mouth_open = 0.0  # 0=closed, 1=full open
        self._target_mouth = 0.0
        self._smile = 0.0  # -1=frown, 0=neutral, 1=smile
        self._target_smile = 0.0
        self._brow_raise = 0.0  # -1=angry, 0=neutral, 1=raised
        self._target_brow = 0.0
        self._lid_squint = 0.0
        self._target_squint = 0.0
        self._pupil_size = 1.0  # multiplier
        self._target_pupil = 1.0
        self._expression_start = 0
        self._idle_mood_timer = time.time() + random.uniform(8, 15)
        self._lock = threading.Lock()

        # Font cache
        try:
            self._font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
            self._font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
            self._font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            self._font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            self._font_sm = ImageFont.load_default()
            self._font_md = self._font_sm
            self._font_lg = self._font_sm
            self._font_sub = self._font_sm

    def set_state(self, state, text=""):
        with self._lock:
            self.state = state
            if text:
                self.response_text = text
            self._anim_frame = 0
            self._expression_start = time.time()

        # Set expression targets based on state
        if state == STATE_IDLE:
            self._target_smile = 0.15
            self._target_brow = 0.0
            self._target_squint = 0.0
            self._target_mouth = 0.0
            self._target_pupil = 1.0
        elif state == STATE_LISTENING:
            self._target_smile = 0.0
            self._target_brow = 0.4  # raised brows = attentive
            self._target_squint = -0.15  # eyes wider
            self._target_mouth = 0.0
            self._target_pupil = 1.2  # dilated = focused
        elif state == STATE_THINKING:
            self._target_smile = -0.1
            self._target_brow = 0.2
            self._target_squint = 0.2  # slight squint
            self._target_mouth = 0.0
            self._target_pupil = 0.8
        elif state == STATE_SPEAKING:
            self._target_smile = 0.2
            self._target_brow = 0.1
            self._target_squint = 0.0
            self._target_pupil = 1.0
            # Mouth animated in render loop
        elif state == STATE_CAMERA:
            self._target_smile = 0.0
            self._target_brow = 0.5  # surprised
            self._target_squint = -0.2  # wide
            self._target_mouth = 0.4  # slightly open
            self._target_pupil = 0.7  # constrict
        elif state == STATE_ERROR:
            self._target_smile = -0.4
            self._target_brow = -0.3  # worried
            self._target_squint = 0.1
            self._target_mouth = 0.2
            self._target_pupil = 0.9
        elif state == STATE_HAPPY:
            self._target_smile = 0.8
            self._target_brow = 0.3
            self._target_squint = 0.15  # happy squint
            self._target_mouth = 0.3
            self._target_pupil = 1.1

        # Set RGB LED
        led_map = {
            STATE_IDLE: (0, 60, 0),
            STATE_LISTENING: (0, 50, 255),
            STATE_THINKING: (255, 180, 0),
            STATE_SPEAKING: (160, 0, 255),
            STATE_CAMERA: (255, 255, 255),
            STATE_ERROR: (255, 0, 0),
            STATE_HAPPY: (0, 200, 100),
            STATE_BOOT: (50, 50, 80),
        }
        r, g, b = led_map.get(state, (0, 40, 0))
        try:
            self.board.set_rgb(r, g, b)
        except:
            pass

    def set_status(self, text):
        with self._lock:
            self.status_text = text

    def _lerp(self, current, target, speed=0.15):
        """Smooth interpolation."""
        return current + (target - current) * speed

    def _update_animation(self):
        """Update all smooth animation values."""
        now = time.time()

        # Smooth expression transitions
        self._smile = self._lerp(self._smile, self._target_smile, 0.12)
        self._brow_raise = self._lerp(self._brow_raise, self._target_brow, 0.1)
        self._lid_squint = self._lerp(self._lid_squint, self._target_squint, 0.12)
        self._pupil_size = self._lerp(self._pupil_size, self._target_pupil, 0.1)
        self._mouth_open = self._lerp(self._mouth_open, self._target_mouth, 0.2)

        # Speaking mouth animation
        if self.state == STATE_SPEAKING:
            # Simulate speech with varied mouth shapes
            t = self._anim_frame * 0.15
            self._target_mouth = 0.15 + 0.35 * abs(math.sin(t * 2.7)) * abs(math.sin(t * 1.3))

        # Auto-blink
        if now > self._next_blink:
            self._blink_amount = 1.0
            self._next_blink = now + random.uniform(2.5, 6)
            # Occasional double-blink
            if random.random() < 0.2:
                self._next_blink = now + 0.3
        if self._blink_amount > 0:
            self._blink_amount = max(0, self._blink_amount - 0.18)

        # Saccades (micro eye movements)
        if now > self._next_saccade:
            if self.state == STATE_THINKING:
                # Look up-right when thinking
                self._saccade_x = random.uniform(0.15, 0.4)
                self._saccade_y = random.uniform(-0.3, -0.1)
            elif self.state == STATE_LISTENING:
                # Look at speaker (center, slightly down)
                self._saccade_x = random.uniform(-0.1, 0.1)
                self._saccade_y = random.uniform(0.0, 0.15)
            else:
                self._saccade_x = random.uniform(-0.3, 0.3)
                self._saccade_y = random.uniform(-0.2, 0.2)
            self._next_saccade = now + random.uniform(1.0, 3.5)

        # Idle mood shifts
        if self.state == STATE_IDLE and now > self._idle_mood_timer:
            mood = random.choice(["neutral", "slight_smile", "curious", "sleepy"])
            if mood == "slight_smile":
                self._target_smile = 0.3
                self._target_brow = 0.1
            elif mood == "curious":
                self._target_smile = 0.0
                self._target_brow = 0.35
                self._target_squint = -0.1
            elif mood == "sleepy":
                self._target_smile = 0.1
                self._target_squint = 0.2
                self._target_brow = -0.1
            else:
                self._target_smile = 0.15
                self._target_brow = 0.0
                self._target_squint = 0.0
            self._idle_mood_timer = now + random.uniform(5, 12)

    def render_frame(self):
        """Render one frame and push to display."""
        img = Image.new('RGB', (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)

        with self._lock:
            state = self.state
            resp = self.response_text
            status = self.status_text
            self._anim_frame += 1

        self._update_animation()

        # Status bar — inside safe zone (below top chamfer)
        if status:
            draw.text((SAFE_LEFT + 4, SAFE_TOP), status, fill=TEXT_DIM, font=self._font_sm)

        if state == STATE_BOOT:
            self._draw_boot(draw)
        elif state == STATE_CAMERA:
            self._draw_camera_screen(draw)
        else:
            # --- EYEBROWS ---
            self._draw_brow(draw, LEFT_EYE_X, EYE_Y - EYE_H - 8, is_left=True)
            self._draw_brow(draw, RIGHT_EYE_X, EYE_Y - EYE_H - 8, is_left=False)

            # --- EYES ---
            accent = {
                STATE_LISTENING: BLUE_ACCENT,
                STATE_THINKING: YELLOW_ACCENT,
                STATE_SPEAKING: PURPLE_ACCENT,
                STATE_ERROR: RED_ACCENT,
                STATE_HAPPY: GREEN_ACCENT,
            }.get(state, HIGHLIGHT)

            self._draw_eye(draw, LEFT_EYE_X, EYE_Y, self._saccade_x, self._saccade_y, accent)
            self._draw_eye(draw, RIGHT_EYE_X, EYE_Y, self._saccade_x, self._saccade_y, accent)

            # --- MOUTH ---
            self._draw_mouth(draw)

            # --- State indicators (below mouth) ---
            if state == STATE_LISTENING:
                self._draw_listening_indicator(draw)
            elif state == STATE_THINKING:
                self._draw_thinking_indicator(draw)

        # Response text OR mode bar — text takes priority when present
        if resp and state not in (STATE_BOOT, STATE_CAMERA):
            # Response text gets full area below face — no mode bar competing
            self._draw_response_text(draw, resp)
        else:
            # Mode bar only when no text displayed
            self._draw_mode_bar(draw, state)

        # Push to display
        self._send_to_display(img)

    def _draw_eye(self, draw, cx, cy, pox, poy, accent):
        """Draw one expressive eye."""
        # Eye dimensions with squint
        w = EYE_W
        h = int(EYE_H * (1.0 - abs(self._lid_squint) * 0.3))
        if self._lid_squint < 0:  # wide open
            h = int(EYE_H * (1.0 - self._lid_squint * 0.25))

        x1 = cx - w
        y1 = cy - h
        x2 = cx + w
        y2 = cy + h

        # Eyeball
        draw.rounded_rectangle([x1, y1, x2, y2], radius=CORNER_R, fill=EYE_WHITE)

        # Pupil with size variation
        pr = int(PUPIL_R * self._pupil_size)
        px = cx + int(pox * w * 0.4)
        py = cy + int(poy * h * 0.35)
        draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=PUPIL)

        # Inner pupil (darker center for depth)
        ipr = max(2, pr // 2)
        draw.ellipse([px - ipr, py - ipr, px + ipr, py + ipr], fill=(10, 10, 20))

        # Highlight reflection (two dots for life)
        hx, hy = px - 4, py - 4
        draw.ellipse([hx - 3, hy - 3, hx + 3, hy + 3], fill=(255, 255, 255))
        # Secondary smaller highlight
        h2x, h2y = px + 3, py + 2
        draw.ellipse([h2x - 1, h2y - 1, h2x + 1, h2y + 1], fill=accent)

        # Eyelid masking (blink + squint)
        blink = self._blink_amount
        top_close = max(0, self._lid_squint * 0.5 + blink * 0.5)
        bot_close = max(0, blink * 0.4)

        if top_close > 0:
            lid_y = y1 + int(top_close * (h * 2))
            draw.rounded_rectangle([x1 - 2, y1 - 6, x2 + 2, min(lid_y, y2)],
                                    radius=CORNER_R, fill=BG)
        if bot_close > 0:
            lid_y = y2 - int(bot_close * (h * 2))
            draw.rounded_rectangle([x1 - 2, max(lid_y, y1), x2 + 2, y2 + 6],
                                    radius=CORNER_R, fill=BG)

        # Happy squint (curved bottom lid) when smiling big
        if self._smile > 0.4:
            squint_h = int((self._smile - 0.4) * h * 0.8)
            for dx in range(-w, w + 1):
                curve = int(squint_h * (1 - (dx / w) ** 2))
                if curve > 0:
                    sx = cx + dx
                    sy = y2 - curve
                    draw.rectangle([sx, sy, sx, y2 + 2], fill=BG)

    def _draw_brow(self, draw, cx, cy, is_left):
        """Draw one eyebrow."""
        brow_w = EYE_W - 4
        raise_amt = self._brow_raise

        # Inner and outer y positions
        inner_y = cy - int(raise_amt * 8)
        outer_y = cy - int(raise_amt * 4)

        if raise_amt < 0:  # angry — inner goes down
            inner_y = cy - int(raise_amt * 6)
            outer_y = cy + int(abs(raise_amt) * 3)

        if is_left:
            pts = [(cx - brow_w, outer_y), (cx + brow_w // 2, inner_y)]
        else:
            pts = [(cx - brow_w // 2, inner_y), (cx + brow_w, outer_y)]

        draw.line(pts, fill=BROW_COLOR, width=3)

    def _draw_mouth(self, draw):
        """Draw expressive mouth."""
        cx = MOUTH_CX
        cy = MOUTH_Y
        mouth_w = 28 + int(self._mouth_open * 12)
        open_h = int(self._mouth_open * 16)
        smile_curve = int(self._smile * 12)

        if self._mouth_open < 0.08:
            # Closed mouth — just a curved line
            pts = []
            for i in range(21):
                t = i / 20.0
                x = cx - mouth_w + int(t * mouth_w * 2)
                # Quadratic curve for smile/frown
                progress = (t - 0.5) * 2  # -1 to 1
                y = cy - int(smile_curve * (1 - progress ** 2))
                pts.append((x, y))
            if len(pts) > 1:
                draw.line(pts, fill=MOUTH_COLOR, width=2)
        else:
            # Open mouth — elliptical shape
            top_y = cy - open_h // 3
            bot_y = cy + open_h * 2 // 3 + smile_curve

            # Outer mouth shape
            mouth_bbox = [cx - mouth_w, top_y - 2, cx + mouth_w, bot_y + 2]
            draw.rounded_rectangle(mouth_bbox, radius=mouth_w // 2, fill=MOUTH_INSIDE)
            draw.rounded_rectangle(mouth_bbox, radius=mouth_w // 2, outline=MOUTH_COLOR, width=2)

            # Tongue hint when mouth is wide open
            if self._mouth_open > 0.5:
                tongue_w = mouth_w // 2
                tongue_y = bot_y - 4
                draw.ellipse([cx - tongue_w, tongue_y - 3, cx + tongue_w, tongue_y + 5],
                             fill=(180, 80, 100))

            # Teeth hint at top
            if open_h > 6:
                teeth_h = min(4, open_h // 3)
                draw.rectangle([cx - mouth_w + 6, top_y, cx + mouth_w - 6, top_y + teeth_h],
                               fill=(240, 240, 245))

    def _draw_listening_indicator(self, draw):
        """Audio level visualization for listening state."""
        y = 178
        frame = self._anim_frame
        # Pulsing bars like an audio meter
        for i in range(7):
            x = 90 + i * 10
            h = 3 + int(5 * abs(math.sin(frame * 0.25 + i * 0.8)))
            color_intensity = 100 + int(155 * abs(math.sin(frame * 0.2 + i * 0.5)))
            c = (0, min(255, color_intensity // 2), min(255, color_intensity))
            draw.rectangle([x, y - h, x + 5, y + h], fill=c)

    def _draw_thinking_indicator(self, draw):
        """Animated thinking dots."""
        y = 178
        frame = self._anim_frame
        active = (frame // 6) % 3
        for i in range(3):
            x = 108 + i * 12
            if i == active:
                r = 4
                c = YELLOW_ACCENT
            else:
                r = 3
                c = (80, 65, 0)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=c)

    def _draw_boot(self, draw):
        """Boot animation screen."""
        frame = self._anim_frame

        # Fade in effect
        alpha = min(1.0, frame / 15.0)
        text_c = tuple(int(v * alpha) for v in HIGHLIGHT)
        sub_c = tuple(int(v * alpha) for v in TEXT_DIM)

        draw.text((55, 100), "SiteEye", fill=text_c, font=self._font_lg)
        draw.text((90, 135), "v2.0", fill=sub_c, font=self._font_sub)

        # Loading bar
        bar_w = 140
        bar_x = (WIDTH - bar_w) // 2
        bar_y = 178
        progress = min(1.0, frame / 20.0)
        draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + 6],
                                radius=3, fill=(30, 30, 50))
        fill_w = int(bar_w * progress)
        if fill_w > 0:
            draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + 6],
                                    radius=3, fill=HIGHLIGHT)

        draw.text((72, 205), "Booting...", fill=sub_c, font=self._font_sub)

    def _draw_camera_screen(self, draw):
        """Camera capture screen with countdown feel."""
        frame = self._anim_frame

        # Flash effect on first frames
        if frame < 3:
            draw.rectangle([0, 0, WIDTH, HEIGHT], fill=(255, 255, 255))
            return

        # Camera icon — centered on full display
        draw.ellipse([80, 80, 160, 160], outline=HIGHLIGHT, width=3)
        draw.ellipse([98, 98, 142, 142], outline=(80, 80, 120), width=2)
        draw.ellipse([110, 110, 130, 130], fill=(40, 40, 80))
        draw.ellipse([117, 117, 123, 123], fill=HIGHLIGHT)

        draw.text((70, 175), "Capturing...", fill=TEXT_PRIMARY, font=self._font_sub)

    def _draw_mode_bar(self, draw, state):
        """Bottom mode indicator."""
        mode_map = {
            STATE_IDLE: ("● Ready", GREEN_ACCENT),
            STATE_LISTENING: ("● Listening...", BLUE_ACCENT),
            STATE_THINKING: ("● Thinking...", YELLOW_ACCENT),
            STATE_SPEAKING: ("● Speaking...", PURPLE_ACCENT),
            STATE_CAMERA: ("● Camera", HIGHLIGHT),
            STATE_ERROR: ("● Error", RED_ACCENT),
            STATE_HAPPY: ("● :)", GREEN_ACCENT),
        }
        text, color = mode_map.get(state, ("", TEXT_DIM))
        if text:
            draw.text((SAFE_LEFT + 4, SAFE_BOT - 4), text, fill=color, font=self._font_sm)

    def _draw_response_text(self, draw, text):
        """Draw response text in the lower area — large, readable, no overlap."""
        x = SAFE_LEFT
        y_start = 180
        max_w = SAFE_RIGHT - SAFE_LEFT
        line_h = 18
        max_lines = 5  # fits between face and bottom safe zone

        try:
            font = self._font_md
        except:
            font = ImageFont.load_default()

        # Word wrap
        words = text.split()
        lines = []
        line = ""
        for w in words:
            test = f"{line} {w}".strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > max_w:
                if line:
                    lines.append(line)
                line = w
            else:
                line = test
        if line:
            lines.append(line)

        # Show last N lines (scrolled to bottom for long text)
        visible = lines[-max_lines:]

        # Dim background behind text for readability
        text_area_h = len(visible) * line_h + 8
        draw.rectangle([0, y_start - 4, WIDTH, y_start + text_area_h],
                        fill=(8, 8, 20))

        for i, ln in enumerate(visible):
            draw.text((x, y_start + i * line_h), ln, fill=TEXT_PRIMARY, font=font)

        # If text is truncated, show scroll indicator
        if len(lines) > max_lines:
            draw.text((SAFE_RIGHT - 20, y_start - 2), "...", fill=TEXT_DIM, font=self._font_sm)

    def _draw_wrapped_text(self, draw, text, x, y, max_w, font, color):
        """Generic word-wrap (kept for compatibility)."""
        words = text.split()
        lines = []
        line = ""
        for w in words:
            test = f"{line} {w}".strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > max_w:
                if line:
                    lines.append(line)
                line = w
            else:
                line = test
        if line:
            lines.append(line)
        visible = lines[-5:]
        for i, ln in enumerate(visible):
            draw.text((x, y + i * 17), ln, fill=color, font=font)

    def _send_to_display(self, img):
        """Convert PIL image to RGB565 and push to Whisplay LCD.

        Uses double-buffer comparison: only sends full frame when content
        actually changed. The WhisPlay SPI runs at 100MHz so a full 134KB
        frame takes ~1.1ms on the wire, but Python overhead in preparing
        the buffer is the real bottleneck. By caching the last buffer and
        doing a fast bytes comparison, we skip identical frames entirely.
        """
        try:
            import numpy as np
            arr = np.array(img, dtype=np.uint16)
            r = (arr[:, :, 0] & 0xF8) << 8
            g = (arr[:, :, 1] & 0xFC) << 3
            b = arr[:, :, 2] >> 3
            rgb565 = r | g | b
            data_hi = ((rgb565 >> 8) & 0xFF).astype(np.uint8)
            data_lo = (rgb565 & 0xFF).astype(np.uint8)
            buf = bytearray(len(data_hi.tobytes()) * 2)
            buf[0::2] = data_hi.tobytes()
            buf[1::2] = data_lo.tobytes()

            # Double-buffer: skip if frame is identical
            if hasattr(self, '_last_buf') and self._last_buf == buf:
                return
            self._last_buf = bytes(buf)

            # Send as bytes directly (avoid list() overhead on 134K items)
            self.board.set_window(0, 0, WIDTH - 1, HEIGHT - 1)
            self.board._send_data(buf)
        except ImportError:
            px = []
            for y in range(HEIGHT):
                for x in range(WIDTH):
                    r, g, b = img.getpixel((x, y))
                    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                    px.extend([(rgb565 >> 8) & 0xFF, rgb565 & 0xFF])
            self.board.draw_image(0, 0, WIDTH, HEIGHT, px)

    def cleanup(self):
        """Turn off display and LED."""
        self._running = False
        try:
            self.board.set_rgb(0, 0, 0)
            self.board.set_backlight(0)
            self.board.cleanup()
        except:
            pass

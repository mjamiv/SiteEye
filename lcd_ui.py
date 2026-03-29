#!/usr/bin/env python3
"""SiteEye v2 LCD UI — Cozmo-style color eyes on Whisplay 240×280 ST7789"""

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

# Eye geometry
EYE_Y = 100
LEFT_EYE_X = 72
RIGHT_EYE_X = 168
EYE_W = 36
EYE_H = 32
PUPIL_R = 10
CORNER_R = 9

# States
STATE_BOOT = "boot"
STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_THINKING = "thinking"
STATE_SPEAKING = "speaking"
STATE_CAMERA = "camera"
STATE_ERROR = "error"


class LcdUI:
    def __init__(self):
        self.board = WhisPlayBoard()
        self.board.set_backlight(70)
        self.state = STATE_BOOT
        self.response_text = ""
        self.status_text = ""
        self._running = True
        self._blink_timer = 0
        self._blink_amount = 0.0  # 0=open, 1=closed
        self._saccade_x = 0.0
        self._saccade_y = 0.0
        self._next_blink = time.time() + random.uniform(2, 5)
        self._next_saccade = time.time() + random.uniform(1, 3)
        self._anim_frame = 0
        self._lock = threading.Lock()

    def set_state(self, state, text=""):
        with self._lock:
            self.state = state
            if text:
                self.response_text = text
            self._anim_frame = 0

        # Set RGB LED based on state
        led_map = {
            STATE_IDLE: (0, 80, 0),
            STATE_LISTENING: (0, 50, 255),
            STATE_THINKING: (255, 200, 0),
            STATE_SPEAKING: (180, 0, 255),
            STATE_CAMERA: (255, 255, 255),
            STATE_ERROR: (255, 0, 0),
        }
        r, g, b = led_map.get(state, (0, 40, 0))
        try:
            self.board.set_rgb(r, g, b)
        except:
            pass

    def set_status(self, text):
        with self._lock:
            self.status_text = text

    def render_frame(self):
        """Render one frame and push to display."""
        img = Image.new('RGB', (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)

        with self._lock:
            state = self.state
            resp = self.response_text
            status = self.status_text
            self._anim_frame += 1

        now = time.time()

        # Auto-blink
        if now > self._next_blink:
            self._blink_amount = 1.0
            self._next_blink = now + random.uniform(2, 6)
        if self._blink_amount > 0:
            self._blink_amount = max(0, self._blink_amount - 0.15)

        # Auto-saccade (small eye movements)
        if now > self._next_saccade:
            self._saccade_x = random.uniform(-0.3, 0.3)
            self._saccade_y = random.uniform(-0.2, 0.2)
            self._next_saccade = now + random.uniform(1.5, 4)

        # Status bar
        try:
            font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        except:
            font_sm = ImageFont.load_default()

        if status:
            draw.text((5, 3), status, fill=TEXT_DIM, font=font_sm)

        # Draw eyes based on state
        if state == STATE_BOOT:
            self._draw_boot(draw)
        elif state == STATE_CAMERA:
            self._draw_camera_icon(draw)
        else:
            # Determine eye expression
            lid_top = 0.0
            lid_bot = 0.0
            pupil_ox = self._saccade_x
            pupil_oy = self._saccade_y
            accent = HIGHLIGHT

            if state == STATE_LISTENING:
                lid_top = -0.15  # eyes wider
                accent = BLUE_ACCENT
            elif state == STATE_THINKING:
                lid_top = 0.2  # slight squint
                pupil_ox = 0.3
                pupil_oy = -0.2
                accent = YELLOW_ACCENT
            elif state == STATE_SPEAKING:
                lid_top = 0.05
                accent = PURPLE_ACCENT
            elif state == STATE_ERROR:
                lid_top = 0.3
                accent = RED_ACCENT

            # Apply blink
            blink = self._blink_amount
            lid_top += blink * 0.5
            lid_bot += blink * 0.5

            self._draw_eye(draw, LEFT_EYE_X, EYE_Y, pupil_ox, pupil_oy, lid_top, lid_bot, accent)
            self._draw_eye(draw, RIGHT_EYE_X, EYE_Y, pupil_ox, pupil_oy, lid_top, lid_bot, accent)

        # State indicator dots
        if state == STATE_LISTENING:
            self._draw_pulse_dot(draw, 120, 155, BLUE_ACCENT, self._anim_frame)
        elif state == STATE_THINKING:
            self._draw_dots_anim(draw, 120, 155, YELLOW_ACCENT, self._anim_frame)
        elif state == STATE_SPEAKING:
            self._draw_wave(draw, 155, PURPLE_ACCENT, self._anim_frame)

        # Response text area
        if resp and state not in (STATE_BOOT, STATE_CAMERA):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
            except:
                font = ImageFont.load_default()
            self._draw_wrapped_text(draw, resp, 8, 175, WIDTH - 16, font, TEXT_PRIMARY)

        # Mode bar at bottom
        mode_text = {
            STATE_IDLE: "● Ready",
            STATE_LISTENING: "● Listening...",
            STATE_THINKING: "● Thinking...",
            STATE_SPEAKING: "● Speaking...",
            STATE_CAMERA: "● Camera",
            STATE_ERROR: "● Error",
        }.get(state, "")
        if mode_text:
            color = {
                STATE_IDLE: GREEN_ACCENT,
                STATE_LISTENING: BLUE_ACCENT,
                STATE_THINKING: YELLOW_ACCENT,
                STATE_SPEAKING: PURPLE_ACCENT,
                STATE_ERROR: RED_ACCENT,
            }.get(state, TEXT_DIM)
            draw.text((8, HEIGHT - 18), mode_text, fill=color, font=font_sm)

        # Push to display
        self._send_to_display(img)

    def _draw_eye(self, draw, cx, cy, pox, poy, lid_top, lid_bot, accent):
        """Draw one Cozmo-style eye."""
        x1 = cx - EYE_W
        y1 = cy - EYE_H
        x2 = cx + EYE_W
        y2 = cy + EYE_H

        # White eyeball
        draw.rounded_rectangle([x1, y1, x2, y2], radius=CORNER_R, fill=EYE_WHITE)

        # Pupil
        px = cx + int(pox * EYE_W * 0.4)
        py = cy + int(poy * EYE_H * 0.3)
        draw.ellipse([px - PUPIL_R, py - PUPIL_R, px + PUPIL_R, py + PUPIL_R], fill=PUPIL)

        # Highlight reflection
        hx = px - 4
        hy = py - 4
        draw.ellipse([hx - 3, hy - 3, hx + 3, hy + 3], fill=accent)

        # Eyelids (mask from top and bottom)
        if lid_top > 0:
            lid_y = y1 + int(lid_top * (EYE_H * 2))
            draw.rounded_rectangle([x1 - 1, y1 - 5, x2 + 1, min(lid_y, y2)], radius=CORNER_R, fill=BG)
        if lid_bot > 0:
            lid_y = y2 - int(lid_bot * (EYE_H * 2))
            draw.rounded_rectangle([x1 - 1, max(lid_y, y1), x2 + 1, y2 + 5], radius=CORNER_R, fill=BG)

    def _draw_boot(self, draw):
        """Boot screen."""
        try:
            font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            font_lg = ImageFont.load_default()
            font_sm = font_lg

        draw.text((60, 100), "SiteEye", fill=HIGHLIGHT, font=font_lg)
        draw.text((85, 135), "v2.0", fill=TEXT_DIM, font=font_sm)
        draw.text((55, 180), "🤖 Booting...", fill=TEXT_DIM, font=font_sm)

    def _draw_camera_icon(self, draw):
        """Camera capture indicator."""
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
        except:
            font = ImageFont.load_default()
        draw.text((90, 80), "📸", fill=TEXT_PRIMARY, font=font)

    def _draw_pulse_dot(self, draw, cx, cy, color, frame):
        """Pulsing dot for listening state."""
        r = 5 + int(3 * math.sin(frame * 0.2))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

    def _draw_dots_anim(self, draw, cx, cy, color, frame):
        """Animated thinking dots."""
        for i in range(3):
            x = cx - 15 + i * 15
            alpha = 1.0 if ((frame // 4) % 3) == i else 0.3
            c = tuple(int(v * alpha) for v in color)
            draw.ellipse([x - 3, cy - 3, x + 3, cy + 3], fill=c)

    def _draw_wave(self, draw, y, color, frame):
        """Speaking waveform visualization."""
        for x in range(20, WIDTH - 20, 4):
            h = int(6 * math.sin(x * 0.05 + frame * 0.3))
            draw.line([(x, y - h), (x, y + h)], fill=color, width=2)

    def _draw_wrapped_text(self, draw, text, x, y, max_w, font, color):
        """Word-wrap text in the lower area."""
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

        # Show max 5 lines (last 5 if more)
        visible = lines[-5:]
        for i, ln in enumerate(visible):
            draw.text((x, y + i * 17), ln, fill=color, font=font)

    def _send_to_display(self, img):
        """Convert PIL image to RGB565 and push to Whisplay LCD."""
        # Fast conversion using numpy if available
        try:
            import numpy as np
            arr = np.array(img, dtype=np.uint16)
            r = (arr[:, :, 0] & 0xF8) << 8
            g = (arr[:, :, 1] & 0xFC) << 3
            b = arr[:, :, 2] >> 3
            rgb565 = r | g | b
            # Convert to big-endian bytes
            data = ((rgb565 >> 8) & 0xFF).astype(np.uint8).tobytes()
            data2 = (rgb565 & 0xFF).astype(np.uint8).tobytes()
            # Interleave
            px = bytearray(len(data) * 2)
            px[0::2] = data
            px[1::2] = data2
            self.board.draw_image(0, 0, WIDTH, HEIGHT, list(px))
        except ImportError:
            # Fallback — slow Python pixel conversion
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

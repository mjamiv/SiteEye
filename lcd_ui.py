#!/usr/bin/env python3
"""SiteEye v2 LCD UI — Premium AI assistant face on Whisplay 240×280 ST7789

Pitch-ready design: dark navy theme, clean geometric face, smooth animations.
Apple Watch meets construction tech. Confident, minimal, professional.
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
CORNER_H = 20
SAFE_TOP = CORNER_H + 2
SAFE_BOT = HEIGHT - CORNER_H - 2
SAFE_LEFT = 12
SAFE_RIGHT = WIDTH - 12

# --- Color Palette: Black / White / Yellow-Gold ---
BG = (0, 0, 0)                  # Pure black
BG_PANEL = (12, 12, 12)         # Near-black panel
TEXT_PRIMARY = (255, 255, 255)   # Pure white
TEXT_DIM = (120, 120, 110)       # Warm gray
ACCENT = (255, 200, 40)         # Gold/yellow #FFC828
ACCENT_DIM = (140, 110, 20)     # Dimmed gold
ACCENT_BRIGHT = (255, 220, 80)  # Bright gold highlight

# Face colors
EYE_WHITE = (248, 248, 248)     # Clean white
EYE_EDGE = (210, 210, 210)      # Light gray edges
PUPIL_COLOR = (15, 15, 15)      # Near-black
PUPIL_CENTER = (5, 5, 5)        # True black center
HIGHLIGHT_DOT = (255, 255, 255) # Pure white reflection
MOUTH_LINE = (180, 180, 170)    # Light gray for closed mouth
MOUTH_FILL = (20, 20, 20)       # Dark fill for open mouth
MOUTH_OUTLINE = (150, 150, 140) # Warm gray outline

# Status colors
STATUS_GREEN = (80, 200, 80)
STATUS_RED = (220, 60, 60)
STATUS_YELLOW = ACCENT
STATUS_BLUE = (80, 160, 255)
SEPARATOR_COLOR = (40, 40, 35)

# Face geometry
EYE_Y = 112
LEFT_EYE_X = 75
RIGHT_EYE_X = 165
EYE_W = 34
EYE_H = 24
PUPIL_R = 9
EYE_CORNER_R = 8
MOUTH_Y = 165
MOUTH_CX = 120

# States
STATE_BOOT = "boot"
STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_THINKING = "thinking"
STATE_SPEAKING = "speaking"
STATE_CAMERA = "camera"
STATE_ERROR = "error"

# Frame timing
FRAME_INTERVAL = 1.0 / 6


class LcdUI:
    def __init__(self):
        self.board = WhisPlayBoard()
        self.board.set_backlight(75)
        self.state = STATE_BOOT
        self.response_text = ""
        self.status_text = ""
        self._running = True

        # Photo overlay state
        self._photo_img = None
        self._photo_text = ""

        # Animation state
        self._blink_amount = 0.0
        self._next_blink = time.time() + random.uniform(2.5, 5)
        self._saccade_x = 0.0
        self._saccade_y = 0.0
        self._saccade_target_x = 0.0
        self._saccade_target_y = 0.0
        self._next_saccade = time.time() + random.uniform(1, 3)
        self._anim_frame = 0
        self._mouth_open = 0.0
        self._target_mouth = 0.0
        self._lid_squint = 0.0
        self._target_squint = 0.0
        self._pupil_size = 1.0
        self._target_pupil = 1.0
        self._breathing_phase = 0.0
        self._boot_start = time.time()
        self._lock = threading.Lock()
        self._last_buf = None

        # Font cache
        try:
            # Roboto Condensed — industrial narrow font (closest to Acumin Narrow Pro)
            # Falls back to DejaVu Sans Condensed if Roboto not installed
            import os as _os
            rc = "/usr/share/fonts/truetype/roboto/unhinted/RobotoCondensed-Regular.ttf"
            rcb = "/usr/share/fonts/truetype/roboto/unhinted/RobotoCondensed-Bold.ttf"
            if not _os.path.exists(rc):
                rc = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"
                rcb = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
            mono = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
            self._font_sm = ImageFont.truetype(rc, 14)
            self._font_md = ImageFont.truetype(rc, 15)
            self._font_lg = ImageFont.truetype(rcb, 24)
            self._font_mono = ImageFont.truetype(rcb, 40)     # Boot title
            self._font_sub = ImageFont.truetype(rc, 12)
            self._font_check = ImageFont.truetype(mono, 12)
        except Exception:
            self._font_sm = ImageFont.load_default()
            self._font_md = self._font_sm
            self._font_lg = self._font_sm
            self._font_mono = self._font_sm
            self._font_sub = self._font_sm
            self._font_check = self._font_sm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_state(self, state, text=""):
        with self._lock:
            prev = self.state
            self.state = state
            if text:
                self.response_text = text
            self._anim_frame = 0
            if state == STATE_BOOT:
                self._boot_start = time.time()

        # Expression targets per state
        if state == STATE_IDLE:
            self._target_squint = 0.0
            self._target_mouth = 0.0
            self._target_pupil = 1.0
        elif state == STATE_LISTENING:
            self._target_squint = -0.12  # eyes slightly wider
            self._target_mouth = 0.0
            self._target_pupil = 1.15
        elif state == STATE_THINKING:
            self._target_squint = 0.08
            self._target_mouth = 0.0
            self._target_pupil = 0.85
        elif state == STATE_SPEAKING:
            self._target_squint = 0.0
            self._target_pupil = 1.0
        elif state == STATE_CAMERA:
            self._target_squint = -0.1
            self._target_mouth = 0.0
            self._target_pupil = 0.8
        elif state == STATE_ERROR:
            self._target_squint = 0.15
            self._target_mouth = 0.0
            self._target_pupil = 0.9

        # RGB LED (muted, professional)
        led_map = {
            STATE_IDLE: (40, 30, 0),       # Warm gold dim
            STATE_LISTENING: (60, 50, 0),   # Gold
            STATE_THINKING: (80, 60, 0),    # Bright gold
            STATE_SPEAKING: (50, 40, 0),    # Gold
            STATE_CAMERA: (60, 60, 60),     # White
            STATE_ERROR: (80, 15, 15),      # Red
            STATE_BOOT: (30, 25, 0),        # Dim gold
        }
        r, g, b = led_map.get(state, (30, 25, 0))
        try:
            self.board.set_rgb(r, g, b)
        except Exception:
            pass

    def set_status(self, text):
        with self._lock:
            self.status_text = text

    def render_frame(self):
        """Render one frame and push to display."""
        if self._photo_img is not None:
            self._render_photo_frame()
            return

        img = Image.new('RGB', (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)

        with self._lock:
            state = self.state
            resp = self.response_text
            status = self.status_text
            self._anim_frame += 1

        self._update_animation(state)

        if state == STATE_BOOT:
            self._draw_boot(draw)
        elif state == STATE_CAMERA:
            self._draw_camera_screen(draw)
        else:
            # Status bar
            self._draw_status_bar(draw, state, status)

            # Eyes
            self._draw_eye(draw, LEFT_EYE_X, EYE_Y)
            self._draw_eye(draw, RIGHT_EYE_X, EYE_Y)

            # Mouth
            self._draw_mouth(draw, state)

            # State-specific indicators
            if state == STATE_LISTENING:
                self._draw_listening_ring(draw)
            elif state == STATE_THINKING:
                self._draw_thinking_dots(draw)
            elif state == STATE_SPEAKING:
                self._draw_speaking_pulse(draw)

            # Response text OR idle hint
            if resp:
                self._draw_response_text(draw, resp)
            elif state == STATE_IDLE:
                self._draw_idle_hint(draw)

        self._send_to_display(img)

    def show_live_frame(self, frame_array):
        """Display a live camera frame (numpy RGB array) on the LCD with viewfinder overlay."""
        try:
            import numpy as np
            from PIL import Image as PILImage

            img = PILImage.fromarray(frame_array).resize((WIDTH, HEIGHT), PILImage.NEAREST)
            draw = ImageDraw.Draw(img)

            # Viewfinder crosshair overlay
            cx, cy = WIDTH // 2, HEIGHT // 2
            line_len = 18
            gap = 8
            crosshair_color = (200, 220, 240, 180)
            # Horizontal
            draw.line([(cx - line_len - gap, cy), (cx - gap, cy)], fill=(200, 220, 240), width=1)
            draw.line([(cx + gap, cy), (cx + line_len + gap, cy)], fill=(200, 220, 240), width=1)
            # Vertical
            draw.line([(cx, cy - line_len - gap), (cx, cy - gap)], fill=(200, 220, 240), width=1)
            draw.line([(cx, cy + gap), (cx, cy + line_len + gap)], fill=(200, 220, 240), width=1)

            # Corner brackets
            blen = 15
            bw = 2
            for bx, by, dx, dy in [(0, 0, 1, 1), (WIDTH, 0, -1, 1),
                                     (0, HEIGHT, 1, -1), (WIDTH, HEIGHT, -1, -1)]:
                x0 = bx + (4 * dx)
                y0 = by + (4 * dy)
                draw.line([(x0, y0), (x0 + blen * dx, y0)], fill=ACCENT, width=bw)
                draw.line([(x0, y0), (x0, y0 + blen * dy)], fill=ACCENT, width=bw)

            # "Press to capture" at bottom
            hint = "Press to capture"
            bbox = draw.textbbox((0, 0), hint, font=self._font_md)
            tw = bbox[2] - bbox[0]
            # Dark backing for readability
            draw.rectangle([0, HEIGHT - 24, WIDTH, HEIGHT], fill=(0, 0, 0))
            draw.text(((WIDTH - tw) // 2, HEIGHT - 22), hint, fill=TEXT_PRIMARY, font=self._font_md)

            # Send directly — bypass double-buffer (live feed always changes)
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
            self.board.set_window(0, 0, WIDTH - 1, HEIGHT - 1)
            self.board._send_data(buf)
            self._last_buf = None  # Invalidate double-buffer cache
        except Exception as e:
            pass

    def show_captured_image(self, img_path):
        """Load captured photo for display during analysis/response."""
        try:
            from PIL import Image as PILImage
            photo = PILImage.open(img_path).convert('RGB')
            display_h = 170
            photo_ratio = photo.width / photo.height
            display_ratio = WIDTH / display_h
            if photo_ratio > display_ratio:
                new_h = display_h
                new_w = int(display_h * photo_ratio)
            else:
                new_w = WIDTH
                new_h = int(WIDTH / photo_ratio)
            photo = photo.resize((new_w, new_h), PILImage.LANCZOS)
            left = (new_w - WIDTH) // 2
            top = (new_h - display_h) // 2
            self._photo_img = photo.crop((left, top, left + WIDTH, top + display_h))
            self._photo_text = "Analyzing..."
            self._last_buf = None
        except Exception:
            pass

    def set_photo_text(self, text):
        self._photo_text = text
        self._last_buf = None

    def clear_photo(self):
        self._photo_img = None
        self._photo_text = ""
        self._last_buf = None

    def cleanup(self):
        self._running = False
        try:
            self.board.set_rgb(0, 0, 0)
            self.board.set_backlight(0)
            self.board.cleanup()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Animation engine
    # ------------------------------------------------------------------

    def _lerp(self, current, target, speed=0.15):
        return current + (target - current) * speed

    def _update_animation(self, state):
        now = time.time()

        # Smooth expression transitions
        self._lid_squint = self._lerp(self._lid_squint, self._target_squint, 0.12)
        self._pupil_size = self._lerp(self._pupil_size, self._target_pupil, 0.1)
        self._mouth_open = self._lerp(self._mouth_open, self._target_mouth, 0.18)

        # Saccade interpolation (smooth eye movement)
        self._saccade_x = self._lerp(self._saccade_x, self._saccade_target_x, 0.12)
        self._saccade_y = self._lerp(self._saccade_y, self._saccade_target_y, 0.12)

        # Speaking mouth animation
        if state == STATE_SPEAKING:
            t = self._anim_frame * 0.15
            self._target_mouth = 0.1 + 0.3 * abs(math.sin(t * 2.5)) * abs(math.sin(t * 1.1))

        # Auto-blink
        if now > self._next_blink:
            self._blink_amount = 1.0
            self._next_blink = now + random.uniform(2.5, 6.0)
            if random.random() < 0.15:
                self._next_blink = now + 0.3  # double blink
        if self._blink_amount > 0:
            self._blink_amount = max(0, self._blink_amount - 0.2)

        # Saccade targets (small, subtle)
        if now > self._next_saccade:
            if state == STATE_THINKING:
                self._saccade_target_x = random.uniform(0.1, 0.25)
                self._saccade_target_y = random.uniform(-0.2, -0.05)
            elif state == STATE_LISTENING:
                self._saccade_target_x = random.uniform(-0.08, 0.08)
                self._saccade_target_y = random.uniform(-0.02, 0.1)
            else:
                self._saccade_target_x = random.uniform(-0.15, 0.15)
                self._saccade_target_y = random.uniform(-0.1, 0.1)
            self._next_saccade = now + random.uniform(1.2, 3.5)

        # Breathing phase (for idle highlight animation)
        self._breathing_phase += 0.04

    # ------------------------------------------------------------------
    # Drawing: Boot sequence
    # ------------------------------------------------------------------

    def _draw_boot(self, draw):
        frame = self._anim_frame

        # Phase 1 (frames 1-5): "SITEEYE" fades in
        if frame <= 5:
            alpha = min(1.0, frame / 5.0)
            c = self._fade_color(TEXT_PRIMARY, alpha)
            # Center "SITEEYE" monospace bold
            text = "SITEEYE"
            bbox = draw.textbbox((0, 0), text, font=self._font_mono)
            tw = bbox[2] - bbox[0]
            tx = (WIDTH - tw) // 2
            draw.text((tx, 95), text, fill=c, font=self._font_mono)

        # Phase 2 (frames 6-15): Title stays + progress bar fills
        elif frame <= 15:
            # Title fully visible
            text = "SITEEYE"
            bbox = draw.textbbox((0, 0), text, font=self._font_mono)
            tw = bbox[2] - bbox[0]
            tx = (WIDTH - tw) // 2
            draw.text((tx, 95), text, fill=TEXT_PRIMARY, font=self._font_mono)

            # Progress bar
            bar_w = 160
            bar_h = 3
            bar_x = (WIDTH - bar_w) // 2
            bar_y = 145
            progress = (frame - 5) / 10.0
            # Bar track
            draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                                   radius=1, fill=(25, 35, 50))
            # Bar fill
            fill_w = int(bar_w * progress)
            if fill_w > 2:
                draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h],
                                       radius=1, fill=ACCENT)

        # Phase 3 (frames 16-25): Subtitle fades in, bar complete
        elif frame <= 25:
            # Title
            text = "SITEEYE"
            bbox = draw.textbbox((0, 0), text, font=self._font_mono)
            tw = bbox[2] - bbox[0]
            tx = (WIDTH - tw) // 2
            draw.text((tx, 95), text, fill=TEXT_PRIMARY, font=self._font_mono)

            # Full progress bar
            bar_w = 160
            bar_h = 3
            bar_x = (WIDTH - bar_w) // 2
            bar_y = 145
            draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                                   radius=1, fill=ACCENT)

            # Subtitle fading in
            sub_alpha = min(1.0, (frame - 15) / 8.0)
            sub_c = self._fade_color(TEXT_DIM, sub_alpha)
            sub_text = "v2.0 | AI-POWERED FIELD ASSISTANT"
            bbox2 = draw.textbbox((0, 0), sub_text, font=self._font_sub)
            sw = bbox2[2] - bbox2[0]
            sx = (WIDTH - sw) // 2
            draw.text((sx, 160), sub_text, fill=sub_c, font=self._font_sub)

        # Phase 4 (frames 26-40): System checks appear sequentially
        else:
            # Title
            text = "SITEEYE"
            bbox = draw.textbbox((0, 0), text, font=self._font_mono)
            tw = bbox[2] - bbox[0]
            tx = (WIDTH - tw) // 2
            draw.text((tx, 95), text, fill=TEXT_PRIMARY, font=self._font_mono)

            # Full progress bar
            bar_w = 160
            bar_h = 3
            bar_x = (WIDTH - bar_w) // 2
            bar_y = 145
            draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                                   radius=1, fill=ACCENT)

            # Subtitle fully visible
            sub_text = "v2.0 | AI-POWERED FIELD ASSISTANT"
            bbox2 = draw.textbbox((0, 0), sub_text, font=self._font_sub)
            sw = bbox2[2] - bbox2[0]
            sx = (WIDTH - sw) // 2
            draw.text((sx, 160), sub_text, fill=TEXT_DIM, font=self._font_sub)

            # System checks (each appears 3 frames apart)
            checks = [
                ("Camera", 26),
                ("Audio", 30),
                ("Network", 34),
            ]
            check_y = 185
            for i, (label, appear_frame) in enumerate(checks):
                if frame >= appear_frame:
                    alpha = min(1.0, (frame - appear_frame) / 3.0)
                    c = self._fade_color(STATUS_GREEN, alpha)
                    tc = self._fade_color(TEXT_DIM, alpha)
                    check_text = f"  {label}"
                    # Checkmark
                    cx = 60
                    ty = check_y + i * 16
                    draw.text((cx, ty), "\u2713", fill=c, font=self._font_check)
                    draw.text((cx + 14, ty), label, fill=tc, font=self._font_check)

    # ------------------------------------------------------------------
    # Drawing: Status bar
    # ------------------------------------------------------------------

    def _draw_status_bar(self, draw, state, status):
        y = SAFE_TOP + 1

        # Status dot (left side) — bigger for visibility
        dot_x = SAFE_LEFT + 8
        dot_y = y + 7
        dot_r = 4
        if state == STATE_ERROR:
            dot_color = STATUS_RED
        elif state in (STATE_THINKING, STATE_CAMERA):
            dot_color = STATUS_YELLOW
        elif state in (STATE_LISTENING, STATE_SPEAKING):
            dot_color = STATUS_BLUE
        else:
            dot_color = STATUS_GREEN
        draw.ellipse([dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r],
                     fill=dot_color)

        # Status text next to dot — brighter for readability
        if status:
            draw.text((dot_x + dot_r + 6, y), status, fill=TEXT_PRIMARY, font=self._font_sm)

        # "SiteEye" wordmark (right side)
        mark = "SiteEye"
        bbox = draw.textbbox((0, 0), mark, font=self._font_sm)
        mw = bbox[2] - bbox[0]
        draw.text((SAFE_RIGHT - mw - 4, y), mark, fill=ACCENT, font=self._font_sm)

        # Separator line
        sep_y = y + 18
        draw.line([(SAFE_LEFT, sep_y), (SAFE_RIGHT, sep_y)], fill=SEPARATOR_COLOR, width=1)

    # ------------------------------------------------------------------
    # Drawing: Eyes
    # ------------------------------------------------------------------

    def _draw_eye(self, draw, cx, cy):
        w = EYE_W
        h = int(EYE_H * (1.0 - abs(self._lid_squint) * 0.25))
        if self._lid_squint < 0:
            h = int(EYE_H * (1.0 - self._lid_squint * 0.2))

        x1 = cx - w
        y1 = cy - h
        x2 = cx + w
        y2 = cy + h

        # Eye shape — rounded rectangle with subtle edge gradient
        # Outer slightly gray
        draw.rounded_rectangle([x1 - 1, y1 - 1, x2 + 1, y2 + 1],
                               radius=EYE_CORNER_R + 1, fill=EYE_EDGE)
        # Inner white fill
        draw.rounded_rectangle([x1, y1, x2, y2],
                               radius=EYE_CORNER_R, fill=EYE_WHITE)

        # Pupil
        pr = int(PUPIL_R * self._pupil_size)
        px = cx + int(self._saccade_x * w * 0.35)
        py = cy + int(self._saccade_y * h * 0.3)
        draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=PUPIL_COLOR)

        # Darker center
        ipr = max(2, pr // 2)
        draw.ellipse([px - ipr, py - ipr, px + ipr, py + ipr], fill=PUPIL_CENTER)

        # Single bright highlight dot
        hx = px - 3
        hy = py - 3
        # Breathing animation for idle — highlight subtly pulses
        hr = 2
        if self.state == STATE_IDLE:
            breath = 0.8 + 0.2 * math.sin(self._breathing_phase)
            hr = max(1, int(2 * breath))
        draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=HIGHLIGHT_DOT)

        # Eyelid masking (blink)
        blink = self._blink_amount
        top_close = max(0, max(self._lid_squint, 0) * 0.4 + blink * 0.5)
        bot_close = max(0, blink * 0.4)

        if top_close > 0:
            lid_y = y1 + int(top_close * (h * 2))
            draw.rounded_rectangle([x1 - 3, y1 - 8, x2 + 3, min(lid_y, y2)],
                                   radius=EYE_CORNER_R + 2, fill=BG)
        if bot_close > 0:
            lid_y = y2 - int(bot_close * (h * 2))
            draw.rounded_rectangle([x1 - 3, max(lid_y, y1), x2 + 3, y2 + 8],
                                   radius=EYE_CORNER_R + 2, fill=BG)

    # ------------------------------------------------------------------
    # Drawing: Mouth
    # ------------------------------------------------------------------

    def _draw_mouth(self, draw, state):
        cx = MOUTH_CX
        cy = MOUTH_Y
        mouth_w = 22
        open_h = int(self._mouth_open * 14)

        if self._mouth_open < 0.06:
            # Closed — subtle smile curve
            pts = []
            for i in range(21):
                t = i / 20.0
                x = cx - mouth_w + int(t * mouth_w * 2)
                progress = (t - 0.5) * 2
                # Gentle upward curve
                curve = 3.0 * (1 - progress ** 2)
                y = cy - int(curve)
                pts.append((x, y))
            if len(pts) > 1:
                draw.line(pts, fill=MOUTH_LINE, width=2)
        else:
            # Open — clean oval/pill shape
            ow = mouth_w + int(self._mouth_open * 8)
            oh = max(4, open_h)
            top_y = cy - oh // 3
            bot_y = cy + oh * 2 // 3

            # Pill shape
            bbox = [cx - ow, top_y, cx + ow, bot_y]
            draw.rounded_rectangle(bbox, radius=ow // 2, fill=MOUTH_FILL)
            draw.rounded_rectangle(bbox, radius=ow // 2, outline=MOUTH_OUTLINE, width=1)

    # ------------------------------------------------------------------
    # Drawing: State indicators
    # ------------------------------------------------------------------

    def _draw_listening_ring(self, draw):
        """Subtle pulsing audio bars below face — clean, no floating bubbles."""
        frame = self._anim_frame
        y = 182
        cx = 120
        # 5 small bars, centered, pulsing at different phases
        bar_w = 3
        bar_gap = 6
        n_bars = 5
        total_w = n_bars * bar_w + (n_bars - 1) * bar_gap
        start_x = cx - total_w // 2
        for i in range(n_bars):
            x = start_x + i * (bar_w + bar_gap)
            h = 3 + int(5 * abs(math.sin(frame * 0.2 + i * 0.9)))
            brightness = 0.4 + 0.6 * abs(math.sin(frame * 0.15 + i * 0.7))
            c = tuple(int(v * brightness) for v in ACCENT)
            draw.rectangle([x, y - h, x + bar_w, y + h], fill=c)

    def _draw_thinking_dots(self, draw):
        """Animated dots below face (...)."""
        y = 190
        frame = self._anim_frame
        for i in range(3):
            x = 108 + i * 12
            # Bounce animation offset per dot
            bounce = math.sin((frame * 0.2) - i * 0.8)
            dy = int(bounce * 3) if bounce > 0 else 0
            # Fade cycle
            brightness = 0.3 + 0.7 * max(0, math.sin((frame * 0.2) - i * 0.8))
            c = tuple(int(v * brightness) for v in ACCENT)
            r = 3
            draw.ellipse([x - r, y - r - dy, x + r, y + r - dy], fill=c)

    def _draw_speaking_pulse(self, draw):
        """Subtle waveform pulse below face."""
        y = 190
        frame = self._anim_frame
        cx = 120
        wave_w = 50
        for i in range(wave_w):
            x = cx - wave_w // 2 + i
            # Sine wave with mouth-sync amplitude
            amp = self._mouth_open * 4
            val = amp * math.sin(i * 0.3 + frame * 0.3)
            brightness = 0.3 + 0.4 * abs(math.sin(i * 0.15 + frame * 0.1))
            c = tuple(int(v * brightness) for v in ACCENT)
            if abs(val) > 0.5:
                h = max(1, int(abs(val)))
                draw.line([(x, y - h), (x, y + h)], fill=c, width=1)

    # ------------------------------------------------------------------
    # Drawing: Camera screen
    # ------------------------------------------------------------------

    def _draw_camera_screen(self, draw):
        frame = self._anim_frame

        # Clean viewfinder overlay
        # Crosshair
        cx, cy = 120, 120
        line_len = 20
        gap = 8
        c = ACCENT_DIM

        # Horizontal crosshair
        draw.line([(cx - line_len - gap, cy), (cx - gap, cy)], fill=c, width=1)
        draw.line([(cx + gap, cy), (cx + line_len + gap, cy)], fill=c, width=1)
        # Vertical crosshair
        draw.line([(cx, cy - line_len - gap), (cx, cy - gap)], fill=c, width=1)
        draw.line([(cx, cy + gap), (cx, cy + line_len + gap)], fill=c, width=1)

        # Corner brackets
        bracket_len = 18
        bracket_inset = 35
        corners = [
            (cx - bracket_inset, cy - bracket_inset, 1, 1),
            (cx + bracket_inset, cy - bracket_inset, -1, 1),
            (cx - bracket_inset, cy + bracket_inset, 1, -1),
            (cx + bracket_inset, cy + bracket_inset, -1, -1),
        ]
        for bx, by, dx, dy in corners:
            draw.line([(bx, by), (bx + bracket_len * dx, by)], fill=ACCENT, width=2)
            draw.line([(bx, by), (bx, by + bracket_len * dy)], fill=ACCENT, width=2)

        # "Capturing..." text
        text = "Capturing..."
        bbox = draw.textbbox((0, 0), text, font=self._font_md)
        tw = bbox[2] - bbox[0]
        draw.text(((WIDTH - tw) // 2, 195), text, fill=TEXT_DIM, font=self._font_md)

    # ------------------------------------------------------------------
    # Drawing: Response text
    # ------------------------------------------------------------------

    def _draw_idle_hint(self, draw):
        """Show button usage hint at bottom when idle."""
        hints = [
            "Tap → Voice",
            "Hold → Camera",
        ]
        idx = int(time.time() / 4) % len(hints)
        hint = hints[idx]

        # Centered, readable, uses medium font
        bbox = draw.textbbox((0, 0), hint, font=self._font_md)
        tw = bbox[2] - bbox[0]
        tx = (WIDTH - tw) // 2
        draw.text((tx, SAFE_BOT - 8), hint, fill=TEXT_DIM, font=self._font_md)

    def _draw_response_text(self, draw, text):
        panel_x = SAFE_LEFT + 2
        panel_x2 = SAFE_RIGHT - 2
        y_start = 195
        panel_y2 = SAFE_BOT
        line_h = 16
        max_lines = 5
        font = self._font_md

        # Dark panel with rounded corners
        draw.rounded_rectangle([panel_x, y_start - 4, panel_x2, panel_y2],
                               radius=6, fill=BG_PANEL)

        # Word wrap
        max_w = panel_x2 - panel_x - 12
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

        visible = lines[-max_lines:]
        text_x = panel_x + 6
        text_y = y_start + 2

        for i, ln in enumerate(visible):
            draw.text((text_x, text_y + i * line_h), ln, fill=TEXT_PRIMARY, font=font)

        # Scroll indicator if truncated
        if len(lines) > max_lines:
            # Small up arrow or dots
            draw.text((panel_x2 - 14, y_start), "\u2191", fill=TEXT_DIM, font=self._font_sm)

    # ------------------------------------------------------------------
    # Drawing: Photo mode
    # ------------------------------------------------------------------

    def _render_photo_frame(self):
        img = Image.new('RGB', (WIDTH, HEIGHT), BG)

        if self._photo_img is not None:
            img.paste(self._photo_img, (0, 0))

        draw = ImageDraw.Draw(img)
        photo_h = 170

        # Accent border around photo
        draw.rectangle([0, 0, WIDTH - 1, photo_h - 1], outline=ACCENT_DIM, width=1)

        # Dark panel below photo
        draw.rounded_rectangle([4, photo_h + 2, WIDTH - 4, HEIGHT - 4],
                               radius=6, fill=BG_PANEL)

        text = self._photo_text
        if text:
            max_w = SAFE_RIGHT - SAFE_LEFT - 8
            y_start = photo_h + 8
            line_h = 16
            max_lines = 6
            font = self._font_md

            # Check for "Analyzing..." to add animated dots
            if text == "Analyzing...":
                dots = "." * (1 + (self._anim_frame // 4) % 3)
                text = "Analyzing" + dots

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

            visible = lines[-max_lines:]
            for i, ln in enumerate(visible):
                draw.text((SAFE_LEFT + 4, y_start + i * line_h), ln,
                          fill=TEXT_PRIMARY, font=font)

        self._send_to_display(img)

    # ------------------------------------------------------------------
    # Display output
    # ------------------------------------------------------------------

    def _send_to_display(self, img):
        """Convert PIL image to RGB565 and push via SPI."""
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

            if hasattr(self, '_last_buf') and self._last_buf == buf:
                return
            self._last_buf = bytes(buf)

            self.board.set_window(0, 0, WIDTH - 1, HEIGHT - 1)
            self.board._send_data(buf)
        except ImportError:
            px = []
            for y in range(HEIGHT):
                for x in range(WIDTH):
                    rv, gv, bv = img.getpixel((x, y))
                    rgb565 = ((rv & 0xF8) << 8) | ((gv & 0xFC) << 3) | (bv >> 3)
                    px.extend([(rgb565 >> 8) & 0xFF, rgb565 & 0xFF])
            self.board.draw_image(0, 0, WIDTH, HEIGHT, px)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fade_color(self, color, alpha):
        """Apply alpha fade to a color tuple (against black background)."""
        return tuple(int(v * max(0.0, min(1.0, alpha))) for v in color)

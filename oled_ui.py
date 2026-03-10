#!/usr/bin/env python3
"""SiteEye OLED UI v3 — Cozmo-style filled rounded rectangle eyes."""

from luma.core.interface.serial import spi
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont
import time, threading, random, math


def ease_in_out(t):
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


class OledUI:
    def __init__(self):
        serial = spi(device=0, port=0, gpio_DC=24, gpio_RST=25, bus_speed_hz=500000)
        self.device = sh1106(serial, width=128, height=64, rotate=2)
        self.device.contrast(255)
        self.W, self.H = 128, 64
        self._lock = threading.Lock()
        self._alive = True
        self._animating = False
        # Smooth pupil tracking
        self._pupil_x, self._pupil_y = 0.0, 0.0
        self._target_x, self._target_y = 0.0, 0.0
        # Eye state
        self._lid_top = 0.0  # 0 = open, 1 = fully closed from top
        self._lid_bot = 0.0  # 0 = open, 1 = fully closed from bottom
        try:
            self.font = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 10)
            self.font_sm = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 8)
        except Exception:
            self.font = ImageFont.load_default()
            self.font_sm = self.font

    def _frame(self):
        return Image.new('1', (self.W, self.H), 0)

    def _show(self, img):
        with self._lock:
            if self._alive:
                self.device.display(img)

    def _update_pupils(self, speed=0.15):
        self._pupil_x = lerp(self._pupil_x, self._target_x, speed)
        self._pupil_y = lerp(self._pupil_y, self._target_y, speed)

    def _draw_eyes(self, draw, lid_top=0.0, lid_bot=0.0, wide=False,
                   happy=False, angry=False, sad=False, suspicious=False,
                   brow_raise=0.0, brow_furrow=False, confused=False):
        """Cozmo-style filled rounded rectangle eyes with lid masking.

        lid_top: 0.0 (open) to 1.0 (closed from top)
        lid_bot: 0.0 (open) to 1.0 (closed from bottom)
        """
        # Eye centers and base dimensions
        lc, rc = 34, 94
        cy = 26
        base_w = 22 if wide else 20
        base_h = 20 if wide else 17
        corner_r = 5

        # Asymmetric scaling based on look direction
        l_scale = 1.0 - self._pupil_x * 0.15  # left eye shrinks when looking right
        r_scale = 1.0 + self._pupil_x * 0.15  # right eye grows when looking right

        for i, (ex, scale) in enumerate([(lc, l_scale), (rc, r_scale)]):
            ew = int(base_w * scale)
            eh = int(base_h * scale)

            # Eye bounding box
            x1 = ex - ew
            y1 = cy - eh
            x2 = ex + ew
            y2 = cy + eh

            # Total closed check
            total_lid = lid_top + lid_bot
            if total_lid >= 1.8:
                # Fully closed — draw a line
                line_y = cy + int((lid_bot - lid_top) * 3)
                draw.line([(x1 + 2, line_y), (x2 - 2, line_y)], fill=1, width=2)
                continue

            # Draw filled white rounded rectangle (the eyeball)
            draw.rounded_rectangle([x1, y1, x2, y2], radius=corner_r, fill=1)

            # Pupil position
            px = ex + int(self._pupil_x * ew * 0.35)
            py = cy + int(self._pupil_y * eh * 0.3)
            pupil_r = int(6 * scale) if wide else int(5 * scale)

            # Draw pupil (black circle on white eye)
            draw.ellipse((px - pupil_r, py - pupil_r,
                          px + pupil_r, py + pupil_r), fill=0)

            # Highlight reflection (white dot on pupil)
            hr = max(1, pupil_r // 3)
            hx = px - pupil_r // 2 + 1
            hy = py - pupil_r // 2
            draw.ellipse((hx, hy, hx + hr, hy + hr), fill=1)

            # === LID MASKING ===
            # Top lid (black rect covering from top)
            if lid_top > 0.02:
                lid_h = int(eh * 2 * lid_top)
                # Angry: angled lids
                if angry:
                    pts = []
                    if i == 0:  # left eye — angry slopes down-right
                        pts = [(x1 - 2, y1 - 2), (x2 + 2, y1 - 2),
                               (x2 + 2, y1 + lid_h + 4),
                               (x1 - 2, y1 + lid_h - 2)]
                    else:  # right eye — angry slopes down-left
                        pts = [(x1 - 2, y1 - 2), (x2 + 2, y1 - 2),
                               (x2 + 2, y1 + lid_h - 2),
                               (x1 - 2, y1 + lid_h + 4)]
                    draw.polygon(pts, fill=0)
                elif suspicious:
                    # One eye more closed than the other
                    extra = 4 if i == 1 else 0
                    draw.rectangle([x1 - 2, y1 - 2, x2 + 2, y1 + lid_h + extra],
                                   fill=0)
                else:
                    draw.rectangle([x1 - 2, y1 - 2, x2 + 2, y1 + lid_h], fill=0)

            # Bottom lid
            if lid_bot > 0.02:
                lid_h = int(eh * 2 * lid_bot)
                if happy:
                    # Happy: curved bottom lid (arc upward)
                    arc_y = y2 - lid_h
                    draw.pieslice([x1 - 2, arc_y - lid_h,
                                   x2 + 2, y2 + lid_h + 4],
                                  start=0, end=180, fill=0)
                elif sad:
                    # Sad: angled bottom (opposite of angry)
                    if i == 0:
                        pts = [(x1 - 2, y2 - lid_h + 4),
                               (x2 + 2, y2 - lid_h),
                               (x2 + 2, y2 + 4), (x1 - 2, y2 + 4)]
                    else:
                        pts = [(x1 - 2, y2 - lid_h),
                               (x2 + 2, y2 - lid_h + 4),
                               (x2 + 2, y2 + 4), (x1 - 2, y2 + 4)]
                    draw.polygon(pts, fill=0)
                else:
                    draw.rectangle([x1 - 2, y2 - lid_h, x2 + 2, y2 + 4], fill=0)

            # === EYEBROWS ===
            brow_y = y1 - 3 - int(brow_raise * 6)
            if brow_furrow or angry:
                # Angled inward brows
                if i == 0:
                    draw.line([(x1 + 2, brow_y - 2), (x2 - 2, brow_y + 3)],
                              fill=1, width=2)
                else:
                    draw.line([(x1 + 2, brow_y + 3), (x2 - 2, brow_y - 2)],
                              fill=1, width=2)
            elif sad:
                # Sad brows — angled outward (opposite of angry)
                if i == 0:
                    draw.line([(x1 + 2, brow_y + 3), (x2 - 2, brow_y - 1)],
                              fill=1, width=2)
                else:
                    draw.line([(x1 + 2, brow_y - 1), (x2 - 2, brow_y + 3)],
                              fill=1, width=2)
            elif confused:
                # One brow up, one down
                if i == 0:
                    draw.line([(x1 + 4, brow_y), (x2 - 4, brow_y - 4)],
                              fill=1, width=2)
                else:
                    draw.line([(x1 + 4, brow_y + 2), (x2 - 4, brow_y + 2)],
                              fill=1, width=2)
            elif brow_raise > 0.1:
                draw.arc((x1 + 4, brow_y - 3, x2 - 4, brow_y + 5),
                         200, 340, fill=1, width=2)

    # ─── Animations ───

    def boot_animation(self):
        """Power-on: eyes open from closed with look-around."""
        self._animating = True
        # Open from fully closed
        for step in range(15):
            t = ease_in_out(step / 14)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid_top=1.0 - t, brow_raise=t * 0.3)
            self._show(img)
            time.sleep(0.04)
        # Quick saccade look-around
        for tx, ty in [(0.7, 0), (-0.7, 0), (0, -0.4), (0, 0)]:
            self._target_x, self._target_y = tx, ty
            # Fast saccade — snap most of the way instantly
            self._pupil_x = lerp(self._pupil_x, tx, 0.7)
            self._pupil_y = lerp(self._pupil_y, ty, 0.7)
            for _ in range(6):
                self._update_pupils(0.4)
                img = self._frame()
                draw = ImageDraw.Draw(img)
                self._draw_eyes(draw, brow_raise=0.3)
                self._show(img)
                time.sleep(0.04)
        time.sleep(0.2)

    def eyes_idle(self, duration=3600):
        """Animated idle with blinks, saccades, and micro-expressions."""
        self._animating = True
        end = time.time() + duration
        next_look = time.time() + random.uniform(1.5, 3)
        next_blink = time.time() + random.uniform(2, 5)
        next_expr = time.time() + random.uniform(6, 12)
        expression = None
        expr_end = 0
        use_saccade = False

        while self._alive and self._animating and time.time() < end:
            now = time.time()

            # Look direction changes
            if now > next_look:
                self._target_x = random.uniform(-0.8, 0.8)
                self._target_y = random.uniform(-0.3, 0.3)
                if random.random() < 0.25:
                    self._target_x, self._target_y = 0, 0
                # 30% chance of saccade (fast snap) vs smooth tracking
                use_saccade = random.random() < 0.3
                if use_saccade:
                    self._pupil_x = lerp(self._pupil_x, self._target_x, 0.8)
                    self._pupil_y = lerp(self._pupil_y, self._target_y, 0.8)
                next_look = now + random.uniform(1.5, 4)

            # Blink
            if now > next_blink:
                for lt in [0.3, 0.7, 1.0, 1.0, 0.7, 0.3, 0.0]:
                    if not self._animating:
                        return
                    self._update_pupils(0.2)
                    img = self._frame()
                    self._draw_eyes(ImageDraw.Draw(img), lid_top=lt)
                    self._show(img)
                    time.sleep(0.025)
                # Double blink 20%
                if random.random() < 0.2:
                    time.sleep(0.08)
                    for lt in [0.5, 1.0, 0.5, 0.0]:
                        img = self._frame()
                        self._draw_eyes(ImageDraw.Draw(img), lid_top=lt)
                        self._show(img)
                        time.sleep(0.03)
                next_blink = now + random.uniform(2.5, 6)
                continue

            # Micro-expressions
            if now > next_expr:
                expression = random.choice([
                    'happy', 'curious', 'suspicious', 'confused', None, None
                ])
                expr_end = now + random.uniform(1.5, 3)
                next_expr = now + random.uniform(8, 18)
            if expression and now > expr_end:
                expression = None

            # Draw
            self._update_pupils(0.12 if not use_saccade else 0.3)
            img = self._frame()
            draw = ImageDraw.Draw(img)

            if expression == 'happy':
                self._draw_eyes(draw, lid_bot=0.3, happy=True)
            elif expression == 'curious':
                self._draw_eyes(draw, brow_raise=0.7)
            elif expression == 'suspicious':
                self._draw_eyes(draw, lid_top=0.35, suspicious=True)
            elif expression == 'confused':
                self._draw_eyes(draw, brow_raise=0.3, confused=True)
            else:
                self._draw_eyes(draw)

            self._show(img)
            time.sleep(0.07)

    def eyes_listening(self):
        """Wide open, raised brows — full attention."""
        self._animating = False
        self._target_x, self._target_y = 0, 0
        for step in range(10):
            t = ease_in_out(step / 9)
            self._update_pupils(0.3)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, wide=True, brow_raise=t * 0.8)
            draw.text((34, 54), 'listening', fill=1, font=self.font)
            self._show(img)
            time.sleep(0.03)

    def eyes_listening_pulse(self, duration=30):
        """Listening with pulsing brows."""
        self._animating = True
        end = time.time() + duration
        phase = 0
        while self._alive and self._animating and time.time() < end:
            phase += 0.12
            pulse = 0.5 + math.sin(phase) * 0.3
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, wide=True, brow_raise=pulse)
            draw.text((34, 54), 'listening', fill=1, font=self.font)
            self._show(img)
            time.sleep(0.07)

    def eyes_thinking(self):
        """Squinted, looking up-right, furrowed brows."""
        self._animating = False
        self._target_x, self._target_y = 0.5, -0.4
        for step in range(12):
            t = ease_in_out(step / 11)
            self._update_pupils(0.25)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid_top=lerp(0, 0.35, t),
                           brow_furrow=t > 0.4)
            draw.text((36, 54), 'thinking', fill=1, font=self.font)
            self._show(img)
            time.sleep(0.03)

    def eyes_thinking_anim(self, duration=30):
        """Thinking with darting eyes."""
        self._animating = True
        end = time.time() + duration
        phase = 0
        while self._alive and self._animating and time.time() < end:
            phase += 0.08
            self._target_x = math.sin(phase) * 0.4 + 0.2
            self._target_y = math.sin(phase * 2) * 0.15 - 0.2
            self._update_pupils(0.15)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid_top=0.3, brow_furrow=True)
            draw.text((36, 54), 'thinking', fill=1, font=self.font)
            self._show(img)
            time.sleep(0.07)

    def eyes_speaking(self, text=None):
        """Relaxed, engaged expression."""
        self._animating = False
        self._target_x, self._target_y = 0, 0.05
        for step in range(8):
            t = ease_in_out(step / 7)
            self._update_pupils(0.25)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid_top=lerp(0.3, 0.05, t),
                           lid_bot=lerp(0, 0.1, t))
            draw.text((36, 54), 'speaking', fill=1, font=self.font)
            self._show(img)
            time.sleep(0.03)

    def eyes_speaking_anim(self, duration=30):
        """Speaking with gentle sway and mood shifts."""
        self._animating = True
        end = time.time() + duration
        phase = 0
        while self._alive and self._animating and time.time() < end:
            phase += 0.06
            self._target_x = math.sin(phase * 0.7) * 0.15
            self._update_pupils(0.1)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            happy = math.sin(phase) > 0.6
            self._draw_eyes(draw, lid_bot=0.15 if happy else 0.08,
                           happy=happy)
            draw.text((36, 54), 'speaking', fill=1, font=self.font)
            self._show(img)
            time.sleep(0.07)

    def eyes_happy(self):
        """Pleased — bottom lids curved up."""
        self._animating = False
        self._target_x, self._target_y = 0, 0
        for step in range(10):
            t = ease_in_out(step / 9)
            self._update_pupils(0.3)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid_bot=lerp(0, 0.4, t), happy=True)
            self._show(img)
            time.sleep(0.03)

    def eyes_angry(self):
        """Angry — angled top lids, furrowed brows."""
        self._animating = False
        self._target_x, self._target_y = 0, 0
        for step in range(10):
            t = ease_in_out(step / 9)
            self._update_pupils(0.3)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid_top=lerp(0, 0.3, t),
                           angry=True, brow_furrow=True)
            self._show(img)
            time.sleep(0.03)

    def eyes_sad(self):
        """Sad — droopy brows and angled bottom lids."""
        self._animating = False
        self._target_x, self._target_y = 0, 0.2
        for step in range(12):
            t = ease_in_out(step / 11)
            self._update_pupils(0.2)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid_top=lerp(0, 0.15, t),
                           lid_bot=lerp(0, 0.15, t), sad=True)
            self._show(img)
            time.sleep(0.04)

    def eyes_confused(self):
        """Confused — one brow up, one flat."""
        self._animating = False
        self._target_x, self._target_y = -0.3, 0
        for step in range(10):
            t = ease_in_out(step / 9)
            self._update_pupils(0.25)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, brow_raise=0.3, confused=True)
            self._show(img)
            time.sleep(0.03)

    def eyes_suspicious(self):
        """Suspicious — squinted, one eye more closed."""
        self._animating = False
        self._target_x, self._target_y = 0.4, 0
        for step in range(10):
            t = ease_in_out(step / 9)
            self._update_pupils(0.2)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid_top=lerp(0, 0.4, t), suspicious=True)
            self._show(img)
            time.sleep(0.03)

    def eyes_alert(self):
        """Quick snap to attention — flash wide."""
        self._animating = False
        self._target_x, self._target_y = 0, 0
        self._pupil_x, self._pupil_y = 0, 0
        for _ in range(2):
            img = self._frame()
            self._draw_eyes(ImageDraw.Draw(img), wide=True, brow_raise=1.0)
            self._show(img)
            time.sleep(0.08)
            img = self._frame()
            self._draw_eyes(ImageDraw.Draw(img), wide=True, brow_raise=0.4)
            self._show(img)
            time.sleep(0.08)
        img = self._frame()
        draw = ImageDraw.Draw(img)
        self._draw_eyes(draw, wide=True, brow_raise=0.9)
        draw.text((32, 54), 'capturing', fill=1, font=self.font)
        self._show(img)

    def eyes_sleepy(self):
        """Droopy, closing down."""
        self._animating = False
        self._target_x, self._target_y = 0, 0.3
        for step in range(18):
            t = ease_in_out(step / 17)
            self._update_pupils(0.1)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid_top=lerp(0, 0.7, t),
                           lid_bot=lerp(0, 0.2, t))
            self._show(img)
            time.sleep(0.05)

    def eyes_wink(self):
        """Right eye wink."""
        self._animating = False
        saved_x, saved_y = self._pupil_x, self._pupil_y

        for step in range(14):
            img = self._frame()
            draw = ImageDraw.Draw(img)

            if step < 4:
                r_close = step / 3
            elif step < 8:
                r_close = 1.0
            else:
                r_close = max(0, 1.0 - (step - 8) / 4)

            # Draw left eye normal
            lc, cy = 34, 26
            ew, eh = 20, 17
            draw.rounded_rectangle([lc - ew, cy - eh, lc + ew, cy + eh],
                                    radius=5, fill=1)
            px = lc + int(saved_x * ew * 0.35)
            py = cy + int(saved_y * eh * 0.3)
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=0)
            draw.ellipse((px - 3, py - 4, px - 1, py - 2), fill=1)

            # Draw right eye closing
            rc = 94
            if r_close > 0.9:
                line_y = cy
                draw.line([(rc - ew + 2, line_y), (rc + ew - 2, line_y)],
                          fill=1, width=2)
            else:
                draw.rounded_rectangle([rc - ew, cy - eh, rc + ew, cy + eh],
                                        radius=5, fill=1)
                # Top lid mask
                lid_h = int(eh * 2 * r_close)
                if lid_h > 0:
                    draw.rectangle([rc - ew - 2, cy - eh - 2,
                                    rc + ew + 2, cy - eh + lid_h], fill=0)
                if r_close < 0.8:
                    px = rc + int(saved_x * ew * 0.35)
                    py = cy + int(saved_y * eh * 0.3 * (1 - r_close))
                    pr = int(5 * (1 - r_close))
                    if pr > 1:
                        draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=0)

            self._show(img)
            time.sleep(0.03)

    def show_text(self, text, eyes=True):
        """Word-wrapped text with optional small eyes at top."""
        self._animating = False
        img = self._frame()
        draw = ImageDraw.Draw(img)

        if eyes:
            # Small rounded rect eyes at top
            for ex in [34, 94]:
                draw.rounded_rectangle([ex - 12, 1, ex + 12, 13],
                                        radius=3, fill=1)
                draw.ellipse((ex - 3, 4, ex + 3, 10), fill=0)
                draw.ellipse((ex - 1, 5, ex + 1, 7), fill=1)

        start_y = 17 if eyes else 4
        lines, cur = [], ''
        for w in text.split():
            if len(cur) + len(w) + 1 <= 21:
                cur = f'{cur} {w}' if cur else w
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)

        max_lines = 4 if eyes else 5
        y = start_y
        for line in lines[:max_lines]:
            draw.text((4, y), line, fill=1, font=self.font)
            y += 12
        if len(lines) > max_lines:
            draw.text((110, y - 12), '…', fill=1, font=self.font)
        self._show(img)

    def clear(self):
        self._animating = False
        self._show(self._frame())

    def stop_animation(self):
        self._animating = False

    def cleanup(self):
        self._alive = False
        self._animating = False
        try:
            self.device.cleanup()
        except Exception:
            pass


if __name__ == '__main__':
    ui = OledUI()

    print('Boot...')
    ui.boot_animation()
    time.sleep(1)

    print('Idle (6s)...')
    ui.eyes_idle(6)

    print('Listening...')
    ui.eyes_listening()
    time.sleep(1)
    ui.eyes_listening_pulse(3)

    print('Thinking...')
    ui.eyes_thinking()
    time.sleep(1)
    ui.eyes_thinking_anim(3)

    print('Speaking...')
    ui.eyes_speaking()
    time.sleep(1)
    ui.eyes_speaking_anim(3)

    print('Happy...')
    ui.eyes_happy()
    time.sleep(2)

    print('Angry...')
    ui.eyes_angry()
    time.sleep(2)

    print('Sad...')
    ui.eyes_sad()
    time.sleep(2)

    print('Confused...')
    ui.eyes_confused()
    time.sleep(2)

    print('Suspicious...')
    ui.eyes_suspicious()
    time.sleep(2)

    print('Alert!')
    ui.eyes_alert()
    time.sleep(2)

    print('Wink...')
    ui.eyes_wink()
    time.sleep(1)

    print('Sleepy...')
    ui.eyes_sleepy()
    time.sleep(2)

    print('Text...')
    ui.show_text('SiteEye v3 ready for the jobsite')
    time.sleep(3)

    print('Idle (6s)...')
    ui.eyes_idle(6)

    ui.cleanup()
    print('Done.')

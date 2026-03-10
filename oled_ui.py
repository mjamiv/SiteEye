#!/usr/bin/env python3
"""SiteEye OLED UI — Expressive animated eyes with personality."""

from luma.core.interface.serial import spi
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont
import time, threading, random, math


def ease_in_out(t):
    """Smooth easing for animations."""
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    """Linear interpolation."""
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
        # Mood system
        self._mood = 'neutral'  # neutral, happy, alert, sleepy
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
            self.device.display(img)

    def _update_pupils(self, speed=0.15):
        """Smooth interpolation toward target look direction."""
        self._pupil_x = lerp(self._pupil_x, self._target_x, speed)
        self._pupil_y = lerp(self._pupil_y, self._target_y, speed)

    def _draw_eyes(self, draw, lid=1.0, wide=False, squint=False,
                   happy=False, brow_raise=0.0, brow_furrow=False):
        """Expressive eyes with eyebrows and multiple shapes.
        
        lid: 0.0 (closed) to 1.0 (open)
        wide: bigger eyes (surprised/listening)
        squint: narrow eyes (thinking/skeptical)
        happy: curved bottom lids (pleased)
        brow_raise: 0.0-1.0 how raised the eyebrows are
        brow_furrow: angled angry/focused brows
        """
        lc, rc = 36, 92  # eye centers x
        cy = 30  # eye center y (slightly higher to leave room for text)
        
        # Eye dimensions
        if wide:
            ew, eh = 20, 18
        elif squint:
            ew, eh = 18, 8
        else:
            ew, eh = 18, 14

        # Effective lid opening
        top_open = int(eh * lid)
        bot_open = int(eh * lid)

        for i, ex in enumerate([lc, rc]):
            top = cy - top_open
            bot = cy + bot_open

            if lid < 0.1:
                # Closed — horizontal line with slight curve
                pts = [(ex - ew, cy), (ex - ew//2, cy - 1),
                       (ex, cy - 2), (ex + ew//2, cy - 1), (ex + ew, cy)]
                draw.line(pts, fill=1, width=2)
            else:
                # Draw eye outline
                if happy:
                    # Top: normal arc, Bottom: curved up (smile shape)
                    draw.arc((ex - ew, top, ex + ew, bot), 180, 360, fill=1)
                    # Happy bottom — flat or curved up
                    mid_bot = bot - int(eh * 0.3 * lid)
                    draw.arc((ex - ew, mid_bot - (bot - mid_bot),
                              ex + ew, bot), 0, 180, fill=1)
                    # Close the sides
                    side_y = cy - int((top_open - 2) * 0.7)
                    draw.line([(ex - ew, side_y), (ex - ew, mid_bot)], fill=1)
                    draw.line([(ex + ew, side_y), (ex + ew, mid_bot)], fill=1)
                else:
                    # Standard rounded eye
                    draw.ellipse((ex - ew, top, ex + ew, bot), outline=1, fill=0)

                # Pupil — smooth tracked position
                px = ex + int(self._pupil_x * 8)
                py = cy + int(self._pupil_y * 5 * lid)

                if wide:
                    # Bigger pupil when wide/surprised
                    pr = 6
                    draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=1)
                    # Highlight dot (reflection)
                    draw.ellipse((px - pr + 2, py - pr + 1,
                                  px - pr + 4, py - pr + 3), fill=0)
                elif squint:
                    pr = 3
                    draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=1)
                else:
                    pr = 5
                    draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=1)
                    # Highlight dot
                    draw.ellipse((px - pr + 2, py - pr + 1,
                                  px - pr + 4, py - pr + 3), fill=0)

            # Eyebrows
            brow_y = top - 4 - int(brow_raise * 5)
            if brow_furrow:
                # Angled inward — focused/concerned
                if i == 0:  # left eye
                    draw.line([(ex - ew + 2, brow_y - 3),
                               (ex + ew - 4, brow_y + 2)], fill=1, width=2)
                else:  # right eye
                    draw.line([(ex - ew + 4, brow_y + 2),
                               (ex + ew - 2, brow_y - 3)], fill=1, width=2)
            elif brow_raise > 0.1:
                # Raised — surprised/interested
                draw.arc((ex - ew + 2, brow_y - 2, ex + ew - 2, brow_y + 6),
                         200, 340, fill=1)

    def _draw_status_dots(self, draw, state='idle'):
        """Small status indicator in corner."""
        if state == 'idle':
            # Subtle breathing dot
            pass
        elif state == 'listening':
            # Three dots pulsing
            for i in range(3):
                x = 58 + i * 6
                draw.ellipse((x, 58, x + 3, 61), fill=1)
        elif state == 'thinking':
            draw.text((40, 55), '· · ·', fill=1, font=self.font_sm)

    # ─── States ───

    def boot_animation(self):
        """Power-on eye opening sequence."""
        self._animating = True
        # Start dark, then open
        for step in range(20):
            t = ease_in_out(step / 19)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=t, brow_raise=t * 0.5)
            self._show(img)
            time.sleep(0.05)
        # Quick look around
        for lx, ly in [(0.5, 0), (-0.5, 0), (0, -0.3), (0, 0)]:
            self._target_x, self._target_y = lx, ly
            for _ in range(8):
                self._update_pupils(0.25)
                img = self._frame()
                draw = ImageDraw.Draw(img)
                self._draw_eyes(draw, lid=1.0, brow_raise=0.3)
                self._show(img)
                time.sleep(0.04)
        # Settle
        time.sleep(0.3)

    def eyes_idle(self, duration=30):
        """Animated idle — blink, look around, occasional expressions."""
        self._animating = True
        end = time.time() + duration
        next_look = time.time() + random.uniform(2, 4)
        next_blink = time.time() + random.uniform(3, 6)
        next_expression = time.time() + random.uniform(8, 15)
        expression = None
        expression_end = 0
        breath_phase = 0

        while self._alive and self._animating and time.time() < end:
            now = time.time()

            # Breathing — subtle pupil size oscillation via brow
            breath_phase += 0.03
            breath = math.sin(breath_phase) * 0.05

            # Random look direction (smooth)
            if now > next_look:
                self._target_x = random.uniform(-0.8, 0.8)
                self._target_y = random.uniform(-0.4, 0.4)
                # Sometimes center
                if random.random() < 0.3:
                    self._target_x, self._target_y = 0, 0
                next_look = now + random.uniform(1.5, 4)

            # Blink
            if now > next_blink:
                # Fast blink with easing
                blink_frames = [0.7, 0.3, 0.05, 0.05, 0.3, 0.7, 1.0]
                for lid in blink_frames:
                    self._update_pupils(0.2)
                    img = self._frame()
                    draw = ImageDraw.Draw(img)
                    self._draw_eyes(draw, lid=lid)
                    self._show(img)
                    time.sleep(0.03)
                # Occasional double blink
                if random.random() < 0.2:
                    time.sleep(0.1)
                    for lid in [0.3, 0.05, 0.3, 1.0]:
                        img = self._frame()
                        self._draw_eyes(ImageDraw.Draw(img), lid=lid)
                        self._show(img)
                        time.sleep(0.03)
                next_blink = now + random.uniform(2.5, 7)
                continue

            # Occasional micro-expressions
            if now > next_expression:
                expression = random.choice(['happy', 'curious', 'squint', None])
                expression_end = now + random.uniform(1.5, 3)
                next_expression = now + random.uniform(10, 20)

            if expression and now > expression_end:
                expression = None

            # Draw frame
            self._update_pupils(0.12)
            img = self._frame()
            draw = ImageDraw.Draw(img)

            if expression == 'happy':
                self._draw_eyes(draw, lid=0.85, happy=True)
            elif expression == 'curious':
                self._draw_eyes(draw, lid=1.0, brow_raise=0.6)
            elif expression == 'squint':
                self._draw_eyes(draw, lid=0.7, squint=True)
            else:
                self._draw_eyes(draw, lid=1.0, brow_raise=max(0, breath))

            self._show(img)
            time.sleep(0.08)

    def eyes_listening(self):
        """Wide open with raised brows — paying full attention."""
        self._animating = False
        self._target_x, self._target_y = 0, 0
        # Animate opening wide
        for step in range(10):
            t = ease_in_out(step / 9)
            self._update_pupils(0.3)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=lerp(1.0, 1.0, t),
                           wide=True, brow_raise=t * 0.8)
            self._draw_status_dots(draw, 'listening')
            self._show(img)
            time.sleep(0.03)

    def eyes_listening_pulse(self, duration=30):
        """Listening with subtle pulsing to show it's active."""
        self._animating = True
        end = time.time() + duration
        phase = 0
        while self._alive and self._animating and time.time() < end:
            phase += 0.15
            pulse = 0.6 + math.sin(phase) * 0.2
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=1.0, wide=True, brow_raise=pulse)
            # Animated dots
            ndots = int((phase / 0.5) % 4)
            dot_str = '·' * ndots
            draw.text((52, 56), dot_str, fill=1, font=self.font)
            self._show(img)
            time.sleep(0.08)

    def eyes_thinking(self):
        """Squinted, looking up-right — processing."""
        self._animating = False
        self._target_x, self._target_y = 0.6, -0.4
        for step in range(12):
            t = ease_in_out(step / 11)
            self._update_pupils(0.2)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=lerp(1.0, 0.6, t),
                           squint=t > 0.5, brow_furrow=t > 0.5)
            self._show(img)
            time.sleep(0.03)

    def eyes_thinking_anim(self, duration=30):
        """Thinking with eyes darting — shows active processing."""
        self._animating = True
        end = time.time() + duration
        phase = 0
        while self._alive and self._animating and time.time() < end:
            phase += 0.08
            # Eyes dart in small figure-8
            self._target_x = math.sin(phase) * 0.4 + 0.3
            self._target_y = math.sin(phase * 2) * 0.2 - 0.2
            self._update_pupils(0.15)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=0.6, squint=True, brow_furrow=True)
            # Rotating dots
            ndots = int(phase * 2) % 4
            dots = ['·   ', ' ·  ', '  · ', '   ·']
            draw.text((46, 56), dots[ndots], fill=1, font=self.font)
            self._show(img)
            time.sleep(0.08)

    def eyes_speaking(self, text=None):
        """Relaxed, engaged — talking back. Optional text below."""
        self._animating = False
        self._target_x, self._target_y = 0, 0.1
        for step in range(8):
            t = ease_in_out(step / 7)
            self._update_pupils(0.25)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=lerp(0.6, 0.85, t))
            self._show(img)
            time.sleep(0.03)

    def eyes_speaking_anim(self, duration=30):
        """Speaking with subtle expression changes."""
        self._animating = True
        end = time.time() + duration
        phase = 0
        while self._alive and self._animating and time.time() < end:
            phase += 0.06
            # Gentle swaying
            self._target_x = math.sin(phase * 0.7) * 0.2
            self._update_pupils(0.1)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            # Alternate between neutral and slightly happy
            happy = math.sin(phase) > 0.5
            self._draw_eyes(draw, lid=0.85, happy=happy)
            self._show(img)
            time.sleep(0.08)

    def eyes_happy(self):
        """Pleased expression — curved bottom lids."""
        self._animating = False
        self._target_x, self._target_y = 0, 0
        for step in range(10):
            t = ease_in_out(step / 9)
            self._update_pupils(0.3)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=lerp(1.0, 0.85, t), happy=True)
            self._show(img)
            time.sleep(0.03)

    def eyes_alert(self):
        """Quick snap to attention — error or important event."""
        self._animating = False
        self._target_x, self._target_y = 0, 0
        self._pupil_x, self._pupil_y = 0, 0  # Instant center
        # Flash wide
        for _ in range(2):
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=1.0, wide=True, brow_raise=1.0)
            self._show(img)
            time.sleep(0.1)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=0.8, wide=True, brow_raise=0.5)
            self._show(img)
            time.sleep(0.1)
        # Hold alert
        img = self._frame()
        draw = ImageDraw.Draw(img)
        self._draw_eyes(draw, lid=1.0, wide=True, brow_raise=0.8)
        draw.text((52, 56), '!', fill=1, font=self.font)
        self._show(img)

    def eyes_sleepy(self):
        """Droopy, about to sleep."""
        self._animating = False
        self._target_x, self._target_y = 0, 0.3
        for step in range(15):
            t = ease_in_out(step / 14)
            self._update_pupils(0.1)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            self._draw_eyes(draw, lid=lerp(1.0, 0.25, t))
            self._show(img)
            time.sleep(0.06)

    def eyes_wink(self):
        """Quick wink — right eye."""
        self._animating = False
        for step in range(12):
            if step < 4:
                r_lid = lerp(1.0, 0.0, step / 3)
            elif step < 8:
                r_lid = 0.0
            else:
                r_lid = lerp(0.0, 1.0, (step - 8) / 3)
            img = self._frame()
            draw = ImageDraw.Draw(img)
            # Left eye normal, right eye winking
            # Draw left
            lc, cy = 36, 30
            ew, eh = 18, 14
            draw.ellipse((lc - ew, cy - eh, lc + ew, cy + eh), outline=1, fill=0)
            px = lc + int(self._pupil_x * 8)
            py = cy + int(self._pupil_y * 5)
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=1)
            draw.ellipse((px - 3, py - 4, px - 1, py - 2), fill=0)
            # Draw right with lid
            rc = 92
            if r_lid < 0.1:
                draw.line([(rc - ew, cy), (rc + ew, cy)], fill=1, width=2)
            else:
                top = cy - int(eh * r_lid)
                bot = cy + int(eh * r_lid)
                draw.ellipse((rc - ew, top, rc + ew, bot), outline=1, fill=0)
                px = rc + int(self._pupil_x * 8)
                py = cy + int(self._pupil_y * 5 * r_lid)
                pr = int(5 * r_lid)
                if pr > 1:
                    draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=1)
            self._show(img)
            time.sleep(0.035)

    def show_text(self, text, eyes=True):
        """Word-wrapped text with optional small eyes at top."""
        self._animating = False
        img = self._frame()
        draw = ImageDraw.Draw(img)

        if eyes:
            # Small eyes at top
            for ex in [36, 92]:
                draw.ellipse((ex - 10, 2, ex + 10, 14), outline=1, fill=0)
                draw.ellipse((ex - 2, 5, ex + 2, 9), fill=1)

        # Word wrap
        start_y = 18 if eyes else 4
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

    def show_text_scroll(self, text, speed=0.8):
        """Scrolling text display for longer messages."""
        self._animating = True
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

        if len(lines) <= 5:
            self.show_text(text, eyes=False)
            return

        for offset in range(len(lines) - 4):
            if not self._animating:
                break
            img = self._frame()
            draw = ImageDraw.Draw(img)
            y = 4
            for line in lines[offset:offset + 5]:
                draw.text((4, y), line, fill=1, font=self.font)
                y += 12
            self._show(img)
            time.sleep(speed)

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

    print('Boot animation...')
    ui.boot_animation()
    time.sleep(1)

    print('Idle eyes (8s)...')
    ui.eyes_idle(8)

    print('Listening...')
    ui.eyes_listening()
    time.sleep(1)
    ui.eyes_listening_pulse(4)

    print('Thinking...')
    ui.eyes_thinking()
    time.sleep(1)
    ui.eyes_thinking_anim(4)

    print('Speaking...')
    ui.eyes_speaking()
    time.sleep(1)
    ui.eyes_speaking_anim(4)

    print('Happy...')
    ui.eyes_happy()
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

    print('Text with eyes...')
    ui.show_text('45F and clear in Merrick tonight')
    time.sleep(3)

    print('Back to idle (8s)...')
    ui.eyes_idle(8)

    ui.cleanup()
    print('Done.')

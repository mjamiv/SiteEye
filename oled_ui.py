#!/usr/bin/env python3
"""Molt Device OLED UI — Eyes + minimal text."""

from luma.core.interface.serial import spi
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont
import time, threading, random

class OledUI:
    def __init__(self):
        serial = spi(device=0, port=0, gpio_DC=24, gpio_RST=25, bus_speed_hz=500000)
        self.device = sh1106(serial, width=128, height=64, rotate=2)
        self.device.contrast(255)
        self.W, self.H = 128, 64
        self._lock = threading.Lock()
        self._alive = True
        self._animating = False
        try:
            self.font = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 11)
        except:
            self.font = ImageFont.load_default()

    def _frame(self):
        return Image.new('1', (self.W, self.H), 0)

    def _show(self, img):
        with self._lock:
            self.device.display(img)

    def _draw_eyes(self, draw, lx=0, ly=0, lid=1.0, wide=False):
        """Two eyes. lx/ly: -1..1 look direction. lid: 0=closed 1=open."""
        lc, rc, cy = 36, 92, 28
        ew = 18
        eh = 16 if wide else 14
        for ex in [lc, rc]:
            top = cy - int(eh * lid)
            bot = cy + int(eh * lid)
            if lid < 0.15:
                draw.line([(ex - ew, cy), (ex + ew, cy)], fill=1, width=2)
            else:
                draw.ellipse((ex - ew, top, ex + ew, bot), outline=1, fill=0)
                px = ex + int(lx * 7)
                py = cy + int(ly * 4 * lid)
                pr = 5 if wide else 4
                draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=1)

    def eyes_idle(self, duration=30):
        """Animated idle — blink and look around."""
        self._animating = True
        end = time.time() + duration
        lx, ly = 0, 0
        next_look = time.time() + random.uniform(2, 5)
        next_blink = time.time() + random.uniform(3, 7)

        while self._alive and self._animating and time.time() < end:
            now = time.time()
            if now > next_look:
                lx = random.uniform(-1, 1)
                ly = random.uniform(-0.5, 0.5)
                if random.random() < 0.3:
                    lx, ly = 0, 0
                next_look = now + random.uniform(2, 5)
            if now > next_blink:
                for lid in [0.6, 0.2, 0.0, 0.0, 0.2, 0.6, 1.0]:
                    img = self._frame()
                    self._draw_eyes(ImageDraw.Draw(img), lx, ly, lid)
                    self._show(img)
                    time.sleep(0.04)
                next_blink = now + random.uniform(3, 8)
                continue
            img = self._frame()
            self._draw_eyes(ImageDraw.Draw(img), lx, ly, 1.0)
            self._show(img)
            time.sleep(0.1)

    def eyes_listening(self):
        """Wide open — paying attention."""
        self._animating = False
        img = self._frame()
        draw = ImageDraw.Draw(img)
        self._draw_eyes(draw, 0, 0, 1.0, wide=True)
        draw.text((32, 52), 'listening', fill=1, font=self.font)
        self._show(img)

    def eyes_thinking(self):
        """Squinty — processing."""
        self._animating = False
        img = self._frame()
        draw = ImageDraw.Draw(img)
        self._draw_eyes(draw, 0.5, -0.3, 0.5)
        draw.text((34, 52), 'thinking', fill=1, font=self.font)
        self._show(img)

    def eyes_speaking(self):
        """Relaxed — talking back."""
        self._animating = False
        img = self._frame()
        draw = ImageDraw.Draw(img)
        self._draw_eyes(draw, 0, 0, 0.85)
        self._show(img)

    def show_text(self, text):
        """Word-wrapped text response."""
        self._animating = False
        img = self._frame()
        draw = ImageDraw.Draw(img)
        lines, cur = [], ''
        for w in text.split():
            if len(cur) + len(w) + 1 <= 20:
                cur = f'{cur} {w}' if cur else w
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        y = 4
        for line in lines[:5]:
            draw.text((4, y), line, fill=1, font=self.font)
            y += 13
        self._show(img)

    def clear(self):
        self._animating = False
        self._show(self._frame())

    def cleanup(self):
        self._alive = False
        self._animating = False
        self.device.cleanup()


if __name__ == '__main__':
    ui = OledUI()
    print('Idle eyes (10s)...')
    ui.eyes_idle(10)
    print('Listening...')
    ui.eyes_listening()
    time.sleep(3)
    print('Thinking...')
    ui.eyes_thinking()
    time.sleep(3)
    print('Speaking...')
    ui.eyes_speaking()
    time.sleep(3)
    print('Text...')
    ui.show_text('45F and clear in Merrick tonight')
    time.sleep(4)
    print('Back to idle (10s)...')
    ui.eyes_idle(10)
    ui.cleanup()
    print('Done.')

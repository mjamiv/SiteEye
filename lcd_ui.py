#!/usr/bin/env python3
"""SiteEye v2 LCD UI — Neural Mesh Face on Whisplay 240×280 ST7789

A face made of interconnected particles forming a network mesh.
Points drift organically, connections glow, and the mesh reshapes
to form expressions. Sci-fi AI energy.
"""

import sys
import time
import math
import random
import threading

sys.path.insert(0, '/home/pi-molt/Whisplay/Driver')

from PIL import Image, ImageDraw, ImageFont
from WhisPlay import WhisPlayBoard

# Display
WIDTH = 240
HEIGHT = 280
CORNER_H = 20
SAFE_TOP = CORNER_H + 2
SAFE_BOT = HEIGHT - CORNER_H - 2
SAFE_LEFT = 14
SAFE_RIGHT = WIDTH - 14

# Colors
BG = (4, 4, 12)
NODE_COLOR = (120, 200, 255)
NODE_BRIGHT = (180, 230, 255)
EDGE_COLOR = (40, 80, 140)
EDGE_BRIGHT = (80, 160, 255)
ACCENT_GLOW = (100, 180, 255)
TEXT_PRIMARY = (200, 220, 240)
TEXT_DIM = (80, 100, 130)

# State colors
STATE_COLORS = {
    "idle":      {"node": (100, 200, 255), "edge": (30, 70, 130),  "glow": (60, 140, 255)},
    "listening": {"node": (80, 160, 255),  "edge": (20, 60, 180),  "glow": (40, 120, 255)},
    "thinking":  {"node": (255, 200, 80),  "edge": (130, 90, 20),  "glow": (255, 180, 40)},
    "speaking":  {"node": (200, 100, 255), "edge": (90, 30, 130),  "glow": (180, 60, 255)},
    "camera":    {"node": (255, 255, 255), "edge": (100, 100, 100),"glow": (200, 200, 200)},
    "error":     {"node": (255, 60, 60),   "edge": (130, 20, 20),  "glow": (255, 40, 40)},
    "boot":      {"node": (60, 120, 200),  "edge": (20, 50, 100),  "glow": (40, 90, 180)},
}

# States
STATE_BOOT = "boot"
STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_THINKING = "thinking"
STATE_SPEAKING = "speaking"
STATE_CAMERA = "camera"
STATE_ERROR = "error"


class Particle:
    """A node in the mesh face."""
    __slots__ = ['x', 'y', 'tx', 'ty', 'ox', 'oy', 'vx', 'vy',
                 'brightness', 'size', 'group', 'drift_phase', 'drift_speed']

    def __init__(self, x, y, group="face", size=2):
        self.x = x
        self.y = y
        self.tx = x  # target x
        self.ty = y  # target y
        self.ox = x  # origin x (for drift)
        self.oy = y  # origin y
        self.vx = 0.0
        self.vy = 0.0
        self.brightness = 0.6 + random.random() * 0.4
        self.size = size
        self.group = group
        self.drift_phase = random.random() * math.pi * 2
        self.drift_speed = 0.3 + random.random() * 0.5

    def update(self, t):
        """Move toward target with organic drift."""
        # Drift around target position
        drift_x = math.sin(t * self.drift_speed + self.drift_phase) * 1.5
        drift_y = math.cos(t * self.drift_speed * 0.7 + self.drift_phase + 1.0) * 1.2
        goal_x = self.tx + drift_x
        goal_y = self.ty + drift_y

        # Spring physics
        ax = (goal_x - self.x) * 0.15
        ay = (goal_y - self.y) * 0.15
        self.vx = (self.vx + ax) * 0.7
        self.vy = (self.vy + ay) * 0.7
        self.x += self.vx
        self.y += self.vy

        # Brightness shimmer
        self.brightness = 0.5 + 0.5 * abs(math.sin(t * 1.5 + self.drift_phase))


def _make_eye_points(cx, cy, w, h, density=12):
    """Generate particles forming an eye shape (elliptical outline + pupil)."""
    pts = []
    # Outer ellipse
    for i in range(density):
        angle = (i / density) * math.pi * 2
        x = cx + math.cos(angle) * w
        y = cy + math.sin(angle) * h
        pts.append(Particle(x, y, "eye_outline", 2))
    # Inner pupil ring
    pw, ph = w * 0.4, h * 0.45
    for i in range(max(6, density // 2)):
        angle = (i / (density // 2)) * math.pi * 2
        x = cx + math.cos(angle) * pw
        y = cy + math.sin(angle) * ph
        pts.append(Particle(x, y, "pupil", 3))
    # Center dot
    pts.append(Particle(cx, cy, "pupil_center", 4))
    return pts


def _make_mouth_points(cx, cy, w):
    """Generate particles forming a mouth line."""
    pts = []
    n = 9
    for i in range(n):
        t = i / (n - 1)
        x = cx - w + t * w * 2
        y = cy
        pts.append(Particle(x, y, "mouth", 2))
    return pts


def _make_brow_points(cx, cy, w):
    """Generate particles forming an eyebrow."""
    pts = []
    n = 6
    for i in range(n):
        t = i / (n - 1)
        x = cx - w + t * w * 2
        y = cy
        pts.append(Particle(x, y, "brow", 2))
    return pts


def _make_ambient_points(n=25):
    """Floating ambient particles for atmosphere."""
    pts = []
    for _ in range(n):
        x = random.uniform(10, WIDTH - 10)
        y = random.uniform(SAFE_TOP, SAFE_BOT)
        p = Particle(x, y, "ambient", 1)
        p.drift_speed = 0.1 + random.random() * 0.3
        pts.append(p)
    return pts


class MeshFace:
    """The neural mesh face — all particles and their connections."""

    def __init__(self):
        cx = WIDTH // 2  # 120
        # Eye positions
        self.left_eye_cx = 70
        self.right_eye_cx = 170
        self.eye_cy = 108
        self.eye_w = 30
        self.eye_h = 22

        # Build particles
        self.left_eye = _make_eye_points(self.left_eye_cx, self.eye_cy, self.eye_w, self.eye_h)
        self.right_eye = _make_eye_points(self.right_eye_cx, self.eye_cy, self.eye_w, self.eye_h)
        self.left_brow = _make_brow_points(self.left_eye_cx, self.eye_cy - 35, 28)
        self.right_brow = _make_brow_points(self.right_eye_cx, self.eye_cy - 35, 28)
        self.mouth = _make_mouth_points(cx, 162, 24)
        self.ambient = _make_ambient_points(20)

        # All particles
        self.all_particles = (self.left_eye + self.right_eye +
                              self.left_brow + self.right_brow +
                              self.mouth + self.ambient)

        # Pre-compute connections (edges between nearby particles of same/related groups)
        self.edges = self._build_edges()

    def _build_edges(self):
        """Build edge list — connect nearby particles."""
        edges = []
        face_pts = [p for p in self.all_particles if p.group != "ambient"]
        # Connect sequential eye outline points
        for eye_pts in [self.left_eye, self.right_eye]:
            outline = [p for p in eye_pts if p.group == "eye_outline"]
            for i in range(len(outline)):
                edges.append((outline[i], outline[(i + 1) % len(outline)]))
            # Connect pupil ring
            pupil = [p for p in eye_pts if p.group == "pupil"]
            for i in range(len(pupil)):
                edges.append((pupil[i], pupil[(i + 1) % len(pupil)]))
            # Connect some outline to pupil (radial spokes)
            center = [p for p in eye_pts if p.group == "pupil_center"]
            if center:
                for p in pupil:
                    edges.append((center[0], p))

        # Mouth connections
        for i in range(len(self.mouth) - 1):
            edges.append((self.mouth[i], self.mouth[i + 1]))

        # Brow connections
        for brow in [self.left_brow, self.right_brow]:
            for i in range(len(brow) - 1):
                edges.append((brow[i], brow[i + 1]))

        # Cross-connections: brow to eye top
        for brow, eye in [(self.left_brow, self.left_eye), (self.right_brow, self.right_eye)]:
            top_eye = [p for p in eye if p.group == "eye_outline" and p.oy < self.eye_cy]
            for i, bp in enumerate(brow):
                if i < len(top_eye):
                    edges.append((bp, top_eye[i]))

        # Ambient connections to nearest face points
        for ap in self.ambient:
            closest = min(face_pts, key=lambda p: (p.ox - ap.ox)**2 + (p.oy - ap.oy)**2)
            dist = math.sqrt((closest.ox - ap.ox)**2 + (closest.oy - ap.oy)**2)
            if dist < 80:
                edges.append((ap, closest))

        return edges

    def set_expression(self, state, blink=0.0, look_x=0.0, look_y=0.0):
        """Reshape the mesh for an expression."""
        cx = WIDTH // 2

        # Base positions
        eye_h = self.eye_h
        eye_w = self.eye_w
        brow_y_offset = 0
        mouth_curve = 0  # positive = smile
        mouth_open = 0
        pupil_shift_x = look_x * 8
        pupil_shift_y = look_y * 6

        if state == STATE_LISTENING:
            eye_h = self.eye_h * 1.15  # wider
            brow_y_offset = -6  # raised
            mouth_open = 0
            pupil_shift_y = 2  # look at speaker
        elif state == STATE_THINKING:
            eye_h = self.eye_h * 0.8  # squint
            brow_y_offset = -3
            pupil_shift_x = 8  # look up-right
            pupil_shift_y = -5
            mouth_curve = -2
        elif state == STATE_SPEAKING:
            mouth_open = 6 + 4 * abs(math.sin(time.time() * 4))
            mouth_curve = 3
            brow_y_offset = -2
        elif state == STATE_CAMERA:
            eye_h = self.eye_h * 1.25  # wide surprised
            brow_y_offset = -10
            mouth_open = 4
        elif state == STATE_ERROR:
            eye_h = self.eye_h * 0.85
            brow_y_offset = 4  # furrowed (inner raised, inverted)
            mouth_curve = -5
        elif state == STATE_IDLE:
            mouth_curve = 2
            brow_y_offset = 0

        # Apply blink (close eyes)
        if blink > 0:
            eye_h *= (1.0 - blink * 0.9)

        # Update eye targets
        for eye_pts, ecx in [(self.left_eye, self.left_eye_cx), (self.right_eye, self.right_eye_cx)]:
            outline = [p for p in eye_pts if p.group == "eye_outline"]
            n = len(outline)
            for i, p in enumerate(outline):
                angle = (i / n) * math.pi * 2
                p.tx = ecx + math.cos(angle) * eye_w
                p.ty = self.eye_cy + math.sin(angle) * eye_h

            pupil = [p for p in eye_pts if p.group == "pupil"]
            pw, ph = eye_w * 0.4, eye_h * 0.45
            np_ = len(pupil)
            for i, p in enumerate(pupil):
                angle = (i / np_) * math.pi * 2
                p.tx = ecx + math.cos(angle) * pw + pupil_shift_x
                p.ty = self.eye_cy + math.sin(angle) * ph + pupil_shift_y

            center = [p for p in eye_pts if p.group == "pupil_center"]
            if center:
                center[0].tx = ecx + pupil_shift_x
                center[0].ty = self.eye_cy + pupil_shift_y

        # Update brow targets
        for brow, bcx in [(self.left_brow, self.left_eye_cx), (self.right_brow, self.right_eye_cx)]:
            bw = 28
            by = self.eye_cy - 35 + brow_y_offset
            n = len(brow)
            for i, p in enumerate(brow):
                t = i / (n - 1)
                p.tx = bcx - bw + t * bw * 2
                # Arch shape
                arch = -3 * (1 - (t * 2 - 1) ** 2)
                p.ty = by + arch

        # Update mouth targets
        n = len(self.mouth)
        mw = 24 + mouth_open * 0.5
        for i, p in enumerate(self.mouth):
            t = i / (n - 1)
            x = cx - mw + t * mw * 2
            # Curve: positive = smile (ends up, center down)
            progress = (t - 0.5) * 2  # -1 to 1
            curve = -mouth_curve * (1 - progress ** 2)
            # Open: center points go down
            open_offset = mouth_open * (1 - abs(progress) ** 1.5)
            p.tx = x
            p.ty = 162 + curve + open_offset


class LcdUI:
    def __init__(self):
        self.board = WhisPlayBoard()
        self.board.set_backlight(70)
        self.state = STATE_BOOT
        self.response_text = ""
        self.status_text = ""
        self._running = True
        self._lock = threading.Lock()

        # Mesh face
        self.face = MeshFace()

        # Animation
        self._anim_frame = 0
        self._blink_amount = 0.0
        self._next_blink = time.time() + random.uniform(2, 5)
        self._look_x = 0.0
        self._look_y = 0.0
        self._next_saccade = time.time() + random.uniform(1, 3)
        self._pulse_phase = 0.0

        # Font cache
        try:
            self._font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
            self._font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
            self._font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
            self._font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
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

        # RGB LED
        led_map = {
            STATE_IDLE: (0, 50, 0),
            STATE_LISTENING: (0, 30, 200),
            STATE_THINKING: (200, 150, 0),
            STATE_SPEAKING: (140, 0, 200),
            STATE_CAMERA: (200, 200, 200),
            STATE_ERROR: (200, 0, 0),
            STATE_BOOT: (30, 30, 60),
        }
        r, g, b = led_map.get(state, (0, 30, 0))
        try:
            self.board.set_rgb(r, g, b)
        except:
            pass

    def set_status(self, text):
        with self._lock:
            self.status_text = text

    def render_frame(self):
        img = Image.new('RGB', (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)

        with self._lock:
            state = self.state
            resp = self.response_text
            status = self.status_text
            self._anim_frame += 1

        now = time.time()
        colors = STATE_COLORS.get(state, STATE_COLORS["idle"])

        # Auto-blink
        if now > self._next_blink:
            self._blink_amount = 1.0
            self._next_blink = now + random.uniform(2.5, 6)
            if random.random() < 0.2:
                self._next_blink = now + 0.3
        if self._blink_amount > 0:
            self._blink_amount = max(0, self._blink_amount - 0.2)

        # Saccades
        if now > self._next_saccade:
            if state == STATE_THINKING:
                self._look_x = random.uniform(0.2, 0.5)
                self._look_y = random.uniform(-0.4, -0.1)
            elif state == STATE_LISTENING:
                self._look_x = random.uniform(-0.1, 0.1)
                self._look_y = random.uniform(0.0, 0.15)
            else:
                self._look_x = random.uniform(-0.3, 0.3)
                self._look_y = random.uniform(-0.2, 0.2)
            self._next_saccade = now + random.uniform(1.0, 3.0)

        self._pulse_phase = now

        if state == STATE_BOOT:
            self._draw_boot(draw, now)
        else:
            # Update mesh expression
            self.face.set_expression(state, self._blink_amount, self._look_x, self._look_y)

            # Update all particles
            for p in self.face.all_particles:
                p.update(now)

            # Draw edges first (behind nodes)
            self._draw_edges(draw, colors, now)

            # Draw nodes
            self._draw_nodes(draw, colors, now)

        # Status text
        if status and state != STATE_BOOT:
            draw.text((SAFE_LEFT + 4, SAFE_TOP), status, fill=TEXT_DIM, font=self._font_sm)

        # Response text
        if resp and state not in (STATE_BOOT, STATE_CAMERA):
            self._draw_wrapped_text(draw, resp, SAFE_LEFT, 195, SAFE_RIGHT - SAFE_LEFT,
                                     self._font_md, TEXT_PRIMARY)

        # Mode bar
        self._draw_mode_bar(draw, state, colors)

        self._send_to_display(img)

    def _draw_edges(self, draw, colors, t):
        """Draw connections between particles."""
        base_color = colors["edge"]
        glow_color = colors["glow"]

        for p1, p2 in self.face.edges:
            dist = math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)
            if dist > 100:
                continue  # Skip very long edges

            # Fade edges by distance
            alpha = max(0.1, 1.0 - dist / 80.0)
            # Pulse effect
            pulse = 0.5 + 0.5 * math.sin(t * 2 + (p1.x + p2.x) * 0.02)

            if p1.group == "ambient" or p2.group == "ambient":
                alpha *= 0.3  # Ambient edges are subtle
                color = tuple(int(c * alpha * 0.5) for c in base_color)
            else:
                mix = alpha * (0.6 + 0.4 * pulse)
                color = tuple(max(0, min(255, int(base_color[i] + (glow_color[i] - base_color[i]) * pulse * alpha)))
                              for i in range(3))

            if any(c > 5 for c in color):
                width = 1 if (p1.group == "ambient" or p2.group == "ambient") else 1
                draw.line([(int(p1.x), int(p1.y)), (int(p2.x), int(p2.y))],
                          fill=color, width=width)

    def _draw_nodes(self, draw, colors, t):
        """Draw particle nodes."""
        node_color = colors["node"]
        glow_color = colors["glow"]

        for p in self.face.all_particles:
            if p.group == "ambient":
                # Ambient: tiny faint dots
                bright = p.brightness * 0.4
                c = tuple(int(v * bright) for v in node_color)
                r = 1
                draw.ellipse([int(p.x) - r, int(p.y) - r, int(p.x) + r, int(p.y) + r], fill=c)
                continue

            bright = p.brightness
            size = p.size

            if p.group == "pupil_center":
                # Center of eye — brightest, biggest
                c = glow_color
                size = 4
                # Glow halo
                for gr in range(8, 2, -2):
                    ga = max(0, 0.15 - (gr - 2) * 0.02)
                    gc = tuple(max(0, min(255, int(v * ga))) for v in glow_color)
                    draw.ellipse([int(p.x) - gr, int(p.y) - gr, int(p.x) + gr, int(p.y) + gr], fill=gc)
            elif p.group == "pupil":
                c = tuple(int(v * bright * 0.9) for v in glow_color)
                size = 3
            elif p.group == "eye_outline":
                c = tuple(int(v * bright * 0.8) for v in node_color)
                size = 2
            elif p.group == "mouth":
                c = tuple(int(v * bright * 0.7) for v in node_color)
                size = 2
            elif p.group == "brow":
                c = tuple(int(v * bright * 0.6) for v in node_color)
                size = 2
            else:
                c = tuple(int(v * bright * 0.5) for v in node_color)
                size = p.size

            ix, iy = int(p.x), int(p.y)
            draw.ellipse([ix - size, iy - size, ix + size, iy + size], fill=c)

    def _draw_boot(self, draw, t):
        """Boot screen — particles assembling from chaos."""
        frame = self._anim_frame
        progress = min(1.0, frame / 30.0)

        # Scattered → assembled interpolation
        for p in self.face.all_particles:
            if p.group == "ambient":
                p.update(t)
                continue
            if frame < 2:
                # Scatter to random positions
                p.x = random.uniform(20, WIDTH - 20)
                p.y = random.uniform(30, HEIGHT - 30)
            # Interpolate toward target
            p.tx = p.ox
            p.ty = p.oy
            p.update(t)

        colors = STATE_COLORS["boot"]

        if progress > 0.3:
            # Start showing edges as particles converge
            edge_alpha = min(1.0, (progress - 0.3) / 0.4)
            dimmed = {k: tuple(int(v * edge_alpha) for v in c) if isinstance(c, tuple) else c
                      for k, c in colors.items()}
            self._draw_edges(draw, dimmed, t)

        if progress > 0.1:
            node_alpha = min(1.0, progress / 0.5)
            dimmed = {k: tuple(int(v * node_alpha) for v in c) if isinstance(c, tuple) else c
                      for k, c in colors.items()}
            self._draw_nodes(draw, dimmed, t)

        # Text fades in
        if progress > 0.6:
            text_alpha = min(1.0, (progress - 0.6) / 0.3)
            tc = tuple(int(v * text_alpha) for v in (100, 180, 255))
            sc = tuple(int(v * text_alpha) for v in TEXT_DIM)
            draw.text((65, SAFE_BOT - 30), "SiteEye v2", fill=tc, font=self._font_lg)
            draw.text((85, SAFE_BOT - 10), "initializing", fill=sc, font=self._font_sub)

    def _draw_mode_bar(self, draw, state, colors):
        mode_map = {
            STATE_IDLE: "READY",
            STATE_LISTENING: "LISTENING",
            STATE_THINKING: "PROCESSING",
            STATE_SPEAKING: "SPEAKING",
            STATE_CAMERA: "CAPTURING",
            STATE_ERROR: "ERROR",
        }
        text = mode_map.get(state, "")
        if text and state != STATE_BOOT:
            # Small indicator dot + text
            dot_color = colors["glow"]
            draw.ellipse([SAFE_LEFT + 4, SAFE_BOT - 3, SAFE_LEFT + 10, SAFE_BOT + 3], fill=dot_color)
            draw.text((SAFE_LEFT + 16, SAFE_BOT - 6), text, fill=TEXT_DIM, font=self._font_sm)

    def _draw_wrapped_text(self, draw, text, x, y, max_w, font, color):
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
        visible = lines[-4:]
        for i, ln in enumerate(visible):
            draw.text((x, y + i * 16), ln, fill=color, font=font)

    def _send_to_display(self, img):
        try:
            import numpy as np
            arr = np.array(img, dtype=np.uint16)
            r = (arr[:, :, 0] & 0xF8) << 8
            g = (arr[:, :, 1] & 0xFC) << 3
            b = arr[:, :, 2] >> 3
            rgb565 = r | g | b
            data_hi = ((rgb565 >> 8) & 0xFF).astype(np.uint8).tobytes()
            data_lo = (rgb565 & 0xFF).astype(np.uint8).tobytes()
            px = bytearray(len(data_hi) * 2)
            px[0::2] = data_hi
            px[1::2] = data_lo
            self.board.draw_image(0, 0, WIDTH, HEIGHT, list(px))
        except ImportError:
            px = []
            for y in range(HEIGHT):
                for x in range(WIDTH):
                    r, g, b = img.getpixel((x, y))
                    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                    px.extend([(rgb565 >> 8) & 0xFF, rgb565 & 0xFF])
            self.board.draw_image(0, 0, WIDTH, HEIGHT, px)

    def cleanup(self):
        self._running = False
        try:
            self.board.set_rgb(0, 0, 0)
            self.board.set_backlight(0)
            self.board.cleanup()
        except:
            pass

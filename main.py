#!/usr/bin/env python3
"""Molt Device v7 — Eyes, ears, voice, camera. 2026-03-09."""

import os, json, time, threading, subprocess, urllib.request, tempfile, random
import http.client, base64
from gpiozero import Button
from luma.core.interface.serial import spi
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont

# CONFIG
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
PROXY_URL = 'http://178.156.211.138:5757'
TG_TOKEN = '8358560979:AAHEPmk-qQg9RsmrIR2cXyNP4i4u_Hqtl2U'
TG_CHAT = '8217278203'
BTN_VOICE, BTN_CAMERA = 27, 17
MIC_GAIN = 25
MAX_REC = 30

class Eyes:
    def __init__(self):
        s = spi(device=0, port=0, gpio_DC=24, gpio_RST=25, bus_speed_hz=500000)
        self.dev = sh1106(s, width=128, height=64, rotate=2)
        self.dev.contrast(255)
        self._lock = threading.Lock()
        self._alive = True
        self._anim = False
        try:
            self.font = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 11)
        except:
            self.font = ImageFont.load_default()

    def _f(self):
        return Image.new('1', (128, 64), 0)

    def _s(self, img):
        with self._lock:
            if self._alive:
                self.dev.display(img)

    def _eyes(self, d, lx=0, ly=0, lid=1.0, w=False):
        for ex in [36, 92]:
            eh = 16 if w else 14
            t = 28 - int(eh * lid)
            b = 28 + int(eh * lid)
            if lid < 0.15:
                d.line([(ex-18, 28), (ex+18, 28)], fill=1, width=2)
            else:
                d.ellipse((ex-18, t, ex+18, b), outline=1, fill=0)
                px = ex + int(lx * 7)
                py = 28 + int(ly * 4 * lid)
                pr = 5 if w else 4
                d.ellipse((px-pr, py-pr, px+pr, py+pr), fill=1)

    def idle(self):
        self._anim = True
        lx, ly = 0, 0
        nl = time.time() + random.uniform(2, 5)
        nb = time.time() + random.uniform(3, 7)
        while self._alive and self._anim:
            now = time.time()
            if now > nl:
                lx = random.uniform(-1, 1)
                ly = random.uniform(-0.5, 0.5)
                if random.random() < 0.3:
                    lx, ly = 0, 0
                nl = now + random.uniform(2, 5)
            if now > nb:
                for lid in [0.6, 0.2, 0.0, 0.0, 0.2, 0.6, 1.0]:
                    if not self._anim:
                        return
                    i = self._f()
                    self._eyes(ImageDraw.Draw(i), lx, ly, lid)
                    self._s(i)
                    time.sleep(0.04)
                nb = now + random.uniform(3, 8)
                continue
            i = self._f()
            self._eyes(ImageDraw.Draw(i), lx, ly)
            self._s(i)
            time.sleep(0.1)

    def _stop(self):
        self._anim = False
        time.sleep(0.15)

    def listening(self):
        self._stop()
        i = self._f()
        d = ImageDraw.Draw(i)
        self._eyes(d, 0, 0, 1.0, True)
        d.text((32, 52), 'listening', fill=1, font=self.font)
        self._s(i)

    def thinking(self):
        self._stop()
        i = self._f()
        d = ImageDraw.Draw(i)
        self._eyes(d, 0.5, -0.3, 0.5)
        d.text((34, 52), 'thinking', fill=1, font=self.font)
        self._s(i)

    def speaking(self):
        self._stop()
        i = self._f()
        d = ImageDraw.Draw(i)
        self._eyes(d, 0, 0, 0.85)
        self._s(i)

    def camera_look(self):
        self._stop()
        i = self._f()
        d = ImageDraw.Draw(i)
        self._eyes(d, 0, -0.8, 1.0, True)
        d.text((30, 52), 'capturing', fill=1, font=self.font)
        self._s(i)

    def text(self, txt):
        self._stop()
        i = self._f()
        d = ImageDraw.Draw(i)
        lines, cur = [], ''
        for w in txt.split():
            if len(cur) + len(w) + 1 <= 20:
                cur = f'{cur} {w}' if cur else w
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        y = 4
        for ln in lines[:5]:
            d.text((4, y), ln, fill=1, font=self.font)
            y += 13
        self._s(i)

    def go_idle(self):
        threading.Thread(target=self.idle, daemon=True).start()

    def die(self):
        self._alive = False
        self._anim = False
        self.dev.cleanup()


def do_record(secs=5, stop_ev=None):
    p = tempfile.mktemp(suffix='.wav')
    proc = subprocess.Popen(
        ['arecord', '-D', 'plughw:1,0', '-f', 'S32_LE',
         '-r', '48000', '-c', '2', '-d', str(secs), p],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if stop_ev:
        while proc.poll() is None:
            if stop_ev.is_set():
                proc.terminate()
                proc.wait()
                break
            time.sleep(0.1)
    else:
        proc.wait()
    return p


def do_boost(path):
    out = tempfile.mktemp(suffix='.wav')
    subprocess.run(
        ['sox', path, out, 'gain', str(MIC_GAIN),
         'rate', '16000', 'channels', '1'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out


def do_play(path):
    tmp = tempfile.mktemp(suffix='.wav')
    subprocess.run(
        ['sox', path, '-t', 'wav', '-b', '32', '-e', 'signed',
         tmp, 'rate', '48000', 'channels', '2',
         'bass', '+6', 'treble', '-7', '3000', 'lowpass', '8000'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(
        ['sudo', 'aplay', '-D', 'speaker', tmp],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.unlink(tmp)
    except:
        pass


def do_whisper(path):
    boundary = f'----Molt{int(time.time())}'
    with open(path, 'rb') as f:
        data = f.read()
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="a.wav"\r\n'
        f'Content-Type: audio/wav\r\n\r\n'
    ).encode() + data + (
        f'\r\n--{boundary}\r\n'
        f'Content-Disposition: form-data; name="model"\r\n\r\n'
        f'whisper-1\r\n'
        f'--{boundary}--\r\n'
    ).encode()
    c = http.client.HTTPSConnection('api.openai.com')
    c.request('POST', '/v1/audio/transcriptions', body, {
        'Authorization': f'Bearer {OPENAI_API_KEY}',
        'Content-Type': f'multipart/form-data; boundary={boundary}'
    })
    r = json.loads(c.getresponse().read().decode())
    c.close()
    return r.get('text', '')


def do_chat(text, img_path=None):
    if img_path:
        with open(img_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        payload = json.dumps({
            'text': text or 'What do you see? Be brief.',
            'image': b64
        }).encode()
        url = f'{PROXY_URL}/vision'
    else:
        payload = json.dumps({'text': text}).encode()
        url = f'{PROXY_URL}/chat'
    req = urllib.request.Request(url, data=payload,
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode())
            return res.get('response', res.get('text', 'No response'))
    except Exception as e:
        return f'Error: {e}'


def do_tts(text):
    payload = json.dumps({
        'model': 'tts-1-hd',
        'input': text[:4096],
        'voice': 'fable',
        'speed': 1.0,
        'response_format': 'wav'
    }).encode()
    req = urllib.request.Request(
        'https://api.openai.com/v1/audio/speech',
        data=payload,
        headers={
            'Authorization': f'Bearer {OPENAI_API_KEY}',
            'Content-Type': 'application/json'
        })
    p = tempfile.mktemp(suffix='.wav')
    with urllib.request.urlopen(req, timeout=30) as r, open(p, 'wb') as f:
        f.write(r.read())
    return p


def do_snap():
    p = tempfile.mktemp(suffix='.jpg')
    subprocess.run(
        ['rpicam-still', '-o', p, '--width', '640', '--height', '480',
         '--nopreview', '-t', '2000', '--vflip', '--hflip'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def do_tg_photo(path, cap=''):
    try:
        boundary = f'----TG{int(time.time())}'
        with open(path, 'rb') as f:
            data = f.read()
        body = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            f'{TG_CHAT}\r\n'
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="photo"; '
            f'filename="p.jpg"\r\n'
            f'Content-Type: image/jpeg\r\n\r\n'
        ).encode() + data
        if cap:
            body += (
                f'\r\n--{boundary}\r\n'
                f'Content-Disposition: form-data; name="caption"\r\n\r\n'
                f'{cap}\r\n'
            ).encode()
        body += f'\r\n--{boundary}--\r\n'.encode()
        c = http.client.HTTPSConnection('api.telegram.org')
        c.request('POST', f'/bot{TG_TOKEN}/sendPhoto', body,
            {'Content-Type': f'multipart/form-data; boundary={boundary}'})
        c.getresponse().read()
        c.close()
    except Exception as e:
        print(f'TG fail: {e}')


class Molt:
    def __init__(self):
        self.ui = Eyes()
        self.b1 = Button(BTN_VOICE, pull_up=True, bounce_time=0.2)
        self.b2 = Button(BTN_CAMERA, pull_up=True, bounce_time=0.2)
        self._busy = False
        self._recording = False
        self._stop_ev = threading.Event()

    def voice_flow(self):
        if self._busy:
            return
        self._busy = True
        try:
            self.ui.listening()
            print('Recording...')
            self._stop_ev.clear()
            raw = do_record(MAX_REC, self._stop_ev)

            b = do_boost(raw)
            os.unlink(raw)

            self.ui.thinking()
            print('Transcribing...')
            txt = do_whisper(b)
            os.unlink(b)

            if not txt.strip():
                self.ui.text('No speech detected')
                time.sleep(2)
                self.ui.go_idle()
                self._busy = False
                return

            print(f'> {txt}')
            self.ui.text(txt)
            time.sleep(1)

            self.ui.thinking()
            print('Thinking...')
            resp = do_chat(txt)
            print(f'< {resp}')

            self.ui.text(resp)
            self.ui.speaking()
            print('Speaking...')
            t = do_tts(resp)
            do_play(t)
            os.unlink(t)

            self.ui.text(resp)
            time.sleep(3)

        except Exception as e:
            print(f'ERR: {e}')
            self.ui.text(str(e)[:80])
            time.sleep(3)

        self.ui.go_idle()
        self._busy = False

    def camera_flow(self):
        if self._busy:
            return
        self._busy = True
        try:
            self.ui.camera_look()
            print('Capturing...')
            photo = do_snap()

            do_tg_photo(photo, 'Molt Device')

            self.ui.thinking()
            print('Analyzing...')
            resp = do_chat('What do you see? Be brief.', photo)
            os.unlink(photo)
            print(f'< {resp}')

            self.ui.text(resp)
            self.ui.speaking()
            print('Speaking...')
            t = do_tts(resp)
            do_play(t)
            os.unlink(t)

            self.ui.text(resp)
            time.sleep(3)

        except Exception as e:
            print(f'ERR: {e}')
            self.ui.text(str(e)[:80])
            time.sleep(3)

        self.ui.go_idle()
        self._busy = False

    def on_voice(self):
        if self._recording:
            self._stop_ev.set()
            self._recording = False
        else:
            self._recording = True
            threading.Thread(target=self.voice_flow, daemon=True).start()

    def on_camera(self):
        threading.Thread(target=self.camera_flow, daemon=True).start()

    def run(self):
        print('MOLT DEVICE v7 | Blue=Voice Red=Camera')
        self.b1.when_pressed = self.on_voice
        self.b2.when_pressed = self.on_camera
        self.ui.go_idle()
        try:
            from signal import pause
            pause()
        except KeyboardInterrupt:
            print('\nBye.')
            self.ui.die()


if __name__ == '__main__':
    Molt().run()

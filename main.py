#!/usr/bin/env python3
"""Molt Device v7 — Eyes, ears, voice, camera. 2026-03-09."""

import os, json, time, threading, subprocess, urllib.request, tempfile, random
import http.client, base64
from gpiozero import Button
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
    """Wrapper around OledUI for Cozmo-style eyes."""
    def __init__(self):
        from oled_ui import OledUI
        self._ui = OledUI()
        self._ui.boot_animation()

    def idle(self):
        self._ui.eyes_idle(duration=3600)

    def _stop(self):
        self._ui.stop_animation()
        time.sleep(0.05)

    def listening(self):
        self._stop()
        self._ui.eyes_listening()

    def thinking(self):
        self._stop()
        self._ui.eyes_thinking()

    def speaking(self):
        self._stop()
        self._ui.eyes_speaking()

    def camera_look(self):
        self._stop()
        self._ui.eyes_alert()

    def text(self, txt):
        self._stop()
        self._ui.show_text(txt)

    def go_idle(self):
        self._stop()
        threading.Thread(target=self.idle, daemon=True).start()

    def die(self):
        self._ui.cleanup()


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
        'model': 'tts-1',
        'input': text[:4096],
        'voice': 'fable',
        'speed': 1.1,
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


def do_snap(timeout=1500):
    p = tempfile.mktemp(suffix='.jpg')
    subprocess.run(
        ['rpicam-still', '-o', p, '--width', '640', '--height', '480',
         '--nopreview', '-t', str(timeout), '--vflip', '--hflip'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def do_snap_async():
    """Start a photo capture in the background, return (thread, result_holder)."""
    result = [None]
    def _snap():
        result[0] = do_snap(timeout=1200)
    t = threading.Thread(target=_snap, daemon=True)
    t.start()
    return t, result


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
        photos = []
        try:
            self.ui.listening()

            # Snap photo at recording start (parallel with mic)
            print('Recording + capturing...')
            snap_t, snap_r = do_snap_async()
            self._stop_ev.clear()
            rec_start = time.time()
            raw = do_record(MAX_REC, self._stop_ev)
            rec_dur = time.time() - rec_start

            # Collect first photo
            snap_t.join(timeout=3)
            if snap_r[0]:
                photos.append(snap_r[0])

            # Long recording? Snap another photo
            if rec_dur > 10:
                print('Long recording — extra snap...')
                photos.append(do_snap(timeout=1000))

            # Boost audio (while photo is already done)
            b = do_boost(raw)
            os.unlink(raw)

            self.ui.thinking()
            print('Transcribing...')
            txt = do_whisper(b)
            os.unlink(b)

            if not txt.strip():
                self.ui.text('No speech detected')
                time.sleep(1.5)
                for p in photos:
                    try: os.unlink(p)
                    except: pass
                self.ui.go_idle()
                self._busy = False
                return

            print(f'> {txt}')
            self.ui.text(txt)

            # Use first photo for vision-enhanced chat
            self.ui.thinking()
            print('Thinking (with vision)...')
            img = photos[0] if photos else None
            resp = do_chat(txt, img)
            print(f'< {resp}')

            # Start TTS immediately
            self.ui.speaking()
            print('Speaking...')
            t = do_tts(resp)
            self.ui.text(resp)
            do_play(t)
            os.unlink(t)

            self.ui.text(resp)
            time.sleep(2)

        except Exception as e:
            print(f'ERR: {e}')
            self.ui.text(str(e)[:80])
            time.sleep(3)

        # Cleanup photos
        for p in photos:
            try: os.unlink(p)
            except: pass

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

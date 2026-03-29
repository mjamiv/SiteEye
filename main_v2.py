#!/usr/bin/env python3
"""SiteEye v2 — Pi Zero 2W + Whisplay HAT + IMX500

Full pipeline:
  - Button tap: voice recording → Whisper STT → Molt → TTS → speaker + LCD
  - Button hold (>1s): camera snap → GPT-4o vision → TTS → speaker + LCD
  - LCD shows premium AI assistant face + response text
  - RGB LED indicates state

Uses WhisPlayBoard's built-in button callbacks (no separate GPIO init).
Display renders at controlled rate to prevent flicker.
"""

import os
import sys
import time
import json
import base64
import signal
import subprocess
import threading
import tempfile
import queue
import requests
from datetime import datetime

sys.path.insert(0, '/home/pi-molt/Whisplay/Driver')

from lcd_ui import LcdUI, STATE_IDLE, STATE_LISTENING, STATE_THINKING, STATE_SPEAKING, STATE_CAMERA, STATE_ERROR, STATE_BOOT

# --- Config ---
PROXY_URL = os.environ.get("SITEEYE_PROXY", "https://molted.tail4a98c5.ts.net")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8358560979:AAHEPmk-qQg9RsmrIR2cXyNP4i4u_Hqtl2U")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8217278203")
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
MAX_RECORD_SECONDS = 30
BUTTON_HOLD_THRESHOLD = 1.0  # seconds for camera mode
DOUBLE_TAP_WINDOW = 0.4  # seconds — two presses within this = double tap

# Audio device
AUDIO_DEV = "plughw:0,0"
RECORD_FMT = "S16_LE"
RECORD_RATE = "16000"
RECORD_CHANNELS = "1"

# Display target FPS
TARGET_FPS = 6
FRAME_INTERVAL = 1.0 / TARGET_FPS

# Boot animation frame count (matches lcd_ui boot sequence phases)
BOOT_FRAMES = 48  # Must exceed highest frame in _draw_boot phases


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


class SiteEye:
    def __init__(self):
        self.ui = LcdUI()
        self.board = self.ui.board
        self._running = True
        self._recording = False
        self._record_proc = None
        self._press_time = 0
        self._busy = False

        # Audio feedback files
        self._base_dir = os.path.dirname(os.path.abspath(__file__))
        self._press_time = 0
        self._held_long = False
        self._press_id = 0
        self._tap_count = 0
        self._dispatch_timer = None
        self._live_mode = False       # Gemini Live streaming active
        self._live_session_id = None  # Current live session ID
        self._live_thread = None      # Background streaming thread

        # Register button callbacks
        self.board.button_press_callback = self._on_button_press
        self.board.button_release_callback = self._on_button_release
        log("Button registered via WhisPlayBoard callbacks")

        # Set volume to max
        try:
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker", "100%"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker AC Volume", "5"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker DC Volume", "5"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Playback", "100%"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Headphone", "100%"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Capture", "80%"],
                           capture_output=True, timeout=5)
            log("All volume controls maxed")
        except Exception:
            pass

    def _send_telegram(self, text, image_path=None):
        """Send text/photo to Telegram — mirrors device activity to phone."""
        if not TELEGRAM_BOT_TOKEN:
            return
        try:
            if image_path and os.path.exists(image_path):
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                with open(image_path, "rb") as f:
                    requests.post(url,
                        data={"chat_id": TELEGRAM_CHAT_ID, "caption": text[:1024]},
                        files={"photo": f}, timeout=15)
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        except Exception as e:
            log(f"Telegram send failed: {e}")

    def _toggle_live_mode(self):
        """Double-tap: toggle Gemini Live streaming conversation on/off."""
        if self._live_mode:
            # Stop live mode
            self._stop_live()
        else:
            # Start live mode
            self._start_live()

    def _start_live(self):
        """Start Gemini Live streaming session."""
        self._play_feedback("click.wav")
        log("🔴 Starting Gemini Live mode")
        self.ui.set_status("LIVE - Connecting...")
        self.ui.set_state(STATE_LISTENING)

        try:
            r = requests.post(f"{PROXY_URL}/live/start", timeout=10)
            if r.status_code == 200:
                data = r.json()
                self._live_session_id = data.get("session_id")
                self._live_mode = True
                log(f"🔴 Live session: {self._live_session_id}")
                self.ui.set_status("LIVE - Speak naturally")

                # Start background audio streaming
                self._live_thread = threading.Thread(target=self._live_audio_loop, daemon=True)
                self._live_thread.start()
            else:
                log(f"Live start failed: {r.status_code}")
                self.ui.set_status("Live failed")
                self._play_feedback("error.wav")
                time.sleep(2)
                self.ui.set_status("")
                self.ui.set_state(STATE_IDLE)
        except Exception as e:
            log(f"Live start error: {e}")
            self.ui.set_status("Live failed")
            self._play_feedback("error.wav")
            time.sleep(2)
            self.ui.set_status("")
            self.ui.set_state(STATE_IDLE)

    def _stop_live(self):
        """Stop Gemini Live session."""
        log("⬛ Stopping Gemini Live mode")
        self._live_mode = False

        if self._live_session_id:
            try:
                requests.post(f"{PROXY_URL}/live/stop",
                    json={"session_id": self._live_session_id}, timeout=5)
            except Exception:
                pass
            self._live_session_id = None

        # Kill any running arecord
        try:
            subprocess.run(["killall", "arecord"], capture_output=True, timeout=2)
        except Exception:
            pass

        self._play_feedback("click.wav")
        self.ui.set_status("")
        self.ui.response_text = ""
        self.ui.set_state(STATE_IDLE)
        self._busy = False
        log("⬛ Live mode ended")

    def _live_audio_loop(self):
        """Continuous streaming: record → send → receive → play concurrently.
        
        Uses persistent arecord/aplay processes instead of per-chunk subprocess calls.
        Two threads: send_loop reads mic and POSTs to proxy, play_loop writes response audio.
        """
        self._busy = True
        play_queue = queue.Queue(maxsize=50)
        error_count = [0]

        # Start continuous arecord (streams raw PCM to stdout, no duration limit)
        try:
            record_proc = subprocess.Popen(
                ["arecord", "-D", AUDIO_DEV, "-f", "S16_LE", "-r", "16000",
                 "-c", "1", "-t", "raw"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            log(f"Failed to start arecord: {e}")
            self._busy = False
            return

        def send_loop():
            """Read 8000-byte chunks from mic, POST to proxy, queue response audio."""
            while self._live_mode and self._live_session_id:
                try:
                    # 8000 bytes = 4000 samples = 0.25s at 16kHz 16-bit mono
                    chunk = record_proc.stdout.read(8000)
                    if not chunk:
                        log("arecord stream ended")
                        break

                    r = requests.post(
                        f"{PROXY_URL}/live/audio?session_id={self._live_session_id}",
                        data=chunk,
                        headers={"Content-Type": "application/octet-stream"},
                        timeout=3
                    )

                    if r.status_code == 200 and len(r.content) > 100:
                        # Got response audio — queue for playback
                        try:
                            play_queue.put_nowait(r.content)
                        except queue.Full:
                            pass  # drop oldest if queue full
                        self.ui.set_state(STATE_SPEAKING)
                        self.ui.set_status("LIVE - Speaking")
                        error_count[0] = 0
                    elif r.status_code == 204:
                        self.ui.set_state(STATE_LISTENING)
                        self.ui.set_status("LIVE - Listening")
                        error_count[0] = 0
                    elif r.status_code == 404 or r.status_code == 410:
                        log(f"Session gone ({r.status_code}), stopping live")
                        self._live_mode = False
                        break
                    else:
                        error_count[0] += 1

                except requests.exceptions.Timeout:
                    error_count[0] += 1
                except Exception as e:
                    log(f"Send loop error: {e}")
                    error_count[0] += 1
                    if error_count[0] > 10:
                        log("Too many errors, stopping live mode")
                        self._live_mode = False
                        break
                    time.sleep(0.1)

        def play_loop():
            """Play response audio through continuous aplay process."""
            play_proc = None
            try:
                play_proc = subprocess.Popen(
                    ["aplay", "-D", AUDIO_DEV, "-f", "S16_LE", "-r", "24000",
                     "-c", "1", "-t", "raw"],
                    stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
            except Exception as e:
                log(f"Failed to start aplay: {e}")
                return

            while self._live_mode:
                try:
                    audio = play_queue.get(timeout=1)
                    if play_proc.poll() is not None:
                        # aplay died, restart it
                        try:
                            play_proc = subprocess.Popen(
                                ["aplay", "-D", AUDIO_DEV, "-f", "S16_LE", "-r", "24000",
                                 "-c", "1", "-t", "raw"],
                                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
                            )
                        except Exception:
                            break
                    play_proc.stdin.write(audio)
                    play_proc.stdin.flush()
                except queue.Empty:
                    continue
                except (BrokenPipeError, OSError):
                    log("aplay pipe broken, restarting")
                    try:
                        play_proc = subprocess.Popen(
                            ["aplay", "-D", AUDIO_DEV, "-f", "S16_LE", "-r", "24000",
                             "-c", "1", "-t", "raw"],
                            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
                        )
                    except Exception:
                        break

            if play_proc and play_proc.poll() is None:
                try:
                    play_proc.stdin.close()
                    play_proc.terminate()
                    play_proc.wait(timeout=2)
                except Exception:
                    try:
                        play_proc.kill()
                    except Exception:
                        pass

        def text_poll_loop():
            """Periodically check for text from Gemini and update display."""
            while self._live_mode and self._live_session_id:
                try:
                    r = requests.get(
                        f"{PROXY_URL}/live/status?session_id={self._live_session_id}",
                        timeout=2)
                    if r.status_code == 200:
                        data = r.json()
                        text = data.get("text", "")
                        if text:
                            self.ui.response_text = text
                            threading.Thread(target=self._send_telegram,
                                args=(f"🔴 LIVE\n{text}",), daemon=True).start()
                except Exception:
                    pass
                time.sleep(1.5)

        # Launch all threads
        send_thread = threading.Thread(target=send_loop, daemon=True)
        play_thread = threading.Thread(target=play_loop, daemon=True)
        text_thread = threading.Thread(target=text_poll_loop, daemon=True)
        send_thread.start()
        play_thread.start()
        text_thread.start()

        log("🔴 Live streaming threads started")

        # Wait until live mode ends
        while self._live_mode:
            time.sleep(0.2)

        # Cleanup
        try:
            record_proc.terminate()
            record_proc.wait(timeout=2)
        except Exception:
            try:
                record_proc.kill()
            except Exception:
                pass

        # Wait for threads to finish
        send_thread.join(timeout=3)
        play_thread.join(timeout=3)

        self._busy = False
        log("⬛ Live streaming threads stopped")

    def _pcm_to_wav(self, pcm_data, wav_path, sample_rate=24000):
        """Convert raw PCM bytes to a WAV file for aplay."""
        import struct
        with open(wav_path, "wb") as f:
            data_size = len(pcm_data)
            # WAV header
            f.write(b'RIFF')
            f.write(struct.pack('<I', 36 + data_size))
            f.write(b'WAVEfmt ')
            f.write(struct.pack('<IHHIIHH', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
            f.write(b'data')
            f.write(struct.pack('<I', data_size))
            f.write(pcm_data)

    def _play_feedback(self, name):
        """Play a short audio feedback file (non-blocking)."""
        path = os.path.join(self._base_dir, "assets", name)
        if os.path.exists(path):
            threading.Thread(target=lambda: subprocess.run(
                ["aplay", "-D", AUDIO_DEV, path],
                capture_output=True, timeout=5
            ), daemon=True).start()

    def _on_button_press(self):
        """Button pressed."""
        self._press_time = time.time()
        self._held_long = False
        self._press_id += 1
        current_id = self._press_id

        # During recording, any press = stop
        if self._recording:
            self._play_feedback("click.wav")
            self._stop_recording()
            return

        # During live mode, any press = stop live
        if self._live_mode:
            self._stop_live()
            return

        if self._busy:
            return

        self._play_feedback("click.wav")

        # Cancel any pending single-tap dispatch
        if self._dispatch_timer and self._dispatch_timer.is_alive():
            self._dispatch_timer.cancel()
            self._dispatch_timer = None

        # Hold detection — runs in background
        def _check_hold():
            time.sleep(BUTTON_HOLD_THRESHOLD)
            if current_id == self._press_id and not self._busy:
                self._held_long = True
                self._play_feedback("camera_beep.wav")
                self.ui.set_status("Release to capture")

        threading.Thread(target=_check_hold, daemon=True).start()

    def _on_button_release(self):
        """Button released — route to voice, camera, or info."""
        if self._busy or self._recording:
            return

        duration = time.time() - self._press_time
        if duration < 0.05:
            return

        # Long press = camera
        if self._held_long or duration > BUTTON_HOLD_THRESHOLD:
            self._tap_count = 0
            threading.Thread(target=self._camera_flow, daemon=True).start()
            return

        # Short tap — count it
        self._tap_count += 1

        if self._tap_count == 1:
            # First tap — wait to see if second comes
            def _dispatch():
                if self._tap_count == 1 and not self._busy:
                    self._tap_count = 0
                    self._voice_flow()
                self._tap_count = 0

            self._dispatch_timer = threading.Timer(DOUBLE_TAP_WINDOW, _dispatch)
            self._dispatch_timer.daemon = True
            self._dispatch_timer.start()

        elif self._tap_count >= 2:
            # Double tap — cancel pending voice dispatch
            self._tap_count = 0
            if self._dispatch_timer:
                self._dispatch_timer.cancel()
                self._dispatch_timer = None
            threading.Thread(target=self._toggle_live_mode, daemon=True).start()

    def _voice_flow(self):
        """Full voice pipeline: record → proxy → TTS → speaker."""
        if self._busy:
            return
        self._busy = True

        log("\U0001f399 Voice flow started")
        self.ui.set_status("Listening")
        self.ui.set_state(STATE_LISTENING)

        audio_path = "/tmp/siteeye_voice.wav"
        try:
            proc = subprocess.Popen(
                ["arecord", "-D", AUDIO_DEV, "-f", RECORD_FMT, "-r", RECORD_RATE,
                 "-c", RECORD_CHANNELS, "-d", str(MAX_RECORD_SECONDS), audio_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._record_proc = proc
            self._recording = True
            log("Recording... (press button to stop)")

            start = time.time()
            while self._recording and (time.time() - start) < MAX_RECORD_SECONDS:
                elapsed = int(time.time() - start)
                self.ui.set_status(f"Recording {elapsed}s — press to stop")
                time.sleep(0.1)
                if proc.poll() is not None:
                    break

            self._stop_recording()
        except Exception as e:
            log(f"Record error: {e}")
            self.ui.set_state(STATE_ERROR, "Record failed")
            self._play_feedback("error.wav")
            time.sleep(2)
            self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
            log("Recording too short")
            self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        # Capture background image for context
        img_path = self._capture_photo()

        self.ui.set_status("Processing")
        self.ui.set_state(STATE_THINKING)
        log("\U0001f504 Sending to proxy...")

        try:
            files = {"audio": ("voice.wav", open(audio_path, "rb"), "audio/wav")}
            if img_path:
                files["image"] = ("snap.jpg", open(img_path, "rb"), "image/jpeg")

            r = requests.post(f"{PROXY_URL}/voice_all", files=files, timeout=60)

            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass

            if r.status_code == 200:
                data = r.json()
                transcription = data.get("transcription", "")
                response = data.get("response", "")
                audio_b64 = data.get("audio")

                log(f"\U0001f4dd You: {transcription}")
                log(f"\U0001f916 Molt: {response}")

                # Mirror to Telegram
                threading.Thread(target=self._send_telegram,
                    args=(f"🎙 You: {transcription}\n\n🤖 {response}",), daemon=True).start()

                self.ui.set_status("Speaking")
                self.ui.set_state(STATE_SPEAKING, response)

                if audio_b64:
                    self._play_audio_b64(audio_b64)
                else:
                    time.sleep(2)

                # Keep text visible briefly, then clear
                time.sleep(3)
                self.ui.response_text = ""
            else:
                log(f"\u274c Proxy error: {r.status_code}")
                self.ui.set_status("Error")
                self.ui.set_state(STATE_ERROR, f"Error {r.status_code}")
                time.sleep(2)
        except Exception as e:
            log(f"\u274c {e}")
            self.ui.set_state(STATE_ERROR, str(e)[:40])
            time.sleep(2)

        for p in [audio_path, img_path]:
            try:
                if p:
                    os.remove(p)
            except Exception:
                pass

        self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
        self._busy = False

    def _camera_flow(self):
        """Camera pipeline: capture → show still → vision → TTS."""
        if self._busy:
            return
        self._busy = True

        log("\U0001f4f7 Camera flow started")
        self.ui.set_status("Capturing...")
        self.ui.set_state(STATE_CAMERA)
        self._play_feedback("click.wav")

        img_path = self._capture_photo()
        if not img_path:
            log("\u274c Camera failed")
            self.ui.set_state(STATE_ERROR, "Camera failed")
            self._play_feedback("error.wav")
            time.sleep(2)
            self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        # Show captured still on LCD
        self.ui.show_captured_image(img_path)
        log("\U0001f504 Sending to proxy for vision...")

        try:
            with open(img_path, "rb") as f:
                r = requests.post(f"{PROXY_URL}/vision",
                    files={"image": ("snap.jpg", f, "image/jpeg")},
                    data={"prompt": "What do you see? Be concise and conversational."},
                    timeout=60)

            if r.status_code == 200:
                data = r.json()
                response = data.get("response", "No response")
                log(f"\U0001f916 {response}")

                self.ui.set_photo_text(response)

                # Mirror photo + response to Telegram
                threading.Thread(target=self._send_telegram,
                    args=(f"📷 SiteEye\n\n🤖 {response}", img_path), daemon=True).start()

                try:
                    tts_r = requests.post(f"{PROXY_URL}/tts",
                        json={"text": response}, timeout=60)
                    if tts_r.status_code == 200 and len(tts_r.content) > 100:
                        self._play_audio_raw(tts_r.content)
                    else:
                        log(f"\u26a0\ufe0f TTS error: status={tts_r.status_code} len={len(tts_r.content)}")
                        time.sleep(3)
                except Exception as e:
                    log(f"\u26a0\ufe0f TTS failed: {e}")
                    time.sleep(3)

                # Keep photo + text visible briefly after speech
                time.sleep(4)
            else:
                log(f"\u274c Vision error: {r.status_code}")
                self.ui.set_photo_text(f"Error {r.status_code}")
                time.sleep(3)
        except Exception as e:
            log(f"\u274c {e}")
            self.ui.set_photo_text(str(e)[:40])
            time.sleep(3)

        self.ui.clear_photo()

        try:
            os.remove(img_path)
        except Exception:
            pass

        self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
        self._busy = False

    def _capture_photo(self):
        path = "/tmp/siteeye_snap.jpg"
        try:
            subprocess.run(
                ["rpicam-still", "-o", path, "--width", str(CAPTURE_WIDTH),
                 "--height", str(CAPTURE_HEIGHT), "--nopreview", "-t", "1500",
                 "--vflip", "--hflip"],
                capture_output=True, timeout=15
            )
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
        except Exception as e:
            log(f"Camera error: {e}")
        return None

    def _stop_recording(self):
        self._recording = False
        if self._record_proc and self._record_proc.poll() is None:
            self._record_proc.terminate()
            try:
                self._record_proc.wait(timeout=2)
            except Exception:
                self._record_proc.kill()
        self._record_proc = None

    def _play_audio_b64(self, audio_b64):
        try:
            audio_bytes = base64.b64decode(audio_b64)
            self._play_audio_raw(audio_bytes)
        except Exception as e:
            log(f"Playback error: {e}")

    def _play_audio_raw(self, audio_bytes):
        try:
            tmp_path = "/tmp/siteeye_tts.wav"
            with open(tmp_path, "wb") as f:
                f.write(audio_bytes)
            subprocess.run(
                ["aplay", "-D", AUDIO_DEV, tmp_path],
                capture_output=True, timeout=120
            )
            os.remove(tmp_path)
        except Exception as e:
            log(f"Playback error: {e}")

    def _display_loop(self):
        while self._running:
            frame_start = time.time()
            try:
                self.ui.render_frame()
            except Exception as e:
                log(f"Display error: {e}")

            elapsed = time.time() - frame_start
            sleep_time = FRAME_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _keyboard_loop(self):
        while self._running:
            try:
                cmd = input("").strip().lower()
                if cmd == "v":
                    threading.Thread(target=self._voice_flow, daemon=True).start()
                elif cmd == "c":
                    threading.Thread(target=self._camera_flow, daemon=True).start()
                elif cmd == "l":
                    threading.Thread(target=self._toggle_live_mode, daemon=True).start()
                elif cmd == "q":
                    if self._live_mode:
                        self._stop_live()
                    self._running = False
                    break
                elif cmd == "s":
                    if self._live_mode:
                        self._stop_live()
                    elif self._recording:
                        self._stop_recording()
            except (EOFError, KeyboardInterrupt):
                self._running = False
                break

    def run(self):
        log("\u2550\u2550\u2550 SiteEye v2 \u2014 Whisplay + IMX500 \u2550\u2550\u2550")
        log(f"Proxy: {PROXY_URL}")

        # Boot animation — chime plays during progress bar phase
        self.ui.set_state(STATE_BOOT)
        chime_played = False
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for i in range(BOOT_FRAMES):
            frame_start = time.time()
            self.ui.render_frame()

            # Play chime at frame 8 (when progress bar appears)
            if i == 8 and not chime_played:
                chime_path = os.path.join(base_dir, "assets", "chime.wav")
                if os.path.exists(chime_path):
                    threading.Thread(target=lambda: subprocess.run(
                        ["aplay", "-D", AUDIO_DEV, chime_path],
                        capture_output=True, timeout=10
                    ), daemon=True).start()
                    chime_played = True

            elapsed = time.time() - frame_start
            if FRAME_INTERVAL - elapsed > 0:
                time.sleep(FRAME_INTERVAL - elapsed)

        # Health check
        try:
            r = requests.get(f"{PROXY_URL}/health", timeout=5)
            if r.status_code == 200:
                log("\u2705 Proxy connected")
                self.ui.set_status("Connected")
            else:
                log("\u26a0\ufe0f Proxy unhealthy")
                self.ui.set_status("Proxy error")
        except Exception:
            log("\u26a0\ufe0f Proxy unreachable")
            self.ui.set_status("Offline")

        self.ui.set_status(""); self.ui.set_state(STATE_IDLE)

        # Voice announcement (chime already played during boot)
        startup_wav = os.path.join(base_dir, "assets", "startup.wav")
        if os.path.exists(startup_wav):
            try:
                subprocess.run(["aplay", "-D", AUDIO_DEV, startup_wav],
                               capture_output=True, timeout=10)
            except Exception:
                pass
        log("\U0001f50a Startup audio played")

        # Start display loop
        display_thread = threading.Thread(target=self._display_loop, daemon=True)
        display_thread.start()

        log("\nControls:")
        log("  Button tap = voice | Button hold (>1s) = camera")
        log("  Keyboard: v=voice c=camera l=live s=stop q=quit\n")

        if sys.stdin.isatty():
            try:
                self._keyboard_loop()
            except Exception:
                pass
        else:
            log("Headless mode \u2014 button only")
            try:
                while self._running:
                    time.sleep(1)
            except Exception:
                pass

        log("Shutting down...")
        self._running = False
        self.ui.cleanup()
        log("Goodbye!")


def main():
    app = SiteEye()

    def handle_signal(sig, frame):
        app._running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    app.run()


if __name__ == "__main__":
    main()

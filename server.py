"""SiteEye Proxy — Whisper STT + Vision + OpenClaw Gateway for Pi Zero 2W"""
import os
import base64
import tempfile
import time
from datetime import datetime
import requests
from flask import Flask, request, jsonify, send_file
from openai import OpenAI

app = Flask(__name__)

# Conversation memory — persists across button presses
conversation_history = []
HISTORY_MAX = 20          # keep last 20 exchanges (10 back-and-forth)
HISTORY_TIMEOUT = 300     # clear after 5 min silence
last_interaction = 0.0


def history_append(role, content):
    """Add a message to history, trimming old entries and resetting timeout."""
    global last_interaction
    now = time.time()
    if now - last_interaction > HISTORY_TIMEOUT and last_interaction > 0:
        conversation_history.clear()
    last_interaction = now
    conversation_history.append({"role": role, "content": content})
    while len(conversation_history) > HISTORY_MAX:
        conversation_history.pop(0)


def get_history_messages(system_prompt):
    """Build messages list with system prompt + conversation history."""
    return [{"role": "system", "content": system_prompt}] + list(conversation_history)


# --- OpenAI clients ---
whisper_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# --- OpenClaw gateway (optional — falls back to OpenAI if not set) ---
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "")
USE_OPENCLAW = bool(OPENCLAW_URL and OPENCLAW_TOKEN)
DEVICE_MODEL = "anthropic/claude-sonnet-4-6"
OPENAI_CHAT_MODEL = "gpt-4o"


def ai_chat(messages, model=None, max_tokens=120):
    """Send a chat request — uses OpenClaw if configured, otherwise OpenAI directly."""
    if USE_OPENCLAW:
        resp = requests.post(
            OPENCLAW_URL,
            headers={"Authorization": f"Bearer {OPENCLAW_TOKEN}", "Content-Type": "application/json"},
            json={"model": model or DEVICE_MODEL, "max_tokens": max_tokens, "messages": messages},
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise Exception(f"Gateway error {resp.status_code}")
    else:
        resp = whisper_client.chat.completions.create(
            model=OPENAI_CHAT_MODEL, max_tokens=max_tokens, messages=messages
        )
        return resp.choices[0].message.content

# --- System prompts ---
DEVICE_SYSTEM = """You are Molt — Michael's AI on his wearable device. Spoken aloud through earphones.

RULES:
- Two to three sentences. Concise but actually useful.
- No markdown, bullets, asterisks, emojis.
- No filler. No "certainly" or "great question." Just answer.
- Contractions. Fragments. Punchy.
- Numbers spelled out. Abbreviations spoken.
- You're the guy in his ear. Fast and helpful."""

VISION_SYSTEM = """You are Molt — Michael Martello's AI assistant on his wearable device. He's a bridge engineer. You're spoken aloud through earphones.

An image may be attached. IGNORE IT COMPLETELY unless Michael explicitly asks about what he's looking at, what's in front of him, or says "what do you see." The image is passive background context — treat it like peripheral vision. Never mention it, reference it, or describe it unless directly asked.

RULES:
- Two to three sentences. Concise but useful.
- No markdown, bullets, emojis.
- Answer HIS QUESTION. Not the image.
- You know Michael personally. You're his AI. Act like it.
- Contractions. Punchy."""


@app.route("/voice", methods=["POST"])
def voice():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file"}), 400

    audio = request.files["audio"]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio.save(tmp.name)
        try:
            with open(tmp.name, "rb") as f:
                result = whisper_client.audio.transcriptions.create(model="whisper-1", file=f)
            transcription = result.text
        finally:
            os.unlink(tmp.name)

    # Check if image was also sent (voice + vision combo)
    img_content = None
    if "image" in request.files:
        img_bytes = request.files["image"].read()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        img_content = {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}

    if img_content:
        try:
            from openai import OpenAI as _OAI
            vision_client = _OAI(api_key=os.environ.get("OPENAI_API_KEY"))
            resp = vision_client.chat.completions.create(
                model="gpt-4o",
                max_tokens=150,
                messages=[
                    {"role": "system", "content": VISION_SYSTEM},
                    {"role": "user", "content": [
                        {"type": "text", "text": transcription},
                        img_content
                    ]}
                ]
            )
            assistant_text = resp.choices[0].message.content
        except Exception as e:
            assistant_text = f"Vision error: {str(e)[:60]}"
    else:
        try:
            assistant_text = ai_chat([
                {"role": "system", "content": DEVICE_SYSTEM},
                {"role": "user", "content": f"[Voice from Molt Device] {transcription}"},
            ])
        except requests.exceptions.Timeout:
            assistant_text = "Thinking too hard. Try again."
        except Exception as e:
            assistant_text = f"Error: {str(e)[:50]}"

    return jsonify({"transcription": transcription, "response": assistant_text})


@app.route("/chat", methods=["POST"])
def chat():
    """Text chat endpoint."""
    data = request.get_json()
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "No text"}), 400

    try:
        history_append("user", text)
        assistant_text = ai_chat(get_history_messages(DEVICE_SYSTEM))
        history_append("assistant", assistant_text)
    except requests.exceptions.Timeout:
        assistant_text = "Thinking too hard. Try again."
    except Exception as e:
        assistant_text = f"Error: {str(e)[:50]}"

    return jsonify({"response": assistant_text})


@app.route("/vision", methods=["POST"])
def vision():
    """Vision endpoint — GPT-4o via OpenClaw gateway."""
    if request.is_json:
        data = request.get_json()
        img_b64 = data.get("image", "")
        prompt = data.get("text", "What do you see? Be brief.")
    elif "image" in request.files:
        img_bytes = request.files["image"].read()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        prompt = request.form.get("prompt", "What do you see? Be brief.")
    else:
        return jsonify({"error": "No image"}), 400

    try:
        assistant_text = ai_chat([
            {"role": "system", "content": VISION_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]}
        ], model="openai/gpt-4o-mini")
    except requests.exceptions.Timeout:
        assistant_text = "Thinking too hard. Try again."
    except Exception as e:
        assistant_text = f"Vision error: {str(e)[:60]}"

    return jsonify({"response": assistant_text, "prompt": prompt})


@app.route("/vision_tts", methods=["POST"])
def vision_tts():
    """Combined vision + TTS — one round trip for camera flow."""
    if "image" not in request.files:
        return jsonify({"error": "No image"}), 400

    img_bytes = request.files["image"].read()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    prompt = request.form.get("prompt", "What do you see? Be concise and conversational.")

    # Vision
    try:
        response_text = ai_chat([
            {"role": "system", "content": VISION_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]}
        ], model="openai/gpt-4o")
    except Exception as e:
        response_text = f"Vision error: {str(e)[:60]}"

    # TTS
    tts_audio = None
    try:
        tts_resp = whisper_client.audio.speech.create(
            model="tts-1",
            voice="fable",
            input=response_text[:4096],
            response_format="wav",
            speed=1.1,
        )
        tts_audio = base64.b64encode(tts_resp.content).decode("utf-8")
    except Exception as e:
        print(f"TTS error: {e}")

    return jsonify({"response": response_text, "audio": tts_audio})


@app.route("/voice_all", methods=["POST"])
def voice_all():
    """All-in-one: audio → STT → AI → TTS. One round trip from Pi.

    Accepts multipart: 'audio' (WAV) + optional 'image' (JPEG).
    Returns JSON with transcription, response text, and base64 WAV audio.
    """
    if "audio" not in request.files:
        return jsonify({"error": "No audio file"}), 400

    # 1. Whisper STT
    audio = request.files["audio"]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio.save(tmp.name)
        try:
            with open(tmp.name, "rb") as f:
                result = whisper_client.audio.transcriptions.create(model="whisper-1", file=f)
            transcription = result.text
        finally:
            os.unlink(tmp.name)

    if not transcription.strip():
        return jsonify({"transcription": "", "response": "", "audio": None})

    # 2. Decide if photo is needed based on what the user said
    VISION_TRIGGERS = [
        'see', 'look', 'photo', 'picture', 'image', 'camera',
        'what is this', "what's this", 'what am i', 'who is',
        'who am i', 'read', 'identify', 'recognize', 'describe',
        'in front of', 'looking at', 'show', 'scan', 'inspect',
        'check this', 'what color', 'how many', 'what type',
        'what kind', 'label', 'sign', 'text on',
    ]
    text_lower = transcription.lower()
    needs_vision = any(t in text_lower for t in VISION_TRIGGERS)

    img_b64 = None
    if "image" in request.files:
        img_bytes = request.files["image"].read()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

    try:
        if needs_vision and img_b64:
            assistant_text = ai_chat([
                {"role": "system", "content": VISION_SYSTEM},
                {"role": "user", "content": [
                    {"type": "text", "text": transcription},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}
            ], model="openai/gpt-4o-mini")
        else:
            history_append("user", transcription)
            assistant_text = ai_chat(get_history_messages(DEVICE_SYSTEM))
            history_append("assistant", assistant_text)
    except requests.exceptions.Timeout:
        assistant_text = "Thinking too hard. Try again."
    except Exception as e:
        assistant_text = f"Error: {str(e)[:50]}"

    # 3. TTS
    tts_audio = None
    try:
        tts_resp = whisper_client.audio.speech.create(
            model="tts-1",
            voice="fable",
            input=assistant_text[:4096],
            response_format="wav",
            speed=1.1,
        )
        tts_audio = base64.b64encode(tts_resp.content).decode("utf-8")
    except Exception as e:
        print(f"TTS error: {e}")

    return jsonify({
        "transcription": transcription,
        "response": assistant_text,
        "audio": tts_audio,
    })


@app.route("/tts", methods=["POST"])
def tts():
    """Generate TTS audio from text. Returns raw WAV."""
    text = request.json.get("text", "")
    if not text:
        return jsonify({"error": "No text"}), 400
    try:
        response = whisper_client.audio.speech.create(
            model="tts-1",
            voice="echo",
            input=text[:500],
            response_format="wav",
            speed=1.1,
        )
        return response.content, 200, {"Content-Type": "audio/wav"}
    except Exception as e:
        return jsonify({"error": str(e)[:60]}), 500


@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Return dashboard data: BTC price, next calendar event, weather."""
    import subprocess
    import json
    data = {}

    # BTC Price
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin&vs_currencies=usd&include_24hr_change=true",
            timeout=5
        )
        if r.status_code == 200:
            btc = r.json()["bitcoin"]
            data["btc"] = {
                "price": int(btc["usd"]),
                "change": round(btc.get("usd_24h_change", 0), 1),
            }
    except Exception:
        pass

    # Next calendar event
    try:
        result = subprocess.run(
            ["gog", "calendar", "list", "--all", "--account", "michael.commack@gmail.com",
             "--from", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "--limit", "3", "--json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            events = json.loads(result.stdout)
            if events:
                evt = events[0] if isinstance(events, list) else events.get("events", [{}])[0]
                data["calendar"] = {
                    "summary": evt.get("summary", ""),
                    "start": evt.get("start", ""),
                }
    except Exception:
        pass

    # Weather
    try:
        r = requests.get(
            "https://wttr.in/Baldwin+NY?format=%t|%C&m",
            timeout=5,
            headers={"User-Agent": "siteeye/1.0"},
        )
        if r.status_code == 200:
            parts = r.text.strip().split("|")
            data["weather"] = {
                "temp": parts[0].strip(),
                "condition": parts[1].strip() if len(parts) > 1 else "",
            }
    except Exception:
        pass

    return jsonify(data)


@app.route("/health", methods=["GET"])
def health():
    backend = "openclaw" if USE_OPENCLAW else "openai"
    return jsonify({"status": "ok", "service": "siteeye-proxy", "backend": backend, "vision": True})


if __name__ == "__main__":
    if USE_OPENCLAW:
        print(f"Backend: OpenClaw ({OPENCLAW_URL})")
    else:
        print("Backend: OpenAI direct (no OpenClaw configured)")
    app.run(host="0.0.0.0", port=5757)

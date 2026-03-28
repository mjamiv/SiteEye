#!/usr/bin/env python3
"""Quick camera test — snap and send to proxy for vision analysis"""
import subprocess, requests, os

PROXY_URL = os.environ.get("SITEEYE_PROXY", "https://molted.tail4a98c5.ts.net")

def snap():
    path = "/tmp/snap.jpg"
    cmd = ["rpicam-still", "-o", path, "--width", "640", "--height", "480",
           "--nopreview", "-t", "1500", "--vflip", "--hflip"]
    print("📸 Capturing...")
    subprocess.run(cmd, capture_output=True)
    if os.path.exists(path):
        size = os.path.getsize(path)
        print(f"✅ Captured {size} bytes")
        return path
    print("❌ Capture failed")
    return None

def send_to_proxy(path):
    print("🔄 Sending to proxy for vision analysis...")
    try:
        with open(path, "rb") as f:
            r = requests.post(f"{PROXY_URL}/vision", files={"image": f}, timeout=60)
        if r.ok:
            data = r.json()
            print(f"🤖 Response: {data.get('response', data)}")
        else:
            print(f"❌ Proxy error: {r.status_code}")
    except Exception as e:
        print(f"❌ Error: {e}")

print("SiteEye Camera Test")
print(f"Proxy: {PROXY_URL}")
print("Commands: c = capture + analyze, q = quit")
while True:
    try:
        cmd = input("\n> ").strip().lower()
        if cmd == "c":
            path = snap()
            if path:
                send_to_proxy(path)
        elif cmd == "q":
            break
    except (KeyboardInterrupt, EOFError):
        break

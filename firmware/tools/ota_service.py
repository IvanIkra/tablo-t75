"""Firmware update through the service (§10): pio run -e service -t upload.

The image goes to PUT /api/firmware, the service offers it to the panel, and the panel
downloads it from /firmware.bin itself. Then this waits for the panel to come back with
the version built into the image. TABLO_API_TOKEN comes from the shell or service/.env,
TABLO_SERVICE (default http://192.168.1.50:8765) says where the service is.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / "service" / ".env"
WAIT_S = 240


def api_token() -> str:
    token = os.environ.get("TABLO_API_TOKEN", "")
    if not token and ENV_FILE.exists():
        m = re.search(r"^TABLO_API_TOKEN=(.*)$", ENV_FILE.read_text(), re.M)
        token = m.group(1).strip().strip("\"'") if m else ""
    if not token:
        sys.exit("TABLO_API_TOKEN is not set (shell or service/.env)")
    return token


def panel(base: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{base}/api/status", timeout=10) as r:
            return json.load(r)["devices"].get("tablo")
    except (OSError, ValueError):
        return None  # the service may be busy for a moment


def main() -> None:
    image = Path(sys.argv[1]).read_bytes()
    base = os.environ.get("TABLO_SERVICE", "http://192.168.1.50:8765").rstrip("/")
    m = re.search(rb"fw-\d+\.\d+\+(?:[0-9a-f]{7}(?:-dirty)?|nogit)", image)
    want = m.group().decode() if m else None
    before = panel(base)
    print(f"panel: {before['fw'] if before else 'not connected'}, image: {want or '?'}, {len(image)} bytes")

    req = urllib.request.Request(f"{base}/api/firmware", data=image, method="PUT", headers={
        "Authorization": f"Bearer {api_token()}", "Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print("offered to", ", ".join(json.load(r)["devices"]))
    except urllib.error.HTTPError as e:
        sys.exit(f"service: {e.code} {e.read().decode(errors='replace')}")
    sent = time.time()

    # The panel drops the link, downloads, restarts and says hello again.
    while time.time() - sent < WAIT_S:
        time.sleep(3)
        now = panel(base)
        if now and now["connected_at"] != (before or {}).get("connected_at"):
            if want is None or now["fw"] == want:
                print(f"panel is back on {now['fw']} after {time.time() - sent:.0f} s")
                return
            sys.exit(f"update failed: the panel came back on {now['fw']}, see the panel or its log")
    sys.exit(f"the panel did not come back in {WAIT_S} s")


if __name__ == "__main__":
    main()

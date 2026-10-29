"""Shared helpers: paths, client profiles, state, HTTP, ffmpeg."""
import base64
import json
import os
import subprocess
import time
import urllib.request

PKG = os.path.dirname(os.path.abspath(__file__))
RF_ROOT = os.path.dirname(PKG)                 # reelflow/
REPO = os.path.dirname(RF_ROOT)                # repo root (engine/ lives here)
CLIENTS = os.path.join(RF_ROOT, "clients")
ENGINE = os.path.join(REPO, "engine", "make_reel.py")

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic")


class ReelFlowError(Exception):
    pass


def sh(cmd, check=True):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)
    if check and r.returncode:
        raise ReelFlowError(f"command failed: {cmd if isinstance(cmd, str) else ' '.join(cmd)}\n{r.stderr[-1500:]}")
    return r.stdout


def repo_path(rel):
    return rel if os.path.isabs(rel) else os.path.join(REPO, rel)


def load_client(cid):
    path = os.path.join(CLIENTS, cid, "client.json")
    if not os.path.exists(path):
        raise ReelFlowError(f"no client profile at {path}")
    c = json.load(open(path))
    c["_dir"] = os.path.dirname(path)
    return c


def list_clients():
    return sorted(d for d in os.listdir(CLIENTS) if os.path.exists(os.path.join(CLIENTS, d, "client.json")))


# ---------- state: one JSON per client ----------
# stage: idle -> nudged -> rendering -> in_review -> approved -> posted -> idle
def load_state(c):
    path = os.path.join(c["_dir"], "state.json")
    return json.load(open(path)) if os.path.exists(path) else {"stage": "idle", "history": []}


def save_state(c, st):
    st["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    json.dump(st, open(os.path.join(c["_dir"], "state.json"), "w"), ensure_ascii=False, indent=1)


def outbox(c, kind, payload):
    """Every message for the client lands here; notify.py delivers it (chat routine, email, webhook, WhatsApp)."""
    d = os.path.join(c["_dir"], "outbox")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}.json")
    json.dump({"kind": kind, **payload}, open(path, "w"), ensure_ascii=False, indent=1)
    return path


# ---------- HTTP ----------
def http_json(url, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ReelFlowError(f"HTTP {e.code} from {url.split('?')[0]}: {e.read()[:600].decode(errors='replace')}")


def b64(path):
    return base64.b64encode(open(path, "rb").read()).decode()


# ---------- media ----------
def media_kind(path):
    ext = os.path.splitext(path)[1].lower()
    return "video" if ext in VIDEO_EXT else "image" if ext in IMAGE_EXT else None


def video_duration(path):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


def frame(path, t, out, width=None):
    vf = ["-vf", f"scale={width}:-2"] if width else []
    sh(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", *vf, "-q:v", "3", out])
    return out

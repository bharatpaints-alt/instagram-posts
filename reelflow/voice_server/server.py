"""Free voice clone server (open-source Chatterbox Multilingual, MIT licence) for ReelFlow's "opensource" engine.

POST /   {"text": "...", "language": "hi", "ref_audio_b64": "<client's 30 s sample, any format>",
          "exaggeration": 0.65, "cfg_weight": 0.4}            -> audio/wav
Header:  Authorization: Bearer <OPENVOICE_TOKEN>   (if the env var is set)

Run on any machine with a GPU (CPU works, ~10x slower):
  pip install chatterbox-tts fastapi uvicorn
  OPENVOICE_TOKEN=... uvicorn server:app --host 0.0.0.0 --port 8100
Then set ReelFlow's OPENVOICE_URL=http://<host>:8100/ and OPENVOICE_TOKEN.
"""
import base64
import hashlib
import hmac
import io
import os
import subprocess
import tempfile
import threading

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="ReelFlow voice")
_model, _lock = None, threading.Lock()
REF_DIR = os.environ.get("VOICE_REF_DIR", os.path.join(tempfile.gettempdir(), "voice_refs"))
os.makedirs(REF_DIR, exist_ok=True)


def model():
    global _model
    if _model is None:
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        dev = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        _model = ChatterboxMultilingualTTS.from_pretrained(device=dev)
    return _model


class Req(BaseModel):
    text: str
    language: str = "hi"
    ref_audio_b64: str | None = None
    voice: str | None = None
    exaggeration: float = 0.65
    cfg_weight: float = 0.4
    temperature: float = 0.8


def ref_wav(b64):
    """Cache each client's reference as a clean 24 kHz mono WAV (keyed by content hash)."""
    raw = base64.b64decode(b64)
    path = os.path.join(REF_DIR, hashlib.sha256(raw).hexdigest()[:16] + ".wav")
    if not os.path.exists(path):
        with tempfile.NamedTemporaryFile(delete=False) as t:
            t.write(raw)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", t.name, "-t", "20", "-ar", "24000", "-ac", "1", path], check=True)
        os.remove(t.name)
    return path


@app.post("/")
def tts(r: Req, authorization: str = Header("")):
    want = os.environ.get("OPENVOICE_TOKEN")
    if want and not hmac.compare_digest(authorization, f"Bearer {want}"):
        raise HTTPException(401)
    if not r.text.strip() or len(r.text) > 600:
        raise HTTPException(400, "text must be 1-600 characters")
    import torchaudio
    m = model()
    with _lock:  # one generation at a time per GPU
        wav = m.generate(r.text, language_id=r.language, audio_prompt_path=ref_wav(r.ref_audio_b64) if r.ref_audio_b64 else None,
                         exaggeration=r.exaggeration, cfg_weight=r.cfg_weight, temperature=r.temperature)
    buf = io.BytesIO()
    torchaudio.save(buf, wav.cpu(), m.sr, format="wav")
    return Response(buf.getvalue(), media_type="audio/wav")


@app.get("/healthz")
def health():
    return {"ok": True, "loaded": _model is not None}

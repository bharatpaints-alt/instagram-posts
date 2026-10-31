"""Voice engines. The client records ~30 s once; every Reel's audio is then generated automatically.

engine = "sarvam"      premium clone (SARVAM_API_KEY); the render engine calls Sarvam itself
engine = "opensource"  free clone (Chatterbox-style) on a GPU endpoint (OPENVOICE_URL) or the GitHub-Action voice repo
                       (OPENVOICE_REPO = local clone with push access); one WAV per spoken line -> exact text sync
engine = "gemini"      DEFAULT: Google Gemini TTS, expressive stock voice + style prompt (GEMINI_API_KEY), no clone
engine = "azure"       Microsoft Azure neural voice (free tier 0.5M chars/month; AZURE_SPEECH_KEY), no clone
engine = "piper"       built-in Hindi voice, no clone; used as the last fallback
Returns (spec_fields, engine_used, note).
"""
import json
import os
import shutil
import time
import urllib.request

from .common import ReelFlowError, asset, b64, sh


def _lines(spec):
    """All spoken lines in order: [(scene_index, line_index, text)]; CTA = last scene index."""
    parts = spec["scenes"] + [spec["cta"]]
    return [(i, j, " ".join(t for t, _ in ln["vo"])) for i, sc in enumerate(parts) for j, ln in enumerate(sc.get("lines", []))]


def _sarvam(client, spec, name, work):
    if not (os.environ.get("SARVAM_API_KEY") or os.path.exists(os.path.expanduser("~/.sarvam_key"))):
        raise ReelFlowError("SARVAM_API_KEY not set")
    if not client["voice"].get("sarvam_voice_id"):
        raise ReelFlowError("no Sarvam voice id for this client yet")
    return {"sarvam_voice": client["voice"]["sarvam_voice_id"]}


GEMINI_STYLE = ("Energetic Indian Hindi TV-ad announcer, deep commanding voice, natural Hindi accent, dramatic pauses, "
                "urgent at the start, confident in the middle, excited at the end")


def _gemini(client):
    if not (os.environ.get("GEMINI_API_KEY") or os.path.exists(os.path.expanduser("~/.gemini_key"))):
        raise ReelFlowError("GEMINI_API_KEY not set")
    v = client["voice"]
    return {"gemini_voice": v.get("gemini_voice", "Koda"), "gemini_style": v.get("gemini_style", GEMINI_STYLE)}


def _azure(client):
    if not (os.environ.get("AZURE_SPEECH_KEY") or os.path.exists(os.path.expanduser("~/.azure_speech_key"))):
        raise ReelFlowError("AZURE_SPEECH_KEY not set")
    return {"azure_voice": client["voice"].get("azure_voice", "hi-IN-MadhurNeural")}


def _opensource_http(client, spec, name, out_dir):
    url = os.environ["OPENVOICE_URL"]
    sample = client["voice"].get("sample")
    ref = b64(asset(client, sample)) if sample else None
    for i, j, text in _lines(spec):
        body = json.dumps({"voice": client["voice"]["opensource_ref"], "text": text, "language": "hi",
                           "exaggeration": 0.65, "cfg_weight": 0.4, "ref_audio_b64": ref}).encode()
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json",
                                                              "authorization": f"Bearer {os.environ.get('OPENVOICE_TOKEN', '')}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            open(os.path.join(out_dir, f"seg_{i:02d}_{j:02d}.wav"), "wb").write(r.read())


def _opensource_repo(client, spec, name, out_dir, timeout_min=40):
    repo = os.environ["OPENVOICE_REPO"]
    lines = _lines(spec)
    job = {"exaggeration": 0.65, "cfg_weight": 0.4, "segments": [[[t, "hi"]] for _, _, t in lines]}
    os.makedirs(os.path.join(repo, "jobs"), exist_ok=True)
    json.dump(job, open(os.path.join(repo, "jobs", f"{name}.json"), "w"), ensure_ascii=False, indent=1)
    sh(f"cd {repo} && git add jobs/{name}.json && git commit -qm 'Voice job {name}' && git push -q")
    deadline = time.time() + timeout_min * 60
    outd = os.path.join(repo, "out", name)
    while time.time() < deadline:
        sh(f"cd {repo} && git pull -q", check=False)
        if os.path.isdir(outd) and len([f for f in os.listdir(outd) if f.endswith('.wav')]) >= len(lines):
            for k, (i, j, _) in enumerate(lines):
                shutil.copy(os.path.join(outd, f"seg_{k:02d}.wav"), os.path.join(out_dir, f"seg_{i:02d}_{j:02d}.wav"))
            return
        time.sleep(60)
    raise ReelFlowError(f"open-source voice job {name} did not finish in {timeout_min} min")


def _opensource(client, spec, name, work, voice_dir):
    os.makedirs(voice_dir, exist_ok=True)
    if os.environ.get("OPENVOICE_URL"):
        _opensource_http(client, spec, name, voice_dir)
    elif os.environ.get("OPENVOICE_REPO"):
        _opensource_repo(client, spec, name, voice_dir)
    else:
        raise ReelFlowError("no open-source voice backend (set OPENVOICE_URL or OPENVOICE_REPO)")
    return {"voice_dir": voice_dir}


def prepare(client, spec, name, work, voice_dir):
    want = client["voice"]["engine"]
    order = [want] + [e for e in [client["voice"].get("fallback", "gemini"), "gemini", "azure", "piper"] if e != want]
    errors = []
    for eng in dict.fromkeys(order):
        try:
            if eng == "sarvam":
                return _sarvam(client, spec, name, work), eng, ""
            if eng == "opensource":
                return _opensource(client, spec, name, work, voice_dir), eng, ""
            if eng == "gemini":
                note = f"Clone voice unavailable ({'; '.join(errors)}), Gemini voice used." if errors else ""
                return _gemini(client), eng, note
            if eng == "azure":
                note = f"Clone voice unavailable ({'; '.join(errors)}), Azure voice used." if errors else ""
                return _azure(client), eng, note
            if eng == "piper":
                note = f"Clone voice unavailable ({'; '.join(errors)}), Piper Hindi voice used." if errors else ""
                return {"piper": client["voice"].get("piper_model", "hi_IN-rohan-medium")}, eng, note
        except (ReelFlowError, KeyError, OSError) as e:
            errors.append(f"{eng}: {e}")
    raise ReelFlowError("no voice engine worked: " + "; ".join(errors))

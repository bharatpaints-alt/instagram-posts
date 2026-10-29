"""New client from the sign-up form: profile, logo cards for the Reel, access token, voice sample."""
import os
import re
import secrets

from PIL import Image, ImageDraw

from .common import CLIENTS, ReelFlowError, load_client, save_client, sh

SAMPLE_TEXT_HI = ("नमस्ते! मैं अपनी दुकान से बोल रहा हूँ। हमारे यहाँ हर काम ध्यान से और ईमानदारी से होता है। "
                  "आप एक बार आइए, फ़र्क़ ख़ुद देखिए। कोई भी सवाल हो तो वॉट्सऐप कीजिए, हम तुरंत जवाब देंगे। "
                  "रुको! ये देखिए... कमाल है ना? अभी कॉल कीजिए!")


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "client"
    base, n = s, 2
    while os.path.exists(os.path.join(CLIENTS, s)):
        s, n = f"{base}-{n}", n + 1
    return s


def logo_cards(src, out_dir):
    """White rounded cards like the pilot's: small (top-left on every scene) and big (end card)."""
    im = Image.open(src).convert("RGBA")
    out = {}
    for name, (w, h) in {"logo_small.png": (292, 124), "logo_big.png": (729, 310)}.items():
        pad = int(h * 0.1)
        lg = im.copy()
        lg.thumbnail((w - 2 * pad, h - 2 * pad), Image.LANCZOS)
        card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(card).rounded_rectangle([0, 0, w - 1, h - 1], radius=int(h * 0.14), fill=(255, 255, 255, 255))
        card.alpha_composite(lg, ((w - lg.width) // 2, (h - lg.height) // 2))
        path = os.path.join(out_dir, name)
        card.save(path)
        out[name.split(".")[0]] = os.path.relpath(path, os.path.dirname(out_dir))
    return out


def create_client(form, logo_path=None):
    """form: dict of the sign-up fields. Returns the saved client (with _dir) and its access token."""
    name = (form.get("name") or "").strip()
    wa = re.sub(r"[^0-9 +]", "", form.get("whatsapp") or "").strip()
    if not name or not wa:
        raise ReelFlowError("business name and WhatsApp number are required")
    cid = slug(name)
    d = os.path.join(CLIENTS, cid)
    os.makedirs(os.path.join(d, "assets"), exist_ok=True)
    lines = lambda k: [x.strip() for x in (form.get(k) or "").splitlines() if x.strip()]
    tag = lines("tagline") or [name, ""]
    facts = [f"{name}, {form.get('address', '').strip()}. WhatsApp: {wa}."] + lines("facts")
    if form.get("brands"):
        facts.append("Brands: " + form["brands"].strip())
    c = {"id": cid, "name": name, "owner": form.get("owner", "").strip(), "email": form.get("email", "").strip(),
         "instagram_handle": "@" + (form.get("instagram") or "").strip().lstrip("@"),
         "uplika_connection_id": (form.get("uplika_connection_id") or "").strip(),
         "language": "hi", "city": form.get("city", "").strip(), "whatsapp": wa,
         "address": form.get("address", "").strip(), "tagline": (tag + [""])[:2],
         "tagline_hi": form.get("tagline_hi", "").strip(),
         "brand_line": form.get("brand_line", "").strip(), "facts": facts,
         "niche": {"description": form.get("niche", "").strip(),
                   "youtube_queries": [q.strip() for q in (form.get("youtube_queries") or "").split(",") if q.strip()]
                   or [form.get("niche", name)], "region": "IN"},
         "pronunciation": {}, "hashtags": [h if h.startswith("#") else "#" + h for h in (form.get("hashtags") or "").split()],
         "voice": {"engine": "sarvam" if form.get("plan") == "premium" else "opensource", "fallback": "piper",
                   "sarvam_voice_id": "", "opensource_ref": cid, "piper_model": "hi_IN-rohan-medium", "sample": ""},
         "plan": form.get("plan", "basic"),
         "paths_base": "client",
         "paths": {"inbox": "inbox", "review": "review", "posted_media": "posted", "posted_reels": "posted/reels"},
         "upload_link": "", "raw_base": "", "nudge_time": form.get("nudge_time") or "09:00", "timezone": "Asia/Kolkata"}
    c["_dir"] = d
    if logo_path:
        c["brand_assets"] = logo_cards(logo_path, os.path.join(d, "assets"))
    else:
        c["brand_assets"] = {"logo_small": "assets/logo_small.png", "logo_big": "assets/logo_big.png"}
        text_logo(name, os.path.join(d, "assets"))
    for k in ("inbox", "review", "posted"):
        os.makedirs(os.path.join(d, k), exist_ok=True)
    save_client(c)
    return c, issue_token(c)


def text_logo(name, out_dir):
    """No logo uploaded: the business name on the white card."""
    from .common import REPO
    font = os.path.join(REPO, "engine", "assets", "InterDisplay-Bold.otf")
    from PIL import ImageFont
    im = Image.new("RGBA", (900, 220), (0, 0, 0, 0))
    f = ImageFont.truetype(font, 90)
    ImageDraw.Draw(im).text((450, 110), name[:22], font=f, fill=(20, 20, 20, 255), anchor="mm")
    tmp = os.path.join(out_dir, "_name.png")
    im.crop(im.getbbox() or (0, 0, 900, 220)).save(tmp)
    logo_cards(tmp, out_dir)


def token_path(c):
    return os.path.join(c["_dir"], "secret.txt")


def issue_token(c):
    tok = secrets.token_urlsafe(16)
    open(token_path(c), "w").write(tok)
    return tok


def client_token(c):
    p = token_path(c)
    return open(p).read().strip() if os.path.exists(p) else issue_token(c)


def save_voice_sample(cid, upload_path):
    """Any browser/phone recording -> clean 24 kHz mono WAV, 10-90 s."""
    c = load_client(cid)
    vd = os.path.join(c["_dir"], "voice")
    os.makedirs(vd, exist_ok=True)
    out = os.path.join(vd, "sample.wav")
    sh(["ffmpeg", "-v", "error", "-y", "-i", upload_path, "-af",
        "highpass=f=80,afftdn=nf=-30,loudnorm=I=-16:TP=-1.5", "-ar", "24000", "-ac", "1", out])
    dur = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out]).strip())
    if dur < 10:
        os.remove(out)
        raise ReelFlowError(f"recording is only {dur:.0f} s; please record at least 20-30 seconds")
    c["voice"]["sample"] = "voice/sample.wav"
    c["voice"]["sample_seconds"] = round(dur, 1)
    save_client(c)
    return dur

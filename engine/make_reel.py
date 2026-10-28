#!/usr/bin/env python3
"""Reel engine: photos/videos + a spec (JSON) -> 9:16 Instagram Reel with voiceover, music, logos and CTA.

Usage:  python3 engine/make_reel.py spec.json out.mp4
Needs:  ffmpeg, pip install kokoro-onnx soundfile numpy pillow
The Kokoro voice model (open source, GitHub releases) downloads itself on first run into engine/.cache/.

Spec format: see engine/README.md and engine/example_spec.json.
"""
import json, os, subprocess, sys, urllib.request

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, ".cache")
os.makedirs(CACHE, exist_ok=True)
FONT = os.path.join(HERE, "assets", "InterDisplay-Bold.otf")
FPS = 30
COLORS = {"white": "white", "yellow": "0xFFD23F"}
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
VOICE_CHAIN = ("highpass=f=70,equalizer=f=120:t=q:w=1:g=3,equalizer=f=280:t=q:w=1.2:g=-2,"
               "equalizer=f=3500:t=q:w=1:g=3.5,acompressor=threshold=-20dB:ratio=3.5:attack=8:release=120:makeup=2,"
               "aecho=0.8:0.5:28:0.08")


def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"FAILED: {cmd[:300]}\n{r.stderr[-1500:]}")
    return r.stdout


def p(path):
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


# ---------- voice ----------
def load_tts():
    from kokoro_onnx import Kokoro
    for f in ["kokoro-v1.0.onnx", "voices-v1.0.bin"]:
        dst = os.path.join(CACHE, f)
        if not os.path.exists(dst):
            print("downloading", f)
            urllib.request.urlretrieve(MODEL_URL + f, dst)
    return Kokoro(os.path.join(CACHE, "kokoro-v1.0.onnx"), os.path.join(CACHE, "voices-v1.0.bin"))


def speak(k, style, chunks, speed):
    lang = {"hi": "hi", "en": "en-us"}
    ph = " ".join(k.tokenizer.phonemize(t, lang[l]) for t, l in chunks)
    a, sr = k.create(ph, voice=style, speed=speed, is_phonemes=True)
    return a, sr


PIPER_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"


class Piper:
    """Native Hindi voice (Piper VITS, ONNX). Default 'hi_IN-rohan-medium': male, trained on the IIT Madras
    IndicTTS 'Hindi Mono Male' recordings (license allows commercial use). Phonemes come from the same
    espeak-ng frontend Kokoro uses, so no extra install beyond onnxruntime."""

    def __init__(self, name, kokoro):
        import onnxruntime as ort
        folder = os.path.join(CACHE, "piper", f"vits-piper-{name}")
        if not os.path.exists(folder):
            os.makedirs(os.path.dirname(folder), exist_ok=True)
            print("downloading", name)
            run(f"curl -sSL {PIPER_URL}vits-piper-{name}.tar.bz2 | tar xj -C {os.path.dirname(folder)}")
        cfg = json.load(open(os.path.join(folder, f"{name}.onnx.json")))
        self.map, self.sr, self.k = cfg["phoneme_id_map"], cfg["audio"]["sample_rate"], kokoro
        self.sess = ort.InferenceSession(os.path.join(folder, f"{name}.onnx"))

    def create(self, chunks, speed):
        lang = {"hi": "hi", "en": "en-us"}
        ph = " ".join(self.k.tokenizer.phonemize(t, lang[l]) for t, l in chunks)
        m = self.map
        ids = m["^"] + m["_"]
        for c in ph:
            if c in m:
                ids += m[c] + m["_"]
        ids += m["$"]
        x = np.array([ids], dtype=np.int64)
        a = self.sess.run(None, {"input": x, "input_lengths": np.array([x.shape[1]], dtype=np.int64),
                                 "scales": np.array([0.667, 1.0 / speed, 0.8], dtype=np.float32)})[0]
        return a.squeeze().astype(np.float32), self.sr


class SarvamClone:
    """Cloned voice on Sarvam AI (POST /voices/clone with a saved voice_id). The API key is read from the
    SARVAM_API_KEY env var or ~/.sarvam_key, never from the repo."""

    def __init__(self, voice_id, work):
        key = os.environ.get("SARVAM_API_KEY") or open(os.path.expanduser("~/.sarvam_key")).read().strip()
        self.voice_id, self.work, self.n = voice_id, work, 0
        self.keyfile = os.path.join(work, "sarvam_hdr")
        with open(self.keyfile, "w") as f:
            f.write(f"api-subscription-key: {key}\n")
        os.chmod(self.keyfile, 0o600)

    def create(self, chunks, speed):
        import base64
        text = " ".join(t for t, _ in chunks)
        self.n += 1
        tfile = os.path.join(self.work, f"sv{self.n}.txt")
        open(tfile, "w").write(text)
        out = run(f"curl -sS --fail-with-body https://api.sarvam.ai/voices/clone -H @{self.keyfile} "
                  f"-F voice_id={self.voice_id} -F 'text=<{tfile}' -F language_code=hi-IN -F pace={speed:.2f}")
        d = json.loads(out)
        wav = os.path.join(self.work, f"sv{self.n}.wav")
        open(wav, "wb").write(base64.b64decode(d.get("audio_b64") or d["audio"]))
        a, sr = sf.read(wav, dtype="float32")
        return (a if a.ndim == 1 else a.mean(1)), sr


def build_voice_from_files(spec, work):
    """Use ready-made segment WAVs (e.g. Gaurav's cloned voice from the private voice repo)."""
    folder = p(spec["voice_dir"])
    n = len(spec["scenes"]) + 1
    pauses = [sc.get("pause", 0.4) for sc in spec["scenes"]] + [0.6]
    out, durs, sr = [], [], 24000
    for i in range(n):
        tmp = os.path.join(work, f"seg{i}.wav")
        run(f"ffmpeg -v error -y -i {folder}/seg_{i:02d}.wav -af silenceremove=start_periods=1:start_threshold=-45dB,"
            f"areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse -ar {sr} -ac 1 {tmp}")
        a, _ = sf.read(tmp, dtype="float32")
        out += [a, np.zeros(int(sr * pauses[i]), dtype=np.float32)]
        durs.append(len(a) / sr + pauses[i])
    raw = os.path.join(work, "vo_raw.wav")
    sf.write(raw, np.concatenate(out), sr)
    run(f"ffmpeg -v error -y -i {raw} -af \"highpass=f=70,equalizer=f=3500:t=q:w=1:g=2,"
        f"acompressor=threshold=-20dB:ratio=3:attack=8:release=120:makeup=2\" -ar 24000 {work}/vo.wav")
    return durs


def build_voice(spec, work):
    if spec.get("voice_dir"):
        durs = build_voice_from_files(spec, work)
        return durs, [[] for _ in durs]
    k = load_tts()
    style = None
    piper = Piper(spec["piper"], k) if spec.get("piper") else None
    if spec.get("sarvam_voice"):
        piper = SarvamClone(spec["sarvam_voice"], work)
    for part in spec.get("voice", "hm_omega:0.65,am_onyx:0.35").split(","):
        v, w = part.split(":")
        s = k.get_voice_style(v) * float(w)
        style = s if style is None else style + s

    def speak(k_, style_, chunks, speed):
        return piper.create(chunks, speed) if piper else globals()["speak"](k_, style_, chunks, speed)
    # Each scene is a list of "lines". A line has its own speed, pitch (semitones), gain and pause after it,
    # which is what gives the voice its rise and fall (fast hook, slow dramatic pause, loud offer).
    def lines_of(sc, dspeed, dpause):
        if sc.get("lines"):
            return sc["lines"], sc.get("pause", dpause)
        return [{"vo": sc["vo"], "speed": sc.get("speed", dspeed), "pause": 0}], sc.get("pause", dpause)
    segs = [lines_of(sc, 0.95, 0.4) for sc in spec["scenes"]] + [lines_of(spec["cta"], 0.92, 0.6)]
    out, durs, timings, sr = [], [], [], 24000
    for si, (lines, scene_pause) in enumerate(segs):
        t, tim = 0.0, []
        for li, ln in enumerate(lines):
            a, sr = speak(k, style, ln["vo"], ln.get("speed", 0.95))
            if spec.get("sarvam_voice"):
                ln = {**ln, "pitch": 0}
            if ln.get("pitch") or ln.get("gain"):
                tmp = os.path.join(work, f"ln{si}_{li}")
                sf.write(tmp + "a.wav", a, sr)
                r = 2 ** (ln.get("pitch", 0) / 12)
                run(f"ffmpeg -v error -y -i {tmp}a.wav -af \"rubberband=pitch={r:.4f},volume={ln.get('gain', 0)}dB\" "
                    f"-ar {sr} {tmp}b.wav")
                a, _ = sf.read(tmp + "b.wav", dtype="float32")
            pause = ln.get("pause", 0.12)
            tim.append((t, t + len(a) / sr))
            out += [a.astype(np.float32), np.zeros(int(sr * pause), dtype=np.float32)]
            t += len(a) / sr + pause
        out.append(np.zeros(int(sr * scene_pause), dtype=np.float32))
        durs.append(t + scene_pause)
        timings.append(tim)
    raw = os.path.join(work, "vo_raw.wav")
    sf.write(raw, np.concatenate(out), sr)
    chain = ("highpass=f=70,equalizer=f=3500:t=q:w=1:g=2,acompressor=threshold=-20dB:ratio=3:attack=8:release=120:makeup=2"
             if spec.get("sarvam_voice") else VOICE_CHAIN)
    run(f"ffmpeg -v error -y -i {raw} -af \"{chain}\" -ar 24000 {work}/vo.wav")
    return durs, timings


# ---------- music ----------
def build_sfx(dur, path, whooshes, hits):
    """Whoosh rising into each cut, and a deep hit on big moments (hook, reveal)."""
    sr = 44100
    out = np.zeros(int(sr * (dur + 1)))
    rng = np.random.default_rng(7)
    for tc in whooshes:
        n = int(0.38 * sr)
        i0 = int(max(0, tc - 0.33) * sr)
        noise = rng.standard_normal(n)
        k = np.linspace(0.02, 0.35, n)              # one-pole low-pass opening up = rising whoosh
        y, acc = np.zeros(n), 0.0
        for j in range(n):
            acc += k[j] * (noise[j] - acc)
            y[j] = acc
        env = np.sin(np.linspace(0, np.pi, n)) ** 2
        out[i0:i0 + n] += 0.5 * y * env
    for th in hits:
        n = int(0.7 * sr)
        i0 = int(th * sr)
        kt = np.arange(n) / sr
        out[i0:i0 + n] += 0.9 * np.sin(2 * np.pi * np.cumsum(38 + 80 * np.exp(-kt * 18)) / sr) * np.exp(-kt * 5)
    out = 0.7 * out / (np.max(np.abs(out)) + 1e-9)
    sf.write(path, np.stack([out, out], 1), sr)


def build_music(dur, path, seed=0, bpm=96):
    rng = np.random.default_rng(seed)
    sr = 44100
    beat = 60 / bpm
    t = np.arange(int(sr * dur)) / sr
    out = np.zeros_like(t)
    note = lambda m: 440 * 2 ** ((m - 69) / 12)
    progs = [[[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]],
             [[50, 53, 57], [55, 58, 62], [53, 57, 60], [57, 61, 64]]]
    prog = progs[seed % len(progs)]
    bar = beat * 4
    for ci in range(int(dur / (bar * 2)) + 2):
        chord, st = prog[ci % 4], ci * bar * 2
        seg = (t >= st) & (t < st + bar * 2 + 0.5)
        tt = t[seg] - st
        env = np.minimum(1, tt / 0.6) * np.exp(-np.maximum(0, tt - bar * 2) * 6)
        for n in chord:
            f = note(n)
            out[seg] += 0.05 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt))
        out[seg] += 0.07 * env * np.sin(2 * np.pi * note(chord[0] - 12) * tt)
    for b in range(int(dur / beat) + 1):
        i0, n = int(b * beat * sr), int(0.25 * sr)
        if i0 + n > len(out):
            break
        kt = np.arange(n) / sr
        out[i0:i0 + n] += 0.35 * np.sin(2 * np.pi * np.cumsum(50 + 90 * np.exp(-kt * 30)) / sr) * np.exp(-kt * 9)
        h0, hn = int((b + 0.5) * beat * sr), int(0.05 * sr)
        if h0 + hn < len(out):
            out[h0:h0 + hn] += 0.03 * rng.standard_normal(hn) * np.exp(-np.arange(hn) / sr * 80)
    fi, fo = int(sr), int(sr * 2.5)
    out[:fi] *= np.linspace(0, 1, fi)
    out[-fo:] *= np.linspace(1, 0, fo)
    out = 0.8 * out / (np.max(np.abs(out)) + 1e-9)
    sf.write(path, np.stack([out, out], 1), sr)


# ---------- video ----------
def tf(work, name, text):
    path = os.path.join(work, f"t_{name}.txt")
    open(path, "w").write(text)
    return path


def is_video(path):
    return path.lower().endswith((".mp4", ".mov", ".m4v", ".webm"))


def prep_still(src, crop, out):
    """Crop (optional) and fit to 2160x3840: cover if close to 9:16, else blurred-background fit."""
    from PIL import Image, ImageFilter
    im = Image.open(src).convert("RGB")
    if crop:
        w, h, x, y = crop
        im = im.crop((x, y, x + w, y + h))
    W, H = 2160, 3840
    r = im.width / im.height
    if 0.5 <= r <= 0.62:
        s = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
        x, y = (im.width - W) // 2, (im.height - H) // 2
        im.crop((x, y, x + W, y + H)).save(out)
    else:
        s = max(W / im.width, H / im.height)
        bg = im.resize((int(im.width * s) + 1, int(im.height * s) + 1)).crop((0, 0, W, H))
        bg = bg.filter(ImageFilter.GaussianBlur(40)).point(lambda v: int(v * 0.55))
        s = min(W / im.width, H / im.height)
        fg = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
        bg.save(out)


def pop(fs, st):
    """Font size that springs in from 60% to 110% and settles at 100%."""
    return (f"'{fs}*if(lt(t,{st}+0.16),0.6+0.5*(t-{st})/0.16,if(lt(t,{st}+0.26),1.1-0.1*(t-{st}-0.16)/0.1,1))'")


def big_lines(work, name, lines, st, en, instant=False):
    f, y = [], 300
    for i, (line, col) in enumerate(lines):
        s0 = st + (0 if instant else 0.05) + i * 0.12
        f.append(f"drawtext=fontfile={FONT}:textfile={tf(work, f'{name}_{i}', line)}:fontcolor={COLORS.get(col, col)}:"
                 f"fontsize={pop(88, s0)}:borderw=8:bordercolor=black:x=(w-tw)/2:y={y}:"
                 f"enable='between(t,{s0:.3f},{en:.3f})'")
        y += 110
    return f, y


def text_layers(work, name, sc, dur, tim):
    f, y = [], 300
    lines = sc.get("lines") or []
    shows = [(tim[j][0], ln["show"]) for j, ln in enumerate(lines) if ln.get("show") and j < len(tim)]
    if shows:
        for k, (st, show) in enumerate(shows):
            en = shows[k + 1][0] - 0.02 if k + 1 < len(shows) else dur
            ff, _ = big_lines(work, f"{name}x{k}", show, max(0, st - 0.08), en, instant=(st < 0.2))
            f += ff
    elif sc.get("head"):
        ff, y = big_lines(work, name + "h", sc["head"], 0, dur, instant=sc.get("instant", False))
        f += ff
    if sc.get("sub"):
        f.append(f"drawtext=fontfile={FONT}:textfile={tf(work, name + 's', sc['sub'])}:fontcolor=white:fontsize=56:"
                 f"borderw=5:bordercolor=black:x=(w-tw)/2:y={(y if not shows else 300 + 220) + 20}:"
                 f"alpha='min(1,(t-0.5)/0.3)'")
    says = [(tim[j][0], ln["say"]) for j, ln in enumerate(lines) if ln.get("say") and j < len(tim)]
    if says:
        for k, (st, say) in enumerate(says):
            en = says[k + 1][0] if k + 1 < len(says) else dur
            f.append(f"drawtext=fontfile={FONT}:textfile={tf(work, f'{name}y{k}', say)}:fontcolor=white:fontsize=50:"
                     f"box=1:boxcolor=black@0.7:boxborderw=22:x=(w-tw)/2:y=1360:enable='between(t,{st:.3f},{en:.3f})'")
    elif sc.get("caption"):
        f.append(f"drawtext=fontfile={FONT}:textfile={tf(work, name + 'c', sc['caption'])}:fontcolor=white:fontsize=46:"
                 f"box=1:boxcolor=black@0.65:boxborderw=22:x=(w-tw)/2:y=1380")
    for k, tag in enumerate(sc.get("tags", [])):
        st = tim[tag["line"]][0] if "line" in tag and tag["line"] < len(tim) else tag.get("from", 0)
        en = tag.get("to", dur)
        if isinstance(en, str) and en.startswith("line"):
            en = tim[int(en[4:])][0]
        f.append(f"drawtext=fontfile={FONT}:textfile={tf(work, f'{name}g{k}', tag['text'])}:"
                 f"fontcolor={tag.get('color', 'black')}:fontsize={pop(64, st)}:box=1:"
                 f"boxcolor={COLORS.get(tag.get('bg', 'yellow'), tag.get('bg', 'yellow'))}:boxborderw=18:"
                 f"x={tag.get('x', '60')}:y={tag.get('y', 1180)}:enable='between(t,{st:.3f},{en:.3f})'")
    if sc.get("badge"):
        f.append(f"drawtext=fontfile={FONT}:textfile={tf(work, name + 'b', sc['badge'])}:fontcolor=black:fontsize=40:"
                 f"box=1:boxcolor=0xFFD23F:boxborderw=14:x=w-tw-50:y=150")
    return ",".join(f) if f else "null"


LOOK = "eq=contrast=1.08:saturation=1.15"


def still_clip(work, name, src, crop, zoom, pan, dur, out):
    still = os.path.join(work, name + ".png")
    prep_still(src, crop, still)
    frames = max(1, int(dur * FPS))
    if zoom == "punch":       # fast punch-in, then a slow creep
        z = f"max(1.0+0.05*on/{frames},1.35-0.30*on/9)"
    elif zoom == "out":
        z = f"1.15-0.15*on/{frames}"
    else:
        z = f"1+0.15*on/{frames}"
    zp = f"zoompan=z='{z}':x='(iw-iw/zoom)*{pan}':y='(ih-ih/zoom)/2':d=1:s=1080x1920:fps={FPS}"
    run(f"ffmpeg -v error -y -loop 1 -framerate {FPS} -t {dur:.3f} -i {still} -vf \"{zp},{LOOK}\" "
        f"-c:v libx264 -preset veryfast -crf 17 -pix_fmt yuv420p -r {FPS} -t {dur:.3f} {out}")
    return out


def render_scene(work, i, sc, dur, logo, tim):
    name = f"s{i}"
    layers = text_layers(work, name, sc, dur, tim)
    flash = "" if i == 0 or sc.get("flash") is False else ",fade=in:st=0:d=0.18:color=white"
    out = os.path.join(work, name + ".mp4")
    if sc.get("compare"):
        c = sc["compare"]
        at = c.get("at_line", 1)
        T = max(0.5, (tim[at][0] if at < len(tim) else dur / 2) - 0.1)
        W_ = c.get("wipe", 0.6)
        b = still_clip(work, name + "b", p(c["before"]["media"]), c["before"].get("crop"), c["before"].get("zoom", "in"),
                       c["before"].get("pan", 0.5), T + W_, os.path.join(work, name + "b.mp4"))
        a = still_clip(work, name + "a", p(c["after"]["media"]), c["after"].get("crop"), c["after"].get("zoom", "in"),
                       c["after"].get("pan", 0.5), dur - T, os.path.join(work, name + "a.mp4"))
        run(f"ffmpeg -v error -y -i {b} -i {a} -i {logo} -f lavfi -i color=white:s=14x1920:r={FPS} -filter_complex "
            f"\"[0:v][1:v]xfade=transition=wiperight:duration={W_}:offset={T:.3f}[x];"
            f"[x][3:v]overlay=x='W*(t-{T:.3f})/{W_}-7':y=0:enable='between(t,{T:.3f},{T + W_:.3f})':shortest=1[y];"
            f"[y]{layers}{flash}[v];[v][2:v]overlay=40:130\" -c:v libx264 -preset veryfast -crf 19 "
            f"-pix_fmt yuv420p -r {FPS} -t {dur:.3f} {out}")
        return out
    src = p(sc["media"])
    if is_video(src):
        ss = sc.get("start", 0)
        base = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
                if sc.get("fill", True) else
                "split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:2,"
                "eq=brightness=-0.25[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=0:(H-h)/2")
        run(f"ffmpeg -v error -y -ss {ss} -t {dur} -i \"{src}\" -i {logo} -filter_complex "
            f"\"[0:v]{base},fps={FPS},{LOOK},{layers}{flash}[v];[v][1:v]overlay=40:130\" -an -c:v libx264 -preset veryfast "
            f"-crf 19 -pix_fmt yuv420p -r {FPS} -t {dur} {out}")
    else:
        base = still_clip(work, name + "z", src, sc.get("crop"), sc.get("zoom", "in"), sc.get("pan", 0.5), dur,
                          os.path.join(work, name + "z.mp4"))
        run(f"ffmpeg -v error -y -i {base} -i {logo} -filter_complex "
            f"\"[0:v]{layers}{flash}[v];[v][1:v]overlay=40:130\" -c:v libx264 -preset veryfast -crf 19 "
            f"-pix_fmt yuv420p -r {FPS} -t {dur:.3f} {out}")
    return out


def render_cta(work, spec, dur, bg_media):
    b, c = spec["brand"], spec["cta"]
    bg_media = c.get("bg", bg_media)
    still = os.path.join(work, "cta.png")
    if is_video(p(bg_media)):
        run(f"ffmpeg -v error -y -ss 1 -i \"{p(bg_media)}\" -frames:v 1 {work}/cta_src.png")
        prep_still(f"{work}/cta_src.png", None, still)
    else:
        prep_still(p(bg_media), c.get("bg_crop", spec["scenes"][0].get("crop")), still)
    T = lambda n, s: tf(work, n, s)
    Y = COLORS["yellow"]
    layers = [
        "boxblur=24:3,eq=brightness=-0.42:saturation=0.6",
        f"drawtext=fontfile={FONT}:textfile={T('e3', c['title'])}:fontcolor=white:fontsize=64:x=(w-tw)/2:y=640:alpha='min(1,(t-0.7)/0.4)'",
        f"drawtext=fontfile={FONT}:textfile={T('e4', c['subtitle'])}:fontcolor=white:fontsize=50:x=(w-tw)/2:y=730:alpha='min(1,(t-0.9)/0.4)'",
        "drawbox=x=90:y=880:w=900:h=250:color=0x25D366@0.95:t=fill:enable='gte(t,1.2)'",
        f"drawtext=fontfile={FONT}:textfile={T('e5', c.get('button', 'WhatsApp karein'))}:fontcolor=white:fontsize=50:x=(w-tw)/2:y=910:enable='gte(t,1.2)'",
        f"drawtext=fontfile={FONT}:textfile={T('e6', b['whatsapp'])}:fontcolor=white:fontsize='110*(1+0.045*sin(2*PI*1.6*t))':x=(w-tw)/2:y=1050-th/2:enable='gte(t,1.2)'",
        f"drawtext=fontfile={FONT}:textfile={T('e7', b['address'])}:fontcolor=0xDDDDDD:fontsize=42:x=(w-tw)/2:y=1190:alpha='min(1,(t-1.6)/0.4)'",
        f"drawtext=fontfile={FONT}:textfile={T('e8', b['tagline1'])}:fontcolor=white:fontsize=50:x=(w-tw)/2:y=1360:alpha='min(1,(t-3.5)/0.5)'",
        f"drawtext=fontfile={FONT}:textfile={T('e9', b['tagline2'])}:fontcolor={Y}:fontsize=58:x=(w-tw)/2:y=1430:alpha='min(1,(t-3.7)/0.5)'",
        f"drawtext=fontfile={FONT}:textfile={T('e10', 'Follow ' + b['handle'])}:fontcolor=white:fontsize=40:box=1:boxcolor=black@0.5:boxborderw=16:x=(w-tw)/2:y=1540:alpha='min(1,(t-4.3)/0.5)'",
    ]
    zp = f"zoompan=z='1.1':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=1080x1920:fps={FPS}"
    out = os.path.join(work, "cta.mp4")
    run(f"ffmpeg -v error -y -loop 1 -framerate {FPS} -t {dur} -i {still} -i {p(b['logo_big'])} -filter_complex "
        f"\"[0:v]{zp},{','.join(layers)}[bg];[bg][1:v]overlay=(W-w)/2:250,fade=in:st=0:d=0.18:color=white\" -c:v libx264 -preset veryfast -crf 19 "
        f"-pix_fmt yuv420p -r {FPS} {out}")
    return out


def main(spec_path, out_path):
    spec = json.load(open(spec_path))
    work = os.path.join(CACHE, "work")
    os.makedirs(work, exist_ok=True)
    lead = spec.get("lead", 0.4)         # silence before the first word
    durs, timings = build_voice(spec, work)
    durs[-1] += 1.6                      # hold the end card after the last word
    durs[0] += lead
    timings[0] = [(a + lead, b + lead) for a, b in timings[0]]
    total = sum(durs)
    logo = p(spec["brand"]["logo_small"])
    clips = [render_scene(work, i, sc, durs[i], logo, timings[i]) for i, sc in enumerate(spec["scenes"])]
    first_media = next(sc["media"] for sc in spec["scenes"] if sc.get("media"))
    clips.append(render_cta(work, spec, durs[-1], first_media))
    open(f"{work}/list.txt", "w").write("".join(f"file '{c}'\n" for c in clips))
    run(f"ffmpeg -v error -y -f concat -safe 0 -i {work}/list.txt -c copy {work}/video.mp4")
    build_music(total + 0.5, f"{work}/music.wav", seed=spec.get("music_seed", 0), bpm=spec.get("bpm", 96))
    starts = np.cumsum([0] + durs[:-1])
    hits = [0.0] if spec.get("sfx") else []
    for i, sc in enumerate(spec["scenes"]):
        if sc.get("compare"):
            at = sc["compare"].get("at_line", 1)
            hits.append(starts[i] + max(0.5, timings[i][at][0] - 0.1) + 0.25)
    whooshes = list(starts[1:]) if spec.get("sfx") else []
    build_sfx(total + 0.5, f"{work}/sfx.wav", whooshes, hits if spec.get("sfx") else [])
    mv = spec.get("music_volume", 0.55)
    run(f"ffmpeg -v error -y -i {work}/vo.wav -af adelay={int(lead * 1000)}:all=1,apad=whole_dur={total},"
        f"loudnorm=I=-15:TP=-1.2 -ar 44100 -ac 2 {work}/vo44.wav")
    run(f"ffmpeg -v error -y -i {work}/music.wav -i {work}/vo44.wav -i {work}/sfx.wav -filter_complex "
        f"\"[0:a]volume={mv}[m];[1:a]asplit[v1][v2];[m][v1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[md];"
        f"[2:a]volume=0.5[fx];[md][v2][fx]amix=inputs=3:duration=first:normalize=0,atrim=0:{total},alimiter=limit=0.95\" "
        f"-ar 44100 {work}/mix.wav")
    run(f"ffmpeg -v error -y -i {work}/video.mp4 -i {work}/mix.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 160k "
        f"-shortest -movflags +faststart {out_path}")
    print(f"done {total:.1f}s -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

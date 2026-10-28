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


def build_voice(spec, work):
    k = load_tts()
    style = None
    for part in spec.get("voice", "hm_omega:0.65,am_onyx:0.35").split(","):
        v, w = part.split(":")
        s = k.get_voice_style(v) * float(w)
        style = s if style is None else style + s
    segs = [(sc["vo"], sc.get("speed", 0.95), sc.get("pause", 0.4)) for sc in spec["scenes"]]
    segs.append((spec["cta"]["vo"], spec["cta"].get("speed", 0.92), 0.6))
    out, durs, sr = [], [], 24000
    for chunks, speed, pause in segs:
        a, sr = speak(k, style, chunks, speed)
        out += [a, np.zeros(int(sr * pause), dtype=np.float32)]
        durs.append(len(a) / sr + pause)
    raw = os.path.join(work, "vo_raw.wav")
    sf.write(raw, np.concatenate(out), sr)
    run(f"ffmpeg -v error -y -i {raw} -af \"{VOICE_CHAIN}\" -ar 24000 {work}/vo.wav")
    return durs


# ---------- music ----------
def build_music(dur, path, seed=0):
    rng = np.random.default_rng(seed)
    sr, bpm = 44100, 96
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


def text_layers(work, name, head, sub, cap):
    f, y = [], 300
    for i, (line, col) in enumerate(head or []):
        f.append(f"drawtext=fontfile={FONT}:textfile={tf(work, f'{name}h{i}', line)}:fontcolor={COLORS.get(col, col)}:"
                 f"fontsize=84:borderw=7:bordercolor=black:x=(w-tw)/2:y={y}:alpha='min(1,(t-{0.15 + i * 0.2})/0.25)'")
        y += 104
    if sub:
        f.append(f"drawtext=fontfile={FONT}:textfile={tf(work, name + 's', sub)}:fontcolor=white:fontsize=54:borderw=5:"
                 f"bordercolor=black:x=(w-tw)/2:y={y + 20}:alpha='min(1,(t-0.6)/0.3)'")
    if cap:
        f.append(f"drawtext=fontfile={FONT}:textfile={tf(work, name + 'c', cap)}:fontcolor=white:fontsize=46:box=1:"
                 f"boxcolor=black@0.65:boxborderw=22:x=(w-tw)/2:y=1380")
    return ",".join(f) if f else "null"


def render_scene(work, i, sc, dur, logo):
    name = f"s{i}"
    layers = text_layers(work, name, sc.get("head"), sc.get("sub"), sc.get("caption"))
    out = os.path.join(work, name + ".mp4")
    src = p(sc["media"])
    look = "eq=contrast=1.08:saturation=1.15"
    if is_video(src):
        ss = sc.get("start", 0)
        base = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
                if sc.get("fill", True) else
                "split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:2,"
                "eq=brightness=-0.25[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=0:(H-h)/2")
        run(f"ffmpeg -v error -y -ss {ss} -t {dur} -i \"{src}\" -i {logo} -filter_complex "
            f"\"[0:v]{base},fps={FPS},{look},{layers}[v];[v][1:v]overlay=40:130\" -an -c:v libx264 -preset veryfast "
            f"-crf 19 -pix_fmt yuv420p -r {FPS} -t {dur} {out}")
    else:
        still = os.path.join(work, name + ".png")
        prep_still(src, sc.get("crop"), still)
        frames = int(dur * FPS)
        z = f"1+0.15*on/{frames}" if sc.get("zoom", "in") == "in" else f"1.15-0.15*on/{frames}"
        xb = sc.get("pan", 0.5)
        zp = f"zoompan=z='{z}':x='(iw-iw/zoom)*{xb}':y='(ih-ih/zoom)/2':d=1:s=1080x1920:fps={FPS}"
        run(f"ffmpeg -v error -y -loop 1 -framerate {FPS} -t {dur} -i {still} -i {logo} -filter_complex "
            f"\"[0:v]{zp},{look},{layers}[v];[v][1:v]overlay=40:130\" -c:v libx264 -preset veryfast -crf 19 "
            f"-pix_fmt yuv420p -r {FPS} {out}")
    return out


def render_cta(work, spec, dur, bg_media):
    b, c = spec["brand"], spec["cta"]
    still = os.path.join(work, "cta.png")
    if is_video(p(bg_media)):
        run(f"ffmpeg -v error -y -ss 1 -i \"{p(bg_media)}\" -frames:v 1 {work}/cta_src.png")
        prep_still(f"{work}/cta_src.png", None, still)
    else:
        prep_still(p(bg_media), spec["scenes"][0].get("crop"), still)
    T = lambda n, s: tf(work, n, s)
    Y = COLORS["yellow"]
    layers = [
        "boxblur=24:3,eq=brightness=-0.42:saturation=0.6",
        f"drawtext=fontfile={FONT}:textfile={T('e3', c['title'])}:fontcolor=white:fontsize=64:x=(w-tw)/2:y=640:alpha='min(1,(t-0.7)/0.4)'",
        f"drawtext=fontfile={FONT}:textfile={T('e4', c['subtitle'])}:fontcolor=white:fontsize=50:x=(w-tw)/2:y=730:alpha='min(1,(t-0.9)/0.4)'",
        "drawbox=x=90:y=880:w=900:h=250:color=0x25D366@0.95:t=fill:enable='gte(t,1.2)'",
        f"drawtext=fontfile={FONT}:textfile={T('e5', c.get('button', 'WhatsApp karein'))}:fontcolor=white:fontsize=50:x=(w-tw)/2:y=910:enable='gte(t,1.2)'",
        f"drawtext=fontfile={FONT}:textfile={T('e6', b['whatsapp'])}:fontcolor=white:fontsize=110:x=(w-tw)/2:y=985:enable='gte(t,1.2)'",
        f"drawtext=fontfile={FONT}:textfile={T('e7', b['address'])}:fontcolor=0xDDDDDD:fontsize=42:x=(w-tw)/2:y=1190:alpha='min(1,(t-1.6)/0.4)'",
        f"drawtext=fontfile={FONT}:textfile={T('e8', b['tagline1'])}:fontcolor=white:fontsize=50:x=(w-tw)/2:y=1360:alpha='min(1,(t-3.5)/0.5)'",
        f"drawtext=fontfile={FONT}:textfile={T('e9', b['tagline2'])}:fontcolor={Y}:fontsize=58:x=(w-tw)/2:y=1430:alpha='min(1,(t-3.7)/0.5)'",
        f"drawtext=fontfile={FONT}:textfile={T('e10', 'Follow ' + b['handle'])}:fontcolor=white:fontsize=40:box=1:boxcolor=black@0.5:boxborderw=16:x=(w-tw)/2:y=1540:alpha='min(1,(t-4.3)/0.5)'",
    ]
    zp = f"zoompan=z='1.1':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=1080x1920:fps={FPS}"
    out = os.path.join(work, "cta.mp4")
    run(f"ffmpeg -v error -y -loop 1 -framerate {FPS} -t {dur} -i {still} -i {p(b['logo_big'])} -filter_complex "
        f"\"[0:v]{zp},{','.join(layers)}[bg];[bg][1:v]overlay=(W-w)/2:250\" -c:v libx264 -preset veryfast -crf 19 "
        f"-pix_fmt yuv420p -r {FPS} {out}")
    return out


def main(spec_path, out_path):
    spec = json.load(open(spec_path))
    work = os.path.join(CACHE, "work")
    os.makedirs(work, exist_ok=True)
    durs = build_voice(spec, work)
    durs[-1] += 1.6                      # hold the end card after the last word
    durs[0] += 0.4                       # voice starts 0.4 s in
    total = sum(durs)
    logo = p(spec["brand"]["logo_small"])
    clips = [render_scene(work, i, sc, durs[i], logo) for i, sc in enumerate(spec["scenes"])]
    clips.append(render_cta(work, spec, durs[-1], spec["scenes"][0]["media"]))
    open(f"{work}/list.txt", "w").write("".join(f"file '{c}'\n" for c in clips))
    run(f"ffmpeg -v error -y -f concat -safe 0 -i {work}/list.txt -c copy {work}/video.mp4")
    build_music(total + 0.5, f"{work}/music.wav", seed=spec.get("music_seed", 0))
    run(f"ffmpeg -v error -y -i {work}/vo.wav -af adelay=400:all=1,apad=whole_dur={total},loudnorm=I=-15:TP=-1.2 "
        f"-ar 44100 -ac 2 {work}/vo44.wav")
    run(f"ffmpeg -v error -y -i {work}/music.wav -i {work}/vo44.wav -filter_complex "
        f"\"[0:a]volume=0.55[m];[1:a]asplit[v1][v2];[m][v1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[md];"
        f"[md][v2]amix=inputs=2:duration=longest:normalize=0,atrim=0:{total},alimiter=limit=0.95\" -ar 44100 {work}/mix.wav")
    run(f"ffmpeg -v error -y -i {work}/video.mp4 -i {work}/mix.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 160k "
        f"-shortest -movflags +faststart {out_path}")
    print(f"done {total:.1f}s -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

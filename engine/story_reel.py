#!/usr/bin/env python3
"""Story Reel: AI-generated cinematic clips (e.g. Google Flow / Veo) -> branded 9:16 Reel.

Unlike make_reel.py (where the voiceover sets each scene's length), here each beat has a fixed length,
keeps the clip's own sound (Veo makes sound effects), and narrator lines are dropped in at set times.
Ends with the same WhatsApp CTA end card as make_reel.py.

Usage: python3 engine/story_reel.py spec.json out.mp4
Spec: {
  "piper": "hi_IN-rohan-medium",  "brand": {...same as make_reel...},  "music_volume": 0.18, "clip_volume": 0.8,
  "beats": [ {"media": "clip.mp4" | "still.jpg", "start": 0, "dur": 5.5, "zoom": "in",
              "head": [["TEXT","yellow"]], "caption": "bottom box text",
              "vo": [{"at": 0.4, "say": [["हिंदी", "hi"]], "speed": 0.95, "show": "subtitle text"}]} ],
  "cta": {"title":..., "subtitle":..., "button":..., "bg": "image", "vo": [["...","hi"]]}
}
"""
import json, os, sys

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_reel as m  # noqa: E402

SR = 44100


def beat_video(work, i, b, logo, subs):
    src, dur = m.p(b["media"]), b["dur"]
    out = os.path.join(work, f"b{i}.mp4")
    layers = []
    if b.get("head"):
        ff, _ = m.big_lines(work, f"b{i}h", b["head"], 0.15, dur)
        layers += ff
    if b.get("caption"):
        layers.append(f"drawtext=fontfile={m.FONT}:textfile={m.tf(work, f'b{i}c', b['caption'])}:fontcolor=white:"
                      f"fontsize=54:box=1:boxcolor=black@0.65:boxborderw=22:x=(w-tw)/2:y=1430:"
                      f"alpha='min(1,(t-0.3)/0.3)'")
    for k, (st, en, text) in enumerate(subs):
        layers.append(f"drawtext=fontfile={m.FONT}:textfile={m.tf(work, f'b{i}s{k}', text)}:fontcolor=0xFFD23F:"
                      f"fontsize=58:borderw=6:bordercolor=black:x=(w-tw)/2:y=1560:"
                      f"enable='between(t,{st:.3f},{en:.3f})'")
    flash = "" if i == 0 else ",fade=in:st=0:d=0.15:color=black"
    vf = (",".join(layers) or "null") + flash
    if m.is_video(src):
        ss, r = b.get("start", 0), b.get("rate", 1.0)
        m.run(f"ffmpeg -v error -y -ss {ss} -t {dur * r:.3f} -i \"{src}\" -i {logo} -filter_complex "
              f"\"[0:v]setpts=PTS/{r},scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={m.FPS},{m.LOOK},"
              f"{vf}[v];[v][1:v]overlay=40:130\" -an -c:v libx264 -preset veryfast -crf 19 -pix_fmt yuv420p "
              f"-r {m.FPS} -t {dur} {out}")
        aud = os.path.join(work, f"b{i}.wav")
        has_audio = m.run(f"ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 \"{src}\"").strip()
        if has_audio:
            m.run(f"ffmpeg -v error -y -ss {ss} -t {dur * r:.3f} -i \"{src}\" -vn -af \"atempo={max(0.5, r)},apad=whole_dur={dur},"
                  f"afade=t=in:d=0.08,afade=t=out:st={max(0, dur - 0.25):.3f}:d=0.25\" -ar {SR} -ac 2 {aud}")
        else:
            m.run(f"ffmpeg -v error -y -f lavfi -t {dur} -i anullsrc=r={SR}:cl=stereo {aud}")
    else:
        base = m.still_clip(work, f"b{i}z", src, b.get("crop"), b.get("zoom", "in"), b.get("pan", 0.5), dur,
                            os.path.join(work, f"b{i}z.mp4"))
        m.run(f"ffmpeg -v error -y -i {base} -i {logo} -filter_complex \"[0:v]{vf}[v];[v][1:v]overlay=40:130\" "
              f"-c:v libx264 -preset veryfast -crf 19 -pix_fmt yuv420p -r {m.FPS} -t {dur:.3f} {out}")
        aud = os.path.join(work, f"b{i}.wav")
        m.run(f"ffmpeg -v error -y -f lavfi -t {dur} -i anullsrc=r={SR}:cl=stereo {aud}")
    return out, aud


def main(spec_path, out_path):
    spec = json.load(open(spec_path))
    work = os.path.join(m.CACHE, "story")
    os.makedirs(work, exist_ok=True)
    k = m.load_tts()
    voice = m.Piper(spec.get("piper", "hi_IN-rohan-medium"), k)

    def say(chunks, speed):
        a, sr = voice.create(chunks, speed)
        tmp = os.path.join(work, "ln.wav")
        sf.write(tmp, a, sr)
        m.run(f"ffmpeg -v error -y -i {tmp} -af \"{m.VOICE_CHAIN}\" -ar {SR} -ac 1 {tmp}.44.wav")
        x, _ = sf.read(tmp + ".44.wav", dtype="float32")
        return x

    beats, cta = spec["beats"], spec["cta"]
    starts = np.cumsum([0] + [b["dur"] for b in beats])
    cta_vo = say(cta["vo"], cta.get("speed", 0.95))
    cta_dur = len(cta_vo) / SR + 2.0
    total = float(starts[-1] + cta_dur)
    vo = np.zeros(int(SR * (total + 1)), dtype=np.float32)
    logo = m.p(spec["brand"]["logo_small"])
    clips, auds = [], []
    for i, b in enumerate(beats):
        subs = []
        for ln in b.get("vo", []):
            a = say(ln["say"], ln.get("speed", 0.95))
            t0 = int(SR * (starts[i] + ln["at"]))
            vo[t0:t0 + len(a)] += a[:len(vo) - t0]
            if ln.get("show"):
                subs.append((ln["at"], min(b["dur"], ln["at"] + len(a) / SR + 0.3), ln["show"]))
        c, a = beat_video(work, i, b, logo, subs)
        clips.append(c)
        auds.append(a)
    t0 = int(SR * (starts[-1] + 0.5))
    vo[t0:t0 + len(cta_vo)] += cta_vo
    clips.append(m.render_cta(work, {**spec, "scenes": [{"crop": None}]}, cta_dur, cta.get("bg", beats[0]["media"])))
    m.run(f"ffmpeg -v error -y -f lavfi -t {cta_dur} -i anullsrc=r={SR}:cl=stereo {work}/cta.wav")
    auds.append(f"{work}/cta.wav")

    open(f"{work}/vlist.txt", "w").write("".join(f"file '{c}'\n" for c in clips))
    m.run(f"ffmpeg -v error -y -f concat -safe 0 -i {work}/vlist.txt -c copy {work}/video.mp4")
    open(f"{work}/alist.txt", "w").write("".join(f"file '{a}'\n" for a in auds))
    m.run(f"ffmpeg -v error -y -f concat -safe 0 -i {work}/alist.txt -ar {SR} -ac 2 {work}/clips.wav")
    sf.write(f"{work}/vo.wav", np.stack([vo, vo], 1)[:int(SR * total)], SR)
    m.build_music(total + 0.5, f"{work}/music.wav", seed=spec.get("music_seed", 1), bpm=spec.get("bpm", 84))
    cv, mv = spec.get("clip_volume", 0.8), spec.get("music_volume", 0.18)
    m.run(f"ffmpeg -v error -y -i {work}/clips.wav -i {work}/music.wav -i {work}/vo.wav -filter_complex "
          f"\"[0:a]volume={cv}[c];[1:a]volume={mv}[mu];[c][mu]amix=inputs=2:duration=first:normalize=0[bed];"
          f"[2:a]loudnorm=I=-15:TP=-1.5,asplit[v1][v2];"
          f"[bed][v1]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=300[bd];"
          f"[bd][v2]amix=inputs=2:duration=first:normalize=0,atrim=0:{total},alimiter=limit=0.95\" -ar {SR} {work}/mix.wav")
    m.run(f"ffmpeg -v error -y -i {work}/video.mp4 -i {work}/mix.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 160k "
          f"-shortest -movflags +faststart {out_path}")
    print(f"done {total:.1f}s -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

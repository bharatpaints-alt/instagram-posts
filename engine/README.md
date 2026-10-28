# Reel engine

Turns photos/videos from `new/` into a 9:16 Instagram Reel: Hindi + English voiceover, background music,
Bharat Paints + GIO Paints logos on every scene, and a WhatsApp CTA end card.

```bash
pip install kokoro-onnx soundfile numpy pillow   # ffmpeg must be installed
python3 engine/make_reel.py engine/example_spec.json out.mp4
```

The voice model (Kokoro, open source) downloads itself from GitHub on the first run into `engine/.cache/` (not committed).

## Spec (one JSON per Reel)

| Field | What it is |
|---|---|
| `voice` | Kokoro voice blend, e.g. `hm_omega:0.65,am_onyx:0.35` (deep, commanding male) |
| `brand` | Logos, WhatsApp number, address, tagline lines, Instagram handle |
| `scenes[]` | One per photo/clip: `media`, optional `crop` `[w,h,x,y]`, `zoom` (`in`/`out`), `pan` (0–1), `head` (big lines, `white`/`yellow`), `sub`, `caption`, `vo` (list of `[text, "hi"|"en"]`), `speed`, `pause`. For a video, `start` = second to start from |
| `cta` | End card `title`, `subtitle`, `button`, and its `vo` |

Rules that make it sound right:
- Write Hindi in Devanagari with `"hi"`. Write English words (Fast Drying, WhatsApp, Paints) as separate chunks with `"en"`, so they are pronounced in English.
- Write GIO as `जियो` (`"hi"`).
- Each scene's length follows its voiceover, so 1–2 short sentences per scene. Total 30–45 seconds.
- Short punchy lines with `!` and `?` give the voice more rise and fall.

## Swapping the voice later

`build_voice()` in `make_reel.py` is the only place that makes audio. To move to another open-source TTS
(Chatterbox, Indic Parler-TTS, IndicF5), replace that function so it writes `vo.wav` and returns the
per-scene durations. Nothing else changes.

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

## v2 options (retention + voice modulation)

| Field | What it is |
|---|---|
| `lines` (scene or `cta`) | Instead of `vo`: a list of lines, each `{vo, speed, pitch (semitones), gain (dB), pause, show, say}`. Speed/pitch/gain per line give the voice its rise and fall. `show` = big text that pops in when that line is spoken; `say` = subtitle box synced to that line |
| `compare` | Before → after wipe reveal: `{before:{media,crop,zoom}, after:{...}, at_line, wipe}`. The wipe starts on line `at_line` |
| `tags` | Small label boxes, e.g. `PEHLE` / `BAAD`: `{text, bg, from/line, to ("lineN" or seconds), y}` |
| `badge` | Small yellow sticker top-right (e.g. offer) |
| `zoom: "punch"` | Fast punch-in for hook / big moments |
| top level `sfx`, `bpm`, `music_volume`, `lead` | Whoosh on every cut + hit on hook/reveal; music tempo; music level; silence before first word |
Scenes after the first open with a short white flash. The WhatsApp number on the end card pulses.

## Native Hindi voice (recommended)
Add `"piper": "hi_IN-rohan-medium"` to the spec. It uses the Piper Hindi male voice trained on IIT Madras
IndicTTS "Hindi Mono Male" recordings (ONNX, downloaded from the sherpa-onnx GitHub release on first run;
the IITM license allows commercial use). Write every word in Devanagari with "hi" (e.g. वॉट्सऐप, पेंट्स, फ़्री).
Do NOT use hi_IN-pratham / hi_IN-priyamvada: their data is CC BY-NC-SA (non-commercial).

## Gaurav's own cloned voice (best)
Add `"sarvam_voice": "svc-38314a5f-36dc-4276-98da-94973af10cec"` (Gaurav, hi-IN) to the spec. It calls Sarvam AI
`POST /voices/clone` with that saved voice. Line `speed` becomes Sarvam `pace`; `pitch` is ignored (real voice).
The API key comes from the `SARVAM_API_KEY` env var or `~/.sarvam_key` — never commit it.

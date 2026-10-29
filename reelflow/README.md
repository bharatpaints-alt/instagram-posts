# ReelFlow (M1 core pipeline)

Phone photos/videos -> daily branded Instagram Reel in the client's own (cloned) voice -> client says yes -> posted.
Spec + roadmap: the "ReelFlow – Auto Reel Software Spec" doc. Bharat Paints is client #1 (`clients/bharat-paints/`).

```bash
pip install --break-system-packages kokoro-onnx soundfile numpy pillow   # + ffmpeg
python3 -m reelflow nudge bharat-paints            # 9 am: trend (YouTube) + 2-3 shots to take
python3 -m reelflow make bharat-paints             # next upload -> script -> voice -> Reel in review/
python3 -m reelflow change bharat-paints "..."     # owner's change request -> new version
python3 -m reelflow approve bharat-paints <commit> # owner said yes -> Uplika publish request
python3 -m reelflow posted bharat-paints <link>    # archive to posted/, back to idle
python3 -m reelflow daily                          # every client
python3 reelflow/tests/test_offline.py             # end-to-end test without API keys
```
(run from `reelflow/`, or `PYTHONPATH=reelflow python3 -m reelflow ...` from the repo root)

| Module | Job |
|---|---|
| `trends.py` | YouTube Data API: recent high-view Shorts for the niche queries -> Claude picks ONE angle + shot list |
| `media.py` | oldest upload batch (same commit), frames from photos + 6 per video |
| `script.py` | Claude writes the plan (3 hooks, scenes, Devanagari voice lines, pop text, compare, CTA keyword, caption) under the script rules; validation; plan -> engine spec (video starts clamped so clips never run out) |
| `voice.py` | `sarvam` (premium clone) / `opensource` (GPU endpoint `OPENVOICE_URL` or voice repo `OPENVOICE_REPO`, one WAV per line) / `piper` fallback, automatic fallback with a note |
| `pipeline.py` | stages idle -> nudged -> in_review -> approved -> idle; never makes a second Reel while one is in review/approved |
| `common.py` | client profile, state.json, outbox (every message for the client) |

Env: `ANTHROPIC_API_KEY` (scripts), `YOUTUBE_API_KEY` (trends; optional), `SARVAM_API_KEY`, `OPENVOICE_URL`/`OPENVOICE_TOKEN` or `OPENVOICE_REPO`, `REELFLOW_MODEL`.
Posting: `approve` writes the Uplika publish request to the outbox; the Claude routine executes it via the Uplika connector (server-side Uplika API next).
New client = copy `clients/bharat-paints/client.json`, edit facts/brand/voice, connect Instagram in Uplika.

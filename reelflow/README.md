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

## M2 + M3: web app, scheduler, admin

```bash
cd reelflow
ADMIN_TOKEN=<secret> PUBLIC_BASE_URL=https://<your-host> python3 -m reelflow serve   # :8000, scheduler thread on
python3 tests/test_web.py                                                           # sign-up -> voice -> upload -> Reel -> change -> yes -> posted
```

| Page | Who | What |
|---|---|---|
| `/admin/<ADMIN_TOKEN>` | Gaurav | all clients, stage, errors, Nudge/Make/Reset, waiting-to-publish list, log |
| `/admin/<ADMIN_TOKEN>/signup` | Gaurav | new client form (facts, niche, YouTube words, logo -> logo cards, plan) -> client link |
| `/admin/<ADMIN_TOKEN>/client/<id>` | Gaurav | edit profile JSON (Uplika connection id, Sarvam voice id, engine), new link |
| `/c/<id>/<token>` | client | today's idea + shots, upload 1-5 files, Reel preview, **Yes, post karo** / change request, history |
| `/c/<id>/<token>/voice` | client | record 30-40 s in the browser (or upload a voice note) -> `voice/sample.wav` |
| `/api/<ADMIN_TOKEN>/pending`, `/posted`, `/status` | publisher | for the Claude routine that holds the Uplika connector |

Scheduler (every minute): nudge at each client's `nudge_time` (IST) once a day; make a Reel when files wait and nothing is in review;
deliver outbox messages by email (SMTP_*), webhook (NOTIFY_WEBHOOK) or WhatsApp Cloud API (WHATSAPP_TOKEN, WHATSAPP_PHONE_ID).
Safety: one make per client at a time, no new Reel while one is in review/approved, a failed batch is not retried every minute.

Deploy: `docker build -f reelflow/Dockerfile .` from the repo root (or `render.yaml`). Client data lives in `REELFLOW_DATA`
(a persistent disk), not in git. New sign-ups use basic = open-source voice (needs OPENVOICE_URL), premium = Sarvam; both fall back to Piper.

Publisher routine prompt (Claude scheduled task, hourly):
> GET https://<host>/api/<ADMIN_TOKEN>/pending. For each item: Uplika media_from_url(media_url), publish to [uplika connection id
> from /admin client profile] with the caption, options.instagram {contentType "reel", shareToFeed true}, wait true; then
> POST https://<host>/api/<ADMIN_TOKEN>/posted {"client": id, "permalink": link}. Never publish an item twice.

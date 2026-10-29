"""Offline end-to-end test: fixture Claude answers, real frames, real render (Piper fallback voice).
Run from repo root:  python3 reelflow/tests/test_offline.py"""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reelflow import common, llm, pipeline, trends, script  # noqa

REPO = common.REPO
tmp = tempfile.mkdtemp(prefix="rf-test-")
cdir = os.path.join(common.CLIENTS, "_test")
os.makedirs(cdir, exist_ok=True)
prof = json.load(open(os.path.join(common.CLIENTS, "bharat-paints", "client.json")))
inbox = os.path.join(tmp, "new")
os.makedirs(inbox)
for f in ("painting-in-progress.mp4", "final-work.mp4"):
    shutil.copy(os.path.join(REPO, "posted", f), inbox)
prof["paths"] = {"inbox": inbox, "review": os.path.join(tmp, "review"), "posted_media": os.path.join(tmp, "posted"),
                 "posted_reels": os.path.join(tmp, "posted", "reels")}
prof["voice"]["engine"] = "sarvam"  # no key in test -> must fall back to piper
json.dump(prof, open(os.path.join(cdir, "client.json"), "w"), ensure_ascii=False)
os.environ.pop("SARVAM_API_KEY", None)

P = os.path.relpath(os.path.join(inbox, "painting-in-progress.mp4"), REPO)
F = os.path.relpath(os.path.join(inbox, "final-work.mp4"), REPO)
TREND = {"trend_line": "Diwali se pehle last-minute painting", "angle": "clean painting", "why": "-", "shots": ["a", "b"]}
PLAN = {"hooks": ["RUKO!", "Daag?", "Painter?"], "chosen_hook": 0, "idea": "plastic cover",
 "scenes": [
  {"media": P, "start": 11.5, "lines": [{"say": "रुको!", "show": [["RUKO!", "yellow"]], "pause": 0.3, "pitch": 1.5, "gain": 3},
                                        {"say": "पेंटर बुलाने से पहले... ये देखिए!", "show": [["PAINTER SE PEHLE", "white"], ["YE DEKHIYE!", "yellow"]]}]},
  {"media": P, "start": 0, "lines": [{"say": "सबको एक ही डर होता है...", "show": [["SABKO EK HI DARR", "white"]]},
                                     {"say": "दरवाज़ों पे छींटे! सामान पे दाग!", "show": [["CHHEENTE?", "white"], ["DAAG?", "yellow"]]}]},
  {"media": P, "start": 3.6, "tags": [{"text": "PLASTIC COVER", "line": 1}],
   "lines": [{"say": "पर यहाँ देखिए...", "show": [["PAR YAHAN...", "white"]]},
             {"say": "हर दरवाज़ा, हर चौखट... पहले प्लास्टिक से पैक!", "show": [["HAR DARWAZA", "white"], ["PLASTIC SE PACK!", "yellow"]]}]},
  {"compare": {"before": {"media": P, "at": 10.3}, "after": {"media": F, "at": 4.5}, "at_line": 1},
   "lines": [{"say": "और काम के बाद... ये देखिए!", "show": [["KAAM KE BAAD...", "white"]]},
             {"say": "नया रंग... नया घर!", "show": [["NAYA RANG", "yellow"], ["NAYA GHAR!", "white"]]}]},
  {"media": F, "start": 8.2, "lines": [{"say": "दिवाली से पहले पेंटिंग करवानी है?", "show": [["DIWALI SE PEHLE", "white"], ["PAINTING?", "yellow"]]}]}],
 "cta": {"keyword": "PAINTER", "title": "Likhein: \"PAINTER\"", "subtitle": "Painter + paint, sab ek jagah",
         "lines": [{"say": "अभी वॉट्सऐप पे लिखिए... पेंटर!"}, {"say": "रंगों की दुनिया में रखें कदम... भारत पेंट्स के संग!"}]},
 "script_roman": ["RUKO! ..."], "caption_hook": "Painter bulane se pehle ye dekh lo!",
 "caption_value_lines": ["Har darwaza plastic se pack."], "hashtags": ["#DiwaliPainting"]}

answers = iter([TREND, PLAN])
llm.ask_json = lambda *a, **k: next(answers)
trends.ask_json = llm.ask_json
script.ask_json = llm.ask_json
os.environ.pop("YOUTUBE_API_KEY", None)
try:
    c = common.load_client("_test")
    print("nudge:", json.load(open(pipeline.nudge(c)))["text"][:80])
    r = json.load(open(pipeline.make(c)))
    print("review:", r["reel"], "| voice:", r["voice_engine"], "|", r["voice_note"][:60], "| problems:", r["problems"])
    assert r["voice_engine"] == "piper"
    reel = os.path.join(REPO, r["reel"])
    d = float(common.sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", reel]))
    print("duration", d)
    assert 20 < d < 60
    try:
        pipeline.make(c); raise SystemExit("double make allowed!")
    except common.ReelFlowError as e:
        print("guard ok:", e)
    print("approve:", json.load(open(pipeline.approve(c, "abc123")))["media_url"][-40:])
    print("OK", reel)
finally:
    shutil.rmtree(cdir)

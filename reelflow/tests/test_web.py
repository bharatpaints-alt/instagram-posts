"""Web app end-to-end with fixture Claude answers: sign-up -> voice -> upload -> Reel -> change -> yes -> publish API -> posted,
plus the 9 am scheduler tick.  Run from reelflow/:  python3 tests/test_web.py"""
import datetime as dt, json, os, re, shutil, sys, tempfile, time
DATA = tempfile.mkdtemp(prefix="rf-web-")
os.environ.update(REELFLOW_DATA=DATA, ADMIN_TOKEN="admintok", REELFLOW_SCHEDULER="0", PUBLIC_BASE_URL="https://reelflow.example")
for k in ("ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "SARVAM_API_KEY", "OPENVOICE_URL", "OPENVOICE_REPO", "NOTIFY_WEBHOOK", "SMTP_HOST"):
    os.environ.pop(k, None)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from reelflow import llm, script, trends, scheduler, common  # noqa
from fastapi.testclient import TestClient  # noqa
from web.app import app  # noqa

REPO = common.REPO
calls = []


def fake(system, parts, max_tokens=0):
    text = "\n".join(p for p in parts if isinstance(p, str))
    calls.append(text[:60])
    if "Return {\"trend_line\"" in text:
        return {"trend_line": "Shaadi season me ghar ka makeover", "angle": "before-after", "why": "-",
                "shots": ["Kamre ka pehle ka video", "Kaam ke baad same jagah se"]}
    media = re.findall(r"^- (\S+): (video|image)", text, re.M)
    v1, v2 = media[0][0], media[-1][0]
    hook = "रुको! ये देखिए!" if "CHANGE REQUEST" not in text else "रुको! पहले ये देखो!"
    return {"hooks": ["a", "b", "c"], "chosen_hook": 0, "idea": "x",
            "scenes": [{"media": v1, "start": 11, "lines": [{"say": hook, "show": [["RUKO!", "yellow"]]}]},
                       {"media": v1, "start": 2, "lines": [{"say": "हर दरवाज़ा पहले प्लास्टिक से पैक!", "show": [["PLASTIC SE PACK!", "yellow"]]}]},
                       {"compare": {"before": {"media": v1, "at": 10}, "after": {"media": v2, "at": 4.5}, "at_line": 1},
                        "lines": [{"say": "और काम के बाद...", "show": [["KAAM KE BAAD", "white"]]}, {"say": "नया रंग, नया घर!", "show": [["NAYA GHAR!", "yellow"]]}]}],
            "cta": {"keyword": "MAKEOVER", "title": "Likhein: \"MAKEOVER\"", "subtitle": "Test",
                    "lines": [{"say": "अभी वॉट्सऐप कीजिए!"}]},
            "script_roman": ["RUKO! ye dekhiye"], "caption_hook": "Ruko!", "caption_value_lines": ["Line"], "hashtags": ["#Test"]}


llm.ask_json = trends.ask_json = script.ask_json = fake
cl = TestClient(app)
A = "/admin/admintok"
assert cl.get("/admin/wrong").status_code == 404
logo = os.path.join(REPO, "engine", "assets", "gio_logo.jpg")
r = cl.post(A + "/signup", data={"name": "Sharma Furniture", "owner": "Ramesh", "whatsapp": "98765 43210", "instagram": "sharmafurn",
                                 "city": "Karnal", "address": "Main Bazaar", "facts": "Since 1995\nFree home visit",
                                 "niche": "Furniture shop", "youtube_queries": "sofa design, bedroom makeover", "tagline": "Ghar sajao\nSharma ke saath",
                                 "plan": "basic"}, files={"logo": ("logo.jpg", open(logo, "rb"), "image/jpeg")}, follow_redirects=False)
assert r.status_code == 303, r.text
cid = "sharma-furniture"
c = common.load_client(cid)
tok = open(os.path.join(c["_dir"], "secret.txt")).read().strip()
C = f"/c/{cid}/{tok}"
assert cl.get(f"/c/{cid}/bad").status_code == 404
assert "awaaz record" in cl.get(C).text
# voice sample (pilot recording) + too-short rejection
short = os.path.join(DATA, "short.wav"); common.sh(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=3", short])
r = cl.post(C + "/voice", files={"file": ("s.wav", open(short, "rb"), "audio/wav")}, follow_redirects=True)
assert "at least" in r.text
rec = os.path.join(REPO, "posted", "reels", "voice", "painter-cover", "gaurav-original.m4a")
r = cl.post(C + "/voice", files={"file": ("v.m4a", open(rec, "rb"), "audio/mp4")}, follow_redirects=True)
assert "save ho gayi" in r.text, r.text[-500:]
# 9 am scheduler tick -> nudge
scheduler.tick(now=dt.datetime(2026, 10, 30, 3, 40, tzinfo=dt.timezone.utc), log=lambda *a: None)  # 09:10 IST
st = common.load_state(c); assert st["stage"] == "nudged" and st["last_nudge"] == "2026-10-30", st
assert "Shaadi season" in cl.get(C).text
# upload two videos -> background make
vids = [os.path.join(REPO, "posted", f) for f in ("painting-in-progress.mp4", "final-work.mp4")]
r = cl.post(C + "/upload", files=[("files", (os.path.basename(v), open(v, "rb"), "video/mp4")) for v in vids], follow_redirects=True)
assert "Reel ban rahi hai" in r.text
t0 = time.time()
while time.time() - t0 < 400:
    s = cl.get(C + "/status.json").json()
    if s["stage"] == "in_review" and not s["busy"]:
        break
    if s["error"]:
        raise SystemExit(s)
    time.sleep(5)
print("made in", round(time.time() - t0), "s")
page = cl.get(C).text
assert "Yes, post karo" in page and "<video" in page
st = common.load_state(c)
assert cl.get(f"/files/{cid}/{tok}/reel/{st['name']}.mp4").status_code == 200
print("voice engine:", st["voice_engine"])
# change request
cl.post(C + "/change", data={"text": "hook aur zor se"})
time.sleep(1)
while cl.get(C + "/status.json").json()["busy"]:
    time.sleep(5)
st = common.load_state(c); assert st["version"] == 2 and st["stage"] == "in_review", st.get("error")
# yes -> pending publish -> posted
cl.post(C + "/approve")
p = cl.get("/api/admintok/pending").json()
assert len(p) == 1 and p[0]["media_url"].startswith("https://reelflow.example/files/sharma-furniture/"), p
assert p[0]["caption"].count("MAKEOVER") == 1
assert cl.post(C + "/upload", files=[("files", ("x.mp4", open(vids[0], "rb"), "video/mp4"))], follow_redirects=True).status_code == 200
assert common.load_state(c)["stage"] == "approved"  # new upload must not start a second Reel
r = cl.post("/api/admintok/posted", json={"client": cid, "permalink": "https://www.instagram.com/reel/TEST/"}).json()
assert r["ok"], r
st = common.load_state(c); assert st["stage"] == "idle" and st["history"][-1]["permalink"].endswith("TEST/")
assert cl.get("/api/admintok/pending").json() == []
assert len(os.listdir(os.path.join(c["_dir"], "posted", "reels"))) >= 3
assert "Sharma Furniture" in cl.get(A).text and cl.get(A + f"/client/{cid}").status_code == 200
assert "instagram.com/reel/TEST" in cl.get(C).text
print("WEB OK", DATA)

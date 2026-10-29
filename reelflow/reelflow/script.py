"""Auto script: media frames + trend + client facts -> Reel plan (JSON) -> make_reel spec."""
import os
import re

from .common import REPO, ReelFlowError, asset, frame, media_kind, repo_path
from .llm import ask_json

RULES = """You write 30-45 second Instagram Reel scripts for a small local business in India, spoken in the owner's voice.
RULES
- Hook in the first 1.5 s: a pattern-break word or a direct question the viewer feels ("RUKO!", "Deewar pe ye daag?"). Never start with the brand name.
- One idea per Reel. 70-100 spoken words total. Short lines, 3-8 words each.
- Structure: hook -> problem/curiosity -> proof (ONLY what the media really shows) -> benefit in the viewer's words -> one CTA.
- Talk like a local shopkeeper to a neighbour: simple Hindi, specific, no corporate words, no exaggeration.
- Never invent prices, warranties, numbers, offers or claims beyond the FACTS and what is visible in the media.
- CTA = one action only: WhatsApp one keyword (UPPERCASE Roman, e.g. PAINTER) to the business number.
- Write 3 different hooks, pick the strongest, then reread as a fast-scrolling critical viewer and cut anything boring.
SPOKEN TEXT ("say"): Hindi in Devanagari only, brand/English words transliterated (use the pronunciation map). Use "..." for dramatic pauses and "!"/"?" for energy.
ON-SCREEN TEXT ("show"): 1-3 lines, UPPERCASE Hinglish Roman, max 18 characters per line, colour "white" or "yellow" (yellow = the key word).
SCENES: 4-6 scenes, each uses one media file (exact name from the media list). For a video give "start" (seconds) so that the shown part matches the words; the scene lasts about as long as its words. For a photo you may give "zoom": "punch" (hook / big moment), "in" or "out". If the media shows a clear before and after, use one "compare" scene with before/after media (for a video give "at" seconds of the frame to use) and wipe on line "at_line".
Optional "tags": small label boxes like {"text": "PLASTIC COVER", "line": 1}.
"""

SCHEMA = """Return:
{"hooks": ["...", "...", "..."], "chosen_hook": 0, "idea": "one line",
 "scenes": [{"media": "<file>", "start": 0.0, "zoom": "in", "tags": [],
             "lines": [{"say": "<Devanagari>", "show": [["TEXT", "yellow"]], "pause": 0.2, "speed": 1.0, "pitch": 0, "gain": 0}]},
            {"compare": {"before": {"media": "<file>", "at": 3.0}, "after": {"media": "<file>", "at": 2.0}, "at_line": 1},
             "lines": [...]}],
 "cta": {"keyword": "PAINTER", "title": "Likhein: \\"PAINTER\\"", "subtitle": "<= 32 chars", "lines": [{"say": "<Devanagari>"}]},
 "script_roman": ["line in Hinglish Roman", "..."],
 "caption_value_lines": ["...", "..."], "caption_hook": "...", "hashtags": ["#...", "..."]}"""


def write_plan(client, frames, index, trend, change_request=None, previous=None):
    facts = "\n- ".join(client["facts"])
    pron = ", ".join(f"{k} = {v}" for k, v in client.get("pronunciation", {}).items())
    head = (f"BUSINESS: {client['name']} ({client.get('city', '')}). WhatsApp {client['whatsapp']}.\nFACTS:\n- {facts}\n"
            f"Pronunciation map: {pron}\nTagline (Devanagari, may close the CTA): {client.get('tagline_hi', '')}\n"
            f"TODAY'S TREND: {trend.get('trend_line', '-')} | angle: {trend.get('angle', '-')}\n"
            "MEDIA:\n" + "\n".join(f"- {k}: {v['kind']}" + (f", {v['duration']}s" if v.get('duration') else "")
                                   for k, v in index.items()))
    parts = [RULES, head]
    if change_request and previous:
        parts.append(f"PREVIOUS PLAN (the owner asked for changes):\n{previous}\nOWNER'S CHANGE REQUEST: {change_request}\n"
                     "Keep everything the owner did not ask to change.")
    parts += [("image", f, label) for label, f in frames]
    parts.append(SCHEMA)
    plan = ask_json(RULES, parts, max_tokens=5000)
    return validate(plan, index)


def words(plan):
    return sum(len(re.findall(r"\S+", ln["say"])) for sc in plan["scenes"] + [plan["cta"]] for ln in sc["lines"])


def validate(plan, index):
    problems = []
    for sc in plan["scenes"]:
        for m in [sc.get("media")] + [sc.get("compare", {}).get(k, {}).get("media") for k in ("before", "after")]:
            if m and m not in index:
                problems.append(f"unknown media {m}")
        for ln in sc["lines"]:
            if re.search(r"[A-Za-z]", ln["say"]):
                problems.append(f"Roman letters in spoken line: {ln['say']}")
            for t, _ in ln.get("show", []):
                if len(t) > 20:
                    problems.append(f"on-screen line too long: {t}")
    n = words(plan)
    if not 55 <= n <= 115:
        problems.append(f"{n} spoken words (want 70-100)")
    plan["_problems"] = problems
    plan["_words"] = n
    return plan


def est_seconds(lines):
    return sum(len(ln["say"].split()) / 2.4 + ln.get("pause", 0.15) for ln in lines) + 0.3


def to_spec(client, plan, work, voice_fields):
    """Plan -> engine spec. Video starts are clamped so the clip never runs out under the voice."""
    os.makedirs(work, exist_ok=True)
    from .common import video_duration
    rel = lambda m: m  # media names are already repo-relative

    def line(ln):
        d = {"vo": [[ln["say"], "hi"]], "speed": ln.get("speed", 1.0), "pause": ln.get("pause", 0.15)}
        for k in ("show", "pitch", "gain", "say_sub"):
            if ln.get(k):
                d[k if k != "say_sub" else "say"] = ln[k]
        return d

    scenes = []
    for i, sc in enumerate(plan["scenes"]):
        out = {"lines": [line(ln) for ln in sc["lines"]], "pause": sc.get("pause", 0.12)}
        if sc.get("tags"):
            out["tags"] = sc["tags"]
        if sc.get("compare"):
            cmp = {}
            for side in ("before", "after"):
                m = sc["compare"][side]["media"]
                src = repo_path(m)
                if media_kind(src) == "video":
                    still = frame(src, float(sc["compare"][side].get("at", 1.0)), os.path.join(work, f"cmp{i}_{side}.jpg"))
                    cmp[side] = {"media": still, "zoom": "in"}
                else:
                    cmp[side] = {"media": rel(m), "zoom": "in"}
            cmp["at_line"] = sc["compare"].get("at_line", 1)
            cmp["wipe"] = 0.6
            out["compare"] = cmp
            out.setdefault("tags", []).extend([{"text": "PEHLE", "bg": "white", "from": 0, "to": f"line{cmp['at_line']}", "y": 1180},
                                               {"text": "BAAD", "line": cmp["at_line"], "y": 1180}])
        else:
            out["media"] = rel(sc["media"])
            if media_kind(repo_path(sc["media"])) == "video":
                d = video_duration(repo_path(sc["media"]))
                need = est_seconds(sc["lines"]) * 1.25
                out["start"] = round(max(0.0, min(float(sc.get("start", 0)), d - need)), 2)
            else:
                out["zoom"] = sc.get("zoom", "punch" if i == 0 else "in")
        scenes.append(out)
    cta = plan["cta"]
    first_still = next((s["media"] for s in scenes if s.get("media") and media_kind(repo_path(s["media"])) == "image"), None)
    if not first_still:  # CTA background from the last video frame
        vid = next(s["media"] for s in scenes if s.get("media"))
        first_still = frame(repo_path(vid), max(0.5, video_duration(repo_path(vid)) - 1.5), os.path.join(work, "cta_bg.jpg"))
    spec = {"music_seed": 5, "bpm": 112, "music_volume": 0.5, "sfx": True, "lead": 0.1,
            "brand": {"logo_small": asset(client, client["brand_assets"]["logo_small"]),
                      "logo_big": asset(client, client["brand_assets"]["logo_big"]), "whatsapp": client["whatsapp"], "address": client["address"],
                      "tagline1": client["tagline"][0], "tagline2": client["tagline"][1],
                      "handle": client["instagram_handle"]},
            "scenes": scenes,
            "cta": {"title": cta["title"], "subtitle": cta.get("subtitle", ""), "button": "WhatsApp karein",
                    "bg": first_still, "lines": [line(ln) for ln in cta["lines"]]}}
    spec.update(voice_fields)
    return spec


def caption(client, plan):
    kw = plan["cta"]["keyword"]
    tags = list(dict.fromkeys(client.get("hashtags", []) + plan.get("hashtags", [])))[:12]
    return "\n".join([plan["caption_hook"], "", *plan["caption_value_lines"], "",
                      f"WhatsApp pe likhiye \"{kw}\" — {client['whatsapp']}", "",
                      " ".join(client["tagline"]), client.get("brand_line", ""),
                      f"📍 {client['address']}", f"📲 WhatsApp: {client['whatsapp']}", "", " ".join(tags)])

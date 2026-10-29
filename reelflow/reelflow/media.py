"""Pick the next upload batch and turn it into frames Claude can look at."""
import os

from .common import REPO, frame, media_kind, repo_path, sh, video_duration


def _added_at(path):
    out = sh(["git", "-C", REPO, "log", "--format=%ct", "--reverse", "--", path], check=False).split()
    return int(out[0]) if out else int(os.path.getmtime(path))


def next_batch(client, max_files=5):
    """Oldest upload first; files uploaded together (same commit time) form one Reel."""
    inbox = repo_path(client["paths"]["inbox"])
    files = [os.path.join(inbox, f) for f in sorted(os.listdir(inbox))
             if not f.startswith(".") and media_kind(f)] if os.path.isdir(inbox) else []
    if not files:
        return []
    stamped = sorted((_added_at(f), f) for f in files)
    first = stamped[0][0]
    return [f for t, f in stamped if t == first][:max_files]


def describe(batch, work):
    """Return [(label, jpg)] frames + a media index {name: {kind, duration}} for the script writer."""
    os.makedirs(work, exist_ok=True)
    frames, index = [], {}
    for path in batch:
        name = os.path.relpath(path, REPO)
        if media_kind(path) == "video":
            d = video_duration(path)
            index[name] = {"kind": "video", "duration": round(d, 2)}
            n = 6 if d > 6 else 3
            for i in range(n):
                t = d * (i + 0.5) / n
                out = frame(path, t, os.path.join(work, f"{os.path.basename(path)}_{i}.jpg"), width=480)
                frames.append((f"{name} (video, {d:.1f}s) at t={t:.1f}s", out))
        else:
            index[name] = {"kind": "image"}
            out = os.path.join(work, os.path.basename(path) + ".jpg")
            sh(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", "scale=640:-2", "-q:v", "3", out])
            frames.append((f"{name} (photo)", out))
    return frames, index

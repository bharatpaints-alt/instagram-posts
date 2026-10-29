"""Deliver outbox messages. Every message is also visible in the client's web page and the admin API,
so a channel that is not configured loses nothing.

Channels (each optional):
  email    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM  -> client["email"]
  webhook  NOTIFY_WEBHOOK  (POST JSON {client, kind, ...}) e.g. a Claude routine, Zapier, a WhatsApp gateway
  whatsapp WHATSAPP_TOKEN + WHATSAPP_PHONE_ID (Meta Cloud API) -> client["whatsapp"]   [M4, text only]
"""
import json
import os
import re
import shutil
import smtplib
from email.message import EmailMessage

from .common import http_json

SUBJECT = {"nudge": "Aaj ki Reel ke liye photos", "review": "Aapki Reel tayyar hai - dekhiye", "posted": "Reel live ho gayi",
           "error": "Reel banane me dikkat", "publish_request": "Reel post ho rahi hai"}


def text_of(c, msg, link=""):
    k = msg["kind"]
    if k == "review":
        body = (f"Aapki Reel tayyar hai (version {msg.get('version', 1)}).\n\nScript:\n" + "\n".join(msg.get("script", [])) +
                f"\n\nCaption:\n{msg.get('caption', '')}\n\n{msg.get('voice_note', '')}\n\n"
                f"Dekhiye aur 'Yes' dabaiye ya change bataiye: {link}")
    else:
        body = msg.get("text") or json.dumps(msg, ensure_ascii=False)
        if link and k == "nudge":
            body += f"\n\nPhotos yahan upload kijiye: {link}"
    return body


def _email(c, subject, body):
    if not (os.environ.get("SMTP_HOST") and c.get("email")):
        return False
    m = EmailMessage()
    m["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))
    m["To"] = c["email"]
    m["Subject"] = f"{subject} - {c['name']}"
    m.set_content(body)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 587)), timeout=30) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
        s.send_message(m)
    return True


def _webhook(c, msg, body):
    url = os.environ.get("NOTIFY_WEBHOOK")
    if not url:
        return False
    http_json(url, {"client": c["id"], "name": c["name"], "text": body, **msg}, timeout=30)
    return True


def _whatsapp(c, body):
    tok, pid = os.environ.get("WHATSAPP_TOKEN"), os.environ.get("WHATSAPP_PHONE_ID")
    if not (tok and pid and c.get("whatsapp")):
        return False
    to = re.sub(r"\D", "", c["whatsapp"])
    to = to if len(to) > 10 else "91" + to
    http_json(f"https://graph.facebook.com/v20.0/{pid}/messages",
              {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body[:4000]}},
              headers={"authorization": f"Bearer {tok}"})
    return True


def client_link(c):
    from .onboard import client_token
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/c/{c['id']}/{client_token(c)}" if base else ""


def deliver(c):
    d = os.path.join(c["_dir"], "outbox")
    if not os.path.isdir(d):
        return 0
    sent = os.path.join(d, "sent")
    os.makedirs(sent, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        path = os.path.join(d, f)
        msg = json.load(open(path))
        if msg["kind"] == "publish_request":  # handled by the publisher (admin API / routine), not the client
            continue
        body = text_of(c, msg, client_link(c))
        try:
            got = [_email(c, SUBJECT.get(msg["kind"], "ReelFlow"), body), _webhook(c, msg, body), _whatsapp(c, body)]
        except Exception as e:  # keep it in the outbox, try next minute
            msg.setdefault("delivery_errors", []).append(str(e)[:300])
            json.dump(msg, open(path, "w"), ensure_ascii=False, indent=1)
            continue
        msg["delivered_via"] = [ch for ch, ok in zip(("email", "webhook", "whatsapp"), got) if ok] or ["web"]
        json.dump(msg, open(path, "w"), ensure_ascii=False, indent=1)
        shutil.move(path, os.path.join(sent, f))
        n += 1
    return n

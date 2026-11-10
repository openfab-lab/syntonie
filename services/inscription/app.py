#!/usr/bin/env python3
"""Inscription des membres Syntonie — MVP : la fiche part par e-mail.

Un seul fichier, bibliothèque standard uniquement. Rien n'est stocké ici :
chaque fiche validée est envoyée à l'adresse de l'association (via Resend),
où elle est encodée à la main. Le numéro de membre est attribué à l'encodage.

  GET  /                   la fiche (www/index.html)
  POST /api/verifier       valide la fiche et le code d'accueil, n'envoie rien
  POST /api/inscriptions   valide la fiche et l'envoie par e-mail, une fois le
                           paiement déclaré par la personne
  GET  /health

Configuration par variables d'environnement :
  RESEND_API_KEY   clé Resend (envoi seul). Sans elle, l'envoi répond 503.
  MAIL_TO          destinataire (défaut contact@syntonie.be)
  MAIL_FROM        expéditeur (défaut Inscriptions Syntonie <inscription@syntonie.be>)
  ACCESS_CODE      code d'accueil, donné sur place par un·e bénévole. Vide =
                   pas de code demandé.
  TEST_MODE        "1" : bandeau TEST sur la page et [TEST] dans l'objet
  PORT             défaut 8080
"""
import datetime as dt
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_API_URL = os.environ.get("RESEND_API_URL", "https://api.resend.com/emails")
MAIL_TO = os.environ.get("MAIL_TO", "contact@syntonie.be")
MAIL_FROM = os.environ.get("MAIL_FROM", "Inscriptions Syntonie <inscription@syntonie.be>")
TEST_MODE = os.environ.get("TEST_MODE", "") == "1"
ACCESS_CODE = " ".join(os.environ.get("ACCESS_CODE", "").split()).lower()
PAYMENTS = {"transfer": "virement bancaire, déclaré fait par la personne : à vérifier sur le compte",
            "desk": "à l'accueil (terminal ou cash), déclaré par la personne : à confirmer par le ou la bénévole"}
PORT = int(os.environ.get("PORT", "8080"))
WWW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")
MAX_BODY = 16 * 1024
RATE_MAX, RATE_WINDOW = 30, 600  # 30 fiches / 10 min par adresse IP

LIMITS = {"last_name": 100, "first_name": 100, "email": 200, "phone": 40, "guardian_name": 200,
          "pro_name": 200, "vat": 40, "smart": 200, "interests": 1000, "place": 80, "terms_version": 20, "code": 40}
EMAIL_RE = re.compile(r"^[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]{2,}$")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/qrcode.js": ("qrcode.js", "text/javascript; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")

_lock = threading.Lock()
_hits = {}


def now():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def rate_ok(ip):
    t = time.time()
    with _lock:
        for key in [k for k, v in _hits.items() if not v or t - v[-1] > RATE_WINDOW]:
            del _hits[key]
        recent = [x for x in _hits.get(ip, []) if t - x < RATE_WINDOW]
        ok = len(recent) < RATE_MAX
        if ok:
            recent.append(t)
        _hits[ip] = recent
        return ok


def code_ok(given):
    if not ACCESS_CODE:
        return True
    return hmac.compare_digest(given.lower().encode("utf-8"), ACCESS_CODE.encode("utf-8"))


def clean(data, need_payment):
    """Valide et normalise la fiche. Renvoie (champs, erreur)."""
    if not isinstance(data, dict):
        return None, "format"
    out = {}
    for key, size in LIMITS.items():
        val = data.get(key, "")
        if not isinstance(val, str):
            return None, key
        out[key] = " ".join(val.split())[:size] if key != "interests" else val.strip()[:size]
    out["email"] = out["email"].lower()
    out["lang"] = data.get("lang") if data.get("lang") in ("fr", "nl", "en") else "fr"
    out["is_minor"] = data.get("is_minor") is True
    out["guardian_accepted"] = data.get("guardian_accepted") is True
    for key in ("last_name", "first_name", "phone", "terms_version"):
        if not out[key]:
            return None, key
    if not EMAIL_RE.match(out["email"]):
        return None, "email"
    if data.get("accepted") is not True:
        return None, "accepted"
    if out["is_minor"] and not (out["guardian_name"] and out["guardian_accepted"]):
        return None, "guardian"
    if not out["is_minor"]:
        out["guardian_name"], out["guardian_accepted"] = "", False
    if not code_ok(out.pop("code")):
        return None, "code"
    out["payment"] = data.get("payment")
    if need_payment and out["payment"] not in PAYMENTS:
        return None, "payment"
    return out, None


def mail_text(f, stamp, year):
    yes = lambda b: "oui" if b else "non"
    lines = [
        "Nouvelle fiche d'inscription, membre adhérent.",
        "",
        "Nom : " + f["last_name"],
        "Prénom : " + f["first_name"],
        "E-mail : " + f["email"],
        "Téléphone : " + f["phone"],
        "Langue de la fiche : " + f["lang"],
        "",
        "Mineur·e : " + yes(f["is_minor"]),
    ]
    if f["is_minor"]:
        lines += ["Personne responsable : " + f["guardian_name"],
                  "Lu et approuvé par la personne responsable : " + yes(f["guardian_accepted"])]
    lines += [
        "",
        "Professionnel, dénomination : " + (f["pro_name"] or "-"),
        "Numéro de TVA : " + (f["vat"] or "-"),
        "Smart, activité : " + (f["smart"] or "-"),
        "",
        "Centres d'intérêt :",
        f["interests"] or "-",
        "",
        "Lu et approuvé : oui",
        "Fiche version : " + f["terms_version"],
        "Fait à : " + (f["place"] or "-") + ", le " + stamp,
        "",
        "Cotisation %d : %s." % (year, PAYMENTS[f["payment"]]),
        "Communication du virement : Cotisation %d %s %s" % (year, f["last_name"], f["first_name"]),
        "",
        "Numéro de membre : à attribuer lors de l'encodage.",
        "Répondre à ce message écrit directement à la personne.",
    ]
    return "\n".join(lines)


def send_mail(f):
    stamp, year = now(), dt.date.today().year
    subject = "%sInscription membre : %s %s" % ("[TEST] " if TEST_MODE else "", f["last_name"], f["first_name"])
    body = json.dumps({"from": MAIL_FROM, "to": [MAIL_TO], "reply_to": f["email"],
                       "subject": subject, "text": mail_text(f, stamp, year)}).encode("utf-8")
    req = urllib.request.Request(RESEND_API_URL, data=body, method="POST", headers={
        "Authorization": "Bearer " + RESEND_API_KEY, "Content-Type": "application/json",
        "User-Agent": "syntonie-inscription/1.0"})
    with urllib.request.urlopen(req, timeout=15) as res:
        res.read()
    return year


class Handler(BaseHTTPRequestHandler):
    server_version = "syntonie-inscription"

    def log_message(self, fmt, *args):  # pas de données personnelles dans les journaux
        pass

    def log(self, code, note=""):
        print("%s %s %d %s" % (self.command, urlparse(self.path).path, code, note), flush=True)

    def reply(self, code, body=b"", ctype="text/plain; charset=utf-8", note=""):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.log(code, note)

    def json(self, code, obj, note=""):
        self.reply(code, json.dumps(obj), "application/json", note)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self.reply(200, "ok")
        if path in STATIC:
            name, ctype = STATIC[path]
            with open(os.path.join(WWW, name), "rb") as fh:
                body = fh.read()
            if name == "index.html":
                body = body.replace(b"__TEST_MODE__", b"1" if TEST_MODE else b"0")
                body = body.replace(b"__NEED_CODE__", b"1" if ACCESS_CODE else b"0")
            return self.reply(200, body, ctype)
        self.reply(404, "introuvable")

    do_HEAD = do_GET

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/inscriptions", "/api/verifier"):
            return self.reply(404, "introuvable")
        sending = path == "/api/inscriptions"
        ip = self.headers.get("X-Forwarded-For", "").split(",")[-1].strip() or self.client_address[0]
        if not rate_ok(ip):
            return self.json(429, {"error": "rate"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if size <= 0 or size > MAX_BODY:
            return self.json(400, {"error": "body"})
        try:
            data = json.loads(self.rfile.read(size))
        except ValueError:
            return self.json(400, {"error": "json"})
        if isinstance(data, dict) and data.get("website"):  # champ piège rempli = robot
            return self.json(400, {"error": "format"})
        fields, err = clean(data, need_payment=sending)
        if err:
            return self.json(403 if err == "code" else 400, {"error": err})
        if not sending:
            return self.json(200, {"ok": True})
        if not RESEND_API_KEY:
            return self.json(503, {"error": "mail"}, "pas de clé d'envoi")
        try:
            year = send_mail(fields)
        except urllib.error.HTTPError as ex:
            return self.json(502, {"error": "mail"}, "envoi refusé : HTTP %d" % ex.code)
        except Exception as ex:
            return self.json(502, {"error": "mail"}, "envoi impossible : %s" % type(ex).__name__)
        self.json(201, {"year": year})


def main():
    print("inscription : port %d, vers %s, test=%s, clé=%s, code d'accueil=%s" % (
        PORT, MAIL_TO, TEST_MODE, "oui" if RESEND_API_KEY else "NON (envoi coupé)",
        "oui" if ACCESS_CODE else "NON (fiche ouverte à tous)"), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

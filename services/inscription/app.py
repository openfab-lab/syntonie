#!/usr/bin/env python3
"""Inscription des membres Syntonie — MVP : la fiche part par e-mail.

Un seul fichier, bibliothèque standard uniquement. Rien n'est stocké ici :
chaque fiche validée est envoyée à l'adresse de l'association (via Resend),
où elle est encodée à la main. Le numéro de membre est attribué à l'encodage.

  GET  /                   la fiche (www/index.html)
  POST /api/verifier       valide la fiche et le code d'accueil, n'envoie rien
  POST /api/paiements      valide la fiche comme /api/verifier, puis crée une
                           commande Citizen Pay de la cotisation
  GET  /api/paiements/<n>  état de cette commande (attente, scanné, en cours,
                           payé, annulé), relayé depuis Citizen Pay
  POST /api/inscriptions   valide la fiche et l'envoie par e-mail, une fois le
                           paiement déclaré par la personne, ou vérifié ici
                           quand il passe par Citizen Pay
  GET  /health

Configuration par variables d'environnement :
  RESEND_API_KEY   clé Resend (envoi seul). Sans elle, l'envoi répond 503.
  MAIL_TO          destinataire (défaut contact@syntonie.be)
  MAIL_FROM        expéditeur (défaut Inscriptions Syntonie <inscription@syntonie.be>)
  ACCESS_CODE      code d'accueil, donné sur place par un·e bénévole. Vide =
                   pas de code demandé.
  TEST_MODE        "1" : bandeau TEST sur la page et [TEST] dans l'objet
  CITIZENPAY_PLACE lieu Citizen Pay qui reçoit la cotisation (id ou slug).
                   Vide = pas de Citizen Pay, virement et accueil seulement.
  CITIZENPAY_API_URL       défaut https://api2.citizenpay.xyz
  FEE_CENTS        cotisation en centimes (défaut 2500), doit valoir FEE de la page
  PORT             défaut 8080
"""
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_API_URL = os.environ.get("RESEND_API_URL", "https://api.resend.com/emails")
MAIL_TO = os.environ.get("MAIL_TO", "contact@syntonie.be")
MAIL_FROM = os.environ.get("MAIL_FROM", "Inscriptions Syntonie <inscription@syntonie.be>")
TEST_MODE = os.environ.get("TEST_MODE", "") == "1"
ACCESS_CODE = " ".join(os.environ.get("ACCESS_CODE", "").split()).lower()
PAYMENTS = {"transfer": "virement bancaire, déclaré fait par la personne : à vérifier sur le compte",
            "desk": "par carte au terminal de l'accueil, déclaré par la personne : à vérifier sur le compte"}
CITIZENPAY_PLACE = os.environ.get("CITIZENPAY_PLACE", "").strip()
CITIZENPAY_API_URL = os.environ.get("CITIZENPAY_API_URL", "").strip().rstrip("/") or "https://api2.citizenpay.xyz"
FEE_CENTS = int(os.environ.get("FEE_CENTS", "") or "2500")
# États Citizen Pay → états montrés sur la page. Inconnu = attente.
STATUS = {"pending": "waiting", "checkout": "scanned", "confirming": "confirming", "paid": "paid",
          "cancelled": "cancelled", "failed": "cancelled"}
# Secret du jeton de commande, tiré au démarrage et jamais écrit nulle part.
# Le jeton prouve que la commande a été créée ici : sans lui, le serveur
# refuse de relayer l'état d'une commande quelconque. Un redémarrage rend les
# jetons en cours invalides ; la personne passe alors par le virement.
PAY_SECRET = os.urandom(32)
UA = "syntonie-inscription/1.0"
PORT = int(os.environ.get("PORT", "8080"))
WWW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")
MAX_BODY = 16 * 1024
RATE_MAX, RATE_WINDOW = 30, 600  # 30 fiches / 10 min par adresse IP
# Suivi du paiement : la page demande l'état toutes les 2 s, soit 300 fois en
# 10 min. Les personnes à l'atelier partagent souvent la même adresse IP.
POLL_MAX = 1500
ORDER_PATH = re.compile(r"^/api/paiements/(\d{1,12})$")

LIMITS = {"last_name": 100, "first_name": 100, "email": 200, "phone": 40, "guardian_name": 200,
          "pro_name": 200, "vat": 40, "smart": 200, "interests": 1000, "place": 80, "terms_version": 20, "code": 40}
EMAIL_RE = re.compile(r"^[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]{2,}$")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/qrcode.js": ("qrcode.js", "text/javascript; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")

_lock = threading.Lock()
_hits = {}
_polls = {}
_used = set()  # commandes déjà envoyées par e-mail (numéros seulement, en mémoire)


def now():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def rate_ok(ip, hits=_hits, limit=RATE_MAX):
    t = time.time()
    with _lock:
        for key in [k for k, v in hits.items() if not v or t - v[-1] > RATE_WINDOW]:
            del hits[key]
        recent = [x for x in hits.get(ip, []) if t - x < RATE_WINDOW]
        ok = len(recent) < limit
        if ok:
            recent.append(t)
        hits[ip] = recent
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
    if need_payment and out["payment"] not in PAYMENTS and not (
            out["payment"] == "citizenpay" and CITIZENPAY_PLACE):
        return None, "payment"
    return out, None


# ------------------------------------------------------------ Citizen Pay
# La commande est publique : qui connaît son numéro peut la lire. Elle ne
# porte donc aucun nom, seulement « Cotisation <année> OpenFab ».

def order_id(val):
    """Numéro de commande venu de la page ou de Citizen Pay, ou None."""
    if isinstance(val, bool):
        return None
    if isinstance(val, int) and 0 < val < 10 ** 12:
        return val
    if isinstance(val, str) and re.fullmatch(r"\d{1,12}", val):
        return int(val)
    return None


def pay_token(oid):
    return hmac.new(PAY_SECRET, b"order:%d" % oid, hashlib.sha256).hexdigest()


def token_ok(oid, token):
    return isinstance(token, str) and hmac.compare_digest(token.encode("utf-8"), pay_token(oid).encode("ascii"))


def cp_get(path, query=None):
    url = CITIZENPAY_API_URL + path + ("?" + urlencode(query) if query else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=8) as res:
        return json.loads(res.read(64 * 1024))


def cp_order(oid):
    data = cp_get("/v2/orders/%d" % oid)
    if not isinstance(data, dict):
        raise ValueError("réponse inattendue")
    return data


def create_order():
    """Crée la commande de la cotisation. Renvoie (numéro, lien de paiement)."""
    year = dt.date.today().year
    made = cp_get("/v2/places/%s/orders/create" % quote(CITIZENPAY_PLACE, safe=""),
                  {"amount": FEE_CENTS, "description": "Cotisation %d OpenFab" % year, "format": "json"})
    oid = order_id(made.get("orderId") if isinstance(made, dict) else None)
    if oid is None:
        raise ValueError("pas de numéro de commande")
    # Le lien de paiement est celui que Citizen Pay renvoie, pris tel quel : sa
    # forme lui appartient. On vérifie seulement que c'est une adresse web,
    # puisqu'il finit dans un QR et dans un lien de la page.
    link = made.get("checkoutUrl")
    if not isinstance(link, str) or len(link) > 500 or not re.fullmatch(r"https?://[^\s\"'<>\\]+", link):
        raise ValueError("pas de lien de paiement")
    return oid, link


def order_paid(o):
    """La commande est payée, au bon montant, au lieu de l'association."""
    place = o.get("place") if isinstance(o.get("place"), dict) else {}
    ours = {str(x).lower() for x in (o.get("place_id"), place.get("id"), place.get("slug")) if x}
    total = o.get("total")
    return (o.get("status") == "paid" and isinstance(total, int) and not isinstance(total, bool)
            and total == FEE_CENTS and CITIZENPAY_PLACE.lower() in ours)


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
    ]
    if f["payment"] == "citizenpay":
        lines += ["Cotisation %d : payée via Citizen Pay, commande n° %d (%s €), "
                  "paiement vérifié par le serveur auprès de Citizen Pay." % (
                      year, f["order"], "%d,%02d" % divmod(FEE_CENTS, 100))]
    else:
        lines += ["Cotisation %d : %s." % (year, PAYMENTS[f["payment"]]),
                  "Communication du virement : Cotisation %d %s %s" % (year, f["last_name"], f["first_name"])]
    lines += [
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
        "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as res:
        res.read()
    return year


class Handler(BaseHTTPRequestHandler):
    server_version = "syntonie-inscription"

    def log_message(self, fmt, *args):  # pas de données personnelles dans les journaux
        pass

    def log(self, code, note=""):
        print("%s %s %d %s" % (self.command, urlparse(self.path).path, code, note), flush=True)

    def reply(self, code, body=b"", ctype="text/plain; charset=utf-8", note="", quiet=False):
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
        if not quiet:
            self.log(code, note)

    def json(self, code, obj, note="", quiet=False):
        self.reply(code, json.dumps(obj), "application/json", note, quiet)

    def ip(self):
        return self.headers.get("X-Forwarded-For", "").split(",")[-1].strip() or self.client_address[0]

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/health":
            return self.reply(200, "ok")
        match = ORDER_PATH.match(path)
        if match and CITIZENPAY_PLACE and self.command == "GET":
            return self.pay_status(int(match.group(1)), parse_qs(url.query).get("token", [""])[0])
        if path in STATIC:
            name, ctype = STATIC[path]
            with open(os.path.join(WWW, name), "rb") as fh:
                body = fh.read()
            if name == "index.html":
                body = body.replace(b"__TEST_MODE__", b"1" if TEST_MODE else b"0")
                body = body.replace(b"__NEED_CODE__", b"1" if ACCESS_CODE else b"0")
                body = body.replace(b"__CITIZENPAY__", b"1" if CITIZENPAY_PLACE else b"0")
            return self.reply(200, body, ctype)
        self.reply(404, "introuvable")

    do_HEAD = do_GET

    def pay_status(self, oid, token):
        if not rate_ok(self.ip(), _polls, POLL_MAX):
            return self.json(429, {"error": "rate"})
        if not token_ok(oid, token):
            return self.json(403, {"error": "token"})
        try:
            status = cp_order(oid).get("status")
        except urllib.error.HTTPError as ex:
            return self.json(502, {"error": "pay"}, "Citizen Pay : HTTP %d" % ex.code)
        except Exception as ex:
            return self.json(502, {"error": "pay"}, "Citizen Pay injoignable : %s" % type(ex).__name__)
        # Une ligne toutes les 2 s par personne qui paie : on ne journalise
        # que la fin (payé ou annulé) et les erreurs.
        shown = STATUS.get(status, "waiting")
        self.json(200, {"status": shown}, "commande %d : %s" % (oid, shown),
                  quiet=shown not in ("paid", "cancelled"))

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/inscriptions", "/api/verifier", "/api/paiements"):
            return self.reply(404, "introuvable")
        if path == "/api/paiements" and not CITIZENPAY_PLACE:
            return self.reply(404, "introuvable")
        sending = path == "/api/inscriptions"
        if not rate_ok(self.ip()):
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
        if path == "/api/paiements":
            try:
                oid, link = create_order()
            except urllib.error.HTTPError as ex:
                return self.json(502, {"error": "pay"}, "création refusée par Citizen Pay : HTTP %d" % ex.code)
            except Exception as ex:
                return self.json(502, {"error": "pay"}, "création impossible : %s" % type(ex).__name__)
            return self.json(201, {"order": oid, "token": pay_token(oid), "url": link}, "commande %d" % oid)
        if not sending:
            return self.json(200, {"ok": True})
        if not RESEND_API_KEY:
            return self.json(503, {"error": "mail"}, "pas de clé d'envoi")
        oid = None
        if fields["payment"] == "citizenpay":
            oid = order_id(data.get("order"))
            if oid is None or not token_ok(oid, data.get("token")):
                return self.json(402, {"error": "unpaid"}, "jeton absent ou faux")
            try:
                paid = order_paid(cp_order(oid))
            except Exception as ex:
                return self.json(502, {"error": "pay"}, "vérification impossible : %s" % type(ex).__name__)
            if not paid:
                return self.json(402, {"error": "unpaid"}, "commande %d non payée ici" % oid)
            # Une commande payée ne vaut que pour une fiche : la seconde
            # demande (double clic, deux onglets, rejeu) n'envoie rien.
            with _lock:
                if oid in _used:
                    return self.json(409, {"error": "used"}, "commande %d déjà envoyée" % oid)
                _used.add(oid)
            fields["order"] = oid
        try:
            year = send_mail(fields)
        except urllib.error.HTTPError as ex:
            self.release(oid)
            return self.json(502, {"error": "mail"}, "envoi refusé : HTTP %d" % ex.code)
        except Exception as ex:
            self.release(oid)
            return self.json(502, {"error": "mail"}, "envoi impossible : %s" % type(ex).__name__)
        self.json(201, {"year": year})

    @staticmethod
    def release(oid):
        if oid is not None:
            with _lock:
                _used.discard(oid)


def main():
    print("inscription : port %d, vers %s, test=%s, clé=%s, code d'accueil=%s, citizen pay=%s" % (
        PORT, MAIL_TO, TEST_MODE, "oui" if RESEND_API_KEY else "NON (envoi coupé)",
        "oui" if ACCESS_CODE else "NON (fiche ouverte à tous)",
        "%s via %s" % (CITIZENPAY_PLACE, CITIZENPAY_API_URL) if CITIZENPAY_PLACE else "non"), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

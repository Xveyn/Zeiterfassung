#!/usr/bin/env python3
r"""Lokaler Test-Empfänger für den Webhook-Versand.

Nimmt POSTs entgegen und zeigt an, was die App tatsächlich geschickt hat:
Content-Type, Auth-Header, HMAC-Prüfung, und den Body je nach Format
(JSON hübsch, PDF als Kennzahl, multipart aufgetrennt in seine Teile).

Warum das ohne Zertifikat geht: `127.0.0.1` ist Loopback und fällt damit
unter die Ausnahme der URL-Regel — `http://` wird kommentarlos akzeptiert.
Für jede Adresse außerhalb des lokalen Netzes verlangt die App `https://`.

    Starten:   python scripts/webhook_testserver.py
    In der App: Einstellungen → Webhooks → Hinzufügen
                URL  http://127.0.0.1:8000/hook

Beispiele:

    # einfacher Empfänger
    python scripts/webhook_testserver.py

    # mit HMAC-Prüfung (dasselbe Secret wie im Webhook-Dialog eintragen)
    python scripts/webhook_testserver.py --secret geheim

    # PDFs mitschreiben, um sie anzusehen
    python scripts/webhook_testserver.py --save-dir .\eingang

    # Fehlerfälle der App prüfen
    python scripts/webhook_testserver.py --status 500   # Server-Fehler
    python scripts/webhook_testserver.py --status 401   # Zugangsdaten abgelehnt
    python scripts/webhook_testserver.py --redirect     # 301 — muss ABGELEHNT werden

Der Redirect-Modus ist der interessanteste Test: die App darf einem 3xx
**nicht** folgen. Täte sie es, machte urllib aus dem POST ein GET ohne Body —
der Bericht käme nie an, der Endpunkt antwortete 200, und die App meldete
Erfolg. Erwartet wird stattdessen: „Der Endpunkt hat weitergeleitet — bitte
die endgültige Adresse eintragen."

Reine stdlib, läuft mit demselben Python wie die App.
"""

import argparse
import datetime
import hashlib
import hmac
import json
import pathlib
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# Header, die für den Versand interessant sind. Alles andere (Host, Accept,
# Connection …) wäre nur Rauschen.
INTERESSANTE_HEADER = (
    "Content-Type", "Content-Length", "User-Agent",
    "Authorization", "X-Api-Key", "X-Hub-Signature-256", "X-Signature",
)

TRENNER = "=" * 72


def _kurz(rohdaten: bytes, grenze: int = 1500) -> str:
    text = rohdaten.decode("utf-8", "replace")
    if len(text) <= grenze:
        return text
    return text[:grenze] + f"\n… (+{len(text) - grenze} weitere Zeichen)"


def _zeige_json(rohdaten: bytes) -> None:
    try:
        doc = json.loads(rohdaten)
    except ValueError as e:
        print(f"  !! kein gültiges JSON: {e}")
        print(_kurz(rohdaten, 400))
        return

    # Kurzfassung zuerst — beim Durchprobieren will man meist nur wissen,
    # ob Zeitraum und Summe zu dem passen, was im Kalender steht.
    if isinstance(doc, dict) and doc.get("kind", "").startswith("zeiterfassung-report"):
        zeitraum = doc.get("period") or {}
        eintraege = doc.get("entries") or {}
        minuten = doc.get("total_minutes")
        print(f"  kind          {doc.get('kind')} (schema_version {doc.get('schema_version')})")
        print(f"  Zeitraum      {zeitraum.get('from')} bis {zeitraum.get('to')}")
        print(f"  Tage          {len(eintraege)}")
        if isinstance(minuten, int):
            print(f"  Summe         {minuten} min  =  {minuten // 60} h {minuten % 60:02d} min")
        print(f"  Kategorien    {doc.get('categories')}")
        print(f"  Absender      {doc.get('sender')!r}   Name {doc.get('name')!r}")
        print("  ---")

    print(_kurz(json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8")))


def _zeige_pdf(rohdaten: bytes, dateiname: str, save_dir: pathlib.Path | None) -> None:
    kopf = rohdaten[:8]
    ok = b"%PDF" if kopf.startswith(b"%PDF") else b"?"
    print(f"  {len(rohdaten)} Bytes, beginnt mit {kopf!r} "
          f"({'sieht nach PDF aus' if ok == b'%PDF' else 'KEIN PDF-Kopf!'})")
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
        stempel = datetime.datetime.now().strftime("%H%M%S")
        ziel = save_dir / f"{stempel}_{dateiname or 'bericht.pdf'}"
        ziel.write_bytes(rohdaten)
        print(f"  gespeichert:  {ziel}")


def _zerlege_multipart(rohdaten: bytes, content_type: str):
    """Teilt einen multipart-Body in (headers, name, filename, inhalt) auf.

    Bewusst von Hand statt über `email`/`cgi`: die Teile sollen genau so
    gezeigt werden, wie sie auf der Leitung ankamen, und `cgi` ist seit
    Python 3.13 entfernt.
    """
    treffer = re.search(r'boundary="?([^";]+)"?', content_type)
    if not treffer:
        print("  !! Content-Type nennt keine boundary")
        return
    trenner = ("--" + treffer.group(1)).encode("latin-1")
    for teil in rohdaten.split(trenner):
        if teil in (b"", b"--", b"--\r\n", b"\r\n"):
            continue
        teil = teil.lstrip(b"\r\n")
        kopf, _, inhalt = teil.partition(b"\r\n\r\n")
        inhalt = inhalt.rstrip(b"\r\n")
        kopfzeilen = kopf.decode("utf-8", "replace").splitlines()
        disposition = next((z for z in kopfzeilen if z.lower().startswith("content-disposition")), "")
        name = (re.search(r'name="([^"]*)"', disposition) or [None, "?"])[1]
        dateiname = (re.search(r'filename="([^"]*)"', disposition) or [None, ""])[1]
        teil_ct = next((z.split(":", 1)[1].strip() for z in kopfzeilen
                        if z.lower().startswith("content-type")), "")
        yield name, dateiname, teil_ct, inhalt


class Empfaenger(BaseHTTPRequestHandler):
    secret = ""
    status = 200
    redirect = False
    save_dir: pathlib.Path | None = None

    def do_POST(self):  # noqa: N802 — von BaseHTTPRequestHandler vorgegeben
        laenge = int(self.headers.get("Content-Length") or 0)
        rohdaten = self.rfile.read(laenge)
        uhrzeit = datetime.datetime.now().strftime("%H:%M:%S")

        print(f"\n{TRENNER}\n{uhrzeit}  POST {self.path}\n{TRENNER}")
        for name in INTERESSANTE_HEADER:
            if self.headers.get(name):
                print(f"  {name}: {self.headers[name]}")

        self._pruefe_hmac(rohdaten)

        content_type = self.headers.get("Content-Type", "")
        print()
        if content_type.startswith("application/json"):
            _zeige_json(rohdaten)
        elif content_type.startswith("application/pdf"):
            _zeige_pdf(rohdaten, "bericht.pdf", self.save_dir)
        elif content_type.startswith("multipart/form-data"):
            for name, dateiname, teil_ct, inhalt in _zerlege_multipart(rohdaten, content_type):
                print(f"  --- Teil {name!r}"
                      + (f", filename={dateiname!r}" if dateiname else "")
                      + f", {teil_ct or 'ohne Content-Type'}, {len(inhalt)} Bytes")
                if teil_ct.startswith("application/json"):
                    _zeige_json(inhalt)
                elif teil_ct.startswith("application/pdf"):
                    _zeige_pdf(inhalt, dateiname, self.save_dir)
                else:
                    print(_kurz(inhalt, 400))
                print()
        else:
            print(f"  unbekannter Content-Type — {len(rohdaten)} Bytes roh:")
            print(_kurz(rohdaten, 800))

        self._antworte()

    def _pruefe_hmac(self, rohdaten: bytes) -> None:
        kopf = self.headers.get("X-Hub-Signature-256") or self.headers.get("X-Signature")
        if not kopf:
            return
        if not self.secret:
            print("  HMAC:         Signatur vorhanden, aber kein --secret angegeben")
            return
        hexwert = hmac.new(self.secret.encode("utf-8"), rohdaten, hashlib.sha256).hexdigest()
        # Präfix des Empfängers übernehmen: die App erlaubt es zu konfigurieren
        # (Default `sha256=`), ein leeres Präfix ist zulässig.
        praefix = kopf[:-len(hexwert)] if kopf.endswith(hexwert) else ""
        stimmt = hmac.compare_digest(praefix + hexwert, kopf)
        print(f"  HMAC:         {'OK' if stimmt else 'FALSCH'}"
              + ("" if stimmt else f"\n                erwartet {praefix or 'sha256='}{hexwert}"))

    def _antworte(self) -> None:
        if self.redirect:
            ziel = self.path.rstrip("/") + "/"
            print(f"\n  -> antworte mit 301 auf {ziel}")
            print("     Erwartung in der App: KEIN Erfolg, sondern der Hinweis,")
            print("     die endgültige Adresse einzutragen.")
            self.send_response(301)
            self.send_header("Location", ziel)
            self.end_headers()
            return
        print(f"\n  -> antworte mit {self.status}")
        self.send_response(self.status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        text = "ok" if self.status < 400 else f"Testserver antwortet absichtlich mit {self.status}"
        self.wfile.write(text.encode("utf-8"))

    def log_message(self, *args):
        pass  # eigenes Format oben, das Standard-Zugriffslog wäre nur Rauschen


def main() -> None:
    p = argparse.ArgumentParser(
        description="Lokaler Test-Empfänger für den Webhook-Versand.")
    p.add_argument("--port", type=int, default=8000, help="Port (Standard: 8000)")
    p.add_argument("--secret", default="",
                   help="Shared Secret für die HMAC-Prüfung (wie im Webhook-Dialog)")
    p.add_argument("--status", type=int, default=200,
                   help="Statuscode, mit dem geantwortet wird (z.B. 401, 404, 500)")
    p.add_argument("--redirect", action="store_true",
                   help="mit 301 antworten — die App muss das ABLEHNEN, nicht folgen")
    p.add_argument("--save-dir", default=None,
                   help="Verzeichnis, in das empfangene PDFs geschrieben werden")
    args = p.parse_args()

    # Zeilenweise flushen: sonst sieht man beim Umleiten in eine Datei
    # (oder in einem gepipten Terminal) minutenlang nichts.
    sys.stdout.reconfigure(line_buffering=True)

    Empfaenger.secret = args.secret
    Empfaenger.status = args.status
    Empfaenger.redirect = args.redirect
    Empfaenger.save_dir = pathlib.Path(args.save_dir) if args.save_dir else None

    print(f"Webhook-Testempfänger auf http://127.0.0.1:{args.port}/")
    print(f"  In der App eintragen:  http://127.0.0.1:{args.port}/hook")
    if args.secret:
        print(f"  HMAC-Prüfung aktiv (Secret: {len(args.secret)} Zeichen)")
    if args.redirect:
        print("  Modus: 301-Redirect — die App muss ablehnen")
    elif args.status != 200:
        print(f"  Modus: antwortet immer mit {args.status}")
    print("  Beenden mit Strg+C\n")

    try:
        HTTPServer(("127.0.0.1", args.port), Empfaenger).serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")


if __name__ == "__main__":
    main()

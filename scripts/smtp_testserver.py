#!/usr/bin/env python3
r"""Lokaler Test-Mailserver für den SMTP-Versand.

Nimmt Mails entgegen und zeigt an, was die App tatsächlich geschickt hat:
Umschlag (MAIL FROM / RCPT TO), Kopfzeilen mit dekodiertem Betreff, die
MIME-Teile einzeln und den PDF-Anhang mit Größe und Signatur.

Der zweite Zweck sind die **Fehlfälle**: für jeden Zweig in
`smtp.classify_smtp_error` gibt es einen Schalter, der ihn auslöst. So lässt
sich einmal ansehen, was der Nutzer im Fehlerfall wirklich zu lesen bekommt —
ohne ein echtes Postfach dafür zu missbrauchen.

    Starten:    python scripts/smtp_testserver.py
    In der App: Einstellungen → SMTP → Hinzufügen
                Server 127.0.0.1, Port 8025,
                Verschlüsselung „Keine Verschlüsselung"

Beispiele:

    # einfacher Empfänger, unverschlüsselt
    python scripts/smtp_testserver.py

    # mit Anmeldung — Zugangsdaten müssen passen, sonst 535
    python scripts/smtp_testserver.py --user hugo --password geheim

    # Anhänge und die rohe .eml mitschreiben, um sie anzusehen
    python scripts/smtp_testserver.py --save-dir .\eingang

    # Fehlerfälle der App prüfen
    python scripts/smtp_testserver.py --reject-auth       # „Zugangsdaten abgelehnt"
    python scripts/smtp_testserver.py --no-auth           # Server ohne AUTH
    python scripts/smtp_testserver.py --no-starttls       # Server ohne STARTTLS
    python scripts/smtp_testserver.py --reject-recipient  # 550 auf RCPT TO
    python scripts/smtp_testserver.py --reject-sender     # 550 auf MAIL FROM
    python scripts/smtp_testserver.py --status 451        # Fehlercode auf DATA
    python scripts/smtp_testserver.py --hang              # annehmen und schweigen

`--hang` ist der interessanteste Test, das Gegenstück zum Redirect-Modus des
Webhook-Servers: der Server nimmt die Verbindung an und sagt dann nichts mehr.
`smtplib` läuft in seinen Timeout und wirft `SMTPServerDisconnected` — mit dem
`TimeoutError` des Sockets im `__context__`. Genau deshalb steht in
`classify_smtp_error` die `SMTPException`-Prüfung **vor** der Offline-Prüfung.
Erwartet wird also „Der Server hat nicht geantwortet" (kind `server`), **nicht**
„keine Internetverbindung". Der Test dauert die 20 Sekunden aus
`smtp.DEFAULT_TIMEOUT`.

Verschlüsselung
---------------

Voreingestellt ist `--security none` auf Port 8025. Das braucht kein
Zertifikat und deckt Versand, MIME-Aufbau und alle Fehlercodes ab.

Für `--security starttls` bzw. `ssl` wird eins gebraucht, und es muss der App
**bekannt** sein: `smtp._tls_context()` prüft voll, und einen Schalter dagegen
gibt es bewusst nicht. Der Server legt deshalb ein selbstsigniertes Zertifikat
für `localhost`/`127.0.0.1` an und druckt beim Start die Zeile, mit der die App
es akzeptiert — `SSL_CERT_FILE` **ergänzt** den System-Zertifikatsspeicher, sie
ersetzt ihn nicht, Drive-Sync und Update-Prüfung laufen also weiter.

Reine stdlib; nur die Zertifikatserzeugung braucht `cryptography` (sonst
`--cert`/`--key` mitgeben).
"""

import argparse
import base64
import datetime
import email
import email.policy
import ipaddress
import os
import pathlib
import re
import socketserver
import ssl
import sys
import tempfile
import threading
import time

TRENNER = "=" * 72

# Name, mit dem sich der Server meldet. Fest, nicht der echte Hostname:
# er steht in der Begruessung und in jeder EHLO-Antwort und soll auf den
# ersten Blick als Testserver erkennbar sein.
SERVERNAME = "zeiterfassung-testserver"

# Standard-Ports. Bewusst hoch: die üblichen 25/465/587 sind auf manchen
# Systemen belegt (lokaler MTA) und laden zur Verwechslung mit einem echten
# Server ein.
STANDARD_PORTS = {"none": 8025, "starttls": 8587, "ssl": 8465}

# Gültigkeit des selbst erzeugten Zertifikats. Kurz genug, dass eine alte
# Datei nicht ewig herumliegt, lang genug, dass man sie nicht ständig neu
# in SSL_CERT_FILE eintragen muss.
ZERTIFIKAT_TAGE = 90

# Ausgabe aus mehreren Verbindungs-Threads: ohne Sperre schieben sich zwei
# Mail-Berichte ineinander.
_ausgabe_sperre = threading.Lock()


def _zeige(text):
    with _ausgabe_sperre:
        print(text, flush=True)


def _zeitstempel():
    return datetime.datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------- Zertifikat


def _zertifikat_gueltig(pfad):
    """Prüft, ob eine vorhandene Datei noch lange genug läuft.

    Wiederverwenden statt neu erzeugen ist kein Geiz: die Datei steht in der
    `SSL_CERT_FILE` des Nutzers. Ein frisches Zertifikat bei jedem Start
    entwertete die Umgebungsvariable einer bereits laufenden App.
    """
    try:
        from cryptography import x509
    except ImportError:
        return False
    try:
        cert = x509.load_pem_x509_certificate(pfad.read_bytes())
        rest = cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)
    except Exception:
        # Unlesbar, oder eine cryptography ohne `not_valid_after_utc`: dann
        # lieber neu erzeugen als auf gut Glueck weiterverwenden.
        return False
    return rest > datetime.timedelta(days=7)


def _erzeuge_zertifikat(pfad):
    """Selbstsigniertes Zertifikat für localhost/127.0.0.1.

    `BasicConstraints(ca=True)` ist nötig, weil das Zertifikat über
    `SSL_CERT_FILE` als **Wurzel** eingebunden wird — ein reines
    Endzertifikat lehnt OpenSSL dort ab.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        sys.exit(
            "Für --security starttls/ssl wird ein Zertifikat gebraucht.\n"
            "Entweder  pip install cryptography  (dann erzeugt der Server "
            "eins selbst),\noder ein eigenes über --cert/--key mitgeben."
        )

    schluessel = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Zeiterfassung Testserver"),
    ])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(schluessel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(jetzt - datetime.timedelta(minutes=5))
        .not_valid_after(jetzt + datetime.timedelta(days=ZERTIFIKAT_TAGE))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                       critical=True)
        .sign(schluessel, hashes.SHA256())
    )
    pfad.write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
        + schluessel.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return pfad


def _zertifikat_besorgen(opts):
    """Liefert (cert_pfad, key_pfad_oder_None) für den TLS-Kontext."""
    if opts.cert:
        return pathlib.Path(opts.cert), (pathlib.Path(opts.key) if opts.key else None)

    pfad = pathlib.Path(tempfile.gettempdir()) / "zeiterfassung-smtp-testserver.pem"
    if _zertifikat_gueltig(pfad):
        _zeige(f"Zertifikat wiederverwendet: {pfad}")
    else:
        _erzeuge_zertifikat(pfad)
        _zeige(f"Zertifikat neu erzeugt ({ZERTIFIKAT_TAGE} Tage gültig): {pfad}")
    return pfad, None


def _tls_kontext(opts):
    cert, key = _zertifikat_besorgen(opts)
    kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    kontext.load_cert_chain(str(cert), str(key) if key else None)
    return kontext, cert


# ------------------------------------------------------------ Mail anzeigen


def _adresse(argument):
    """Die nackte Adresse aus `MAIL FROM:<a@b> SIZE=775` bzw. `RCPT TO:<a@b>`.

    Die ESMTP-Parameter hinter der Adresse gehoeren nicht in die Anzeige des
    Umschlags — sonst liest sich der Absender als „<a@b> size=775".
    """
    roh = argument.partition(":")[2].strip()
    if roh.startswith("<"):
        return roh[1:roh.index(">")] if ">" in roh else roh[1:]
    return roh.split(" ")[0]


def _kurz(text, grenze=800):
    if len(text) <= grenze:
        return text
    return text[:grenze] + f"\n… (+{len(text) - grenze} weitere Zeichen)"


def _teil_beschreiben(teil, index, opts, ziel_name):
    """Ein MIME-Teil als Textblock. Gibt die Zeilen zurück."""
    typ = teil.get_content_type()
    zeilen = [f"  [{index}] {typ}"]

    nutzlast = teil.get_payload(decode=True) or b""
    zeilen.append(f"      {len(nutzlast)} Bytes, "
                  f"Transfer-Encoding {teil.get('content-transfer-encoding', '—')}")

    if typ.startswith("text/"):
        zeichensatz = teil.get_content_charset() or "us-ascii"
        zeilen.append(f"      charset={zeichensatz}")
        try:
            text = nutzlast.decode(zeichensatz, errors="replace")
        except LookupError:
            text = nutzlast.decode("utf-8", errors="replace")
        # Eine der drei UTF-8-Pflichten aus CLAUDE.md sitzt im HTML selbst;
        # hier ist die Stelle, an der man sie einmal wirklich sieht.
        if typ == "text/html":
            # Die Anfuehrungszeichen sind optional und das Attribut kann
            # Leerzeichen tragen — eine reine Substring-Suche nach
            # `charset=utf-8` meldete das gesetzte `charset="utf-8"` als
            # fehlend und damit ausgerechnet einen Fehlalarm auf der Pflicht,
            # die hier geprueft werden soll.
            gesetzt = re.search(r"charset\s*=\s*[\"']?utf-8", text, re.I)
            marke = "vorhanden" if gesetzt else "FEHLT"
            zeilen.append(f"      <meta charset=\"utf-8\">: {marke}")
        zeilen.append("      ---")
        for zeile in _kurz(text).splitlines():
            zeilen.append(f"      {zeile}")
        zeilen.append("      ---")
    else:
        dateiname = teil.get_filename() or "(ohne Namen)"
        zeilen.append(f"      Dateiname: {dateiname}")
        if nutzlast[:5] == b"%PDF-":
            kopf = nutzlast[:8].decode("ascii", "replace").strip()
            zeilen.append(f"      Signatur: {kopf} — sieht nach einem PDF aus")
        elif typ == "application/pdf":
            zeilen.append("      Signatur: !! kein %PDF- am Anfang")

        if opts.save_dir:
            ziel = pathlib.Path(opts.save_dir)
            ziel.mkdir(parents=True, exist_ok=True)
            sicher = pathlib.Path(dateiname).name or f"anhang-{index}"
            datei = ziel / f"{ziel_name}-{sicher}"
            datei.write_bytes(nutzlast)
            zeilen.append(f"      gespeichert: {datei}")

    return zeilen


def _zeige_mail(rohdaten, umschlag_von, umschlag_an, opts):
    ziel_name = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    zeilen = [
        TRENNER,
        f"{_zeitstempel()}  Mail empfangen ({len(rohdaten)} Bytes)",
        TRENNER,
        "Umschlag (das, was wirklich zugestellt würde):",
        f"  MAIL FROM: {umschlag_von or '— (leerer Absender)'}",
        f"  RCPT TO:   {', '.join(umschlag_an) or '—'}",
    ]

    try:
        nachricht = email.message_from_bytes(rohdaten, policy=email.policy.default)
        roh = email.message_from_bytes(rohdaten)
    except Exception as e:
        zeilen.append(f"  !! Nachricht nicht lesbar: {e}")
        _zeige("\n".join(zeilen))
        return

    zeilen.append("")
    zeilen.append("Kopfzeilen:")
    for feld in ("From", "To", "Subject"):
        zeilen.append(f"  {feld}: {nachricht.get(feld, '—')}")

    # Der Betreff geht als RFC-2047-Wort über die Leitung, sobald er
    # Nicht-ASCII enthält. Beide Formen zu zeigen ist der eigentliche
    # Umlaut-Test: oben lesbar, hier so, wie es wirklich gesendet wurde.
    roh_betreff = roh.get("Subject", "")
    if roh_betreff != str(nachricht.get("Subject", "")):
        zeilen.append(f"  Subject (roh): {roh_betreff}")

    fehlend = [f for f in ("Date", "Message-ID") if not nachricht.get(f)]
    if fehlend:
        zeilen.append(f"  Hinweis: {', '.join(fehlend)} fehlt — setzt "
                      "üblicherweise der annehmende Server.")

    zeilen.append("")
    zeilen.append("MIME-Teile:")
    index = 0
    for teil in nachricht.walk():
        if teil.get_content_maintype() == "multipart":
            zeilen.append(f"  ({teil.get_content_type()})")
            continue
        index += 1
        zeilen.extend(_teil_beschreiben(teil, index, opts, ziel_name))

    if opts.save_dir:
        ziel = pathlib.Path(opts.save_dir)
        ziel.mkdir(parents=True, exist_ok=True)
        datei = ziel / f"{ziel_name}.eml"
        datei.write_bytes(rohdaten)
        zeilen.append(f"\nRohe Nachricht gespeichert: {datei}")

    zeilen.append(TRENNER)
    _zeige("\n".join(zeilen))


# --------------------------------------------------------------- Protokoll


class SmtpHandler(socketserver.StreamRequestHandler):
    # Der Server reicht Optionen und TLS-Kontext über sich selbst durch;
    # die Annotation macht das explizit (und beruhigt den Editor).
    server: "SmtpServer"

    # Ohne Timeout bleibt ein Thread an einem Client hängen, der die
    # Verbindung offen lässt und nichts mehr schickt.
    timeout = 300

    def setup(self):
        opts = self.server.opts
        if opts.security == "ssl":
            self.request = self.server.tls_kontext.wrap_socket(
                self.request, server_side=True)
        super().setup()

    # -- kleine Helfer ----------------------------------------------------

    def _sende(self, zeile):
        if self.server.opts.trace:
            _zeige(f"  >> {zeile}")
        self.wfile.write(zeile.encode("utf-8") + b"\r\n")
        self.wfile.flush()

    def _lies(self):
        roh = self.rfile.readline()
        if not roh:
            return None
        zeile = roh.decode("utf-8", "replace").rstrip("\r\n")
        if self.server.opts.trace:
            # Die AUTH-Zeile trägt das Passwort base64-kodiert, also
            # praktisch im Klartext. Im Trace hat es nichts verloren.
            sichtbar = zeile.split(" ")[0] + " …" if zeile.upper().startswith(
                "AUTH ") else zeile
            _zeige(f"  << {sichtbar}")
        return zeile

    def _ehlo_antwort(self, domain):
        opts = self.server.opts
        merkmale = ["SIZE 35882577", "8BITMIME"]
        if opts.security == "starttls" and not self.tls_aktiv and not opts.no_starttls:
            merkmale.append("STARTTLS")
        if not opts.no_auth:
            merkmale.append("AUTH PLAIN LOGIN")

        kopf = f"{SERVERNAME} Hallo {domain}"
        zeilen = [kopf] + merkmale
        for eintrag in zeilen[:-1]:
            self._sende(f"250-{eintrag}")
        self._sende(f"250 {zeilen[-1]}")

    def _pruefe_anmeldung(self, benutzer, passwort):
        opts = self.server.opts
        maske = f"{len(passwort)} Zeichen" if passwort else "LEER"
        _zeige(f"{_zeitstempel()}  Anmeldung: Benutzer {benutzer!r}, "
               f"Passwort {maske}")

        if opts.reject_auth:
            self._sende("535 5.7.8 Authentication credentials invalid")
            return False
        if opts.user is not None and (benutzer != opts.user
                                      or passwort != (opts.password or "")):
            self._sende("535 5.7.8 Authentication credentials invalid")
            return False
        self._sende("235 2.7.0 Authentication successful")
        return True

    def _auth(self, argumente):
        """AUTH PLAIN und AUTH LOGIN — die beiden, die `smtplib` nach
        CRAM-MD5 anbietet und die jeder echte Server kann."""
        teile = argumente.split()
        mechanismus = (teile[0] if teile else "").upper()

        if mechanismus == "PLAIN":
            if len(teile) > 1:
                roh = teile[1]
            else:
                self._sende("334 ")
                roh = self._lies() or ""
            try:
                entpackt = base64.b64decode(roh).decode("utf-8", "replace")
            except Exception:
                self._sende("501 5.5.2 Cannot decode AUTH PLAIN argument")
                return
            felder = entpackt.split("\x00")
            benutzer = felder[1] if len(felder) > 2 else ""
            passwort = felder[2] if len(felder) > 2 else ""

        elif mechanismus == "LOGIN":
            if len(teile) > 1:
                benutzer_roh = teile[1]
            else:
                self._sende("334 " + base64.b64encode(b"Username:").decode())
                benutzer_roh = self._lies() or ""
            self._sende("334 " + base64.b64encode(b"Password:").decode())
            passwort_roh = self._lies() or ""
            try:
                benutzer = base64.b64decode(benutzer_roh).decode("utf-8", "replace")
                passwort = base64.b64decode(passwort_roh).decode("utf-8", "replace")
            except Exception:
                self._sende("501 5.5.2 Cannot decode AUTH LOGIN argument")
                return
        else:
            self._sende("504 5.5.4 Unrecognized authentication type")
            return

        self.angemeldet = self._pruefe_anmeldung(benutzer, passwort)

    def _starttls(self):
        opts = self.server.opts
        if opts.security != "starttls" or opts.no_starttls:
            self._sende("502 5.5.1 Command not implemented")
            return
        self._sende("220 2.0.0 Ready to start TLS")
        self.request = self.server.tls_kontext.wrap_socket(
            self.request, server_side=True)
        # rfile/wfile hängen am alten, unverschlüsselten Socket — ohne
        # Neuaufbau läse der Handler weiter am Klartext-Strom.
        self.connection = self.request
        self.rfile = self.connection.makefile("rb", self.rbufsize)
        self.wfile = self.connection.makefile("wb", 0)
        self.tls_aktiv = True
        # RFC 3207: nach STARTTLS ist der Zustand zu verwerfen.
        self.angemeldet = False
        self.umschlag_von = ""
        self.umschlag_an = []
        _zeige(f"{_zeitstempel()}  STARTTLS ausgehandelt")

    def _daten_lesen(self):
        """Liest bis zum einzelnen Punkt und macht das Dot-Stuffing rückgängig."""
        stuecke = []
        while True:
            zeile = self.rfile.readline()
            if not zeile:
                return None
            if zeile in (b".\r\n", b".\n"):
                break
            if zeile.startswith(b".."):
                zeile = zeile[1:]
            stuecke.append(zeile)
        return b"".join(stuecke)

    # -- Hauptschleife ----------------------------------------------------

    def handle(self):
        opts = self.server.opts
        self.tls_aktiv = opts.security == "ssl"
        self.angemeldet = False
        self.umschlag_von = ""
        self.umschlag_an = []

        adresse = f"{self.client_address[0]}:{self.client_address[1]}"
        _zeige(f"{_zeitstempel()}  Verbindung von {adresse}")

        if opts.hang:
            _zeige(f"{_zeitstempel()}  --hang: Verbindung angenommen, es folgt "
                   f"KEINE Begrüßung ({opts.hang_seconds}s). Erwartet wird in "
                   "der App „Der Server hat nicht geantwortet\", nicht "
                   "„keine Internetverbindung\".")
            time.sleep(opts.hang_seconds)
            return

        self._sende(f"220 {SERVERNAME} ESMTP bereit")

        while True:
            zeile = self._lies()
            if zeile is None:
                break
            befehl, _, argumente = zeile.partition(" ")
            befehl = befehl.upper()

            if befehl == "EHLO":
                self._ehlo_antwort(argumente.strip() or "(ohne Domain)")
            elif befehl == "HELO":
                self._sende(f"250 {SERVERNAME}")
            elif befehl == "STARTTLS":
                self._starttls()
            elif befehl == "AUTH":
                self._auth(argumente)
            elif befehl == "NOOP":
                # Der „Verbindung testen"-Button endet genau hier.
                self._sende("250 2.0.0 OK")
                _zeige(f"{_zeitstempel()}  NOOP — Verbindungstest erfolgreich")
            elif befehl == "RSET":
                self.umschlag_von = ""
                self.umschlag_an = []
                self._sende("250 2.0.0 OK")
            elif befehl == "MAIL":
                if opts.reject_sender:
                    self._sende("550 5.1.8 Sender address rejected")
                    continue
                self.umschlag_von = _adresse(argumente)
                self.umschlag_an = []
                self._sende("250 2.1.0 OK")
            elif befehl == "RCPT":
                if opts.reject_recipient:
                    self._sende("550 5.1.1 Recipient address rejected: "
                                "User unknown")
                    continue
                self.umschlag_an.append(_adresse(argumente))
                self._sende("250 2.1.5 OK")
            elif befehl == "DATA":
                self._sende("354 Ende mit <CRLF>.<CRLF>")
                rohdaten = self._daten_lesen()
                if rohdaten is None:
                    break
                if opts.status:
                    klasse = "4.0.0" if 400 <= opts.status < 500 else "5.0.0"
                    self._sende(f"{opts.status} {klasse} Testserver lehnt "
                                "diese Nachricht ab")
                    _zeige(f"{_zeitstempel()}  DATA mit {opts.status} "
                           f"abgelehnt ({len(rohdaten)} Bytes verworfen)")
                    continue
                self._sende("250 2.0.0 OK: Nachricht angenommen")
                _zeige_mail(rohdaten, self.umschlag_von, self.umschlag_an, opts)
            elif befehl == "QUIT":
                self._sende("221 2.0.0 Tschüss")
                break
            else:
                self._sende("500 5.5.2 Unbekanntes Kommando")


class SmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    # Von main() gesetzt und von jedem Handler gelesen.
    opts: argparse.Namespace
    tls_kontext: ssl.SSLContext | None

    def handle_error(self, request, client_address):
        """Abgebrochene Verbindungen sind hier der Normalfall — ein
        Client-seitiger Timeout (`--hang`) oder ein abgelehnter TLS-Handshake
        soll keinen Traceback in die Ausgabe schreiben, die gerade das
        eigentliche Prüfergebnis zeigt."""
        fehler = sys.exc_info()[1]
        woher = ":".join(str(teil) for teil in client_address[:2])
        _zeige(f"{_zeitstempel()}  Verbindung {woher} beendet: "
               f"{type(fehler).__name__}: {fehler}")


# ------------------------------------------------------------------- Start


def _startzeilen(opts, zertifikat):
    label = {
        "none": "Keine Verschlüsselung",
        "starttls": "STARTTLS (üblich, Port 587)",
        "ssl": "SSL/TLS (Port 465)",
    }[opts.security]

    zeilen = [
        TRENNER,
        f"SMTP-Testserver läuft auf {opts.host}:{opts.port}",
        TRENNER,
        "In der App: Einstellungen → SMTP → Hinzufügen",
        f"  Server:          {opts.host}",
        f"  Port:            {opts.port}",
        f"  Verschlüsselung: {label}",
    ]
    if opts.no_auth:
        zeilen.append("  Benutzer:        leer lassen — dieser Server bietet "
                      "kein AUTH an")
    elif opts.user is not None:
        zeilen.append(f"  Benutzer:        {opts.user}")
        zeilen.append(f"  Passwort:        {opts.password or '(leer)'}")
    else:
        zeilen.append("  Benutzer:        beliebig (jede Anmeldung wird "
                      "angenommen)")
    zeilen.append("  Absender/Empfänger: beliebige Adressen")

    if opts.security != "none":
        zeilen += [
            "",
            "Das Zertifikat ist selbstsigniert. Die App prüft voll und würde es",
            "ablehnen — sie muss es also kennen. App so starten:",
            "",
            f"  PowerShell:  $env:SSL_CERT_FILE = \"{zertifikat}\"; "
            "python -m src.main",
            f"  Bash:        SSL_CERT_FILE=\"{zertifikat}\" python -m src.main",
            "",
            "SSL_CERT_FILE ergänzt den System-Zertifikatsspeicher, sie ersetzt",
            "ihn nicht — Drive-Sync und Update-Prüfung laufen weiter.",
        ]

    aktiv = [name for name, an in (
        ("--reject-auth", opts.reject_auth),
        ("--no-auth", opts.no_auth),
        ("--no-starttls", opts.no_starttls),
        ("--reject-sender", opts.reject_sender),
        ("--reject-recipient", opts.reject_recipient),
        ("--hang", opts.hang),
    ) if an]
    if opts.status:
        aktiv.append(f"--status {opts.status}")
    if aktiv:
        zeilen += ["", f"Fehlerfall aktiv: {', '.join(aktiv)}"]

    zeilen += ["", "Beenden mit Strg+C.", TRENNER]
    return "\n".join(zeilen)


def _argumente(argv=None):
    p = argparse.ArgumentParser(
        description="Lokaler Test-Mailserver für den SMTP-Versand der App.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--host", default="127.0.0.1",
                   help="Adresse zum Lauschen (Standard: 127.0.0.1)")
    p.add_argument("--port", type=int, default=None,
                   help="Port (Standard: 8025 / 8587 / 8465 je nach --security)")
    p.add_argument("--security", choices=("none", "starttls", "ssl"),
                   default="none",
                   help="Verschlüsselung des Servers (Standard: none)")
    p.add_argument("--cert", help="eigenes Zertifikat (PEM) statt eines "
                                  "selbst erzeugten")
    p.add_argument("--key", help="passender privater Schlüssel, falls nicht "
                                 "in --cert enthalten")
    p.add_argument("--user", help="erwarteter Benutzername; ohne Angabe wird "
                                  "jede Anmeldung angenommen")
    p.add_argument("--password", default="",
                   help="erwartetes Passwort (nur mit --user sinnvoll)")
    p.add_argument("--save-dir", help="Anhänge und rohe .eml hier ablegen")
    p.add_argument("--trace", action="store_true",
                   help="Protokollzeilen mitschreiben (AUTH-Zeile gekürzt)")

    fehler = p.add_argument_group("Fehlerfälle")
    fehler.add_argument("--reject-auth", action="store_true",
                        help="535 auf AUTH → „Zugangsdaten abgelehnt\"")
    fehler.add_argument("--no-auth", action="store_true",
                        help="AUTH nicht anbieten → AuthNotSupported")
    fehler.add_argument("--no-starttls", action="store_true",
                        help="STARTTLS nicht anbieten → TlsNotSupported")
    fehler.add_argument("--reject-sender", action="store_true",
                        help="550 auf MAIL FROM → „Absender abgelehnt\"")
    fehler.add_argument("--reject-recipient", action="store_true",
                        help="550 auf RCPT TO → „Empfänger abgelehnt\"")
    fehler.add_argument("--status", type=int,
                        help="dieser Fehlercode auf DATA (z.B. 451, 552)")
    fehler.add_argument("--hang", action="store_true",
                        help="annehmen und schweigen — prüft den Timeout")
    fehler.add_argument("--hang-seconds", type=int, default=60,
                        help="wie lange --hang schweigt (Standard: 60)")

    opts = p.parse_args(argv)
    if opts.port is None:
        opts.port = STANDARD_PORTS[opts.security]
    return opts


def main(argv=None):
    opts = _argumente(argv)

    zertifikat = None
    kontext = None
    if opts.security != "none":
        kontext, zertifikat = _tls_kontext(opts)

    server = SmtpServer((opts.host, opts.port), SmtpHandler)
    server.opts = opts
    server.tls_kontext = kontext

    print(_startzeilen(opts, zertifikat), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    # Ohne das kommen Umlaute auf einer Windows-Konsole mit cp1252 als
    # Fragezeichen an — ausgerechnet in dem Werkzeug, das die
    # UTF-8-Pflichten prüfen soll.
    umstellen = getattr(sys.stdout, "reconfigure", None)
    if umstellen is not None:
        umstellen(encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONUTF8", "1")
    main()

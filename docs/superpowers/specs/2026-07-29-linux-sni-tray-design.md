# Design: Linux-Tray über StatusNotifierItem (KDE Plasma)

Datum: 2026-07-29
Branch: `feat/linux-sni-tray`
Issue: #42

## Problem

`src/tray.py::is_supported()` liefert unter Linux hart `False`, `_select_backend("Linux")`
liefert `None`. Damit fehlt auf Linux nicht nur das Minimize-to-Tray, sondern es fehlen
**drei** Funktionen: `ui.py::_apply_tray_setting` schaltet bei fehlendem Tray auch
`reminders_enabled` und `send_reminder_enabled` ab, weil das Tray-Objekt zugleich der
Toast-Kanal ist (`_apply_reminder_setting`/`_apply_send_reminder_setting` lesen
`App._tray`). Reservierungs-Erinnerungen, der monatliche Sende-Reminder und die
Update-Toasts sind auf Linux also mit abgeschaltet.

Issue #42 schlägt vor, das über pystrays `appindicator`-Backend zu lösen. Drei Annahmen
des Issues halten der Prüfung nicht stand (Primärquellen: pystray-Doku und -Quelltext,
KDEs Interface-XML):

1. **„pystrays appindicator-Backend unterstützt `notify()` nicht"** — falsch. Das Backend
   erbt von `pystray/_util/gtk.py::GtkIcon`, dessen `_notify` über
   `pystray/_util/notify_dbus.py` per Gio-D-Bus an `org.freedesktop.Notifications` geht.
   Die pystray-Doku listet „keine Notifications" nur für `darwin` und `xorg`. Der im Issue
   vorgeschlagene `notify-send`-Fallback ist damit gegenstandslos.
2. **Das `xorg`-Backend ist keine GI-freie Ausweichvariante** — es „does not support any
   menu functionality except for a default action"; unser Menü trägt fünf Quick-Actions.
3. **Der Packaging-Preis ist höher als „Typelibs bündeln"** — das appindicator-Backend
   zieht PyGObject (`gi`, C-Extension) **plus GTK3** in die AppImage. Das gebündelte
   Python 3.10 kann das System-`gi` nicht mitbenutzen (Distro-Python hat eine andere ABI),
   Bündeln ist also Pflicht, nicht Kür — ein zweiter Toolkit-Stack in einer Tk-App,
   gebaut auf einem Ubuntu-Runner, ausgeführt auf Debian 13.

Dazu: pystray steht seit 0.19.5 (September 2023) still und zieht auf Linux zusätzlich
`python-xlib`.

## Ziel

Tray-Icon inklusive Menü und Toasts auf KDE Plasma — über die Schnittstelle, die KDE
selbst spricht: **StatusNotifierItem (SNI)**, reines D-Bus. Kein GTK, kein
GObject-Introspection, keine System-Bibliothek; das AppImage-Rezept bleibt unverändert.

Der Weg über pystray/appindicator legt den schwersten Teil (Packaging) genau dorthin, wo
ihn weder die CI noch die Windows-Dev-Maschine prüfen kann. Der SNI-Weg legt ihn in Code
— und Code ist prüfbar: die Layout-/Property-Logik ist pure testbar, und ein
Integrationstest gegen einen echten `dbus-daemon` mit Fake-Watcher läuft im Linux-CI-Job.
Das ist derselbe Zuschnitt-Gedanke wie in `docs/known-limitations.md`: Verhalten aus der
nicht prüfbaren Schicht herausziehen, statt es dort zu belassen.

**Gestaged, weil ohne Plasma nicht verifizierbar:** Das Backend landet vollständig, bleibt
in ausgelieferten Builds aber **dormant** (Opt-in `ZEIT_LINUX_TRAY=1`) — exakt das Muster
des macOS-Trays (#88/#96). Verifiziert wird später auf einem Debian 13 mit Plasma 6;
der Default-an-Flip ist ein eigener PR.

**Windows und macOS bleiben unangetastet.**

## Architektur

`tray.py::TrayIcon` bleibt die öffentliche Fassade mit unveränderter API. Neu ist ein
**drittes Backend** in `src/tray_linux.py`, das denselben Vertrag erfüllt wie
`tray_mac.py`:

```
LinuxTrayBackend(base_path, on_show, on_quit, actions)
    .start()   # synchron; wirft bei Fehlschlag durch
    .stop()    # idempotent
    .notify(message, title="Zeiterfassung")
```

`src/ui.py` ändert sich **nicht**. Das ist der Zweck der Fassade — und die Bestätigung,
dass `build_menu_model` als backend-agnostische Naht richtig geschnitten war: das
Linux-Backend rendert genau dieses Modell nach dbusmenu, statt sich ein eigenes Menü zu
bauen.

Eigenes Modul aus demselben Grund wie bei macOS: `dbus_fast` darf nie in den
Windows-/macOS-Importpfad geraten (`_select_backend` importiert lazy).

### Zwei D-Bus-Objekte

| Objekt | Pfad | Interface | Aufgabe |
|---|---|---|---|
| Item | `/StatusNotifierItem` | `org.kde.StatusNotifierItem` | Icon, Titel, Status, Klick-Methoden |
| Menü | `/MenuBar` | `com.canonical.dbusmenu` | Menü-Layout und Klick-Events |

Busname `org.kde.StatusNotifierItem-<pid>-1`, danach
`org.kde.StatusNotifierWatcher.RegisterStatusNotifierItem(service)` — die Signatur nimmt
laut KDEs `org.kde.StatusNotifierWatcher.xml` den **Busnamen**, nicht den Objektpfad.

### Bibliothek

`dbus-fast` (MIT, zero dependencies, pure Python mit optionaler Cython-Beschleunigung,
`requires_python >= 3.10` — trifft unseren Boden exakt). Bietet `ServiceInterface` mit
Decorators für Methoden/Properties/Signale und bedient `org.freedesktop.DBus.Properties`
und `Introspectable` automatisch. Alternative jeepney wäre ebenfalls pure Python, kennt
aber nur die Client-Seite — das Exportieren zweier Objekte müsste man dort von Hand
dispatchen.

Pin: `dbus-fast==5.0.22` (aktueller Stand am 2026-07-29). **Beim Umsetzen gegenchecken:**
Version noch aktuell, Wheels für 3.10–3.13 vorhanden (Matrix-Python), Marker
`sys_platform == "linux"`.

### Gate (dormant)

`is_supported()` bleibt eine **pure** Funktion ohne I/O:

- Windows → `True` (unverändert)
- macOS → Opt-in `ZEIT_MACOS_TRAY=1` (unverändert)
- Linux → Opt-in `ZEIT_LINUX_TRAY=1` (neu, `_linux_tray_opt_in()` analog `_macos_tray_opt_in()`)

Der spätere Default-an-Flip ersetzt die Env-Var durch die ehrliche Laufzeitprüfung „hat
diese Session einen `org.kde.StatusNotifierWatcher`?". Das ist die tatsächliche
Abhängigkeit — und deckt KDE, XFCE und GNOME-mit-AppIndicator-Extension gleichermaßen ab,
ohne die vom Issue vorgeschlagene `XDG_CURRENT_DESKTOP`-Whitelist. Der Flip ist ein
eigener PR (s. Rollout).

## Verhalten

### Klickmodell

`ItemIsMenu = False` → **Linksklick** löst `Activate(x, y)` aus → `on_show`.
**Rechtsklick** zeigt der Host selbst aus dem dbusmenu (weil `Menu` gesetzt ist).
`ContextMenu`, `SecondaryActivate`, `Scroll` und `ProvideXdgActivationToken` werden als
No-ops implementiert, damit kein Host einen `UnknownMethod` sieht.

Linux bekommt damit den **Default-Linksklick**, den der pystray/appindicator-Weg
prinzipbedingt nicht kann („All pystray features except for a menu default action").

### Icon

`IconName` leer, `IconPixmap` (`a(iiay)`) mit mehreren Größen (32/64/128) aus
`assets/margenheld-icon.png`, ARGB32 in Network-Byte-Order. Die Konvertierung ist eine
**Pillow-freie pure Funktion** (testbar ohne Bildbibliothek); Pillow dekodiert und
skaliert nur und wird lazy importiert wie im pystray-Backend — inklusive desselben
Fallbacks, wenn die PNG fehlt.

### Menü

`build_menu_model(on_show, on_quit, actions)` liefert die Struktur; das Backend rendert
sie nach dbusmenu: Wurzel `id 0` mit `children-display: "submenu"`, Kinder ab `id 1`,
Trenner als `type: "separator"`, sonst `label`/`enabled`/`visible`.

Die `visible`-Callables werden bei **jedem `AboutToShow`** neu ausgewertet; ändert sich
etwas, Revision +1, `needUpdate = True` und `LayoutUpdated` — der Host holt das Layout
neu. Linux verhält sich damit **live wie Windows**, nicht als Snapshot wie macOS: der
Sync-Eintrag erscheint und verschwindet korrekt mit `sync_enabled`. Der
Plattform-Vergleich im `_PystrayBackend`-Docstring (`tray.py`) ist entsprechend
mitzuziehen.

`Event(id, "clicked", …)` ruft den Callback; unbekannte IDs und andere Event-IDs
(`hovered`/`opened`/`closed`) werden still ignoriert. `GetLayout`,
`GetGroupProperties` und `GetProperty` bedienen dieselbe Property-Tabelle — eine Quelle,
kein zweiter Pfad.

### Toasts

`org.freedesktop.Notifications.Notify(...)` über dieselbe Verbindung — kein
`notify-send`-Subprozess und kein zusätzliches Binary im AppImage. `replaces_id = 0`,
damit eine zweite Erinnerung die erste nicht überschreibt. Fehler werden geloggt, nie
geworfen (`notify` ist vertraglich fehlertolerant).

### Threading

Ein Daemon-Thread mit eigener Asyncio-Loop — dasselbe Muster, das pystray auf Windows
fährt. `start()` blockiert auf einem Future, bis Verbindung **und** Registrierung stehen
(Timeout 10 s), und wirft dessen Exception im Aufrufer-Thread: genau der Vertrag, den
`_apply_tray_setting` erwartet. Callbacks kommen aus dem Loop-Thread und marshallen
selbst per `root.after(0, …)` — unverändertes Muster.

`stop()` gibt den Busnamen frei, stoppt die Loop, joint kurz und ist idempotent.

### Watcher-Neustart

Abo auf `NameOwnerChanged` für `org.kde.StatusNotifierWatcher`: taucht der Watcher neu
auf (plasmashell-Neustart), registriert sich das Item neu. Bewusst über YAGNI hinaus —
ohne das verschwindet das Icon nach jedem plasmashell-Neustart, und die Ursache ist von
außen praktisch nicht zu erraten.

## Betroffene Stellen

1. **`src/tray.py`** — zwei Stellen: `_linux_tray_opt_in()` + Linux-Zweig in
   `is_supported()`; `_select_backend("Linux")` → lazy `LinuxTrayBackend`. Dazu die
   Docstrings (Modul-Kopf und `_PystrayBackend`-Plattform-Vergleich), die heute „Linux hat
   kein Tray" behaupten.
2. **`src/tray_linux.py`** — neues Modul: pure Layout-/ARGB32-Helfer, die zwei
   `ServiceInterface`-Klassen, `LinuxTrayBackend` (Thread/Loop/Registrierung/Notify).
3. **`requirements.txt`** — `dbus-fast==5.0.22; sys_platform == "linux"`.
4. **`requirements-test.txt`** — derselbe Pin mit demselben Marker (nur der Linux-Job
   braucht ihn; auf Windows/macOS skippt der Integrationstest über den fehlenden Import).
   `test.yml` bleibt unverändert, **solange der Ubuntu-Runner `dbus-daemon` mitbringt** —
   tut er das nicht, kommt eine apt-Zeile dazu. Ein stiller Skip ausgerechnet im
   Linux-Job wäre genau die Evidenzlücke, die dieser Test schließen soll.
5. **`build.py::build_linux`** — `--collect-all dbus_fast`. Sonst nichts.
6. **`tests/`** — `test_tray.py` erweitern, neue `test_tray_linux.py` (pure) und
   `test_tray_linux_dbus.py` (Integration, `skipif`), `test_build.py` um den
   Collect-Guard.
7. **Doku** — `README.md` (die Plattform-Tabelle hat bis heute *gar keine* Tray-Zeile),
   `CLAUDE.md` (Modul-Liste + Tray-Absatz), `src/CLAUDE.md` (Tray-Abschnitt: drittes
   Backend, Live-vs-Snapshot), `docs/known-limitations.md` (#42-Zeile).

## Fehlerbehandlung / Edge Cases

- **Kein Watcher / kein Session-Bus** → `start()` wirft → bestehender Pfad in
  `_apply_tray_setting` (themed `showerror`, drei Settings aus). Kein neuer Pfad nötig.
  Auf Linux kommt dieser Weg nur zustande, wenn jemand die Env-Var gesetzt hat.
- **Registrierung hängt** → Future-Timeout (10 s) → dieselbe Behandlung wie ein Wurf.
- **`notify()` ohne laufendes Tray** → die Fassade prüft `_backend is None` (unverändert).
- **`stop()` mehrfach** → idempotent, wie bei den anderen Backends.
- **Quit-Pfad** → `App._quit_with_sync_push` ruft `tray.stop()` vor `root.destroy()`;
  Reihenfolge bleibt, `stop()` joint den Loop-Thread mit kurzem Timeout und blockiert das
  Beenden nicht.
- **Callback wirft** → jeder aus dem D-Bus-Dispatch gerufene Python-Callback wird
  restlos gekapselt (swallow + log); eine Exception darf nie die Loop killen und damit das
  Icon stumm schalten.

## Tests

Pure Tests (laufen auf jeder Plattform, kein D-Bus, kein Tk):

1. **`is_supported()`** — Linux ohne Opt-in → `False`, mit `ZEIT_LINUX_TRAY=1` → `True`
   (bestehende Parametrisierung in `test_tray.py` erweitern; der heutige Fall
   `("Linux", None, False)` bleibt gültig).
2. **`_select_backend("Linux")`** → `LinuxTrayBackend` (heute: `None` — der bestehende
   Test wird rot und mitgezogen).
3. **dbusmenu-Layout** aus einem Beispiel-Menü-Modell: IDs, Reihenfolge, Separatoren,
   `children-display` an der Wurzel, Labels.
4. **`visible`-Logik**: `AboutToShow` wertet die Callable neu aus; Wechsel → Revision +1
   und `needUpdate = True`, kein Wechsel → Revision unverändert, `False`.
5. **ARGB32-Konvertierung**: RGBA-Bytes → ARGB in Network-Byte-Order, ohne Pillow.

Integrationstest (nur Linux, `skipif` bei fehlendem `dbus-fast` oder `dbus-daemon`):

6. Echter `dbus-daemon --session` im Test, dazu ein Fake-`StatusNotifierWatcher` und ein
   Fake-`org.freedesktop.Notifications`. Geprüft wird: Busname belegt, Registrierung mit
   dem eigenen Namen angekommen, Item-Properties korrekt (`Category`, `Id`, `Status`,
   `ItemIsMenu`, `Menu`, `IconPixmap` nicht leer), `GetLayout` liefert Anzeigen /
   Quick-Actions / Beenden inklusive Separatoren, `Event(id, "clicked")` löst genau den
   erwarteten Callback aus, `Activate` löst `on_show` aus, `notify()` erreicht den
   Fake-Dienst, `stop()` gibt den Namen frei.

Build-Guard:

7. `tests/test_build.py` — `--collect-all dbus_fast` im Linux-Kommando (analog zum
   bestehenden Vier-Pakete-Guard).

Nicht automatisiert prüfbar (→ Plasma-Gate): sichtbares Icon, echtes Menü-Öffnen per
Klick, Icon-Darstellung in der echten Panel-Größe, Toast-Optik, Verhalten unter Wayland.

## Auslieferungs-Default & Rollout (Staging)

1. **Merge-Zustand:** Linux-Tray dormant (`is_supported()` → `False` ohne
   `ZEIT_LINUX_TRAY=1`). Für alle bestehenden Nutzer ändert sich **nichts** —
   Windows/macOS unberührt, Linux verhält sich wie heute.
2. **Verifikations-Zustand:** Pre-Release bauen (`release.yml`, Häkchen *prerelease*),
   AppImage auf Debian 13 mit Plasma 6 mit gesetzter Env-Var starten, Gate fahren.
3. **Flip:** separater, kleiner PR — Env-Var raus, Watcher-Probe rein, Default an. Darf
   erst mergen, wenn das Plasma-Gate dokumentiert grün ist.

## Verifikation / Übergabe

- **CI (jetzt):** pure Tests auf allen Matrix-Pythons plus der D-Bus-Integrationstest im
  Linux-Job. Belegt Registrierung, Properties, Layout und Event-Dispatch gegen einen
  echten Bus — nicht die Darstellung in Plasma.
- **Manuelles Plasma-Gate (REQUIRED, blockiert den Flip):** AppImage aus dem Pre-Release
  mit `ZEIT_LINUX_TRAY=1` auf Debian 13/Plasma 6 starten. Prüfen: Icon erscheint im
  Systemabschnitt; Linksklick holt das Fenster zurück; Rechtsklick zeigt das Menü mit
  Anzeigen / Senden / Teilen / Export / Sync / Beenden; der Sync-Eintrag erscheint und
  verschwindet mit `sync_enabled`; „Beenden" beendet sauber; Fenster schließen minimiert
  in den Systemabschnitt; ein Reservierungs-Reminder erscheint als Toast; nach einem
  `plasmashell --replace` ist das Icon wieder da.

**Übergabe (schwerer Loop):**

- **VERHALTEN:** Merge liefert ein vollständiges Linux-SNI-Backend, dormant hinter
  `ZEIT_LINUX_TRAY=1`. Ohne Env-Var ist Linux exakt wie heute; Windows und macOS sind
  unberührt. Neue Abhängigkeit nur auf Linux (`dbus-fast`), AppImage-Rezept bis auf ein
  `--collect-all` unverändert.
- **RISIKO:** Bricht am ehesten in der dbusmenu-Ausgestaltung (Plasma zeigt kein oder ein
  unvollständiges Menü) oder beim Icon-Pixmap (falsche Byte-Reihenfolge → Farbmüll). Beides
  trifft nur Opt-in-Nutzer. Zweitrisiko: `dbus_fast` fehlt im AppImage → `start()` wirft →
  sichtbare Fehlermeldung, kein stiller Ausfall. Für Windows/macOS: null, der Importpfad
  wird dort nie betreten.
- **TEST:** `pytest` (pure + D-Bus-Integration) plus das manuelle Plasma-Gate oben.

## Offene Annahmen (irreduzibles Risiko)

Die Interfaces sind primärbelegt (KDEs `org.kde.StatusNotifierItem.xml` /
`org.kde.StatusNotifierWatcher.xml`, Canonicals `dbus-menu.xml`). Nicht belegbar ohne
laufendes Plasma ist, wie tolerant Plasmas dbusmenu-Client bei den Details ist
(Revisions-Handling, Property-Defaults, `AboutToShow`-Zeitpunkt) und wie es unsere
Pixmaps skaliert. Deshalb der dormant-Default: schlägt eine dieser Annahmen fehl, sieht
das kein Endnutzer.

**Wayland-Grenze (bekannt, gehört in die Doku):** `Activate` holt das Fenster aus dem
`withdraw()`-Zustand zurück, das Anheben in den Vordergrund darf der Compositor aber
verweigern (Focus-Stealing-Prevention). Tk kann den XDG-Activation-Token nicht verwerten
— deshalb ist `ProvideXdgActivationToken` ein No-op.

## Bewusst nicht enthalten (YAGNI)

- Kein pystray-/appindicator-Pfad und damit kein GTK/GI im AppImage.
- Kein XEmbed-Fallback (`xembedsniproxy`) für Nicht-SNI-Desktops.
- Keine Änderung an Windows oder macOS, keine Änderung an `ui.py`.
- Kein `IconThemePath`/Icon-Installation ins System-Theme — Pixmaps reichen.
- Keine Menü-Extras, die es auf den anderen Plattformen nicht gibt (Toggles, Submenüs,
  Icons pro Eintrag).
- Kein Default-an-Flip in diesem PR.

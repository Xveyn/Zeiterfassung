# src/devices.py
"""Gerätenamen für die Sync-Anzeige — reine Logik, kein Tk, kein I/O.

Die `device_id` (s. `device_id.py`) ist stabil und eindeutig, aber als
Hex-Hash für Menschen nichtssagend: der Konfliktdialog konnte bisher nur
„von 6800a51a…" sagen. Der Name schließt diese Lücke.

Weil ein Konflikt praktisch immer ein **anderes** Gerät betrifft, muss der
Name mitreisen. Er hängt deshalb nicht an den einzelnen Einträgen, sondern
in einer Registry im Sync-Doc:

    {device_id: {"name": str, "updated_at": ISO-String}}

Jedes Gerät schreibt beim Push ausschließlich seinen eigenen Eintrag
(`with_own_entry`); fremde Einträge werden per LWW über `updated_at`
zusammengeführt (`merge_registries`). Die Registry ist damit additiv und
ohne Schema-Bump abwärtskompatibel: ältere Clients ignorieren das Feld,
verlieren es beim eigenen Push — und jedes neuere Gerät trägt sich beim
nächsten Push wieder ein.

**Alles hier behandelt seine Eingabe als Fremddaten.** Die Registry kommt
aus dem Remote-Doc, und der Name landet ungefiltert in einem Tk-Label:
`sanitize_device_name` deckelt die Länge und wirft Steuerzeichen raus,
`sanitize_registry` zusätzlich unbekannte Felder und die Menge. Fehlt oder
bricht etwas davon, fällt die Anzeige auf die gekürzte ID zurück — also auf
exakt das Verhalten von vor diesem Feature.
"""

from __future__ import annotations

import socket
from typing import Any, Callable

# Namenslänge im Konfliktdialog: er zeigt Name UND ID in einer Zeile, die
# ohnehin schon Zeitstempel und Slots trägt.
MAX_NAME_LENGTH = 40

# Obergrenze der Registry. Sie wächst sonst mit jeder je gesynct gewesenen
# Installation monoton weiter (eine Neuinstallation auf derselben Hardware
# behält ihre ID, ein Plattformwechsel nicht) — ohne Deckel wandert das
# unbegrenzt durch jedes Sync-Doc.
MAX_DEVICES = 50

# Hostnamen, die als Vorbelegung wertlos sind: sie beschreiben jedes Gerät
# und keines. Dann lieber leer lassen und die ID zeigen.
_USELESS_HOSTNAMES = frozenset({"localhost", "localdomain", "local"})


def sanitize_device_name(name: Any) -> str:
    """Anzeigefertiger Gerätename: Steuerzeichen raus, Whitespace normalisiert,
    auf `MAX_NAME_LENGTH` gedeckelt. Alles Nicht-Textliche wird zu ``""``."""
    if not isinstance(name, str):
        return ""
    # Steuerzeichen (inkl. \n, \t, \x00) zu Leerzeichen, dann Runs einsammeln:
    # str.split() ohne Argument erledigt beides in einem Durchgang.
    cleaned = "".join(ch if ch.isprintable() else " " for ch in name)
    return " ".join(cleaned.split())[:MAX_NAME_LENGTH]


def default_device_name(hostname: Callable[[], str] | None = None) -> str:
    """Vorbelegung für den eigenen Gerätenamen aus dem Hostnamen.

    Liefert ``""``, wenn der Hostname nicht ermittelbar oder nichtssagend ist
    (`localhost` & Co.) — der Aufrufer zeigt dann weiter die ID.

    `socket.gethostname` wird bewusst erst hier aufgelöst und nicht als
    Default-Argument gebunden: ein Default würde die Funktion beim Import
    festnageln, und ein `monkeypatch` auf `socket` liefe ins Leere."""
    resolve = hostname if hostname is not None else socket.gethostname
    try:
        raw = resolve()
    except Exception:
        # Hostname-Auflösung ist best-effort: ein fehlender Name darf den
        # Start nicht gefährden (gethostname wirft je nach Plattform OSError).
        return ""
    name = sanitize_device_name(raw)
    if name.split(".")[0].strip().lower() in _USELESS_HOSTNAMES:
        return ""
    return name


def short_device_id(device_id: Any) -> str:
    """Die gekürzte ID, wie sie der Konfliktdialog seit jeher zeigt."""
    if not isinstance(device_id, str) or not device_id:
        return "?"
    return f"{device_id[:8]}…" if len(device_id) > 8 else device_id


def device_label(device_id: Any, registry: Any) -> str:
    """„Laptop Arbeit · 6800a51a…" — oder nur die gekürzte ID, wenn zu dieser
    `device_id` kein (brauchbarer) Name bekannt ist."""
    short = short_device_id(device_id)
    # Die device_id kommt aus einem Konflikt-Kandidaten des Remote-Docs, dessen
    # Form vor der Anzeige niemand prüft: ein Nicht-String (Liste/Dict) wäre
    # nicht mal als dict-Key zulässig und risse `registry.get` mit TypeError um.
    if not isinstance(device_id, str) or not isinstance(registry, dict):
        return short
    entry = registry.get(device_id)
    if not isinstance(entry, dict):
        return short
    name = sanitize_device_name(entry.get("name"))
    return f"{name} · {short}" if name else short


def sanitize_registry(raw: Any, max_devices: int = MAX_DEVICES) -> dict[str, dict[str, str]]:
    """Macht aus beliebiger Eingabe eine wohlgeformte Registry.

    Verworfen wird alles, was nicht `{str: {"name": str, "updated_at": str}}`
    ist — inklusive unbekannter Felder, die sonst über den lokalen Spiegel
    wieder mit hochgeladen würden. Bei mehr als `max_devices` Einträgen
    gewinnen die zuletzt aktualisierten.

    Ein **leerer Name bleibt erhalten**: er ist der Grabstein eines gelöschten
    Namens (s. `with_own_entry`). Würde er hier wegfallen, käme das Leeren nie
    bei den anderen Geräten an — `merge_registries` ist eine Union, und eine
    Abwesenheit schlägt darin keine vorhandene ältere Kopie."""
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, dict[str, str]] = {}
    for device_id, entry in raw.items():
        if not isinstance(device_id, str) or not device_id:
            continue
        if not isinstance(entry, dict):
            continue
        updated_at = entry.get("updated_at")
        clean[device_id] = {
            "name": sanitize_device_name(entry.get("name")),
            "updated_at": updated_at if isinstance(updated_at, str) else "",
        }
    if len(clean) <= max_devices:
        return clean
    newest = sorted(clean.items(), key=lambda kv: (kv[1]["updated_at"], kv[0]), reverse=True)
    return dict(newest[:max_devices])


def merge_registries(local: Any, remote: Any,
                     max_devices: int = MAX_DEVICES) -> dict[str, dict[str, str]]:
    """Vereinigt zwei Registries per LWW über `updated_at`; bei Gleichstand
    gewinnt die lokale Seite. Beide Eingaben werden vorher saniert und bleiben
    unangetastet."""
    merged = sanitize_registry(local, max_devices=max_devices)
    for device_id, entry in sanitize_registry(remote, max_devices=max_devices).items():
        current = merged.get(device_id)
        if current is None or current["updated_at"] < entry["updated_at"]:
            merged[device_id] = entry
    if len(merged) <= max_devices:
        return merged
    return sanitize_registry(merged, max_devices=max_devices)


def with_own_entry(registry: Any, device_id: str, name: str, updated_at: str,
                   max_devices: int = MAX_DEVICES) -> dict[str, dict[str, str]]:
    """Setzt den eigenen Eintrag in einer Kopie der Registry.

    Der eigene Name gewinnt hier **immer** — anders als in `merge_registries`
    ohne Zeitstempel-Vergleich: über den Namen dieses Geräts entscheidet
    dieses Gerät.

    Ein **geleerter Name wird zum Grabstein** (`name: ""` mit frischem
    Stempel), nicht zu einer Abwesenheit. Der Unterschied ist nicht kosmetisch:
    `merge_registries` ist eine Union, in der ein fehlender Eintrag gegen die
    vorhandene Kopie eines anderen Geräts verliert — der gelöschte Name käme
    beim nächsten fremden Push global zurück. Ein Gerät ohne je gesetzten Namen
    bekommt keinen Grabstein; der wäre nur Rauschen und zählte gegen
    `max_devices`.

    `updated_at` greift nur, wenn sich der Name tatsächlich geändert hat —
    sonst trüge jeder Push einen frischen Stempel und das Sync-Doc wiche bei
    jedem Lauf ab, ohne dass sich etwas geändert hat."""
    merged = sanitize_registry(registry, max_devices=max_devices)
    if not device_id:
        return merged
    clean_name = sanitize_device_name(name)
    current = merged.get(device_id)
    if current is not None and current["name"] == clean_name:
        return merged
    if current is None and not clean_name:
        return merged
    merged[device_id] = {"name": clean_name, "updated_at": updated_at}
    # Der eigene Eintrag darf den Deckel nicht sprengen: das hochgeladene Doc
    # ist die Stelle, an der er gelten muss.
    return sanitize_registry(merged, max_devices=max_devices)

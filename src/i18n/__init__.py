# pyright: reportOptionalMemberAccess=true
"""Textschicht des Desktops: `t("schlüssel", name=…)` liefert den Text der gewählten Sprache.

Schlüssel stehen nur als Literal im Aufruf (die Ratsche liest sie am Quelltext). Tabellen
Code → Text markieren ihre Schlüssel mit `N_("…")` und lösen erst beim Aufruf mit
`t(TABELLE[code])` auf — zur Importzeit aufgelöst bliebe ein Text in der Startsprache.

Die Sprache setzt `main.py` einmal beim Start, direkt nach dem Laden der Einstellungen;
danach wird nur gelesen, `t()` ist damit aus Worker-Threads aufrufbar. Das Paket importiert
nichts aus dem übrigen `src` (`region` importiert es) und lädt die Kataloge statisch, damit
PyInstaller sie findet.
"""
import logging
import re

from src.i18n import de

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "de"

CATALOGS: dict[str, dict[str, str]] = {"de": de.TEXTS}

# Die unterstützten Sprachen; auch `region.normalize_language` liest sie hier.
LANGUAGES: tuple[str, ...] = tuple(CATALOGS)

# Katalog der Standardsprache, zugleich Rückfall für Lücken anderer Kataloge.
TEXTS: dict[str, str] = CATALOGS[DEFAULT_LANGUAGE]

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

_current = DEFAULT_LANGUAGE
# Schlüssel, deren Fehlen schon geloggt ist: eine Warnung je Schlüssel, nicht je Anzeige.
_warned: set[str] = set()


def normalize_language(value: object) -> str:
    """Ein unterstützter Sprachcode; `de-AT`, `de_CH` und Großschreibung fallen auf den
    Basiscode, alles andere auf Deutsch (Fremddaten, wirft nie)."""
    if not isinstance(value, str):
        return DEFAULT_LANGUAGE
    base = re.split(r"[-_]", value.strip().lower(), maxsplit=1)[0]
    return base if base in LANGUAGES else DEFAULT_LANGUAGE


def set_language(lang: object) -> None:
    """Setzt die Oberflächensprache (normalisiert). Nur beim Start aufrufen."""
    global _current
    _current = normalize_language(lang)


def get_language() -> str:
    return _current


def t(key: str, /, **params: object) -> str:
    """Text zu `key` in der aktuellen Sprache, `{name}`-Platzhalter durch `params` ersetzt.

    Ersetzt wird in einem Durchlauf: ein Wert, der selbst `{…}` enthält, bleibt wörtlich
    stehen; Platzhalter ohne Parameter bleiben stehen. Ein unbekannter Schlüssel liefert
    den Schlüssel selbst (sichtbar, statt zu werfen) und wird einmal geloggt."""
    text = CATALOGS.get(_current, TEXTS).get(key)
    if text is None:
        text = TEXTS.get(key)
    if text is None:
        if key not in _warned:
            _warned.add(key)
            log.warning("Text fehlt im Katalog: %s", key)
        return key
    if not params:
        return text

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(params[name]) if name in params else match.group(0)

    return _PLACEHOLDER.sub(_replace, text)


def N_(key: str) -> str:  # noqa: N802  (Name nach gettext-Konvention; die Ratsche sucht ihn)
    """Markiert einen Schlüssel in einer Tabelle; aufgelöst wird beim Aufruf mit `t()`."""
    return key

# pyright: reportOptionalMemberAccess=true
"""Deutscher Katalog, je Bereich ein Modul (konfliktfrei bei parallelen Änderungen).

Ein Schlüssel steht in genau einem Bereich; ein Test verbietet Doppelte über Module hinweg.
"""
from types import ModuleType

from src.i18n.de import allgemein, dialoge, einstellungen, hauptfenster, meldungen

AREAS: tuple[ModuleType, ...] = (allgemein, meldungen, einstellungen, dialoge, hauptfenster)

TEXTS: dict[str, str] = {key: text for area in AREAS for key, text in area.TEXTS.items()}

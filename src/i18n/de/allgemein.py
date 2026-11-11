# pyright: reportOptionalMemberAccess=true
"""Bereich „allgemein“: wiederkehrende Texte (Knöpfe, Einheiten, Wochentage) und die
Schlüssel der Textschicht selbst (`i18n.*`, nur für deren Tests)."""

TEXTS: dict[str, str] = {
    "i18n.beispiel": "Hallo {name}, es sind {count} Einträge.",
    "i18n.ohne_parameter": "Nur Text",
    "i18n.schluessel": "Taste {key}",
}

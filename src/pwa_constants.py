"""Adresse der gehosteten Handy-PWA, an genau einer Stelle.

Eigenes Modul, stdlib-frei und ohne Importe aus ``src``: so koennen die
Routenebene (``mobile_routes``) und der Relay-Codec (``mobile_relay_codec``)
dieselben Werte nutzen, ohne dass der Codec die Routenebene mitlaedt.
Zieht das Repo um, muessen beide Konstanten (und die Doku) mit.
"""
from __future__ import annotations

PWA_ORIGIN: str = "https://xveyn.github.io"
PWA_URL: str = "https://xveyn.github.io/Zeiterfassung/"

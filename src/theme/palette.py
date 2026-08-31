# src/theme/palette.py
"""Farbpalette und die reinen Wert-Listen des Dark-Themes.

Keine Tk-Objekte, keine Funktionen — nur Konstanten. Unterste Schicht des
Pakets: hängt an nichts.
"""

# Dark Modern color palette
BG = "#1a1a2e"
CELL_BG = "#16213e"
WEEKEND_BG = "#0f3460"
ACCENT = "#e94560"
ACCENT_HOVER = "#c73550"
# Gedämpfter, entsättigter Akzent für deaktivierte Primary-Buttons — klar als
# "nicht klickbar" erkennbar, behält aber den Rot-Charakter des Löschen-Buttons.
ACCENT_DISABLED = "#5c2a37"
STATUS_OK = "#4ade80"
TEXT = "#e0e0e0"
TEXT_MUTED = "#888888"
ENTRY_BG = "#1a3a5c"
WEEKEND_ENTRY_BG = "#1a3050"
WEEKEND_FG = "#6c6c80"

# Hover colors (slightly lighter variants)
CELL_BG_HOVER = "#1e2d52"
WEEKEND_BG_HOVER = "#153a6e"
ENTRY_BG_HOVER = "#224a70"
WEEKEND_ENTRY_BG_HOVER = "#223e60"

# Holiday cell colors (green analog to red ACCENT for entries)
HOLIDAY_BG = "#0f3a2a"
HOLIDAY_BG_HOVER = "#15523a"
HOLIDAY_ACCENT = "#4ade80"  # gleicher Grünton wie STATUS_OK

# Reservation cell accent ("geplant"-Look — violetter Akzent, abgesetzt von
# der roten Ist-Zeit-Zelle und der grünen Feiertagszelle)
RESERVATION_ACCENT = "#a78bfa"

# Urlaubszelle — türkis, klar abgesetzt von rotem Eintrag, grünem Feiertag,
# violetter Reservierung, blauem Heute-Rahmen und orangem Konflikt-Rand.
VACATION_BG = "#134e4a"
VACATION_BG_HOVER = "#176b64"
VACATION_ACCENT = "#2dd4bf"

# Rahmenfarbe für den heutigen Tag — blau, klar abgesetzt von rotem Eintrag,
# grünem Feiertag, violetter Reservierung und orangem Konflikt-Rand.
TODAY_ACCENT = "#38bdf8"

# Time dropdown values (5-min steps, 00:00 - 23:55)
TIME_VALUES = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 5)]
PAUSE_VALUES = [str(m) for m in range(0, 125, 5)]

"""Dialog „Datenschutzhinweise“ (Einstellungen → App): zeigt `docs/datenschutz.md` im Stil der App.

Die Datei wird mit dem Build mitgeliefert und von `privacy_doc` (Tk-frei, getestet) in Blöcke zerlegt; hier
steht nur der Aufbau: ein schreibgeschütztes Text-Widget mit Tags, Links im Akzent, Auswahl und Kopieren
bleiben möglich. Fehlt die Datei, zeigt derselbe Dialog einen Ersatztext mit Link auf das Dokument im
Projekt, nie ein leeres Fenster.
"""
import logging
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import ttk

from src.paths import get_resource_path
from src.privacy_doc import fallback_blocks, is_web_url, load_privacy_doc, parse_privacy_markdown
from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, FONT_BOLD, FONT_HEADER_SMALL, TEXT_MUTED, apply_combobox_style,
    center_dialog_on_parent, create_dialog, dark_text, px, secondary_button, workarea_for,
)

log = logging.getLogger(__name__)

_WIDTH_CHARS = 78
_HEIGHT_LINES = 26
_MIN_LINES = 8
_BULLETS = ("•", "–", "·")


def _blocks():
    text = load_privacy_doc(get_resource_path())
    blocks = parse_privacy_markdown(text) if text is not None else []
    return blocks or fallback_blocks()


def visible_lines(available_px, line_px, *, preferred=_HEIGHT_LINES, minimum=_MIN_LINES):
    """Wie viele Zeilen der Text zeigt: die bevorzugte Zahl, bei knappem Platz so viele, wie hineinpassen, nie
    weniger als `minimum`. Die Zeilenhöhe wächst mit der UI-Skalierung, die Arbeitsfläche nicht."""
    if line_px <= 0:
        return preferred
    return max(minimum, min(preferred, int(available_px // line_px)))


def open_url(url):
    """Öffnet nur Web-Adressen; ein Fehler beim Start des Browsers beendet den Dialog nicht."""
    if not is_web_url(url):
        return
    try:
        webbrowser.open(url)
    except Exception:
        # Der Dialog ist nur Anzeige; ein fehlender Standardbrowser soll ihn nicht beenden.
        log.warning("Browser für die Datenschutzhinweise nicht gestartet", exc_info=True)


def _configure_tags(text):
    # Blockarten zuerst, Auszeichnungen danach: spätere Tags gewinnen bei gleicher Option (ein Link im Zitat
    # behält die Linkfarbe).
    text.tag_configure("title", font=FONT_HEADER_SMALL, spacing3=px(8))
    text.tag_configure("heading", font=FONT_BOLD, spacing1=px(14), spacing3=px(4))
    text.tag_configure("paragraph", spacing3=px(8))
    text.tag_configure("quote", foreground=TEXT_MUTED, lmargin1=px(12), lmargin2=px(12), spacing3=px(8))
    for level in range(len(_BULLETS)):
        text.tag_configure(f"bullet{level}", lmargin1=px(8 + 16 * level), lmargin2=px(22 + 16 * level),
                           spacing3=px(4))
    text.tag_configure("bold", font=FONT_BOLD)
    text.tag_configure("code", foreground=TEXT_MUTED, background=ENTRY_BG)
    text.tag_configure("link", foreground=ACCENT, underline=True)


def render_blocks(text, blocks):
    """Schreibt die Blöcke in ein (noch beschreibbares) Text-Widget; jeder Link bekommt ein eigenes Tag
    für Klick und Zeiger."""
    _configure_tags(text)
    link_count = 0
    for block in blocks:
        kind = block["kind"]
        block_tag = f"bullet{min(block['level'], len(_BULLETS) - 1)}" if kind == "bullet" else kind
        if kind == "bullet":
            text.insert("end", f"{_BULLETS[min(block['level'], len(_BULLETS) - 1)]} ", (block_tag,))
        for segment in block["segments"]:
            tags = [block_tag]
            if segment["style"] != "plain":
                tags.append(segment["style"])
            if segment["style"] == "link" and segment["url"]:
                link_count += 1
                name = f"url{link_count}"
                tags.append(name)
                url = segment["url"]
                text.tag_bind(name, "<Button-1>", lambda _event, target=url: open_url(target))
                text.tag_bind(name, "<Enter>", lambda _event: text.config(cursor="hand2"))
                text.tag_bind(name, "<Leave>", lambda _event: text.config(cursor=""))
            text.insert("end", segment["text"], tuple(tags))
        text.insert("end", "\n", (block_tag,))


def open_privacy_dialog(parent):
    """Öffnet den Dialog (modal)."""
    dialog = create_dialog(parent, "Datenschutzhinweise")
    apply_combobox_style(dialog)         # stylt `Vertical.TScrollbar` dunkel

    body = tk.Frame(dialog, bg=BG)
    body.pack(fill="both", expand=True, padx=12, pady=(12, 4))
    _left, top, _right, bottom = workarea_for(parent)
    line_px = tkfont.nametofont(FONT).metrics("linespace")
    lines = visible_lines((bottom - top) - px(190), line_px)     # Titelleiste, Rand, Knopf, Abstände
    text = dark_text(body, _WIDTH_CHARS, lines, padx=px(12), pady=px(10))
    scrollbar = ttk.Scrollbar(body, orient="vertical", command=text.yview, style="Vertical.TScrollbar")
    text.configure(yscrollcommand=scrollbar.set)
    text.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    render_blocks(text, _blocks())
    # Schreibgeschützt; Auswahl und Kopieren bleiben möglich. Kein Fokusrahmen (`dark_text` zeichnet ihn in der
    # Akzentfarbe, für Eingabefelder gedacht) und kein Tab-Stopp: das Fenster ist nur zum Lesen.
    text.configure(state="disabled", highlightthickness=0, takefocus=0)

    buttons = tk.Frame(dialog, bg=BG)
    buttons.pack(pady=(4, 12))
    secondary_button(buttons, "Schließen", dialog.destroy).pack()
    center_dialog_on_parent(dialog, parent)

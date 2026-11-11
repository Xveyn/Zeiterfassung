"""Oberflächentexte des Desktops: Inventur und Äquivalenzprüfung.

    python scripts/desktop_text_check.py --list
        Je Datei unter src/ die Literale, die als Nutzertext gelten, mit Grund.

    python scripts/desktop_text_check.py --base <ref|ordner> --files src/a.py …
        Äquivalenz einer Umstellung: die Texte, die in den Dateien gegenüber dem
        Stand <ref> weggefallen sind, gegen die Katalogwerte der neu hinzugekommenen
        t("…")/N_("…")-Schlüssel, je Datei als Multimenge. <ref> ist ein git-Ref
        (gelesen über `git show <ref>:<pfad>`) oder ein Ordner mit einem älteren
        Arbeitsstand. Exit 1 bei Abweichungen; sie gehören in den Commit, mit Grund.

Die Regel teilt sich das Skript mit der Ratsche `tests/test_desktop_texts.py`, die es
über seinen Pfad lädt: ein Parser für beide.
"""

import argparse
import ast
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass

# Liegt in scripts/, liest aber src/ und den Katalog aus `src.i18n`.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# --- Die Regel: was ist ein Nutzertext? -------------------------------------------------

# Eigennamen der Plattform und des Produkts: kommen in Vergleichen, Pfaden und
# Fenstertiteln vor und werden nicht übersetzt.
TECHNICAL_WORDS = frozenset({"Windows", "Linux", "Darwin", "Zeiterfassung"})

_UMLAUT = re.compile(r"[äöüÄÖÜß]")
# Ein Token ohne Leerraum mit Zeichen, die in Text nicht vorkommen: Pfade, Dateien,
# Punktnamen, Formate, Tk-Ereignisse, Optionen (`settings.json`, `<Button-3>`, `%H:%M`).
_TECH_TOKEN = re.compile(r"^[^\s]*[._/\\%<>@#=|$~^*\[\]{}][^\s]*$")
# CamelCase oder ein Großbuchstabe mitten im Wort (`TkDefaultFont`, `macOS`, `iPhone`).
_CAMEL = re.compile(r"^[^\s]*[a-zäöüß][A-ZÄÖÜ][^\s]*$")
# printf-/strftime-/logging-Codes (`%s`, `%H`, `%(asctime)s`); sie zählen nicht als Wörter.
_FORMAT_CODE = re.compile(r"%(?:\(\w+\))?[-+ #0]*\d*(?:\.\d+)?[a-zA-Z]")
# Ein Klassen- oder Fehlername mit führender Abkürzung (`URLError`, `TCombobox`).
_ACRONYM_CLASS = re.compile(r"^[A-Z]{2,}[a-z]{2,}\w*$")
# Abkürzungen aus Buchstaben und Punkten (`z.B.`, `u.a.`): Text, kein Punktname.
_ABBREVIATION = re.compile(r"^(?:[^\W\d_]{1,3}\.)+$")
# Satzzeichen am Ende (`Speichern...`, `Fertig.`, `Bis:`) machen ein Wort nicht technisch.
_TRAILING_PUNCT = re.compile(r"[.!?:…]+$")
# Ein in Klammern gesetztes Wort (`[Hinweis]`, `(Standard)`): Text, kein Index `[0]`.
_BRACKETED_WORD = re.compile(r"^[(\[][^\W\d_]{2,}[)\]]$")
_LEADING_SYMBOLS = re.compile(r"^[^\w\s]+")
_WORD = re.compile(r"[^\W\d_]+")


def _technical_token(token: str) -> bool:
    """Ein einzelnes Token ohne Leerraum, das Technik ist (Pfad, Format, Punktname,
    CamelCase, Bezeichner)."""
    if _ABBREVIATION.match(token) or _BRACKETED_WORD.match(token):
        return False
    core = _TRAILING_PUNCT.sub("", token) or token
    return bool(_TECH_TOKEN.match(core) or _CAMEL.match(core)
                or _ACRONYM_CLASS.match(core) or "_" in core)


def _has_lowercase_word(s: str) -> bool:
    words = _WORD.findall(_FORMAT_CODE.sub(" ", s))
    return any(any(ch.islower() for ch in w) for w in words)


def text_reason(template: str, ui_slot: bool = False) -> str | None:
    """Warum `template` als Nutzertext gilt, sonst None. `template` ist ein String-Literal,
    f-Strings mit `{}` je Ausdruck.

    Leerraum und Wörter werden mit `x` für jedes `{}` geprüft (`"{} h"` ist Text), die
    Technik-Regeln am Template ohne `{}` (`.{}-*.tmp`, `werkstudent_limit_{}.year` bleiben
    Technik). `ui_slot`: das Literal steht an einer Stelle, die die Oberfläche zeigt
    (`text=`, `title=`, Meldungs-Argument) — dort zählt auch ein einzelnes kleines Wort."""
    bare = template.replace("{}", "").strip()
    probe = template.replace("{}", "x").strip()
    if not bare or bare in TECHNICAL_WORDS or not _has_lowercase_word(bare):
        return None
    if not re.search(r"\s", bare) and _technical_token(bare):
        return None
    if re.search(r"\s", probe):
        return "Leerzeichen"
    # Ein führendes Nicht-Buchstaben-Zeichen (`(Standard)`, `+ Slot`, `▶ Start`) ändert nichts.
    lead = _LEADING_SYMBOLS.sub("", bare)
    if lead[:1].isupper():
        return "Großbuchstabe"
    if _UMLAUT.search(bare):
        return "Umlaut"
    if _ABBREVIATION.match(bare):
        return "Abkürzung"
    if ui_slot and _has_lowercase_word(bare):
        return "Anzeigeargument"
    return None


# --- Kontexte, in denen ein Literal nie Oberfläche ist ---------------------------------

LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})
# Empfänger, die Logger sind; `banner.info("…")` ist keiner.
LOGGERS = frozenset({"log", "_log", "logger", "_logger", "logging", "LOG",
                     "self.log", "self._log", "self.logger"})
# Funktionen, die nur ins Log schreiben (ihre Argumente sind Log-Text).
LOG_HELPERS = frozenset({"_log_skipped", "_log_ok", "_log_failure"})
# Alle Argumente technisch.
TECH_CALLS = frozenset({"os.environ.get", "os.getenv", "os.path.join", "namedtuple",
                        "collections.namedtuple"})
# Nur das Attribut-Argument technisch (ein Default von `getattr` kann Text sein).
ATTRIBUTE_CALLS = frozenset({"getattr", "hasattr", "setattr"})
TECH_METHODS = frozenset({"startswith", "endswith", "add_header", "send_header", "putheader"})
# Nur Schlüsselwörter, die einen Wert tragen, den die Token-Regeln nicht erkennen
# (gemessen: ohne sie entstehen Fundstellen).
TECH_KEYWORDS = frozenset({
    "fields", "q",          # Feldmaske/Abfrage der Google-APIs (`files(id, name, …)`)
    "member",               # D-Bus-Signal (`Notify`)
})
# Aufrufe, deren Ergebnis ein technischer Code ist; ein Vergleich damit nennt Codes.
CODE_CALLS = frozenset({"platform.system", "system", "unicodedata.category"})
# Namen von HTTP-Kopfzeilen: als Dict-Schlüssel oder Index technisch. Andere Schlüssel
# bleiben geprüft — eine Tabelle {"Allgemein": "general"} ist eine Beschriftung.
HTTP_HEADERS = frozenset({"Authorization", "Origin", "Vary", "Allow", "Host", "Accept",
                          "Location", "Content-Type", "Content-Length", "Content-Disposition",
                          "WWW-Authenticate", "Sec-Fetch-Site", "Transfer-Encoding",
                          "X-Hub-Signature-256", "User-Agent",
                          "Access-Control-Allow-Origin", "Access-Control-Allow-Methods",
                          "Access-Control-Allow-Headers", "Access-Control-Max-Age",
                          "Access-Control-Allow-Private-Network"})
KEY_FUNCTIONS = frozenset({"t", "N_"})

# Stellen, die die Oberfläche zeigt: Schlüsselwörter und Position des Textarguments
# der Widget-, Dialog- und Meldungsfabriken.
UI_KEYWORDS = frozenset({"text", "title", "message", "label"})
UI_POSITIONAL: dict[str, tuple[int, ...]] = {
    "primary_button": (1,), "secondary_button": (1,), "toggle_button": (1,),
    "icon_button": (1,), "label_button": (1,), "set_button_text": (1,),
    "empty_state": (1,), "create_dialog": (1,),
    "themed_showinfo": (1, 2), "themed_showwarning": (1, 2), "themed_showerror": (1, 2),
    "themed_askyesno": (1, 2), "themed_ask_delete_choice": (1, 2),
    "showinfo": (0, 1), "showwarning": (0, 1), "showerror": (0, 1), "askyesno": (0, 1),
}


@dataclass(frozen=True)
class Literal:
    text: str          # Template: f-String-Ausdrücke als `{}`
    line: int
    context: str | None  # Grund der Kontext-Ausnahme, sonst None
    key: bool          # Argument von t(/N_( → Schlüsselliteral
    ui_slot: bool = False  # steht an einer Anzeigestelle (UI_KEYWORDS/UI_POSITIONAL)


@dataclass(frozen=True)
class Finding:
    text: str
    line: int
    reason: str


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else node.attr
    return ""


def _callee_name(call: ast.Call) -> str:
    """Letzter Name der aufgerufenen Funktion (`log.warning` → `warning`)."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def is_key_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in KEY_FUNCTIONS
    return (isinstance(func, ast.Attribute) and func.attr in KEY_FUNCTIONS
            and _dotted(func.value) in {"i18n", "src.i18n"})


def _is_logger(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        return _callee_name(node) == "getLogger"
    return _dotted(node) in LOGGERS


def _call_context(call: ast.Call) -> str | None:
    """Grund, aus dem **alle** Argumente des Aufrufs technisch sind, sonst None."""
    name = _callee_name(call)
    dotted = _dotted(call.func)
    if isinstance(call.func, ast.Attribute) and name in LOG_METHODS and _is_logger(call.func.value):
        return "Log"
    if isinstance(call.func, ast.Name) and name in LOG_HELPERS:
        return "Log"
    if dotted in TECH_CALLS or dotted.startswith("re."):
        return "Technik-Aufruf"
    if isinstance(call.func, ast.Attribute) and name in TECH_METHODS:
        return "Technik-Aufruf"
    return None


def _is_code_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _dotted(node.func) in CODE_CALLS


def _template(node: ast.JoinedStr) -> str:
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append("{}")
    return "".join(parts)


def _literal_nodes(node: ast.AST) -> list[ast.AST]:
    """Das Literal selbst oder die Literale einer Tupel-/Listen-/Mengen-Angabe bzw. eines
    bedingten Ausdrucks — nicht tiefer (ein Aufruf darin bleibt geprüft)."""
    if isinstance(node, (ast.Constant, ast.JoinedStr)):
        return [node]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [lit for elt in node.elts for lit in _literal_nodes(elt)]
    if isinstance(node, ast.IfExp):
        return [*_literal_nodes(node.body), *_literal_nodes(node.orelse)]
    return []


class _Scanner:
    def __init__(self, tree: ast.AST) -> None:
        self.parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                self.parents[child] = node
        self.skip: set[int] = set()        # Konstanten in f-Strings und Format-Specs
        self.exempt: dict[int, str] = {}   # Teilbäume mit Kontext-Ausnahme
        self.ui: set[int] = set()          # Literale an Anzeigestellen
        for node in ast.walk(tree):
            self._mark(node)

    def _exempt_tree(self, node: ast.AST, reason: str) -> None:
        for sub in ast.walk(node):
            self.exempt.setdefault(id(sub), reason)

    def _exempt_direct(self, node: ast.AST, reason: str) -> None:
        for lit in _literal_nodes(node):
            self._exempt_tree(lit, reason)

    def _exempt_header(self, node: ast.AST | None, reason: str) -> None:
        for lit in _literal_nodes(node) if node is not None else []:
            if isinstance(lit, ast.Constant) and lit.value in HTTP_HEADERS:
                self._exempt_tree(lit, reason)

    def _mark_call(self, node: ast.Call) -> None:
        reason = _call_context(node)
        if reason:
            for arg in [*node.args, *(k.value for k in node.keywords)]:
                self._exempt_tree(arg, reason)
        name = _callee_name(node)
        if isinstance(node.func, ast.Name) and name in ATTRIBUTE_CALLS and len(node.args) > 1:
            self._exempt_direct(node.args[1], "Attributname")
        for kw in node.keywords:
            if kw.arg in TECH_KEYWORDS:
                self._exempt_direct(kw.value, f"Schlüsselwort {kw.arg}=")
            if kw.arg in UI_KEYWORDS:
                self.ui.update(id(lit) for lit in _literal_nodes(kw.value))
        for index in UI_POSITIONAL.get(name, ()):
            if index < len(node.args):
                self.ui.update(id(lit) for lit in _literal_nodes(node.args[index]))

    def _mark(self, node: ast.AST) -> None:
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.Constant):
                    self.skip.add(id(value))
                elif isinstance(value, ast.FormattedValue) and value.format_spec is not None:
                    for sub in ast.walk(value.format_spec):
                        self.skip.add(id(sub))
        elif isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
            self._exempt_tree(node.value, "Docstring")
        elif isinstance(node, ast.Call):
            self._mark_call(node)
        elif isinstance(node, ast.Subscript):
            self._exempt_header(node.slice, "HTTP-Kopfzeile")
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                self._exempt_header(key, "HTTP-Kopfzeile")
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                if node.value is not None:
                    self._exempt_tree(node.value, "__all__")
            if isinstance(node, ast.AnnAssign):
                self._exempt_tree(node.annotation, "Annotation")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                self._exempt_tree(node.returns, "Annotation")
            args = node.args
            for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                if a is not None and a.annotation is not None:
                    self._exempt_tree(a.annotation, "Annotation")
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(_is_code_call(o) for o in operands):
                for o in operands:
                    self._exempt_direct(o, "Codevergleich")

    def _is_key(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Constant):
            return False      # ein f-String als Schlüssel ist gebaut (`dynamic_keys`)
        parent = self.parents.get(node)
        return (isinstance(parent, ast.Call) and is_key_call(parent)
                and bool(parent.args) and parent.args[0] is node)

    def literals(self, tree: ast.AST) -> list[Literal]:
        out: list[Literal] = []
        for node in ast.walk(tree):
            if id(node) in self.skip:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
            elif isinstance(node, ast.JoinedStr):
                text = _template(node)
            else:
                continue
            out.append(Literal(text, getattr(node, "lineno", 0), self.exempt.get(id(node)),
                               self._is_key(node), id(node) in self.ui))
        out.sort(key=lambda lit: lit.line)
        return out


def scan(source: str) -> list[Literal]:
    """Alle String-Literale einer Quelle mit Kontext-Ausnahme und Schlüssel-Markierung."""
    tree = ast.parse(source)
    return _Scanner(tree).literals(tree)


def findings(source: str) -> list[Finding]:
    """Die Literale, die als Nutzertext gelten (ohne Kontext-Ausnahmen und Schlüssel)."""
    out: list[Finding] = []
    for lit in scan(source):
        if lit.context or lit.key:
            continue
        reason = text_reason(lit.text, ui_slot=lit.ui_slot)
        if reason:
            out.append(Finding(lit.text, lit.line, reason))
    return out


def key_literals(source: str) -> list[str]:
    """Die Schlüssel aller t("…")/N_("…")-Aufrufe der Quelle, in Reihenfolge."""
    return [lit.text for lit in scan(source) if lit.key]


_TABLE_NAME = re.compile(r"^_?[A-Z][A-Z0-9_]*$")


def _is_table(node: ast.AST) -> bool:
    """Eine Tabelle Code → Schlüssel: ein Name in Großbuchstaben (`LABELS`, `_KIND_TEXTS`),
    auch als Attribut (`tab_rules.LABELS`)."""
    if isinstance(node, ast.Name):
        return bool(_TABLE_NAME.match(node.id))
    return isinstance(node, ast.Attribute) and bool(_TABLE_NAME.match(node.attr))


def _is_table_lookup(arg: ast.AST) -> bool:
    if isinstance(arg, ast.Subscript):
        return _is_table(arg.value) and not isinstance(arg.slice, (ast.JoinedStr, ast.BinOp))
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
        return (arg.func.attr == "get" and _is_table(arg.func.value) and len(arg.args) >= 1
                and not isinstance(arg.args[0], (ast.JoinedStr, ast.BinOp)))
    return False


def dynamic_keys(source: str) -> list[int]:
    """Zeilen von t(/N_(-Aufrufen, deren Schlüssel gebaut statt genannt wird.

    Erlaubt sind ein Literal und für `t(` ein Zugriff auf eine Tabelle in Großbuchstaben
    (`t(TABELLE[code])`, `t(TABELLE.get(code, N_("…")))`); f-Strings, Verkettung, Namen und
    beliebige `.get()` sind es nicht — sie könnten einen gebauten Schlüssel tragen."""
    out: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and is_key_call(node)):
            continue
        if not node.args:
            out.append(node.lineno)
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            continue
        if _callee_name(node) == "t" and _is_table_lookup(arg):
            continue
        out.append(node.lineno)
    return out


# Die Textschicht selbst: ihre Werte sind die Texte, nicht Fundstellen.
CATALOG_PREFIX = "src/i18n/"


def source_files(root: str = _ROOT) -> list[str]:
    """Relative Pfade (`src/…`, mit `/`) aller Python-Dateien unter src/ außer der
    Textschicht, sortiert."""
    out: list[str] = []
    for folder, _dirs, files in os.walk(os.path.join(root, "src")):
        for name in files:
            if name.endswith(".py"):
                rel = os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")
                if not rel.startswith(CATALOG_PREFIX):
                    out.append(rel)
    return sorted(out)


def read_source(rel: str, root: str = _ROOT) -> str:
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return fh.read()


# --- Inventur -------------------------------------------------------------------------

def inventory(root: str = _ROOT) -> dict[str, list[Finding]]:
    out: dict[str, list[Finding]] = {}
    for rel in source_files(root):
        hits = findings(read_source(rel, root))
        if hits:
            out[rel] = hits
    return out


def _print_inventory(show_texts: bool) -> None:
    inv = inventory()
    total: Counter[str] = Counter()
    for rel, hits in inv.items():
        reasons = Counter(h.reason for h in hits)
        total.update(reasons)
        detail = ", ".join(f"{r} {n}" for r, n in sorted(reasons.items()))
        print(f"{rel}: {len(hits)} ({detail})")
        if show_texts:
            for h in hits:
                print(f"  {h.line}: [{h.reason}] {h.text!r}")
    print(f"insgesamt: {sum(total.values())} in {len(inv)} Dateien "
          f"({', '.join(f'{r} {n}' for r, n in sorted(total.items()))})")


# --- Äquivalenzprüfung ----------------------------------------------------------------

_CATALOG_PLACEHOLDER = re.compile(r"\{\w+\}")


def normalize_catalog_text(text: str) -> str:
    """Katalogtext in der Form der Literale: `{name}` → `{}`."""
    return _CATALOG_PLACEHOLDER.sub("{}", text)


class UnknownBase(Exception):
    """`--base` ist weder ein Ordner noch ein auflösbarer git-Ref."""


def resolve_base(base: str) -> None:
    """Wirft `UnknownBase`, wenn `base` weder Ordner noch git-Ref ist — ein Tippfehler
    im Ref ergäbe sonst lauter leere Altstände und eine scheinbar saubere Prüfung."""
    if os.path.isdir(base):
        return
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"],
                            cwd=_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise UnknownBase(base)


def read_base(base: str, rel: str) -> str:
    """Quelltext von `rel` im Stand `base` (Ordner oder git-Ref); "" wenn es die Datei
    dort nicht gab. Den Ref prüft vorher `resolve_base`."""
    if os.path.isdir(base):
        path = os.path.join(base, rel)
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    result = subprocess.run(["git", "show", f"{base}:{rel}"], cwd=_ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    return result.stdout if result.returncode == 0 else ""


@dataclass(frozen=True)
class Equivalence:
    removed_without_key: list[str]   # weggefallene Texte ohne passenden Katalogwert
    keys_without_text: list[str]     # neue Schlüssel, deren Wert kein weggefallener Text ist
    unknown_keys: list[str]          # neue Schlüssel ohne Katalogeintrag

    @property
    def ok(self) -> bool:
        return not (self.removed_without_key or self.keys_without_text or self.unknown_keys)


def compare(old_source: str, new_source: str, catalog: dict[str, str]) -> Equivalence:
    """Multimengen-Vergleich: weggefallene Texte gegen die Werte neu hinzugekommener
    Schlüsselaufrufe."""
    old_texts = Counter(f.text for f in findings(old_source)) if old_source else Counter()
    new_texts = Counter(f.text for f in findings(new_source))
    removed = old_texts - new_texts
    old_keys = Counter(key_literals(old_source)) if old_source else Counter()
    added_keys = Counter(key_literals(new_source)) - old_keys
    unknown = sorted(k for k in added_keys if k not in catalog)
    values: Counter[str] = Counter()
    by_value: dict[str, list[str]] = {}
    for key, count in added_keys.items():
        if key in catalog:
            value = normalize_catalog_text(catalog[key])
            values[value] += count
            by_value.setdefault(value, []).append(key)
    missing = removed - values
    extra = values - removed
    return Equivalence(
        removed_without_key=sorted(missing.elements()),
        keys_without_text=sorted(f"{', '.join(by_value[v])} = {v!r}" for v in extra.elements()),
        unknown_keys=unknown,
    )


def _run_equivalence(base: str, files: list[str]) -> int:
    from src.i18n import TEXTS  # nach dem Bootstrap; nur dieser Modus braucht den Katalog

    try:
        resolve_base(base)
    except UnknownBase:
        print(f"--base {base!r}: weder Ordner noch git-Ref", file=sys.stderr)
        return 2
    status = 0
    for rel in files:
        rel = rel.replace(os.sep, "/")
        result = compare(read_base(base, rel), read_source(rel), TEXTS)
        if result.ok:
            print(f"{rel}: gleich")
            continue
        status = 1
        print(f"{rel}: Abweichungen")
        for text in result.removed_without_key:
            print(f"  weggefallen, kein Katalogwert: {text!r}")
        for entry in result.keys_without_text:
            print(f"  neuer Schlüssel ohne alten Text: {entry}")
        for key in result.unknown_keys:
            print(f"  Schlüssel fehlt im Katalog: {key}")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="Inventur je Datei mit allen Texten")
    parser.add_argument("--summary", action="store_true", help="Inventur nur mit Zahlen")
    parser.add_argument("--base", help="git-Ref oder Ordner des Vergleichsstands")
    parser.add_argument("--files", nargs="+", default=[], help="Dateien für --base")
    args = parser.parse_args(argv)
    if args.base:
        if not args.files:
            parser.error("--base braucht --files")
        return _run_equivalence(args.base, args.files)
    _print_inventory(show_texts=args.list or not args.summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

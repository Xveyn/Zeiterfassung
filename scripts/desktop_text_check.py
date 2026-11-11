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
_WORD = re.compile(r"[^\W\d_]+")


def text_reason(template: str) -> str | None:
    """Warum `template` als Nutzertext gilt („Leerzeichen“, „Großbuchstabe“, „Umlaut“),
    sonst None. `template` ist ein String-Literal, f-Strings mit `{}` je Ausdruck."""
    s = template.replace("{}", "").strip()
    if not s or s in TECHNICAL_WORDS:
        return None
    words = _WORD.findall(_FORMAT_CODE.sub(" ", s))
    if not any(any(ch.islower() for ch in w) for w in words):
        return None
    if not re.search(r"\s", s):
        if _TECH_TOKEN.match(s) or _CAMEL.match(s) or _ACRONYM_CLASS.match(s) or "_" in s:
            return None
    if re.search(r"\s", s):
        return "Leerzeichen"
    if s[0].isupper():
        return "Großbuchstabe"
    if _UMLAUT.search(s):
        return "Umlaut"
    return None


# --- Kontexte, in denen ein Literal nie Oberfläche ist ---------------------------------

LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})
# Funktionen, die nur ins Log schreiben (ihre Argumente sind Log-Text).
LOG_HELPERS = frozenset({"_log_skipped", "_log_summary", "_log_ok", "_log_notify_failure",
                         "log_message"})
TECH_CALLS = frozenset({"os.environ.get", "os.getenv", "os.path.join", "namedtuple",
                        "collections.namedtuple", "getattr", "hasattr", "setattr"})
TECH_METHODS = frozenset({"startswith", "endswith", "add_header", "send_header", "putheader"})
TECH_KEYWORDS = frozenset({"style", "font", "name", "sticky", "compound", "anchor", "orient",
                           "state", "relief", "cursor", "show",
                           # Feldmaske/Abfrage der Google-APIs, D-Bus-Signale
                           "fields", "q", "member", "signature"})
# Aufrufe, deren Ergebnis ein technischer Code ist; ein Vergleich damit nennt Codes.
CODE_CALLS = frozenset({"platform.system", "system", "unicodedata.category"})
KEY_FUNCTIONS = frozenset({"t", "N_"})


@dataclass(frozen=True)
class Literal:
    text: str          # Template: f-String-Ausdrücke als `{}`
    line: int
    context: str | None  # Grund der Kontext-Ausnahme, sonst None
    key: bool          # Argument von t(/N_( → Schlüsselliteral


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


def _call_context(call: ast.Call) -> str | None:
    name = _callee_name(call)
    dotted = _dotted(call.func)
    if isinstance(call.func, ast.Attribute) and name in LOG_METHODS:
        return "Log"
    if name in LOG_HELPERS:
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


class _Scanner:
    def __init__(self, tree: ast.AST) -> None:
        self.parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                self.parents[child] = node
        self.skip: set[int] = set()        # Konstanten in f-Strings und Format-Specs
        self.exempt: dict[int, str] = {}   # Teilbäume mit Kontext-Ausnahme
        for node in ast.walk(tree):
            self._mark(node)

    def _exempt_tree(self, node: ast.AST, reason: str) -> None:
        for sub in ast.walk(node):
            self.exempt.setdefault(id(sub), reason)

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
            reason = _call_context(node)
            if reason:
                for arg in [*node.args, *(k.value for k in node.keywords)]:
                    self._exempt_tree(arg, reason)
            for kw in node.keywords:
                if kw.arg in TECH_KEYWORDS:
                    self._exempt_direct(kw.value, f"Schlüsselwort {kw.arg}=")
        elif isinstance(node, ast.Subscript):
            self._exempt_direct(node.slice, "Index")
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if key is not None:
                    self._exempt_direct(key, "Dict-Schlüssel")
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

    def _exempt_direct(self, node: ast.AST, reason: str) -> None:
        """Das Literal selbst oder die Literale einer Tupel-/Listen-/Mengen-Angabe bzw. eines
        bedingten Ausdrucks — nicht tiefer (ein Aufruf darin bleibt geprüft)."""
        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            self._exempt_tree(node, reason)
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            for elt in node.elts:
                self._exempt_direct(elt, reason)
        elif isinstance(node, ast.IfExp):
            self._exempt_direct(node.body, reason)
            self._exempt_direct(node.orelse, reason)

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
                               self._is_key(node)))
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
        reason = text_reason(lit.text)
        if reason:
            out.append(Finding(lit.text, lit.line, reason))
    return out


def key_literals(source: str) -> list[str]:
    """Die Schlüssel aller t("…")/N_("…")-Aufrufe der Quelle, in Reihenfolge."""
    return [lit.text for lit in scan(source) if lit.key]


def dynamic_keys(source: str) -> list[int]:
    """Zeilen von t(/N_(-Aufrufen, deren Schlüssel gebaut statt genannt wird.

    Erlaubt sind ein Literal und für `t(` ein Tabellenzugriff (`t(TABELLE[code])`,
    `t(TABELLE.get(code, N_("…")))`); f-Strings, Verkettung, Formatieren und Namen sind
    es nicht — ein Name könnte einen gebauten Schlüssel tragen."""
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
        is_t = _callee_name(node) == "t"
        lookup = isinstance(arg, ast.Subscript) or (
            isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
            and arg.func.attr == "get")
        if is_t and lookup:
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


def read_base(base: str, rel: str) -> str:
    """Quelltext von `rel` im Stand `base` (Ordner oder git-Ref); "" wenn es die Datei
    dort nicht gab."""
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

"""Textschicht des Desktops (`src/i18n`): `t`, `N_`, Sprache und Katalog."""
import ast
import logging
import pathlib

import pytest

from src import i18n
from src.i18n import de

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_language():
    i18n.set_language(i18n.DEFAULT_LANGUAGE)
    i18n._warned.clear()
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)
    i18n._warned.clear()


def test_t_replaces_parameters_and_leaves_unknown_placeholders_standing():
    assert i18n.t("i18n.beispiel", name="Anna", count=3) == "Hallo Anna, es sind 3 Einträge."
    assert i18n.t("i18n.beispiel", name="Anna") == "Hallo Anna, es sind {count} Einträge."
    assert i18n.t("i18n.beispiel") == "Hallo {name}, es sind {count} Einträge."
    assert i18n.t("i18n.ohne_parameter") == "Nur Text"


def test_t_replaces_in_one_pass_so_values_with_braces_stay_literal():
    # Ein Wert mit `{count}` darf nicht seinerseits ersetzt werden (kein str.format, ein Durchlauf).
    assert i18n.t("i18n.beispiel", name="{count}", count=3) == "Hallo {count}, es sind 3 Einträge."
    assert i18n.t("i18n.beispiel", name="{", count="}") == "Hallo {, es sind } Einträge."


def test_a_parameter_named_key_does_not_collide_with_the_key():
    assert i18n.t("i18n.schluessel", key="Strg+S") == "Taste Strg+S"


def test_an_unknown_key_returns_the_key_and_warns_once(caplog):
    with caplog.at_level(logging.WARNING, logger="src.i18n"):
        assert i18n.t("gibt.es.nicht") == "gibt.es.nicht"
        assert i18n.t("gibt.es.nicht", x=1) == "gibt.es.nicht"
    warnings = [r for r in caplog.records if "gibt.es.nicht" in r.getMessage()]
    assert len(warnings) == 1


def test_n_marker_is_the_identity():
    assert i18n.N_("a.b") == "a.b"


@pytest.mark.parametrize("value, expected", [
    ("de", "de"), ("DE", "de"), ("de-AT", "de"), ("de_CH", "de"), (" de ", "de"),
    ("xx", "de"), ("", "de"), (None, "de"), (5, "de"), (["de"], "de"),
])
def test_normalize_language(value, expected):
    assert i18n.normalize_language(value) == expected


def test_normalize_language_follows_the_supported_languages(monkeypatch):
    monkeypatch.setattr(i18n, "LANGUAGES", ("de", "en"))
    assert i18n.normalize_language("en-US") == "en"
    assert i18n.normalize_language("fr") == "de"


def test_set_language_normalizes():
    i18n.set_language("xx")
    assert i18n.get_language() == "de"
    i18n.set_language("de-AT")
    assert i18n.get_language() == "de"


def test_an_unsupported_catalog_falls_back_to_german(monkeypatch):
    # Eine Sprache ohne eigenen Katalog (oder mit Lücke) liest den deutschen Text.
    monkeypatch.setattr(i18n, "LANGUAGES", ("de", "en"))
    i18n.set_language("en")
    assert i18n.get_language() == "en"
    assert i18n.t("i18n.ohne_parameter") == "Nur Text"


def test_the_languages_are_the_catalogs():
    assert i18n.LANGUAGES == tuple(i18n.CATALOGS)
    assert i18n.DEFAULT_LANGUAGE in i18n.LANGUAGES
    assert i18n.CATALOGS["de"] is i18n.TEXTS


def test_no_duplicate_keys_across_area_modules():
    seen: dict[str, str] = {}
    duplicates = []
    for area in de.AREAS:
        for key in area.TEXTS:
            if key in seen:
                duplicates.append(f"{key}: {seen[key]} und {area.__name__}")
            seen[key] = area.__name__
    assert duplicates == []
    assert de.TEXTS == {k: v for area in de.AREAS for k, v in area.TEXTS.items()}


def test_every_area_module_is_part_of_the_catalog():
    folder = REPO / "src" / "i18n" / "de"
    files = {p.stem for p in folder.glob("*.py") if p.stem != "__init__"}
    assert files == {area.__name__.rsplit(".", 1)[1] for area in de.AREAS}


def test_catalog_keys_are_dotted_lowercase_names_and_texts_are_strings():
    import re
    for key, text in i18n.TEXTS.items():
        assert re.fullmatch(r"[a-z0-9_]+(\.[a-z0-9_]+)+", key), key
        assert isinstance(text, str) and text, key


def test_the_layer_imports_nothing_from_src():
    # `region` importiert `i18n`; ein Rückweg wäre ein Importzyklus, und PyInstaller
    # findet die Bereichsmodule nur über statische Importe.
    def foreign(module: str) -> bool:
        inside = module == "src.i18n" or module.startswith("src.i18n.")
        return (module == "src" or module.startswith("src.")) and not inside

    for path in (REPO / "src" / "i18n").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not foreign(node.module), path
                assert not node.module.startswith("importlib"), path
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not foreign(alias.name), path
                    assert not alias.name.startswith("importlib"), path


def test_main_sets_the_language_right_after_the_settings():
    source = (REPO / "src" / "main.py").read_text(encoding="utf-8")
    settings_at = source.index("settings = Settings(")
    language_at = source.index('i18n.set_language(settings.get("language"))')
    storage_at = source.index("storage = Storage(")
    assert settings_at < language_at < storage_at


def test_version_module_does_not_import_the_text_layer():
    """Release-Skripte importieren `src.version` nur für `VERSION`; ein
    Katalogfehler darf sie nicht brechen."""
    import subprocess
    import sys
    code = ("import sys, src.version; "
            "sys.exit(1 if any(m == 'src.i18n' or m.startswith('src.i18n.') "
            "for m in sys.modules) else 0)")
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO)
    assert result.returncode == 0

"""Der Uninstaller löscht auf Nachfrage genau die Nutzerdaten, die die README
aufzählt.

`vacations.json` kam mit dem Urlaubs-Feature in die README, aber nie in
`DeleteUserData` von `installer.iss` — wer „Daten löschen" wählte, behielt
seine Urlaubszeiträume (#101). Die Liste in der README ist die Zusage an den
Nutzer; dieser Test hält den Uninstaller daran fest. Reine stdlib, wie
`test_claude_md_claims.py`.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _readme_user_files():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("**Deine Daten:**")
    end = text.index("**Zugangsdaten**", start)
    names = re.findall(r"^- \*\*([^*]+)\*\*", text[start:end], flags=re.M)
    assert names, "Liste „Deine Daten“ in der README nicht gefunden"
    return names


def _delete_user_data_body():
    text = (ROOT / "installer.iss").read_text(encoding="utf-8")
    match = re.search(r"procedure DeleteUserData\(\);\s*begin(.*?)\nend;",
                      text, flags=re.S)
    assert match, "DeleteUserData in installer.iss nicht gefunden"
    return match.group(1)


def test_uninstaller_deletes_every_user_file_the_readme_lists():
    body = _delete_user_data_body()
    missing = []
    for name in _readme_user_files():
        top = name.split("/")[0]
        if "/" in name:
            # Ordner (logs/zeiterfassung.log) wird als Ganzes entfernt.
            covered = f"DelTree(ExpandConstant('{{app}}\\{top}')" in body
        else:
            covered = f"DeleteFile(ExpandConstant('{{app}}\\{name}'))" in body
        if not covered:
            missing.append(name)
    assert missing == []

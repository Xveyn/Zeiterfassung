from src.dialogs.category_dialog import add_category, remove_category, rename_category


def test_add_category():
    assert add_category([], "Büro") == ["Büro"]


def test_add_strips_whitespace():
    assert add_category([], "  Büro  ") == ["Büro"]


def test_add_empty_is_ignored():
    assert add_category(["A"], "   ") == ["A"]


def test_add_duplicate_is_ignored():
    assert add_category(["Büro"], "Büro") == ["Büro"]


def test_add_returns_new_list():
    orig = ["A"]
    result = add_category(orig, "B")
    assert orig == ["A"]            # Original unverändert
    assert result == ["A", "B"]


def test_remove_category():
    assert remove_category(["A", "B"], "A") == ["B"]


def test_remove_absent_is_noop():
    assert remove_category(["A"], "X") == ["A"]


def test_rename_category():
    assert rename_category(["A", "B"], "A", "C") == ["C", "B"]


def test_rename_strips_whitespace():
    assert rename_category(["A"], "A", "  C  ") == ["C"]


def test_rename_empty_new_is_ignored():
    assert rename_category(["A"], "A", "   ") == ["A"]


def test_rename_absent_old_is_noop():
    assert rename_category(["A"], "X", "C") == ["A"]


def test_rename_to_existing_other_is_ignored():
    assert rename_category(["A", "B"], "A", "B") == ["A", "B"]


def test_rename_to_same_name_keeps_list():
    assert rename_category(["A", "B"], "A", "A") == ["A", "B"]

def test_selected_category_filter_empty_map_is_none():
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({}) is None


def test_selected_category_filter_all_selected_is_none():
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"Büro": True, "HO": True}) is None


def test_selected_category_filter_partial_returns_selected_set():
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"Büro": True, "HO": False}) == {"Büro"}


def test_selected_category_filter_none_selected_returns_empty_set():
    # keiner ausgewählt ist NICHT "alle" -> leere Menge (Filter ohne Treffer),
    # exakt die bisherige send_dialog-Semantik.
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"Büro": False, "HO": False}) == set()

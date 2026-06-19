from src.ui import _delete_action


def test_delete_action_none_when_type_not_selected():
    assert _delete_action([{"start": "08:00"}], {"reservation:all"}, "entry") == ("none", None)


def test_delete_action_whole_type():
    assert _delete_action([{"start": "08:00"}], {"entry:all"}, "entry") == ("delete", None)


def test_delete_action_partial_keeps_rest():
    slots = [{"s": 0}, {"s": 1}, {"s": 2}]
    action, keep = _delete_action(slots, {"entry:1"}, "entry")
    assert action == "save"
    assert keep == [{"s": 0}, {"s": 2}]


def test_delete_action_all_indices_selected_becomes_delete():
    slots = [{"s": 0}, {"s": 1}]
    assert _delete_action(slots, {"entry:0", "entry:1"}, "entry") == ("delete", None)


def test_delete_action_prefix_isolation():
    slots = [{"s": 0}, {"s": 1}]
    # Nur Reservierungs-Keys gewählt → entry nicht betroffen.
    assert _delete_action(slots, {"reservation:0"}, "entry") == ("none", None)
    # Reservierungs-Teillöschung trifft den reservation-Prefix.
    action, keep = _delete_action(slots, {"reservation:0"}, "reservation")
    assert action == "save"
    assert keep == [{"s": 1}]


def test_delete_action_mixed_selection():
    entry_slots = [{"s": 0}, {"s": 1}]
    res_slots = [{"r": 0}]
    selected = {"entry:0", "reservation:all"}
    assert _delete_action(entry_slots, selected, "entry") == ("save", [{"s": 1}])
    assert _delete_action(res_slots, selected, "reservation") == ("delete", None)

from src import sick_plan


def test_normalize_basis():
    assert sick_plan.normalize_basis("average_3m") == "average_3m"
    assert sick_plan.normalize_basis("standard") == "standard"
    for bad in ("kaputt", None, 3):
        assert sick_plan.normalize_basis(bad) == "standard"

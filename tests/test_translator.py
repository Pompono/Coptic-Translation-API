from app.translator import copticify, normalize_bohairic_output, normalize_dialect


def test_dialect_aliases():
    assert normalize_dialect("s", "bohairic") == "sahidic"
    assert normalize_dialect(None, "bohairic") == "bohairic"


def test_greek_output_is_converted_to_coptic():
    assert copticify("ⲁγαπη") == "ⲁⲅⲁⲡⲏ"


def test_bohairic_normalization_only_applies_to_bohairic():
    source = "ϫⲟⲉⲓⲥ"
    assert normalize_bohairic_output(source, "bohairic") == "ϭⲟⲓⲥ"
    assert normalize_bohairic_output(source, "sahidic") == source

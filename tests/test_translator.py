from app.translator import TranslationModels, copticify, normalize_bohairic_output, normalize_dialect


def test_dialect_aliases():
    assert normalize_dialect("s", "bohairic") == "sahidic"
    assert normalize_dialect(None, "bohairic") == "bohairic"


def test_greek_output_is_converted_to_coptic():
    assert copticify("ⲁγαπη") == "ⲁⲅⲁⲡⲏ"


def test_bohairic_normalization_only_applies_to_bohairic():
    source = "ϫⲟⲉⲓⲥ"
    assert normalize_bohairic_output(source, "bohairic") == "ϭⲟⲓⲥ"
    assert normalize_bohairic_output(source, "sahidic") == source


def test_english_input_has_the_selected_model_dialect_prefix():
    assert TranslationModels._prepared_english("Amen", "bohairic").text == "б amen"
    assert TranslationModels._prepared_english("Amen", "sahidic").text == "з amen"

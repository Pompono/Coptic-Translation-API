from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import math

SAHIDIC_TAG = "з"
BOHAIRIC_TAG = "б"

COPTIC_TO_GREEK = {
    "ⲁ": "α", "ⲃ": "β", "ⲅ": "γ", "ⲇ": "δ", "ⲉ": "ε", "ⲋ": "ϛ", "ⲍ": "ζ",
    "ⲏ": "η", "ⲑ": "θ", "ⲓ": "ι", "ⲕ": "κ", "ⲗ": "λ", "ⲙ": "μ", "ⲛ": "ν",
    "ⲝ": "ξ", "ⲟ": "ο", "ⲡ": "π", "ⲣ": "ρ", "ⲥ": "σ", "ⲧ": "τ", "ⲩ": "υ",
    "ⲫ": "φ", "ⲭ": "χ", "ⲯ": "ψ", "ⲱ": "ω", "ϣ": "s", "ϥ": "f", "ϧ": "k",
    "ϩ": "h", "ϫ": "j", "ϭ": "c", "ϯ": "t",
}
GREEK_TO_COPTIC = {value: key for key, value in COPTIC_TO_GREEK.items()}
GREEK_TO_COPTIC.update({"ς": "ⲥ", "ϲ": "ⲥ"})
GREEK_TO_COPTIC.update({key.upper(): value.upper() for key, value in list(GREEK_TO_COPTIC.items()) if key.isalpha()})

BOHAIRIC_NORMALIZATION_MAP = {
    "ϫⲟⲉⲓⲥ": "ϭⲟⲓⲥ",
    "ⲡⲁϫⲟⲉⲓⲥ": "ⲡⲁϭⲟⲓⲥ",
    "ⲓⲏⲥⲩⲥ": "ⲓⲏⲥⲟⲩⲥ",
    "ⲓⲉⲥⲟⲩⲥ": "ⲓⲏⲥⲟⲩⲥ",
    "ⲡⲛⲛⲟⲩⲧⲉ": "ⲛ̀ⲛⲟⲩϯ",
    "ⲡϣⲏⲣⲓ ⲛⲛⲟⲩⲧⲉ": "ⲡϣⲏⲣⲓ ⲛ̀ⲛⲟⲩϯ",
}


class TranslatorLoadError(RuntimeError):
    pass


class TranslatorRuntimeError(RuntimeError):
    pass


class TranslatorInputError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedInput:
    dialect: str
    text: str


def normalize_dialect(dialect: str | None, default: str) -> str:
    value = (dialect or default).strip().lower()
    aliases = {"sahidic": "sahidic", "sah": "sahidic", "s": "sahidic",
               "bohairic": "bohairic", "boh": "bohairic", "b": "bohairic"}
    if value not in aliases:
        raise ValueError("dialect must be one of: sahidic, bohairic")
    return aliases[value]


def copticify(text: str) -> str:
    return "".join(GREEK_TO_COPTIC.get(char, char) for char in text)


def normalize_bohairic_output(text: str, dialect: str) -> str:
    if dialect != "bohairic":
        return text
    for source, target in BOHAIRIC_NORMALIZATION_MAP.items():
        text = text.replace(source, target).replace(source.upper(), target.upper())
    return text


class TranslationModels:
    """Loads each Hugging Face model once and reuses it for all API requests."""

    def __init__(self, c2e_model: str, e2c_model: str, c2e_revision: str = "main",
                 e2c_revision: str = "main", max_new_tokens: int = 64) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            self.c2e_tokenizer = AutoTokenizer.from_pretrained(c2e_model, revision=c2e_revision)
            self.c2e_model = AutoModelForSeq2SeqLM.from_pretrained(c2e_model, revision=c2e_revision)
            self.e2c_tokenizer = AutoTokenizer.from_pretrained(e2c_model, revision=e2c_revision)
            self.e2c_model = AutoModelForSeq2SeqLM.from_pretrained(e2c_model, revision=e2c_revision)
            self.c2e_model.to(self.device).eval()
            self.e2c_model.to(self.device).eval()
        except Exception as exc:  # noqa: BLE001
            raise TranslatorLoadError(f"Unable to load the configured Hugging Face models: {exc}") from exc
        self.max_new_tokens = max_new_tokens

    @staticmethod
    def _prepared_coptic(text: str, dialect: str) -> ProcessedInput:
        normalized = text.strip().lower()
        greek_text = "".join(COPTIC_TO_GREEK.get(char, char) for char in normalized)
        tag = BOHAIRIC_TAG if dialect == "bohairic" else SAHIDIC_TAG
        return ProcessedInput(dialect, f"{tag} {greek_text}")

    @staticmethod
    def _prepared_english(text: str, dialect: str) -> ProcessedInput:
        normalized = text.strip().lower()
        tag = BOHAIRIC_TAG if dialect == "bohairic" else SAHIDIC_TAG
        normalized = f"{tag} {normalized}"
        return ProcessedInput(dialect, normalized)

    def translate(self, text: str, direction: str, dialect: str | None = None,
                  include_confidence: bool = False) -> dict[str, Any]:
        if direction == "coptic_to_english":
            chosen_dialect = normalize_dialect(dialect, "sahidic")
            prepared = self._prepared_coptic(text, chosen_dialect)
            model, tokenizer = self.c2e_model, self.c2e_tokenizer
            def output_transform(value: str) -> str:
                return value.strip()
        elif direction == "english_to_coptic":
            chosen_dialect = normalize_dialect(dialect, "bohairic")
            prepared = self._prepared_english(text, chosen_dialect)
            model, tokenizer = self.e2c_model, self.e2c_tokenizer
            def output_transform(value: str) -> str:
                return normalize_bohairic_output(copticify(value.strip()), chosen_dialect)
        else:
            raise ValueError("direction must be coptic_to_english or english_to_coptic")

        try:
            encoded = tokenizer(prepared.text, return_tensors="pt", truncation=False)
            if encoded["input_ids"].shape[-1] > 512:
                raise TranslatorInputError("text exceeds the model limit of 512 input tokens")
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            generation_args = {"max_new_tokens": self.max_new_tokens}
            if include_confidence:
                generation_args.update(output_scores=True, return_dict_in_generate=True)
            with self._torch.inference_mode():
                generated = model.generate(**encoded, **generation_args)
            sequence = generated.sequences[0] if include_confidence else generated[0]
            result = output_transform(tokenizer.decode(sequence, skip_special_tokens=True))
        except TranslatorInputError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TranslatorRuntimeError(f"Translation generation failed: {exc}") from exc

        if not result:
            raise TranslatorRuntimeError("The model returned an empty translation")
        response = {"translation": result, "direction": direction, "dialect": chosen_dialect}
        if include_confidence:
            # This preserves the reference implementation's heuristic; it is not calibrated.
            token_confidences = [self._torch.softmax(score[0], dim=-1).max().item() for score in generated.scores]
            word_count = max(1, len(result.split()))
            response["confidence"] = math.exp(sum(math.log(max(value, 1e-12)) for value in token_confidences) / word_count)
        return response


@lru_cache(maxsize=1)
def load_models(c2e_model: str, e2c_model: str, c2e_revision: str,
                e2c_revision: str, max_new_tokens: int) -> TranslationModels:
    return TranslationModels(c2e_model, e2c_model, c2e_revision, e2c_revision, max_new_tokens)

from __future__ import annotations

import re


# Reply-to-message "praise" triggers that automatically award +1 reputation
# (same rules/cooldown as /plus).
#
# We keep it allow-list based and only match short messages consisting of
# 1-4 tokens (optionally with intensifiers like "очень").


_INTENSIFIERS: set[str] = {
    "очень",
    "прям",
    "реально",
    "вообще",
    "просто",
    "сильно",
    "крайне",
    "ну",
}


_PRAISE_TOKENS: set[str] = {
    # User requested (incl. common misspellings).
    "норм",
    "нормс",
    "нормас",
    "нормуль",
    "нормально",
    "клас",
    "класс",
    "классно",
    "классный",
    "балдеж",
    "балдежка",
    "балдежно",
    "заебок",
    "мощно",
    "мощь",
    "мощна",
    "охуенчик",
    "охуевше",
    "охуенно",
    "красота",
    # Extra enthusiastic epithets.
    "круто",
    "крутяк",
    "крутотень",
    "крутота",
    "топ",
    "топчик",
    "имба",
    "огонь",
    "огнище",
    "пушка",
    "бомба",
    "бомбезно",
    "кайф",
    "кайфово",
    "кайфец",
    "шик",
    "шикарно",
    "великолепно",
    "офигенно",
    "обалденно",
    "обалдеть",
    "прекрасно",
    "отлично",
    "отличненько",
    "супер",
    "суперски",
    "респект",
    "уважаю",
    "годно",
    "годнота",
    "зачет",
    "красиво",
    "мега",
    "идеально",
    "лучше",
    # Vulgar enthusiastic.
    "ахуенно",
    "ахуеть",
    "заебись",
    "заебца",
    "збс",
    "пиздато",
    "пиздатенько",
    "пиздец",
    "ебать",
    # More positive words.
    "четко",
    "ништяк",
    "бесподобно",
    "восхитительно",
    "потрясающе",
    "фантастика",
    "невероятно",
    "изумительно",
    "божественно",
    "безупречно",
    "магия",
    "эпик",
    "лайк",
    "молодец",
    "красавчик",
    "красава",
    "найс",
    "наис",
    "гуд",
    "вау",
    "браво",
    "блеск",
    "шедевр",
    "сила",
    "жиза",
    "пушечка",
    "ракета",
    "бро",
    "агонь",
}


_ALLOWED_TOKENS: set[str] = _PRAISE_TOKENS | _INTENSIFIERS


def _compress_runs(token: str, *, max_run: int = 2) -> str:
    # "классссс" -> "класс", but keep double-letters ("класс", "охуенно").
    out: list[str] = []
    prev = ""
    run = 0
    for ch in token:
        if ch == prev:
            run += 1
            if run <= max_run:
                out.append(ch)
            continue
        prev = ch
        run = 1
        out.append(ch)
    return "".join(out)


def normalize_praise_text(text: str) -> list[str]:
    """Normalize text for praise matching; returns tokens."""
    s = (text or "").strip().lower().replace("ё", "е")
    if not s:
        return []

    # Remove punctuation/emojis by replacing with spaces.
    cleaned: list[str] = []
    for ch in s:
        if ch.isalpha() or ch.isdigit() or ch.isspace():
            cleaned.append(ch)
        else:
            cleaned.append(" ")

    tokens = [_compress_runs(t) for t in "".join(cleaned).split()]
    return [t for t in tokens if t]


def is_praise_reply_text(text: str) -> bool:
    """True if message text should count as a praise reply (+1)."""
    raw = (text or "").strip()
    if not raw:
        return False

    # Special case: "+" as a quick /plus replacement (reply must exist; checked elsewhere).
    compact = "".join(raw.split())
    if re.fullmatch(r"\+{1,3}(1)?", compact):
        return True

    tokens = normalize_praise_text(text)
    if not tokens:
        return False
    if len(tokens) > 4:
        return False
    if any(t not in _ALLOWED_TOKENS for t in tokens):
        return False
    return any(t in _PRAISE_TOKENS for t in tokens)

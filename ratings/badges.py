from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Badge:
    threshold: int
    name: str
    icon: str


BADGES: tuple[Badge, ...] = (
    # Levels are based on the public table from "Ответы Mail.ru".
    Badge(0, "Новичок", "🌱"),
    Badge(1, "Ученик", "📗"),
    Badge(250, "Знаток", "📚"),
    Badge(500, "Профи", "🎯"),
    Badge(1000, "Мастер", "🛠"),
    Badge(2500, "Гуру", "🧠"),
    Badge(5000, "Мыслитель", "🤔"),
    Badge(10000, "Мудрец", "🦉"),
    Badge(20000, "Просветленный", "✨"),
    # Two names for the same rating range depending on КПД.
    Badge(50000, "Оракул", "🔮"),
    Badge(50000, "Гений", "🧬"),
    Badge(100000, "Искусственный интеллект", "🤖"),
    Badge(100000, "Высший разум", "🌌"),
)

# Unique thresholds in ascending order (used for "next badge" hints).
_LEVELS: tuple[tuple[int, str], ...] = (
    (0, "Новичок"),
    (1, "Ученик"),
    (250, "Знаток"),
    (500, "Профи"),
    (1000, "Мастер"),
    (2500, "Гуру"),
    (5000, "Мыслитель"),
    (10000, "Мудрец"),
    (20000, "Просветленный"),
    (50000, "Оракул/Гений"),
    (100000, "Искусственный интеллект/Высший разум"),
)


def badge_for_rating(rating: int, *, kpd_percent: int | None = None) -> Badge:
    """Return badge for rating, optionally using КПД for top tiers.

    КПД is used only for:
    - 50_000..99_999: Гений if КПД >= 25%, else Оракул
    - 100_000+: Высший разум if КПД >= 30%, else Искусственный интеллект
    """
    rating = int(rating)
    kpd = int(kpd_percent) if kpd_percent is not None else None

    if rating >= 100000:
        if kpd is not None and kpd >= 30:
            return Badge(100000, "Высший разум", "🌌")
        return Badge(100000, "Искусственный интеллект", "🤖")

    if rating >= 50000:
        if kpd is not None and kpd >= 25:
            return Badge(50000, "Гений", "🧬")
        return Badge(50000, "Оракул", "🔮")

    current = BADGES[0]
    for b in BADGES:
        if b.threshold >= 50000:
            break
        if rating >= b.threshold:
            current = b
        else:
            break
    return current


def next_badge(rating: int) -> Badge | None:
    rating = int(rating)
    for threshold, name in _LEVELS:
        if rating < threshold:
            # Icons are only cosmetic here.
            return Badge(threshold, name, "⬆️")
    return None

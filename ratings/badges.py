from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Badge:
    threshold: int
    name: str
    icon: str


BADGES: tuple[Badge, ...] = (
    Badge(0, "Новичок", "🌱"),
    Badge(10, "Мыслитель", "🤔"),
    Badge(50, "Знаток", "📚"),
    Badge(150, "Мастер", "🛠"),
    Badge(300, "Гуру", "🧠"),
    Badge(500, "Мудрец", "🦉"),
    Badge(800, "Легенда", "🏆"),
)


def badge_for_rating(rating: int) -> Badge:
    current = BADGES[0]
    for b in BADGES:
        if rating >= b.threshold:
            current = b
        else:
            break
    return current


def next_badge(rating: int) -> Badge | None:
    for b in BADGES:
        if rating < b.threshold:
            return b
    return None

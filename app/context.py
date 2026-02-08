from __future__ import annotations

from dataclasses import dataclass

from config.config import Settings
from demotivator.layout import LayoutConfig
from ratings.service import RatingService
from services.groq_service import GroqService


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    layout_cfg: LayoutConfig
    groq: GroqService
    rating: RatingService


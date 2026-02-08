from __future__ import annotations

import logging
import random

from groq import Groq


class GroqService:
    def __init__(self, *, api_key: str) -> None:
        self._client = Groq(api_key=api_key) if api_key else None

    def enabled(self) -> bool:
        return self._client is not None

    def generate_demotivator_text(self) -> str:
        """Generate a short phrase for a demotivator."""
        if not self._client:
            return random.choice(
                [
                    "Жизнь - боль",
                    "Всё тленно",
                    "Ничего не вечно",
                    "Надежда умирает последней",
                ]
            )

        try:
            prompts = [
                "напиши какой-нибудь рофл рофлянский",
                "напиши какую-нибудь шизу до 8 слов",
            ]

            response = self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "Ты генератор текста для демотиваторов. Пиши кратко, саркастично, по-русски.",
                    },
                    {"role": "user", "content": random.choice(prompts)},
                ],
                max_tokens=50,
                temperature=1.2,
            )

            text = response.choices[0].message.content.strip()
            text = text.strip('"').strip("'").strip()

            words = text.split()
            if len(words) > 10:
                text = " ".join(words[:10]) + "..."

            logging.info("Generated text: %s", text)
            return text

        except Exception as e:
            logging.error("Groq generation error: %s", e, exc_info=True)
            return random.choice(["Всё сложно", "Бывает", "Жизнь - боль", "Ничего не вечно"])

    def trumpify_text(self, *, original_text: str) -> str:
        """Rewrite text in the style of Donald Trump."""
        if not self._client:
            return f"{original_text} Tremendous! 🇺🇸"

        try:
            prompt = f"""Перепиши текст в стиле твитов Дональда Трампа. Точно копируй его манеру!

ОБЯЗАТЕЛЬНЫЕ элементы стиля:
- ЗАГЛАВНЫЕ слова для усиления (VERY, GREAT, FAKE NEWS, TERRIBLE, etc)
- Превосходные степени: biggest, greatest, best, worst, most, tremendous, fantastic, incredible, beautiful
- Короткие резкие предложения. Много восклицательных знаков!
- Фразы: "Many people are saying", "Believe me", "Everyone knows", "Like never before"
- Местоимения: "I", "We", "They" (враги)
- Третье лицо о себе: "President Trump", "Your favorite President"
- Эмодзи: 🇺🇸 (обязательно 1-2 раза)
- Драматизм и уверенность
- Обвинения врагов в провалах

Оригинал: "{original_text}"

Ответ (только переписанный текст без комментариев):"""

            response = self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You write EXACTLY like Donald Trump tweets. Use his style: CAPS, "
                            "superlatives, short sentences, confidence, drama. Add 1-2 🇺🇸 flags."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=350,
                temperature=1.0,
            )

            result = response.choices[0].message.content.strip()
            result = result.strip('"').strip("'").strip()
            result = result.replace("**", "")
            return result

        except Exception as e:
            logging.error("Trumpify error: %s", e, exc_info=True)
            return f"{original_text} - FAKE NEWS! 🇺🇸"

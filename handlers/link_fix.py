from __future__ import annotations

import re
from aiogram import Router, F
from aiogram.types import Message

router = Router(name="link_fix")

# Domain replacement map: (pattern, replacement)
_FIXES: list[tuple[re.Pattern[str], str]] = [
    # Twitter → fxtwitter
    (re.compile(r'https?://(?:www\.)?twitter\.com/'), 'https://fxtwitter.com/'),
    # X.com → fixupx
    (re.compile(r'https?://(?:www\.)?x\.com/'), 'https://fixupx.com/'),
    # TikTok → vxtiktok
    (re.compile(r'https?://(?:www\.)?tiktok\.com/'), 'https://www.vxtiktok.com/'),
]

# Match any URL from supported platforms
_URL_RE = re.compile(
    r'https?://(?:www\.)?(?:twitter\.com|x\.com|tiktok\.com)/\S+'
)


def _has_fixable_url(text: str | None) -> bool:
    return bool(text and _URL_RE.search(text))


def _fix_urls(text: str) -> list[str]:
    """Extract URLs and return their fixed versions (only those that changed)."""
    urls = _URL_RE.findall(text)
    fixed = []
    for url in urls:
        new_url = url
        for pattern, replacement in _FIXES:
            new_url = pattern.sub(replacement, new_url, count=1)
        if new_url != url:
            fixed.append(new_url)
    return fixed


@router.message(F.text.func(_has_fixable_url))
async def fix_links_in_text(message: Message) -> None:
    from handlers.x_video import handled_urls
    from services.x_video import canonical_url
    handled = handled_urls(message)
    text = _URL_RE.sub(lambda m: '' if canonical_url(m.group().rstrip('.,!?:;)]}\"\'')) in handled else m.group(), message.text)
    fixed = _fix_urls(text)
    if fixed:
        await message.reply('\n'.join(fixed))


@router.message(F.caption.func(_has_fixable_url))
async def fix_links_in_caption(message: Message) -> None:
    fixed = _fix_urls(message.caption)
    if fixed:
        await message.reply('\n'.join(fixed))

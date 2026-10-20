"""Automatic public Instagram standalone media, scoped to existing groups only."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import unicodedata
import re
from pathlib import Path

from aiogram import Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Filter
from aiogram.types import FSInputFile, InputMediaVideo, InputMediaPhoto, Message, ReplyParameters

from services.instagram_download import (DownloadError, DownloadService, canonical_url,
                                         extract_urls, media_type, media_value, media_complete, MAX_ITEMS, MediaItem)
from services.instagram_video_metadata import probe_video_dimensions, valid_dimensions
from services.x_video import canonical_url as canonical_x_url

BASE = Path(__file__).resolve().parents[1]
# Frozen deployment snapshot, not a live DB query: joining a new group does NOT
# grant it downloader access. Fail closed if configuration is absent or invalid.
try:
    _ids = json.loads((BASE / 'config/instagram_chats.json').read_text())['allowed_chat_ids']
    if not isinstance(_ids, list) or any(type(x) is not int or x >= 0 for x in _ids):
        raise ValueError('invalid chat allowlist')
except (OSError, ValueError, KeyError, TypeError):
    _ids = []
# Missing/invalid delivery config defaults to conservative debug replies.
try:
    DELIVERY = json.loads((BASE / 'config/instagram_delivery.json').read_text())
    if set(DELIVERY) != {'reply_mode', 'delete_source', 'author_caption'} or any(type(v) is not bool for v in DELIVERY.values()):
        raise ValueError('invalid delivery configuration')
except (OSError, ValueError, TypeError):
    DELIVERY = dict(reply_mode=True, delete_source=False, author_caption=True)
service = DownloadService(BASE, _ids)
router = Router(name='instagram')


class InstagramFilter(Filter):
    async def __call__(self, message: Message):
        # Existing media already contains the payload: never redownload its
        # caption/link, including media forwarded from downloader bots.
        if any(getattr(message, field, None) for field in (
                'video', 'animation', 'document', 'photo', 'audio', 'voice',
                'video_note', 'sticker')):
            return False
        text = message.text or ''
        if (os.getenv('INSTAGRAM_ENABLED', '1') != '1'
                or message.chat.type not in {'group', 'supergroup'}
                or message.chat.id not in service.allowed_chats
                or (message.from_user and message.from_user.is_bot and not message.sender_chat)
                or text.lstrip().startswith('/')):
            return False
        urls = extract_urls(text)
        for entity in (message.entities or message.caption_entities or []):
            if entity.type == 'text_link' and entity.url:
                url = canonical_url(entity.url)
                if url and url not in urls:
                    urls.append(url)
        # Only current-message links, bounded before queue admission.
        return {'instagram_urls': urls[:3]} if urls else False


@router.message(InstagramFilter())
async def instagram_video(message: Message, instagram_url=None, instagram_urls=None):
    started = time.monotonic()
    user = message.from_user
    author = (getattr(getattr(message, 'sender_chat', None), 'title', '') or
              getattr(user, 'username', None) or
              ' '.join(x for x in (getattr(user, 'first_name', None), getattr(user, 'last_name', None)) if x) or
              getattr(getattr(message, 'sender_chat', None), 'title', '') or '')
    author = ''.join(' ' if unicodedata.category(c).startswith('C') else c for c in author).replace('@', '')[:80].strip()
    text = message.text or ''
    def remove_instagram(match):
        raw = match.group()
        clean = raw.rstrip(".,!?:;)]}\"'")
        return raw[len(clean):] if canonical_url(clean) else raw
    comment = re.sub(r'https://[^\s<>]+', remove_instagram, text).strip()
    current_urls = set(extract_urls(text))
    preserve_link_entities = False
    for entity in (getattr(message, 'entities', None) or []):
        if entity.type == 'text_link' and entity.url:
            linked = canonical_url(entity.url)
            if linked:
                current_urls.add(linked)
            else:
                preserve_link_entities = True

    caption = '\n'.join(x for x in (author if DELIVERY['author_caption'] else '', comment) if x)
    # Conservative UTF-16 bound; never remove source if its comment is omitted.
    complete_caption = len(caption.encode('utf-16-le')) // 2 <= 1024
    if not complete_caption:
        caption = author if DELIVERY['author_caption'] else ''
    common = dict(chat_id=message.chat.id, message_thread_id=getattr(message, 'message_thread_id', None),
                  reply_parameters=ReplyParameters(message_id=message.message_id) if DELIVERY['reply_mode'] else None)
    confirmed = 0
    async def send(items):
        nonlocal confirmed
        kinds = [media_type(x) for x in items]
        if not 1 <= len(items) <= MAX_ITEMS or any(x not in {'photo', 'video'} for x in kinds):
            raise DownloadError('invalid_file')
        values = [media_value(x) for x in items]
        dimensions = []
        for index, (kind, value, item) in enumerate(zip(kinds, values, items)):
            dims = None
            if kind == 'video':
                if isinstance(value, Path):
                    dims = await probe_video_dimensions(value)
                    if dims:
                        # The service caches this exact list after successful send.
                        items[index] = MediaItem(kind, value, *dims, coverage=getattr(item, 'coverage', None))
                elif isinstance(item, MediaItem) and valid_dimensions(item.width, item.height):
                    dims = (item.width, item.height)
            dimensions.append(dict(width=dims[0], height=dims[1]) if dims else {})
        media = [FSInputFile(x) if isinstance(x, Path) else x for x in values]
        if len(media) == 1:
            if kinds[0] == 'photo':
                sent = [await message.bot.send_photo(photo=media[0], caption=caption, parse_mode=None, caption_entities=[], **common)]
            else:
                sent = [await message.bot.send_video(video=media[0], supports_streaming=True, caption=caption, parse_mode=None, caption_entities=[], **common, **dimensions[0])]
        else:
            sent = await message.bot.send_media_group(**common, media=[
                InputMediaPhoto(media=x, caption=caption if index == 0 else None, parse_mode=None, caption_entities=[]) if kind == 'photo'
                else InputMediaVideo(media=x, supports_streaming=True, caption=caption if index == 0 else None, parse_mode=None, caption_entities=[], **dims)
                for index, (kind, x, dims) in enumerate(zip(kinds, media, dimensions))])
        ids = []
        for kind, result in zip(kinds, sent):
            if kind == 'photo' and getattr(result, 'photo', None):
                ids.append(result.photo[-1].file_id)
            elif kind == 'video' and getattr(result, 'video', None):
                ids.append(result.video.file_id)
        if len(ids) == len(items) and len(sent) == len(items) and all(media_complete(x) for x in items):
            confirmed += 1
        return ids

    async def process(url):
        before = confirmed
        try:
            await service.handle(message.chat.id, url, send, message_id=message.message_id)
            logging.info('Instagram delivery success shortcode=%s message_id=%s chat=%s elapsed=%.3f',
                         canonical_url(url).rstrip('/').rsplit('/', 1)[-1],
                         message.message_id, message.chat.id, time.monotonic() - started)
            return confirmed > before
        except Exception as exc:
            # Automatic downloads never send status/error text. Never retry an
            # ambiguous Telegram delivery; the service retry boundary is fetch-only.
            reason = str(exc) if isinstance(exc, DownloadError) else 'unknown'
            if reason not in {'busy', 'scope', 'no_video', 'timeout', 'unavailable',
                              'empty_media', 'api_denied', 'login_or_rate_limit',
                              'invalid_file', 'too_large', 'http_error', 'network_guard'}:
                reason = 'unknown'
            logging.warning('Instagram operation failed class=%s code=%s message_id=%s chat=%s',
                            type(exc).__name__, reason, message.message_id, message.chat.id)
            return False

    urls = instagram_urls if instagram_urls is not None else [instagram_url]
    # Sequential delivery: deletion needs confirmation of every current URL.
    outcomes = []
    for url in urls[:3]:
        outcomes.append(await process(url))
    # A separate provider cannot confirm our deliveries (or vice versa). Keep
    # mixed-source originals while allowing both handlers to send their media.
    contains_x = any(canonical_x_url(value.rstrip(".,!?:;)]}\"'")) for value in re.findall(r'https?://[^\s<>]+', text))
    contains_x = contains_x or any(canonical_x_url(e.url) for e in (message.entities or []) if e.type == 'text_link' and e.url)
    if (DELIVERY['delete_source'] and not DELIVERY['reply_mode'] and complete_caption
            and not contains_x and not preserve_link_entities and urls and len(urls) <= 3
            and current_urls.issubset({canonical_url(url) for url in urls})
            and all(outcomes) and message.text is not None
            and not any(getattr(message, field, None) for field in ('video', 'animation', 'document', 'photo', 'audio', 'voice', 'video_note', 'sticker'))
            and message.chat.id in service.allowed_chats):
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception as exc:
            logging.warning('Instagram source deletion failed class=%s message_id=%s chat=%s',
                            type(exc).__name__, message.message_id, message.chat.id)
    # Preserve existing handlers (including mixed Instagram/X/TikTok text).
    raise SkipHandler

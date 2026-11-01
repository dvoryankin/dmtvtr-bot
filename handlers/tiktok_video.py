"""Silent, scoped TikTok reposts; source removal requires complete receipts."""
import json
import logging
from pathlib import Path

from aiogram import Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Filter
from aiogram.types import FSInputFile, MessageEntity
from services.repost_author import repost_author, url_entities_covered
from services.tiktok_video import TikTokService, canonical_url
from services.youtube_video import URL_RE
from collections import OrderedDict

BASE = Path(__file__).resolve().parents[1]
try:
    ids = json.loads((BASE / 'config/instagram_chats.json').read_text())['allowed_chat_ids']
    if not isinstance(ids, list) or any(type(x) is not int for x in ids):
        raise ValueError()
    ids = set(ids) & {-1003681962162, -1003911850060, -1001165620202}
except (OSError, ValueError, KeyError, TypeError):
    ids = set()
service = TikTokService(BASE, ids)
router = Router(name='tiktok_video')
HANDLED = OrderedDict()


def handled_urls(message):
    return HANDLED.get((message.chat.id, message.message_id), set())


def mark_attempted(message, url):
    key = (message.chat.id, message.message_id)
    HANDLED.setdefault(key, set()).add(url)
    HANDLED.move_to_end(key)
    while len(HANDLED) > 2048:
        HANDLED.popitem(last=False)


TRAILING = '.,!?:;)]}\"\''
MEDIA = ('video', 'animation', 'document', 'photo', 'audio', 'voice', 'video_note', 'sticker')


def entity_span(text, entity):
    """Validate Telegram UTF-16 coordinates, including surrogate boundaries."""
    offset, length = entity.offset, entity.length
    encoded = text.encode('utf-16-le')
    if (type(offset) is not int or type(length) is not int or offset < 0
            or length <= 0 or (offset + length) * 2 > len(encoded)):
        raise ValueError('invalid_entity')
    start = len(encoded[:offset * 2].decode('utf-16-le'))
    end = len(encoded[:(offset + length) * 2].decode('utf-16-le'))
    return start, end


def current(message):
    text = message.text or ''
    raw = [match.group().rstrip(TRAILING) for match in URL_RE.finditer(text)]
    for entity in (message.entities or []):
        try:
            start, end = entity_span(text, entity)
            if entity.type == 'text_link':
                raw.append(entity.url or 'invalid_entity')
            elif entity.type == 'url':
                raw.append(text[start:end].rstrip(TRAILING))
        except (AttributeError, TypeError, ValueError, UnicodeError):
            raw.append('invalid_entity')
    urls = list(dict.fromkeys(canonical_url(value) for value in raw if canonical_url(value)))
    return raw, urls


def comment_caption(message, author):
    """Remove only provider URLs; rebase intact links without losing external URLs."""
    text = message.text
    removed = set()
    for match in URL_RE.finditer(text):
        clean = match.group().rstrip(TRAILING)
        if canonical_url(clean):
            removed.update(range(match.start(), match.start() + len(clean)))
    for entity in (message.entities or []):
        try:
            start, end = entity_span(text, entity)
            if entity.type == 'url' and canonical_url(text[start:end].rstrip(TRAILING)):
                removed.update(range(start, start + len(text[start:end].rstrip(TRAILING))))
        except (AttributeError, TypeError, ValueError, UnicodeError):
            continue
    kept = [index for index in range(len(text)) if index not in removed]
    while kept and text[kept[0]].isspace():
        kept.pop(0)
    while kept and text[kept[-1]].isspace():
        kept.pop()
    comment = ''.join(text[index] for index in kept)
    prefix = author + '\n' if author and comment else author
    caption = prefix + comment
    entities = []
    positions = {old: new for new, old in enumerate(kept)}
    for entity in (message.entities or []):
        try:
            start, end = entity_span(text, entity)
            if entity.type != 'text_link' or not entity.url:
                continue
            if all(index in positions for index in range(start, end)):
                new_start = positions[start]
                entities.append(MessageEntity(type='text_link', url=entity.url,
                    offset=len((prefix + comment[:new_start]).encode('utf-16-le')) // 2,
                    length=len(text[start:end].encode('utf-16-le')) // 2))
        except (AttributeError, TypeError, ValueError, UnicodeError):
            continue
    complete = len(caption.encode('utf-16-le')) // 2 <= 1024
    return (caption, entities, True) if complete else (author, [], False)


class TikTokFilter(Filter):
    async def __call__(self, message):
        if (not message.text or message.chat.id not in service.allowed_chats
                or message.chat.type not in {'group', 'supergroup'}
                or message.text.lstrip().startswith('/')
                or any(getattr(message, key, None) for key in MEDIA)
                or (message.from_user and message.from_user.is_bot and not message.sender_chat)
                or getattr(getattr(getattr(message, 'forward_origin', None), 'sender_user', None), 'is_bot', False)
                or getattr(getattr(message, 'forward_from', None), 'is_bot', False)):
            return False
        _, urls = current(message)
        return {'tiktok_urls': urls[:3]} if urls else False


@router.message(TikTokFilter())
async def tiktok_video(message, tiktok_urls):
    raw, all_urls = current(message)
    author, _ = repost_author(message)
    caption, comment_entities, complete = comment_caption(message, author)
    outcomes = []
    for url in tiktok_urls[:3]:
        _, author_entities = repost_author(message, source_url=canonical_url(url))
        confirmed = False
        attempted = False
        covered = False

        async def send(items):
            nonlocal confirmed, attempted, covered
            if attempted:
                raise ValueError('upload_already_attempted')
            if len(items) != 1 or items[0].type != 'video':
                raise ValueError('invalid_file')
            item = items[0]
            covered = getattr(item, 'coverage', None) in (None, 'complete', 'extracted_videos')
            attempted = True
            mark_attempted(message, url)
            sent = await message.bot.send_video(
                chat_id=message.chat.id, message_thread_id=getattr(message, 'message_thread_id', None),
                video=FSInputFile(item.value) if isinstance(item.value, Path) else item.value,
                width=item.width, height=item.height, caption=caption, parse_mode=None,
                caption_entities=author_entities + comment_entities, supports_streaming=True)
            message_id = getattr(sent, 'message_id', None)
            file_id = getattr(getattr(sent, 'video', None), 'file_id', None)
            confirmed = (type(message_id) is int and message_id > 0
                         and isinstance(file_id, str) and bool(file_id))
            if not confirmed:
                raise ValueError('unconfirmed_delivery')
            return [(message_id, file_id)]

        try:
            await service.handle(message.chat.id, url, send, message_id=message.message_id)
        except Exception:
            confirmed = False
            logging.warning('TikTok video operation failed message_id=%s chat=%s', message.message_id, message.chat.id)
        outcomes.append(confirmed and covered)
    if (complete and outcomes and all(outcomes) and set(tiktok_urls) == set(all_urls)
            and all(canonical_url(value) for value in raw)
            and url_entities_covered(message.text, message.entities or [], canonical_url,
                                     {canonical_url(url) for url in tiktok_urls})):
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:
            logging.warning('TikTok source deletion failed message_id=%s chat=%s', message.message_id, message.chat.id)
    raise SkipHandler

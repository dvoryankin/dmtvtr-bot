"""Scoped, silent standalone idiod MP4 reposts; confirmations precede deletion."""
import json
import logging
from services.repost_author import repost_author
from pathlib import Path
from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import FSInputFile
from aiogram.dispatcher.event.bases import SkipHandler
from services.idiod_video import IdiodService, canonical_url, URL_RE

BASE = Path(__file__).resolve().parents[1]
try:
    ids = json.loads((BASE / 'config/instagram_chats.json').read_text())['allowed_chat_ids']
    if not isinstance(ids, list) or any(type(x) is not int for x in ids):
        raise ValueError()
    ids = set(ids) & {-1003681962162, -1003911850060, -1001165620202}
except (OSError, ValueError, KeyError, TypeError):
    ids = set()
service = IdiodService(ids)
router = Router(name='idiod_video')


def current(message):
    raw = [m.group().rstrip('.,!?:;)]}\"\'') for m in URL_RE.finditer(message.text or '')]
    encoded = (message.text or '').encode('utf-16-le')
    for entity in (message.entities or []):
        if entity.type == 'text_link' and entity.url:
            raw.append(entity.url)
        elif entity.type == 'url':
            try:
                raw.append(encoded[entity.offset * 2:(entity.offset + entity.length) * 2]
                           .decode('utf-16-le').rstrip('.,!?:;)]}\"\''))
            except (UnicodeError, TypeError, AttributeError):
                raw.append('invalid_entity')  # Never delete uncertain source text.
    urls = list(dict.fromkeys(canonical_url(u) for u in raw if canonical_url(u)))
    return raw, urls


class IdiodFilter(Filter):
    async def __call__(self, message):
        if (not message.text or message.chat.id not in service.allowed_chats
                or message.chat.type not in {'group', 'supergroup'}
                or message.text.lstrip().startswith('/')
                or any(getattr(message, k, None) for k in ('video', 'animation', 'document', 'photo', 'audio', 'voice', 'video_note', 'sticker'))
                or (message.from_user and message.from_user.is_bot and not message.sender_chat)
                or getattr(getattr(getattr(message, 'forward_origin', None), 'sender_user', None), 'is_bot', False)
                or getattr(getattr(message, 'forward_from', None), 'is_bot', False)):
            return False
        raw, urls = current(message)
        return {'idiod_urls': urls[:3]} if urls else False


@router.message(IdiodFilter())
async def idiod_video(message, idiod_urls):
    raw, all_urls = current(message)
    author, _ = repost_author(message)
    def remove(match):
        value = match.group()
        clean = value.rstrip('.,!?:;)]}\"\'')
        return value[len(clean):] if canonical_url(clean) else value
    comment = URL_RE.sub(remove, message.text).strip()
    caption = '\n'.join(filter(None, (author, comment)))
    complete = len(caption.encode('utf-16-le')) // 2 <= 1024
    if not complete:
        caption = author
    outcomes = []
    for url in idiod_urls[:3]:
        _, author_entities = repost_author(message, source_url=canonical_url(url))
        confirmed = False
        async def send(items):
            nonlocal confirmed
            if len(items) != 1:
                raise ValueError('invalid_file')
            item = items[0]
            sent = await message.bot.send_video(
                chat_id=message.chat.id, message_thread_id=getattr(message, 'message_thread_id', None),
                video=FSInputFile(item.value) if isinstance(item.value, Path) else item.value,
                width=item.width, height=item.height, caption=caption,
                parse_mode=None, caption_entities=author_entities, supports_streaming=True)
            confirmed = bool(getattr(sent, 'message_id', None) and getattr(getattr(sent, 'video', None), 'file_id', None))
            return confirmed
        try:
            await service.handle(message.chat.id, url, send, message_id=message.message_id)
        except Exception:
            logging.warning('Idiod video operation failed message_id=%s chat=%s', message.message_id, message.chat.id)
        outcomes.append(confirmed)
    if (complete and outcomes and all(outcomes) and set(idiod_urls) == set(all_urls)
            and all(canonical_url(u) for u in raw)):
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:
            logging.warning('Idiod source deletion failed message_id=%s chat=%s', message.message_id, message.chat.id)
    raise SkipHandler

"""Current-message music matching, limited to the frozen Instagram group scope."""
import json
import os
import re
from pathlib import Path
from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import Message
from aiogram.exceptions import TelegramAPIError
from aiogram.dispatcher.event.bases import SkipHandler
from services.music_match import MatchService, MatchError, canonical_url, render, album_link

try:
    allowed_chats = json.loads((Path(__file__).resolve().parents[1] / 'config/instagram_chats.json').read_text())['allowed_chat_ids']
    if not isinstance(allowed_chats,list) or any(type(x) is not int or x >= 0 for x in allowed_chats): raise ValueError()
except (OSError,ValueError,KeyError,TypeError):
    allowed_chats = []
service = MatchService()
router = Router(name='music')


class MusicFilter(Filter):
    async def __call__(self, message: Message):
        if (os.getenv('MUSIC_ENABLED','1') != '1' or message.chat.type not in ('group','supergroup')
                or message.chat.id not in allowed_chats or not message.from_user or message.from_user.is_bot
                or any(getattr(message,field,None) for field in ('video','animation','document','photo','audio','voice','video_note','sticker'))):
            return False
        text = message.text or ''
        if text.lstrip().startswith('/'): return False
        # Choose the first CURRENT URL, including hidden text links by UTF-16 offset.
        candidates = [(len(text[:m.start()].encode('utf-16-le'))//2, m.group().rstrip('.,!?:;)')) for m in re.finditer(r'https?://[^\s<>]+',text)]
        candidates.extend((e.offset,e.url) for e in (message.entities or []) if e.type == 'text_link' and e.url)
        if not candidates: return False
        url = canonical_url(min(candidates,key=lambda x:x[0])[1])
        return {'music_url':url} if url else False


@router.message(MusicFilter())
async def music_links(message: Message, music_url: str):
    try:
        try:
            result = await service.match(music_url)
            await message.reply(render(result), parse_mode='HTML', disable_web_page_preview=False)
        except MatchError as exc:
            text = ('Сервис поиска музыки сейчас занят. Пришли ссылку ещё раз чуть позже.' if str(exc) == 'busy'
                    else 'Не удалось подтвердить ссылки на этот трек через Odesli / Songlink. Попробуй позже; поисковые ссылки не подставляю.')
            if str(exc) != 'busy' and album_link(music_url):
                text = 'Не удалось подтвердить ссылки на этот альбом через Odesli / Albumlink. Попробуй позже; ссылки на отдельные песни и поисковые ссылки не подставляю.'
            await message.reply(text)
    except TelegramAPIError:
        pass
    raise SkipHandler

"""Scoped standalone X uploads; never delete without send-level confirmations."""
import json
import logging
import re
import unicodedata
from pathlib import Path
from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import FSInputFile, InputMediaVideo, ReplyParameters
from aiogram.dispatcher.event.bases import SkipHandler
from services.x_video import XService, canonical_url, URL_RE
BASE=Path(__file__).resolve().parents[1]
try:
 ids=json.loads((BASE/'config/instagram_chats.json').read_text())['allowed_chat_ids']
 if not isinstance(ids,list) or any(type(x) is not int for x in ids):raise ValueError()
 ids=set(ids)&{-1003681962162,-1003911850060,-1001165620202}
except (OSError,ValueError,KeyError,TypeError):ids=set()
try:
 DELIVERY=json.loads((BASE/'config/x_delivery.json').read_text())
 if set(DELIVERY)!={'enabled','reply_mode','delete_source','author_caption'} or any(type(v) is not bool for v in DELIVERY.values()):raise ValueError()
except (OSError,ValueError,TypeError):DELIVERY=dict(enabled=False,reply_mode=True,delete_source=False,author_caption=True)
service=XService(ids)
router=Router(name='x_video')
MEDIA=('video','animation','document','photo','audio','voice','video_note','sticker')
HANDLED={}

def current(message):
 raw=[m.group().rstrip('.,!?:;)]}\"\'') for m in URL_RE.finditer(message.text or '')]
 raw.extend(e.url for e in (message.entities or []) if e.type=='text_link' and e.url)
 # Telegram offsets/lengths count UTF-16 code units, not Python characters.
 encoded=(message.text or '').encode('utf-16-le')
 raw.extend(encoded[e.offset*2:(e.offset+e.length)*2].decode('utf-16-le').rstrip('.,!?:;)]}\"\'')
            for e in (message.entities or []) if e.type=='url')
 urls=list(dict.fromkeys(canonical_url(u) for u in raw if canonical_url(u)))
 return raw,urls

def handled_urls(message):
 return HANDLED.get((message.chat.id,message.message_id),set())

class XFilter(Filter):
 async def __call__(self,message):
  if (not DELIVERY['enabled'] or not message.text or message.text.lstrip().startswith('/')
      or any(getattr(message,k,None) for k in MEDIA) or message.chat.type not in {'group','supergroup'}
      or message.chat.id not in service.allowed_chats or (message.from_user and message.from_user.is_bot and not message.sender_chat)):return False
  raw,urls=current(message)
  return {'x_urls':urls[:3]} if urls else False

@router.message(XFilter())
async def x_video(message,x_urls):
 raw,all_urls=current(message)
 user=message.from_user
 author=(getattr(message.sender_chat,'title','') or getattr(user,'username','') or ' '.join(filter(None,(getattr(user,'first_name',''),getattr(user,'last_name','')))))
 author=''.join(' ' if unicodedata.category(c).startswith('C') else c for c in author).replace('@','')[:80].strip()
 def remove(match):
  value=match.group();clean=value.rstrip('.,!?:;)]}\"\'')
  return value[len(clean):] if canonical_url(clean) else value
 comment=URL_RE.sub(remove,message.text).strip()
 caption='\n'.join(filter(None,(author if DELIVERY['author_caption'] else '',comment)))
 complete=len(caption.encode('utf-16-le'))//2<=1024
 if not complete:caption=author if DELIVERY['author_caption'] else ''
 common=dict(chat_id=message.chat.id,message_thread_id=getattr(message,'message_thread_id',None))
 if DELIVERY['reply_mode']:common['reply_parameters']=ReplyParameters(message_id=message.message_id)
 outcomes=[];handled=set();attempted=set()
 for url in x_urls:
  confirmed=False
  async def send(items):
   nonlocal confirmed
   if not 1<=len(items)<=10:raise ValueError('invalid_file')
   kwargs=dict(caption=caption,parse_mode=None,caption_entities=[],supports_streaming=True)
   def value(item):return FSInputFile(item.value) if isinstance(item.value,Path) else item.value
   # Once upload starts, a timeout may mean Telegram accepted the media.
   # Suppress mirror fallback without counting this as delivery confirmation.
   attempted.add(url)
   if len(items)==1:
    item=items[0]
    sent=[await message.bot.send_video(video=value(item),width=item.width,height=item.height,**common,**kwargs)]
   else:
    sent=await message.bot.send_media_group(**common,media=[InputMediaVideo(media=value(item),width=item.width,height=item.height,caption=caption if i==0 else None,parse_mode=None,caption_entities=[],supports_streaming=True) for i,item in enumerate(items)])
   confirmed=len(sent)==len(items) and all(getattr(r,'message_id',None) and getattr(getattr(r,'video',None),'file_id',None) for r in sent)
   return confirmed
  try:
   await service.handle(message.chat.id,url,send,message_id=message.message_id)
  except Exception:
   logging.warning('X video operation failed message_id=%s chat=%s',message.message_id,message.chat.id)
  outcomes.append(confirmed)
  if confirmed:handled.add(url)
 HANDLED[(message.chat.id,message.message_id)]=handled|attempted
 if len(HANDLED)>2048:HANDLED.pop(next(iter(HANDLED)))
 if (DELIVERY['delete_source'] and not DELIVERY['reply_mode'] and complete and outcomes and all(outcomes)
     and set(x_urls)==set(all_urls) and all(canonical_url(u) for u in raw)):
  try:await message.bot.delete_message(chat_id=message.chat.id,message_id=message.message_id)
  except Exception:logging.warning('X source deletion failed message_id=%s chat=%s',message.message_id,message.chat.id)
 # Mixed Instagram sources were excluded from the legacy route by the
 # registration guard. Continue unrelated handlers, including TikTok mirrors.
 raise SkipHandler

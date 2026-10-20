import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

class Network(unittest.IsolatedAsyncioTestCase):
 async def test_public_dns_pinned_private_mixed_rejected(self):
  from services.x_video import GuardResolver, validate_fetch_url
  for url in ('https://video.twimg.com/a.mp4','https://api.fxtwitter.com/status/1'):
   self.assertEqual(validate_fetch_url(url),url)
  for url in ('https://video.twimg.com.evil/a','https://a@video.twimg.com/a','https://video.twimg.com:80/a','http://video.twimg.com/a','https://127.0.0.1/a'):
   with self.assertRaises(ValueError):validate_fetch_url(url)
  for addresses,good in [(['1.1.1.1'],True),(['127.0.0.1'],False),(['1.1.1.1','10.0.0.1'],False),(['::1'],False)]:
   rows=[(2,1,6,'',(a,443)) for a in addresses]
   with patch('socket.getaddrinfo',return_value=rows):
    if good:
     result=await GuardResolver().resolve('video.twimg.com',443);self.assertEqual(result[0]['host'],'1.1.1.1');self.assertTrue(result[0]['flags'])
    else:
     with self.assertRaises(ValueError):await GuardResolver().resolve('video.twimg.com',443)
 async def test_download_validation_cleanup_and_limits(self):
  import tempfile
  from pathlib import Path
  from services.x_video import XService, MAX_FILE
  service=XService({-1})
  paths=[]
  async def fetch(session,url,path=None,limit=None,method='GET'):
   if path:
    paths.append(path);path.write_bytes(b'0000ftyp'+b'x'*16);return 24
   return {'tweet':{'media':{'videos':[{'type':'video','url':'https://video.twimg.com/a.mp4'}]}}}
  async def send(items):
   self.assertEqual(items[0].width,1066);self.assertTrue(items[0].value.exists());return True
  with patch('services.x_video.fetch',side_effect=fetch),patch('services.x_video.probe_video_dimensions',AsyncMock(return_value=(1066,1668))):
   self.assertTrue(await service.handle(-1,'https://x.com/u/status/1',send,message_id=1))
  self.assertTrue(paths);self.assertTrue(all(not p.exists() for p in paths))
  self.assertEqual(service.pending,0)
 async def test_head_reports_oversize_for_quality_selection(self):
  from services.x_video import fetch, MAX_FILE
  response=NS(status=200,content_length=MAX_FILE+1)
  class Context:
   async def __aenter__(self):return response
   async def __aexit__(self,*args):pass
  session=NS(request=lambda *a,**kw:Context())
  self.assertEqual(await fetch(session,'https://video.twimg.com/a.mp4',limit=MAX_FILE,method='HEAD'),MAX_FILE+1)
 async def test_mixed_photo_inventory_not_claimed_complete(self):
  from services.x_video import XService
  service=XService({-1});send=AsyncMock(return_value=True)
  data={'tweet':{'media':{'all':[{'type':'photo'},{'type':'video','url':'https://video.twimg.com/a.mp4'}],'videos':[{'url':'https://video.twimg.com/a.mp4'}]}}}
  with patch('services.x_video.fetch',AsyncMock(return_value=data)):
   with self.assertRaises(ValueError):await service.handle(-1,'https://x.com/u/status/1',send,message_id=2)
  send.assert_not_awaited()
 async def test_service_failure_cancel_cleanup_no_send_retry(self):
  import asyncio
  from services.x_video import XService
  for failure in (ValueError('private'),asyncio.CancelledError()):
   service=XService({-1});paths=[];send=AsyncMock(side_effect=failure)
   async def fake(session,url,path=None,limit=None,method='GET'):
    if path:paths.append(path);path.write_bytes(b'0000ftyp00000000');return 16
    if method=='HEAD':return 16
    return {'tweet':{'media':{'videos':[{'url':'https://video.twimg.com/a.mp4'}]}}}
   with patch('services.x_video.fetch',side_effect=fake),patch('services.x_video.probe_video_dimensions',AsyncMock(return_value=(1920,1080))):
    with self.assertRaises(type(failure)):await service.handle(-1,'https://x.com/u/status/1',send,message_id=1)
    self.assertFalse(await service.handle(-1,'https://x.com/u/status/1',send,message_id=1))
   send.assert_awaited_once();self.assertEqual(service.pending,0);self.assertFalse(service.chats);self.assertTrue(all(not p.exists() for p in paths))
 async def test_queue_capacity_and_cancel_release(self):
  import asyncio
  from services.x_video import XService
  service=XService({-1,-2,-3});gate=asyncio.Event()
  async def blocked(*args,**kw):await gate.wait()
  with patch('services.x_video.fetch',side_effect=blocked):
   tasks=[asyncio.create_task(service.handle(-1,'https://x.com/u/status/%s'%i,AsyncMock(),message_id=i)) for i in range(10)]
   for _ in range(10):await asyncio.sleep(0)
   self.assertEqual(service.pending,10)
   with self.assertRaises(ValueError):await service.handle(-1,'https://x.com/u/status/99',AsyncMock(),message_id=99)
   for t in tasks:t.cancel()
   await asyncio.gather(*tasks,return_exceptions=True)
   self.assertEqual(service.pending,0);self.assertFalse(service.chats)
 async def test_quality_selects_highest_fitting(self):
  from services.x_video import XService,MAX_FILE
  service=XService({-1});downloaded=[]
  async def fake(session,url,path=None,limit=None,method='GET'):
   if path:downloaded.append(url);path.write_bytes(b'0000ftyp00000000');return 16
   if method=='HEAD':return MAX_FILE+1 if url.endswith('high.mp4') else 16
   return {'tweet':{'media':{'videos':[{'url':'https://video.twimg.com/high.mp4','formats':[{'url':'https://video.twimg.com/high.mp4','bitrate':999},{'url':'https://video.twimg.com/medium.mp4','bitrate':555},{'url':'https://video.twimg.com/low.mp4','bitrate':111}]}]}}}
  with patch('services.x_video.fetch',side_effect=fake),patch('services.x_video.probe_video_dimensions',AsyncMock(return_value=(1280,720))):
   await service.handle(-1,'https://x.com/u/status/1',AsyncMock(return_value=True),message_id=1)
  self.assertEqual(downloaded,['https://video.twimg.com/medium.mp4'])
 async def test_redirect_and_large_json_reject_before_read(self):
  from services.x_video import fetch
  for status,size in [(302,0),(200,1024*1024+1)]:
   response=NS(status=status,content_length=size,content=NS())
   class Context:
    async def __aenter__(self):return response
    async def __aexit__(self,*args):pass
   calls=[]
   def request(*a,**kw):calls.append(kw);return Context()
   with self.assertRaises(ValueError):await fetch(NS(request=request),'https://api.fxtwitter.com/status/1')
   self.assertFalse(calls[0]['allow_redirects'])
 async def test_stream_limit(self):
  from services.x_video import bounded_read
  class Content:
   async def iter_chunked(self,n):
    yield b'a'*5;yield b'b'*6
  with self.assertRaises(ValueError):await bounded_read(Content(),10)

class Delivery(unittest.IsolatedAsyncioTestCase):
 def message(self,text='коммент https://x.com/u/status/1',**kw):
  bot=NS(send_video=AsyncMock(return_value=NS(video=NS(file_id='v'),message_id=50)),send_media_group=AsyncMock(),delete_message=AsyncMock())
  m=NS(bot=bot,chat=NS(id=-1003911850060,type='supergroup'),message_id=11,message_thread_id=27,text=text,entities=[],from_user=NS(username='alice',is_bot=False),sender_chat=None,reply=AsyncMock())
  m.__dict__.update(kw);return m
 async def run_handler(self,m,mode='ok'):
  from handlers import x_video as h
  from services.x_video import Item
  events=[]
  async def send_video(**kw):events.append('send');return NS(video=NS(file_id='v'),message_id=50)
  m.bot.send_video.side_effect=send_video
  async def handle(chat,url,send,**kw):
   if mode=='noop':return True
   if mode=='fail' or mode=='partial' and url.endswith('/2'):raise ValueError()
   return await send([Item('fileid',1066,1668)])
  from aiogram.dispatcher.event.bases import SkipHandler
  with patch.object(h.service,'handle',side_effect=handle):
   try:await h.x_video(m,**(await h.XFilter()(m)))
   except SkipHandler:pass
  return events
 async def test_all_confirmed_standalone_delete_dimensions_caption(self):
  m=self.message('коммент https://x.com/u/status/1 https://twitter.com/u/status/2')
  events=await self.run_handler(m)
  self.assertEqual(events,['send','send']);m.bot.delete_message.assert_awaited_once()
  args=m.bot.send_video.call_args.kwargs
  self.assertEqual((args['width'],args['height']),(1066,1668));self.assertEqual(args['caption'],'alice\nкоммент')
  self.assertIsNone(args['parse_mode']);self.assertEqual(args['caption_entities'],[])
  self.assertNotIn('reply_parameters',args);self.assertEqual(args['message_thread_id'],27)
 async def test_fail_noop_partial_mixed_overflow_long_preserve(self):
  for mode,text in [('fail','https://x.com/u/status/1'),('noop','https://x.com/u/status/1'),('partial','https://x.com/u/status/1 https://x.com/u/status/2'),('ok','https://x.com/u/status/1 https://example.com/a'),('ok','https://x.com/u/status/1 https://instagram.com/p/a/'),('ok',' '.join('https://x.com/u/status/%s'%i for i in range(4))),('ok','😀'*1100+' https://x.com/u/status/1')]:
   m=self.message(text);await self.run_handler(m,mode);m.bot.delete_message.assert_not_awaited()
 async def test_scope_caption_media_skip(self):
  from handlers.x_video import XFilter
  for m in (self.message(video=object()),self.message(chat=NS(id=-123,type='supergroup')),self.message(text=None,caption='https://x.com/u/status/1')):
   self.assertFalse(await XFilter()(m))
 async def test_album_confirmation_and_dimensions(self):
  from handlers import x_video as h
  from services.x_video import Item
  from aiogram.dispatcher.event.bases import SkipHandler
  for count in (1,2):
   m=self.message();m.bot.send_media_group.return_value=[NS(video=NS(file_id='v'),message_id=i+1) for i in range(count)]
   async def handle(chat,url,send,**kw):return await send([Item('a',1066,1668),Item('b',1920,1080)])
   with patch.object(h.service,'handle',side_effect=handle):
    with self.assertRaises(SkipHandler):await h.x_video(m,x_urls=['https://x.com/u/status/1'])
   media=m.bot.send_media_group.call_args.kwargs['media']
   self.assertEqual((media[0].width,media[0].height),(1066,1668));self.assertEqual((media[1].width,media[1].height),(1920,1080))
   self.assertIsNone(media[1].caption)
   if count==2:m.bot.delete_message.assert_awaited_once()
   else:m.bot.delete_message.assert_not_awaited()
 async def test_hidden_fourth_url_keeps_source(self):
  m=self.message('labels',entities=[NS(type='text_link',url='https://x.com/u/status/%s'%i) for i in range(4)])
  await self.run_handler(m);self.assertEqual(m.bot.send_video.await_count,3);m.bot.delete_message.assert_not_awaited()
 async def test_delete_failure_does_not_resend(self):
  m=self.message();m.bot.delete_message.side_effect=RuntimeError('private secret')
  with self.assertLogs(level='WARNING') as logs:await self.run_handler(m)
  m.bot.send_video.assert_awaited_once();m.bot.delete_message.assert_awaited_once()
  self.assertNotIn('private secret',' '.join(logs.output))
 async def test_hidden_links_supported_unhandled_entity_preserves(self):
  m=self.message('смотри',entities=[NS(type='text_link',url='https://twitter.com/u/status/1?s=1')])
  await self.run_handler(m);m.bot.delete_message.assert_awaited_once()
  m=self.message(entities=[NS(type='text_link',url='https://example.com/a')])
  await self.run_handler(m);m.bot.delete_message.assert_not_awaited()
 async def test_mixed_instagram_x_both_send_and_source_remains(self):
  from handlers import instagram as ig
  from handlers import instagram_router
  from aiogram.dispatcher.event.bases import SkipHandler
  m=self.message('https://www.instagram.com/reel/ABC/ https://x.com/u/status/1')
  async def handle(chat,url,send,**kw):
   return await send([ig.MediaItem('video','ig_file_id',1066,1668)])
  with patch.object(ig.service,'handle',side_effect=handle):
   with self.assertRaises(SkipHandler):
    await ig.instagram_video(m,instagram_urls=['https://www.instagram.com/reel/ABC/'])
  m.bot.delete_message.assert_not_awaited()
  await self.run_handler(m)
  self.assertEqual(m.bot.send_video.await_count,2)
  m.bot.delete_message.assert_not_awaited()
  self.assertFalse(instagram_router.message._handler.filters)
 async def test_telegram_bare_url_entity_preserves_original_with_utf16_offset(self):
  text='😀 https://x.com/u/status/1 example.com'
  offset=len(text[:text.index('example.com')].encode('utf-16-le'))//2
  m=self.message(text,entities=[NS(type='url',offset=offset,length=11)])
  await self.run_handler(m)
  m.bot.send_video.assert_awaited_once()
  m.bot.delete_message.assert_not_awaited()
 async def test_ambiguous_send_suppresses_mirror_without_deleting(self):
  import asyncio
  from handlers import x_video as h
  from handlers.link_fix import fix_links_in_text
  from services.x_video import Item
  from aiogram.dispatcher.event.bases import SkipHandler
  m=self.message('https://x.com/u/status/9999')
  m.bot.send_video.side_effect=asyncio.TimeoutError()
  async def handle(chat,url,send,**kw):return await send([Item('a',1066,1668)])
  with patch.object(h.service,'handle',side_effect=handle):
   with self.assertRaises(SkipHandler):await h.x_video(m,x_urls=['https://x.com/u/status/9999'])
  await fix_links_in_text(m)
  m.bot.send_video.assert_awaited_once()
  m.bot.delete_message.assert_not_awaited()
  m.reply.assert_not_awaited()
 async def test_cancellation_preserves_source(self):
  import asyncio
  from handlers import x_video as h
  m=self.message()
  with patch.object(h.service,'handle',AsyncMock(side_effect=asyncio.CancelledError())):
   with self.assertRaises(asyncio.CancelledError):await h.x_video(m,x_urls=['https://x.com/u/status/1'])
  m.bot.delete_message.assert_not_awaited()
 async def test_suppress_only_delivered_x_keep_tiktok(self):
  from handlers.link_fix import fix_links_in_text
  m=self.message('https://x.com/u/status/1 https://tiktok.com/a')
  await self.run_handler(m);await fix_links_in_text(m)
  self.assertEqual(m.reply.call_args.args[0],'https://www.vxtiktok.com/a')

class URLs(unittest.TestCase):
 def test_exact_canonical_aliases(self):
  from services.x_video import canonical_url
  for host in ('x.com','www.x.com','mobile.x.com','twitter.com','www.twitter.com','mobile.twitter.com'):
   self.assertEqual(canonical_url('https://'+host+'/mristo/status/2112063963429052761?s=52'),'https://x.com/mristo/status/2112063963429052761')
  for url in ('http://x.com/u/status/1','https://x.com.evil/u/status/1','https://a@x.com/u/status/1','https://x.com:444/u/status/1','https://x.com/u/status/abc'):
   self.assertIsNone(canonical_url(url))

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

URL = 'https://idiod.video/k5r9yf.mp4'

def setUpModule():
 from handlers import idiod_video, instagram, x_video
 from services import idiod_video as service
 root=Path(__file__).resolve().parents[1]
 for module in (idiod_video,instagram,x_video,service):
  if root not in Path(module.__file__).resolve().parents:
   raise AssertionError('Non-stage import: '+module.__file__)

class URLs(unittest.TestCase):
 def test_exact_sample_and_unsafe_urls(self):
  from services import idiod_video as s
  self.assertEqual(s.canonical_url(URL), URL)
  for value in ('http://idiod.video/a.mp4','https://idiod.video.evil/a.mp4','https://a@idiod.video/a.mp4','https://idiod.video:444/a.mp4','https://idiod.video/x/a.mp4','https://idiod.video/%61.mp4','https://idiod.video/a.mp4?x=1','https://idiod.video/a.mp4#x','https://idiod.video/a.mp4\n','https://idiod.video\\@evil/a.mp4'):
   with self.subTest(value=value):self.assertIsNone(s.canonical_url(value))

class Service(unittest.IsolatedAsyncioTestCase):
 async def test_wait_and_active_timeouts_release_capacity(self):
  from services import idiod_video as s
  real_wait_for=asyncio.wait_for
  for phase in ('queue','active'):
   with self.subTest(phase=phase):
    service=s.IdiodService({-1});gate=asyncio.Event();seen=[]
    if phase=='queue':
     service.active=asyncio.Semaphore(2)
     await service.active.acquire();await service.active.acquire()
    async def bounded(awaitable,timeout):
     seen.append(timeout)
     return await real_wait_for(awaitable,.01)
    async def blocked(*args):await gate.wait()
    with patch.object(s.asyncio,'wait_for',side_effect=bounded),patch.object(service,'_download_send',side_effect=blocked) as work:
     with self.assertRaises(asyncio.TimeoutError):await service.handle(-1,URL,AsyncMock(),message_id=1)
    self.assertEqual(seen,[900] if phase=='queue' else [900,90])
    self.assertEqual(work.await_count,0 if phase=='queue' else 1)
    self.assertEqual(service.pending,0);self.assertFalse(service.chats);self.assertFalse(service.locks);self.assertFalse(service.inflight)
    if phase=='queue':service.active.release();service.active.release()
    self.assertEqual(service.active._value,2)
    with patch.object(service,'_download_send',AsyncMock(return_value=True)):
     self.assertTrue(await service.handle(-1,URL,AsyncMock(),message_id=2))

 async def test_ambiguous_receipt_prevents_same_update_retry(self):
  from services import idiod_video as s
  service=s.IdiodService({-1})
  callback=AsyncMock(side_effect=asyncio.TimeoutError())
  async def work(url,send):return await send([])
  with patch.object(service,'_download_send',side_effect=work):
   with self.assertRaises(asyncio.TimeoutError):await service.handle(-1,URL,callback,message_id=7)
   self.assertFalse(await service.handle(-1,URL,callback,message_id=7))
  callback.assert_awaited_once()
 async def test_admission_caps_and_cancel_release(self):
  from services import idiod_video as s
  service=s.IdiodService({-1,-2,-3});gate=asyncio.Event()
  async def blocked(*args):await gate.wait()
  with patch.object(service,'_download_send',side_effect=blocked):
   tasks=[asyncio.create_task(service.handle(chat,'https://idiod.video/a%s.mp4'%i,AsyncMock(),message_id=i)) for i,chat in enumerate([-1]*10+[-2]*10)]
   try:
    for _ in range(15):await asyncio.sleep(0)
    self.assertEqual(service.pending,20)
    with self.assertRaisesRegex(ValueError,'busy'):await asyncio.wait_for(service.handle(-3,URL,AsyncMock()),.1)
    with self.assertRaisesRegex(ValueError,'busy'):await service.handle(-1,URL,AsyncMock())
   finally:
    for task in tasks:task.cancel()
    await asyncio.gather(*tasks,return_exceptions=True)
  self.assertEqual(service.pending,0);self.assertFalse(service.chats);self.assertFalse(service.locks);self.assertFalse(service.inflight)
 async def test_fifo_global_two_chat_one_inflight_dedup_and_release(self):
  from services import idiod_video as s
  service=s.IdiodService({-1,-2,-3});gate=asyncio.Event();started=[];running=set();maximum=0
  async def work(url,send):
   nonlocal maximum
   started.append(url);running.add(url);maximum=max(maximum,len(running))
   await gate.wait();running.remove(url);return True
  with patch.object(service,'_download_send',side_effect=work):
   tasks=[asyncio.create_task(service.handle(chat,'https://idiod.video/%s.mp4'%name,AsyncMock(),message_id=i)) for i,(chat,name) in enumerate([(-1,'a'),(-1,'b'),(-1,'c'),(-2,'d'),(-3,'e')])]
   for _ in range(15):await asyncio.sleep(0)
   self.assertEqual(started,['https://idiod.video/a.mp4','https://idiod.video/d.mp4'])
   self.assertFalse(await service.handle(-1,'https://idiod.video/a.mp4',AsyncMock(),message_id=99))
   gate.set();self.assertTrue(all(await asyncio.gather(*tasks)))
  self.assertEqual(maximum,2)
  self.assertLess(started.index('https://idiod.video/b.mp4'),started.index('https://idiod.video/c.mp4'))
  self.assertEqual(service.pending,0);self.assertFalse(service.chats);self.assertFalse(service.locks);self.assertFalse(service.inflight)
 async def test_download_probe_send_cleanup_and_ambiguous_no_retry(self):
  from services import idiod_video as s
  for failure in (None,asyncio.TimeoutError(),asyncio.CancelledError()):
   service=s.IdiodService({-1});paths=[]
   async def download(session,url,path,limit=s.MAX_FILE):
    paths.append(path);path.write_bytes(b'\x00\x00\x00\x18ftypisom'+b'\x00'*12);return 24
   async def send(items):
    self.assertTrue(items[0].value.exists());self.assertEqual((items[0].width,items[0].height),(1280,720))
    if failure:raise failure
    return True
   callback=AsyncMock(side_effect=send)
   with patch.object(s,'fetch',side_effect=download),patch.object(s,'probe_video_dimensions',AsyncMock(return_value=(1280,720))),patch.object(s.aiohttp,'ClientSession',wraps=s.aiohttp.ClientSession) as session:
    if failure:
     with self.assertRaises(type(failure)):await service.handle(-1,URL,callback,message_id=1)
    else:self.assertTrue(await service.handle(-1,URL,callback,message_id=1))
    kwargs=session.call_args.kwargs
    self.assertFalse(kwargs['trust_env']);self.assertFalse(kwargs['auto_decompress'])
    self.assertIsInstance(kwargs['cookie_jar'],s.aiohttp.DummyCookieJar)
    self.assertNotIn('auth',kwargs)
   callback.assert_awaited_once();self.assertTrue(all(not p.exists() for p in paths))

class Delivery(unittest.IsolatedAsyncioTestCase):
 def message(self,text='коммент '+URL,**kw):
  bot=NS(send_video=AsyncMock(return_value=NS(video=NS(file_id='v'),message_id=50)),delete_message=AsyncMock())
  message=NS(bot=bot,chat=NS(id=-1003911850060,type='supergroup'),message_id=11,message_thread_id=27,text=text,entities=[],from_user=NS(username='alice',is_bot=False),sender_chat=None,reply=AsyncMock(),caption_entities=[])
  message.__dict__.update(kw);return message
 async def test_scope_current_only_media_bot_forwards_and_utf16_links(self):
  from handlers import idiod_video as h
  for kwargs in [dict(video=object()),dict(animation=object()),dict(document=object()),dict(photo=[1]),dict(audio=object()),dict(voice=object()),dict(video_note=object()),dict(sticker=object()),dict(text='/cmd '+URL),dict(chat=NS(id=-1,type='supergroup')),dict(chat=NS(id=-1003911850060,type='private')),dict(from_user=NS(is_bot=True)),dict(forward_origin=NS(sender_user=NS(is_bot=True))),dict(text='спасибо',reply_to_message=NS(text=URL)),dict(text=None,caption=URL)]:
   self.assertFalse(await h.IdiodFilter()(self.message(**kwargs)),kwargs)
  self.assertTrue(await h.IdiodFilter()(self.message(forward_origin=NS(sender_user=NS(is_bot=False)))))
  message=self.message('😀 смотри',entities=[NS(type='text_link',url=URL)])
  self.assertEqual((await h.IdiodFilter()(message))['idiod_urls'],[URL])
  text='😀 '+URL+' example.com'
  start=len(('😀 '+URL+' ').encode('utf-16-le'))//2
  message=self.message(text,entities=[NS(type='url',offset=start,length=11)])
  raw,urls=h.current(message)
  self.assertIn('example.com',raw);self.assertEqual(urls,[URL])

 async def test_registered_router_standalone_plain_caption_topic_send_then_delete(self):
  from handlers import all_routers, idiod_video as h
  from services.idiod_video import Item
  self.assertIn(h.router,all_routers())
  self.assertEqual(Path(h.__file__).resolve().parents[1],Path(__file__).resolve().parents[1])
  message=self.message();events=[]
  async def send_video(**kwargs):events.append('send');return NS(video=NS(file_id='v'),message_id=50)
  async def delete(**kwargs):events.append('delete')
  message.bot.send_video.side_effect=send_video;message.bot.delete_message.side_effect=delete
  async def handle(chat,url,send,**kwargs):return await send([Item('fileid',1280,720)])
  with patch.object(h.service,'handle',side_effect=handle):
   await h.router.propagate_event(update_type='message',event=message)
  self.assertEqual(events,['send','delete'])
  args=message.bot.send_video.call_args.kwargs
  self.assertEqual(args['caption'],'alice\nкоммент');self.assertEqual(args['message_thread_id'],27)
  self.assertEqual((args['width'],args['height']),(1280,720))
  self.assertIsNone(args['parse_mode'])
  self.assertEqual([(e.type,e.offset,e.length,e.url,e.user) for e in args['caption_entities']], [('text_link',0,5,URL,None)])
  self.assertNotIn('reply_parameters',args);self.assertNotIn('reply_to_message_id',args)

 async def test_failure_partial_overflow_mixed_long_unconfirmed_keep_source(self):
  from handlers import idiod_video as h
  from services.idiod_video import Item
  cases=[('fail',URL),('busy',URL),('noop',URL),('unconfirmed',URL),('partial',URL+' https://idiod.video/b.mp4'),('ok',' '.join('https://idiod.video/a%s.mp4'%i for i in range(4))),('ok',URL+' https://example.com/a'),('ok',URL+' https://x.com/u/status/1'),('ok',URL+' https://instagram.com/p/ABC/'),('ok','😀'*1100+' '+URL)]
  for mode,text in cases:
   with self.subTest(mode=mode,text=text[:70]):
    message=self.message(text)
    if mode=='unconfirmed':message.bot.send_video.return_value=NS(message_id=50,video=None)
    async def handle(chat,url,send,**kwargs):
     if mode in ('fail','busy') or mode=='partial' and url.endswith('/b.mp4'):raise ValueError(mode)
     if mode=='noop':return True
     return await send([Item('fileid',1280,720)])
    with patch.object(h.service,'handle',side_effect=handle) as work:
     await h.router.propagate_event(update_type='message',event=message)
    self.assertLessEqual(work.await_count,3)
    if mode=='ok':self.assertGreater(message.bot.send_video.await_count,0)
    message.bot.delete_message.assert_not_awaited();message.reply.assert_not_awaited()

 async def test_cancellation_keeps_source_delete_failure_never_resends(self):
  from handlers import idiod_video as h
  from services.idiod_video import Item
  message=self.message()
  with patch.object(h.service,'handle',AsyncMock(side_effect=asyncio.CancelledError())):
   with self.assertRaises(asyncio.CancelledError):await h.router.propagate_event(update_type='message',event=message)
  message.bot.delete_message.assert_not_awaited()
  async def handle(chat,url,send,**kwargs):return await send([Item('fileid',1280,720)])
  message.bot.delete_message.side_effect=RuntimeError('private secret')
  with patch.object(h.service,'handle',side_effect=handle),self.assertLogs(level='WARNING') as logs:
   await h.router.propagate_event(update_type='message',event=message)
  message.bot.send_video.assert_awaited_once();message.bot.delete_message.assert_awaited_once()
  self.assertNotIn('private secret',' '.join(logs.output))

 async def test_mixed_instagram_idiod_real_routers_both_send_preserve_source(self):
  from handlers import instagram as ig, idiod_video as h, x_video as x
  from services.idiod_video import Item
  for extra in ('', ' https://x.com/u/status/1'):
   with self.subTest(extra=extra):
    message=self.message('https://www.instagram.com/reel/ABC/ '+URL+extra)
    async def ig_handle(chat,url,send,**kw):return await send([ig.MediaItem('video','ig_file',1280,720)])
    async def idiod_handle(chat,url,send,**kw):return await send([Item('idiod_file',1280,720)])
    from services.x_video import Item as XItem
    async def x_handle(chat,url,send,**kw):return await send([XItem('x_file',1280,720)])
    with patch.object(ig.service,'handle',side_effect=ig_handle),patch.object(h.service,'handle',side_effect=idiod_handle),patch.object(x.service,'handle',side_effect=x_handle),patch.dict(ig.DELIVERY,reply_mode=False,delete_source=True):
     for router in (ig.router,x.router,h.router):
      await router.propagate_event(update_type='message',event=message)
    self.assertEqual(message.bot.send_video.await_count,3 if extra else 2)
    message.bot.delete_message.assert_not_awaited()

class Network(unittest.IsolatedAsyncioTestCase):
 async def test_guarded_stream_response_limits_and_no_redirect(self):
  import tempfile
  from services import idiod_video as s
  class Content:
   async def iter_chunked(self,n):
    yield b'a'*5;yield b'b'*6
  class Context:
   async def __aenter__(self):return response
   async def __aexit__(self,*args):pass
  calls=[]
  def request(*args,**kw):calls.append(kw);return Context()
  session=NS(get=request)
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'a.mp4'
   for status,mime,size,limit in [(302,'video/mp4',0,20),(200,'text/html',0,20),(200,'video/mp4',21,20),(200,'video/mp4',None,10)]:
    response=NS(status=status,content_length=size,headers={'Content-Type':mime},content=Content())
    with self.assertRaises(ValueError):await s.fetch(session,URL,path,limit)
   response=NS(status=200,content_length=11,headers={'Content-Type':'video/mp4'},content=Content())
   self.assertEqual(await s.fetch(session,URL,path,20),11)
   self.assertEqual(path.read_bytes(),b'aaaaabbbbbb')
   self.assertTrue(all(c['allow_redirects'] is False for c in calls))
   response.content_length=12
   with self.assertRaises(ValueError):await s.fetch(session,URL,path,20)
 async def test_dns_pins_all_answers_and_rejects_mixed(self):
  from services import idiod_video as s
  for addresses, good in [(['1.1.1.1'],True),(['1.1.1.1','10.0.0.1'],False),(['::1'],False),(['224.0.0.1'],False),([],False)]:
   rows=[(2,1,6,'',(a,443)) for a in addresses]
   with patch('socket.getaddrinfo',return_value=rows) as dns:
    if good:
     result=await s.GuardResolver().resolve('idiod.video')
     self.assertEqual(result[0]['host'],'1.1.1.1')
     self.assertTrue(result[0]['flags'])
     self.assertEqual(dns.call_args.args[2],s.socket.AF_UNSPEC)
    else:
     with self.assertRaises(ValueError):await s.GuardResolver().resolve('idiod.video')
  for host,port in [('evil',443),('idiod.video',80)]:
   with self.assertRaises(ValueError):await s.GuardResolver().resolve(host,port)

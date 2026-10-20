import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, PropertyMock
from aiogram.types import Message
from aiogram.dispatcher.event.bases import SkipHandler

class DimensionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # New delivery policy uses explicit Bot APIs, never reply shortcuts.
        self.bot = SimpleNamespace(send_video=AsyncMock(), send_photo=AsyncMock(),
                                   send_media_group=AsyncMock(), delete_message=AsyncMock())
        binding = patch.object(Message, 'bot', new_callable=PropertyMock, return_value=self.bot)
        binding.start(); self.addCleanup(binding.stop)

    async def test_local_video_standalone_dimensions(self):
        from handlers.instagram import instagram_video, service
        msg = Message.model_validate({'message_id':11,'date':1700000000,'chat':{'id':-1003911850060,'type':'supergroup'},'text':'https://www.instagram.com/reel/abc/'})
        async def handle(chat,url,send,message_id=None):
            await send([Path('/root/bots/instagram-verification/DeHGTtux7SL.mp4')])
        with patch.object(service,'handle',side_effect=handle), patch.object(self.bot,'send_video',new_callable=AsyncMock,return_value=SimpleNamespace(video=SimpleNamespace(file_id='id'))) as reply:
            with self.assertRaises(SkipHandler): await instagram_video(msg,'https://www.instagram.com/reel/abc/')
            self.assertEqual((reply.call_args.kwargs.get('width'),reply.call_args.kwargs.get('height')),(720,1280))

    async def test_mixed_album_and_cache_preserve_geometry(self):
        import tempfile
        import json
        from handlers.instagram import instagram_video, service
        from services.instagram_download import DownloadService, MediaItem
        msg = Message.model_validate({'message_id':11,'date':1700000000,'chat':{'id':-1003911850060,'type':'supergroup'}})
        async def runner(url, directory):
            (directory/'v.mp4').write_bytes(b'\x00\x00\x00\x20ftyp' + b'x'*20)
        local = DownloadService(Path('/tmp'), [msg.chat.id], runner=runner)
        video = SimpleNamespace(video=SimpleNamespace(file_id='video-id'),photo=None)
        photo = SimpleNamespace(photo=[SimpleNamespace(file_id='photo-id')],video=None)
        with patch.object(service,'handle',side_effect=local.handle), patch('handlers.instagram.probe_video_dimensions',new_callable=AsyncMock,return_value=(720,1280)) as probe, patch.object(self.bot,'send_video',new_callable=AsyncMock,return_value=video) as reply:
            for _ in range(2):
                with self.assertRaises(SkipHandler): await instagram_video(msg,'https://www.instagram.com/reel/abc/')
            self.assertEqual(probe.await_count,1)
            for call in reply.call_args_list:
                self.assertEqual((call.kwargs['width'],call.kwargs['height']),(720,1280))
            self.assertEqual(local.cache['https://www.instagram.com/reel/abc/'][1],[MediaItem('video','video-id',720,1280)])
        items = [MediaItem('photo','photo-id'),MediaItem('video','video-id',1280,720)]
        async def album_handle(chat,url,send,message_id=None): await send(items)
        with patch.object(service,'handle',side_effect=album_handle), patch('handlers.instagram.probe_video_dimensions',new_callable=AsyncMock) as probe, patch.object(self.bot,'send_media_group',new_callable=AsyncMock,return_value=[photo,video]) as reply:
            with self.assertRaises(SkipHandler): await instagram_video(msg,'https://www.instagram.com/reel/abc/')
            media=reply.call_args.kwargs['media']
            self.assertEqual((media[1].width,media[1].height,media[1].supports_streaming),(1280,720,True))
            self.assertFalse(hasattr(media[0],'width'))
            probe.assert_not_awaited()

    async def test_local_mixed_album_and_failed_probe_fallback(self):
        from handlers.instagram import instagram_video, service
        from services.instagram_download import MediaItem
        msg=Message.model_validate({'message_id':11,'date':1700000000,'chat':{'id':-1003911850060,'type':'supergroup'}})
        photo=SimpleNamespace(photo=[SimpleNamespace(file_id='photo-id')],video=None)
        video=SimpleNamespace(video=SimpleNamespace(file_id='video-id'),photo=None)
        for dims in [(720,1280),None]:
            async def handle(chat,url,send,message_id=None):
                await send([MediaItem('photo',Path('/tmp/p.jpg')),MediaItem('video',Path('/tmp/v.mp4'))])
            with patch.object(service,'handle',side_effect=handle),patch('handlers.instagram.probe_video_dimensions',new_callable=AsyncMock,return_value=dims) as probe,patch.object(self.bot,'send_media_group',new_callable=AsyncMock,return_value=[photo,video]) as reply:
                with self.assertRaises(SkipHandler): await instagram_video(msg,'https://www.instagram.com/reel/abc/')
                media=reply.call_args.kwargs['media']
                self.assertEqual((media[1].width,media[1].height),dims or (None,None))
                self.assertTrue(media[1].supports_streaming)
                probe.assert_awaited_once_with(Path('/tmp/v.mp4'))

    async def test_stale_file_id_omits_metadata_without_probe(self):
        from handlers.instagram import instagram_video,service
        from services.instagram_download import MediaItem
        msg=Message.model_validate({'message_id':11,'date':1700000000,'chat':{'id':-1003911850060,'type':'supergroup'}})
        async def handle(chat,url,send,message_id=None): await send([MediaItem('video','old-id')])
        with patch.object(service,'handle',side_effect=handle),patch('handlers.instagram.probe_video_dimensions',new_callable=AsyncMock) as probe,patch.object(self.bot,'send_video',new_callable=AsyncMock,return_value=SimpleNamespace(video=SimpleNamespace(file_id='new'))) as reply:
            with self.assertRaises(SkipHandler): await instagram_video(msg,'https://www.instagram.com/reel/abc/')
            self.assertNotIn('width',reply.call_args.kwargs)
            self.assertNotIn('height',reply.call_args.kwargs)
            probe.assert_not_awaited()

    async def test_probe_timeout_and_cancellation_reap(self):
        import asyncio
        from services import instagram_video_metadata as metadata
        for cancel in (False,True):
            killed=asyncio.Event()
            class Process:
                returncode=None
                def __init__(self): self.stdout=SimpleNamespace(read=self.read)
                async def read(self,n): await killed.wait();return b''
                def kill(self): self.returncode=-9;killed.set()
                async def wait(self): await killed.wait();return -9
            process=Process()
            with patch.object(metadata.asyncio,'create_subprocess_exec',new_callable=AsyncMock,return_value=process) as create,patch.object(metadata,'PROBE_TIMEOUT',0.01):
                task=asyncio.create_task(metadata.probe_video_dimensions(Path('/tmp/v.mp4')))
                if cancel:
                    await asyncio.sleep(0.001);task.cancel()
                    with self.assertRaises(asyncio.CancelledError): await task
                else: self.assertIsNone(await task)
                self.assertTrue(killed.is_set())
                self.assertEqual(create.call_args.args[:9],('ffprobe','-v','error','-select_streams','v:0','-show_streams','-of','json','/tmp/v.mp4'))

    async def test_probe_output_cap_and_invalid_json_safe(self):
        import json
        from services import instagram_video_metadata as metadata
        for payload in [b'x'*(metadata.MAX_OUTPUT+1),b'{secret-CANARY}',b'\xff',json.dumps({'streams':[{'width':0,'height':1280}]}).encode()]:
            class Process:
                returncode=None
                def __init__(self): self.buffer=payload;self.stdout=SimpleNamespace(read=self.read);self.killed=False
                async def read(self,n):
                    result=self.buffer[:n];self.buffer=self.buffer[n:];return result
                async def wait(self): self.returncode=0;return 0
                def kill(self): self.killed=True;self.returncode=-9
            process=Process()
            with patch.object(metadata.asyncio,'create_subprocess_exec',new_callable=AsyncMock,return_value=process),self.assertLogs(level='WARNING') as logs:
                self.assertIsNone(await metadata.probe_video_dimensions(Path('/tmp/v.mp4')))
            self.assertNotIn('CANARY',' '.join(logs.output))
            if len(payload)>metadata.MAX_OUTPUT:self.assertTrue(process.killed)

class GeometryTests(unittest.TestCase):
    def test_rotation_sar_dar_and_bounds(self):
        from services.instagram_video_metadata import display_dimensions
        for rotation,expected in [(0,(720,1280)),(-90,(1280,720)),(180,(720,1280)),(270,(1280,720))]:
            self.assertEqual(display_dimensions({'streams':[{'width':720,'height':1280,'side_data_list':[{'rotation':rotation}]}]}),expected)
        self.assertEqual(display_dimensions({'streams':[{'width':720,'height':576,'sample_aspect_ratio':'16:15'}]}),(768,576))
        self.assertEqual(display_dimensions({'streams':[{'width':720,'height':576,'display_aspect_ratio':'4:3','tags':{'rotate':'-90'}}]}),(576,768))
        self.assertEqual(display_dimensions({'streams':[{'width':8192,'height':1}]}),(8192,1))
        for extra in [{'width':0},{'height':-1},{'width':8193},{'width':True},{'sample_aspect_ratio':'1:0'},{'sample_aspect_ratio':'__import__("os")'},{'display_aspect_ratio':'1:999999999'},{'tags':{'rotate':'90;secret'}},{'tags':{'rotate':'45'}},{'sample_aspect_ratio':'100:1'}]:
            stream={'width':720,'height':1280};stream.update(extra)
            self.assertIsNone(display_dimensions({'streams':[stream]}),extra)
        for invalid in [None,{}, {'streams':[]},{'streams':[None]}]:self.assertIsNone(display_dimensions(invalid))

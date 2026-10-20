import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from aiogram.dispatcher.event.bases import SkipHandler
from services.instagram_download import MediaItem, DownloadError

class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def message(self, text='https://instagram.com/p/a/', **kw):
        bot=NS(send_video=AsyncMock(return_value=NS(video=NS(file_id='v'))),send_photo=AsyncMock(return_value=NS(photo=[NS(file_id='p')])),send_media_group=AsyncMock(return_value=[NS(photo=[NS(file_id='p')]),NS(video=NS(file_id='v'))]),delete_message=AsyncMock())
        m=NS(bot=bot,chat=NS(id=-1003911850060,type='supergroup'),message_id=11,message_thread_id=27,text=text,entities=[],caption_entities=[],from_user=NS(username='alice',first_name='Alice',last_name=None,is_bot=False),sender_chat=None)
        m.__dict__.update(kw);return m
    async def run_handler(self,m,handle):
        from handlers import instagram as h
        with patch.object(h.service,'handle',side_effect=handle):
            with self.assertRaises(SkipHandler): await h.instagram_video(m,instagram_urls=['https://www.instagram.com/p/a/'])
    async def test_comment_unicode_plain_preserved(self):
        m=self.message('Мой <b>коммент</b> 😀 https://instagram.com/p/a/ конец')
        async def handle(chat,url,send,**kw): await send([MediaItem('photo','cache', coverage='complete')])
        await self.run_handler(m,handle)
        self.assertEqual(m.bot.send_photo.call_args.kwargs['caption'],'alice\nМой <b>коммент</b> 😀  конец')
        m.bot.delete_message.assert_awaited_once()

    async def test_long_comment_keeps_original(self):
        m=self.message('😀'*1100+' https://instagram.com/p/a/')
        async def handle(chat,url,send,**kw): await send([MediaItem('video','cache')])
        await self.run_handler(m,handle)
        m.bot.delete_message.assert_not_awaited()

    async def test_debug_reply_keeps_original(self):
        from handlers import instagram as h
        m=self.message()
        async def handle(chat,url,send,**kw): await send([MediaItem('video','cache')])
        with patch.object(h,'DELIVERY',{'reply_mode':True,'delete_source':True,'author_caption':True},create=True):
            await self.run_handler(m,handle)
        m.bot.delete_message.assert_not_awaited()
        self.assertEqual(m.bot.send_video.call_args.kwargs['reply_parameters'].message_id,11)

    async def test_partial_failure_no_confirmation_and_capacity_keep_source(self):
        from handlers import instagram as h
        for mode in ('partial','noop','busy','send_failure','short_album'):
            m=self.message('https://instagram.com/p/a/ https://instagram.com/p/b/')
            async def handle(chat,url,send,**kw):
                if mode == 'noop': return
                if mode == 'busy' or (mode == 'partial' and url.endswith('/b/')): raise DownloadError('busy')
                if mode == 'send_failure': m.bot.send_video.side_effect=RuntimeError('telegram')
                if mode == 'short_album':
                    m.bot.send_media_group.return_value=[NS(photo=[NS(file_id='p')])]
                    await send([MediaItem('photo','p'),MediaItem('video','v')])
                else: await send([MediaItem('video','cache')])
            with patch.object(h.service,'handle',side_effect=handle):
                with self.assertRaises(SkipHandler): await h.instagram_video(m,instagram_urls=['https://instagram.com/p/a/','https://instagram.com/p/b/'])
            m.bot.delete_message.assert_not_awaited()

    async def test_delete_api_failure_does_not_resend(self):
        m=self.message();m.bot.delete_message.side_effect=RuntimeError('forbidden old message')
        async def handle(chat,url,send,**kw): await send([MediaItem('video','cache')])
        with self.assertLogs(level='WARNING') as logs: await self.run_handler(m,handle)
        m.bot.send_video.assert_awaited_once();m.bot.delete_message.assert_awaited_once()
        self.assertNotIn('forbidden old message',' '.join(logs.output))

    async def test_mixed_album_only_first_caption(self):
        m=self.message('коммент https://instagram.com/p/a/')
        async def handle(chat,url,send,**kw): await send([MediaItem('photo','p', coverage='complete'),MediaItem('video','v',1280,720)])
        await self.run_handler(m,handle)
        args=m.bot.send_media_group.call_args.kwargs;media=args['media']
        self.assertEqual(media[0].caption,'alice\nкоммент');self.assertIsNone(media[1].caption)
        for item in media: self.assertIsNone(item.parse_mode);self.assertEqual(item.caption_entities,[])
        self.assertIsNone(args['reply_parameters']);self.assertEqual(args['message_thread_id'],27)
        m.bot.delete_message.assert_awaited_once()

    async def test_fallback_author_bounded_and_controls_removed(self):
        for user,chat,expected in [(NS(username=None,first_name='Иван',last_name='Иванов'),None,'Иван Иванов'),(None,NS(title='Группа\r\n@x\x00'),'Группа  x')]:
            m=self.message(from_user=user,sender_chat=chat)
            async def handle(chat,url,send,**kw): await send([MediaItem('video','v')])
            await self.run_handler(m,handle)
            self.assertEqual(m.bot.send_video.call_args.kwargs['caption'],expected)
        m=self.message(from_user=NS(username=None,first_name='x'*1000,last_name=None))
        await self.run_handler(m,handle)
        self.assertEqual(len(m.bot.send_video.call_args.kwargs['caption']),80)

    async def test_cancel_keeps_source(self):
        import asyncio
        from handlers import instagram as h
        m=self.message()
        async def handle(*args,**kw): raise asyncio.CancelledError()
        with patch.object(h.service,'handle',side_effect=handle):
            with self.assertRaises(asyncio.CancelledError): await h.instagram_video(m,instagram_urls=['https://instagram.com/p/a/'])
        m.bot.delete_message.assert_not_awaited()

    async def test_fourth_url_keeps_source(self):
        m=self.message(' '.join('https://instagram.com/p/%s/'%x for x in 'abcd'))
        async def handle(chat,url,send,**kw): await send([MediaItem('video','v')])
        await self.run_handler(m,handle);m.bot.delete_message.assert_not_awaited()

    async def test_url_punctuation_is_preserved(self):
        m=self.message('смотри https://instagram.com/p/a/, класс!')
        async def handle(chat,url,send,**kw): await send([MediaItem('video','v')])
        await self.run_handler(m,handle)
        self.assertEqual(m.bot.send_video.call_args.kwargs['caption'],'alice\nсмотри , класс!')

    async def test_hidden_fourth_url_keeps_source(self):
        m=self.message('a b c d',entities=[NS(type='text_link',url='https://instagram.com/p/%s/'%x) for x in 'abcd'])
        async def handle(chat,url,send,**kw): await send([MediaItem('video','v')])
        await self.run_handler(m,handle);m.bot.delete_message.assert_not_awaited()

    async def test_sender_chat_text_passes_filter(self):
        from handlers.instagram import InstagramFilter
        m=self.message(sender_chat=NS(title='Канал'),from_user=NS(is_bot=True))
        self.assertTrue(await InstagramFilter()(m))

    async def test_sender_chat_is_actual_uploader_not_anonymous_user(self):
        m=self.message(sender_chat=NS(title='Канал'),from_user=NS(username='GroupAnonymousBot',first_name='Group',last_name=None))
        async def handle(chat,url,send,**kw): await send([MediaItem('video','v')])
        await self.run_handler(m,handle)
        self.assertEqual(m.bot.send_video.call_args.kwargs['caption'],'Канал')

    async def test_delete_once_after_all_urls(self):
        from handlers import instagram as h
        m=self.message('https://instagram.com/p/a/ https://instagram.com/p/b/')
        events=[]
        async def handle(chat,url,send,**kw):
            await send([MediaItem('video','cached')]);events.append(url)
        async def delete(**kw): events.append('delete')
        m.bot.delete_message.side_effect=delete
        with patch.object(h.service,'handle',side_effect=handle):
            with self.assertRaises(SkipHandler): await h.instagram_video(m,instagram_urls=['https://instagram.com/p/a/','https://instagram.com/p/b/'])
        self.assertEqual(events,['https://instagram.com/p/a/','https://instagram.com/p/b/','delete'])
        m.bot.delete_message.assert_awaited_once_with(chat_id=m.chat.id,message_id=11)

    async def test_standalone_plain_author_topic(self):
        m=self.message()
        async def handle(chat,url,send,**kw): await send([MediaItem('video','cached',720,1280)])
        await self.run_handler(m,handle)
        m.bot.send_video.assert_awaited_once()
        args=m.bot.send_video.call_args.kwargs
        self.assertEqual(args['chat_id'],m.chat.id);self.assertEqual(args['message_thread_id'],27)
        self.assertIsNone(args['reply_parameters']);self.assertNotIn('reply_to_message_id',args)
        self.assertEqual(args['caption'],'alice');self.assertIsNone(args['parse_mode']);self.assertEqual(args['caption_entities'],[])
        self.assertEqual((args['width'],args['height']),(720,1280))

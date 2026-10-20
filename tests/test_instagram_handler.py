"""No Telegram network: concrete aiogram messages and injected downloader/send."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, PropertyMock
from aiogram.types import Message
from aiogram.dispatcher.event.bases import SkipHandler

class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # New delivery policy uses explicit Bot APIs, never reply shortcuts.
        self.bot = SimpleNamespace(send_video=AsyncMock(), send_photo=AsyncMock(),
                                   send_media_group=AsyncMock(), delete_message=AsyncMock())
        binding = patch.object(Message, 'bot', new_callable=PropertyMock, return_value=self.bot)
        binding.start(); self.addCleanup(binding.stop)

    def message(self, chat=-1003911850060, text='https://instagram.com/reel/abc/?igsh=x', **extra):
        data = {'message_id': 11, 'date': 1700000000,
                'chat': {'id': chat, 'type': 'supergroup'},
                'from': {'id': 42, 'is_bot': False, 'first_name': 'Test'}, 'text': text}
        data.update(extra)
        return Message.model_validate(data)

    async def test_filter_scope_and_entities(self):
        from handlers.instagram import InstagramFilter
        filter_ = InstagramFilter()
        self.assertEqual(await filter_(self.message()), {'instagram_urls': ['https://www.instagram.com/reel/abc/']})
        self.assertFalse(await filter_(self.message(chat=-999)))
        self.assertFalse(await filter_(self.message(text='/help https://instagram.com/reel/abc/')))
        self.assertFalse(await filter_(self.message(text='https://instagram.com.evil/reel/abc/')))
        self.assertEqual(await filter_(self.message(text='video', entities=[{'type':'text_link','offset':0,'length':5,'url':'https://instagram.com/p/abc/'}])), {'instagram_urls': ['https://www.instagram.com/p/abc/']})
        private = self.message().model_copy(update={'chat': self.message().chat.model_copy(update={'type': 'private'})})
        self.assertFalse(await filter_(private))

    async def test_existing_media_with_instagram_caption_is_ignored(self):
        from handlers.instagram import InstagramFilter
        for media in ['video', 'animation', 'document', 'photo', 'audio', 'voice', 'video_note', 'sticker']:
            msg = self.message(text=None, caption='https://instagram.com/reel/abc/').model_copy(update={media: object()})
            self.assertFalse(await InstagramFilter()(msg), media)
        forwarded = self.message().model_copy(update={'forward_date': 1700000000})
        self.assertEqual(await InstagramFilter()(forwarded), {'instagram_urls': ['https://www.instagram.com/reel/abc/']})

    async def test_capacity_failure_is_silent(self):
        from handlers.instagram import instagram_video, service, DownloadError
        with patch.object(service, 'handle', new_callable=AsyncMock) as handle, patch.object(Message, 'reply', new_callable=AsyncMock) as reply:
            handle.side_effect = DownloadError('busy')
            with self.assertRaises(SkipHandler):
                await instagram_video(self.message(), 'https://www.instagram.com/reel/abc/')
            reply.assert_not_awaited()

    async def test_router_is_registered_before_generic_handlers(self):
        from handlers import all_routers
        self.assertEqual(all_routers()[0].name, 'instagram')

    async def test_handler_sends_standalone_video_and_continues_existing_routing(self):
        from handlers.instagram import instagram_video, service
        async def handle(chat, url, send, message_id=None):
            self.assertEqual(await send(['cached-file-id']), ['returned-id'])
        message = self.message()
        with patch.object(service, 'handle', side_effect=handle), patch.object(self.bot, 'send_video', new_callable=AsyncMock) as reply:
            reply.return_value = SimpleNamespace(video=SimpleNamespace(file_id='returned-id'))
            with self.assertRaises(SkipHandler):
                await instagram_video(message, 'https://www.instagram.com/reel/abc/')
            reply.assert_awaited_once()
            self.assertEqual(reply.call_args.kwargs['video'], 'cached-file-id')

    async def test_three_current_urls_and_no_history(self):
        from handlers.instagram import InstagramFilter
        urls = ['https://www.instagram.com/p/%s/' % x for x in ['one', 'two', 'three', 'four']]
        self.assertEqual(await InstagramFilter()(self.message(text=' '.join(urls))), {'instagram_urls': urls[:3]})
        self.assertFalse(await InstagramFilter()(self.message(text='спасибо', reply_to_message=self.message().model_dump(by_alias=True))))

    async def test_all_failures_silent_and_next_link_attempted(self):
        from handlers.instagram import instagram_video, service, DownloadError
        urls = ['https://www.instagram.com/p/%s/' % x for x in ['one', 'two', 'three']]
        with patch.object(service, 'handle', new_callable=AsyncMock) as handle, patch.object(Message, 'reply', new_callable=AsyncMock) as reply:
            handle.side_effect = [DownloadError('no_video'), OSError('local'), None]
            with self.assertRaises(SkipHandler):
                await instagram_video(self.message(), instagram_urls=urls)
            self.assertEqual(handle.await_count, 3)
            reply.assert_not_awaited()

    async def test_failure_log_is_classified_and_sanitized(self):
        from handlers.instagram import instagram_video, service, DownloadError
        for reason, expected in [('busy', 'busy'), ('no_video', 'no_video'), ('secret?token=CANARY', 'unknown')]:
            with patch.object(service, 'handle', new_callable=AsyncMock) as handle, self.assertLogs(level='WARNING') as logs:
                handle.side_effect = DownloadError(reason)
                with self.assertRaises(SkipHandler):
                    await instagram_video(self.message(), 'https://www.instagram.com/p/abc/')
            output = ' '.join(logs.output)
            self.assertIn('code=' + expected, output)
            self.assertNotIn('CANARY', output)

    async def test_typed_photo_and_mixed_album_cached_ids(self):
        from handlers.instagram import instagram_video, service
        from services.instagram_download import MediaItem
        for items in [[MediaItem('photo', 'photo-cache')],
                      [MediaItem('photo', 'photo-cache'), MediaItem('video', 'video-cache')]]:
            async def handle(chat, url, send, message_id=None):
                self.assertEqual(await send(items), ['photo-return'] if len(items) == 1 else ['photo-return', 'video-return'])
            photo = SimpleNamespace(photo=[SimpleNamespace(file_id='small'), SimpleNamespace(file_id='photo-return')], video=None)
            video = SimpleNamespace(video=SimpleNamespace(file_id='video-return'), photo=None)
            with patch.object(service, 'handle', side_effect=handle), \
                    patch.object(self.bot, 'send_photo', new_callable=AsyncMock, return_value=photo) as rp, \
                    patch.object(self.bot, 'send_video', new_callable=AsyncMock) as rv, \
                    patch.object(self.bot, 'send_media_group', new_callable=AsyncMock, return_value=[photo, video]) as rg, \
                    patch.object(Message, 'reply', new_callable=AsyncMock) as text:
                with self.assertRaises(SkipHandler):
                    await instagram_video(self.message(), 'https://www.instagram.com/p/abc/')
                rv.assert_not_awaited(); text.assert_not_awaited()
                if len(items) == 1:
                    self.assertEqual(rp.call_args.kwargs['photo'], 'photo-cache')
                    rg.assert_not_awaited()
                else:
                    media = rg.call_args.kwargs['media']
                    self.assertEqual([m.type for m in media], ['photo', 'video'])
                    self.assertEqual([m.media for m in media], ['photo-cache', 'video-cache'])
                    rp.assert_not_awaited()

    async def test_photo_path_upload_and_album_limit(self):
        from handlers.instagram import instagram_video, service
        from services.instagram_download import MediaItem, DownloadError
        from pathlib import Path
        from aiogram.types import FSInputFile
        photo = SimpleNamespace(photo=[SimpleNamespace(file_id='photo-return')], video=None)
        for count in [1, 10, 11]:
            items = [MediaItem('photo', Path('/tmp/photo.jpg'))] * count
            async def handle(chat, url, send, message_id=None):
                if count > 10:
                    with self.assertRaises(DownloadError): await send(items)
                else:
                    self.assertEqual(await send(items), ['photo-return'] * count)
            with patch.object(service, 'handle', side_effect=handle), \
                    patch.object(self.bot, 'send_photo', new_callable=AsyncMock, return_value=photo) as rp, \
                    patch.object(self.bot, 'send_media_group', new_callable=AsyncMock, return_value=[photo] * count) as rg:
                with self.assertRaises(SkipHandler):
                    await instagram_video(self.message(), 'https://www.instagram.com/p/abc/')
                if count == 1:
                    self.assertIsInstance(rp.call_args.kwargs['photo'], FSInputFile)
                elif count == 10:
                    self.assertEqual(len(rg.call_args.kwargs['media']), 10)
                else:
                    rp.assert_not_awaited(); rg.assert_not_awaited()

if __name__ == '__main__': unittest.main()

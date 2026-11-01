"""Offline native-aiogram TikTok registration and delivery contracts."""
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

CHAT = -1003911850060
URL = 'https://www.tiktok.com/@sample/video/123456789'


def message(text=URL, **kwargs):
    result = NS(text=text, entities=[], caption_entities=[], caption=None,
        bot=NS(send_video=AsyncMock(return_value=NS(message_id=50, video=NS(file_id='cached'))),
               delete_message=AsyncMock()),
        chat=NS(id=CHAT, type='supergroup'), message_id=11, message_thread_id=27,
        from_user=NS(username='alice😀', is_bot=False), sender_chat=None, reply=AsyncMock())
    result.__dict__.update(kwargs)
    return result


def registered():
    from aiogram import Router
    from handlers import all_routers
    root = Router(name='offline_tiktok')
    for module_router in all_routers():
        if module_router.name not in {'instagram', 'x_video', 'youtube_video', 'tiktok_video', 'link_fix'}:
            continue
        child = Router(name='test_'+module_router.name)
        child.message.handlers.extend(module_router.message.handlers)
        root.include_router(child)
    return root


class Registration(unittest.IsolatedAsyncioTestCase):
    async def test_registered_ig_tiktok_both_send_without_delete(self):
        from handlers import instagram as ig
        from services.instagram_download import MediaItem
        m = message('https://www.instagram.com/reel/ABC/ '+URL)
        # Patch the backend class before import: no synthetic handler/router.
        from services.tiktok_video import TikTokService
        async def send(chat, url, callback, **kw):
            return await callback([MediaItem('video', 'native', 720, 1280)])
        with patch.object(TikTokService, 'handle', side_effect=send), patch.object(ig.service, 'handle', side_effect=send), patch.dict(ig.DELIVERY, reply_mode=False, delete_source=True):
            await registered().propagate_event(update_type='message', event=m)
        self.assertEqual(m.bot.send_video.await_count, 2)
        m.bot.delete_message.assert_not_awaited()
        m.reply.assert_not_awaited()

    async def test_standalone_confirmed_or_ambiguous_no_legacy_duplicate(self):
        from services.tiktok_video import TikTokService
        from services.instagram_download import MediaItem
        for ambiguous in (False, True):
            m = message()
            if ambiguous:
                m.bot.send_video.side_effect = TimeoutError()
            async def send(chat, url, callback, **kw):
                return await callback([MediaItem('video', 'native', 720, 1280)])
            with patch.object(TikTokService, 'handle', side_effect=send):
                await registered().propagate_event(update_type='message', event=m)
            m.bot.send_video.assert_awaited_once()
            self.assertEqual(m.bot.delete_message.await_count, 0 if ambiguous else 1)
            m.reply.assert_not_awaited()

WATCH = URL
SHORT = 'https://vm.tiktok.com/AbCd123/'

class Delivery(unittest.IsolatedAsyncioTestCase):
    def message(self, text='😀 коммент ' + SHORT, **kwargs):
        bot = NS(send_video=AsyncMock(return_value=NS(message_id=50, video=NS(file_id='cached'))),
                 delete_message=AsyncMock())
        message = NS(bot=bot, chat=NS(id=CHAT, type='supergroup'), message_id=11,
                     message_thread_id=27, text=text, entities=[], caption_entities=[],
                     from_user=NS(username='alice😀', is_bot=False), sender_chat=None,
                     reply=AsyncMock())
        message.__dict__.update(kwargs)
        return message

    async def test_router_standalone_short_and_watch_caption_receipts(self):
        from handlers import all_routers, tiktok_video as h
        from services.instagram_download import MediaItem
        self.assertEqual(Path(h.__file__).resolve().parents[1], Path(__file__).resolve().parents[1])
        self.assertIn(h.router, all_routers())
        self.assertLess(all_routers().index(h.router), len(all_routers()) - 1)
        for url in (SHORT, WATCH, 'https://www.tiktok.com/@sample/video/123456789?tracking=abc'):
            with self.subTest(url=url):
                message = self.message('😀 коммент ' + url)
                receipts = []
                async def handle(chat, source, send, **kwargs):
                    self.assertEqual(source, h.canonical_url(url))
                    receipts.append(await send([MediaItem('video', 'fileid', 1280, 720)]))
                    return receipts[-1]
                with patch.object(h.service, 'handle', side_effect=handle):
                    await h.router.propagate_event(update_type='message', event=message)
                self.assertEqual(receipts, [[(50, 'cached')]])
                args = message.bot.send_video.call_args.kwargs
                self.assertEqual(args['caption'], 'alice😀\n😀 коммент')
                self.assertEqual(args['message_thread_id'], 27)
                self.assertEqual(args['video'], 'fileid')
                self.assertEqual((args['width'], args['height']), (1280, 720))
                self.assertTrue(args['supports_streaming'])
                self.assertIsNone(args['parse_mode'])
                self.assertEqual([(e.type, e.offset, e.length, e.url) for e in args['caption_entities']],
                                 [('text_link', 0, 7, h.canonical_url(url))])
                message.bot.delete_message.assert_awaited_once()
                message.reply.assert_not_awaited()

    async def test_unknown_item_coverage_retains_source(self):
        from handlers import tiktok_video as h
        from services.instagram_download import MediaItem
        message = self.message()
        async def handle(chat, url, send, **kwargs):
            return await send([MediaItem('video', 'cached', 720, 1280, 'unknown')])
        with patch.object(h.service, 'handle', side_effect=handle):
            await h.router.propagate_event(update_type='message', event=message)
        message.bot.send_video.assert_awaited_once()
        message.bot.delete_message.assert_not_awaited()

    async def test_scope_current_only_and_bot_forwards(self):
        from handlers import tiktok_video as h
        cases = [dict(text=None, caption=SHORT), dict(text='thanks', reply_to_message=NS(text=SHORT)),
                 dict(text='/cmd '+SHORT), dict(chat=NS(id=-1, type='supergroup')),
                 dict(chat=NS(id=CHAT, type='private')), dict(from_user=NS(is_bot=True)),
                 dict(forward_origin=NS(sender_user=NS(is_bot=True))), dict(forward_from=NS(is_bot=True))]
        cases += [{field: object()} for field in h.MEDIA]
        for kwargs in cases:
            self.assertFalse(await h.TikTokFilter()(self.message(**kwargs)), kwargs)
        self.assertTrue(await h.TikTokFilter()(self.message(sender_chat=NS(title='Channel'), from_user=NS(is_bot=True))))

    async def test_entities_utf16_hidden_provider_and_external_comment_link(self):
        from handlers import tiktok_video as h
        from services.instagram_download import MediaItem
        async def handle(chat, url, send, **kwargs):
            return await send([MediaItem('video', 'cache', 720, 1280)])
        text = '😀 смотри сайт '+SHORT
        external = NS(type='text_link', offset=10, length=4, url='https://example.com/info')
        # Offset is deliberately calculated from Unicode rather than Python indexes.
        external.offset = len('😀 смотри '.encode('utf-16-le')) // 2
        message = self.message(text, entities=[external])
        with patch.object(h.service, 'handle', side_effect=handle):
            await h.router.propagate_event(update_type='message', event=message)
        args = message.bot.send_video.call_args.kwargs
        self.assertEqual(args['caption'], 'alice😀\n😀 смотри сайт')
        link = args['caption_entities'][1]
        self.assertEqual(link.url, external.url)
        self.assertEqual(link.offset, len('alice😀\n😀 смотри '.encode('utf-16-le')) // 2)
        message.bot.delete_message.assert_not_awaited()
        message = self.message('😀 смотри', entities=[NS(type='text_link', offset=3, length=6, url=SHORT)])
        with patch.object(h.service, 'handle', side_effect=handle):
            await h.router.propagate_event(update_type='message', event=message)
        message.bot.delete_message.assert_awaited_once()
        # Telegram URL entities without a scheme must not disappear from the veto inventory.
        text = SHORT+' example.com'
        message = self.message(text, entities=[NS(type='url', offset=len(SHORT)+1, length=11)])
        with patch.object(h.service, 'handle', side_effect=handle):
            await h.router.propagate_event(update_type='message', event=message)
        message.bot.delete_message.assert_not_awaited()

    async def test_failures_partial_receipts_and_deletion_vetoes(self):
        from handlers import tiktok_video as h
        from services.instagram_download import MediaItem
        urls = ['https://www.tiktok.com/@sample/video/12345678'+str(i) for i in range(4)]
        cases = [('error', SHORT), ('noop', SHORT), ('false', SHORT), ('missing_id', SHORT),
                 ('missing_file', SHORT), ('bool_id', SHORT), ('nonstring_file', SHORT), ('partial', ' '.join(urls[:2])),
                 ('ok', ' '.join(urls)), ('ok', SHORT+' https://example.com'),
                 ('ok', '😀'*600+' '+SHORT), ('invalid_entity', SHORT), ('invalid_items', SHORT)]
        for mode, text in cases:
            with self.subTest(mode=mode, text=text[:80]):
                message = self.message(text)
                if mode == 'false': message.bot.send_video.return_value = False
                if mode == 'missing_id': message.bot.send_video.return_value = NS(video=NS(file_id='file'))
                if mode == 'missing_file': message.bot.send_video.return_value = NS(message_id=50, video=NS(file_id=''))
                if mode == 'bool_id': message.bot.send_video.return_value = NS(message_id=True, video=NS(file_id='cached'))
                if mode == 'nonstring_file': message.bot.send_video.return_value = NS(message_id=50, video=NS(file_id=True))
                if mode == 'invalid_entity': message.entities = [NS(type='text_link', offset=-1, length=2, url=WATCH)]
                count = []
                async def handle(chat, url, send, **kwargs):
                    count.append(url)
                    if mode == 'error' or mode == 'partial' and len(count) == 2: raise ValueError('secret')
                    if mode == 'noop': return True
                    return await send([] if mode == 'invalid_items' else [MediaItem('video', 'cache', 720, 1280)])
                with patch.object(h.service, 'handle', side_effect=handle):
                    await h.router.propagate_event(update_type='message', event=message)
                self.assertLessEqual(len(count), 3)
                message.bot.delete_message.assert_not_awaited()
                message.reply.assert_not_awaited()

    async def test_path_upload_dedup_and_each_source_caption(self):
        from handlers import tiktok_video as h
        from services.instagram_download import MediaItem
        from aiogram.types import FSInputFile
        second = 'https://www.tiktok.com/@sample/video/987654321'
        message = self.message(WATCH+'?tracking=1 '+WATCH+' '+second)
        async def handle(chat, url, send, **kwargs):
            return await send([MediaItem('video', Path('/tmp/offline.mp4'), 720, 1280)])
        with patch.object(h.service, 'handle', side_effect=handle) as work:
            await h.router.propagate_event(update_type='message', event=message)
        self.assertEqual(work.await_count, 2)
        self.assertEqual(message.bot.send_video.await_count, 2)
        for call, url in zip(message.bot.send_video.call_args_list, (WATCH, h.canonical_url(second))):
            self.assertIsInstance(call.kwargs['video'], FSInputFile)
            self.assertEqual(call.kwargs['caption_entities'][0].url, url)
        message.bot.delete_message.assert_awaited_once()

    async def test_inline_url_entities_and_uncertain_utf16_offsets(self):
        from handlers import tiktok_video as h
        from services.instagram_download import MediaItem
        async def handle(chat, url, send, **kwargs):
            return await send([MediaItem('video', 'cached', 1280, 720)])
        text = '😀 '+SHORT
        entities = [NS(type='url', offset=3, length=len(SHORT))]
        message = self.message(text, entities=entities)
        with patch.object(h.service, 'handle', side_effect=handle):
            await h.router.propagate_event(update_type='message', event=message)
        self.assertEqual(message.bot.send_video.call_args.kwargs['caption'], 'alice😀\n😀')
        message.bot.delete_message.assert_awaited_once()
        for entity in (NS(type='url', offset=1, length=2),
                       NS(type='text_link', offset=999, length=3, url=SHORT),
                       NS(type='url', offset=3, length=999)):
            message = self.message(text, entities=[entity])
            with patch.object(h.service, 'handle', side_effect=handle):
                await h.router.propagate_event(update_type='message', event=message)
            message.bot.delete_message.assert_not_awaited()

    async def test_service_exception_after_send_cancellation_and_delete_failure(self):
        import asyncio
        from handlers import tiktok_video as h
        from services.instagram_download import MediaItem
        message = self.message()
        async def handle(chat, url, send, **kwargs):
            await send([MediaItem('video', 'cached', 1280, 720)])
            raise RuntimeError('private secret')
        with patch.object(h.service, 'handle', side_effect=handle), self.assertLogs(level='WARNING') as logs:
            await h.router.propagate_event(update_type='message', event=message)
        self.assertNotIn('private secret', ' '.join(logs.output))
        message.bot.delete_message.assert_not_awaited()
        message = self.message()
        with patch.object(h.service, 'handle', side_effect=asyncio.CancelledError()):
            with self.assertRaises(asyncio.CancelledError):
                await h.router.propagate_event(update_type='message', event=message)
        message.bot.delete_message.assert_not_awaited()
        async def success(chat, url, send, **kwargs):
            return await send([MediaItem('video', 'cached', 1280, 720)])
        message.bot.delete_message.side_effect = RuntimeError('private secret')
        with patch.object(h.service, 'handle', side_effect=success), self.assertLogs(level='WARNING') as logs:
            await h.router.propagate_event(update_type='message', event=message)
        message.bot.send_video.assert_awaited_once()
        self.assertNotIn('private secret', ' '.join(logs.output))


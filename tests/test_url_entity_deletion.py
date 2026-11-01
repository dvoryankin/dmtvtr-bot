"""Registered-handler retention tests, native aiogram or explicit offline mock.

Local fallback: python3 tests/test_url_entity_deletion.py --mock-aiogram -v
Mocks only aiogram registration/dispatch/types; provider services are imported
from this checkout and their handle/send transport boundaries are patched.
This fallback is NOT native aiogram/router integration evidence.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
IG = 'https://www.instagram.com/reel/ABC/'
YT = 'https://www.youtube.com/shorts/2bZeMfMUhUc'
CHAT = -1003911850060


def install_aiogram_mock():
    import types
    class SkipHandler(Exception):
        pass
    class Value:
        def __init__(self, **kwargs):
            self.user = None  # MessageEntity's native optional field.
            self.__dict__.update(kwargs)
    class Observer:
        def __init__(self):
            self.handlers = []
        def __call__(self, filter_):
            def register(callback):
                self.handlers.append((filter_, callback))
                return callback
            return register
    class Router:
        def __init__(self, name):
            self.name = name
            self.message = Observer()
        async def propagate_event(self, update_type, event):
            for filter_, callback in self.message.handlers:
                result = await filter_(event)
                if result:
                    try:
                        await callback(event, **result)
                    except SkipHandler:
                        continue
    for name in ('aiogram', 'aiogram.filters', 'aiogram.types',
                 'aiogram.dispatcher', 'aiogram.dispatcher.event',
                 'aiogram.dispatcher.event.bases'):
        sys.modules[name] = types.ModuleType(name)
    sys.modules['aiogram'].Router = Router
    sys.modules['aiogram.filters'].Filter = object
    sys.modules['aiogram.dispatcher.event.bases'].SkipHandler = SkipHandler
    for name in ('MessageEntity', 'Message', 'FSInputFile', 'InputMediaVideo',
                 'InputMediaPhoto', 'ReplyParameters'):
        setattr(sys.modules['aiogram.types'], name, Value)
    # Load only selected real handlers, not unrelated application/bootstrap code.
    package = types.ModuleType('handlers')
    package.__path__ = [str(ROOT / 'handlers')]
    sys.modules['handlers'] = package


class URLInventory(unittest.IsolatedAsyncioTestCase):
    def message(self, text, entities):
        return NS(text=text, entities=entities, caption_entities=[],
                  chat=NS(id=CHAT, type='supergroup'), message_id=11,
                  message_thread_id=27, from_user=NS(username='alice😀', is_bot=False),
                  sender_chat=None, reply=AsyncMock(),
                  bot=NS(send_video=AsyncMock(return_value=NS(
                      message_id=50, video=NS(file_id='cached'))),
                      delete_message=AsyncMock()))

    async def dispatch(self, provider, text, entities, delete=False):
        from handlers import instagram, youtube_video
        from services import repost_author
        from services.instagram_download import MediaItem
        module = instagram if provider == 'ig' else youtube_video
        for loaded in (instagram, youtube_video, repost_author):
            self.assertEqual(Path(loaded.__file__).resolve().parents[1], ROOT)
        message = self.message(text, entities)
        async def handle(chat, url, send, **kwargs):
            return await send([MediaItem('video', 'cached', 720, 1280,
                                         coverage='extracted_videos')])
        with patch.object(module.service, 'handle', side_effect=handle) as work, \
                patch.dict(instagram.DELIVERY, reply_mode=False, delete_source=True):
            await module.router.propagate_event(update_type='message', event=message)
        work.assert_awaited_once()
        # Unknown entities never become extra fetches or suppress normal delivery.
        self.assertEqual(work.call_args.args[1], module.canonical_url(IG if provider == 'ig' else YT))
        message.bot.send_video.assert_awaited_once()
        args = message.bot.send_video.call_args.kwargs
        self.assertEqual(args['message_thread_id'], 27)
        self.assertIsNone(args['parse_mode'])
        self.assertEqual(args['caption_entities'][0].url, module.canonical_url(IG if provider == 'ig' else YT))
        message.reply.assert_not_awaited()
        if delete:
            message.bot.delete_message.assert_awaited_once()
        else:
            message.bot.delete_message.assert_not_awaited()
        return message

    async def test_extra_schemeless_url_after_emoji_retains_source(self):
        for provider, url in (('ig', IG), ('yt', YT)):
            for prefix in ('', '😀 '):
                with self.subTest(provider=provider, prefix=prefix):
                    text = prefix + url + ' example.com/url'
                    offset = len((prefix + url + ' ').encode('utf-16-le')) // 2
                    message = await self.dispatch(provider, text, [NS(type='url', offset=offset, length=15)])
                    self.assertIn('example.com/url', message.bot.send_video.call_args.kwargs['caption'])

    async def test_malformed_entity_coordinates_retain_without_suppressing_send(self):
        for provider, url in (('ig', IG), ('yt', YT)):
            cases = [NS(type='url'), NS(type='url', offset=True, length=1),
                     NS(type='url', offset=3, length=True),
                     NS(type='url', offset=-1, length=1), NS(type='url', offset=3, length=-1),
                     NS(type='url', offset=3, length=0), NS(type='url', offset='3', length=1),
                     NS(type='url', offset=3, length=1.5), NS(type='url', offset=999, length=1),
                     NS(type='url', offset=3, length=999),
                     NS(type='text_link', offset=False, length=2, url=url),
                     NS(type='text_link', offset=3, length=True, url=url),
                     NS(type='url', offset=1, length=1), NS(type='url', offset=0, length=1),
                     NS(type='text_link', offset=999, length=1, url=url),
                     NS(type='text_link', offset=3, length=1, url=None)]
            for entity in cases:
                with self.subTest(provider=provider, entity=vars(entity)):
                    await self.dispatch(provider, '😀 '+url, [entity])

    async def test_complete_provider_only_utf16_entities_still_delete(self):
        for provider, url in (('ig', IG), ('yt', YT)):
            for entities in ([], [NS(type='url', offset=3, length=len(url))],
                             [NS(type='bold', offset=0, length=2)]):
                with self.subTest(provider=provider, entities=entities):
                    await self.dispatch(provider, '😀 '+url, entities, delete=True)

    async def test_instagram_unknown_and_ambiguous_entities_retain(self):
        cases = [[NS(type='future_link', offset=3, length=len(IG))],
                 [NS(offset=3, length=len(IG))], [None],
                 [NS(type='text_link', offset=3, length=1)],
                 [NS(type='text_link', offset=3, length=1, url=True)],
                 [NS(type='url', offset=3, length=len(IG)),
                  NS(type='text_link', offset=3, length=len(IG), url=IG)]]
        for entities in cases:
            with self.subTest(entities=entities):
                await self.dispatch('ig', '😀 '+IG, entities)

    async def test_youtube_unknown_entity_external_url_retains_source(self):
        for prefix in ('', '😀 '):
            with self.subTest(prefix=prefix):
                offset = len(prefix.encode('utf-16-le')) // 2
                await self.dispatch('yt', prefix + YT,
                    [NS(type='future_link', offset=offset, length=len(YT),
                        url='https://example.com/url')])

    async def test_youtube_overlapping_provider_entities_retain_source(self):
        for prefix in ('', '😀 '):
            with self.subTest(prefix=prefix):
                offset = len(prefix.encode('utf-16-le')) // 2
                await self.dispatch('yt', prefix + YT,
                    [NS(type='url', offset=offset, length=len(YT)),
                     NS(type='text_link', offset=offset, length=len(YT), url=YT)])

    async def test_valid_hidden_provider_entity_still_deletes(self):
        for provider, url in (('ig', IG), ('yt', YT)):
            with self.subTest(provider=provider):
                # Visible provider URL keeps the dispatch assertion identical;
                # the valid hidden link must not become a blanket deletion veto.
                await self.dispatch(provider, '😀 '+url,
                    [NS(type='text_link', offset=0, length=2, url=url)], delete=True)

    async def test_explicit_http_fallback_and_hidden_external_links_retain(self):
        for provider, url in (('ig', IG), ('yt', YT)):
            with self.subTest(provider=provider, kind='http'):
                await self.dispatch(provider, url+' https://example.com/url', [])
            with self.subTest(provider=provider, kind='hidden'):
                await self.dispatch(provider, 'site '+url, [NS(type='text_link', offset=0,
                    length=4, url='https://example.com/url')])


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    if '--mock-aiogram' in sys.argv:
        sys.argv.remove('--mock-aiogram')
        install_aiogram_mock()
        print('EXPLICIT MOCK: aiogram types + registration/dispatch; real staged handlers/services', flush=True)
    unittest.main()

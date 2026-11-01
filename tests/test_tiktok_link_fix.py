"""Real registered routes and real service/cache; Telegram is always offline."""
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from test_tiktok_handler import URL, CHAT, message, registered


class NativeService(unittest.IsolatedAsyncioTestCase):
    async def test_four_providers_real_cached_service_registered_sends(self):
        from handlers import instagram as ig, x_video as x, youtube_video as yt, tiktok_video as tt
        from services.instagram_download import DownloadService, MediaItem
        from services.x_video import XService, Item
        from services.youtube_video import YouTubeService
        from services.tiktok_video import TikTokService
        base = Path(__file__).resolve().parents[1]
        modules = (ig, x, yt, tt)
        for module in modules:
            self.assertEqual(Path(module.__file__).resolve().parents[1], base)
        urls = ('https://www.instagram.com/reel/ABC/', 'https://x.com/u/status/1',
                'https://www.youtube.com/watch?v=2bZeMfMUhUc', URL)
        services = (DownloadService(base, [CHAT]), XService([CHAT]),
                    YouTubeService(base, [CHAT]), TikTokService(base, [CHAT]))
        with ExitStack() as stack:
            for module, service, url in zip(modules, services, urls):
                if module is not x:
                    item = MediaItem('video', module.router.name, 720, 1280, 'complete')
                    service.cache[module.canonical_url(url)] = (service.clock(), [item])
                stack.enter_context(patch.object(module, 'service', service))
            async def x_fetch(session, url, path=None, limit=None, method='GET'):
                if method == 'HEAD':
                    return 40
                if path is not None:
                    path.write_bytes(b'0000ftyp' + b'0'*32)
                    return 40
                return {'tweet': {'media': {'videos': [{'url': 'https://video.twimg.com/offline.mp4'}]}}}
            from unittest.mock import AsyncMock
            stack.enter_context(patch('services.x_video.fetch', side_effect=x_fetch))
            stack.enter_context(patch('services.x_video.probe_video_dimensions', new=AsyncMock(return_value=(720, 1280))))
            stack.enter_context(patch.dict(ig.DELIVERY, reply_mode=False, delete_source=True))
            stack.enter_context(patch.dict(x.DELIVERY, enabled=True, reply_mode=False, delete_source=True))
            m = message(' '.join(urls))
            await registered().propagate_event(update_type='message', event=m)
        self.assertEqual(m.bot.send_video.await_count, 4)
        m.bot.delete_message.assert_not_awaited()
        m.reply.assert_not_awaited()

    async def test_real_tiktok_service_download_cache_alias_ambiguous_never_retries(self):
        import json
        from handlers import tiktok_video as tt
        from services.tiktok_video import TikTokService
        for ambiguous in (False, True):
            calls = []
            async def downloader(url, directory):
                calls.append(url)
                # Explicit fake downloader output; never represented as a real MP4.
                (directory/'video.mp4').write_bytes(b'0000ftyp' + b'0'*32)
                (directory/'manifest.json').write_text(json.dumps({'version': 1, 'items': [
                    {'type': 'video', 'file': 'video.mp4', 'width': 720, 'height': 1280}]}))
            service = TikTokService(tt.BASE, [CHAT], runner=downloader)
            m = message(URL+'?tracking=first')
            if ambiguous:
                m.bot.send_video.side_effect = TimeoutError()
            with patch.object(tt, 'service', service):
                await registered().propagate_event(update_type='message', event=m)
                m.bot.send_video.assert_awaited_once()
                m.reply.assert_not_awaited()
                self.assertEqual(m.bot.delete_message.await_count, 0 if ambiguous else 1)
                if not ambiguous:
                    second = message(URL+'?tracking=second', message_id=12)
                    await registered().propagate_event(update_type='message', event=second)
                    self.assertEqual(second.bot.send_video.call_args.kwargs['video'], 'cached')
                    second.bot.delete_message.assert_awaited_once()
            self.assertEqual(len(calls), 1)
            self.assertFalse(service.pending)
            self.assertFalse(service.inflight)

    async def test_legacy_unsupported_out_of_scope_and_x_rules_unchanged(self):
        from handlers import tiktok_video as tt, x_video as x
        tt.HANDLED.clear()
        x.HANDLED.clear()
        for text, kwargs in ((URL, {'chat': type('Chat', (), {'id': -1, 'type': 'supergroup'})()}),
                             ('https://www.tiktok.com/@sample', {}),
                             ('https://x.com/u/status/1', {'chat': type('Chat', (), {'id': -1, 'type': 'supergroup'})()})):
            m = message(text, **kwargs)
            await registered().propagate_event(update_type='message', event=m)
            m.bot.send_video.assert_not_awaited()
            m.reply.assert_awaited_once()
            m.bot.delete_message.assert_not_awaited()

"""Sanitized structural fixture from the two captured public embeds.
Only class, media type and canonical permalink shape retained; no profile IDs,
raw HTML, signed CDN URLs or request IDs from the capture are stored here.
"""
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PIL import Image
import test_instagram_delivery as delivery_tests


def embed(code='DdxEe7ZM5TR', media_type='GraphImage'):
    url = 'https://www.instagram.com/p/%s/' % code
    return ('<html><head><meta charset="utf-8"><link rel="stylesheet" href="/test.css"></head>'
            '<body><div class="Embed" data-permalink="%s?utm_source=ig_embed&amp;utm_campaign=test" '
            'data-media-type="%s"><br><a class="EmbeddedMedia" href="%s?utm_source=ig_embed">'
            '<div><img class="EmbeddedMediaImage" src="https://x.cdninstagram.com/test.jpg">'
            '</div></a><hr></div></body></html>') % (url, media_type, url)


def jpeg():
    out = io.BytesIO()
    Image.new('RGB', (640, 480), 'red').save(out, format='JPEG')
    return out.getvalue()


class InventoryTests(unittest.TestCase):
    def coverage(self, page, code='DdxEe7ZM5TR'):
        from instagram_photos import download_photo
        with TemporaryDirectory() as raw:
            directory = Path(raw)
            with patch('instagram_photos.fetch', side_effect=[page.encode(), jpeg()]):
                download_photo('https://www.instagram.com/p/%s/' % code, directory)
            return json.loads((directory / 'manifest.json').read_text())['coverage']

    def test_two_captured_root_shapes_with_queries_and_void_elements(self):
        for code in ('DdxEe7ZM5TR', 'DequRzUxxZ7'):
            with self.subTest(code=code):
                self.assertEqual(self.coverage(embed(code), code), 'embed_single_image')

    def test_captured_optional_document_end_tags_not_unclosed_embed(self):
        # Both stored captures omit only </body></html>, which HTML permits.
        self.assertEqual(self.coverage(embed().replace('</body></html>', '')), 'embed_single_image')
        self.assertEqual(self.coverage(embed().replace('<br>', '<br/>')), 'embed_single_image')

    def test_unfinished_markup_is_not_positive_inventory(self):
        for suffix in ('<', '<div', '<!-- unfinished'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.coverage(embed() + suffix), 'embed_first_image')

    def test_no_false_complete_inventory(self):
        page = embed()
        main = '<img class="EmbeddedMediaImage" src="https://x.cdninstagram.com/test.jpg">'
        extra = '<div class="Embed" data-permalink="https://www.instagram.com/p/other/" data-media-type="GraphImage"></div>'
        cases = {
            'sidecar': page.replace('GraphImage', 'GraphSidecar'),
            # Explicit GraphVideo covers are rejected entirely, not partial photos;
            # covered by EmbedTests.test_explicit_video_embed_cover_is_not_a_post_photo.
            'unknown': page.replace('GraphImage', 'FutureType'),
            'missing_type': page.replace('data-media-type="GraphImage"', ''),
            'wrong_root_post': page.replace('data-permalink="https://www.instagram.com/p/DdxEe7ZM5TR/', 'data-permalink="https://www.instagram.com/p/other/'),
            'missing_permalink': page.replace('data-permalink=', 'data-unrelated='),
            'multiple_roots': page + extra,
            'contradictory_roots': page + extra.replace('GraphImage', 'GraphSidecar'),
            'nested_root': page.replace('<br>', extra + '<br>'),
            'not_div_root': page.replace('<div class="Embed"', '<section class="Embed"').replace('</div></body>', '</section></body>'),
            'image_outside_root': page.replace(main, '') + '<a class="EmbeddedMedia" href="https://www.instagram.com/p/DdxEe7ZM5TR/">' + main + '</a>',
            'missing_root': page.replace('class="Embed"', 'class="Other"'),
            'duplicate_type': page.replace('data-media-type="GraphImage"', 'data-media-type="GraphSidecar" data-media-type="GraphImage"'),
            'unclosed': page.replace('</div></body></html>', ''),
            'mismatched': page.replace('</div></a>', '</span></a>'),
            'extra_anchor': page.replace('<br>', '<a class="EmbeddedMedia" href="https://www.instagram.com/p/other/"></a><br>'),
        }
        for case, html in cases.items():
            with self.subTest(case=case):
                self.assertEqual(self.coverage(html), 'embed_first_image')

    def test_duplicate_images_never_complete_even_same_source(self):
        from instagram_photos import download_photo
        from instagram_download import DownloadError
        page = embed()
        main = '<img class="EmbeddedMediaImage" src="https://x.cdninstagram.com/test.jpg">'
        # Old partial URL API deduplicates identical URLs; inventory must not.
        self.assertEqual(self.coverage(page.replace(main, main * 2)), 'embed_first_image')
        wrong = page.replace('href="https://www.instagram.com/p/DdxEe7ZM5TR/?utm_source', 'href="https://www.instagram.com/p/other/?utm_source')
        for html in (wrong, page.replace(main, main + main.replace('test.jpg', 'second.jpg'))):
            with TemporaryDirectory() as raw, patch('instagram_photos.fetch', return_value=html.encode()) as fetch:
                with self.assertRaises(DownloadError):
                    download_photo('https://www.instagram.com/p/DdxEe7ZM5TR/', Path(raw))
                self.assertEqual(fetch.call_count, 1)

    def test_marker_is_photo_specific_and_old_contracts_unchanged(self):
        from services.instagram_download import MediaItem, media_complete
        self.assertTrue(media_complete(MediaItem('photo', 'p', coverage='embed_single_image')))
        self.assertFalse(media_complete(MediaItem('video', 'v', coverage='embed_single_image')))
        for coverage in (None, 'unknown', 'embed_first_image', 'extracted_videos'):
            self.assertFalse(media_complete(MediaItem('photo', 'p', coverage=coverage)))
        for coverage in (None, 'complete', 'extracted_videos'):
            self.assertTrue(media_complete(MediaItem('video', 'v', coverage=coverage)))
        self.assertTrue(media_complete(MediaItem('photo', 'p', coverage='complete')))


class SinglePhotoDelivery(unittest.IsolatedAsyncioTestCase):
    async def test_ambiguous_delivery_never_deletes_or_retries_send(self):
        import asyncio
        from types import SimpleNamespace as NS
        from aiogram.dispatcher.event.bases import SkipHandler
        from handlers import instagram as h
        from services.instagram_download import DownloadService
        for mode in ('photo_error', 'photo_timeout', 'missing_confirmation',
                     'album_short', 'album_error', 'cache_timeout', 'cache_error'):
            with self.subTest(mode=mode):
                runs = []
                async def runner(url, directory):
                    runs.append(directory)
                    (directory / 'one.jpg').write_bytes(jpeg())
                    items = [dict(type='photo', file='one.jpg')]
                    if mode.startswith('album'):
                        (directory / 'two.jpg').write_bytes(jpeg())
                        items.append(dict(type='photo', file='two.jpg'))
                    (directory / 'manifest.json').write_text(json.dumps(dict(
                        version=1, coverage='complete' if mode.startswith('album') else 'embed_single_image', items=items)))
                service = DownloadService(h.BASE, {-1003911850060}, runner=runner)
                async def deliver(m):
                    with patch.object(h, 'service', service):
                        with self.assertRaises(SkipHandler):
                            await h.instagram_video(m, instagram_urls=['https://www.instagram.com/p/a/'])
                if mode.startswith('cache'):
                    await deliver(delivery_tests.DeliveryTests().message())
                    self.assertTrue(service.cache)
                m = delivery_tests.DeliveryTests().message()
                target = m.bot.send_media_group if mode.startswith('album') else m.bot.send_photo
                if mode.endswith('timeout'):
                    target.side_effect = asyncio.TimeoutError()
                elif mode.endswith('error'):
                    target.side_effect = RuntimeError('ambiguous delivery')
                elif mode == 'album_short':
                    target.return_value = [NS(photo=[NS(file_id='p')])]
                else:
                    target.return_value = NS(photo=[])
                await deliver(m)
                target.assert_awaited_once()
                m.bot.delete_message.assert_not_awaited()
                self.assertEqual(len(runs), 1)
                self.assertFalse(service.cache)
                self.assertTrue(all(not p.exists() for p in runs))

    async def test_proven_single_photo_download_prepare_local_cache_delete_after_send(self):
        from handlers import instagram as h
        from services.instagram_download import DownloadService
        from instagram_photos import download_photo
        runs, markers, events = [], [], []
        async def runner(url, directory):
            runs.append(directory)
            with patch('instagram_photos.fetch', side_effect=[embed().encode(), jpeg()]):
                download_photo(url, directory)
            markers.append(json.loads((directory / 'manifest.json').read_text())['coverage'])
        service = DownloadService(h.BASE, {-1003911850060}, runner=runner)
        for attempt in range(2):
            m = delivery_tests.DeliveryTests().message('https://instagram.com/p/DdxEe7ZM5TR/')
            original_send = m.bot.send_photo.return_value
            async def send(**kwargs):
                value = kwargs['photo']
                if attempt == 0:
                    self.assertTrue(Path(value.path).name.startswith('prepared_'))
                    self.assertTrue(Path(value.path).is_file())
                else:
                    self.assertEqual(value, 'p')
                events.append('send')
                return original_send
            async def delete(**kwargs):
                events.append('delete')
            m.bot.send_photo.side_effect = send
            m.bot.delete_message.side_effect = delete
            with patch.object(h, 'service', service):
                from aiogram.dispatcher.event.bases import SkipHandler
                with self.assertRaises(SkipHandler):
                    await h.instagram_video(m, instagram_urls=['https://www.instagram.com/p/DdxEe7ZM5TR/'])
            m.bot.send_photo.assert_awaited_once()
            m.bot.delete_message.assert_awaited_once()
        self.assertEqual(markers, ['embed_single_image'])
        self.assertEqual(events, ['send', 'delete', 'send', 'delete'])
        self.assertEqual(len(runs), 1)
        self.assertFalse(runs[0].exists())
        cached = next(iter(service.cache.values()))[1][0]
        self.assertEqual(cached.coverage, 'embed_single_image')

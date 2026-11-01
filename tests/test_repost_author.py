"""Offline send boundaries: uploader label links only the current source post."""
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from aiogram.dispatcher.event.bases import SkipHandler

COMMENT = '<b>literal</b> [evil](tg://user?id=999) @nobody *markdown*'
IG = 'https://www.instagram.com/p/ABC/'
X = 'https://x.com/u/status/1'
D = 'https://idiod.video/k5r9yf.mp4'


def setUpModule():
    from handlers import instagram, x_video, idiod_video
    from services import repost_author
    root = Path(__file__).resolve().parents[1]
    for module in (instagram, x_video, idiod_video, repost_author):
        assert root in Path(module.__file__).resolve().parents, module.__file__


class AuthorDelivery(unittest.IsolatedAsyncioTestCase):
    def message(self, url, user=None, sender=None, comment=COMMENT):
        receipt = NS(message_id=50, video=NS(file_id='v'), photo=[NS(file_id='p')])
        bot = NS(send_video=AsyncMock(return_value=receipt), send_photo=AsyncMock(return_value=receipt),
                 send_media_group=AsyncMock(return_value=[receipt, receipt]), delete_message=AsyncMock())
        return NS(bot=bot, chat=NS(id=-1003911850060, type='supergroup'), message_id=11,
                  message_thread_id=27, text=comment+' '+url, entities=[], caption_entities=[],
                  from_user=user if user is not None else NS(username='alice', id=42, is_bot=False), sender_chat=sender)

    def scope(self, caption, entities, label, url):
        self.assertTrue(caption.startswith(label))
        self.assertEqual(len(entities), 1 if label and url else 0)
        if entities:
            e = entities[0]
            self.assertEqual((e.type, e.offset, e.length, e.url),
                             ('text_link', 0, len(label.encode('utf-16-le'))//2, url))
            self.assertIsNone(e.user)
            self.assertFalse(e.url.startswith(('https://t.me/', 'tg://')))
            self.assertEqual(caption.encode('utf-16-le')[:e.length*2].decode('utf-16-le'), label)

    async def deliver(self, provider, message, items, enabled=True, urls=None):
        async def handle(chat, url, send, **kwargs):
            await asyncio.sleep(0)  # Exercise the callback after yielding.
            return await send(items)
        options = dict(author_caption=enabled, reply_mode=False, delete_source=True)
        with patch.object(provider.service, 'handle', side_effect=handle):
            with patch.dict(provider.DELIVERY, **options) if hasattr(provider, 'DELIVERY') else patch.dict({}, {}):
                with self.assertRaises(SkipHandler):
                    if provider.__name__.endswith('instagram'):
                        await provider.instagram_video(message, instagram_urls=urls or [IG])
                    elif provider.__name__.endswith('x_video'):
                        await provider.x_video(message, urls or [X])
                    else:
                        await provider.idiod_video(message, urls or [D])

    async def test_x_idiod_cached_video_album_identity_disabled_and_overflow(self):
        from handlers import x_video as x, idiod_video as d
        from services.x_video import Item as XItem
        from services.idiod_video import Item as DItem
        for h, Item, url in [(x, XItem, X), (d, DItem, D)]:
            cases = [(NS(username='alice'), None, 'alice', True, COMMENT),
                     (NS(username='bob'), None, 'bob', True, COMMENT),
                     (NS(id=42, first_name='😀Name'), None, '😀Name', True, COMMENT),
                     (NS(username='GroupAnonymousBot'), NS(title='Private'), 'Private', True, COMMENT),
                     (NS(username='GroupAnonymousBot'), NS(title='😀Public', username='public_chat'), '😀Public', True, COMMENT),
                     (NS(username=None), None, '', True, COMMENT),
                     (NS(username='alice'), None, 'alice', True, '😀'*1100)]
            if h is x:
                cases.append((NS(username='alice'), None, '', False, COMMENT))
            for user, sender, label, enabled, comment in cases:
                for count in ((1, 2) if h is x else (1,)):
                    with self.subTest(provider=h.__name__, label=label, count=count, enabled=enabled):
                        m = self.message(url, user, sender, comment)
                        await self.deliver(h, m, [Item('cached-'+str(i), 1280, 720) for i in range(count)], enabled)
                        if count == 1:
                            args = m.bot.send_video.call_args.kwargs
                            caption, entities = args['caption'], args['caption_entities']
                            self.assertEqual(args['video'], 'cached-0'); self.assertIsNone(args['parse_mode'])
                        else:
                            media = m.bot.send_media_group.call_args.kwargs['media']
                            caption, entities = media[0].caption, media[0].caption_entities
                            self.assertIsNone(media[1].caption); self.assertEqual(media[1].caption_entities, [])
                            for i, item in enumerate(media):
                                self.assertEqual(item.media, 'cached-'+str(i)); self.assertIsNone(item.parse_mode)
                        self.scope(caption, entities, label, url)
                        self.assertEqual(caption, label if len(comment)>1024 else '\n'.join(filter(None, (label, comment))))
                        if len(comment)>1024: m.bot.delete_message.assert_not_awaited()

    async def test_instagram_single_cached_photo_video_and_first_album_only(self):
        from handlers import instagram as h
        from services.instagram_download import MediaItem
        for kinds in [('photo',), ('video',), ('photo', 'video'), ('video', 'photo')]:
            for username in ('alice', 'bob'):
                with self.subTest(kinds=kinds, username=username):
                    m = self.message(IG, NS(username=username, is_bot=False))
                    await self.deliver(h, m, [MediaItem(k, 'cached-'+k, 1280, 720) for k in kinds])
                    if len(kinds) == 1:
                        args = getattr(m.bot, 'send_'+kinds[0]).call_args.kwargs
                        self.assertEqual(args[kinds[0]], 'cached-'+kinds[0]); self.assertIsNone(args['parse_mode'])
                        self.assertEqual(args['caption'], username+'\n'+COMMENT)
                        self.scope(args['caption'], args['caption_entities'], username, IG)
                    else:
                        media = m.bot.send_media_group.call_args.kwargs['media']
                        self.scope(media[0].caption, media[0].caption_entities, username, IG)
                        self.assertEqual(media[0].caption, username+'\n'+COMMENT)
                        self.assertIsNone(media[1].caption); self.assertEqual(media[1].caption_entities, [])
                        for item, kind in zip(media, kinds):
                            self.assertEqual(item.media, 'cached-'+kind); self.assertIsNone(item.parse_mode)

    async def test_instagram_identity_utf16_sanitization_and_untrusted_comment(self):
        from handlers import instagram as h
        from services.instagram_download import MediaItem
        cases = [(NS(username=None, id=42, first_name='😀@A\nB', last_name='Z'), '😀A B Z', None),
                 (NS(username='alice'), 'alice', None),
                 (NS(username='bad/name', id=42), 'bad/name', None),
                 (NS(username=None, id=True, first_name='Name'), 'Name', None),
                 (NS(username=None, id=-1, first_name='Name'), 'Name', None),
                 (NS(username=None, first_name='A'*100), 'A'*80, None),
                 (NS(username='GroupAnonymousBot', id=1087968824), '😀Channel', NS(title='😀Channel', username='public_channel')),
                 (NS(username='GroupAnonymousBot', id=1087968824), 'Private', NS(title='Private')),
                 (NS(username='GroupAnonymousBot', id=1087968824), 'Anonymous', NS(title='Anonymous', username=None)),
                 (NS(username=None), '', None)]
        for user, label, sender in cases:
            with self.subTest(label=label):
                m = self.message(IG, user, sender)
                await self.deliver(h, m, [MediaItem('photo', 'cached-photo')])
                args = m.bot.send_photo.call_args.kwargs
                self.assertEqual(args['caption'], '\n'.join(filter(None, (label, COMMENT))))
                self.scope(args['caption'], args['caption_entities'], label, IG)
                self.assertIsNone(args['parse_mode'])

    async def test_instagram_disabled_overflow_and_unknown_photo_preserve(self):
        from handlers import instagram as h
        from services.instagram_download import MediaItem
        for enabled, comment, coverage in [(False, COMMENT, None), (True, '😀'*1100, None), (True, COMMENT, 'embed_first_image')]:
            with self.subTest(enabled=enabled, coverage=coverage):
                m = self.message(IG, comment=comment)
                await self.deliver(h, m, [MediaItem('photo', 'cached-photo', coverage=coverage)], enabled)
                args = m.bot.send_photo.call_args.kwargs
                self.scope(args['caption'], args['caption_entities'], 'alice' if enabled else '', IG)
                if len(comment)>1024: self.assertEqual(args['caption'], 'alice')
                if coverage or len(comment)>1024: m.bot.delete_message.assert_not_awaited()

    def test_missing_target_keeps_plain_label_without_profile_fallback(self):
        from services.repost_author import repost_author
        for user in [NS(username='alice'), NS(id=42, first_name='Name')]:
            m = self.message(IG, user)
            label, entities = repost_author(m)
            self.assertTrue(label)
            self.assertEqual(entities, [])
            self.assertEqual(repost_author(m, False), ('', []))

    async def test_multi_url_each_provider_same_cached_id_uses_current_post(self):
        from handlers import instagram as ig, x_video as x, idiod_video as d
        from services.instagram_download import MediaItem
        from services.x_video import Item as XItem
        from services.idiod_video import Item as DItem
        cases = [(ig, [IG, 'https://www.instagram.com/p/DEF/'], [MediaItem('photo', 'same-cache')], 'photo'),
                 (ig, [IG, 'https://www.instagram.com/p/DEF/'], [MediaItem('video', 'same-cache')], 'video'),
                 (ig, [IG, 'https://www.instagram.com/p/DEF/'], [MediaItem('photo', 'same-cache'), MediaItem('video', 'same-cache')], 'album'),
                 (x, [X, 'https://x.com/u/status/2'], [XItem('same-cache', 1280, 720)], 'video'),
                 (x, [X, 'https://x.com/u/status/2'], [XItem('same-cache', 1280, 720)]*2, 'album'),
                 (d, [D, 'https://idiod.video/other.mp4'], [DItem('same-cache', 1280, 720)], 'video')]
        for h, urls, items, kind in cases:
            with self.subTest(provider=h.__name__, kind=kind):
                m = self.message(' '.join(urls))
                await self.deliver(h, m, items, urls=urls)
                calls = getattr(m.bot, 'send_media_group' if kind == 'album' else 'send_'+kind).call_args_list
                self.assertEqual(len(calls), 2)
                targets = []
                for call, url in zip(calls, urls):
                    args = call.kwargs
                    if kind == 'album':
                        first, second = args['media']
                        caption, entities = first.caption, first.caption_entities
                        self.assertEqual(first.media, 'same-cache')
                        self.assertIsNone(second.caption); self.assertEqual(second.caption_entities, [])
                        self.assertIsNone(first.parse_mode); self.assertIsNone(second.parse_mode)
                    else:
                        caption, entities = args['caption'], args['caption_entities']
                        self.assertEqual(args[kind], 'same-cache'); self.assertIsNone(args['parse_mode'])
                    self.assertEqual(caption, 'alice\n'+COMMENT)
                    self.scope(caption, entities, 'alice', url)
                    targets.append(entities[0].url)
                self.assertNotEqual(*targets)

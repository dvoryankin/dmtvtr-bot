"""Regression for malformed Telegram UTF-16 entities before the TikTok router."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from aiogram.types import Message, Chat, MessageEntity
from handlers import x_video as x

X = 'https://x.com/u/status/1'
TT = 'https://www.tiktok.com/@sample/video/123456789'
CHAT = -1003911850060


class CurrentEntities(unittest.TestCase):
    def test_split_codeunit_retains_source_inventory(self):
        m = Message(message_id=1, date=datetime.now(timezone.utc),
                    chat=Chat(id=CHAT, type='supergroup'), text='😀 '+X+' '+TT,
                    entities=[MessageEntity(type='url', offset=1, length=2)])
        raw, urls = x.current(m)
        self.assertIn('', raw)
        self.assertEqual(urls, [X])
        self.assertIn(TT, raw)

    def test_invalid_bounds_and_types_veto_deletion(self):
        # Namespace deliberately bypasses aiogram/pydantic integer coercion.
        for offset, length in ((-1, 1), (0, 9999), (9999, 1), (0, 0),
                               (True, 1), (0, True), ('0', 1), (0, None)):
            with self.subTest(offset=offset, length=length):
                raw, urls = x.current(NS(text=X, entities=[NS(type='url', offset=offset, length=length)]))
                self.assertIn('', raw)
                self.assertEqual(urls, [X])

    def test_valid_utf16_entity_and_ordinary_x_unchanged(self):
        for entities in ([], [MessageEntity(type='url', offset=3, length=len(X))]):
            raw, urls = x.current(NS(text='😀 '+X, entities=entities))
            self.assertNotIn('', raw)
            self.assertEqual(urls, [X])
            self.assertTrue(all(x.canonical_url(u) for u in raw))

    def test_unencodable_text_fails_closed(self):
        raw, urls = x.current(NS(text='\ud800 '+X, entities=[]))
        self.assertIn('', raw)
        self.assertEqual(urls, [])


class Delivery(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_text_link_sends_x_but_retains_source(self):
        from aiogram.dispatcher.event.bases import SkipHandler
        from services.x_video import Item
        cases = [(-1, 1), (0, 9999), (9999, 1), (0, 0), (True, 1),
                 (0, True), ('0', 1), (0, None), (1, 2), (0, 2)]
        for offset, length in cases:
            with self.subTest(offset=offset, length=length):
                # Emoji spans [0,2); offset=1 splits it, offset=0,length=2 is valid.
                valid = type(offset) is int and type(length) is int and (offset, length) == (0, 2)
                m = NS(text='😀 '+X,
                       entities=[NS(type='text_link', offset=offset, length=length, url=X)],
                       chat=NS(id=CHAT, type='supergroup'), message_id=12, message_thread_id=None,
                       from_user=NS(username='alice', is_bot=False), sender_chat=None,
                       bot=NS(send_video=AsyncMock(return_value=NS(message_id=50, video=NS(file_id='cached'))),
                              delete_message=AsyncMock()))
                async def handle(chat, url, send, **kwargs):
                    return await send([Item('cached', 720, 1280)])
                with patch.object(x.service, 'handle', side_effect=handle), patch.dict(x.DELIVERY, enabled=True, reply_mode=False, delete_source=True):
                    self.assertEqual(await x.XFilter()(m), {'x_urls': [X]})
                    with self.assertRaises(SkipHandler):
                        await x.x_video(m, [X])
                m.bot.send_video.assert_awaited_once()
                self.assertEqual(m.bot.delete_message.await_count, 1 if valid else 0)

    async def test_malformed_inventory_sends_x_but_retains_source(self):
        from aiogram.dispatcher.event.bases import SkipHandler
        from services.x_video import Item
        for malformed in (True, False):
            m = NS(text='😀 '+X, entities=[NS(type='url', offset=1, length=2)] if malformed else [],
                   chat=NS(id=CHAT, type='supergroup'), message_id=11, message_thread_id=None,
                   from_user=NS(username='alice', is_bot=False), sender_chat=None,
                   bot=NS(send_video=AsyncMock(return_value=NS(message_id=50, video=NS(file_id='cached'))),
                          delete_message=AsyncMock()))
            async def handle(chat, url, send, **kwargs):
                return await send([Item('cached', 720, 1280)])
            with patch.object(x.service, 'handle', side_effect=handle), patch.dict(x.DELIVERY, enabled=True, reply_mode=False, delete_source=True):
                self.assertEqual(await x.XFilter()(m), {'x_urls': [X]})
                with self.assertRaises(SkipHandler):
                    await x.x_video(m, [X])
            m.bot.send_video.assert_awaited_once()
            self.assertEqual(m.bot.delete_message.await_count, 0 if malformed else 1)

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from aiogram.types import Message

class DemotivatorCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_requested_cases_route_and_preserve_args(self):
        from handlers.demotivator import router, handle_command
        event=next(x for x in router.message.handlers if x.callback is handle_command)
        command_filter=event.filters[0].callback
        bot=SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username='dmtvtr_bot')))
        for cmd in ['d','D','д','Д']:
            for suffix in ['', '@dmtvtr_bot']:
                with self.subTest(command=cmd+suffix):
                    msg=Message.model_validate({'message_id':1,'date':1700000000,'chat':{'id':-1003911850060,'type':'supergroup'},'text':'/'+cmd+suffix+' Текст НЕ менять','from':{'id':42,'is_bot':False,'first_name':'Test'}})
                    result=await command_filter(msg,bot)
                    self.assertIsInstance(result,dict)
                    self.assertEqual(result['command'].args,'Текст НЕ менять')
    async def test_other_commands_do_not_match(self):
        from handlers.demotivator import router, handle_command
        event=next(x for x in router.message.handlers if x.callback is handle_command)
        bot=SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username='dmtvtr_bot')))
        for cmd in ['help','dog','друг','D@other_bot']:
            msg=Message.model_validate({'message_id':1,'date':1700000000,'chat':{'id':-1003911850060,'type':'supergroup'},'text':'/'+cmd})
            self.assertFalse(await event.filters[0].callback(msg,bot))

import asyncio
import unittest
from pathlib import Path
from instagram_download import DownloadService

class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_consecutive_links_are_fifo_and_cleaned(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        order, directories = [], []
        async def runner(url, directory):
            order.append(url.rsplit('/', 2)[-2])
            directories.append(directory)
            entered.set()
            await release.wait()
            (directory / '01.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')
        async def send(items):
            return ['id']
        service = DownloadService(Path('/unused'), {-1}, runner=runner)
        tasks = [asyncio.create_task(service.handle(-1, 'https://instagram.com/p/%s/' % code, send)) for code in ['one', 'two', 'three']]
        await entered.wait()
        await asyncio.sleep(.02)
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(results, [None, None, None])
        self.assertEqual(order, ['one', 'two', 'three'])
        self.assertFalse(service.active)
        self.assertFalse(service.inflight)
        self.assertTrue(all(not p.exists() for p in directories))

    async def test_limits_cancel_and_network_capacity(self):
        from instagram_download import DownloadError
        running = 0
        maximum = 0
        entered = asyncio.Event()
        async def runner(url, directory):
            nonlocal running, maximum
            running += 1
            maximum = max(maximum, running)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                running -= 1
        async def send(items): self.fail('must not send')
        service = DownloadService(Path('/unused'), {-1, -2, -3}, runner=runner)
        tasks = [asyncio.create_task(service.handle(chat, 'https://instagram.com/p/p%s_%s/' % (abs(chat), i), send)) for chat in [-1,-2] for i in range(10)]
        await entered.wait()
        await asyncio.sleep(.03)
        try:
            self.assertEqual(service.pending, {-1:10, -2:10})
            self.assertEqual(maximum, 2)
            for chat in [-1,-3]:
                with self.assertRaises(DownloadError):
                    await service.handle(chat, 'https://instagram.com/p/overflow/', send)
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertFalse(service.pending)
        self.assertFalse(service.chat_locks)
        self.assertFalse(service.inflight)
        self.assertFalse(service.active)
        self.assertEqual(running, 0)

    async def test_queue_timeout_removes_reservation(self):
        from instagram_download import DownloadError
        entered = asyncio.Event()
        async def runner(url, directory):
            entered.set()
            await asyncio.Event().wait()
        async def send(items): self.fail('must not send')
        service = DownloadService(Path('/unused'), {-1}, runner=runner)
        first = asyncio.create_task(service.handle(-1, 'https://instagram.com/p/one/', send))
        await entered.wait()
        service.queue_timeout = .01
        try:
            with self.assertRaisesRegex(DownloadError, 'timeout'):
                await service.handle(-1, 'https://instagram.com/p/two/', send)
            self.assertEqual(service.pending, {-1: 1})
        finally:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        self.assertFalse(service.pending)

class StartupTests(unittest.TestCase):
    def test_service_created_before_runtime_loop(self):
        # Mirrors module-level service creation followed by bot asyncio.run().
        initial = asyncio.new_event_loop()
        asyncio.set_event_loop(initial)
        async def runner(url, directory):
            await asyncio.sleep(.02)
            (directory / '01.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom')
        async def send(items): return ['id']
        service = DownloadService(Path('/unused'), {-1,-2,-3}, runner=runner)
        async def execute():
            results = await asyncio.gather(*(service.handle(chat, 'https://instagram.com/p/a%s/' % abs(chat), send) for chat in [-1,-2,-3]), return_exceptions=True)
            self.assertEqual(results, [None,None,None])
        try:
            asyncio.run(execute())
        finally:
            initial.close()
            asyncio.set_event_loop(None)

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from services import tiktok_video_worker as w


class DiskGate(unittest.TestCase):
    def test_reserved_control_space_and_existing_files(self):
        fmt = {'url':'https://v16-webapp-prime.tiktok.com/video/test', 'filesize':1810,
               'vcodec':'h264', 'acodec':'aac', 'ext':'mp4'}
        info = {'duration':16, 'formats':[fmt]}
        with tempfile.TemporaryDirectory() as raw, patch.object(w, 'MAX_FILE', 10000):
            directory = Path(raw)
            (directory/'aux').write_bytes(b'x'*100)
            def receive(selected, target): target.write_bytes(b'x'*1810)
            with patch.object(w, 'download', side_effect=receive), patch.object(w, 'probe_file', return_value=(720,1280)), patch('services.tiktok_video.validate_files', return_value=[]):
                with self.assertRaises(w.WorkerError): w.process_info(info, directory)
            self.assertEqual((directory/'aux').stat().st_size, 100)
            self.assertFalse((directory/'video.mp4').exists())


    def test_control_writes_never_overflow_or_delete_auxiliary(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(w, 'MAX_FILE', 120):
            directory = Path(raw)
            aux = directory/'aux'; aux.write_bytes(b'x'*110)
            with self.assertRaises(w.WorkerError): w.write_diagnostic(directory, 'ok')
            self.assertEqual(w.disk_usage(directory), 110)
            self.assertFalse((directory/'diagnostic.json').exists())
            aux.unlink()
            (directory/'unexpected').mkdir()
            with self.assertRaises(w.WorkerError): w.disk_usage(directory)
            (directory/'unexpected').rmdir()
            (directory/'link').symlink_to(aux)
            with self.assertRaises(w.WorkerError): w.disk_usage(directory)

    def test_preexisting_video_not_deleted_on_exclusive_failure(self):
        class Response(io.BytesIO):
            headers = {'Content-Length':'12'}
            def geturl(self): return 'https://v16-webapp-prime.tiktok.com/video/test'
        class Opener:
            def open(self, *args, **kwargs): return Response(b'0000ftypisom')
        with tempfile.TemporaryDirectory() as raw, patch.object(w.urllib.request, 'build_opener', return_value=Opener()):
            target = Path(raw)/'video.mp4'; target.write_bytes(b'original')
            with self.assertRaises(FileExistsError): w.download({'url':Response().geturl()}, target)
            self.assertEqual(target.read_bytes(), b'original')

if __name__ == '__main__': unittest.main()

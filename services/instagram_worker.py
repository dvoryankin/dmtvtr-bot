"""Disposable, credential-free yt-dlp worker (isolated Python >=3.10)."""
from pathlib import Path
import resource
import signal
import sys

# -I removes cwd/PYTHONPATH; import only our explicitly selected sibling modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from instagram_download import canonical_url, validate_files, MAX_FILE, MAX_TOTAL, MAX_ITEMS
from instagram_network import install_network_guard
from instagram_diagnostics import Diagnostic, classify
from instagram_photos import download_photo
from instagram_download import media_value
import json


def extract_media(dl, url, directory):
    try:
        dl.extract_info(url, download=True)
        files = validate_files(directory, decode_photos=False)
    except Exception as exc:
        if classify(exc)['code'] != 'no_video':
            raise
        download_photo(url, directory)
        files = validate_files(directory, decode_photos=False)
    if not (directory / 'manifest.json').exists():
        (directory / 'manifest.json').write_text(json.dumps({
            'version': 1, 'coverage': 'extracted_videos',
            'items': [{'type': 'video', 'file': media_value(p).name} for p in files]}))
    return files


def check_disk(directory):
    files = [p for p in directory.iterdir() if p.is_file()]
    if sum(p.stat().st_size for p in files) > MAX_TOTAL:
        raise ValueError('Total size limit exceeded')


def build_options(directory):
    return {
        'format': 'best[ext=mp4][protocol=https]',
        'outtmpl': str(directory / '%(autonumber)02d.%(ext)s'),
        'restrictfilenames': True,
        'proxy': '', 'cachedir': False, 'cookiefile': None,
        'socket_timeout': 10, 'retries': 0, 'extractor_retries': 0,
        'fragment_retries': 0, 'file_access_retries': 0,
        'max_filesize': MAX_FILE, 'playlistend': MAX_ITEMS,
        'max_downloads': MAX_ITEMS, 'noplaylist': False,
        'fixup': 'never', 'postprocessors': [],
        'writethumbnail': False, 'writeinfojson': False,
        'writesubtitles': False, 'writeautomaticsub': False,
        'quiet': True, 'no_warnings': True, 'noprogress': True,
        'allow_unplayable_formats': False,
        'progress_hooks': [lambda _: check_disk(directory)],
    }


def main():
    url = canonical_url(sys.argv[1])
    directory = Path(sys.argv[2]).resolve()
    if not url or not directory.is_dir():
        return 2
    # Hard backstops if parent disappears; parent also kills on timeout/cancel.
    signal.alarm(70)
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE, MAX_FILE))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    install_network_guard()
    diagnostic = Diagnostic(directory)
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.instagram import InstagramIE
    from yt_dlp.networking._urllib import UrllibRH

    class GuardedDL(YoutubeDL):
        def process_info(self, info_dict):
            diagnostic.set_phase('media')
            return super().process_info(info_dict)

        def build_request_director(self, handlers, preferences=None):
            # Do not permit curl/requests, whose resolution bypasses socket guards.
            return super().build_request_director([UrllibRH], preferences)

    try:
        options = build_options(directory)
        options.update(logger=diagnostic, no_warnings=False)
        diagnostic.set_phase('metadata')
        with GuardedDL(options, auto_init=False) as dl:
            dl.add_info_extractor(InstagramIE())
            extract_media(dl, url, directory)
        diagnostic.set_phase('validation')
        check_disk(directory)
        files = validate_files(directory, decode_photos=False)
        diagnostic.phase = 'complete'
        diagnostic.write(ok=True)
        print('OK files=%d bytes=%d' % (len(files), sum(media_value(p).stat().st_size for p in files)))
        return 0
    except Exception as exc:
        diagnostic.write(exc)
        # Never print exception text/provider payloads into bot logs/chat.
        print('DOWNLOAD_FAILED %s' % type(exc).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

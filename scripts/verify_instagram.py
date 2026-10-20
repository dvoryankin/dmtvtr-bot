"""Real download verification with a local sink; NEVER calls Telegram or an LLM."""
import asyncio
from pathlib import Path
import shutil
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from services.instagram_download import DownloadService, canonical_url, media_value, media_type


async def main():
    url = canonical_url(sys.argv[1]) if len(sys.argv) > 1 else None
    if not url:
        raise SystemExit('Usage: venv/bin/python scripts/verify_instagram.py HTTPS_INSTAGRAM_REEL_URL')
    output = BASE / 'instagram-verification'
    output.mkdir(mode=0o700, exist_ok=True)
    temporary = []
    async def local_sink(files):
        temporary.extend(media_value(item) for item in files)
        for item in files:
            p = media_value(item)
            target = output / p.name
            shutil.copyfile(p, target)
            print('DOWNLOADED %s bytes=%d type=%s width=%s height=%s' % (
                target, target.stat().st_size, media_type(item),
                getattr(item, 'width', None), getattr(item, 'height', None)))
        # Deliberately no Telegram file IDs: this is a local-only sink.
        return []
    await DownloadService(BASE, {-1}).handle(-1, url, local_sink)
    assert temporary and all(not p.exists() for p in temporary), 'temporary files leaked'
    print('TEMP_CLEANUP_OK; no Telegram calls')


if __name__ == '__main__':
    asyncio.run(main())

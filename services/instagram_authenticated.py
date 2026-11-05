"""Session-only API extraction. Never invokes login, embed, or anonymous fallback.

Session-accessible media is permitted regardless of audience/owner privacy.
An exact, complete typed API inventory remains mandatory; no access bypass.
"""
import json
from instagram_download import DownloadError, MAX_ITEMS, validate_files, media_value
from instagram_photos import fetch, photo_extension, MAX_PHOTO, validate_fetch_url


def extract_authenticated(dl, url, directory):
    from yt_dlp.networking import Request
    from yt_dlp.extractor.instagram import _id_to_pk
    shortcode = url.rstrip('/').rsplit('/', 1)[-1]
    media_id = str(_id_to_pk(shortcode))
    request = Request('https://i.instagram.com/api/v1/media/%s/info/' % media_id,
                      headers={'X-IG-App-ID': '936619743392459',
                               'Accept-Encoding': 'identity'})
    with dl.urlopen(request) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise DownloadError('inventory_incomplete')
    try:
        result = json.loads(payload)
        if result.get('status') != 'ok' or len(result['items']) != 1:
            raise ValueError()
        product = result['items'][0]
        if str(product['pk']) != media_id:
            raise ValueError()
        kind = product['media_type']
        if type(kind) is not int or kind not in (1, 2, 8):
            raise ValueError()
        if kind == 8:
            items = product['carousel_media']
            count = product['carousel_media_count']
            if type(count) is not int or not isinstance(items, list) or count != len(items):
                raise ValueError()
        else:
            if product.get('carousel_media') or product.get('carousel_media_count'):
                raise ValueError()
            items = [product]
        if not 1 <= len(items) <= MAX_ITEMS:
            raise ValueError()
        plans, ids = [], set()
        for item in items:
            pk = str(item['pk'])
            if not pk.isdigit() or pk in ids:
                raise ValueError()
            ids.add(pk)
            if type(item['media_type']) is not int:
                raise ValueError()
            if item['media_type'] == 1:
                candidates = item['image_versions2']['candidates']
                target = validate_fetch_url(candidates[0]['url'])
                plans.append(('photo', target))
            elif item['media_type'] == 2:
                formats = []
                for variant in item['video_versions']:
                    formats.append({'url': validate_fetch_url(variant['url']), 'ext':'mp4',
                                    'width': variant.get('width'), 'height': variant.get('height')})
                if not formats:
                    raise ValueError()
                plans.append(('video', {'id': pk, 'title': 'Instagram media', 'formats': formats}))
            else:
                raise ValueError()
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise DownloadError('inventory_incomplete') from None
    entries = []
    # No files are created until the whole raw inventory has passed admission.
    for index, (kind, plan) in enumerate(plans, 1):
        if kind == 'photo':
            data = fetch(plan, MAX_PHOTO)  # deliberately credential-free CDN fetch
            name = '%02d' % index + photo_extension(data)
            (directory / name).write_bytes(data)
        else:
            before = set(directory.glob('*.mp4'))
            dl.process_ie_result(plan, download=True)
            created = set(directory.glob('*.mp4')) - before
            if len(created) != 1 or any(directory.glob('*.part')):
                raise DownloadError('inventory_incomplete')
            name = created.pop().name
        entries.append({'type': kind, 'file': name})
    # Publish completeness only after every item has actually downloaded.
    (directory / 'manifest.json').write_text(json.dumps({
        'version': 1, 'coverage': 'complete', 'items': entries}))
    return validate_files(directory, decode_photos=False)

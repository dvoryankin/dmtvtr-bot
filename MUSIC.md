# Music link matching

`handlers/music.py` is registered immediately after Instagram. It handles only
current text messages in the three groups in `config/instagram_chats.json`.
No DMs, bots, media captions/attachments, commands, reply/history lookup, or
general YouTube links. The first current URL (including text-link entities)
must be a supported HTTPS track URL. Set `MUSIC_ENABLED=0` to disable.

`services/music_match.py` uses public Songlink HTML, not its deprecated API.
It sends canonical URLs through `https://song.link/<percent-encoded-url>` and
extracts the first page title and actual provider anchors. It emits only
allowlisted Spotify, Apple Music, Deezer, Yandex Music, SoundCloud, YouTube Music
and Tidal track links found on the page. Missing/unrecognized platforms are not
invented and search links are not emitted. No audio is downloaded.

Transport: only HTTPS song.link:443, public DNS answers checked and passed as
numeric connection addresses with original TLS hostname; proxies disabled;
maximum four HTTP requests, 20-second overall deadline, 2 MiB HTML limit;
compression refused (identity requested), <=2 in-flight jobs, 128-entry/15-minute
success cache. Busy/failure replies are explicit. HTTP 401 is not bypassed.

Tests (main Python 3.8 bot virtualenv):

```
cd /root/bots
PYTHONPATH=.:services venv/bin/python -m unittest discover -s tests -v
```

Live check uses `await MatchService().match(url)` and `render(result)` from the
same production service. User Spotify track `5VykLQtjCYF6qFq59HbUg9` returned
Sen Bilmezsin by Dedublüman, Spotify, Deezer 2684821152, Tidal 348475585,
Yandex Music 123294914. No Telegram send/restart was performed during install.

Existing dirty router registration was backed up to
`.music-backup-20261005T135609Z/handlers-init.py`; its pre-feature Git diff is
`baseline.diff` in that directory. No Instagram modules/config were changed.

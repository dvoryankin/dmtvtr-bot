# Instagram public-video replies

Status: files installed and tested; **service NOT restarted**. Existing bot Python
3.8 and requirements are untouched. Downloader runs separately with Python 3.12
in `.instagram-venv`, yt-dlp pinned in `requirements-instagram.txt`.

## Scope / behavior

- Bare HTTPS Instagram `reel`, `p`, `tv` URLs in current group text/text-link
  entities trigger a reply video. Tracking and fragments are removed. Reply
  history is never inspected; any existing media attachment skips the handler.
- Public **videos only**; photo posts, stories, private/login-required content
  are not supported. No cookies, login, paid services, or LLM calls.
- Up to three distinct posts per message; up to ten supported MP4 entries per post as an
  album. Unsupported/oversized entries may be omitted by yt-dlp. No transcoding.
- `config/instagram_chats.json` is a frozen list of the seven group chat IDs
  already recorded in ratings.sqlite3. No newly joined group gains automatic
  access. Review this list before activation; membership in historical data is
  not a new grant of permission. Private chats and bot senders are ignored.
- `INSTAGRAM_ENABLED=0` disables matching after environment is loaded.
- Bot must receive ordinary group messages (administrator or BotFather privacy
  disabled). Tests do not alter BotFather settings or post to real chats.
- Instagram router runs first, then raises SkipHandler so original routers still
  see the message. Existing X/TikTok fix-link behavior is unchanged.

## Bounds and security

- Bounded FIFO admission: ten jobs per chat, twenty globally (including active
  jobs); two active operations globally, one per chat. No completion cooldown.
  Same URL already admitted is suppressed. Maximum queue wait: 900 seconds.
  Cancellation releases pending/active reservations and locks.
- Automatic handling is silent: no starting/busy/no-video/failure Telegram text.
  Only successful media sends; failures are classified in sanitized logs.
- Per-operation 90-second deadline after admission to active processing; at most
  three transient download attempts (28 seconds each), fresh temporary directory
  per attempt, bounded backoff. Worker alarm 70 seconds, 45 CPU seconds,
  512 MiB address space. Upload max 60 seconds within remaining deadline.
  Telegram delivery is never retried. Parent kills/reaps worker on timeout or
  cancellation; temporary directories removed on handled exits (not SIGKILL).
- 45 MiB per file, 90 MiB aggregate, ten files; disk/progress checks and OS
  per-file hard limit. Verify MP4 signature before sending.
- Telegram file-ID cache: one hour, 128 URLs, memory only. Stale Telegram IDs
  are evicted on send failure. No media is retained by the normal bot path.
- Clean child environment, isolated interpreter, no shell invocation; no
  downloaded filenames/titles are used as paths or chat markup.
- Worker exclusively uses yt-dlp's stdlib urllib handler. All DNS answers must
  be public and belong to Instagram/Meta CDN host suffixes; the actual socket
  connect IP is rechecked and must be public on port 443. Redirects go through
  the same guard. No proxies, curl HTTP backend, generic extractor, external
  downloader, HLS download, ffmpeg postprocessing or persistent cookies.
- Metadata processing is bounded by worker memory/deadline; redirects by urllib.
  Instagram rate limits can still make some public videos unavailable.

## Reproduce isolated setup (no service restart)

```sh
cd /root/bots
venv/bin/python -m pip install --target .instagram-bootstrap uv==0.11.2
.instagram-bootstrap/bin/uv venv --python 3.12 .instagram-venv
.instagram-bootstrap/bin/uv pip install --python .instagram-venv/bin/python -r requirements-instagram.txt
```

Python was installed by uv under `/root/.local/share/uv/python/`; retain it with
`.instagram-venv`. Do not upgrade the main bot environment for this feature.

## Verify without Telegram / LLM traffic

```sh
cd /root/bots
PYTHONPATH=services venv/bin/python -m unittest discover -s tests -p 'test_instagram*.py' -v
venv/bin/python -m compileall -q services/instagram_download.py services/instagram_network.py services/instagram_worker.py handlers/instagram.py handlers/__init__.py
venv/bin/python scripts/verify_instagram.py 'https://www.instagram.com/reel/DWuGIV2iTcr/'
ffprobe -v error -show_entries format=duration,size:stream=codec_type,codec_name,width,height -of json instagram-verification/01.mp4
```

Actual guarded download and the main Python 3.8 service wrapper both succeeded:
`instagram-verification/01.mp4`, **4,005,419 bytes**, **32.414 seconds**, H.264
720×1280 + AAC. The local-sink check confirmed temporary-file cleanup. This is
real Instagram media, not a fixture. Telegram sending was tested only with mocks.
The verification script intentionally retains one local artifact; delete the
`instagram-verification` directory when no longer needed.

## Activation / rollback (parent operator only)

No restart, commit or push was performed. Check the diff and frozen chat scope,
then restart only `dmtvtr-bot.service` when approved and verify polling logs.
Before edits the only tracked changed file (`handlers/__init__.py`) was backed
up with mode/owner preserved to
`.instagram-backup-20261002T221755Z/handlers-init.py`; that directory also contains
baseline git diff/status. The pre-existing untracked quiz/cleanup/log files were
not changed. To detach the feature, restore the backed-up router file (or remove
its two Instagram lines) and restart the service as a separate approved action.

## 2026-10-05 silent-queue verification and photo blocker

Queue/handler edits installed without restart; 33 regression tests pass under
`PYTHONPATH=services:. venv/bin/python -m unittest discover -s tests -v`.
RED/GREEN covered FIFO links, silent failures, multi-link current-message scope,
classified logs, and the Python 3.8 import-time semaphore/different-loop failure.
Counters/concurrency, queue cancellation/timeout and worker cleanup also tested.

Exact-URL guarded worker probes (one invocation each, no Telegram):
- `p/DdfOOUKTV3j/`: `no_video`, no media downloaded.
- `reel/DeElLYQNnVM/`: `01.mp4`, 594248 bytes; ffprobe confirms H.264
  720x1280 + AAC, duration 13.351 seconds.
- `p/Dd9MZl4NKmg/`: `no_video`, no media downloaded.
Artifacts and sanitized diagnostics: `instagram-verification/queue-20261005/`.

**Photo/carousel support is NOT implemented or verified.** Public pages of both
photo examples returned HTTP 200 but no `display_url`, `video_url`,
`image_versions2` or `edge_sidecar_to_children` metadata. Public embeds supplied
`EmbeddedMediaImage` but not a verified original-media inventory. No thumbnail,
avatar, or potentially incomplete carousel was substituted for original media.
No login, private endpoint or access bypass was added. This is a partial delivery,
not completion of the requested photo+video feature.

Backup with original file modes and baseline git diff/status:
`.instagram-queue-backup-20261005T153515Z/`. Feature-only patch is stored there.
No music code, downloader worker, network guard, credentials or model config was
changed. Parent operator owns restart/activation; this change has not been activated.

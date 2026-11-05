# Optional Instagram session

Instagram remains anonymous-first. A separately provisioned session of a dedicated
account can enable a bounded authenticated fallback for media accessible to that
account. Owner privacy and audience labels are not an additional download filter:
private, follower-only or Close Friends media is allowed when the session itself
has access. This is not an access bypass or a password-based login service.
Supported URL routes are unchanged; this does not add story/profile browsing.
Unknown/incomplete media inventories are still rejected.

## Provisioning boundary

The runtime session file is fixed, outside this repository:

```
/root/.config/dmtvtr-instagram-auth/session.cookies.txt
```

The owning directory must be root-owned mode `0700`; the regular, non-symlink,
single-link file must be root-owned mode `0600`, at most 32 KiB, and use Netscape
cookies.txt format. Provision only `sessionid`, `csrftoken`, `ds_user_id`,
`mid` and `ig_did`; remove unrelated browser-state cookies and session-only
`rur` from the provisioned copy, without changing the browser's original export.
Export only Instagram cookies from a dedicated browser
profile. Never export the browser's complete cookie database. Never commit or
print session cookies, passwords, raw HTTP headers or signed media URLs.

An absent file leaves anonymous behavior available. An invalid or expired file
must fail closed for authenticated work. The bot never discovers browser
profiles, stores a password, requests verification codes, refreshes a session or
retries login. Renew the file manually from the dedicated account when needed.
Changing permissions, deleting the file or revoking the session disables its
future use; an already active worker may finish its bounded attempt.

## Runtime contract

- Existing configured chat scope, URL admission, queues and delivery receipts stay
  in force. This feature is not a new grant of access to other chats.
- Try the anonymous path first. Permit at most one authenticated attempt within
  the existing overall job deadline, using a fresh media directory; never combine
  anonymous and authenticated partial files.
- Authentication must not retry rate limits, challenges, safety denials, generic
  access errors or timeouts. Clean metadata-only `empty_media` (optionally with
  `csrf_missing`) or explicit login/age evidence may enable one bounded session-accessible
  inventory verification. Any ambiguous, non-metadata or truncated diagnostic
  history vetoes authentication, including failures in earlier attempts. All
  public/authenticated launches share the existing three-attempt job budget.
- The parent passes a read-only descriptor to a disposable worker. Values never
  enter argv, environment, logs, manifests, cache keys or media filenames. The
  cookie jar is volatile and is never written back.
- Cookies and authorization material are confined to exact approved Instagram
  API hosts, not suffix matches or CDN hosts. Redirects and extractor-provided
  headers must respect the same boundary. Existing public-address/DNS/connect,
  HTTPS, file, memory, byte and time guards remain mandatory.
- Authenticated extraction requires an exact matching media ID and a complete,
  ordered, typed inventory returned successfully to the session. Privacy/audience
  fields are not admission gates. Truncated carousels, missing items, unknown
  media types or exceeded limits fail the whole post. No anonymous embed downgrade.
- Telegram delivery and source deletion rules are unchanged: no deletion after
  a failed/partial/ambiguous send; author attribution targets the original post.

## Verification

Session acquisition, a successful metadata request, an isolated real download,
an installed service-wrapper download and an actual Telegram send are distinct
checks. A metadata success is not an installation or delivery proof. Network
acceptance is performed by the operator without posting test messages to groups.

Offline regression tests cover the private-file boundary, descriptor lifecycle,
request-header/redirect isolation, fallback budget, complete inventory, resource
limits and the legacy anonymous/YouTube/TikTok behavior. Use the main Python 3.8
runtime and the isolated modern worker runtime separately where required.

Credentials are deployment data, not release artifacts. Publish code and tests
only, after independent source/install review and real no-send acceptance.

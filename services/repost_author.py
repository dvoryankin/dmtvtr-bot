"""Sanitized uploader labels linking only an explicitly supplied source post."""
import unicodedata
from aiogram.types import MessageEntity


def url_entities_covered(text, entities, canonicalizer, processed_urls):
    """Deletion-only inventory: uncertain Telegram UTF-16 entities retain source.

    Never normalize bare domains into fetch targets. Explicit HTTP URL fallback
    and delivery/coverage confirmation remain the caller's separate gates.
    """
    try:
        encoded = text.encode('utf-16-le')
        link_spans = []
        non_links = {'mention', 'hashtag', 'cashtag', 'bot_command', 'email',
                     'phone_number', 'bold', 'italic', 'underline', 'strikethrough',
                     'spoiler', 'blockquote', 'expandable_blockquote', 'code',
                     'pre', 'text_mention', 'custom_emoji'}
        for entity in entities:
            offset, length = entity.offset, entity.length
            if (type(offset) is not int or type(length) is not int
                    or offset < 0 or length <= 0
                    or (offset + length) * 2 > len(encoded)):
                return False
            # Strict decoding rejects either boundary splitting a surrogate pair.
            start = len(encoded[:offset * 2].decode('utf-16-le'))
            end = len(encoded[:(offset + length) * 2].decode('utf-16-le'))
            if entity.type == 'url':
                raw = text[start:end].rstrip(".,!?:;)]}\"'")
            elif entity.type == 'text_link':
                raw = entity.url
                if not isinstance(raw, str) or not raw:
                    return False
            elif entity.type in non_links:
                continue
            else:
                return False
            # Conflicting/duplicate clickable spans have no unambiguous inventory.
            if any(start < other_end and other_start < end
                   for other_start, other_end in link_spans):
                return False
            link_spans.append((start, end))
            url = canonicalizer(raw)
            if not url or url not in processed_urls:
                return False
        return True
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return False


def repost_author(message, enabled=True, source_url=None):
    if not enabled:
        return '', []
    sender = getattr(message, 'sender_chat', None)
    identity = sender if sender is not None else getattr(message, 'from_user', None)
    username = getattr(identity, 'username', None)
    if sender is not None:
        label = getattr(sender, 'title', '') or username or ''
    else:
        label = username or ' '.join(filter(None, (getattr(identity, 'first_name', ''),
                                                   getattr(identity, 'last_name', ''))))
    label = ''.join(' ' if unicodedata.category(c).startswith('C') else c
                    for c in label).replace('@', '')[:80].strip()
    # Callers supply their already validated current provider URL, never a
    # Telegram identity or cached media metadata. Missing source stays plain.
    url = source_url
    entities = [MessageEntity(type='text_link', offset=0,
                             length=len(label.encode('utf-16-le')) // 2, url=url)] if label and url else []
    return label, entities

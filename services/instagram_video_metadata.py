"""Bounded, read-only display geometry for local Instagram uploads."""
import asyncio
import json
import logging
import math
import re
from fractions import Fraction
from pathlib import Path

MAX_DIMENSION = 8192
MAX_OUTPUT = 64 * 1024
PROBE_TIMEOUT = 4


def valid_dimensions(width, height):
    return (type(width) is int and type(height) is int
            and 0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION)


def _ratio(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,9}[:/][0-9]{1,9}', value):
        raise ValueError()
    numerator, denominator = map(int, re.split('[:/]', value))
    if not numerator or not denominator:
        raise ValueError()
    return Fraction(numerator, denominator)


def display_dimensions(data):
    try:
        stream = data['streams'][0]
        width, height = stream['width'], stream['height']
        if not valid_dimensions(width, height):
            return None
        sar = stream.get('sample_aspect_ratio')
        dar = stream.get('display_aspect_ratio')
        if sar not in (None, 'N/A', '0:1'):
            width = round(width * _ratio(sar))
        elif dar not in (None, 'N/A', '0:1'):
            width = round(height * _ratio(dar))
        rotation = stream.get('tags', {}).get('rotate', 0)
        for side in stream.get('side_data_list', []):
            if 'rotation' in side:
                rotation = side['rotation']
                break
        if isinstance(rotation, bool) or not re.fullmatch(r'-?[0-9]{1,6}(?:\.[0-9]{1,6})?', str(rotation)):
            return None
        rotation = float(rotation)
        if not math.isfinite(rotation) or rotation % 90:
            return None
        if rotation % 180:
            width, height = height, width
        return (width, height) if valid_dimensions(width, height) else None
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        return None


async def probe_video_dimensions(path):
    if not isinstance(path, Path):
        return None
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_streams', '-of', 'json', str(path.resolve()),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=MAX_OUTPUT)
        async def read_result():
            chunks = []
            size = 0
            while True:
                chunk = await process.stdout.read(min(8192, MAX_OUTPUT + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_OUTPUT:
                    raise ValueError()
                chunks.append(chunk)
            code = await process.wait()
            if code:
                raise ValueError()
            return display_dimensions(json.loads(b''.join(chunks)))
        result = await asyncio.wait_for(read_result(), PROBE_TIMEOUT)
        if result is None:
            logging.warning('Instagram video metadata unavailable code=invalid')
        return result
    except (OSError, ValueError, UnicodeError, asyncio.TimeoutError):
        logging.warning('Instagram video metadata unavailable code=probe_failed')
        return None
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            async def reap():
                # Drain the bounded pipe after kill: wait() alone can deadlock
                # when the pipe transport is paused by its buffer limit.
                while await process.stdout.read(8192):
                    pass
                await process.wait()
            await asyncio.shield(reap())

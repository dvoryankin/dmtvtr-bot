from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sqlite3
import time

from services.aquastar_service import AquaStarError, get_current_load
from utils.asyncio_utils import run_in_thread


_COLLECT_INTERVAL_SECONDS = 30 * 60
_MOSCOW_TZ = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class AquaStarSample:
    ts: int
    people: int


@dataclass(frozen=True)
class AquaStarHourSummary:
    hour: int
    average_people: float
    sample_count: int


@dataclass(frozen=True)
class AquaStarStatsSummary:
    samples: tuple[AquaStarSample, ...]
    average_people: float
    min_sample: AquaStarSample
    max_sample: AquaStarSample
    quietest_hours: tuple[AquaStarHourSummary, ...]


class AquaStarStatsStorage:
    def __init__(self, *, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS aquastar_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    people INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_aquastar_samples_ts
                ON aquastar_samples(ts)
                """
            )

    def add_sample(self, *, people: int, ts: int | None = None) -> None:
        timestamp = int(time.time()) if ts is None else ts
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO aquastar_samples(ts, people) VALUES(?, ?)",
                (timestamp, people),
            )

    def summary(self, *, since_ts: int) -> AquaStarStatsSummary | None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, people
                FROM aquastar_samples
                WHERE ts >= ?
                ORDER BY ts
                """,
                (since_ts,),
            ).fetchall()

        samples = tuple(AquaStarSample(ts=int(row["ts"]), people=int(row["people"])) for row in rows)
        if not samples:
            return None

        by_hour: dict[int, list[int]] = {}
        for sample in samples:
            hour = datetime.fromtimestamp(sample.ts, tz=_MOSCOW_TZ).hour
            by_hour.setdefault(hour, []).append(sample.people)

        quietest_hours = tuple(
            sorted(
                (
                    AquaStarHourSummary(
                        hour=hour,
                        average_people=sum(values) / len(values),
                        sample_count=len(values),
                    )
                    for hour, values in by_hour.items()
                ),
                key=lambda item: (item.average_people, item.hour),
            )[:5]
        )
        return AquaStarStatsSummary(
            samples=samples,
            average_people=sum(sample.people for sample in samples) / len(samples),
            min_sample=min(samples, key=lambda sample: (sample.people, sample.ts)),
            max_sample=max(samples, key=lambda sample: (sample.people, -sample.ts)),
            quietest_hours=quietest_hours,
        )


class AquaStarStatsService:
    def __init__(self, *, db_path: Path) -> None:
        self._storage = AquaStarStatsStorage(db_path=db_path)

    def init_db(self) -> None:
        self._storage.init_db()

    async def collect(self) -> None:
        load = await get_current_load()
        await run_in_thread(self._storage.add_sample, people=load.people)
        logging.info("AquaStar background sample collected: %s visitors", load.people)

    async def summary(self, *, period_seconds: int) -> AquaStarStatsSummary | None:
        since_ts = int(time.time()) - period_seconds
        return await run_in_thread(self._storage.summary, since_ts=since_ts)


async def collect_aquastar_stats(stats: AquaStarStatsService) -> None:
    while True:
        try:
            await stats.collect()
        except AquaStarError as exc:
            logging.warning("AquaStar background sample failed: %s", exc)
        except Exception:
            logging.exception("Unexpected AquaStar background sample failure")
        await asyncio.sleep(_COLLECT_INTERVAL_SECONDS)


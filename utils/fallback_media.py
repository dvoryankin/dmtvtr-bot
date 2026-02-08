from __future__ import annotations

from pathlib import Path
from shutil import copy2
import logging
import random

from aiogram import Bot


_STICKER_PACKS: tuple[str, ...] = (
    "sp031fedcbc4e438a8984a76e28c81713d_by_stckrRobot",
    "sp70cc950ed11089c18703860f5419aa27_by_stckrRobot",
    "sp5e6aec1cfbfc458c3166a9bbb80e4bf2_by_stckrRobot",
    "sp40ba02f59a1bd3f647b89178bf001829_by_stckrRobot",
    "JowFaderMitch_by_fStikBot",
    "pa_PzVnv4JOlkayQOj8W8LQ_by_SigStick20Bot",
    "OninationSquadAnimStickers",
    "PerdunMorjopa_by_fStikBot",
    "vDfCbyQ_by_achestickbot",
    "woodcum",
    "ShooBeDoo",
    "pchellovod85434_by_sportsmem_bot",
    "pchellovod7569_by_sportsmem_bot",
    "l8da2e0PmqVX0fArOJ7A5vlCc_by_literalmebot",
    "vdyrky",
    "pchellovod78493_by_sportsmem_bot",
    "f_weyjrjak_896383854_by_fStikBot",
    "pchellovod84489_by_Kinopoisk_Memes_bot",
    "Hiroon_RafGrassetti",
    "with_love_for_680300712_by_msu_hub_bot",
    "with_love_for_1001414584186_by_msu_hub_bot",
    "dedobemebykot",
    "igorvikhorkov_by_fStikBot",
    "horsestikerisfiu_by_fStikBot",
    "with_love_for_1001615989157_by_msu_hub_bot",
    "peepee_poopoo",
    "Miss_evidence",
    "set_2900_by_makestick3_bot",
    "GamingYarAnimated",
    "Fortrach",
    "mihalpalich",
    "tapok2",
    "airplanshaha",
    "GospodJesus",
    "bttvAni",
    "Harry_Potter_stickers",
    "gifki",
    "skzkz",
    "Eto_golub_eeZee",
    "BoysClub",
    "anegen_2",
    "electroeditions",
    "NonameR",
    "tashkent_stickers",
    "KAZINO",
    "uktambek",
    "ChineseCubes",
    "BEPHO",
    "ButlerOstin",
    "Mosamapack",
    "Moral_condemnation",
    "als_ohuenny",
    "Stickers_ebat",
    "RESTORENATURALORDER",
    "blobbyyyy",
    "VitaminParty",
    "pollitrovaya",
    "LMTBZH_people",
    "sp760f8c50d2ff59b6231022bcb81e1e66_by_stckrRobot",
    "IgorIvanovich_by_fStikBot",
    "blyaskolko",
    "f_ws1afq2_1216979815_by_fStikBot",
    "modern2",
    "Rudiemoji",
    "AtiltDitalMasus_by_fStikBot",
    "kulhaker_salt",
    "ozero",
    "stkrchat",
    "putinsmoney",
    "daEntoOn",
    "PBaas",
    "best_ecosystem",
    "Yellowboi",
    "vsrpron",
    "ultrarjombav2",
)


async def get_random_fallback_image(
    bot: Bot,
    *,
    message_id: int,
    fallback_avatar: Path,
    prefer_local_probability: float = 0.02,
    max_attempts: int = 6,
) -> str | None:
    """Download a random sticker (or use a local placeholder) and return a temp file path."""
    # With small probability prefer a local placeholder (if present).
    if random.random() < prefer_local_probability and fallback_avatar.exists():
        output_file = f"temp_fallback_{message_id}.png"
        copy2(fallback_avatar, output_file)
        logging.info("Using local fallback avatar: %s", fallback_avatar)
        return output_file

    for _ in range(max_attempts):
        pack_name = random.choice(_STICKER_PACKS)
        try:
            logging.info("Getting random sticker from pack: %s", pack_name)
            sticker_set = await bot.get_sticker_set(pack_name)
            if not sticker_set.stickers:
                continue

            sticker = random.choice(sticker_set.stickers)
            logging.info(
                "Selected sticker: animated=%s, video=%s", sticker.is_animated, sticker.is_video
            )

            if sticker.is_animated:
                # TGS stickers: use thumbnail preview when available.
                if sticker.thumbnail:
                    output_file = f"temp_fallback_{message_id}.jpg"
                    await bot.download(sticker.thumbnail, destination=output_file)
                    return output_file
                continue

            if sticker.is_video:
                output_file = f"temp_fallback_{message_id}.webm"
                await bot.download(sticker, destination=output_file)
                return output_file

            output_file = f"temp_fallback_{message_id}.webp"
            await bot.download(sticker, destination=output_file)
            return output_file

        except Exception as e:
            logging.error("Failed to get random fallback: %s", e, exc_info=True)
            continue

    if fallback_avatar.exists():
        output_file = f"temp_fallback_{message_id}.png"
        copy2(fallback_avatar, output_file)
        return output_file

    return None


import asyncio
import os
from datetime import date, datetime, time, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from api_client import ApiError, fetch_all_lectures_basic, fetch_enrollment_counts, fetch_open_lectures
from state_store import init_state_store, mark_notified, was_notified

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GUILD_ID = int(os.getenv("GUILD_ID", "1447887618317619261"))
NOTIFY_CHANNEL_ID = int(os.getenv("NOTIFY_CHANNEL_ID", "1490575679786455111"))
STUDENT_ROLE_ID = int(os.getenv("STUDENT_ROLE_ID", "1490586180679368734"))

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
CONFIRMED_MIN = int(os.getenv("CONFIRMED_MIN", "10"))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


def fmt_date(value):
    if not value:
        return "미정"
    if isinstance(value, datetime):
        return value.strftime("%Y년 %m월 %d일")
    if isinstance(value, date):
        return value.strftime("%Y년 %m월 %d일")
    return str(value)


def fmt_time(value):
    if not value:
        return "미정"
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return str(value)


def fmt_deadline(value):
    if not value:
        return "미정"
    if isinstance(value, datetime):
        return value.strftime("%Y년 %m월 %d일 %H:%M")
    return str(value).replace("T", " ")


def make_new_lecture_embed(lecture):
    embed = discord.Embed(
        title="새 릴스 강연이 등록됐어요",
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="강연 제목", value=lecture["title"], inline=False)
    embed.add_field(name="연사자", value=lecture["creator_name"], inline=True)
    embed.add_field(
        name="강연 일시",
        value=f"{fmt_date(lecture['lecture_date'])} {fmt_time(lecture['lecture_time'])}",
        inline=True,
    )
    embed.add_field(name="신청 마감", value=fmt_deadline(lecture["application_deadline"]), inline=True)
    embed.add_field(name="대상자", value=lecture.get("target") or "전체", inline=True)
    embed.add_field(name="장소", value=lecture["lecture_location"] or "미정", inline=True)
    embed.set_footer(text="GSM 릴스 봇")
    return embed


def make_confirmed_embed(lecture, enrolled_count):
    embed = discord.Embed(
        title="릴스 강연 개설이 확정됐어요",
        description=f"**{lecture['title']}** 강연이 {CONFIRMED_MIN}명 이상 모여 개설 확정됐습니다!",
        color=0x57F287,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="연사자", value=lecture["creator_name"], inline=True)
    embed.add_field(name="현재 인원", value=f"{enrolled_count}명", inline=True)
    embed.add_field(
        name="강연 일시",
        value=f"{fmt_date(lecture['lecture_date'])} {fmt_time(lecture['lecture_time'])}",
        inline=True,
    )
    embed.set_footer(text="GSM 릴스 봇")
    return embed


def get_notify_channel():
    return bot.get_channel(NOTIFY_CHANNEL_ID)


def get_student_role_mention():
    guild = bot.get_guild(GUILD_ID)
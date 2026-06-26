import asyncio
import os
from datetime import date, datetime, time, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from api_client import (
    ApiError,
    fetch_active_lectures,
    fetch_all_lectures_basic,
    fetch_enrollment_counts,
    fetch_open_lectures,
)
from state_store import claim_notification, init_state_store, mark_notified

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "1447887618317619261"))
NOTIFY_CHANNEL_ID = int(os.getenv("NOTIFY_CHANNEL_ID", "1490575679786455111"))
STUDENT_ROLE_ID = int(os.getenv("STUDENT_ROLE_ID", "1490586180679368734"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
CONFIRMED_MIN = int(os.getenv("CONFIRMED_MIN", "10"))

CONFIRMED_STATUSES = {"CONFIRMED", "CONFIRM"}

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


def fmt_date(value):
    if not value:
        return "미정"
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value).replace("T", " ")


def fmt_time(value):
    if not value:
        return "미정"
    if isinstance(value, (datetime, time)):
        return value.strftime("%H:%M")
    text = str(value)
    return text.split(".", 1)[0] if "." in text else text


def fmt_deadline(value):
    if not value:
        return "미정"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    text = str(value).replace("T", " ")
    if "." in text:
        text = text.split(".", 1)[0]
    return text.rstrip("Z")


def _lecture_datetime_str(lecture):
    return f"{fmt_date(lecture['lecture_date'])} {fmt_time(lecture['lecture_time'])}"


def make_new_lecture_embed(lecture):
    embed = discord.Embed(
        title="새 릴레이 스터디가 등록됐어요",
        color=0xE8B84B,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="강연 제목", value=lecture["title"], inline=False)
    embed.add_field(name="연사자", value=lecture["creator_name"], inline=False)
    embed.add_field(name="강연 일시", value=_lecture_datetime_str(lecture), inline=False)
    embed.add_field(name="장소", value=lecture["lecture_location"] or "미정", inline=False)
    embed.add_field(name="신청 마감", value=fmt_deadline(lecture["application_deadline"]), inline=False)
    embed.add_field(name="대상자", value=lecture.get("target") or "전체", inline=False)
    if lecture.get("lecture_url"):
        embed.add_field(name="신청 링크", value=f"[강연 신청하기]({lecture['lecture_url']})", inline=False)
    embed.set_footer(text="GSM 릴스 봇")
    return embed


def make_confirmed_embed(lecture, enrolled_count):
    embed = discord.Embed(
        title="릴레이 스터디 개설이 확정됐어요",
        description=f"**{lecture['title']}** 강연이 {CONFIRMED_MIN}명 이상 모여 개설 확정됐습니다!",
        color=0xE8B84B,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="강연 제목", value=lecture["title"], inline=False)
    embed.add_field(name="연사자", value=lecture["creator_name"], inline=False)
    embed.add_field(name="강연 일시", value=_lecture_datetime_str(lecture), inline=False)
    embed.add_field(name="장소", value=lecture["lecture_location"] or "미정", inline=False)
    embed.add_field(name="신청 마감", value=fmt_deadline(lecture["application_deadline"]), inline=False)
    embed.add_field(name="현재 인원", value=f"{enrolled_count}명", inline=False)
    if lecture.get("lecture_url"):
        embed.add_field(name="신청 링크", value=f"[강연 신청하기]({lecture['lecture_url']})", inline=False)
    embed.set_footer(text="GSM 릴스 봇")
    return embed

def get_notify_channel():
    return bot.get_channel(NOTIFY_CHANNEL_ID)


def get_student_role_mention():
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return ""
    role = guild.get_role(STUDENT_ROLE_ID)
    return role.mention if role else ""


def is_confirmed_lecture(lecture, enrolled_count):
    return lecture["status"] in CONFIRMED_STATUSES or enrolled_count >= CONFIRMED_MIN


@tasks.loop(seconds=POLL_INTERVAL)
async def poll_api():
    channel = get_notify_channel()
    if channel is None:
        print(f"[경고] 알림 채널(ID: {NOTIFY_CHANNEL_ID})을 찾을 수 없습니다.")
        return

    role_mention = get_student_role_mention()

    try:
        lectures = fetch_open_lectures()
        enroll_map = fetch_enrollment_counts(lectures)

        for lecture in lectures:
            lecture_id = lecture["id"]
            enrolled_count = int(enroll_map.get(lecture_id, {"enrolled_count": 0})["enrolled_count"] or 0)

            if lecture["status"] == "OPEN" and claim_notification(lecture_id, "new", lecture["title"]):
                await channel.send(
                    content=f"{role_mention} 새 릴레이 스터디가 등록됐어요!",
                    embed=make_new_lecture_embed(lecture),
                )
                await asyncio.sleep(0.5)

            if is_confirmed_lecture(lecture, enrolled_count) and claim_notification(lecture_id, "confirmed", lecture["title"]):
                await channel.send(
                    content=f"{role_mention} 릴레이 스터디 개설이 확정됐어요!",
                    embed=make_confirmed_embed(lecture, enrolled_count),
                )
                await asyncio.sleep(0.5)

    except ApiError as exc:
        print(f"[API 오류] {exc}")
    except Exception as exc:
        print(f"[오류] {type(exc).__name__}: {exc}")


@poll_api.before_loop
async def before_poll():
    await bot.wait_until_ready()
    init_state_store()

    try:
        lectures = fetch_open_lectures()
        enroll_map = fetch_enrollment_counts(lectures)

        for lecture in lectures:
            lecture_id = lecture["id"]
            enrolled_count = int(enroll_map.get(lecture_id, {"enrolled_count": 0})["enrolled_count"] or 0)

            if lecture["status"] == "OPEN":
                mark_notified(lecture_id, "new", lecture["title"])
            if is_confirmed_lecture(lecture, enrolled_count):
                mark_notified(lecture_id, "confirmed", lecture["title"])

        print(f"[초기화] 기존 강연 {len(lectures)}개를 알림 완료 상태로 저장했습니다.")
    except ApiError as exc:
        print(f"[초기화 API 오류] {exc}")
    except Exception as exc:
        print(f"[초기화 오류] {type(exc).__name__}: {exc}")


@bot.command(name="릴스")
async def cmd_rels(ctx):
    try:
        lectures = fetch_active_lectures()

        if not lectures:
            await ctx.send("현재 신청 가능한 강연이 없어요.")
            return

        display_lectures = lectures[:25]

        embed = discord.Embed(
            title="📋 신청 가능한 강연",
            color=0xE8B84B,
            timestamp=datetime.now(timezone.utc),
        )

        for lecture in display_lectures:
            target = lecture.get("target") or "전체"
            is_confirmed = lecture["status"] in CONFIRMED_STATUSES

            lines = []
            if is_confirmed:
                lines.append("✅ 개설 확정")
            lines.append(f"{fmt_date(lecture['lecture_date'])} {fmt_time(lecture['lecture_time'])}")
            lines.append(f"마감 {fmt_deadline(lecture['application_deadline'])}")
            lines.append(f"대상 {target}")
            if lecture.get("lecture_url"):
                lines.append(f"🔗 [신청하기]({lecture['lecture_url']})")

            embed.add_field(
                name=f"{lecture['title']} — {lecture['creator_name']}",
                value="\n".join(lines),
                inline=False,
            )

        if len(lectures) > 25:
            embed.set_footer(text="GSM 릴스 봇 • 25개 이상의 강연 중 상위 25개만 표시됨")
        else:
            embed.set_footer(text="GSM 릴스 봇")
        await ctx.send(embed=embed)

    except Exception as exc:
        await ctx.send(f"오류가 발생했어요: {exc}")


@bot.command(name="인원")
async def cmd_headcount(ctx):
    try:
        lectures = fetch_all_lectures_basic()
        enroll_map = fetch_enrollment_counts(lectures)

        if not lectures:
            await ctx.send("현재 진행 중인 강연이 없어요.")
            return

        embed = discord.Embed(
            title="릴레이 스터디 인원 현황",
            color=0xE8B84B,
            timestamp=datetime.now(timezone.utc),
        )

        for lecture in lectures:
            lecture_id = lecture["id"]
            enrolled_count = int(enroll_map.get(lecture_id, {"enrolled_count": 0})["enrolled_count"] or 0)
            capacity = int(lecture["total_capacity"] or CONFIRMED_MIN * 3)
            filled = min(round(enrolled_count / capacity * 10), 10) if capacity else 0
            bar = "█" * filled + "░" * (10 - filled)

            status_tag = "개설 확정" if enrolled_count >= CONFIRMED_MIN else f"{CONFIRMED_MIN - enrolled_count}명 더 모이면 확정"
            value = f"`{bar}` {enrolled_count}/{capacity}명 | {status_tag}"
            embed.add_field(name=lecture["title"], value=value, inline=False)

        embed.set_footer(text="GSM 릴스 봇")
        await ctx.send(embed=embed)

    except Exception as exc:
        await ctx.send(f"오류가 발생했어요: {exc}")


@bot.command(name="도움말")
async def cmd_help(ctx):
    embed = discord.Embed(title="릴스 봇 명령어 목록", color=0xE8B84B)
    embed.add_field(name="!릴스", value="현재 신청 가능한 강연 목록을 보여줘요.", inline=False)
    embed.add_field(name="!인원", value="강연별 신청 인원 현황을 보여줘요.", inline=False)
    embed.add_field(name="!도움말", value="명령어 목록을 보여줘요.", inline=False)
    embed.set_footer(text="GSM 릴스 봇")
    await ctx.send(embed=embed)


@bot.event
async def on_ready():
    print(f"[봇 시작] {bot.user} 로그인 완료")
    if not poll_api.is_running():
        poll_api.start()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("없는 명령어예요. `!도움말`로 명령어 목록을 확인해보세요!")
    else:
        raise error


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN이 .env에 설정되어 있지 않습니다.")
    bot.run(DISCORD_TOKEN)
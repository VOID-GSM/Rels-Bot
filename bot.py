import asyncio
import os
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional, Union

import discord
from discord import app_commands
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


def _parse_id_list(env_val: str) -> List[int]:
    return [int(x.strip()) for x in env_val.split(",") if x.strip().isdigit()]


GUILD_IDS = _parse_id_list(os.getenv("GUILD_ID", "1447887618317619261"))


def _parse_channel_role_map(env_val: str) -> Dict[int, int]:
    """ "채널ID:역할ID,채널ID:역할ID" 형식 문자열을 파싱해 {채널ID: 역할ID} 매핑을 만든다."""
    mapping: Dict[int, int] = {}
    for pair in env_val.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        channel_str, role_str = pair.split(":", 1)
        channel_str = channel_str.strip()
        role_str = role_str.strip()
        if channel_str.isdigit() and role_str.isdigit():
            mapping[int(channel_str)] = int(role_str)
    return mapping


NOTIFY_CHANNEL_ROLE_MAP: Dict[int, int] = _parse_channel_role_map(
    os.getenv(
        "NOTIFY_CHANNEL_ROLE_MAP",
        "1490575679786455111:1490586180679368734,"
        "748827810528755772:919712218566774794,"
        "851322917932498964:919712218566774794",
    )
)

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
CONFIRMED_MIN = int(os.getenv("CONFIRMED_MIN", "10"))

CONFIRMED_STATUSES = {"CONFIRMED", "CONFIRM"}
EMBED_COLOR = 0xE8B84B
FOOTER_TEXT = "GSM 릴스 봇"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


def fmt_date(value: Optional[Union[datetime, date, str]]) -> str:
    if not value:
        return "미정"
    if isinstance(value, (datetime, date)):
        return value.strftime("%m-%d")
    text = str(value).replace("T", " ")
    parts = text.split("-")
    if len(parts) >= 3:
        return f"{parts[1]}-{parts[2][:2]}"
    return text


def fmt_time(value: Optional[Union[datetime, time, str]]) -> str:
    if not value:
        return ""
    if isinstance(value, (datetime, time)):
        return value.strftime("%H:%M")
    text = str(value)
    parts = text.split(":")
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    return text


def fmt_deadline(value: Optional[Union[datetime, str]]) -> str:
    if not value:
        return "미정"
    if isinstance(value, datetime):
        return value.strftime("%m-%d %H:%M")

    text = str(value).replace("T", " ").rstrip("Z")
    if "." in text:
        text = text.split(".", 1)[0]

    try:
        dt = datetime.fromisoformat(text)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        parts = text.split("-")
        if len(parts) >= 3:
            return f"{parts[1]}-{parts[2][:11]}"
        return text


def _lecture_datetime_str(lecture: Dict[str, Any]) -> str:
    return fmt_date(lecture.get("lecture_date"))


def _make_progress_bar(enrolled: int, capacity: int, width: int = 10) -> str:
    if not capacity:
        return "░" * width
    filled = min(round((enrolled / capacity) * width), width)
    return "█" * filled + "░" * (width - filled)


def _build_base_embed(
    title: str, lecture: Dict[str, Any], description: Optional[str] = None
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="강연 제목", value=f"**{lecture['title']}**", inline=False)
    embed.add_field(
        name="연사자", value=lecture.get("creator_name") or "미정", inline=True
    )
    embed.add_field(name="대상자", value=lecture.get("target") or "전체", inline=True)
    embed.add_field(
        name="장소", value=lecture.get("lecture_location") or "미정", inline=True
    )

    embed.add_field(name="강연 일시", value=_lecture_datetime_str(lecture), inline=True)
    embed.add_field(
        name="신청 마감",
        value=fmt_deadline(lecture.get("application_deadline")),
        inline=True,
    )
    return embed


def make_new_lecture_embed(lecture: Dict[str, Any]) -> discord.Embed:
    embed = _build_base_embed("새 릴레이 스터디가 등록됐어요!", lecture)
    if lecture.get("lecture_url"):
        embed.add_field(
            name="신청 링크",
            value=f"[강연 신청하러 가기]({lecture['lecture_url']})",
            inline=False,
        )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def make_confirmed_embed(lecture: Dict[str, Any], enrolled_count: int) -> discord.Embed:
    desc = (
        f"**{lecture['title']}** 강연이 {CONFIRMED_MIN}명 이상 모여 개설 확정됐습니다!"
    )
    embed = _build_base_embed("릴레이 스터디 개설 확정!", lecture, description=desc)
    embed.add_field(name="현재 인원", value=f"**{enrolled_count}명**", inline=True)
    if lecture.get("lecture_url"):
        embed.add_field(
            name="신청 링크",
            value=f"[강연 신청하러 가기]({lecture['lecture_url']})",
            inline=False,
        )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def _get_channel_mention(channel_id: int) -> str:
    role_id = NOTIFY_CHANNEL_ROLE_MAP.get(channel_id)
    if not role_id:
        return ""

    channel = bot.get_channel(channel_id)
    if channel is not None and getattr(channel, "guild", None) is not None:
        role = channel.guild.get_role(role_id)
        if role:
            return role.mention

    return f"<@&{role_id}>"


def is_confirmed_lecture(lecture: Dict[str, Any], enrolled_count: int) -> bool:
    return (
        lecture.get("status") in CONFIRMED_STATUSES or enrolled_count >= CONFIRMED_MIN
    )


async def send_to_all_notify_channels(message: str, embed: discord.Embed) -> None:
    for channel_id in NOTIFY_CHANNEL_ROLE_MAP:
        channel = bot.get_channel(channel_id)
        if channel:
            mention = _get_channel_mention(channel_id)
            content = f"{mention} {message}".strip()
            try:
                await channel.send(content=content, embed=embed)
            except Exception as e:
                print(f"[전송 에러] 채널 {channel_id}로 메시지 전송 실패: {e}")
        else:
            print(
                f"[채널 없음] {channel_id} — 봇이 이 채널을 못 찾음(권한/캐시 확인 필요)"
            )


@tasks.loop(seconds=POLL_INTERVAL)
async def poll_api() -> None:
    try:
        lectures = fetch_open_lectures()
        enroll_map = fetch_enrollment_counts(lectures)

        for lecture in lectures:
            lecture_id = lecture["id"]
            enrolled_count = int(
                enroll_map.get(lecture_id, {}).get("enrolled_count", 0) or 0
            )

            if lecture.get("status") == "OPEN" and claim_notification(
                lecture_id, "new", lecture["title"]
            ):
                await send_to_all_notify_channels(
                    "새 릴레이 스터디가 등록됐어요!", make_new_lecture_embed(lecture)
                )
                await asyncio.sleep(0.5)

            if is_confirmed_lecture(lecture, enrolled_count) and claim_notification(
                lecture_id, "confirmed", lecture["title"]
            ):
                await send_to_all_notify_channels(
                    "릴레이 스터디 개설이 확정됐어요!",
                    make_confirmed_embed(lecture, enrolled_count),
                )
                await asyncio.sleep(0.5)

    except ApiError as exc:
        print(f"[API 오류] {exc}")
    except Exception as exc:
        print(f"[오류] {type(exc).__name__}: {exc}")


@poll_api.before_loop
async def before_poll() -> None:
    await bot.wait_until_ready()
    init_state_store()

    try:
        lectures = fetch_open_lectures()
        enroll_map = fetch_enrollment_counts(lectures)

        for lecture in lectures:
            lecture_id = lecture["id"]
            enrolled_count = int(
                enroll_map.get(lecture_id, {}).get("enrolled_count", 0) or 0
            )

            if lecture.get("status") == "OPEN":
                mark_notified(lecture_id, "new", lecture["title"])
            if is_confirmed_lecture(lecture, enrolled_count):
                mark_notified(lecture_id, "confirmed", lecture["title"])

        print(f"[초기화] 기존 강연 {len(lectures)}개를 알림 완료 상태로 저장했습니다.")
    except ApiError as exc:
        print(f"[초기화 API 오류] {exc}")
    except Exception as exc:
        print(f"[초기화 오류] {type(exc).__name__}: {exc}")


@bot.tree.command(name="릴스", description="현재 신청 가능한 강연 목록 보기")
async def cmd_rels(interaction: discord.Interaction) -> None:
    try:
        lectures = fetch_active_lectures()

        if not lectures:
            await interaction.response.send_message("현재 신청 가능한 강연이 없어요.")
            return

        display_lectures = lectures[:25]

        embed = discord.Embed(
            title="신청 가능한 강연 목록",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )

        for lecture in display_lectures:
            target = lecture.get("target") or "전체"
            is_confirmed = lecture.get("status") in CONFIRMED_STATUSES

            lines = []
            if is_confirmed:
                lines.append("**개설 확정**")
            lines.append(f"연사자: {lecture.get('creator_name') or '미정'}")
            lines.append(f"일시: {_lecture_datetime_str(lecture)}")
            lines.append(f"마감: {fmt_deadline(lecture.get('application_deadline'))}")
            lines.append(f"대상: {target}")
            if lecture.get("lecture_url"):
                lines.append(f"[신청하기]({lecture['lecture_url']})")

            embed.add_field(
                name=f"{lecture['title']}",
                value="\n".join(lines),
                inline=False,
            )

        footer_note = (
            " • 25개 이상의 강연 중 상위 25개만 표시됨" if len(lectures) > 25 else ""
        )
        embed.set_footer(text=f"{FOOTER_TEXT}{footer_note}")
        await interaction.response.send_message(embed=embed)

    except Exception as exc:
        await interaction.response.send_message(f"오류가 발생했어요: {exc}")


@bot.tree.command(name="인원", description="강연별 신청 인원 현황 보기")
async def cmd_headcount(interaction: discord.Interaction) -> None:
    try:
        lectures = fetch_all_lectures_basic()
        enroll_map = fetch_enrollment_counts(lectures)

        if not lectures:
            await interaction.response.send_message("현재 진행 중인 강연이 없어요.")
            return

        embed = discord.Embed(
            title="릴레이 스터디 인원 현황",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )

        for lecture in lectures:
            lecture_id = lecture["id"]
            enrolled_count = int(
                enroll_map.get(lecture_id, {}).get("enrolled_count", 0) or 0
            )
            capacity = int(lecture.get("total_capacity") or (CONFIRMED_MIN * 3))

            bar = _make_progress_bar(enrolled_count, capacity)
            status_tag = (
                "개설 확정"
                if enrolled_count >= CONFIRMED_MIN
                else f"{CONFIRMED_MIN - enrolled_count}명 더 모이면 확정"
            )

            value = f"`{bar}` **{enrolled_count}/{capacity}명** | {status_tag}"
            embed.add_field(name=lecture["title"], value=value, inline=False)

        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    except Exception as exc:
        await interaction.response.send_message(f"오류가 발생했어요: {exc}")


@bot.tree.command(name="도움말", description="명령어 안내")
async def cmd_help(interaction: discord.Interaction) -> None:
    embed = discord.Embed(title="릴스 봇 명령어 목록", color=EMBED_COLOR)
    embed.add_field(name="/릴스", value="현재 신청 가능한 강연 목록 보기", inline=False)
    embed.add_field(name="/인원", value="강연별 신청 인원 현황 보기", inline=False)
    embed.add_field(name="/도움말", value="명령어 안내", inline=False)
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)


@bot.event
async def on_ready() -> None:
    print(f"[봇 시작] {bot.user} 로그인 완료")
    if not poll_api.is_running():
        poll_api.start()

    try:
        if GUILD_IDS:
            for guild_id in GUILD_IDS:
                guild_obj = discord.Object(id=guild_id)
                bot.tree.copy_global_to(guild=guild_obj)
                synced = await bot.tree.sync(guild=guild_obj)
                print(
                    f"[슬래시 동기화] 길드 {guild_id}: {len(synced)}개 명령어 동기화 완료"
                )
        else:
            synced = await bot.tree.sync()
            print(
                f"[슬래시 동기화] 전역: {len(synced)}개 명령어 동기화 완료 (반영까지 최대 1시간 소요될 수 있음)"
            )
    except Exception as e:
        print(f"[슬래시 동기화 오류] {e}")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    print(f"[명령어 오류] {error}")
    message = "명령어 실행 중 오류가 발생했어요."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN이 .env에 설정되어 있지 않습니다.")
    bot.run(DISCORD_TOKEN)

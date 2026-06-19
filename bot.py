import asyncio
import os
from datetime import date, datetime, time, timezone
 
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
 
from api_client import ApiError, fetch_all_lectures_basic, fetch_enrollment_counts, fetch_open_lectures
from state_store import claim_notification, init_state_store, mark_notified
 
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
        return value.strftime("%Y-%m-%d")
 
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
 
    return str(value).replace("T", " ")
 
 
def fmt_time(value):
    if not value:
        return "미정"
 
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
 
    if isinstance(value, time):
        return value.strftime("%H:%M")
 
    text = str(value)
    if "." in text:
        text = text.split(".", 1)[0]
 
    return text
 
 
def fmt_deadline(value):
    if not value:
        return "미정"
 
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
 
    text = str(value).replace("T", " ")
 
    if "." in text:
        text = text.split(".", 1)[0]
 
    if text.endswith("Z"):
        text = text[:-1]
 
    return text
 
 
def make_new_lecture_embed(lecture):
    embed = discord.Embed(
        title="새 릴스 강연이 등록됐어요",
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
 
    embed.add_field(name="강연 제목", value=lecture["title"], inline=False)
    embed.add_field(name="연사자", value=lecture["creator_name"], inline=False)
    embed.add_field(
        name="강연 일시",
        value=f"{fmt_date(lecture['lecture_date'])} {fmt_time(lecture['lecture_time'])}",
        inline=False,
    )
    embed.add_field(name="장소", value=lecture["lecture_location"] or "미정", inline=False)
    embed.add_field(name="신청 마감", value=fmt_deadline(lecture["application_deadline"]), inline=False)
    embed.add_field(name="대상자", value=lecture.get("target") or "전체", inline=False)
 
    embed.set_footer(text="GSM 릴스 봇")
    return embed
 
 
def make_confirmed_embed(lecture, enrolled_count):
    embed = discord.Embed(
        title="릴스 강연 개설이 확정됐어요",
        description=f"**{lecture['title']}** 강연이 {CONFIRMED_MIN}명 이상 모여 개설 확정됐습니다!",
        color=0x57F287,
        timestamp=datetime.now(timezone.utc),
    )
 
    embed.add_field(name="강연 제목", value=lecture["title"], inline=False)
    embed.add_field(name="연사자", value=lecture["creator_name"], inline=False)
    embed.add_field(
        name="강연 일시",
        value=f"{fmt_date(lecture['lecture_date'])} {fmt_time(lecture['lecture_time'])}",
        inline=False,
    )
    embed.add_field(name="장소", value=lecture["lecture_location"] or "미정", inline=False)
    embed.add_field(name="신청 마감", value=fmt_deadline(lecture["application_deadline"]), inline=False)
    embed.add_field(name="현재 인원", value=f"{enrolled_count}명", inline=False)
 
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
    return lecture["status"] in {"CONFIRMED", "CONFIRM"} or enrolled_count >= CONFIRMED_MIN
 
 
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
            counts = enroll_map.get(lecture_id, {"enrolled_count": 0})
            enrolled_count = int(counts["enrolled_count"] or 0)
 
            # 먼저 DB에 "보냈다"고 점유(claim)한 뒤에만 실제로 전송한다.
            # 이렇게 하면 전송 후 기록이 실패해서 다음 polling에서
            # 같은 알림이 또 나가는 중복 전송 문제가 발생하지 않는다.
            if lecture["status"] == "OPEN" and claim_notification(lecture_id, "new", lecture["title"]):
                await channel.send(
                    content=f"{role_mention} 새 릴스 강연이 등록됐어요!",
                    embed=make_new_lecture_embed(lecture),
                )
                await asyncio.sleep(0.5)
 
            if is_confirmed_lecture(lecture, enrolled_count) and claim_notification(
                lecture_id, "confirmed", lecture["title"]
            ):
                await channel.send(
                    content=f"{role_mention} 릴스 강연 개설이 확정됐어요!",
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
        lectures = fetch_all_lectures_basic()
 
        if not lectures:
            await ctx.send("현재 신청 가능한 릴스 강연이 없어요.")
            return
 
        embed = discord.Embed(
            title="현재 신청 가능한 릴스 강연",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )
 
        for lecture in lectures:
            value = (
                f"연사자: {lecture['creator_name']}\n"
                f"강연 일시: {fmt_date(lecture['lecture_date'])} {fmt_time(lecture['lecture_time'])}\n"
                f"장소: {lecture['lecture_location'] or '미정'}\n"
                f"신청 마감: {fmt_deadline(lecture['application_deadline'])}\n"
                f"대상자: {lecture.get('target') or '전체'}"
            )
            embed.add_field(name=lecture["title"], value=value, inline=False)
 
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
            await ctx.send("현재 진행 중인 릴스 강연이 없어요.")
            return
 
        embed = discord.Embed(
            title="릴스 강연 인원 현황",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )
 
        for lecture in lectures:
            lecture_id = lecture["id"]
            enrolled_count = int(enroll_map.get(lecture_id, {"enrolled_count": 0})["enrolled_count"] or 0)
            capacity = int(lecture["total_capacity"] or CONFIRMED_MIN * 3)
            filled = min(round(enrolled_count / capacity * 10), 10) if capacity else 0
            bar = "█" * filled + "░" * (10 - filled)
 
            if enrolled_count >= CONFIRMED_MIN:
                status_tag = "개설 확정"
            else:
                status_tag = f"{CONFIRMED_MIN - enrolled_count}명 더 모이면 확정"
 
            value = f"`{bar}` {enrolled_count}/{capacity}명 | {status_tag}"
            embed.add_field(name=lecture["title"], value=value, inline=False)
 
        embed.set_footer(text="GSM 릴스 봇")
        await ctx.send(embed=embed)
 
    except Exception as exc:
        await ctx.send(f"오류가 발생했어요: {exc}")
 
 
@bot.command(name="도움말")
async def cmd_help(ctx):
    embed = discord.Embed(title="릴스 봇 명령어 목록", color=0x5865F2)
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
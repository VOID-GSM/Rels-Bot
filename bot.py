import os
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from client import fetch_open_lectures, fetch_all_lectures_basic
from store import init_state_store, was_notified, mark_notified

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
NOTIFICATION_CHANNEL_ID = int(os.getenv("NOTIFICATION_CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user.name}")
    init_state_store()
    lecture_alarm_loop.start()


@bot.command(name="릴스")
async def show_lectures(ctx):
    lectures = fetch_all_lectures_basic()

    if not lectures:
        await ctx.send("현재 신청 가능한 릴스 강연이 없습니다.")
        return

    for lecture in lectures:
        embed = discord.Embed(
            title="현재 신청 가능한 릴스 강연",
            description=f"**{lecture['title']}**",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="강연 정보",
            value=(
                f"**연사자**: {lecture['creator_name']}\n\n"
                f"**일시**: {lecture['lecture_date']} {lecture['lecture_time']}\n\n"
                f"**마감**: {lecture['application_deadline']}\n\n"
                f"**대상**: {lecture['target_info']}\n\n"
                f"**바로가기**: [강연 상세 보기]({lecture['lecture_url']})"
            ),
            inline=False,
        )

        embed.set_footer(text=f"GSM 릴스 봇 • 오늘 {discord.utils.utcnow().strftime('%p %I:%M')}")
        await ctx.send(embed=embed)


@tasks.loop(minutes=5)
async def lecture_alarm_loop():
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if not channel:
        return

    try:
        lectures = fetch_open_lectures()
    except Exception as e:
        print(f"강연 데이터를 가져오는 중 오류 발생: {e}")
        return

    for lecture in lectures:
        lecture_id = str(lecture["id"])

        if not was_notified(lecture_id, "NEW_LECTURE"):

            embed = discord.Embed(
                title="새 릴스 강연이 등록됐어요",
                description=f"**{lecture['title']}**",
                color=discord.Color.green(),
            )

            embed.add_field(
                name="강연 정보",
                value=(
                    f"**연사자**: {lecture['creator_name']}\n\n"
                    f"**일시**: {lecture['lecture_date']} {lecture['lecture_time']}\n\n"
                    f"**마감**: {lecture['application_deadline']}\n\n"
                    f"**대상**: {lecture['target_info']}\n\n"
                    f"**바로가기**: [강연 상세 보기]({lecture['lecture_url']})"
                ),
                inline=False,
            )

            embed.set_footer(text="GSM 릴스 봇")

            await channel.send(content="@everyone 새 릴스 강연이 등록됐어요!", embed=embed)
            mark_notified(lecture_id, "NEW_LECTURE", lecture["title"])


if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("토큰 설정이 비어있습니다. .env 파일을 확인해주세요.")
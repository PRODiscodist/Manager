from prettytable import PrettyTable
from core import Cog, Quotient, Context
from discord.ext import commands


from .helper import PremiumPurchase, tabulate_query
from time import perf_counter as pf
from models.models import Commands, Partner
from utils import get_ipm, QuoUser
import typing, datetime
import discord
from contextlib import suppress
from constants import PartnerRequest, IST

__all__ = ("Dev",)


class Dev(Cog):
    def __init__(self, bot: Quotient):
        self.bot = bot

    def cog_check(self, ctx: Context):
        return ctx.author.id in ctx.config.DEVS

    @commands.command(hidden=True)
    async def pgift(self, ctx: Context, user: QuoUser, _type: PremiumPurchase):
        await ctx.send(_type)

    @commands.command(hidden=True)
    async def partner_approve(self, ctx: Context, message_id: int, author_id: int):
        record = await Partner.get(message_id=message_id)
        guild = self.bot.get_guild(record.guild_id)

        user = await self.bot.getch(self.bot.get_user, self.bot.fetch_user, author_id)

        embed = discord.Embed(
            color=self.bot.color,
            description=(
                f"Dear {user} ({guild.name}),\n"
                f"Congrats! Your request for Quotient Partnership Program has been approved,\n"
                f"Kindly join the support server and talk to {ctx.author} to receive perks."
                f"\n\nUse `qinvite` if you don't have the support server link."
            ),
        )
        embed.set_author(name=ctx.author, icon_url=ctx.author.avatar_url)

        with suppress(discord.Forbidden, AttributeError, discord.HTTPException):
            await user.send(embed=embed)

        await Partner.filter(message_id=message_id).update(
            status=PartnerRequest.approved, review_time=datetime.datetime.now(tz=IST), mod=ctx.author.id
        )
        await ctx.success("done")

    @commands.command(hidden=True)
    async def partner_deny(self, ctx: Context, message_id: int, author_id: int, *, reason):
        user = await self.bot.getch(self.bot.get_user, self.bot.fetch_user, author_id)

        embed = discord.Embed(color=discord.Color.red(), description=reason)
        embed.set_author(name=ctx.author, icon_url=ctx.author.avatar_url)

        with suppress(discord.Forbidden, AttributeError, discord.HTTPException):
            await user.send(embed=embed)

        await Partner.filter(message_id=message_id).update(
            status=PartnerRequest.denied, review_time=datetime.datetime.now(tz=IST), review_note=reason, mod=ctx.author.id
        )
        await ctx.success("done")

    # TODO: add flags for webhooks and embeds

    @commands.command(hidden=True)
    async def broadcast(self, ctx: Context, *, msg):
        message = f"{msg}\n\n- {str(ctx.author)}, Team Quotient"
        records = await ctx.db.fetch("SELECT private_channel FROM guild_data WHERE private_channel IS NOT NULL")
        success, failed = 0, 0
        start = pf()
        for record in records:
            channel = await self.bot.getch(self.bot.get_channel, self.bot.fetch_channel, record["private_channel"])

            if channel is not None and channel.permissions_for(channel.guild.me).send_messages:
                try:
                    await channel.send(message)
                    success += 1
                except:
                    failed += 1
                    continue

        end = pf()
        await ctx.send(f"Sent {success}: {failed} finished in {end - start:.3f}s.")

    @commands.command(hidden=True)
    async def cmds(self, ctx):
        total_uses = await Commands.all().count()

        records = await ctx.db.fetch(
            "SELECT cmd, COUNT(*) AS uses FROM commands GROUP BY cmd ORDER BY uses DESC LIMIT 15 "
        )

        table = PrettyTable()
        table.field_names = ["Command", "Invoke Count"]
        for record in records:
            table.add_row([record["cmd"], record["uses"]])

        table = table.get_string()
        embed = self.bot.embed(ctx, title=f"Command Usage ({total_uses})")
        embed.description = f"```{table}```"

        cmds = sum(1 for i in self.bot.walk_commands())

        embed.set_footer(text="Total Commands: {}  | Invoke rate per minute: {}".format(cmds, round(get_ipm(ctx.bot), 2)))

        await ctx.send(embed=embed)

    @commands.group(hidden=True, invoke_without_command=True, name="history")
    async def command_history(self, ctx):
        """Command history."""
        query = """SELECT
                        CASE failed
                            WHEN TRUE THEN cmd || ' [!]'
                            ELSE cmd
                        END AS "cmd",
                        to_char(used_at, 'Mon DD HH12:MI:SS AM') AS "invoked",
                        user_id,
                        guild_id
                   FROM commands
                   ORDER BY used_at DESC
                   LIMIT 15;
                """
        await tabulate_query(ctx, query)

    @command_history.command(name="for")
    async def command_history_for(self, ctx, days: typing.Optional[int] = 7, *, command: str):
        """Command history for a command."""
        query = """SELECT *, t.success + t.failed AS "total"
                   FROM (
                       SELECT guild_id,
                              SUM(CASE WHEN failed THEN 0 ELSE 1 END) AS "success",
                              SUM(CASE WHEN failed THEN 1 ELSE 0 END) AS "failed"
                       FROM commands
                       WHERE cmd=$1
                       AND used_at > (CURRENT_TIMESTAMP - $2::interval)
                       GROUP BY guild_id
                   ) AS t
                   ORDER BY "total" DESC
                   LIMIT 30;
                """

        await tabulate_query(ctx, query, command, datetime.timedelta(days=days))

    @command_history.command(name="guild", aliases=["server"])
    async def command_history_guild(self, ctx, guild_id: int):
        """Command history for a guild."""
        query = """SELECT
                        CASE failed
                            WHEN TRUE THEN cmd || ' [!]'
                            ELSE cmd
                        END AS "cmd",
                        channel_id,
                        user_id,
                        used_at
                   FROM commands
                   WHERE guild_id=$1
                   ORDER BY used_at DESC
                   LIMIT 15;
                """
        await tabulate_query(ctx, query, guild_id)

    @command_history.command(name="user", aliases=["member"])
    @commands.is_owner()
    async def command_history_user(self, ctx, user_id: int):
        """Command history for a user."""
        query = """SELECT
                        CASE failed
                            WHEN TRUE THEN cmd || ' [!]'
                            ELSE cmd
                        END AS "cmd",
                        guild_id,
                        used_at
                   FROM commands
                   WHERE user_id=$1
                   ORDER BY used_at DESC
                   LIMIT 20;
                """
        await tabulate_query(ctx, query, user_id)

    @command_history.command(name="cog")
    async def command_history_cog(self, ctx, days: typing.Optional[int] = 7, *, cog: str = None):
        """Command history for a cog or grouped by a cog."""
        interval = datetime.timedelta(days=days)
        if cog is not None:
            cog = self.bot.get_cog(cog)
            if cog is None:
                return await ctx.send(f"Unknown cog: {cog}")

            query = """SELECT *, t.success + t.failed AS "total"
                       FROM (
                           SELECT command,
                                  SUM(CASE WHEN failed THEN 0 ELSE 1 END) AS "success",
                                  SUM(CASE WHEN failed THEN 1 ELSE 0 END) AS "failed"
                           FROM commands
                           WHERE cmd = any($1::text[])
                           AND used_at > (CURRENT_TIMESTAMP - $2::interval)
                           GROUP BY cmd
                       ) AS t
                       ORDER BY "total" DESC
                       LIMIT 30;
                    """
            return await tabulate_query(ctx, query, [c.qualified_name for c in cog.walk_commands()], interval)

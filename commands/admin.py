import discord
from typing import Union
from discord.ext import commands
from mooBird import MooBird

class Admin(commands.Cog):
    no_speak = '🙊'

    def __init__(self, bot):
        self.bot = bot  # type: MooBird

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        ignore_me = (commands.CommandNotFound, commands.CheckFailure)
        if isinstance(error, ignore_me):
            pass
        else:
            raise error

    @commands.group(help='Configuration >')
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def set(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            pass

    @set.group(help='Channel Restrictions >')
    async def channel(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            pass

    @channel.command(name='allow', help='Allow commands from target channel')
    async def channel_add(self, ctx: commands.Context, channel: Union[discord.TextChannel, str]):
        if isinstance(channel, str):
            if channel == 'here':
                channel = ctx.channel
            else:
                raise commands.ArgumentParsingError

        if isinstance(channel, discord.TextChannel):
            if not ctx.channel.permissions_for(ctx.me).send_messages:
                return await ctx.message.add_reaction(self.no_speak)

            if not channel.permissions_for(ctx.me).send_messages:
                embed = discord.Embed(color=discord.Color.red(), title='Invalid Setting',
                                      description=f"I'm unable to speak in #{channel}.")
                return await ctx.send(embed=embed)

            channel_permissions = self.bot.config[ctx.guild.id]['allowed']['channels']
            if channel.id not in channel_permissions:
                channel_permissions.append(channel.id)
                self.bot.save_config()

            embed = discord.Embed(color=discord.Color.dark_blue(), title="Authorized Channel",
                                  description="Responding to commands in this channel.")
            await channel.send(embed=embed)

    @channel_add.error
    async def channel_add_error(self, ctx, error):
        embed = discord.Embed(color=discord.Color.red())
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send('What?')

        if isinstance(error, commands.ArgumentParsingError):
            embed.title = 'Invalid Argument'
            embed.description = 'Provide a tagged channel, or `here`'
            await ctx.send(embed=embed)

    @set.group(help='User Restrictions >')
    async def user(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            pass

    @user.command(name='grant')
    async def user_grant(self, ctx: commands.Context, target: Union[discord.Role, discord.Member]):
        allow_config = self.bot.config[ctx.guild.id]['allowed']
        target_type = None

        if isinstance(target, discord.Role):
            allow_config['roles'].append(target.id)
            target_type = 'Role'

        if isinstance(target, discord.Member):
            allow_config['users'].append(target.id)
            target_type = 'User'

        self.bot.save_config()
        embed = discord.Embed(color=discord.Color.dark_blue(), title=f"Authorized {target_type}",
                              description=f"{target.name} can now interact with me.")
        await ctx.channel.send(embed=embed)

    @user_grant.error
    async def user_grant_error(self, ctx, error):
        embed = discord.Embed(color=discord.Color.red())
        if isinstance(error, (commands.MissingRequiredArgument, commands.ArgumentParsingError)):
            embed.title = 'Invalid Argument'
            embed.description = 'Provide a tagged User or Role'
            await ctx.send(embed=embed)

    @set.command('votes')
    async def votes(self, ctx: commands.Context, votes: int):
        self.bot.config[ctx.guild.id]['votes_needed'] = votes
        self.bot.save_config()

        embed = discord.Embed(color=discord.Color.dark_blue(), title="Configured Vote Counts",
                              description=f"Vote Threshold set at {votes}")
        await ctx.send(embed=embed)

    @votes.error
    async def votes_error(self, ctx, error):
        await ctx.message.add_reaction('❓')

def setup(bot):
    bot.add_cog(Admin(bot))

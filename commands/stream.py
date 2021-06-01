import json
import shlex
import discord
from discord.ext import commands
from tweepy import asynchronous
from mooBird import MooBird

def can_stream():
    def predicate(ctx):
        return ctx.cog.check_permission(ctx)

    return commands.check(predicate)

class Stream(commands.Cog, name='Streams', description="Twitter Search Stream"):
    def __init__(self, bot):
        self.bot = bot  # type: MooBird

        if self.bot.is_ready():
            # Need to think more about target channel
            # bot.loop.create_task(self._startup())
            pass

    async def check_permission(self, user):
        if not user.guild:
            return False

        if isinstance(user, commands.Context):
            user = user.author

        is_owner = await self.bot.is_owner(user)
        return any([
            user.guild_permissions.administrator,
            is_owner,
        ])

    @commands.Cog.listener()
    async def on_ready(self):
        # Need to think more about target channel
        # await self._startup()
        pass

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, my_error):
        ignore_me = (commands.CommandNotFound, commands.CheckFailure)
        if isinstance(my_error, ignore_me):
            pass
        else:
            await ctx.message.add_reaction('❓')
            embed = discord.Embed(color=discord.Color.red(), title='Exception', description=str(my_error.original))
            await ctx.send(embed=embed, reference=ctx.message)

    async def _startup(self):
        for guild in self.bot.guilds:
            config = self.bot.config.get(guild.id, {}).get('search', {})
            if config and config.get('enabled'):
                await self._start_stream(guild)

    async def _start_stream(self, ctx):
        guild_id = ctx.id if isinstance(ctx, discord.Guild) else ctx.guild.id
        terms = self.bot.config.get(guild_id, {}).get('search', {}).get('terms')
        if not terms:
            return await ctx.channel.send('No terms?')

        api = self.bot.twitterApi[guild_id]  # type: tweepy.API
        tweet_cog = self.bot.get_cog('Twitter')

        stream = self.bot.streams[guild_id] = MyStreamListener(
            api.get_settings()['screen_name'],
            ctx.channel,
            tweet_cog.stream_to_channel,
            access_token=api.auth.access_token, access_token_secret=api.auth.access_token_secret,
            consumer_key=api.auth.consumer_key, consumer_secret=api.auth.consumer_secret
        )

        await stream.filter(track=terms)

    async def _to_channel(self, channel, payload):
        if payload['rt'] and self.bot.tweet_candidates.get(payload['rt']):
            return

        post = await channel.send(payload['msg'])
        for emoji in self.bot.interaction_options:
            await post.add_reaction(emoji=emoji)

    async def _restart_stream(self, ctx):
        guild_id = ctx.guild.id
        stream = self.bot.streams[guild_id]
        await stream.disconnect()  # type: MyStreamListener
        del self.bot.streams[ctx.guild.id]
        await self._start_stream(ctx)

    @commands.group(help="Start or Stop a stream >")
    @commands.guild_only()
    @can_stream()
    async def stream(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            pass

    @stream.command()
    async def start(self, ctx: commands.Context):
        if stream := self.bot.streams.get(ctx.guild.id):
            raise Exception('A stream is running already!')

        config = self.bot.config.get(ctx.guild.id, {}).get('search', {})
        terms = config.get('terms')
        if not config or not terms:
            return await ctx.channel.send('Cannot start - No Terms!')

        config['enabled'] = True
        self.bot.save_config()

        await ctx.message.add_reaction('🚰')
        await self._start_stream(ctx)

    @stream.command()
    async def stop(self, ctx: commands.Context):
        if not (stream := self.bot.streams.get(ctx.guild.id)):
            raise Exception('No stream started!')

        config = self.bot.config.get(ctx.guild.id, {}).get('search', {})
        config['enabled'] = False
        self.bot.save_config()

        await stream.disconnect()
        del self.bot.streams[ctx.guild.id]
        await ctx.message.add_reaction('🚱')

    @commands.command(help='Set terms separated by commas')
    @commands.guild_only()
    @can_stream()
    async def search(self, ctx: commands.Context, *, terms):
        terms = shlex.split(terms)

        self.bot.config[ctx.guild.id]['search']['terms'] = terms
        self.bot.save_config()

        embed = discord.Embed(color=discord.Color.greyple(), title='Search Terms Updated',
                              description=f"Searching for `{'` `'.join(terms)}`")

        if self.bot.streams.get(ctx.guild.id):
            embed.set_footer(text="Restarting Stream")
            await self._restart_stream(ctx)

        await ctx.channel.send(embed=embed)

    @commands.group()
    @commands.guild_only()
    @can_stream()
    async def ignore(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            pass

    @ignore.command()
    async def list(self, ctx: commands.Context):
        ignore_list = self.bot.config[ctx.guild.id]['search'].get('ignore')
        if not ignore_list:
            embed = discord.Embed(colour=discord.Color.red(), title='Empty Ignore List!',
                                  description="No current ignore terms are defined. Add them with `ignore add <term> [<term...>]`")
            return await ctx.channel.send(embed=embed)

        list_output = '\n'.join(f'- `{k}`' for k in ignore_list)
        embed = discord.Embed(color=discord.Color.greyple(), title='Current Ignore List',
                              description=list_output)
        await ctx.channel.send(embed=embed)

    def add_ignore_term(self, guild_id, terms):
        if isinstance(terms, str):
            terms = [terms]

        new_list = list(set(self.bot.config[guild_id]['search'].get('ignore', []) + terms))
        new_list.sort()
        self.bot.config[guild_id]['search']['ignore'] = new_list
        self.bot.save_config()

        return new_list

    @ignore.command()
    async def add(self, ctx: commands.Context, *, terms):
        terms = shlex.split(terms)
        new_list = self.add_ignore_term(ctx.guild.id, terms)

        list_output = '\n'.join(f'- `{k}`' for k in new_list)
        embed = discord.Embed(colour=discord.Colour.blurple(), title='Ignore Terms Added',
                              description=f"New Ignore List:\n{list_output}")

        await ctx.channel.send(embed=embed)

    @ignore.command(name='del')
    async def ignore_del(self, ctx: commands.Context, term):
        ignore_list = self.bot.config[ctx.guild.id]['search'].get('ignore', [])
        try:
            ignore_list.remove(term)
            self.bot.config[ctx.guild.id]['search']['ignore'] = ignore_list
            self.bot.save_config()
            embed = discord.Embed(colour=discord.Colour.blurple(), title='Ignore Term Removed',
                                  description=f"Removed `{term}` from the ignore list")
        except ValueError:
            embed = discord.Embed(color=discord.Color.red(), title='Unknown Ignore Term',
                                  description=f"`{term}` is not in the list, and thus was not removed. Use `ignore list` to display the current list")

        await ctx.channel.send(embed=embed)

    @ignore.command()
    async def clear(self, ctx: commands.Context):
        ignore_list = self.bot.config[ctx.guild.id]['search'].get('ignore')
        if not ignore_list:
            embed = discord.Embed(colour=discord.Colour.lighter_grey(), title="Empty Ignore List Emptied",
                                  description="Good work; I've cleared an ignore list that did not exist.")
            return await ctx.channel.send(embed=embed)

        list_output = '\n'.join(f'- `{k}`' for k in ignore_list)
        self.bot.config[ctx.guild.id]['search']['ignore'] = []
        self.bot.save_config()
        embed = discord.Embed(colour=discord.Colour.lighter_grey(), title='Ignore List Cleared',
                              description=f'The ignore list has been cleared. For reference, this was the previous list:\n{list_output}')
        return await ctx.channel.send(embed=embed)

    @search.error
    async def search_error(self, ctx, my_error):
        embed = discord.Embed(color=discord.Color.red(), title='No Search Terms Defined!',
                              description="Please enter search terms, separated by spaces. Enclose 'and' searches in quotation marks.")
        embed.add_field(name='Examples',
                        value='`BNB Binance` searches posts for `BNB` _or_ `Binance`\n`BTC "bear market"` searches `BTC` _or_ (`bear` **and** `market`)')
        return await ctx.channel.send(embed=embed)

class MyStreamListener(asynchronous.AsyncStream):
    def __init__(self, account, channel, callback, **kwargs):
        super().__init__(**kwargs)
        self.me = account
        self.channel = channel
        self.callback = callback
        self.running = True

    async def on_data(self, raw_data):
        if not self.running:
            return

        data = json.loads(raw_data)
        if data.get("in_reply_to_status_id") or data.get('retweeted_status'):
            return

        await super().on_data(raw_data)

    async def on_status(self, status):
        if self.running and status.author.screen_name != self.me:
            if not hasattr(status, 'quoted_status'):
                status.quoted_status = None
                status.quoted_status_id = None

            if status.quoted_status and not hasattr(status.quoted_status, 'extended_tweet'):
                status.quoted_status.extended_tweet = {}

            await self.callback(self.channel, status)

    async def disconnect(self):
        self.running = False
        super().disconnect()

def setup(bot):
    bot.add_cog(Stream(bot))

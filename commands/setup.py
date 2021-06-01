import asyncio
import discord
from discord.ext import commands
from mooBird import MooBird

def is_invoker():
    def predicate(ctx):
        return ctx.cog.invokers.get(ctx.author.id, {})

    return commands.check(predicate)

class Setup(commands.Cog, description="Initial Setup Commands"):
    def __init__(self, bot):
        self.bot = bot  # type: MooBird
        self.invokers = {}
        self.prompt = ['✅', '❌']
        self.timeout = 15

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._warn_no_creds(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._warn_no_creds(guild)

    @commands.has_permissions(administrator=True)
    @commands.command()
    async def setup(self, ctx: commands.Context):
        if isinstance(ctx.channel, discord.channel.DMChannel):
            if self.invokers.get(ctx.author.id):
                return await self._send_setup_step(ctx)
            else:
                embed = discord.Embed(color=discord.Color.red(), title='Unknown Server Context', description="Please run this command inside your server!")
                embed.add_field(name="Usage", value=f"`@{self.bot.user.display_name} setup`")
                return await ctx.channel.send(embed=embed)

        self.invokers[ctx.author.id] = ctx.guild.id
        await ctx.message.add_reaction('📨')
        await self._send_setup_step(ctx)

    @setup.error
    async def setup_error(self, ctx, error):
        if isinstance(error, discord.ext.commands.errors.MissingPermissions):
            return await ctx.message.add_reaction('❌')

    async def _warn_no_creds(self, guild):
        if not (credentials := self.bot.config.get(guild.id, {}).get('credentials')):
            self.bot.create_config(guild.id)

            channel = discord.utils.find(lambda m: 'general' in m.name, guild.text_channels)
            if not channel:
                channel = guild.text_channels[0]

            embed = discord.Embed(colour=discord.Colour.blurple(), title="Welcome to mooBird!",
                                  description=f"An administrator should start the setup process with `@{self.bot.user.display_name} setup`")
            await channel.send(embed=embed)

    async def _send_setup_step(self, ctx, msg=None):
        credentials = self.bot.config.get(self.invokers[ctx.author.id], {}).get('credentials')
        help_intro = msg if msg else "Hello! Let's set up your Twitter credentials."
        help_text = f"{help_intro} Please provide the API Key and Secret in the form of `api <api_key> <api_secret>`"
        embed = discord.Embed(color=discord.Color.dark_purple(), title='MooBird Setup', description=help_text)

        if credentials:
            api_key = credentials.get('API Key', '<Not Set>')
            api_secret = credentials.get('API Secret', '<Not Set>')

            embed.add_field(name='Reset Keys?', value='It appears we already have these API Credentials saved. '
                                                      'Following the above instructions will overwrite them.', inline=False)
            embed.add_field(name='Current API Key', value=f"`{api_key}`", inline=False)
            embed.add_field(name='Current API Secret', value=f"`{api_secret}`", inline=False)

            if credentials.get('Access Token'):
                embed.add_field(name='Reset User Auth?', value='There are also Access Tokens saved, not shown here.\n'
                                                               'You can reset these with `auth <access_token> <access_secret>`', inline=False)
            else:
                embed.add_field(name='Add User Auth', value='Add Auth Tokens with `auth <access_token> <access_secret>`', inline=False)

        dm = await ctx.author.create_dm()
        await dm.send(embed=embed)

    @commands.command()
    @commands.dm_only()
    @is_invoker()
    async def api(self, ctx: commands.Context, api_key, api_secret):
        guild_id = self.invokers[ctx.author.id]

        embed = discord.Embed(color=discord.Color.blue(), title='Confirm Twitter API Keys')
        embed.add_field(name='API Key', value=f"`{api_key}`", inline=False)
        embed.add_field(name='API Secret', value=f"`{api_secret}`", inline=False)
        embed.set_footer(text=f"Timeout in {self.timeout} seconds.")

        prompt = await ctx.channel.send(embed=embed)
        for emoji in self.prompt:
            await prompt.add_reaction(emoji=emoji)

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in self.prompt

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=self.timeout, check=check)

            if str(reaction) == self.prompt[1]:
                await prompt.delete()
                return await self._send_setup_step(ctx)

            self.bot.config[guild_id]['credentials'] = {
                'API Key'   : api_key,
                'API Secret': api_secret
            }

            self.bot.save_config()
            await prompt.delete()
            await self._send_auth_step(ctx)
        except asyncio.TimeoutError:
            await prompt.delete()
            await self._send_setup_step(ctx, "For security, we have timed out your previous response.")

    @api.error
    async def api_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(color=discord.Color.red(), title='Incomplete!',
                                  description='Please provide both the `<api_key>` and `<api_secret>` arguments.')
            await ctx.send(embed=embed)

    async def _send_auth_step(self, ctx, msg=None):
        credentials = self.bot.config.get(self.invokers[ctx.author.id], {}).get('credentials')
        help_intro = msg if msg else ""
        help_text = f"{help_intro} Please provide the Auth Token and Secret in the form of `auth <access_token> <access_secret>`"
        embed = discord.Embed(colour=discord.Color.dark_blue(), title='Twitter Auth Tokens', description=help_text)

        if credentials.get('Access Token'):
            embed.add_field(name='Reset Keys?', value='Access Tokens are already saved. Following the above instructions will overwrite them.', inline=False)
            embed.add_field(name='Tokens', value='Not displayed for security reasons.', inline=False)

        await ctx.channel.send(embed=embed)

    @commands.command()
    @commands.dm_only()
    @is_invoker()
    async def auth(self, ctx: commands.Context, access_token, access_secret):
        guild_id = self.invokers[ctx.author.id]

        credentials = self.bot.config.get(guild_id, {}).get('credentials', {})
        if not credentials.get('API Key'):
            return await self._send_setup_step(ctx, "Before we can add target credentials, you must configure the API Keys!")

        embed = discord.Embed(colour=discord.Colour.blue(), title='Confirm Account Access')
        embed.add_field(name='Access Token', value=f"`{access_token}`", inline=False)
        embed.add_field(name='Access Secret', value=f"`{access_secret}`", inline=False)
        embed.set_footer(text=f"Timeout in {self.timeout} seconds.")

        prompt = await ctx.channel.send(embed=embed)
        for emoji in self.prompt:
            await prompt.add_reaction(emoji=emoji)

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in self.prompt

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=self.timeout * 2, check=check)

            if str(reaction) == self.prompt[1]:
                await prompt.delete()
                return await self._send_auth_step(ctx, "Aborted.")

            self.bot.config[guild_id]['credentials'].update({
                'Access Token' : access_token,
                'Access Secret': access_secret
            })

            self.bot.save_config()

            if api := self.bot.validate_credentials(self.bot.config[guild_id]['credentials']):
                self.bot.twitterApi[guild_id] = api
                embed = discord.Embed(color=discord.Color.green(), title=f'Welcome, @{api.me().screen_name}!',
                                      description="Your account has been confirmed, and you're ready to start Tweeting!\n\n"
                                                  "Send `help` for more information on how to operate this, "
                                                  "but note that most interaction takes place within your channels.")
                embed.add_field(name="Note", value=f"To restart this process, issue `@{self.bot.user.display_name} setup` from within your server.")

                del self.invokers[ctx.author.id]
                await prompt.delete()
                return await ctx.channel.send(embed=embed)

            await prompt.delete()
            await self._send_setup_step(ctx, "Authenticating failed! Let's restart the process to ensure all keys are entered correctly.")

        except asyncio.TimeoutError:
            await prompt.delete()
            await self._send_setup_step(ctx, "For security, we have timed out your previous response.")

    @auth.error
    async def auth_error(self, ctx, error):
        print(error)
        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(color=discord.Color.red(), title='Incomplete!',
                                  description='Please provide both the `<access_token>` and `<access_secret>` arguments.')
            await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(Setup(bot))

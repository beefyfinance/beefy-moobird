import io
import os
import re
import shlex
import time
import urllib.request
from urllib.parse import urlparse

import discord
import emoji
import requests
from discord.ext import commands, tasks
import tweepy
from mooBird import MooBird

def can_tweet():
    def predicate(ctx):
        return ctx.cog.check_permission(ctx)

    return commands.check(predicate)

class Twitter(commands.Cog, name='Twitter', description="Twitter Interaction"):
    interaction_string = "`💬 {} 🔃 {} ❤️ {}`"
    no_speak = '🙊'

    def __init__(self, bot):
        self.bot = bot  # type: MooBird
        self.cleanup.start()

    def cog_unload(self):
        self.cleanup.cancel()

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        ignore_me = (commands.CommandNotFound, commands.CheckFailure)
        if isinstance(error, ignore_me):
            pass
        else:
            raise error

    @staticmethod
    async def validate_credentials(credentials: dict):
        auth = tweepy.OAuthHandler(credentials['API Key'], credentials['API Secret'])
        auth.set_access_token(credentials['Access Token'], credentials['Access Secret'])
        api = tweepy.API(auth)

        if api.verify_credentials():
            return api

        return None

    async def check_permission(self, user):
        if not user.guild:
            return False

        if isinstance(user, commands.Context):
            user = user.author

        is_owner = await self.bot.is_owner(user)
        permissions = self.bot.config.get(user.guild.id, {}).get('allowed', {})
        if permissions:
            has_user_permission = user.id in permissions.get('users', [])
            has_role_permission = any(role.id in permissions.get('roles', []) for role in user.roles)

            return any([
                user.guild_permissions.administrator,
                is_owner,
                has_user_permission,
                has_role_permission
            ])

        return False

    @tasks.loop(minutes=30)
    async def cleanup(self):
        if not len(self.bot.tweet_candidates):
            return

        now = int(time.time())
        tweet_threshold = 3600
        interaction_threshold = 86400

        # Interactions
        to_delete = {vote_id: info for (vote_id, info) in self.bot.tweet_candidates.items() if
                     info['action'] == 'interact' and (now - info['proposed']) > interaction_threshold}

        for vote_id, info in to_delete.items():
            for cur_emoji in self.bot.interaction_options:
                try:
                    await info['message'].clear_reaction(cur_emoji)
                except Exception:
                    pass

            del self.bot.tweet_candidates[vote_id]

        to_delete = {vote_id: info for (vote_id, info) in self.bot.tweet_candidates.items() if
                     info['action'] == 'tweet' and (now - info['proposed']) > tweet_threshold}

        for vote_id, info in to_delete.items():
            if vote := await info['message'].channel.fetch_message(vote_id):
                embed = discord.Embed(color=discord.Colour.greyple(), title='Vote Timed Out',
                                      description="This vote failed to pass, but can restarted at any time.")
                await vote.delete()
                await info['message'].channel.send(embed=embed, reference=info['message'])

            del self.bot.tweet_candidates[vote_id]

    async def stream_to_channel(self, channel, status):
        if status.quoted_status:
            terms = self.bot.config[channel.guild.id]['search']['terms']
            if any(word in status.quoted_status.extended_tweet.get('full_text', status.quoted_status.text) for word in terms):
                return

        ignore_list = self.bot.config[channel.guild.id]['search'].get('ignore', [])

        user_ignore = [user.lower()[1:] for user in ignore_list if user.startswith('@')]
        if status.author.screen_name.lower() in user_ignore:
            return

        tweet_text = status.text if not status.truncated else status.extended_tweet['full_text']
        if any(word.lower() in tweet_text.lower() for word in ignore_list):
            return

        if tweet_text.count('$') > 15:
            return

        msg = f"https://twitter.com/{status.author.screen_name}/status/{status.id}"
        post = await channel.send(msg)

        self.bot.tweet_candidates[post.id] = {
            'votes'       : {},
            'proposed'    : int(time.time()),
            'action'      : 'interact',
            'tweet_id'    : status.id,
            'tweet_author': status.author.screen_name.lower(),
            'message'     : post
        }

        for cur_emoji in self.bot.interaction_options:
            await post.add_reaction(emoji=cur_emoji)

    async def _post(self, message_id):
        if not (message_info := self.bot.tweet_candidates.get(message_id)):
            return None

        message = message_info['message']  # type: discord.Message

        api = self.bot.twitterApi[message.guild.id]

        message_content = message.clean_content
        attachments = message.attachments
        media_ids = []
        for i in range(0, len(attachments)):
            filename = attachments[i].filename
            content_type = attachments[i].content_type

            data = io.BytesIO(await attachments[i].read())

            media_category = 'tweet_image'
            if 'video' in content_type:
                media_category = 'tweet_video'
            if 'gif' in content_type:
                media_category = 'tweet_gif'

            res = api.media_upload(filename=filename, file=data, chunked=True, media_category=media_category)
            media_ids.append(res.media_id)

        status = api.update_status(status=message_content, media_ids=media_ids)  # type: tweepy.Status

        del self.bot.tweet_candidates[message_id]

        return f'https://twitter.com/{status.author.screen_name}/status/{status.id_str}'

    async def _action(self, ctx: discord.Message, candidate, voters, action):
        api = self.bot.twitterApi[ctx.guild.id]

        if 'retweet' in action:
            api.retweet(candidate['tweet_id'])
            icon = '🔃'
            color = discord.Color.blurple()
            title = f"{icon} Retweeted"

        if 'favorite' in action:
            api.create_favorite(candidate['tweet_id'])
            icon = '♥️'
            color = discord.Color.magenta()
            title = f"{icon} Liked"

        if 'mute' in action:
            stream = self.bot.get_cog('Streams')
            stream.add_ignore_term(ctx.guild.id, '@' + candidate['tweet_author'])
            icon = '🤐'
            color = discord.Color.greyple()
            title = f"{icon} @{candidate['tweet_author']} Muted"

        if 'cowmoonity' in action:
            await ctx.clear_reactions()
            try:
                self.submit_to_trello(ctx)
            except Exception as e:
                embed = discord.Embed(color=discord.Color.red(), title='Error')
                embed.description = 'An error occurred while sending this to the Cowmoonity'
                embed.add_field(name='Details', value=str(e))
                return await ctx.channel.send(embed=embed, reference=ctx)

            icon = '🚀'
            color = discord.Color.gold()
            title = f"{icon} Submitted to Cowmmoonity"

        await ctx.add_reaction(icon)
        embed = discord.Embed(color=color, title=title)
        embed.add_field(name='Voters', value=voters)
        await ctx.channel.send(embed=embed, reference=ctx)

    async def _check_vote_threshold(self, guild, votes):
        needed_votes = self.bot.config[guild.id]['votes_needed']
        if votes.get(self.bot.response_options[0], 0) >= needed_votes:
            return 'pass'

        if votes.get(self.bot.response_options[1], 0) * 2 >= needed_votes:
            return 'fail'

        return None

    def submit_to_trello(self, ctx: discord.Message):
        url = "https://api.trello.com/1/cards"

        query = self.bot.config[ctx.guild.id].get('trello', {})
        if not query:
            raise Exception('No Trello configuration!')

        query['cardRole'] = 'link'
        query['name'] = ctx.content

        response = requests.request(
            "POST",
            url,
            params=query
        )

        if not response.status_code:
            raise Exception(f'Error: `{response.text}`')

    @commands.command(help='Mark a message for a Tweet vote')
    @can_tweet()
    async def tweet(self, ctx: commands.Context):
        if not ctx.message.reference:
            return await ctx.channel.send('Please reference a message you want me to Tweet!')

        message_ref = ctx.message.reference.cached_message
        if not ctx.message.reference.cached_message:
            try:
                message_ref = await ctx.fetch_message(ctx.message.reference.message_id)
            except Exception as e:
                return await ctx.channel.send('I do not have access to this message. Please repost.')

        message_content = message_ref.content

        username_matches = re.findall("`@.*?`", message_ref.content)
        for match in username_matches:
            message_content = message_content.replace(match, match.strip('`').strip())

        message_length = len(message_content)

        embed = discord.Embed(color=0x4aa1eb, title='Tweet Preview', description=message_content)

        for url in re.findall("(?P<url>https?://[^\s]+)", message_content):
            message_length -= len(url) - 23

        for cur_embed in message_ref.embeds:
            if cur_embed.type == 'article':
                message_length -= len(cur_embed.url) - 33
                if not embed.image:
                    embed.set_image(url=cur_embed.thumbnail.url)

            if cur_embed.type == 'image':
                if not embed.image:
                    embed.description = embed.description.replace(cur_embed.url, '')
                    embed.set_image(url=cur_embed.url)

        message_length += emoji.emoji_count(message_content)

        if message_length > 280:
            return await ctx.channel.send(f'This message is too large by {message_length - 280} characters!')

        if len(message_ref.attachments):
            max_size = 5

            if 'video' in message_ref.attachments[0].content_type:
                max_size = 15
                embed.add_field(name='Attachment', value='Video')
            else:
                if 'gif' in message_ref.attachments[0].content_type:
                    max_size = 15

                if not embed.image:
                    embed.set_image(url=message_ref.attachments[0].url)

            if message_ref.attachments[0].size / 1024000 > max_size:
                embed = discord.Embed(color=discord.Color.red(), title="Attachment too large", description=f"The attached media exceeds the {max_size} MB maximum!")
                embed.add_field(name='Guide', value="Images: 5 MB\nGIF/Video: 15 MB")
                return await ctx.channel.send(embed=embed, reference=message_ref, mention_author=True)

        embed.set_footer(text=f"Posting to @{self.bot.twitterApi[ctx.guild.id].get_settings()['screen_name']} - Vote Below!")

        voting = await ctx.channel.send(embed=embed, reference=message_ref, mention_author=False)

        self.bot.tweet_candidates[voting.id] = {
            'votes'   : {},
            'proposed': int(time.time()),
            'action'  : 'tweet',
            'tweet_id': None,
            'message' : message_ref
        }

        for cur_emoji in self.bot.response_options:
            await voting.add_reaction(emoji=cur_emoji)

    @commands.command(help="Mark a message for retweet")
    @can_tweet()
    async def reply(self, ctx: commands.Context, *, content=None):
        if not ctx.message.reference:
            return await ctx.channel.send('Please reference a message you want to reply to!')
        pass

        message_ref = ctx.message.reference.cached_message
        if not ctx.message.reference.cached_message:
            try:
                message_ref = await ctx.fetch_message(ctx.message.reference.message_id)
            except Exception as e:
                return await ctx.channel.send('I do not have access to this message. Please repost.')

        message_content = shlex.split(message_ref.clean_content)[0]
        tweet_info = urlparse(message_content)

        if 'twitter.com' not in tweet_info.netloc:
            return ctx.channel.send('Not a valid Twitter link')

        try:
            _, username, _, tweet_id = tweet_info.path.split('/')
        except ValueError:
            return ctx.channel.send('Not a valid Twitter link!')

        await self._action(ctx, tweet_id, ['retweet'])

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if isinstance(after.channel, discord.DMChannel):
            return

        if after.channel.id not in self.bot.config[after.guild.id]['allowed']['channels']:
            return

        for vote_id, candidate in self.bot.tweet_candidates.items():
            if candidate['message'].id == after.id:
                # Something to handle the edited message
                pass

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if isinstance(message.channel, discord.DMChannel):
            return

        if message.channel.id not in self.bot.config[message.guild.id]['allowed']['channels']:
            return

        to_delete = []
        for vote_msg, candidate in self.bot.tweet_candidates.items():
            if candidate['message'].id == message.id:
                to_delete.append(vote_msg)

        for vote_msg in to_delete:
            del self.bot.tweet_candidates[vote_msg]

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or reaction.message.author.id != self.bot.user.id:
            return

        if not (candidate := self.bot.tweet_candidates.get(reaction.message.id)):
            return

        if not await self.check_permission(user):
            return await reaction.message.remove_reaction(reaction, user)

        if candidate['action'] == 'interact':
            if reaction.emoji not in self.bot.interaction_options:
                return

            idx = self.bot.interaction_options.index(reaction.emoji)
            msg = candidate['message']

            candidate['votes'][reaction.emoji] = reaction.count - 1
            needed_votes = self.bot.config[reaction.message.guild.id]['votes_needed']
            if candidate['votes'][reaction.emoji] >= needed_votes:
                updated_message = await msg.channel.fetch_message(msg.id)
                voters = ' '.join([user.mention for user in await updated_message.reactions[idx].users().flatten() if not user.bot])

                await reaction.message.clear_reaction(reaction)

                actions = ['favorite', 'mute', 'cowmoonity']
                if idx < len(actions):
                    await self._action(reaction.message, candidate, voters, actions[idx])

        if candidate['action'] == 'tweet':
            candidate['votes'][reaction.emoji] = reaction.count - 1

            message = reaction.message
            action = await self._check_vote_threshold(reaction.message.guild, candidate['votes'])

            if action == 'pass':
                async with message.channel.typing():
                    try:
                        updated_message = await message.channel.fetch_message(message.id)
                        voters = ' '.join([user.mention for user in await updated_message.reactions[0].users().flatten() if not user.bot])

                        await message.delete()
                        post_link = await self._post(message.id)
                        # await message.channel.send(self.interaction_string.format(0, 0, 0) + '\n' + post_link)

                        return await message.channel.send(f"Voters: {voters}\n" + post_link, allowed_mentions=discord.AllowedMentions(users=False))
                    except Exception as e:
                        print(e)
                        await message.channel.send('An error occurred sending this Tweet!')

            if action == 'fail':
                await message.delete()
                embed = discord.Embed(color=discord.Color.dark_red(), title='Voted Down',
                                      description='This proposal was voted down and has not been sent.')
                await message.channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_reaction_remove(self, payload, user):
        if user.bot:
            return

        if not (candidate := self.bot.tweet_candidates.get(payload.message.id)):
            return

        if not await self.check_permission(user):
            return

        candidate['votes'][payload.emoji] -= 1
        # member = payload.message.author # type: discord.Member
        # emoji = payload.emoji
        # candidate['votes'] -= self._vote_value(member, emoji)

    def _vote_value(self, member: discord.Member, vote: discord.Emoji):
        value = 1
        if member.top_role.name == 'Team':
            value *= 2
        pass

    @commands.command(hidden=True)
    async def check(self, ctx: commands.Context, tweet_id):
        api = self.bot.twitterApi[ctx.guild.id]  # type: tweepy.API

        tweet = api.get_status(tweet_id)
        handle = tweet.author.screen_name
        date = tweet.created_at
        replies = api.search(q='to:binance', result_type='recent', count=200, since_id=tweet_id, include_entities=False)
        print(tweet.retweet_count, tweet.favorite_count)

def setup(bot):
    bot.add_cog(Twitter(bot))

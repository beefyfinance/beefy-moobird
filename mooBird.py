import os
import discord
import tweepy
import yaml
from discord.ext import tasks, commands

class MooBird(commands.Bot):
    tweet_candidates = {}
    response_options = ['👍', '👎']
    interaction_options = ['🤍', '🔇', '🐮']
    interaction_confirm = ['♥️', '🤐', '🚀']
    twitterApi = {}
    streams = {}

    def __init__(self, config):
        self.api_key = config.get('discord_key')
        self.config = config.get('config')

        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=self.handle_prefix, case_insensitive=True, intents=intents)

        self.help_command = commands.DefaultHelpCommand(command_attrs={"hidden": True})
        # default_channel = config['channels'][0] if len(config['channels']) else None

        for guild_id, config in self.config.items():
            if api := self.validate_credentials(config.get('credentials', {})):
                self.twitterApi[guild_id] = api
            else:
                config['credentials'] = {}

    def create_config(self, guild_id):
        skel = {
            'credentials': {},
            'trello': {},
            'allowed': {
                'channels': [],
                'roles': [],
                'users': []
            },
            'search': {
                'enabled': False,
                'terms': []
            },
            'votes_needed': 1
        }

        self.config[guild_id] = skel

    def save_config(self):
        with open(r'config.yaml', 'w') as file:
            yaml.dump({'discord_key': self.api_key, 'config': self.config}, file)

    @staticmethod
    def validate_credentials(credentials : dict):
        if not credentials:
            return None

        auth = tweepy.OAuthHandler(credentials['API Key'], credentials['API Secret'])
        auth.set_access_token(credentials['Access Token'], credentials['Access Secret'])
        api = tweepy.API(auth)

        if api.verify_credentials():
            return api

        return None

    @staticmethod
    def list_cogs(directory):
        return (f"{directory}.{f.rstrip('py').rstrip('.')}" for f in os.listdir(directory) if f.endswith('.py'))

    @staticmethod
    def handle_prefix(bot, message):
        if isinstance(message.channel, discord.channel.DMChannel):
            return ''

        return commands.when_mentioned(bot, message)

    async def on_ready(self):
        await self.change_presence(activity=discord.Game(name='on Twitter'))

    @staticmethod
    def parse_int(val):
        try:
            val = int(val)
        except ValueError:
            val = None

        return val

    def exec(self):
        for cog in self.list_cogs('commands'):
            try:
                self.load_extension(cog)
            except Exception as e:
                print(f'Failed to load extension {cog}.', e)
        self.run(self.api_key)

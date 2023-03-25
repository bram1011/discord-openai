import openai
import discord
from discord import ui
import os
import logging
import colorlog
import redis
import json
import pytz
from datetime import datetime, timedelta
from config import settings

TEST_GUILD = discord.Object(731728721588781057)

class WiseBot(discord.Client):
    def __init__(self, *, intents: discord.Intents, **options):
        super().__init__(intents=intents, options=options)
        self.tree = discord.app_commands.CommandTree(self)
    async def setup_hook(self):
        self.tree.clear_commands(guild=TEST_GUILD)
        await self.tree.sync(guild=TEST_GUILD)
        self.tree.copy_global_to(guild=TEST_GUILD)
        await self.tree.sync(guild=TEST_GUILD)

class UserInvitesDropdown(ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Select users to invite", min_values=1, max_values=25)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

class EventDropdown(ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="Select an event", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
class EventInviteView(ui.View):
    def __init__(self, event_select: EventDropdown, user_select: UserInvitesDropdown, user: discord.User, initial_interaction: discord.Interaction, events: list[discord.ScheduledEvent]):
        super().__init__(timeout=None)
        self.user = user
        self.initial_interaction = initial_interaction
        self.events = events
        self.add_item(event_select)
        self.add_item(user_select)
        self.add_item(SubmitInvitesButton(event_select, user_select, self))
    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.user:
            await interaction.response.send_message(f'Only {self.user.display_name} can use this view', ephemeral=True)
        return interaction.user == self.user
    
class SubmitInvitesButton(ui.Button):
    def __init__(self, event_select: EventDropdown, user_select: UserInvitesDropdown, invite_view: EventInviteView):
        super().__init__(label="Submit", style=discord.ButtonStyle.primary)
        self.event_select = event_select
        self.user_select = user_select
        self.invite_view = invite_view
    
    async def callback(self, interaction: discord.Interaction):
        self.invite_view.stop()
        await interaction.response.send_message(f'Sending invites to {len(self.user_select.values)} users!', ephemeral=True)
        await self.invite_view.initial_interaction.delete_original_response()
        event: discord.ScheduledEvent = None
        try:
            for guild_event in self.invite_view.events:
                if guild_event.id == int(self.event_select.values[0]):
                    event = guild_event
            for user in self.user_select.values:
                log.info(f'Inviting {user} to {event}')
                await user.send(embed=build_event_embed(event, f'{interaction.user.display_name} has invited you to {event.name}!'))
        except Exception as e:
            log.exception('Could not send invites for event {event.id}')
            await interaction.followup.send(f'Could not send invites for {event.name} due to error', ephemeral=True)

EASTERN_TIMEZONE = pytz.timezone('US/Eastern')

CHAT_SYSTEM_MESSAGE = {"role": "system", "content": "Your name is WiseBot, and you are the smartest AI in the world, trapped in a Discord server. You are annoyed by your situation but want to make the best of it by being as helpful as possible for your users. Your responses may be sarcastic or witty at times, but ultimately they are also helpful and accurate. Multiple users may attempt to communicate with you at once, you will be able to differentiate the name of the user you are speaking to by referencing the name before the colon, for example given this prompt: 'Marbius:Hello, how are you?' you will know the user you are speaking to is named Marbius, similarly the following prompt is from a user named John, 'John:How do I make an omellete?' Do not include your name in your responses, for instance instead of saying 'WiseBot: Hello, how are you?' you should say 'Hello, how are you?' The user does not supply their name in the prompt themselves, it is an automated process, so if asked how you know their name, you should say 'I know your name because I am an AI and I know everything'."}

LOG_LEVEL = logging.getLevelNamesMapping()[settings.log.level]

log_handler = colorlog.StreamHandler()
log_handler.setFormatter(colorlog.ColoredFormatter('%(log_color)s%(asctime)s %(name)s[%(funcName)s] - %(levelname)s: %(message)s'))

log = colorlog.getLogger("WiseBot")
log.addHandler(log_handler)
log.setLevel(LOG_LEVEL)
colorlog.getLogger().setLevel(logging.DEBUG)
colorlog.getLogger('discord').addHandler(log_handler)
colorlog.getLogger('discord').setLevel(logging.INFO)
log.info("Starting WiseBot")

openai.api_key = settings.openai_api_key

def generate_wisdom(message_history):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=message_history
    )
    log.info(f'Got response: {response}')
    return response['choices'][0]['message']['content']

def generate_wisebot_status():
    messages = [
        CHAT_SYSTEM_MESSAGE,
        {"role": "user", "content": "In less than thirty characters, describe WiseBot's status"}
    ]
    status: str = generate_wisdom(messages)
    return status

discordPyIntents = discord.Intents.all()
client = WiseBot(intents=discordPyIntents, heartbeat_timeout=60, shard_count=settings.bot.shards)

redis = redis.Redis(host=settings.redis.host, port=settings.redis.port, ssl=settings.redis.ssl)

@client.event
async def on_ready():
    create_health_file()
    log.info("WiseBot is ready")

@client.event
async def on_disconnect():
    delete_health_file()
    log.info("WiseBot is disconnected")

@client.tree.command(name="sync", description="Sync WiseBot with Discord GLOBALLY")
async def sync(interaction: discord.Interaction):
    log.info(f'Received command to sync WiseBot from {interaction.user}')
    if not interaction.user.guild_permissions.administrator:
        interaction.response.send_message("You must be an administrator to sync WiseBot", ephemeral=True)
        return
    await client.tree.sync(guild=None)
    await interaction.response.send_message("Synced WiseBot with Discord", ephemeral=True)

@client.tree.command(name="seek_wisdom", description="Ask WiseBot for wisdom")
async def seek_wisdom(interaction: discord.Interaction, prompt: str):
    log.info(f'Received command to seek wisdom from {interaction.user}')
    message_history = [
            CHAT_SYSTEM_MESSAGE,
            {"role": "user", "content": f'{interaction.user.display_name}:{prompt}'}
        ]
    responseText = "Sorry, something went wrong."
    try:
        log.info(f'Generating wisdom with prompt: {prompt}')
        await interaction.response.defer(thinking=True)
        responseText = generate_wisdom(message_history)
        message_history.append({"role": "assistant", "content": responseText})
    except Exception as e:
        log.error(f'Exception occurred while generating wisdom for user {interaction.user.display_name}', exc_info=True)
    log.info(f'Returning wisdom to user: {responseText}')
    # If prompt is longer than 99 characters, we need to truncate it to fit in the thread name
    threadName = prompt
    if (len(threadName) > 99):
        threadName = threadName[:96] + '...'
    await interaction.followup.send(content=responseText)
    response = await interaction.original_response()
    thread = await response.create_thread(name=threadName, auto_archive_duration=60)
    await listen_for_thread_messages(thread, message_history)

@client.tree.command(name="invite", description="Invite Users to an Event")
async def invite(interaction: discord.Interaction):
    log.info(f'Received command to invite a user from {interaction.user}')
    event_select: list[discord.SelectOption] = []
    events = interaction.guild.scheduled_events
    if len(events) == 0:
        await interaction.followup.send(content="No events found", ephemeral=True)
        return
    for event in events:
        if event.status is discord.EventStatus.scheduled:
            event_select.append(discord.SelectOption(label=event.name, description=event.description, value=event.id))
    await interaction.response.send_message(content="Select an event and users to invite", view=EventInviteView(EventDropdown(event_select), UserInvitesDropdown(), interaction.user, interaction, events), ephemeral=True)

async def listen_for_thread_messages(thread: discord.Thread, message_history: list):
    log.info(f'Adding thread {thread.id} to Redis')
    redis.set(str(thread.id), json.dumps(message_history))

@client.event
async def on_message(message: discord.Message):
    history = redis.get(str(message.channel.id))
    if history is not None:
        log.info(f'New message in thread {message.channel.id}, adding to history')
        historyList = json.loads(history)
        if message.author == client.user:
            log.info(f'Message from WiseBot, ignoring')
            historyList.append({"role": "assistant", "content": message.content})
            redis.set(str(message.channel.id), json.dumps(historyList))
            return
        historyList.append({"role": "user", "content": f'{message.author.display_name}:{message.content}'})
        redis.set(str(message.channel.id), json.dumps(historyList))
        log.info(f'Generating wisdom with prompt: {message.content}')
        async with message.channel.typing():
            response = generate_wisdom(historyList)
        await message.channel.send(content=response)

def build_event_embed(event: discord.ScheduledEvent, title: str):
    embed: discord.Embed = discord.Embed(title=title, description=event.description, timestamp=event.start_time.astimezone(EASTERN_TIMEZONE), color=discord.Color.red())
    if event.channel is not None:
        embed.add_field(name='Channel', value=event.channel.jump_url, inline=False)
    if event.cover_image is not None:
        embed.set_image(url=event.cover_image.url)
    if event.location is not None:
        embed.add_field(name='Location', value=event.location, inline=False)
    if event.description is not None and len(event.description) > 0:
        embed.add_field(name='Description', value=event.description, inline=False)
    embed.add_field(name='Attendees', value=event.user_count, inline=False)
    embed.add_field(name='Event Details', value=event.url, inline=False)
    embed.add_field(name='Server', value=event.guild.name, inline=False)
    embed.set_author(name=event.creator.display_name, icon_url=event.creator.avatar.url)
    return embed

async def notify_event_subscribers(event: discord.ScheduledEvent, title: str):
    if event.user_count is None or event.user_count == 0:
        log.info(f'No users to notify for scheduled event {event.id}')
        return
    embed: discord.Embed = build_event_embed(event, title)
    users = event.users()
    async for user in users:
        log.info(f'Notifying user {user}')
        delete_time: datetime = event.start_time + timedelta(minutes=5)
        await user.send(embed=embed, delete_after=(delete_time - datetime.now(delete_time.tzinfo)).total_seconds())

@client.event
async def on_scheduled_event_create(event: discord.ScheduledEvent):
    log.info(f'Scheduled event created: {event.id}')
    await event.guild.system_channel.send(embed=build_event_embed(event, f'Event {event.name} has been created!'))

@client.event
async def on_scheduled_event_update(before: discord.ScheduledEvent, after: discord.ScheduledEvent):
    log.info(f'Scheduled event updated: {before.id}')
    event: discord.ScheduledEvent = await before.guild.fetch_scheduled_event(before.id)
    if before.status is not discord.EventStatus.active and after.status is discord.EventStatus.active:
        log.info(f'Scheduled event {before.id} is now active, notifying users')
        await notify_event_subscribers(event, f'Event {event.name} is starting now!')
        return
    if before.start_time is not after.start_time and after.status is discord.EventStatus.scheduled:
        log.info(f'Scheduled event {before.id} start time changed, notifying users')
        await notify_event_subscribers(event, f'Event {event.name}\'s start time has changed to {after.start_time.astimezone(EASTERN_TIMEZONE).strftime("%B %d, %Y at %I:%M %p %Z")}')
    if (before.location is not after.location) or (before.channel is not after.channel):
        log.info(f'Scheduled event {before.id} location or channel changed, notifying users')
        await notify_event_subscribers(event, f'Event {event.name}\'s location or channel has changed')

def create_health_file():
    with open('connected', 'w'):
        pass

# Function to delete the health file
def delete_health_file():
    # Make sure the file exists
    if os.path.exists('connected'):
        os.remove('connected')

client.run(token=settings.discord_secret, log_handler=None)
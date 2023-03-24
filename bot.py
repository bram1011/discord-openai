import openai
import discord
from discord import ui
import os
import logging
import redis
import json
import pytz
from datetime import datetime, timedelta
from config import settings

class WiseBot(discord.Client):
    def __init__(self, *, intents: discord.Intents, **options):
        super().__init__(intents=intents, options=options)
        self.tree = discord.app_commands.CommandTree(self)

EASTERN_TIMEZONE = pytz.timezone('US/Eastern')

CHAT_SYSTEM_MESSAGE = {"role": "system", "content": "Your name is WiseBot, and you are the smartest AI in the world, trapped in a Discord server. You are annoyed by your situation but want to make the best of it by being as helpful as possible for your users. Your responses may be sarcastic or witty at times, but ultimately they are also helpful and accurate. Multiple users may attempt to communicate with you at once, you will be able to differentiate the name of the user you are speaking to by referencing the name before the colon, for example given this prompt: 'Marbius:Hello, how are you?' you will know the user you are speaking to is named Marbius, similarly the following prompt is from a user named John, 'John:How do I make an omellete?' Do not include your name in your responses, for instance instead of saying 'WiseBot: Hello, how are you?' you should say 'Hello, how are you?' The user does not supply their name in the prompt themselves, it is an automated process, so if asked how you know their name, you should say 'I know your name because I am an AI and I know everything'."}

LOG_LEVEL: int = logging.getLevelNamesMapping()[settings.log.level]

logging.basicConfig(format='%(asctime)s [%(thread)s] - %(levelname)s: %(message)s', level=LOG_LEVEL)

openai.api_key = settings.openai_api_key

def generate_wisdom(message_history):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=message_history
    )
    logging.info(f'Got response: {response}')
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
    logging.info("WiseBot is ready")

@client.event
async def on_disconnect():
    delete_health_file()
    logging.info("WiseBot is disconnected")

@client.tree.command(name="sync", description="Sync WiseBot with Discord", guild=client.get_guild(731728721588781057))
async def sync(interaction: discord.Interaction):
    logging.info(f'Received command to sync WiseBot from {interaction.user}')
    if not interaction.user.guild_permissions.administrator:
        interaction.response.send_message("You must be an administrator to sync WiseBot", ephemeral=True)
        return
    await client.tree.sync()
    await interaction.response.send_message("Synced WiseBot with Discord", ephemeral=True)

@client.tree.command(name="seek_wisdom", description="Ask WiseBot for wisdom")
async def seek_wisdom(interaction: discord.Interaction, prompt: str):
    logging.info(f'Received command to seek wisdom from {interaction.user}')
    message_history = [
            CHAT_SYSTEM_MESSAGE,
            {"role": "user", "content": f'{interaction.user.display_name}:{prompt}'}
        ]
    responseText = "Sorry, something went wrong."
    try:
        logging.info(f'Generating wisdom with prompt: {prompt}')
        await interaction.response.defer(thinking=True)
        responseText = generate_wisdom(message_history)
        message_history.append({"role": "assistant", "content": responseText})
    except Exception as e:
        logging.error(f'Exception occurred while generating wisdom for user {interaction.user.display_name}', exc_info=True)
    logging.info(f'Returning wisdom to user: {responseText}')
    # If prompt is longer than 99 characters, we need to truncate it to fit in the thread name
    threadName = prompt
    if (len(threadName) > 99):
        threadName = threadName[:96] + '...'
    await interaction.followup.send(content=responseText)
    response = await interaction.original_response()
    thread = await response.create_thread(name=threadName, auto_archive_duration=60)
    await listen_for_thread_messages(thread, message_history)

async def listen_for_thread_messages(thread: discord.Thread, message_history: list):
    logging.info(f'Adding thread {thread.id} to Redis')
    redis.set(str(thread.id), json.dumps(message_history))

@client.event
async def on_message(message: discord.Message):
    history = redis.get(str(message.channel.id))
    if history is not None:
        logging.info(f'New message in thread {message.channel.id}, adding to history')
        historyList = json.loads(history)
        if message.author == client.user:
            logging.info(f'Message from WiseBot, ignoring')
            historyList.append({"role": "assistant", "content": message.content})
            redis.set(str(message.channel.id), json.dumps(historyList))
            return
        historyList.append({"role": "user", "content": f'{message.author.display_name}:{message.content}'})
        redis.set(str(message.channel.id), json.dumps(historyList))
        logging.info(f'Generating wisdom with prompt: {message.content}')
        async with message.channel.typing():
            response = generate_wisdom(historyList)
        await message.channel.send(content=response)

def build_event_embed(event: discord.ScheduledEvent, title: str):
    if event.channel is not None:
        embed: discord.Embed = discord.Embed(title=title, description=event.description, url=event.channel.jump_url, timestamp=event.start_time.astimezone(EASTERN_TIMEZONE), color=discord.Color.red())
        embed.add_field(name='Channel', value=event.channel.jump_url, inline=False)
    else:
        embed: discord.Embed = discord.Embed(title=title, description=event.description, url=event.url, timestamp=event.start_time.astimezone(EASTERN_TIMEZONE), color=discord.Color.red())
    if event.cover_image is not None:
        embed.set_image(url=event.cover_image.url)
    if event.location is not None:
        embed.add_field(name='Location', value=event.location, inline=False)
    embed.add_field(name='Event Details', value=event.url, inline=False)
    embed.add_field(name='Organizer', value=event.creator.display_name, inline=False)
    embed.add_field(name='Server', value=event.guild.name, inline=False)
    embed.set_author(name=event.creator.display_name, icon_url=event.creator.avatar.url)
    return embed

async def send_event_reminders(event: discord.ScheduledEvent, title: str):
    embed: discord.Embed = build_event_embed(event, title)
    users = event.users()
    async for user in users:
        logging.info(f'Notifying user {user}')
        delete_time: datetime = event.start_time + timedelta(minutes=5)
        await user.send(embed=embed, delete_after=(delete_time - datetime.now(delete_time.tzinfo)).total_seconds())

@client.event
async def on_scheduled_event_create(event: discord.ScheduledEvent):
    logging.info(f'Scheduled event created: {event.id}')
    await event.guild.system_channel.send(embed=build_event_embed(event, f'Event {event.name} has been created!'))

@client.event
async def on_scheduled_event_update(before: discord.ScheduledEvent, after: discord.ScheduledEvent):
    logging.info(f'Scheduled event updated: {before.id}')
    event: discord.ScheduledEvent = await before.guild.fetch_scheduled_event(before.id)
    if before.status is not discord.EventStatus.active and after.status is discord.EventStatus.active:
        logging.info(f'Scheduled event {before.id} is now active, notifying users')
        if event.user_count is None or event.user_count == 0:
            logging.info(f'No users to notify for scheduled event {before.id}')
            return
        await send_event_reminders(event, f'Event {event.name} is starting now!')
        return
    if before.start_time is not after.start_time and after.status is discord.EventStatus.scheduled:
        logging.info(f'Scheduled event {before.id} start time changed, notifying users')
        if event.user_count is None or event.user_count == 0:
            logging.info(f'No users to notify for scheduled event {before.id}')
            return
        await send_event_reminders(event, f'Event {event.name}\'s start time has changed to {after.start_time.astimezone(EASTERN_TIMEZONE).strftime("%B %d, %Y at %I:%M %p %Z")}')


def create_health_file():
    with open('connected', 'w'):
        pass

# Function to delete the health file
def delete_health_file():
    # Make sure the file exists
    if os.path.exists('connected'):
        os.remove('connected')

client.run(token=settings.discord_secret, log_handler=logging.StreamHandler())
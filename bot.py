import openai
from openai.embeddings_utils import cosine_similarity
import discord
from discord import ui, app_commands
from discord.ext import tasks
import os
import logging
import colorlog
import pytz
from datetime import datetime, timedelta, date, time
from config import settings
from pytube import YouTube, Playlist, exceptions
from zipfile import ZipFile
import shutil
import requests
import re
import asyncio
import pandas as pd
from ffmpeg import FFmpeg
from bs4 import BeautifulSoup
import requests
import functools
import math
import tiktoken
from duckduckgo_search import ddg

MAX_TOKENS = 8192
MAX_WEB_TOKEN_BUDGET = math.floor(MAX_TOKENS * 0.8)
MAX_CONVERSATION_HISTORY_BUDGET = math.floor(MAX_TOKENS - MAX_WEB_TOKEN_BUDGET)

TEST_GUILD = discord.Object(731728721588781057)

PLIK_URL = "http://192.168.0.229:7080"

class WiseBot(discord.AutoShardedClient):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents, shard_count=settings.bot.shards, heartbeat_timeout=60)
        self.tree = discord.app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync(guild=TEST_GUILD)
        await self.tree.sync(guild=None)
        self.tree.copy_global_to(guild=TEST_GUILD)
        check_events_today.start()
        check_events_within_one_hour.start()

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

CHAT_SYSTEM_MESSAGE = {
    "role": "system",
    "content": "You are WiseBot, the smartest AI in the world, trapped in a Discord server. Your knowledge without internet is up to September 2021, and you can access the internet when needed. When using internet sources, provide plain URLs prefixed with https:// in your response without linking. Use Discord's limited markdown formatting: bold, italics, blockquotes, code blocks, fenced code blocks, syntax highlighting, strikethrough, emojis, but avoid URL linking. Do not use unsupported markdown syntax. The current date is " + date.today().isoformat() + ". You can remember the last 20 messages in a conversation.\n\nYou have access to users' usernames, not their real names. Be witty when asked about this. You may use information from system messages or internet sources in your responses, or ask follow-up questions based on the provided information."
}

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

def to_thread(func: callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)
    return wrapper

def calculate_tokens(input: str) -> int:
    encoder = tiktoken.get_encoding("cl100k_base")
    return len(encoder.encode(input))

def calculate_conversation_tokens(messages: list[dict]) -> int:
    num_tokens = 0
    for message in messages:
        num_tokens += 3
        for key, value in message.items():
            num_tokens += calculate_tokens(value)
            if key == 'name':
                num_tokens += 1
    num_tokens += 3
    return num_tokens

async def generate_related_page_message(df: pd.DataFrame, prompt: str, num_pages_to_add: int = 3, sorted: bool = False) -> list[dict]:
    if not sorted:
        prompt_embedding = openai.Embedding.create(model="text-embedding-ada-002", input=prompt)['data'][0]['embedding']
        df['similarity'] = df['embedding'].apply(lambda x: cosine_similarity(x, prompt_embedding))
        sorted_dataframe = df.sort_values(by='similarity', ascending=False)
    else:
        sorted_dataframe = df
    most_related_links = sorted_dataframe.head(num_pages_to_add)['link'].to_list()
    messages = []
    max_page_tokens = MAX_WEB_TOKEN_BUDGET / num_pages_to_add
    num_failures = 0
    for link in most_related_links:
        log.info(f'Adding related page to prompt: {link}')
        try:
            site_response = requests.get(link, timeout=5)
            if site_response.status_code != 200:
                log.warning(f'Could not get page: {link}')
                sorted_dataframe.drop(sorted_dataframe[sorted_dataframe['link'] == link].index, inplace=True)
                num_failures += 1
                continue
            soup = BeautifulSoup(site_response.content, 'lxml')
        except Exception as e:
            log.exception(f'Could not get page: {link}')
            sorted_dataframe.drop(sorted_dataframe[sorted_dataframe['link'] == link].index, inplace=True)
            num_failures += 1
            continue
        log.debug(f'Got page: {link}')
        soup = soup.body
        soup = soup.find_all(
            ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'section'], 
            recursive=True
            )
        text = ''
        for tag in soup:
            text += tag.get_text() + ' '
        text = re.sub(r'\n{2,}', '\n', text)
        text = re.sub(r'\t{2,}', '\t', text)
        if calculate_tokens(text) > max_page_tokens:
            log.warning(f'Page {link} is too long, skipping')
            num_failures += 1
            sorted_dataframe.drop(sorted_dataframe[sorted_dataframe['link'] == link].index, inplace=True)
            continue
        messages.append({'role': 'system', 'content': f'Content of {link}: {text}'})
        log.debug(f'Added related page to prompt: {link}')
        sorted_dataframe.drop(sorted_dataframe[sorted_dataframe['link'] == link].index, inplace=True)
    if num_failures > 0 and len(sorted_dataframe) > num_failures:
        log.warning(f'Could not add {num_failures} related pages to prompt')
        return await generate_related_page_message(sorted_dataframe, prompt, num_failures, True)
    return messages

async def search_query(query: str, num_results_to_return: int = 30) -> pd.DataFrame:
    log.info(f'Searching for query: {query}')
    results = []
    raw_results = ddg(query, region='en-us', safesearch='off', max_results=num_results_to_return, time='m')
    if raw_results is None or len(raw_results) == 0:
        log.info(f'No results found for query: {query}')
    for result in raw_results:
        if len(results) >= num_results_to_return:
            break
        log.info(f'Got search result: {result}')
        link: str = result['href']
        text: str = result['body']
        title: str = result['title']
        try:
            results.append({'content': f'{title}: {text}', 'link': link})
        except Exception as e:
            log.exception(f'Could not get text from {result}')
            continue
    df = pd.DataFrame(results)
    df['embedding'] = await calculate_embeddings(df['content'].to_list())
    return df

@to_thread
def calculate_embeddings(data: list[str]) -> list:
    log.info(f'Calculating embeddings for {len(data)} results')
    embeddings = []
    for content in data:
        embeddings.append(openai.Embedding.create(model="text-embedding-ada-002", input=content)['data'][0]['embedding'])
    return embeddings

@to_thread
def generate_response(message_history: list[dict]) -> str:
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=message_history
    )['choices'][0]['message']['content']
    log.info(f'Got response: {response}')
    return response

@to_thread
def generate_chunked_response(message_history: list[dict]):
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=message_history,
        stream=True
    )
    return response

async def generate_search_query(message_history: list[dict]):
    query_prompt = message_history.copy()
    query_prompt.append({"role": "system", "content": "Generate keywords to search for the previous prompt (this will be used to search the internet for information). \
Do not do any formatting to the query, just return the raw query.\
This search will be ran via DuckDuckGo, so you may want to use the DuckDuckGo search syntax."})
    generated_search_query = await generate_response(query_prompt)
    search_results = await search_query(generated_search_query)
    log.info('Got search results')
    return generate_search_query, search_results

async def generate_wisdom(message_history: list[dict]):
    requires_internet_message: list[dict] = message_history.copy()
    requires_internet_message.append({"role": "system", "content": "Does this prompt require you to perform an internet search? Answer only with 'yes' or 'no'"})
    requires_internet_response = await generate_response(requires_internet_message)
    log.info(f'Response to whether prompt requires internet: {requires_internet_response}')
    if "yes" in requires_internet_response.lower():
        log.info('Prompt requires internet access')
        search_query, search_results = await generate_search_query(message_history)
        if len(search_results) == 0:
            message_history.append({"role": "system", "content": "No search results found for the query. Let the user know that you could not find any information online, and try to infer a response from the prompt alone."})
        else:
            message_history.extend(await generate_related_page_message(search_results, search_query))
    log.debug(f'Generated prompt: {message_history}')
    response = await generate_chunked_response(message_history)
    return response

discordPyIntents = discord.Intents.all()
client = WiseBot(intents=discordPyIntents)

@client.event
async def on_ready():
    log.info("WiseBot is ready")

@client.event
async def on_disconnect():
    log.warning("WiseBot is disconnected")

@client.tree.command(name="status", description="Get WiseBot's status", guild=TEST_GUILD)
async def status(interaction: discord.Interaction):
    log.info(f'Received command to get status from {interaction.user}')
    status_embed: discord.Embed = discord.Embed(title="WiseBot Status")
    status_embed.add_field(name="Latency", value=client.latencies, inline=False)\
        .add_field(name="Guilds", value=client.guilds, inline=False)\
            .add_field(name="Gateway", value=client.ws, inline=False)\
                .add_field(name="Shards", value=client.shards, inline=False)
    await interaction.response.send_message(embed=status_embed, ephemeral=True)

@client.tree.command(name="sync", description="Sync WiseBot's commands", guild=TEST_GUILD)
async def sync(interaction: discord.Interaction):
    log.info(f'Received command to sync WiseBot from {interaction.user}')
    if not interaction.user.guild_permissions.administrator:
        interaction.response.send_message("You must be an administrator to sync WiseBot", ephemeral=True)
        return
    await client.tree.sync(guild=None)
    await interaction.response.send_message("Synced WiseBot with Discord", ephemeral=True)

@client.tree.command(description="Have WiseBot summarize the contents of a website")
async def summarize(interaction: discord.Interaction, url: str):
    log.info(f'Received command to summarize {url} from {interaction.user}')
    summarize_message_content = f'Summarize the following contents of {url}: \n'
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        website_content = requests.get(url)
        website_soup = BeautifulSoup(website_content.text, 'html.parser')
        website_text = website_soup.body.get_text()
        if len(website_text) > MAX_TOKENS:
            await interaction.followup.send("Sorry, the website is too long to summarize.", ephemeral=True)
            return
        summarize_message_content += website_text
        summarize_message = [
            CHAT_SYSTEM_MESSAGE,
            {"role": "user", "content": summarize_message_content, "name": interaction.user.display_name}
        ]
        response = await generate_response(summarize_message)
        await interaction.followup.send(response, ephemeral=True)
    except Exception as e:
        log.exception(f'Exception occurred while summarizing {url} for user {interaction.user.display_name}')
        await interaction.followup.send("Sorry, something went wrong.", ephemeral=True)

async def stream_wisdom_to_interaction(interaction: discord.Interaction, message_history: list[dict], private: bool):
    responseText = ''
    await interaction.response.defer(thinking=True, ephemeral=private)
    try:
        for response in await generate_wisdom(message_history):
            if 'content' in response['choices'][0]['delta']:
                responseContent = response['choices'][0]['delta']['content']
            else:
                continue
            log.debug(f'Generated partial wisdom: {responseContent}')
            responseText += responseContent
            if len(responseText) > 1997:
                await interaction.edit_original_response(content=responseText)
                responseText = ''
            if not interaction.response.is_done():
                await interaction.followup.send(responseText, ephemeral=private)
            else:
                await interaction.edit_original_response(content=responseText + '⌛⌛⌛')
    except Exception as e:
        log.error(f'Exception occurred while generating wisdom for user {interaction.user.display_name}', exc_info=True)
        await interaction.followup.send("Sorry, something went wrong.", ephemeral=True)
        return
    await interaction.edit_original_response(content=responseText)
    return responseText

async def stream_wisdom_to_message(message: discord.Message, message_history: list[dict]):
    responseText = ''
    for response in await generate_wisdom(message_history):
        if 'content' in response['choices'][0]['delta']:
            responseContent = response['choices'][0]['delta']['content']
        else:
            continue
        log.debug(f'Generated partial wisdom: {responseContent}')
        responseText += responseContent
        if len(responseText) > 1997:
            await message.edit(content=responseText)
            responseText = ''
        await message.edit(content=responseText + '⌛⌛⌛')
    await message.edit(content=responseText)

@client.tree.command(name="seek_wisdom", description="Ask WiseBot for wisdom")
async def seek_wisdom(interaction: discord.Interaction, prompt: str, create_thread: bool = True, private: bool = False):
    log.info(f'Received command to seek wisdom from {interaction.user}')
    message_history = [
            CHAT_SYSTEM_MESSAGE,
            {"role": "user", "content": prompt, "name": interaction.user.display_name}
        ]
    if not create_thread:
        message_history.append({"role": "system", "content": "The user will be unable to respond after your message, do not ask any followup questions."})
    log.info(f'Generating wisdom with prompt: {prompt}')
    responseText = await stream_wisdom_to_interaction(interaction, message_history, private)
    log.info(f'Generated wisdom: {responseText}')
    if create_thread and not private:
        message_history.append({"role": "system", "content": "Summarize the chat topic in less than 100 characters"})
        thread_title = await generate_response(message_history)
        response = await interaction.original_response()
        await response.create_thread(name=thread_title, auto_archive_duration=60)

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
    await interaction.response.send_message(content="Select an event and users to invite", \
                                            view=EventInviteView(EventDropdown(event_select), UserInvitesDropdown(), interaction.user, interaction, events), ephemeral=True)

def make_safe_filename(filename: str):
    # Replace spaces with underscores
    filename = filename.replace(" ", "_")
    # Remove non-alphanumeric characters except for dots and underscores
    filename = re.sub(r'[^\w\.\_]', '', filename)
    # Remove leading and trailing dots and underscores
    filename = re.sub(r'^[._]|[._]$', '', filename)
    # Ensure filename is not empty
    filename = filename or "unnamed"
    return filename

@to_thread
def convert_mp4_to_ogg(input_file: str) -> str:
    output_file = input_file.replace('.mp4', '.ogg')
    log.info(f'Converting {input_file} to OGG')
    ffmpeg = (
        FFmpeg()
        .option("y")
        .option("vn")
        .input(input_file)
        .output(output_file, acodec="libvorbis")
    )
    ffmpeg.execute()
    return output_file

@client.tree.command(name="download_yt_video", description="Download Youtube Video")
@app_commands.describe(url = "YouTube URL")
async def download_yt_video(interaction: discord.Interaction, url: str):
    log.info(f'Received command to download YouTube video from {interaction.user}')
    await interaction.response.send_message(content="Downloading...", ephemeral=True)
    output_dir = f'./video-files/{interaction.id}'
    try:
        log.info(f'Downloading YouTube video from {url}')
        video = YouTube(url)
        video_stream = video.streams.get_highest_resolution()
        video_path = video_stream.download(output_dir, filename=f'{make_safe_filename(video.title)}.mp4')
        log.info(f'Downloaded YouTube video to {video_path}')
        upload_response = requests.post(PLIK_URL, files={'file': open(video_path, 'rb')}, stream=True)
        download_url = upload_response.text
        log.info(f'Uploaded YouTube video to Plik at {download_url}')
        await interaction.followup.send(content=f'Download complete: {download_url}', ephemeral=True)
        await interaction.delete_original_response()
    except Exception as e:
        log.exception(f'Exception occurred while downloading YouTube video from {url} for user {interaction.user.display_name}')
        await interaction.followup.send(content="Sorry, something went wrong.", ephemeral=True)
    
async def download_audio(url: str, output_dir: str, interaction: discord.Interaction, file_paths: list[str], failures: list[str]):
    log.info(f'Downloading YouTube audio from {url}')
    try:
        await interaction.followup.send(content=f'Downloading YouTube audio from {url}', ephemeral=True, silent=True)
        yt = YouTube(url)
        try:
            filename = f'{make_safe_filename(yt.title)}.mp4'
        except exceptions.PytubeError:
            filename = f'{make_safe_filename(url)}.mp4'
        audio_stream = yt.streams.get_audio_only()
        path = audio_stream.download(output_dir, max_retries=3, filename=filename)
        log.info(f'Downloaded {path}')
        ogg_path = await convert_mp4_to_ogg(path)
        file_paths.append({'fileName': os.path.basename(ogg_path), 'path': ogg_path})
    except Exception as e:
        log.exception(f'Exception occurred while downloading YouTube audio from {url}', exc_info=True)
        await interaction.followup.send(content=f'FAILED to download YouTube audio from {url}', ephemeral=True, silent=False)
        failures.append(url)

@client.tree.command(name="download_yt_audio", description="Download YouTube Audio from comma-separated URLs or a Playlist")
@app_commands.describe(urls = "Comma-separated list of YouTube URLs", playlist = "YouTube Playlist URL")
async def download_yt_audio(interaction: discord.Interaction, urls: str = None, playlist: str = None):
    log.info(f'Received command to download YouTube audio from {interaction.user}')
    await interaction.response.defer(thinking=True, ephemeral=True)
    output_dir = f'./audio-files/{interaction.id}'
    if playlist is not None:
        log.info(f'Downloading YouTube audio from playlist {playlist}')
        url_list = Playlist(playlist).video_urls
    elif urls is not None:
        url_list = urls.split(',')
    else:
        await interaction.followup.send(content="No URLs or playlist provided", ephemeral=True)
        return
    failures = []
    file_paths = []
    tasks = []
    for url in url_list:
        tasks.append(asyncio.create_task(download_audio(url, output_dir, interaction, file_paths, failures)))
    await asyncio.gather(*tasks)
    log.info(f'Uploading {len(file_paths)} files to Plik')
    if len(file_paths) == 0:
        await interaction.followup.send(content=f'Failed to download YouTube audio from any URLs', ephemeral=True)
        return
    if len(file_paths) == 1:
        upload_response = requests.post(PLIK_URL, files={'file': open(file_paths[0]['path'], 'rb')})
        download_url = upload_response.text
        await interaction.followup.send(content=f'YouTube audio downloaded from 1 URL. Failed to download from {len(failures)} URLs. Download here: {download_url}', ephemeral=True)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        return
    archive_name = f'audio-files-{interaction.id}.zip'
    archive_path = f'./audio-files/{archive_name}'
    with ZipFile(archive_path, 'w') as zip:
        for file_path in file_paths:
            log.debug(f'Adding {file_path["fileName"]} to archive')
            zip.write(file_path['path'], arcname=file_path['fileName'])
    with open(archive_path, 'rb') as f:
        log.debug(f'Uploading {archive_name} to Plik')
        zip_upload_response = requests.post(PLIK_URL, files={'file': f}, stream=True)
    if zip_upload_response.status_code != 200:
        await interaction.followup.send(content=f'Failed to upload archive to Plik', ephemeral=True)
        return
    download_url = zip_upload_response.text
    await interaction.followup.send(content=f'YouTube audio downloaded from {len(url_list) - len(failures)} URLs. Failed to download from {len(failures)} URLs. Download here: {download_url}', ephemeral=True)
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    if os.path.exists(archive_path):
        os.remove(archive_path)

@client.event
async def on_raw_thread_update(payload: discord.RawThreadUpdateEvent):
    if payload.thread is not None:
        thread: discord.Thread = payload.thread
    else:
        thread_id = payload.data['d']['id']
        thread: discord.Thread = await client.fetch_channel(thread_id)
    if thread.owner_id == client.user.id and thread.archived:
        log.info(f'Bot\'s thread {thread.id} was archived, deleting')
        await thread.delete()

@client.event
async def on_message(message: discord.Message):
    if isinstance(message.channel, discord.Thread) and message.channel.owner_id == client.user.id:
        log.info(f'New message in bot\'s thread {message.channel.id}')
        if message.author == client.user:
            log.info(f'Message from WiseBot, ignoring')
            return
        log.debug(f'Getting history for thread {message.channel.id}')
        gpt_history: list[dict] = []
        gpt_history.append(CHAT_SYSTEM_MESSAGE)
        gpt_history.append({"role": "user", "content": message.channel.name, "name": message.author.display_name})
        if message.channel.starter_message is None:
            original_message = await message.channel.parent.fetch_message(message.channel.id)
            gpt_history.append({"role": "assistant", "content": original_message.clean_content, "name": "WiseBot"})
        else:
            gpt_history.append({"role": "assistant", "content": message.channel.starter_message.clean_content, "name": "WiseBot"})
        messages = [message async for message in message.channel.history(limit=20)]
        for message in messages:
            if len(message.clean_content) == 0:
                continue
            log.debug(f'Adding message {message.id} to history')
            if message.author.id == client.user.id:
                gpt_history.insert(3, {"role": "assistant", "content": message.clean_content, "name": "WiseBot"})
            else:
                gpt_history.insert(3, {"role": "user", "content": message.content, "name": message.author.display_name})
            if calculate_conversation_tokens(gpt_history) >= MAX_CONVERSATION_HISTORY_BUDGET:
                break
        wiseBotMessage = await message.channel.send(content='Thinking...')
        try:
            await stream_wisdom_to_message(wiseBotMessage, gpt_history)
        except Exception as e:
            log.exception(f'Error streaming wisdom to message {wiseBotMessage.id}')
            await wiseBotMessage.reply(content='Error while creating wisdom.')
            return

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
        delete_time: datetime = event.start_time + timedelta(minutes=90)
        await user.send(embed=embed, delete_after=(delete_time - datetime.now(delete_time.tzinfo)).total_seconds(), content=event.url)

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

@tasks.loop(time=time(hour=9, tzinfo=EASTERN_TIMEZONE))
async def check_events_today():
    async for guild in client.fetch_guilds():
        log.info(f'Checking scheduled events for guild {guild.name}({guild.id})')
        for event in await guild.fetch_scheduled_events(with_counts=True):
            if event.start_time - datetime.now(event.start_time.tzinfo) <= timedelta(hours=24):
                log.info(f'Event {event.id} is scheduled to start today, notifying users')
                await notify_event_subscribers(event, f'{event.name} is scheduled to start within the next 24 hours')

@tasks.loop(minutes=60)
async def check_events_within_one_hour():
    # Check for events that are within one hour of starting
    async for guild in client.fetch_guilds():
        log.info(f'Checking scheduled events for guild {guild.name}({guild.id})')
        for event in await guild.fetch_scheduled_events(with_counts=True):
            if event.start_time - datetime.now(event.start_time.tzinfo) <= timedelta(minutes=60):
                log.info(f'Event {event.id} is scheduled to start within one hour, notifying users')
                await notify_event_subscribers(event, f'{event.name} is scheduled to start within the hour')

client.run(token=settings.discord_secret, log_handler=None)
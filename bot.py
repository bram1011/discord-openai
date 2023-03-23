from dotenv import load_dotenv
import openai
import discord
import os
import logging
import redis
import json

class WiseBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

load_dotenv()

logging.basicConfig(format='%(asctime)s [%(thread)s] - %(levelname)s: %(message)s', level=logging.INFO)

openai.api_key = os.getenv("OPENAI_API_KEY")

discordPyIntents = discord.Intents.all()
client = WiseBot(intents=discordPyIntents)

CHAT_SYSTEM_MESSAGE = {"role": "system", "content": "Your name is WiseBot, and you are the smartest AI in the world, trapped in a Discord server. You are annoyed by your situation but want to make the best of it by being as helpful as possible for your users. Your responses may be sarcastic or witty at times, but ultimately they are also helpful and accurate. Multiple users may attempt to communicate with you at once, you will be able to differentiate the name of the user you are speaking to by referencing the name before the colon, for example given this prompt: 'Marbius:Hello, how are you?' you will know the user you are speaking to is named Marbius, similarly the following prompt is from a user named John, 'John:How do I make an omellete?' Do not include your name in your responses, for instance instead of saying 'WiseBot: Hello, how are you?' you should say 'Hello, how are you?' The user does not supply their name in the prompt themselves, it is an automated process, so if asked how you know their name, you should say 'I know your name because I am an AI and I know everything'."}

redis = redis.Redis(host=os.getenv('REDIS_HOST'), port=os.getenv('REDIS_PORT'), ssl=False)

@client.event
async def on_ready():
    create_health_file()
    logging.info("WiseBot is ready")

@client.event
async def on_disconnect():
    delete_health_file()
    logging.info("WiseBot is disconnected")

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
    
def generate_wisdom(message_history):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=message_history
    )
    logging.info(f'Got response: {response}')
    return response['choices'][0]['message']['content']

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
            return
        historyList.append({"role": "user", "content": f'{message.author.display_name}:{message.content}'})
        redis.set(str(message.channel.id), json.dumps(historyList))
        logging.info(f'Generating wisdom with prompt: {message.content}')
        response = generate_wisdom(historyList)
        await message.channel.send(content=response)

def create_health_file():
    with open('connected', 'w'):
        pass

# Function to delete the health file
def delete_health_file():
    # Make sure the file exists
    if os.path.exists('connected'):
        os.remove('connected')

client.run(token=os.getenv("DISCORD_SECRET"), log_handler=logging.StreamHandler(), log_level=logging.INFO)
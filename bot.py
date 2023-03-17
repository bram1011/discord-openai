from dotenv import load_dotenv
import openai
import datetime
import time
import os
import interactions
from worker import worker
from flask import Flask
from healthcheck import HealthCheck

load_dotenv()

connected = False

openai.api_key = os.getenv("OPENAI_API_KEY")

bot = interactions.Client(token=os.getenv('DISCORD_SECRET'), intents=interactions.Intents.ALL)

CHAT_SYSTEM_MESSAGE = {"role": "system", "content": "You are the smartest AI in the world, trapped in a Discord server. You are annoyed by your situation but want to make the best of it by being as helpful as possible for your users."}

@bot.command(
    name="create_image",
    description="Create an image from a text prompt"
)
@interactions.option()
async def create_image(ctx: interactions.CommandContext, prompt: str):
    print(f'Received command to generate image from {ctx.member}')
    await ctx.defer()
    try:
        image = generate_image(prompt)
        print(f'Generated image: {image}')
        await ctx.send(image)
    except Exception as e:
        print(f'Could not complete request due to error: {e}')
        await ctx.send('Sorry, I could not complete your beautiful artwork, please try again.')

@bot.command(
    name = "seek_wisdom",
    description = "Seek the bot's wisdom, ask a question or have it perform a task"
)
@interactions.option()
async def seek_wisdom(ctx: interactions.CommandContext, prompt: str):
    print(f'Received command to seek wisdom from {ctx.member}')
    await ctx.defer()
    try:
        responseText = generate_wisdom(prompt)
        print(f'Returning wisdom to user: {responseText}')
        sent_message = await ctx.send(responseText)
        thread = await sent_message.create_thread(name=prompt)
        await thread.join()
        await thread.add_member(ctx.member.id)
    except Exception as e:
        print(f'Could not complete request due to error: {e}')
        await ctx.send('Sorry, I could not complete your request. Please try again.')
    await listen_for_thread_messages(thread, datetime.datetime.now() + datetime.timedelta(minutes=15), sent_message, prompt)
    
def generate_wisdom(userPrompt: str):
    print(f'Generating wisdom with prompt: {userPrompt}')
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            CHAT_SYSTEM_MESSAGE,
            {"role": "user", "content": userPrompt}
        ]
    )
    print(f'Got response: {response}')
    return response['choices'][0]['message']['content']

def generate_image(prompt: str):
    print(f'Generating image with prompt: {prompt}')
    return openai.Image.create(prompt=prompt, n=1, size="256x256")['data'][0]['url']

@bot.event
async def on_disconnect():
    global connected
    connected = False
    print("WiseBot has been disconnected")

@bot.event
async def on_ready():
    global connected
    connected = True
    print("WiseBot is ready")

def check_if_ready():
    global connected
    return connected, connected

@worker
def start_bot_in_new_process():
    bot.start()

async def listen_for_thread_messages(thread: interactions.Channel, whenToStopListening: datetime.datetime, startFrom: interactions.Message, userPrompt: str):
    currentMessages = 2
    while (datetime.datetime.now() < whenToStopListening):
        history = thread.history(reverse=True, start_at=startFrom)
        print(f'Checking if thread {thread.id} has new messages')
        messageList = await history.flatten()
        if (len(messageList) > currentMessages):
            print('Detected new message, building message history')
            currentMessages = len(messageList) + 1
            whenToStopListening = datetime.datetime.now() + datetime.timedelta(minutes=10)
            gptMessageDict = []
            gptMessageDict.append(CHAT_SYSTEM_MESSAGE)
            gptMessageDict.append({"role": "user", "content": userPrompt})
            gptMessageDict.append({"role": "assistant", "content": startFrom.content})
            for message in messageList:
                if len(message.content) > 1 and (message.type == interactions.MessageType.DEFAULT or message.type == interactions.MessageType.REPLY):
                    if (message.author.bot):
                        gptMessageDict.append({"role": "assistant", "content": message.content})
                    else:
                        gptMessageDict.append({"role": "user", "content": message.content})
            print(f'Built message history: {gptMessageDict}')
            try:
                response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=gptMessageDict
                )
                print(f'Got response: {response}')
                await thread.send(content=response['choices'][0]['message']['content'])
            except Exception as e:
                print(f'Exception while replying to thread: {e}')
                await thread.send(content="Sorry something went wrong, please try again")
        print('Sleeping')
        time.sleep(5)
    await thread.archive()

app = Flask(__name__)
health = HealthCheck(checkers=[check_if_ready])
app.add_url_rule('/health', 'health', view_func=lambda: health.run())

start_bot_in_new_process()
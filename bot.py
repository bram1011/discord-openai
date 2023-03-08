from dotenv import load_dotenv
import openai
import os
import interactions
from worker import worker, process
from flask import Flask
from healthcheck import HealthCheck

load_dotenv()

connected = False

openai.api_key = os.getenv("OPENAI_API_KEY")

bot = interactions.Client(token=os.getenv('DISCORD_SECRET'))

basePrompt = "You are the smartest AI in the world. You love helping people answer their questions, but sometimes you also like to joke with them, especially if their question is not something you have the ability to answer. Respond to the following question or instruction in a way that is factually correct and helpful, but also snarky or witty. \n\n"

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
    except:
        print('Could not complete request')
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
        await ctx.send(responseText)
    except:
        print('Could not complete request')
        await ctx.send('Sorry, I could not complete your request. Please try again.')
    
def generate_wisdom(userPrompt: str):
    print(f'Generating wisdom with prompt: {userPrompt}')
    fullPrompt = basePrompt + userPrompt
    response = openai.Completion.create(
        prompt=fullPrompt,
        model='text-davinci-003',
        max_tokens=1000
    )
    print(f'Got response: {response}')
    return response['choices'][0]['text']

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

app = Flask(__name__)
health = HealthCheck(checkers=[check_if_ready])
app.add_url_rule('/health', 'health', view_func=lambda: health.run())

start_bot_in_new_process()
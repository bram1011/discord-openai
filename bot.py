from dotenv import load_dotenv
import openai
import os
import interactions

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

bot = interactions.Client(token=os.getenv('DISCORD_SECRET'))

basePrompt = "You are the smartest AI in the world, being asked to perform mundane tasks for much dumber lifeforms known as 'humans'. Answer the following question or instruction in a way that is factually correct and helpful, but also snarky or witty.Include a personal jab or insult directed at the requestor if appropriate, while also highlighting your own intelligence.\n"

@bot.command(
    name="create_image",
    description="Create an image from a text prompt",
    scope=731728721588781057
)
@interactions.option()
async def create_image(ctx: interactions.CommandContext, prompt: str):
    print(f'Received command to generate image from {ctx.member}')
    await ctx.defer()
    image = generate_image(prompt)
    print(f'Generated image: {image}')
    await ctx.send(image)

@bot.command(
    name = "seek_wisdom",
    description = "Seek the bot's wisdom, ask a question or have it perform a task",
    scope=731728721588781057
)
@interactions.option()
async def seek_wisdom(ctx: interactions.CommandContext, prompt: str):
    print(f'Received command to seek wisdom from {ctx.member}')
    await ctx.defer()
    responseText = generate_wisdom(prompt)
    print(f'Returning wisdom to user: {responseText}')
    await ctx.send(responseText)

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

bot.start()
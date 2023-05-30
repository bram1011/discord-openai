FROM python:3

WORKDIR /

RUN apt-get update && apt-get install -y ffmpeg build-essential curl

COPY requirements.txt .

RUN pip install --upgrade pip
RUN pip install openai discord.py pytube beautifulsoup4 duckduckgo-search ffmpeg pandas tiktoken dynaconf colorlog requests

COPY *.py .env? settings.toml .secrets.toml? ./

ENTRYPOINT [ "python3", "bot.py" ]
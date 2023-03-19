FROM python:3

WORKDIR /usr/src/discord-bot

COPY requirements.txt ./

RUN pip install -r requirements.txt

COPY bot.py .env? ./

ENTRYPOINT [ "python3", "bot.py" ]
FROM python:3

WORKDIR /usr/src/discord-bot

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY bot.py .

CMD ["python", "bot.py"]
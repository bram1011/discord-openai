FROM python:3

WORKDIR /usr/src/discord-bot

COPY requirements.txt ./

RUN pip install -r requirements.txt

HEALTHCHECK --start-period=10s CMD curl --fail http://localhost:5000/health || exit 1

COPY bot.py .env? ./

CMD ["flask", "--app", "bot", "run"]
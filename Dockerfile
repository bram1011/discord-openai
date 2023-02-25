FROM python:3

WORKDIR /usr/src/discord-bot

COPY requirements.txt ./

RUN pip install -r requirements.txt

HEALTHCHECK CMD [ "curl", "http://localhost:5000/health" ]

COPY bot.py .env ./

CMD ["flask", "--app", "bot", "run"]
FROM python:3

WORKDIR /usr/src/discord-bot

COPY requirements.txt ./

RUN pip install -r requirements.txt

COPY *.py .env? settings.toml? ./

# Healthcheck to check if the 'connected' file exists
HEALTHCHECK --interval=30s --timeout=3s \
  CMD test -f /usr/src/discord-bot/connected || exit 1

ENTRYPOINT [ "python3", "bot.py" ]
FROM python:3

WORKDIR /usr/src/discord-bot

RUN apt-get update && apt-get install -y ffmpeg build-essential curl

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

COPY requirements.txt .

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY *.py .env? settings.toml? .secrets.toml? ./

ENTRYPOINT [ "python3", "bot.py" ]
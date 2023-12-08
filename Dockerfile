FROM python:3

WORKDIR /

RUN pip install --upgrade pip

COPY src/*.py .env? settings.toml .secrets.toml? requirements.txt ./

RUN pip install -r requirements.txt

ENTRYPOINT [ "python3", "bot.py" ]
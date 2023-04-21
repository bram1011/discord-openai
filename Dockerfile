FROM python:3

RUN apt-get update && apt-get install -y ffmpeg build-essential curl

COPY requirements.txt .

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="${PATH}:/root/.cargo/bin"
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
RUN pip install setuptools-rust
RUN curl -L https://github.com/openai/tiktoken/archive/refs/tags/0.3.3.tar.gz | tar zxf - && cd tiktoken-0.3.3 && python3 setup.py install

COPY *.py .env? settings.toml? .secrets.toml? ./

ENTRYPOINT [ "python3", "bot.py" ]
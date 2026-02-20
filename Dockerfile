FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py discord_sender.py bot.py ./

CMD ["python", "-u", "bot.py"]

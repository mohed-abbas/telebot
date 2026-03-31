FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps mt5linux==1.0.3

COPY config.py discord_sender.py bot.py ./
COPY signal_parser.py models.py signal_keywords.json ./
COPY mt5_connector.py risk_calculator.py trade_manager.py executor.py ./
COPY notifier.py db.py dashboard.py maintenance.py ./
COPY templates/ ./templates/
COPY static/ ./static/

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "-u", "bot.py"]

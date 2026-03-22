FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py discord_sender.py bot.py ./
COPY signal_parser.py models.py signal_keywords.json ./
COPY mt5_connector.py risk_calculator.py trade_manager.py executor.py ./
COPY notifier.py db.py dashboard.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY docs/ ./docs/
COPY nginx/ ./nginx/

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "-u", "bot.py"]

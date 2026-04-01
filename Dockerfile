FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps mt5linux==1.0.3

COPY *.py *.json ./
COPY templates/ ./templates/
COPY static/ ./static/

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "-u", "bot.py"]

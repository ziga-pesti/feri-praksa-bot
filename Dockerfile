FROM python:3.11-alpine

WORKDIR /app
COPY praksa_bot.py config.json ./

CMD ["python3", "praksa_bot.py"]

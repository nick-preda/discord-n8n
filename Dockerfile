FROM python:3.11-slim

WORKDIR /app

# Evita buffer su stdout/stderr
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Avvia il bot
CMD ["python", "bot.py"]
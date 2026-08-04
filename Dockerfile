FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY stripe_prices.json* ./

ENV PORT=10000
EXPOSE 10000

CMD uvicorn server:app --host 0.0.0.0 --port ${PORT}

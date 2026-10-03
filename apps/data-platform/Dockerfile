FROM python:3.11-slim

WORKDIR /app

# Deps
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Симуляторы
COPY *.py /app/

# Entrypoint (по умолчанию — farcana)
CMD ["python", "farcana_director.py"]
# CI test Sat Oct  3 12:33:46 +03 2026

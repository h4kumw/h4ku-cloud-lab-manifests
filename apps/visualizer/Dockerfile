FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    flask \
    flask-socketio \
    requests \
    psycopg2-binary

COPY app.py .

CMD ["python3", "app.py"]

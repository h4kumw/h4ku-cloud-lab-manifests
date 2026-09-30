"""Единый конфиг для всех симуляторов.
Работает и локально (Docker Compose), и в K8s (через ENV).
"""
import os

# PostgreSQL
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "admin")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DB = os.getenv("PG_DB", "farcana")

# ClickHouse
CH_HOST = os.getenv("CH_HOST", "localhost")
CH_PORT = int(os.getenv("CH_PORT", "8123"))
CH_USER = os.getenv("CH_USER", "admin")
CH_PASSWORD = os.getenv("CH_PASSWORD", "admin")
CH_URL = f"http://{CH_HOST}:{CH_PORT}/"
CH_PARAMS = {"user": CH_USER, "password": CH_PASSWORD}

# MinIO
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_USER = os.getenv("MINIO_USER", "minioadmin")
MINIO_PASSWORD = os.getenv("MINIO_PASSWORD", "minioadmin")

# Mosquitto (MQTT)
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# InfluxDB
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086/api/v2/write")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "admin123")
INFLUX_ORG = os.getenv("INFLUX_ORG", "cps")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "cps_telemetry")

# Kafka
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "cps-sensors")

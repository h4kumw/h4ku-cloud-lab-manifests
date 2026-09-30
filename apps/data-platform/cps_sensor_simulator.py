"""CPS симулятор — MQTT + InfluxDB + PostgreSQL (OLTP)."""
import paho.mqtt.client as mqtt
import random
import time
import json
import requests
import psycopg2
from config import (
    MQTT_HOST, MQTT_PORT,
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
    PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB,
    KAFKA_BOOTSTRAP, KAFKA_TOPIC,
)
from kafka import KafkaProducer
from datetime import datetime


class CPSSensorSimulator:
    HOTSPOTS = [
        (40.7, -74.0), (51.5, -0.1), (35.7, 139.7),
        (1.35, 103.8), (-33.9, 151.2), (55.7, 37.6),
        (52.5, 13.4), (48.9, 2.35), (-23.5, -46.6),
        (19.4, -99.1), (28.6, 77.2), (-1.3, 36.8),
    ]

    def __init__(self):
        # MQTT (real-time)
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.connect(MQTT_HOST, MQTT_PORT)

        # InfluxDB (time-series)
        self.influx_url = INFLUX_URL
        self.influx_token = INFLUX_TOKEN

        # PostgreSQL (OLTP)
        self.pg_conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, user=PG_USER,
            password=PG_PASSWORD, database=PG_DB,
        )

        # Kafka (stream, для CH Kafka Engine)
        try:
            self.kafka_producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks=1,
                retries=3,
            )
            print(f"[KAFKA] Producer connected to {KAFKA_BOOTSTRAP}")
        except Exception as e:
            print(f"[KAFKA] Init failed: {e}")
            self.kafka_producer = None

    def generate_sensor_data(self):
        devices = ["sensor_01", "sensor_02", "sensor_03", "edge_01", "edge_02"]
        sensors = ["temperature", "pressure", "vibration", "humidity", "current"]

        device = random.choice(devices)
        sensor = random.choice(sensors)

        ranges = {
            "temperature": (15, 85),
            "pressure": (950, 1050),
            "vibration": (0, 10),
            "humidity": (20, 90),
            "current": (0, 50),
        }
        units = {
            "temperature": "°C",
            "pressure": "hPa",
            "vibration": "mm/s",
            "humidity": "%",
            "current": "A",
        }

        value = random.uniform(*ranges[sensor])

        return {
            "timestamp": datetime.now().isoformat(),
            "device": device,
            "sensor": sensor,
            "value": round(value, 2),
            "unit": units.get(sensor, "unit"),
            "location": f"factory_{random.randint(1, 3)}",
        }

    def send_mqtt(self, data):
        topic = f"cps/{data['device']}/{data['sensor']}"
        self.mqtt_client.publish(topic, json.dumps(data))

    def send_influxdb(self, data):
        line = (
            f"sensors,device={data['device']},sensor={data['sensor']},"
            f"location={data['location']} value={data['value']} "
            f"{int(datetime.now().timestamp() * 1e9)}"
        )
        headers = {
            "Authorization": f"Token {self.influx_token}",
            "Content-Type": "text/plain",
        }
        params = {"org": INFLUX_ORG, "bucket": INFLUX_BUCKET, "precision": "ns"}
        try:
            requests.post(self.influx_url, headers=headers, params=params, data=line)
        except Exception as e:
            print(f"[INFLUX] Error: {e}")

    def save_to_postgres(self, data):
        """Сенсоры в PostgreSQL (OLTP)."""
        cursor = self.pg_conn.cursor()
        cursor.execute("""
            INSERT INTO cps_sensors 
                (device_id, sensor_type, value, unit, location)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            data["device"],
            data["sensor"],
            data["value"],
            data["unit"],
            data["location"],
        ))
        self.pg_conn.commit()

    def send_kafka(self, data):
        """Stream в Kafka (для CH Kafka Engine)."""
        if not self.kafka_producer:
            return
        payload = {
            "timestamp": data["timestamp"],
            "device_id": data["device"],
            "sensor_type": data["sensor"],
            "value": data["value"],
            "unit": data["unit"],
            "location": data["location"],
        }
        try:
            self.kafka_producer.send(KAFKA_TOPIC, payload)
        except Exception as e:
            print(f"[KAFKA] Error: {e}")

    def run(self):
        while True:
            for _ in range(random.randint(1, 5)):
                data = self.generate_sensor_data()
                self.send_mqtt(data)          # MQTT (real-time)
                self.send_influxdb(data)      # InfluxDB (time-series)
                self.save_to_postgres(data)   # PostgreSQL (OLTP)
                self.send_kafka(data)         # Kafka (stream → CH)
                print(f"[CPS] {data['device']}/{data['sensor']}={data['value']}{data['unit']} (MQTT+Influx+PG+Kafka)")
            time.sleep(random.uniform(0.5, 2))


if __name__ == "__main__":
    sim = CPSSensorSimulator()
    sim.run()

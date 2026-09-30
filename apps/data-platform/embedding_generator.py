"""Генератор embeddings из игровых логов через Ollama → pgvector."""
import os
import json
import psycopg2
import requests
from datetime import datetime

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "admin")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DB = os.getenv("PG_DB", "farcana")
CH_HOST = os.getenv("CH_HOST", "localhost")
CH_PORT = int(os.getenv("CH_PORT", "8123"))
CH_USER = os.getenv("CH_USER", "admin")
CH_PASSWORD = os.getenv("CH_PASSWORD", "admin")


def get_embedding(text):
    """Получить embedding через Ollama (GPU)."""
    resp = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": text},
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def ch_query(query):
    """Запрос в ClickHouse."""
    ch_url = f"http://{CH_HOST}:{CH_PORT}/"
    params = {"user": CH_USER, "password": CH_PASSWORD}
    r = requests.get(ch_url, params={**params, "query": query + " FORMAT JSON"}, timeout=10)
    if r.status_code == 200:
        return r.json().get("data", [])
    return []


def fetch_logs(limit=500):
    """Собирает последние события из ClickHouse."""
    logs = []

    # Farcana match events
    for row in ch_query(f"""
        SELECT event_time, match_id, player_id, event_type, lat, lon
        FROM game_analytics.match_telemetry
        WHERE event_time > now() - INTERVAL 60 MINUTE
        ORDER BY event_time DESC
        LIMIT 200
    """):
        text = (f"Farcana match {row['match_id'][:8]} player {row['player_id'][:8]} "
                f"event {row['event_type']} at ({row['lat']:.2f},{row['lon']:.2f})")
        logs.append({
            "log_id": f"farcana_{row['match_id']}_{row['event_time']}",
            "text": text,
            "source": "farcana",
            "metadata": row
        })

    # Chimeras NFT
    for row in ch_query(f"""
        SELECT timestamp, nft_id, price, from_address, to_address
        FROM game_analytics.nft_transactions
        WHERE timestamp > now() - INTERVAL 60 MINUTE
        ORDER BY timestamp DESC
        LIMIT 200
    """):
        text = (f"Chimeras NFT {row['nft_id'][:12]} sold for {row['price']:.2f} "
                f"from {row['from_address'][:10]} to {row['to_address'][:10]}")
        logs.append({
            "log_id": f"chimeras_{row['nft_id']}_{row['timestamp']}",
            "text": text,
            "source": "chimeras",
            "metadata": row
        })

    # CPS sensors
    for row in ch_query(f"""
        SELECT timestamp, device_id, sensor_type, value, unit, location
        FROM game_analytics.sensor_data
        WHERE timestamp > now() - INTERVAL 60 MINUTE
        ORDER BY timestamp DESC
        LIMIT 200
    """):
        text = (f"CPS {row['device_id']} {row['sensor_type']} = {row['value']:.2f} "
                f"{row['unit']} at {row['location']}")
        logs.append({
            "log_id": f"cps_{row['device_id']}_{row['sensor_type']}_{row['timestamp']}",
            "text": text,
            "source": "cps",
            "metadata": row
        })

    return logs


def store_embeddings(items):
    """Сохраняет embeddings в pgvector."""
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, database=PG_DB
    )
    cur = conn.cursor()
    stored = 0
    skipped = 0

    for item in items:
        vector_str = "[" + ",".join(str(x) for x in item["embedding"]) + "]"
        try:
            cur.execute("""
                INSERT INTO game_log_embeddings 
                    (log_id, log_text, log_source, embedding, metadata)
                VALUES (%s, %s, %s, %s::vector, %s)
                ON CONFLICT (log_id) DO NOTHING
            """, (
                item["log_id"],
                item["text"],
                item["source"],
                vector_str,
                json.dumps(item["metadata"], default=str)
            ))
            if cur.rowcount > 0:
                stored += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"Error storing {item['log_id']}: {e}")

    conn.commit()
    cur.close()
    conn.close()
    return stored, skipped


def main():
    print(f"[{datetime.now()}] Starting embedding generation...")
    start = datetime.now()

    logs = fetch_logs(limit=500)
    print(f"Fetched {len(logs)} logs from ClickHouse")

    if not logs:
        print("No logs to process")
        return

    embeddings = []
    for i, log in enumerate(logs):
        try:
            emb = get_embedding(log["text"])
            embeddings.append({
                "log_id": log["log_id"],
                "text": log["text"],
                "source": log["source"],
                "embedding": emb,
                "metadata": log["metadata"]
            })
            if (i + 1) % 10 == 0:
                print(f"  Embedded {i+1}/{len(logs)}")
        except Exception as e:
            print(f"Error embedding {log['log_id']}: {e}")

    stored, skipped = store_embeddings(embeddings)
    duration = (datetime.now() - start).total_seconds()

    print(f"[{datetime.now()}] Done in {duration:.1f}s")
    print(f"  Stored: {stored}")
    print(f"  Skipped (duplicates): {skipped}")


if __name__ == "__main__":
    main()

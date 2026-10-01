"""Farcana ETL: PostgreSQL → ClickHouse (batch каждые 5 минут)."""
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime, timedelta
import json
import requests


CLICKHOUSE_URL = "http://clickhouse.infra.svc.cluster.local:8123/"
CLICKHOUSE_PARAMS = {"user": "admin", "password": "admin"}
BATCH_SIZE = 5000


def extract_from_postgres(**context):
    pg_hook = PostgresHook(postgres_conn_id='postgres_farcana')

    sql = """
        SELECT id, event_time, match_id, player_id, event_type,
               lat, lon, ping, server_id
        FROM match_telemetry
        WHERE synced_to_ch = FALSE
        ORDER BY event_time ASC
        LIMIT %s
    """
    records = pg_hook.get_records(sql, parameters=(BATCH_SIZE,))

    if not records:
        print("No new records")
        return []

    data = [dict(zip(
        ['id', 'event_time', 'match_id', 'player_id', 'event_type', 'lat', 'lon', 'ping', 'server_id'],
        r
    )) for r in records]

    print(f"Extracted {len(data)} records from PostgreSQL")
    return data


def load_to_clickhouse(**context):
    ti = context['ti']
    data = ti.xcom_pull(task_ids='extract_from_postgres')

    if not data:
        print("No data to load")
        return 0

    lines = []
    for row in data:
        event_time = row['event_time']
        if hasattr(event_time, 'isoformat'):
            event_time = event_time.isoformat()
        lines.append(json.dumps({
            "event_time": event_time,
            "match_id":   row['match_id'],
            "player_id":  row['player_id'],
            "event_type": row['event_type'],
            "lat":        row['lat'],
            "lon":        row['lon'],
            "ping":       row['ping'],
            "server_id":  row['server_id'] or '',
        }, ensure_ascii=False))

    body = "\n".join(lines)

    resp = requests.post(
        CLICKHOUSE_URL,
        params={
            **CLICKHOUSE_PARAMS,
            "query": "INSERT INTO game_analytics.match_telemetry "
                     "(event_time, match_id, player_id, event_type, lat, lon, ping, server_id) "
                     "FORMAT JSONEachRow",
        },
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        timeout=60,
    )
    if resp.status_code != 200:
        raise Exception(f"ClickHouse error ({resp.status_code}): {resp.text[:500]}")

    ids = [row['id'] for row in data]
    pg_hook = PostgresHook(postgres_conn_id='postgres_farcana')
    pg_hook.run(
        "UPDATE match_telemetry SET synced_to_ch = TRUE WHERE id = ANY(%s)",
        parameters=(ids,),
    )

    print(f"Loaded {len(data)} records to ClickHouse (ids: {len(ids)})")
    return len(data)


with DAG(
    dag_id='farcana_etl',
    default_args={
        'owner': 'devops',
        'depends_on_past': False,
        'start_date': datetime(2026, 9, 1),
        'retries': 2,
        'retry_delay': timedelta(minutes=1),
    },
    schedule='*/5 * * * *',
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=['farcana', 'etl', 'oltp-olap'],
) as dag:
    extract = PythonOperator(task_id='extract_from_postgres', python_callable=extract_from_postgres)
    load = PythonOperator(task_id='load_to_clickhouse', python_callable=load_to_clickhouse)
    extract >> load

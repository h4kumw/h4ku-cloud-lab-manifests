"""Chimeras ETL: PostgreSQL nft_transactions → ClickHouse."""
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
        SELECT tx_hash, nft_id, from_address, to_address, price, timestamp
        FROM nft_transactions
        WHERE synced_to_ch = FALSE
        ORDER BY timestamp ASC
        LIMIT %s
    """
    records = pg_hook.get_records(sql, parameters=(BATCH_SIZE,))
    if not records:
        print("No new records")
        return []
    data = [dict(zip(
        ['tx_hash', 'nft_id', 'from_address', 'to_address', 'price', 'timestamp'],
        r
    )) for r in records]
    print(f"Extracted {len(data)} nft_transactions from PostgreSQL")
    return data


def load_to_clickhouse(**context):
    ti = context['ti']
    data = ti.xcom_pull(task_ids='extract_from_postgres')
    if not data:
        print("No data to load")
        return 0
    lines = []
    for row in data:
        ts = row['timestamp']
        if hasattr(ts, 'isoformat'):
            ts = ts.isoformat()
        lines.append(json.dumps({
            "timestamp":    ts,
            "tx_hash":      row['tx_hash'],
            "nft_id":       row['nft_id'] or '',
            "from_address": row['from_address'] or '',
            "to_address":   row['to_address'] or '',
            "price":        float(row['price']) if row['price'] is not None else 0.0,
        }, ensure_ascii=False))
    body = "\n".join(lines)
    resp = requests.post(
        CLICKHOUSE_URL,
        params={
            **CLICKHOUSE_PARAMS,
            "query": "INSERT INTO game_analytics.nft_transactions "
                     "(timestamp, tx_hash, nft_id, from_address, to_address, price) "
                     "FORMAT JSONEachRow",
        },
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        timeout=60,
    )
    if resp.status_code != 200:
        raise Exception(f"ClickHouse error ({resp.status_code}): {resp.text[:500]}")
    hashes = [row['tx_hash'] for row in data]
    pg_hook = PostgresHook(postgres_conn_id='postgres_farcana')
    pg_hook.run(
        "UPDATE nft_transactions SET synced_to_ch = TRUE WHERE tx_hash = ANY(%s)",
        parameters=(hashes,),
    )
    print(f"Loaded {len(data)} nft_transactions to ClickHouse")
    return len(data)


with DAG(
    dag_id='chimeras_etl',
    default_args={
        'owner': 'devops',
        'depends_on_past': False,
        'start_date': datetime(2026, 9, 1),
        'retries': 2,
        'retry_delay': timedelta(minutes=1),
    },
    schedule='*/1 * * * *',
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=['chimeras', 'etl', 'oltp-olap'],
) as dag:
    extract = PythonOperator(task_id='extract_from_postgres', python_callable=extract_from_postgres)
    load = PythonOperator(task_id='load_to_clickhouse', python_callable=load_to_clickhouse)
    extract >> load

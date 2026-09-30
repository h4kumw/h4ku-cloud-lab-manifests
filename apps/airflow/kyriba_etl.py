"""Kyriba ETL: bank_statements (raw) → financial_reports (aggregated)."""
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime, timedelta
import json
import requests
from collections import defaultdict


CLICKHOUSE_URL = "http://clickhouse.infra.svc.cluster.local:8123/"
CLICKHOUSE_PARAMS = {"user": "admin", "password": "admin"}
BATCH_SIZE = 5000


def extract_from_postgres(**context):
    """Читаем сырые транзакции из PG."""
    pg_hook = PostgresHook(postgres_conn_id='postgres_farcana')
    sql = """
        SELECT id, statement_date, bank_code, total_amount, processed_at
        FROM bank_statements
        WHERE synced_to_ch = FALSE
        ORDER BY id ASC
        LIMIT %s
    """
    records = pg_hook.get_records(sql, parameters=(BATCH_SIZE,))
    if not records:
        print("No new records")
        return []
    data = [dict(zip(
        ['id', 'statement_date', 'bank_code', 'total_amount', 'processed_at'],
        r
    )) for r in records]
    print(f"Extracted {len(data)} bank_statements from PostgreSQL")
    return data


def load_to_clickhouse(**context):
    """Агрегируем и вставляем в CH."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='extract_from_postgres')
    if not data:
        print("No data to load")
        return 0

    # Агрегация в Python: (report_date, bank_code) → {count, sum}
    agg = defaultdict(lambda: {"count": 0, "sum": 0.0})
    for row in data:
        report_date = row['statement_date']
        if hasattr(report_date, 'isoformat'):
            report_date = report_date.isoformat()
        key = (report_date, row['bank_code'])
        agg[key]["count"] += 1
        agg[key]["sum"] += float(row['total_amount']) if row['total_amount'] is not None else 0.0

    print(f"Aggregated {len(data)} raw rows → {len(agg)} (date, bank) groups")

    # Формируем JSONEachRow для вставки
    lines = []
    for (report_date, bank_code), v in agg.items():
        lines.append(json.dumps({
            "report_date":        report_date,
            "bank_code":          bank_code,
            "total_transactions": v["count"],
            "total_volume":       v["sum"],
            "avg_transaction":    v["sum"] / v["count"] if v["count"] else 0.0,
        }, ensure_ascii=False))

    body = "\n".join(lines)

    # ReplacingMergeTree: дубликаты схлопнутся
    resp = requests.post(
        CLICKHOUSE_URL,
        params={
            **CLICKHOUSE_PARAMS,
            "query": "INSERT INTO game_analytics.financial_reports "
                     "(report_date, bank_code, total_transactions, total_volume, avg_transaction) "
                     "FORMAT JSONEachRow",
        },
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        timeout=60,
    )
    if resp.status_code != 200:
        raise Exception(f"ClickHouse error ({resp.status_code}): {resp.text[:500]}")

    # Помечаем raw как synced
    ids = [row['id'] for row in data]
    pg_hook = PostgresHook(postgres_conn_id='postgres_farcana')
    pg_hook.run(
        "UPDATE bank_statements SET synced_to_ch = TRUE WHERE id = ANY(%s)",
        parameters=(ids,),
    )

    print(f"Loaded {len(agg)} aggregated rows to ClickHouse (from {len(data)} raw)")
    return len(data)


with DAG(
    dag_id='kyriba_etl',
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
    tags=['kyriba', 'etl', 'oltp-olap'],
) as dag:
    extract = PythonOperator(task_id='extract_from_postgres', python_callable=extract_from_postgres)
    load = PythonOperator(task_id='load_to_clickhouse', python_callable=load_to_clickhouse)
    extract >> load

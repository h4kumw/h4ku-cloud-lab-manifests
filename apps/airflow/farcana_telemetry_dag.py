from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.http.hooks.http import HttpHook
from datetime import datetime, timedelta
import json

default_args = {
    'owner': 'devops',
    'depends_on_past': False,
    'start_date': datetime(2026, 9, 1),
    'retries': 2,
    'retry_delay': timedelta(minutes=5)
}

def extract_match_data(**context):
    pg_hook = PostgresHook(postgres_conn_id='postgres_farcana')
    sql = """
        SELECT m.match_id, m.created_at, m.region,
               p.player_id, p.skill_level
        FROM matches m
        JOIN match_players mp ON m.match_id = mp.match_id
        JOIN players p ON p.player_id = mp.player_id
        WHERE m.created_at > NOW() - INTERVAL '1 hour'
          AND m.status = 'completed'
    """
    records = pg_hook.get_records(sql)
    return json.dumps(records)

def transform_and_load_to_clickhouse(**context):
    import requests
    ti = context['ti']
    records_json = ti.xcom_pull(task_ids='extract_match_data')
    records = json.loads(records_json)
    
    if not records:
        return "No new data"
    
    values = []
    for r in records:
        values.append(f"('{r[0]}', '{r[1]}', '{r[2]}', {r[3]})")
    
    insert_sql = f"""
        INSERT INTO game_analytics.match_summary
        VALUES {','.join(values)}
    """
    
    url = "http://clickhouse:8123/"
    params = {"query": insert_sql}
    response = requests.post(url, params=params)
    
    if response.status_code != 200:
        raise Exception(f"ClickHouse error: {response.text}")
    
    return f"Loaded {len(values)} records"

with DAG(
    'farcana_telemetry_etl',
    default_args=default_args,
    schedule_interval='*/15 * * * *',
    catchup=False,
    tags=['farcana', 'gamedev']
) as dag:
    
    extract = PythonOperator(
        task_id='extract_match_data',
        python_callable=extract_match_data
    )
    
    transform_load = PythonOperator(
        task_id='transform_and_load_to_clickhouse',
        python_callable=transform_and_load_to_clickhouse
    )
    
    extract >> transform_load

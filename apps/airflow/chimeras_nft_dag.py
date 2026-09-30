from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.http.hooks.http import HttpHook
from datetime import datetime, timedelta
import requests
import json

default_args = {
    'owner': 'devops',
    'depends_on_past': False,
    'start_date': datetime(2026, 9, 1),
    'retries': 2,
    'retry_delay': timedelta(minutes=5)
}

def aggregate_nft_stats():
    """Агрегация NFT-транзакций за последний час"""
    ch_hook = HttpHook(http_conn_id='clickhouse_analytics', method='POST')
    
    query = """
        SELECT 
            toStartOfHour(timestamp) as hour,
            count(*) as tx_count,
            sum(price) as total_volume,
            avg(price) as avg_price
        FROM game_analytics.nft_transactions
        WHERE timestamp > now() - INTERVAL 1 HOUR
        GROUP BY hour
    """
    
    url = "http://clickhouse:8123/"
    params = {"query": query, "format": "JSON"}
    response = requests.post(url, params=params)
    
    if response.status_code != 200:
        raise Exception(f"ClickHouse error: {response.text}")
    
    data = response.json()
    print(f"[CHIMERAS] Aggregated {data['rows']} rows")
    return data

with DAG(
    'chimeras_nft_aggregator',
    default_args=default_args,
    schedule_interval='*/5 * * * *',
    catchup=False,
    tags=['chimeras', 'web3']
) as dag:
    
    aggregate = PythonOperator(
        task_id='aggregate_nft_stats',
        python_callable=aggregate_nft_stats
    )

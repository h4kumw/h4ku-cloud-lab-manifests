FROM apache/airflow:3.2.2-python3.12

USER airflow

# Официальный ClickHouse provider (не community-плагин!)
RUN pip install --no-cache-dir \
    "apache-airflow-providers-clickhousedb"

RUN pip install --no-cache-dir \
    "clickhouse-connect" \
    "xgboost" \
    "mlflow" \
    "scikit-learn" \
    "pandas" \
    "pyarrow"

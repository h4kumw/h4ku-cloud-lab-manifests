FROM apache/airflow:3.2.2-python3.12

USER airflow

RUN pip install --no-cache-dir \
    "apache-airflow-providers-clickhouse" \
    "clickhouse-connect" \
    "xgboost==2.0.3" \
    "mlflow==2.16.2" \
    "scikit-learn" \
    "pandas" \
    "pyarrow"

"""
D2 MLOps: XGBoost training DAG
Читает sensor_data из ClickHouse → anomaly detection (value вне 5-95 перцентиля)
Логирует params/metrics/model в MLflow
"""
from datetime import datetime, timedelta
import os
import pandas as pd
import numpy as np
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.clickhousedb.hooks.clickhouse import ClickHouseHook
import mlflow
import mlflow.xgboost
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

MLFLOW_TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI",
    "http://mlflow.mlflow.svc.cluster.local:5000",
)
EXPERIMENT_NAME = "cloud-lab-sensor-anomaly"

default_args = {
    "owner": "cloud-lab",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


def extract_data(**ctx):
    """Читаем sensor_data + feature engineering"""
    hook = ClickHouseHook(clickhouse_conn_id="clickhouse_default")

    # Считаем перцентили по каждому sensor_type
    query = """
        WITH stats AS (
            SELECT
                sensor_type,
                quantile(0.05)(value) AS p05,
                quantile(0.95)(value) AS p95
            FROM game_analytics.sensor_data
            WHERE timestamp > now() - INTERVAL 7 DAY
            GROUP BY sensor_type
        )
        SELECT
            toUnixTimestamp(s.timestamp)     AS ts,
            s.device_id,
            s.sensor_type,
            s.value,
            s.unit,
            s.location,
            st.p05,
            st.p95,
            if(s.value < st.p05 OR s.value > st.p95, 1, 0) AS is_anomaly,
            cityHash64(s.device_id) % 1000   AS device_hash,
            cityHash64(s.sensor_type) % 100  AS sensor_hash
        FROM game_analytics.sensor_data s
        INNER JOIN stats st ON s.sensor_type = st.sensor_type
        WHERE s.timestamp > now() - INTERVAL 7 DAY
        LIMIT 100000
    """
    rows = hook.get_records(query)
    cols = [
        "ts", "device_id", "sensor_type", "value", "unit", "location",
        "p05", "p95", "is_anomaly", "device_hash", "sensor_hash",
    ]
    df = pd.DataFrame(rows, columns=cols)

    if len(df) == 0:
        raise ValueError("Нет данных в sensor_data за 7 дней")

    df.to_parquet("/tmp/ml_train.parquet", index=False)
    print(f"✅ Extracted {len(df)} rows")
    print(f"   anomaly rate: {df['is_anomaly'].mean():.2%}")
    print(f"   value stats: min={df['value'].min()}, avg={df['value'].mean():.2f}, max={df['value'].max()}")
    print(f"   sensor_types: {df['sensor_type'].nunique()}")
    return len(df)


def train_model(**ctx):
    """XGBoost training + MLflow logging"""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    df = pd.read_parquet("/tmp/ml_train.parquet")

    # Encode categorical
    df["sensor_type_enc"] = df["sensor_type"].astype("category").cat.codes
    df["unit_enc"] = df["unit"].astype("category").cat.codes
    df["location_enc"] = df["location"].astype("category").cat.codes

    feature_cols = [
        "value", "p05", "p95",
        "device_hash", "sensor_hash",
        "sensor_type_enc", "unit_enc", "location_enc",
    ]

    X = df[feature_cols].fillna(0)
    y = df["is_anomaly"]

    # Защита: если класс один — добавим шум
    if y.nunique() < 2:
        raise ValueError(f"Только один класс в таргете: {y.unique()}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 5,
        "learning_rate": 0.1,
        "n_estimators": 150,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
        "tree_method": "hist",
    }

    with mlflow.start_run(run_name=f"xgboost_anomaly_{datetime.now():%Y%m%d_%H%M%S}") as run:
        mlflow.log_params(params)
        mlflow.log_param("n_train", len(X_train))
        mlflow.log_param("n_test", len(X_test))
        mlflow.log_param("features", ",".join(feature_cols))
        mlflow.log_param("target", "is_anomaly (value outside p05-p95)")
        mlflow.log_param("data_source", "game_analytics.sensor_data")

        model = xgb.XGBClassifier(**params)
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

        y_pred = model.predict(X_test)
        y_proba = model.predict_proba(X_test)[:, 1]

        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "f1": float(f1_score(y_test, y_pred)),
            "roc_auc": float(roc_auc_score(y_test, y_proba)),
        }
        mlflow.log_metrics(metrics)
        mlflow.xgboost.log_model(
            model, "model",
            registered_model_name="sensor_anomaly_predictor",
        )

        imp = pd.DataFrame({
            "feature": feature_cols,
            "importance": model.feature_importances_,
        }).sort_values("importance", ascending=False)
        imp.to_csv("/tmp/feature_importance.csv", index=False)
        mlflow.log_artifact("/tmp/feature_importance.csv")

        print(f"✅ Run ID: {run.info.run_id}")
        print(f"✅ Metrics: {metrics}")
        print(f"✅ Feature importance:\n{imp}")
        return run.info.run_id


def validate_model(**ctx):
    """Проверяем что модель загружается обратно"""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = mlflow.tracking.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT_NAME)
    runs = client.search_runs(
        exp.experiment_id, order_by=["start_time DESC"], max_results=1
    )
    if not runs:
        raise ValueError("No runs found!")
    latest = runs[0]
    print(f"✅ Latest run: {latest.info.run_id}")
    print(f"   AUC: {latest.data.metrics.get('roc_auc')}")
    print(f"   F1:  {latest.data.metrics.get('f1')}")
    return latest.info.run_id


with DAG(
    dag_id="ml_training_xgboost",
    description="D2: XGBoost training (sensor anomaly) → MLflow",
    default_args=default_args,
    start_date=datetime(2026, 10, 15),
    schedule="0 */6 * * *",
    catchup=False,
    tags=["ml", "d2", "xgboost", "mlflow"],
) as dag:

    t1 = PythonOperator(task_id="extract_data", python_callable=extract_data)
    t2 = PythonOperator(task_id="train_model", python_callable=train_model)
    t3 = PythonOperator(task_id="validate_model", python_callable=validate_model)

    t1 >> t2 >> t3

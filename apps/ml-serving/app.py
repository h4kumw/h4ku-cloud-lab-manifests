"""
D2 MLOps: FastAPI serving для sensor_anomaly_predictor
Загружает модель из MLflow Model Registry, отдаёт /predict
"""
import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

import mlflow
import mlflow.xgboost
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MLFLOW_TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI", "http://mlflow.mlflow.svc.cluster.local:5000"
)
MODEL_NAME = os.getenv("MODEL_NAME", "sensor_anomaly_predictor")
MODEL_STAGE = os.getenv("MODEL_STAGE", "latest")  # None = latest version
MODEL_VERSION = os.getenv("MODEL_VERSION", None)

model = None
model_info = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Загружаем модель при старте"""
    global model, model_info
    logger.info(f"Connecting to MLflow: {MLFLOW_TRACKING_URI}")
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = mlflow.tracking.MlflowClient()

    if MODEL_VERSION:
        model_uri = f"models:/{MODEL_NAME}/{MODEL_VERSION}"
        logger.info(f"Loading model: {model_uri}")
        model = mlflow.pyfunc.load_model(model_uri)
        model_info = {"name": MODEL_NAME, "version": MODEL_VERSION}
    else:
        model_uri = f"models:/{MODEL_NAME}/{MODEL_STAGE}"
        logger.info(f"Loading model: {model_uri}")
        model = mlflow.xgboost.load_model(model_uri)
        mv = client.get_model_version_by_alias(MODEL_NAME, MODEL_STAGE)
        model_info = {
            "name": MODEL_NAME,
            "version": mv.version,
            "run_id": mv.run_id,
        }

    logger.info(f"✅ Model loaded: {model_info}")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Cloud-Lab ML Serving",
    description="XGBoost anomaly detection for CPS sensors",
    version="1.0.0",
    lifespan=lifespan,
)


class PredictRequest(BaseModel):
    value: float = Field(..., example=45.5)
    p05: float = Field(..., example=20.0)
    p95: float = Field(..., example=90.0)
    device_hash: float = Field(..., example=123.0)
    sensor_hash: float = Field(..., example=42.0)
    sensor_type_enc: float = Field(..., example=0.0)
    unit_enc: float = Field(..., example=0.0)
    location_enc: float = Field(..., example=0.0)


class PredictResponse(BaseModel):
    is_anomaly: int
    anomaly_probability: float
    model: dict
    threshold: float


@app.get("/health")
async def health():
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ok", "model": model_info}


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # XGBoost модель ожидает тот же порядок фичей, что был при обучении
    X = pd.DataFrame([{
        "value": req.value,
        "p05": req.p05,
        "p95": req.p95,
        "device_hash": req.device_hash,
        "sensor_hash": req.sensor_hash,
        "sensor_type_enc": req.sensor_type_enc,
        "unit_enc": req.unit_enc,
        "location_enc": req.location_enc,
    }])

    try:
        # XGBoost predict_proba
        if hasattr(model, "predict_proba"):
            proba = float(model.predict_proba(X)[0, 1])
        else:
            proba = float(model.predict(X)[0])
        is_anomaly = int(proba > 0.5)
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(e)}")

    return PredictResponse(
        is_anomaly=is_anomaly,
        anomaly_probability=proba,
        model=model_info,
        threshold=0.5,
    )


@app.get("/metrics")
async def metrics():
    """Prometheus-совместимый endpoint (простой)"""
    return {
        "model_loaded": 1 if model is not None else 0,
        "model_version": model_info.get("version", "unknown"),
    }

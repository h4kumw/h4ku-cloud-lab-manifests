# Cloud-Lab Manifests

GitOps-репозиторий для Cloud-Lab (K3d + Airflow + MLflow + ArgoCD).

## Структура

├── apps/ # Приложения (Application CRDs)
│ ├── infra/ # PG, CH, Kafka, MinIO, InfluxDB, Mosquitto
│ ├── data-platform/ # Симуляторы + Visualizer
│ ├── airflow/ # Airflow
│ └── traefik/ # IngressRoutes
├── infrastructure/ # Helm values, общие ресурсы
└── clusters/
└── cps-lab/ # Root Application (App of Apps)

text

## Sync

ArgoCD следит за репо и синкает всё автоматически.

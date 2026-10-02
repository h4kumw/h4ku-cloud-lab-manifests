# CONTEXT: Cloud-Lab — D1 CLOSED ✅

**Дата:** 2026-09-29 (04:00)
**Фаза:** D1 — Data Pipeline — **100% ГОТОВ**

---

## ✅ D1 — ЗАКРЫТ
- K3d (4 ноды, 24 GB RAM после WSL fix)
- Infra (6): postgres, clickhouse, kafka, minio, influxdb, mosquitto
- Airflow 3.2.2 (8 подов, migrations `1d6611b6ab7c`)
- DAG'и: farcana_etl, chimeras_etl, kyriba_etl — success */5min
- Симуляторы (5): chimeras, farcana, kyriba, cps, visualizer
- Stream: CPS → Kafka → CH
- Batch: PG → CH
- Monitoring: Grafana, Prometheus, Alertmanager, Telegram
- Скрипты: start-all, stop-all, status, backup, restore, test-scripts
- Золотой backup: `cloud-lab-backup-2026-09-29-0330.tar.gz`
- STOP→START: ~3 мин

---

## 🗺️ ЕДИНЫЙ ПЛАН (согласован 2026-09-29)

**Порядок:** `D1 ✅ → I1 → E → D2 → A1 → T1 → I → F → J → K → H`

| # | Фаза | Что | Время | Статус |
|---|---|---|---|---|
| D1 | Data Pipeline | Airflow + Kafka + CH | — | ✅ DONE |
| I1 | Traefik | Ingress вместо Nginx | 1 ч | ⏳ NEXT |
| E | GitOps + CI/CD | ArgoCD + GitHub Actions | 3 ч | ⏳ |
| D2 | MLOps | MLflow + XGBoost + FastAPI | 4 ч | ⏳ |
| A1 | Ansible | Конфигурация | 2 ч | ⏳ |
| T1 | Terraform | IaC | 2 ч | ⏳ |
| I | Istio + Kiali | Service Mesh | 2-3 ч | ⏳ |
| F | Production-grade | Hardening | 1 день | ⏳ |
| J | Documentation | README + docs/ | 3-4 ч | ⏳ |
| K | Chaos Engineering | Имитация инцидентов | 4-5 ч | ⏳ |
| H | Финал | — | — | ⏳ |

---

## 🎯 СЛЕДУЮЩИЙ ШАГ: I1 (Traefik)

**Почему первым:**
- Nginx Ingress **deprecated** в K3s 1.28+
- Traefik — **CRD-based routing** (IngressRoute) — современнее
- ArgoCD, MLflow, Grafana, RAG UI — всё через Ingress

**Что делаем:**
1. Установить Traefik в K3d (Helm)
2. Заменить NodePort на Ingress для всех сервисов
3. Self-signed TLS через mkcert
4. Доступ через `https://*.cloud-lab.local`

---

## 🎯 ПОСЛЕ: E (GitOps + CI/CD)

**Best practice 2026:** GitHub Actions + ArgoCD 
**Почему GitHub сейчас:** 0 RAM, 2000 CI минут, 20k actions
**Почему GitLab потом:** enterprise-стандарт, self-hosted на VPS (портфолио)

**E.1** — Git-репо `cloud-lab-manifests` (GitHub)
**E.2** — ArgoCD в K3d (Helm, ~500 MB)
**E.3** — Application CRDs (App of Apps pattern)
**E.4** — GitHub Actions для CI (build, test, push image)
**E.5** — Демо: git push → ArgoCD sync → изменение в кластере

---

## 🔑 КРЕДЫ

| Сервис | URL | Логин |
|---|---|---|
| Airflow | localhost:8080 | admin/admin |
| Grafana | localhost:3100 | admin/admin |
| RAG UI | localhost:5001 | — |
| Visualizer | localhost:30050 | — |
| Prometheus | localhost:9090 | — |
| Alertmanager | localhost:9093 | — |

---

## ⚠️ ИЗВЕСТНЫЕ ГРАБЛИ (Airflow 3.x)

1-10. (Airflow 3.x грабли — см. предыдущий CONTEXT)
11. **Airflow API-server медленно поднимается** — `break` при pod Running

## ⚠️ ГРАБЛИ СКРИПТОВ
12-17. (см. предыдущий CONTEXT — скрипты, спиннеры)

---

## 💡 WSL2 ОПТИМИЗАЦИЯ (сделано)

`C:\Users\h4ku\.wslconfig`:
```ini
[wsl2]
memory=24GB
swap=4GB
✅ E.3 (2026-09-30 03:00)
ArgoCD v3.5.3 в ns argocd (5 подов, optimized под K3s)

Repo: https://github.com/h4kumw/h4ku-cloud-lab-manifests (private)

PAT через K8s Secret с label argocd.argoproj.io/secret-type=repository

IngressRoute: argocd.cloud-lab.local (Traefik)

Первый Application: traefik-ingressroutes → Synced + Healthy

5 IngressRoute под управлением ArgoCD

Auto-sync + self-heal + prune
✅ E.4 (2026-09-30 03:15)
App of Apps pattern работает

Root App → 4 дочерних (infra, data-platform, airflow, traefik)

Git repo: apps/infra, apps/data-platform, apps/airflow, apps/traefik

Infrastructure values: traefik, argocd, airflow

Все App'ы: Healthy + Synced

GitOps полностью работает: git push → auto-sync

## ✅ E.4 — App of Apps ЗАКРЫТ (2026-09-30 03:15)

**5 Applications в ArgoCD (все Synced + Healthy):**
- `root` → управляет `clusters/cps-lab/applications/`
- `infra` → `apps/infra/` (PG, CH, Kafka, MinIO, InfluxDB, Mosquitto)
- `data-platform` → `apps/data-platform/` (симуляторы)
- `airflow` → `apps/airflow/` (DAGs + values)
- `traefik-ingressroutes` → `apps/traefik/`

**GitOps работает:**
- git push → auto-sync через ~3 мин
- self-heal: удалил вручную → восстановится
- prune: убрал из git → удалится из кластера

**Архитектура:**
- Repo: https://github.com/h4kumw/h4ku-cloud-lab-manifests (private)
- Secret с label `argocd.argoproj.io/secret-type=repository`
- IngressRoute: argocd.cloud-lab.local

## ✅ E.4 — App of Apps ЗАКРЫТ (2026-09-30 03:15)

**5 Applications в ArgoCD (все Synced + Healthy):**
- root → clusters/cps-lab/applications/
- infra → apps/infra/
- data-platform → apps/data-platform/
- airflow → apps/airflow/
- traefik-ingressroutes → apps/traefik/

**GitOps работает:** git push → auto-sync, self-heal, prune.
**Repo:** https://github.com/h4kumw/h4ku-cloud-lab-manifests (private)
**IngressRoute:** argocd.cloud-lab.local
✅ E.5 — GitHub Actions CI ЗАКРЫТ (2026-09-30)
Workflow: .github/workflows/build-simulators.yml

Matrix build: 4 симулятора за 41s

Image: ghcr.io/h4kumw/cloud-lab-simulators:<sim>-latest

PAT обновлён: workflow: Read and write

Total: ~10 минут CI/день (free tier 2000 мин/мес)

## ✅ E.6 — ETL РАБОТАЕТ (2026-10-01 02:00)

**DAGs — все success:**
- farcana_etl → match_telemetry в CH = 4227
- chimeras_etl → nft_transactions в CH = 1252
- kyriba_etl → financial_reports в CH = 96
- sensor_data (stream) = 8405

**Fixes:**
- `synced_to_ch` добавлен в `nft_transactions`, `bank_statements`
- DAG-PVC в `apps/airflow/values.yaml` (helm upgrade)
- DAG'и залиты в PVC через pod-хелпер

**TODO (E.7):**
- Init-Job PG (CREATE TABLE IF NOT EXISTS)
- Init-Job CH (game_analytics + Kafka Engine MV)
- DAGs в ConfigMap + initContainer
- ArgoCD Image Updater

**Все 5 ArgoCD Apps — Synced+Healthy. Все 4 симулятора Running.**

## ✅ E.7 — Init-Jobs ЗАКРЫТ (2026-10-01 14:50)

**Init-Jobs (idempotent restore после reboot):**
- `pg-init-schema` — Complete (CREATE TABLE IF NOT EXISTS × 7)
- `ch-init-schema` — Complete (curl HTTP 8123, CREATE TABLE × 6 + MV)

**Проблемы при разработке:**
- Heredoc в YAML literal block — syntax error
- `clickhouse-client --protocol` — нет такой опции
- Solution: `curl` HTTP API на 8123

**ArgoCD `directory.recurse: true`** — для подпапок `apps/infra/init/`

**Fix:** `.py` DAGs → `dags-src/` (вне ArgoCD source), ConfigMap в `apps/airflow/`

**CH tables (7):** match_telemetry, nft_transactions, financial_reports,
                    sensor_data, sensor_aggregates, sensor_data_mv, sensor_data_queue
**CH counts:** match_telemetry 6679, nft_transactions 1833,
               sensor_data 13290, financial_reports 139

## 🎯 ДАЛЬШЕ
- A: DEMO для портфолио
- B: D2 MLOps (MLflow + XGBoost + FastAPI)

## ✅ E.7 — Init-Jobs ЗАКРЫТ (2026-10-01 14:50)

**Init-Jobs (idempotent restore после reboot):**
- `pg-init-schema` — Complete (CREATE TABLE IF NOT EXISTS × 7)
- `ch-init-schema` — Complete (curl HTTP 8123, CREATE TABLE × 6 + MV)

**Проблемы при разработке:**
- Heredoc в YAML literal block — syntax error
- `clickhouse-client --protocol` — нет такой опции
- Solution: `curl` HTTP API на 8123

**ArgoCD `directory.recurse: true`** — для подпапок `apps/infra/init/`

**Fix:** `.py` DAGs → `dags-src/` (вне ArgoCD source), ConfigMap в `apps/airflow/`

**CH tables (7):** match_telemetry, nft_transactions, financial_reports,
                    sensor_data, sensor_aggregates, sensor_data_mv, sensor_data_queue
**CH counts:** match_telemetry 6679, nft_transactions 1833,
               sensor_data 13290, financial_reports 139

## 🎯 ДАЛЬШЕ
- A: DEMO для портфолио
- B: D2 MLOps (MLflow + XGBoost + FastAPI)

## ✅ E.7 — Init-Jobs ЗАКРЫТ (2026-10-01 15:50)

**Init-Jobs (idempotent restore):**
- `pg-init-schema` — Complete (CREATE TABLE IF NOT EXISTS × 7)
- `ch-init-schema` — Complete (curl HTTP 8123)

**Грабли:**
- Heredoc в YAML literal block → syntax error
- `clickhouse-client --protocol` — не существует
- **Fix:** `curl` HTTP API на 8123

**ArgoCD `directory.recurse: true`** — для подпапок `apps/infra/init/`

**Fix DAG-и:** `.py` → `dags-src/` (вне ArgoCD source), ConfigMap в `apps/airflow/`

**CH таблицы (7):** match_telemetry, nft_transactions, financial_reports,
                    sensor_data, sensor_aggregates, sensor_data_mv, sensor_data_queue
**CH counts:** match_telemetry 6679, nft_transactions 1833,
               sensor_data 13290, financial_reports 139

**Все 5 ArgoCD apps — Synced + Healthy, 0 conditions.**

## 🎯 СЛЕДУЮЩИЙ ШАГ
**A: DEMO для портфолио**

## ✅ A: DEMO для портфолио (2026-10-01 18:00)

**Demo #1: GitOps auto-sync** — replicas 1→2 (git push → ArgoCD)
**Demo #2: Self-Heal** — delete pod → auto-recreate
**Demo #3: CI/CD** — GitHub Actions workflow Success (4 jobs, 42s)
**Demo #4: ArgoCD UI Tour** — 5 apps Synced+Healthy, ApplicationTree, History

**Скриншоты:** Actions, Packages, ArgoCD UI, k9s, CH counts.
**Видео:** Loom 3 min.

## ✅ Visualizer финал (2026-10-02 15:48)

**Global Sensors:**
- DEVICE_COORDS: 25 городов (US, EU, Asia, AU, S.America, Africa)
- LIMIT 30 — все sensors в UI
- Fallback для unknown device — random global
- cps_simulator devices: 27

**Унифицированные цвета:**
- Players: #00d2ff (cyan) — текст + точки
- Servers: #ff4444 (red) — текст + точки
- Sensors: #ffd93d (yellow) — текст + точки
- NFT: #ff6b6b (red-orange) — текст

**Visualizer:**
- Players: 50, Sensors: 25+, Servers: 5, NFT: 1007
- Карта: 30+ точек глобально
- WebSocket: Connected

## ✅ K3d Overview + Federation РАБОТАЕТ (2026-10-02)

**kube-prometheus-stack в k8s:**
- ns: monitoring
- 7 pods: operator, prometheus, kube-state-metrics, 4× node-exporter
- 22 targets ✅

**Federation:**
- External Prometheus → kube-prom Prometheus (NodePort 30715)
- target: k3d-cps-lab-server-0:30715/federate
- metrics: kube_*, container_*, node_*
- networks: prometheus-external в k3d-cps-lab

**Grafana Overview (K3d):**
- Pods Running: 22
- Nodes Ready: 4/4
- CPU/Memory by namespace
- Network RX/TX

**Visualizer финальный:**
- 25 sensors глобально (US, EU, Asia, AU, S.America, Africa)
- Унифицированные цвета (Players cyan, Servers red, Sensors yellow)
- LIMIT 30

**TODO (D2):**
- MLflow + XGBoost + FastAPI

## ✅ D1 + Visualizer + Grafana + Federation — 100% (2026-10-02)

**Grafana Overview (K3d):**
- Pods Running: 43
- Nodes Ready: 4/4
- CPU/Memory/Network by namespace
- Pods by Namespace (7/7/9/8/5/8/...)
- Federation: k3d-federate → UP

**Visualizer:**
- 25 sensors глобально (US, EU, Asia, AU, S.America, Africa)
- Унифицированные цвета (Players cyan, Servers red, Sensors yellow)
- Players: 50, Sensors: 5, NFT: 923

**kube-prometheus-stack:**
- ns: monitoring, 7 pods, 22 targets
- Federation через NodePort 30715 + k3d-cps-lab network

**TODO:**
- RAG UI (game_log_embeddings table + embedding pipeline)
- D2 MLOps (MLflow + XGBoost + FastAPI)

## ✅ RAG UI РАБОТАЕТ (2026-10-02 16:50)

**RAG pipeline:**
- Ollama (nomic-embed-text) → embeddings (768 dim)
- pgvector 0.8.7 → cosine similarity search
- LLM (qwen/hermes) → answer synthesis

**pgvector:**
- Image: pgvector/pgvector:pg15
- Extension: vector 0.8.7
- Table: game_log_embeddings (470 rows)
- Sources: farcana (matches), chimeras (NFT), cps (sensors)

**RAG UI:**
- Query → Top-5 similar logs → LLM answer
- Endpoint: http://localhost:5001

**Грабли:**
- heredoc через `kubectl exec` без `-i` — не работает (stdin)
- postgres image: pgvector/pgvector:pg15 (не postgres:15-alpine)

**TODO (D2):**
- MLflow + XGBoost + FastAPI

## ✅ CHECKPOINT SYSTEM РАБОТАЕТ (2026-10-02 18:00)

**Checkpoint:**
- Tarball: 185 MB, 100 files
- K8s: 17 YAML, 343 resources, 15 namespaces
- DB: PG 25M + 13M, CH 5 tables
- Docker: simulator + visualizer
- Secrets + git bundle + DAGs

**Restore:**
- Скрипт `restore-from-checkpoint.sh`
- Safety check: отказ если current-context = k3d-cps-lab
- Dry-run проверен: ✅

**Проверено:**
- Tarball на Windows: ✅
- YAML validation: 17/17 ✅
- PG/CH dumps: валидны ✅
- Git bundle: клонируется ✅
- Dry-run apply: ✅

## 🎯 СЛЕДУЮЩИЙ ШАГ: D2 MLOps
- MLflow + XGBoost + FastAPI

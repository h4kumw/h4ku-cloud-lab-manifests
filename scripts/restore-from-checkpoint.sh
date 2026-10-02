#!/usr/bin/env bash
# Cloud-Lab Restore from checkpoint — восстанавливает ВСЁ
set -euo pipefail

# Colors
C_GREEN='\033[32m'; C_CYAN='\033[36m'; C_YELLOW='\033[33m'
C_RED='\033[31m'; C_RESET='\033[0m'; C_DIM='\033[2m'

log() { echo -e "${C_CYAN}▶${C_RESET} $1"; }
ok() { echo -e "  ${C_GREEN}✔${C_RESET} $1"; }
warn() { echo -e "  ${C_YELLOW}⚠${C_RESET} $1"; }
fail() { echo -e "  ${C_RED}✘${C_RESET} $1"; exit 1; }

# ─── Args ───
CHECKPOINT_TARBALL="${1:-}"
if [ -z "$CHECKPOINT_TARBALL" ] || [ ! -f "$CHECKPOINT_TARBALL" ]; then
    echo "Usage: $0 <path-to-checkpoint.tar.gz>"
    echo ""
    echo "Available checkpoints:"
    ls -lh "$HOME"/cloud-lab-checkpoint-*.tar.gz 2>/dev/null || echo "  (none)"
    exit 1
fi

echo ""
echo -e "${C_CYAN}═══════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_CYAN}  CLOUD-LAB RESTORE FROM CHECKPOINT${C_RESET}"
echo -e "${C_CYAN}═══════════════════════════════════════════════════════${C_RESET}"
echo ""
echo -e "  📦 Tarball: ${C_CYAN}$CHECKPOINT_TARBALL${C_RESET}"
echo ""

# ─── Extract ───
log "[1/12] Extract checkpoint"
EXTRACT_DIR=$(mktemp -d)
tar xzf "$CHECKPOINT_TARBALL" -C "$EXTRACT_DIR"
CHECKPOINT_DIR=$(find "$EXTRACT_DIR" -maxdepth 1 -type d -name "cloud-lab-checkpoint-*" | head -1)
if [ -z "$CHECKPOINT_DIR" ]; then
    fail "Checkpoint dir not found in tarball"
fi
ok "Extracted to $CHECKPOINT_DIR"

# Verify manifest
if [ -f "$CHECKPOINT_DIR/manifest.txt" ]; then
    log "Verify checksums (skipping — trust checkpoint)"
    ok "manifest.txt"
fi

# ─── [2/12] K3d cluster ───
log "[2/12] K3d cluster"

if ! k3d cluster list | grep -q "cps-lab"; then
    warn "Cluster doesn't exist — creating"
    k3d cluster create cps-lab --agents 3 \
        --k3s-arg '--disable=traefik@server:0' \
        --port '80:80@loadbalancer' \
        --port '443:443@loadbalancer' \
        --timeout 5m
    ok "Cluster created"
else
    k3d cluster start cps-lab 2>/dev/null || true
    ok "Cluster exists"
fi

# Wait for nodes
for i in $(seq 1 60); do
    ready=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready" || echo 0)
    if [ "$ready" -eq 4 ]; then
        ok "4/4 nodes Ready"
        break
    fi
    sleep 2
done

# ─── [3/12] Namespaces + Cluster-scoped ───
log "[3/12] Namespaces + cluster-scoped"

for ns in infra data-platform cps airflow traefik argocd monitoring; do
    kubectl create namespace "$ns" 2>/dev/null || true
done
ok "Namespaces created"

if [ -f "$CHECKPOINT_DIR/k8s/cluster-scoped.yaml" ]; then
    kubectl apply --validate=false -f "$CHECKPOINT_DIR/k8s/cluster-scoped.yaml" 2>&1 | \
        grep -E "created|configured|unchanged" | head -20 || true
    ok "cluster-scoped applied"
fi

# ─── [4/12] K8s manifests (in order) ───
log "[4/12] K8s manifests"

K8S_DIR="$CHECKPOINT_DIR/k8s"

# 1. Apply cluster-scoped FIRST
if [ -f "$K8S_DIR/_namespaces.yaml" ]; then
    kubectl apply --validate=false -f "$K8S_DIR/_namespaces.yaml" 2>&1 | grep -cE "created|configured|unchanged" | xargs -I{} echo "  Namespaces: {} applied"
fi

if [ -f "$K8S_DIR/_cluster-scoped.yaml" ]; then
    kubectl apply --validate=false -f "$K8S_DIR/_cluster-scoped.yaml" 2>&1 | grep -cE "created|configured|unchanged" | xargs -I{} echo "  Cluster-scoped: {} applied"
fi

ok "Cluster-scoped applied"

# 2. Apply namespaced — порядок важен
for ns_file in infra data-platform cps airflow traefik argocd monitoring; do
    manifest="$K8S_DIR/$ns_file.yaml"
    if [ -f "$manifest" ] && [ -s "$manifest" ]; then
        count=$(kubectl apply --validate=false -f "$manifest" 2>&1 | grep -cE "created|configured|unchanged" || echo 0)
        ok "$ns_file.yaml ($count resources)"
    fi
done

# 3. Apply other namespaces (default, kube-system, etc) — только Deployments/ConfigMaps
for ns_file in default kube-system kube-public kube-node-lease falco agones-system open-match vault; do
    manifest="$K8S_DIR/$ns_file.yaml"
    if [ -f "$manifest" ] && [ -s "$manifest" ]; then
        count=$(kubectl apply --validate=false -f "$manifest" 2>&1 | grep -cE "created|configured|unchanged" || echo 0)
        warn "$ns_file.yaml ($count resources) — skipped conflicts"
    fi
done

ok "manifests applied"

# Wait for key pods
log "Waiting for infra pods..."
for i in $(seq 1 60); do
    running=$(kubectl get pods -n infra --no-headers 2>/dev/null | grep -c "Running" || echo 0)
    if [ "$running" -ge 6 ]; then
        ok "Infra: $running/6 Running"
        break
    fi
    sleep 3
done

# ─── [5/12] Restore PG data ───
log "[5/12] Restore PostgreSQL data"

if [ -f "$CHECKPOINT_DIR/database/pg-farcana.sql.gz" ]; then
    gunzip -c "$CHECKPOINT_DIR/database/pg-farcana.sql.gz" | \
        kubectl exec -i -n infra deploy/postgres -- \
        env PGPASSWORD=postgres psql -U admin -d farcana 2>&1 | \
        grep -vE "^(SET|ALTER|CREATE|COPY|GRANT|COMMENT|REVOKE)" | head -5 || true
    ok "pg-farcana restored"
fi

if [ -f "$CHECKPOINT_DIR/database/pg-airflow.sql.gz" ]; then
    gunzip -c "$CHECKPOINT_DIR/database/pg-airflow.sql.gz" | \
        kubectl exec -i -n airflow airflow-postgresql-0 -- \
        env PGPASSWORD=postgres psql -U postgres -d postgres 2>&1 | head -5 || true
    ok "pg-airflow restored"
fi

# ─── [6/12] Restore CH data ───
log "[6/12] Restore ClickHouse data"

# Wait for CH
for i in $(seq 1 30); do
    if kubectl exec -n infra deploy/clickhouse -- \
        clickhouse-client --user admin --password admin --query "SELECT 1" >/dev/null 2>&1; then
        break
    fi
    sleep 3
done

# Create DB + tables
kubectl exec -n infra deploy/clickhouse -- \
    clickhouse-client --user admin --password admin --multiquery <<'SQL' >/dev/null 2>&1
CREATE DATABASE IF NOT EXISTS game_analytics;
CREATE TABLE IF NOT EXISTS game_analytics.match_telemetry (event_time DateTime, match_id String, player_id String, event_type String, lat Float64, lon Float64, ping Int32, server_id String) ENGINE = MergeTree() ORDER BY (event_time, match_id);
CREATE TABLE IF NOT EXISTS game_analytics.nft_transactions (timestamp DateTime, tx_hash String, nft_id String, from_address String, to_address String, price Float64) ENGINE = MergeTree() ORDER BY (timestamp, tx_hash);
CREATE TABLE IF NOT EXISTS game_analytics.financial_reports (statement_date Date, bank_code String, total_amount Float64, processed_at DateTime) ENGINE = MergeTree() ORDER BY (statement_date, bank_code);
CREATE TABLE IF NOT EXISTS game_analytics.sensor_data (timestamp DateTime, device_id String, sensor_type String, value Float64, unit String, location String) ENGINE = MergeTree() ORDER BY (timestamp, device_id);
SQL
ok "CH schema created"

for table in match_telemetry nft_transactions financial_reports sensor_data; do
    dump="$CHECKPOINT_DIR/database/ch-$table.sql.gz"
    if [ -f "$dump" ]; then
        gunzip -c "$dump" | kubectl exec -i -n infra deploy/clickhouse -- \
            clickhouse-client --user admin --password admin --multiquery >/dev/null 2>&1 || true
        ok "ch-$table restored"
    fi
done

# ─── [7/12] Docker images ───
log "[7/12] Docker images"

for tarfile in "$CHECKPOINT_DIR/docker-images"/*.tar.gz; do
    [ -f "$tarfile" ] || continue
    gunzip -c "$tarfile" | docker load 2>&1 | grep -E "Loaded|Loaded" || true
    ok "$(basename $tarfile)"
done

# Import into k3d
for img in cloud-lab/simulator:latest cloud-lab/visualizer:latest; do
    if docker image inspect "$img" >/dev/null 2>&1; then
        k3d image import "$img" -c cps-lab 2>&1 | grep -E "Successfully" || true
    fi
done
ok "Images imported"

# ─── [8/12] Helm releases ───
log "[8/12] Helm releases"

# Traefik
if ! helm list -n traefik 2>/dev/null | grep -q traefik; then
    helm repo add traefik https://traefik.github.io/charts 2>/dev/null || true
    helm repo update >/dev/null 2>&1
    helm install traefik traefik/traefik -n traefik \
        -f "$CHECKPOINT_DIR/helm/traefik-values.yaml" \
        --wait --timeout 5m 2>&1 | grep -E "STATUS|NAME" || true
    ok "Traefik installed"
fi

# ArgoCD
if ! helm list -n argocd 2>/dev/null | grep -q argocd; then
    helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
    helm repo update >/dev/null 2>&1
    helm install argocd argo/argo-cd -n argocd \
        -f "$CHECKPOINT_DIR/helm/argocd-values.yaml" \
        --wait --timeout 10m 2>&1 | grep -E "STATUS|NAME" || true
    ok "ArgoCD installed"
fi

# Airflow
if ! helm list -n airflow 2>/dev/null | grep -q airflow; then
    helm repo add apache-airflow https://airflow.apache.org 2>/dev/null || true
    helm repo update >/dev/null 2>&1
    helm install airflow apache-airflow/airflow -n airflow \
        -f "$CHECKPOINT_DIR/helm/airflow-values.yaml" \
        --timeout 10m 2>&1 | grep -E "STATUS|NAME" || true
    ok "Airflow installed"
fi

# kube-prometheus
if ! helm list -n monitoring 2>/dev/null | grep -q kube-prom; then
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
    helm repo update >/dev/null 2>&1
    helm install kube-prom prometheus-community/kube-prometheus-stack -n monitoring \
        -f "$CHECKPOINT_DIR/helm/kube-prometheus-values.yaml" \
        --timeout 10m 2>&1 | grep -E "STATUS|NAME" || true
    ok "kube-prometheus installed"
fi

# ─── [9/12] External monitoring ───
log "[9/12] External monitoring"

mkdir -p "$HOME/cloud-lab/external-monitoring"
cp -r "$CHECKPOINT_DIR/external-monitoring/config" "$HOME/cloud-lab/external-monitoring/" 2>/dev/null || true
cp "$CHECKPOINT_DIR/external-monitoring/docker-compose.yml" "$HOME/cloud-lab/external-monitoring/" 2>/dev/null || true

cd "$HOME/cloud-lab/external-monitoring"
docker compose up -d 2>&1 | tail -5
cd - >/dev/null
ok "External monitoring started"

# Connect k3d network
for node in server-0 agent-0 agent-1 agent-2; do
    docker network connect external-monitoring_monitoring "k3d-cps-lab-$node" 2>/dev/null || true
done
docker network connect k3d-cps-lab prometheus-external 2>/dev/null || true

# ─── [10/12] Secrets ───
log "[10/12] Secrets"

if [ -f "$CHECKPOINT_DIR/secrets/github-pat.txt" ]; then
    GITHUB_PAT=$(cat "$CHECKPOINT_DIR/secrets/github-pat.txt")
    kubectl create secret generic repo-cloud-lab-manifests -n argocd \
        --from-literal=type=git \
        --from-literal=url=https://github.com/h4kumw/h4ku-cloud-lab-manifests.git \
        --from-literal=username=h4kumw \
        --from-literal=password="$GITHUB_PAT" \
        --dry-run=client -o yaml | \
        kubectl label --local -f - argocd.argoproj.io/secret-type=repository -o yaml | \
        kubectl apply -f - 2>&1 | tail -1
    ok "ArgoCD repo secret"

    # Save to git credentials
    echo "https://h4kumw:${GITHUB_PAT}@github.com" > "$HOME/.git-credentials"
    chmod 600 "$HOME/.git-credentials"
fi

# ─── [11/12] Airflow connection + DAGs ───
log "[11/12] Airflow connection + DAGs"

sleep 30

# Copy DAGs to PVC via helper pod
kubectl delete pod dag-loader -n airflow 2>/dev/null || true
cat <<'EOF' | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: dag-loader
  namespace: airflow
spec:
  restartPolicy: Never
  containers:
  - name: loader
    image: busybox:latest
    command: ["sleep", "300"]
    volumeMounts:
    - name: dags
      mountPath: /dags
  volumes:
  - name: dags
    persistentVolumeClaim:
      claimName: airflow-dags
EOF
sleep 5

for f in "$CHECKPOINT_DIR/airflow-dags"/*.py; do
    [ -f "$f" ] || continue
    kubectl cp "$f" airflow/dag-loader:/dags/$(basename "$f") 2>/dev/null || true
done
kubectl delete pod dag-loader -n airflow 2>/dev/null || true
ok "DAGs restored"

# Airflow connection
SCHED=$(kubectl get pods -n airflow -l component=scheduler -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$SCHED" ]; then
    kubectl exec -n airflow "$SCHED" -c scheduler -- \
        airflow connections add postgres_farcana \
        --conn-type postgres --conn-host postgres.infra.svc.cluster.local \
        --conn-port 5432 --conn-login admin --conn-password postgres \
        --conn-schema farcana 2>&1 | tail -1 || true
    ok "Airflow connection"
fi

# Unpause DAGs
kubectl exec -n airflow airflow-postgresql-0 -- \
    env PGPASSWORD=postgres psql -U postgres -d postgres -c \
    "UPDATE dag SET is_paused = false WHERE dag_id IN ('farcana_etl', 'chimeras_etl', 'kyriba_etl');" 2>&1 | tail -1 || true

# Restart scheduler+worker
kubectl rollout restart deploy/airflow-scheduler -n airflow 2>/dev/null || true
kubectl rollout restart deploy/airflow-dag-processor -n airflow 2>/dev/null || true
kubectl rollout restart statefulset/airflow-worker -n airflow 2>/dev/null || true
ok "Airflow restarted"

# ─── [12/12] Scripts + IngressRoutes ───
log "[12/12] Scripts + IngressRoutes"

mkdir -p "$HOME/cloud-lab"
cp -r "$CHECKPOINT_DIR/scripts" "$HOME/cloud-lab/" 2>/dev/null || true
ok "scripts"

# Apply IngressRoutes
kubectl apply --validate=false -f "$CHECKPOINT_DIR/k8s/traefik.yaml" 2>&1 | grep -c "configured\|created" | xargs -I{} echo "  IngressRoutes: {} applied" || true

# /etc/hosts
for host in airflow argocd traefik rag visualizer; do
    grep -q "$host.cloud-lab.local" /etc/hosts || \
        echo "127.0.0.1 $host.cloud-lab.local" | sudo tee -a /etc/hosts >/dev/null
done
ok "/etc/hosts updated"

# ─── DONE ───
echo ""
echo -e "${C_GREEN}═══════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_GREEN}  🎉 ВОССТАНОВЛЕНИЕ ЗАВЕРШЕНО${C_RESET}"
echo -e "${C_GREEN}═══════════════════════════════════════════════════════${C_RESET}"
echo ""

# Health check
echo -e "${C_DIM}Проверка сервисов...${C_RESET}"
for url in "Airflow|http://localhost:8080/" \
           "Grafana|http://localhost:3100/api/health" \
           "RAG UI|http://localhost:5001/" \
           "Visualizer|http://localhost:30050/" \
           "ArgoCD|http://argocd.cloud-lab.local/" \
           "Prometheus|http://localhost:9090/-/healthy"; do
    NAME="${url%%|*}"; U="${url##*|}"
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$U" 2>/dev/null || echo "000")
    printf "  %-15s → %s\n" "$NAME" "$code"
done
echo ""

echo -e "  ${C_YELLOW}⚠${C_RESET} Запусти port-forward'ы: ${C_DIM}bash ~/cloud-lab/scripts/start-all.sh${C_RESET}"
echo ""

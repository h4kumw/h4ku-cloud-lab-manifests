#!/usr/bin/env bash
# Cloud-Lab Checkpoint — сохраняет ВСЁ для восстановления
set -euo pipefail

CLOUD_LAB="$HOME/cloud-lab"
TIMESTAMP=$(date +%Y-%m-%d-%H%M)
CHECKPOINT_DIR="$HOME/cloud-lab-checkpoint-$TIMESTAMP"
TARBALL="$HOME/cloud-lab-checkpoint-$TIMESTAMP.tar.gz"

# Colors
C_GREEN='\033[32m'; C_CYAN='\033[36m'; C_YELLOW='\033[33m'
C_RED='\033[31m'; C_RESET='\033[0m'; C_DIM='\033[2m'

log() { echo -e "${C_CYAN}▶${C_RESET} $1"; }
ok() { echo -e "  ${C_GREEN}✔${C_RESET} $1"; }
warn() { echo -e "  ${C_YELLOW}⚠${C_RESET} $1"; }
fail() { echo -e "  ${C_RED}✘${C_RESET} $1"; }

echo ""
echo -e "${C_CYAN}═══════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_CYAN}  CLOUD-LAB CHECKPOINT · $TIMESTAMP${C_RESET}"
echo -e "${C_CYAN}═══════════════════════════════════════════════════════${C_RESET}"
echo ""

mkdir -p "$CHECKPOINT_DIR"/{k8s,helm,database,docker-images,external-monitoring,scripts,git-repos,secrets}

# ─── [1/10] K8s manifests ───
log "[1/10] K8s manifests"

python3 <<'PYEOF' > /tmp/strip_metadata.py
import sys, yaml, re

SKIP_KEYS = {
    'resourceVersion', 'uid', 'creationTimestamp', 'generation',
    'selfLink', 'managedFields', 'ownerReferences', 'finalizers'
}
SKIP_STATUS = True

def strip(obj):
    if isinstance(obj, dict):
        obj = {k: strip(v) for k, v in obj.items()
               if k not in SKIP_KEYS and not (SKIP_STATUS and k == 'status')}
        # Annotations: keep useful, drop noisy
        if 'metadata' in obj and 'annotations' in obj['metadata']:
            ann = obj['metadata']['annotations']
            for k in list(ann.keys()):
                if any(x in k for x in ['last-applied', 'deployment.kubernetes.io/revision',
                                         'kubectl.kubernetes.io', 'argocd.argoproj.io/tracking']):
                    del ann[k]
            if not ann:
                del obj['metadata']['annotations']
        return obj
    elif isinstance(obj, list):
        return [strip(x) for x in obj]
    return obj

for doc in yaml.safe_load_all(sys.stdin):
    if doc:
        yaml.safe_dump(strip(doc), sys.stdout, default_flow_style=False, sort_keys=False)
        print('---')
PYEOF

for ns in infra data-platform cps airflow traefik argocd monitoring; do
    kubectl get deploy,sts,svc,cm,pvc,job,ingress,ingressroute,application,secret,sa,role,rolebinding,cronjob,networkpolicy,servicemonitor,prometheusrule \
        -n "$ns" -o yaml 2>/dev/null | python3 /tmp/strip_metadata.py > "$CHECKPOINT_DIR/k8s/$ns.yaml" || true
    lines=$(wc -l < "$CHECKPOINT_DIR/k8s/$ns.yaml" 2>/dev/null || echo 0)
    if [ "$lines" -gt 5 ]; then
        ok "$ns.yaml ($lines lines)"
    else
        warn "$ns.yaml пустой"
    fi
done

# Namespaces + cluster-scoped
kubectl get ns -o yaml 2>/dev/null | python3 /tmp/strip_metadata.py > "$CHECKPOINT_DIR/k8s/namespaces.yaml" || true
kubectl get ingressclass,clusterrole,clusterrolebinding -o yaml 2>/dev/null | python3 /tmp/strip_metadata.py > "$CHECKPOINT_DIR/k8s/cluster-scoped.yaml" || true
ok "cluster-scoped"

# ─── [2/10] Helm values ───
log "[2/10] Helm values"

cp "$CLOUD_LAB/infra/airflow-values.yaml" "$CHECKPOINT_DIR/helm/" 2>/dev/null || true
cp "$CLOUD_LAB/infra/argocd-values.yaml" "$CHECKPOINT_DIR/helm/" 2>/dev/null || true
cp "$CLOUD_LAB/infra/traefik-values.yaml" "$CHECKPOINT_DIR/helm/" 2>/dev/null || true
cp "$CLOUD_LAB/infra/kube-prometheus-values.yaml" "$CHECKPOINT_DIR/helm/" 2>/dev/null || true

helm list -A > "$CHECKPOINT_DIR/helm/helm-releases.txt" 2>&1
ok "helm values + releases"

# ─── [3/10] PostgreSQL dumps ───
log "[3/10] PostgreSQL dumps"

kubectl exec -n infra deploy/postgres -- \
    env PGPASSWORD=postgres pg_dump -U admin -d farcana --no-owner 2>/dev/null | \
    gzip > "$CHECKPOINT_DIR/database/pg-farcana.sql.gz" || warn "PG farcana dump failed"
ok "pg-farcana.sql.gz ($(du -h "$CHECKPOINT_DIR/database/pg-farcana.sql.gz" | cut -f1))"

kubectl exec -n airflow airflow-postgresql-0 -- \
    env PGPASSWORD=postgres pg_dump -U postgres -d postgres --no-owner 2>/dev/null | \
    gzip > "$CHECKPOINT_DIR/database/pg-airflow.sql.gz" || warn "PG airflow dump failed"
ok "pg-airflow.sql.gz ($(du -h "$CHECKPOINT_DIR/database/pg-airflow.sql.gz" | cut -f1))"

# ─── [4/10] ClickHouse dumps ───
log "[4/10] ClickHouse dumps"

for table in match_telemetry nft_transactions financial_reports sensor_data sensor_aggregates; do
    kubectl exec -n infra deploy/clickhouse -- \
        clickhouse-client --user admin --password admin \
        --query "SELECT * FROM game_analytics.$table FORMAT SQLInsert" 2>/dev/null | \
        gzip > "$CHECKPOINT_DIR/database/ch-$table.sql.gz" 2>/dev/null || true
done
ok "CH dumps: $(ls "$CHECKPOINT_DIR/database/ch-"*.gz 2>/dev/null | wc -l) tables"

# ─── [5/10] Docker images ───
log "[5/10] Docker images"

for img in cloud-lab/simulator:latest cloud-lab/visualizer:latest; do
    name=$(echo "$img" | tr '/:' '-')
    if docker image inspect "$img" >/dev/null 2>&1; then
        docker save "$img" | gzip > "$CHECKPOINT_DIR/docker-images/$name.tar.gz"
        ok "$name.tar.gz ($(du -h "$CHECKPOINT_DIR/docker-images/$name.tar.gz" | cut -f1))"
    else
        warn "$img not found"
    fi
done

# ─── [6/10] External monitoring ───
log "[6/10] External monitoring"

cp -r "$CLOUD_LAB/external-monitoring/config" "$CHECKPOINT_DIR/external-monitoring/" 2>/dev/null || true
cp "$CLOUD_LAB/external-monitoring/docker-compose.yml" "$CHECKPOINT_DIR/external-monitoring/" 2>/dev/null || true
ok "docker-compose + configs"

# ─── [7/10] Scripts ───
log "[7/10] Scripts"

cp -r "$CLOUD_LAB/scripts" "$CHECKPOINT_DIR/" 2>/dev/null || true
cp "$CLOUD_LAB/CONTEXT-CURRENT.md" "$CHECKPOINT_DIR/" 2>/dev/null || true
ok "scripts + context"

# ─── [8/10] Git repos ───
log "[8/10] Git repos"

if [ -d "$HOME/cloud-lab-manifests/.git" ]; then
    cd "$HOME/cloud-lab-manifests"
    git bundle create "$CHECKPOINT_DIR/git-repos/cloud-lab-manifests.bundle" --all 2>/dev/null || true
    cd - >/dev/null
    ok "cloud-lab-manifests.bundle"
fi

# Also save DAGs from PVC
mkdir -p "$CHECKPOINT_DIR/airflow-dags"
for f in farcana_etl.py chimeras_etl.py kyriba_etl.py; do
    kubectl cp airflow/airflow-scheduler-0:/opt/airflow/dags/$f "$CHECKPOINT_DIR/airflow-dags/$f" 2>/dev/null || true
done
# Fallback: from local
cp "$CLOUD_LAB/airflow-dags"/*.py "$CHECKPOINT_DIR/airflow-dags/" 2>/dev/null || true
ok "DAGs"

# ─── [9/10] Secrets ───
log "[9/10] Secrets"

cat > "$CHECKPOINT_DIR/secrets/credentials.env" <<EOF
# Cloud-Lab credentials — DO NOT COMMIT TO GIT
# Created: $TIMESTAMP

# PostgreSQL (infra)
PG_INFRA_HOST=postgres.infra.svc.cluster.local
PG_INFRA_USER=admin
PG_INFRA_PASSWORD=postgres
PG_INFRA_DB=farcana

# PostgreSQL (airflow)
PG_AIRFLOW_HOST=airflow-postgresql.airflow.svc.cluster.local
PG_AIRFLOW_USER=postgres
PG_AIRFLOW_PASSWORD=postgres

# ClickHouse
CH_HOST=clickhouse.infra.svc.cluster.local
CH_USER=admin
CH_PASSWORD=admin
CH_DB=game_analytics

# MinIO
MINIO_URL=minio.infra.svc.cluster.local:9000
MINIO_USER=minioadmin
MINIO_PASSWORD=minioadmin

# Grafana (external)
GRAFANA_URL=http://localhost:3100
GRAFANA_USER=admin
GRAFANA_PASSWORD=admin

# ArgoCD
ARGOCD_URL=http://argocd.cloud-lab.local
ARGOCD_USER=admin
# Password: kubectl get secret -n argocd argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d

# GitHub
GITHUB_USER=h4kumw
GITHUB_REPO=https://github.com/h4kumw/h4ku-cloud-lab-manifests.git
# PAT: см. github-pat.txt

# Airflow
AIRFLOW_URL=http://localhost:8080
AIRFLOW_USER=admin
AIRFLOW_PASSWORD=admin
EOF
ok "credentials.env"

# GitHub PAT from K8s Secret
kubectl get secret repo-cloud-lab-manifests -n argocd \
    -o jsonpath='{.data.password}' 2>/dev/null | base64 -d > "$CHECKPOINT_DIR/secrets/github-pat.txt" 2>/dev/null || true
if [ -s "$CHECKPOINT_DIR/secrets/github-pat.txt" ]; then
    ok "github-pat.txt"
fi

# ArgoCD admin password
kubectl get secret argocd-initial-admin-secret -n argocd \
    -o jsonpath='{.data.password}' 2>/dev/null | base64 -d > "$CHECKPOINT_DIR/secrets/argocd-admin-password.txt" 2>/dev/null || true
ok "argocd-admin-password.txt"

# .gitignore to prevent accidental commit
cat > "$CHECKPOINT_DIR/secrets/.gitignore" <<EOF
*
!.gitignore
!credentials.env.example
EOF
ok "secrets/.gitignore"

# ─── [10/10] Metadata ───
log "[10/10] Metadata"

# Cluster info
{
    echo "# Cluster info"
    echo "Date: $TIMESTAMP"
    echo ""
    echo "## K3d cluster"
    k3d cluster list 2>&1
    echo ""
    echo "## Nodes"
    kubectl get nodes -o wide 2>&1
    echo ""
    echo "## All pods"
    kubectl get pods -A 2>&1
    echo ""
    echo "## Namespaces"
    kubectl get ns 2>&1
    echo ""
    echo "## Docker images (custom)"
    docker image ls | grep -E "cloud-lab|pgvector" 2>&1
    echo ""
    echo "## Git commit"
    cd "$HOME/cloud-lab-manifests" && git log -1 --oneline 2>&1
} > "$CHECKPOINT_DIR/cluster-info.txt"
ok "cluster-info.txt"

# MANIFEST with checksums
{
    echo "# Cloud-Lab Checkpoint Manifest"
    echo "Timestamp: $TIMESTAMP"
    echo "Created: $(date)"
    echo ""
    echo "## Files + checksums (SHA256)"
    find "$CHECKPOINT_DIR" -type f -exec sha256sum {} \; | sed "s|$CHECKPOINT_DIR/||"
} > "$CHECKPOINT_DIR/manifest.txt"
ok "manifest.txt"

# ─── Create tarball ───
log "Creating tarball..."

cd "$HOME"
tar czf "$TARBALL" "cloud-lab-checkpoint-$TIMESTAMP" 2>/dev/null
cd - >/dev/null

SIZE=$(du -h "$TARBALL" | cut -f1)
ok "Tarball: $TARBALL ($SIZE)"

# Cleanup uncompressed dir (optional — comment out to keep)
# rm -rf "$CHECKPOINT_DIR"

echo ""
echo -e "${C_GREEN}═══════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_GREEN}  ✔ CHECKPOINT ГОТОВ${C_RESET}"
echo -e "${C_GREEN}═══════════════════════════════════════════════════════${C_RESET}"
echo ""
echo -e "  📦 Tarball:     ${C_CYAN}$TARBALL${C_RESET}"
echo -e "  📂 Directory:   ${C_CYAN}$CHECKPOINT_DIR${C_RESET}"
echo -e "  📏 Size:        ${C_CYAN}$SIZE${C_RESET}"
echo ""
echo -e "  ${C_DIM}Восстановить:${C_RESET} bash ~/cloud-lab/scripts/restore-from-checkpoint.sh $TARBALL"
echo ""

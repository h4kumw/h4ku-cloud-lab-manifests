#!/usr/bin/env bash
# Cloud-Lab Checkpoint — сохраняет ВСЁ для восстановления
set -euo pipefail

CLOUD_LAB="$HOME/cloud-lab"
TIMESTAMP=$(date +%Y-%m-%d-%H%M)
CHECKPOINT_DIR="$HOME/cloud-lab-checkpoint-$TIMESTAMP"
TARBALL="$HOME/cloud-lab-checkpoint-$TIMESTAMP.tar.gz"

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

mkdir -p "$CHECKPOINT_DIR"/{k8s,helm,database,docker-images,external-monitoring,scripts,git-repos,secrets,airflow-dags}

# ═══════════════════════════════════════════════════════════
# [1/10] K8s manifests — per-type loop + split by ns
# ═══════════════════════════════════════════════════════════
log "[1/10] K8s manifests"

# Create strip_metadata.py once
cat > /tmp/strip_metadata.py <<'STRIP_EOF'
import sys, yaml

SKIP_KEYS = {
    'resourceVersion', 'uid', 'creationTimestamp', 'generation',
    'selfLink', 'managedFields', 'ownerReferences', 'finalizers'
}

def strip(obj):
    if isinstance(obj, dict):
        obj = {k: strip(v) for k, v in obj.items()
               if k not in SKIP_KEYS and k != 'status'}
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
STRIP_EOF

# List of resource types to save
RESOURCES="configmaps deployments statefulsets daemonsets replicasets services persistentvolumeclaims jobs cronjobs serviceaccounts roles rolebindings networkpolicies resourcequotas limitranges poddisruptionbudgets ingresses ingressroutes applications applicationsets servicemonitors prometheusrules podmonitors prometheuses alertmanagers"

# Collect all resources
: > /tmp/all_k8s_resources.yaml

for res in $RESOURCES; do
    if ! kubectl api-resources -o name 2>/dev/null | grep -qE "^${res}([.][a-z0-9.-]+)?$"; then
        continue
    fi
    output=$(kubectl get "$res" -A -o yaml --ignore-not-found 2>/dev/null || true)
    if [ -n "$output" ]; then
        echo "$output" >> /tmp/all_k8s_resources.yaml
        echo "---" >> /tmp/all_k8s_resources.yaml
    fi
done

# Strip metadata
python3 /tmp/strip_metadata.py < /tmp/all_k8s_resources.yaml > /tmp/all_k8s_clean.yaml

# Split by namespace via Python (unroll List → items)
python3 - "$CHECKPOINT_DIR" <<'SPLIT_EOF'
import sys, yaml
from pathlib import Path
from collections import defaultdict

checkpoint_dir = Path(sys.argv[1]) / "k8s"
checkpoint_dir.mkdir(parents=True, exist_ok=True)

ns_docs = defaultdict(list)

def add_doc(doc):
    if not doc or not isinstance(doc, dict):
        return
    # Unroll List → items
    if doc.get('kind') == 'List':
        for item in doc.get('items', []):
            add_doc(item)
        return
    ns = doc.get('metadata', {}).get('namespace', '_cluster')
    ns_docs[ns].append(doc)

with open("/tmp/all_k8s_clean.yaml") as f:
    for doc in yaml.safe_load_all(f):
        add_doc(doc)

total = 0
for ns, docs in sorted(ns_docs.items()):
    safe_ns = ns.replace('/', '_')
    path = checkpoint_dir / f"{safe_ns}.yaml"
    with open(path, 'w') as f:
        yaml.safe_dump_all(docs, f, default_flow_style=False, sort_keys=False)
    print(f"  ✔ {safe_ns}.yaml ({len(docs)} resources)")
    total += len(docs)

print(f"  ✔ TOTAL: {total} resources in {len(ns_docs)} namespaces")
SPLIT_EOF

ok "k8s manifests saved"

# ═══════════════════════════════════════════════════════════
# Secrets (без SA tokens)
# ═══════════════════════════════════════════════════════════
mkdir -p "$CHECKPOINT_DIR/k8s/secrets"
for ns in infra data-platform cps airflow traefik argocd monitoring; do
    kubectl get secrets -n "$ns" -o yaml --ignore-not-found 2>/dev/null | \
        grep -vE "type: kubernetes.io/service-account-token" | \
        python3 /tmp/strip_metadata.py > "$CHECKPOINT_DIR/k8s/secrets/$ns.yaml" 2>/dev/null || true
done
ok "k8s/secrets/ (без SA tokens)"

# ═══════════════════════════════════════════════════════════
# Cluster-scoped
# ═══════════════════════════════════════════════════════════
kubectl get namespaces -o yaml 2>/dev/null | python3 /tmp/strip_metadata.py > "$CHECKPOINT_DIR/k8s/_namespaces.yaml" || true
kubectl get clusterroles,clusterrolebindings,ingressclasses,storageclasses,priorityclasses -o yaml --ignore-not-found 2>/dev/null | \
    python3 /tmp/strip_metadata.py > "$CHECKPOINT_DIR/k8s/_cluster-scoped.yaml" || true
ok "cluster-scoped"

# ═══════════════════════════════════════════════════════════
# [2/10] Helm values
# ═══════════════════════════════════════════════════════════
log "[2/10] Helm values"

for f in airflow-values.yaml argocd-values.yaml traefik-values.yaml kube-prometheus-values.yaml; do
    [ -f "$CLOUD_LAB/infra/$f" ] && cp "$CLOUD_LAB/infra/$f" "$CHECKPOINT_DIR/helm/" 2>/dev/null || true
done
helm list -A > "$CHECKPOINT_DIR/helm/helm-releases.txt" 2>&1
ok "helm values + releases"

# ═══════════════════════════════════════════════════════════
# [3/10] PostgreSQL dumps
# ═══════════════════════════════════════════════════════════
log "[3/10] PostgreSQL dumps"

kubectl exec -n infra deploy/postgres -- \
    env PGPASSWORD=postgres pg_dump -U admin -d farcana --no-owner 2>/dev/null | \
    gzip > "$CHECKPOINT_DIR/database/pg-farcana.sql.gz" || warn "PG farcana dump failed"
[ -s "$CHECKPOINT_DIR/database/pg-farcana.sql.gz" ] && ok "pg-farcana.sql.gz ($(du -h "$CHECKPOINT_DIR/database/pg-farcana.sql.gz" | cut -f1))"

kubectl exec -n airflow airflow-postgresql-0 -- \
    env PGPASSWORD=postgres pg_dump -U postgres -d postgres --no-owner 2>/dev/null | \
    gzip > "$CHECKPOINT_DIR/database/pg-airflow.sql.gz" || warn "PG airflow dump failed"
[ -s "$CHECKPOINT_DIR/database/pg-airflow.sql.gz" ] && ok "pg-airflow.sql.gz ($(du -h "$CHECKPOINT_DIR/database/pg-airflow.sql.gz" | cut -f1))"

# ═══════════════════════════════════════════════════════════
# [4/10] ClickHouse dumps
# ═══════════════════════════════════════════════════════════
log "[4/10] ClickHouse dumps"

for table in match_telemetry nft_transactions financial_reports sensor_data sensor_aggregates; do
    kubectl exec -n infra deploy/clickhouse -- \
        clickhouse-client --user admin --password admin \
        --query "SELECT * FROM game_analytics.$table FORMAT SQLInsert" 2>/dev/null | \
        gzip > "$CHECKPOINT_DIR/database/ch-$table.sql.gz" 2>/dev/null || true
done
COUNT=$(ls "$CHECKPOINT_DIR/database/ch-"*.gz 2>/dev/null | wc -l)
ok "CH dumps: $COUNT tables"

# ═══════════════════════════════════════════════════════════
# [5/10] Docker images
# ═══════════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════════
# [6/10] External monitoring
# ═══════════════════════════════════════════════════════════
log "[6/10] External monitoring"

cp -r "$CLOUD_LAB/external-monitoring/config" "$CHECKPOINT_DIR/external-monitoring/" 2>/dev/null || true
cp "$CLOUD_LAB/external-monitoring/docker-compose.yml" "$CHECKPOINT_DIR/external-monitoring/" 2>/dev/null || true
ok "docker-compose + configs"

# ═══════════════════════════════════════════════════════════
# [7/10] Scripts + CONTEXT
# ═══════════════════════════════════════════════════════════
log "[7/10] Scripts"

cp -r "$CLOUD_LAB/scripts" "$CHECKPOINT_DIR/" 2>/dev/null || true
cp "$CLOUD_LAB/CONTEXT-CURRENT.md" "$CHECKPOINT_DIR/" 2>/dev/null || true
ok "scripts + context"

# ═══════════════════════════════════════════════════════════
# [8/10] Git repos + DAGs
# ═══════════════════════════════════════════════════════════
log "[8/10] Git repos"

if [ -d "$HOME/cloud-lab-manifests/.git" ]; then
    cd "$HOME/cloud-lab-manifests"
    git bundle create "$CHECKPOINT_DIR/git-repos/cloud-lab-manifests.bundle" --all 2>/dev/null || true
    cd - >/dev/null
    ok "cloud-lab-manifests.bundle"
fi

# DAGs from local
cp "$CLOUD_LAB/airflow-dags"/*.py "$CHECKPOINT_DIR/airflow-dags/" 2>/dev/null || true
DAG_COUNT=$(ls "$CHECKPOINT_DIR/airflow-dags/"*.py 2>/dev/null | wc -l)
ok "DAGs ($DAG_COUNT files)"

# ═══════════════════════════════════════════════════════════
# [9/10] Secrets
# ═══════════════════════════════════════════════════════════
log "[9/10] Secrets"

cat > "$CHECKPOINT_DIR/secrets/credentials.env" <<'CREDS_EOF'
# Cloud-Lab credentials — DO NOT COMMIT TO GIT
PG_INFRA_HOST=postgres.infra.svc.cluster.local
PG_INFRA_USER=admin
PG_INFRA_PASSWORD=postgres
PG_INFRA_DB=farcana

PG_AIRFLOW_HOST=airflow-postgresql.airflow.svc.cluster.local
PG_AIRFLOW_USER=postgres
PG_AIRFLOW_PASSWORD=postgres

CH_HOST=clickhouse.infra.svc.cluster.local
CH_USER=admin
CH_PASSWORD=admin
CH_DB=game_analytics

MINIO_URL=minio.infra.svc.cluster.local:9000
MINIO_USER=minioadmin
MINIO_PASSWORD=minioadmin

GRAFANA_URL=http://localhost:3100
GRAFANA_USER=admin
GRAFANA_PASSWORD=admin

ARGOCD_URL=http://argocd.cloud-lab.local
ARGOCD_USER=admin

GITHUB_USER=h4kumw
GITHUB_REPO=https://github.com/h4kumw/h4ku-cloud-lab-manifests.git

AIRFLOW_URL=http://localhost:8080
AIRFLOW_USER=admin
AIRFLOW_PASSWORD=admin
CREDS_EOF
ok "credentials.env"

kubectl get secret repo-cloud-lab-manifests -n argocd \
    -o jsonpath='{.data.password}' 2>/dev/null | base64 -d > "$CHECKPOINT_DIR/secrets/github-pat.txt" 2>/dev/null || true
[ -s "$CHECKPOINT_DIR/secrets/github-pat.txt" ] && ok "github-pat.txt"

kubectl get secret argocd-initial-admin-secret -n argocd \
    -o jsonpath='{.data.password}' 2>/dev/null | base64 -d > "$CHECKPOINT_DIR/secrets/argocd-admin-password.txt" 2>/dev/null || true
ok "argocd-admin-password.txt"

cat > "$CHECKPOINT_DIR/secrets/.gitignore" <<'GI_EOF'
*
!.gitignore
GI_EOF
ok "secrets/.gitignore"

# ═══════════════════════════════════════════════════════════
# [10/10] Metadata
# ═══════════════════════════════════════════════════════════
log "[10/10] Metadata"

{
    echo "# Cloud-Lab Checkpoint Metadata"
    echo "Timestamp: $TIMESTAMP"
    echo "Created: $(date)"
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

{
    echo "# Cloud-Lab Checkpoint Manifest"
    echo "Timestamp: $TIMESTAMP"
    echo "Created: $(date)"
    echo ""
    echo "## Files + checksums (SHA256)"
    find "$CHECKPOINT_DIR" -type f -exec sha256sum {} \; | sed "s|$CHECKPOINT_DIR/||"
} > "$CHECKPOINT_DIR/manifest.txt"
ok "manifest.txt"

# ═══════════════════════════════════════════════════════════
# Create tarball
# ═══════════════════════════════════════════════════════════
log "Creating tarball..."

cd "$HOME"
tar czf "$TARBALL" "cloud-lab-checkpoint-$TIMESTAMP" 2>/dev/null
cd - >/dev/null

SIZE=$(du -h "$TARBALL" | cut -f1)
ok "Tarball: $TARBALL ($SIZE)"

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

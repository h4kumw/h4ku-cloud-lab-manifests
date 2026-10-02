#!/usr/bin/env bash
# Cloud-Lab Recovery — поднимает стек после restart
set -uo pipefail

CLOUD_LAB="$HOME/cloud-lab"
PIDS_DIR="$CLOUD_LAB/.pids"
LOGS_DIR="$CLOUD_LAB/logs"

C_GREEN='\033[32m'; C_CYAN='\033[36m'; C_YELLOW='\033[33m'
C_RED='\033[31m'; C_RESET='\033[0m'; C_DIM='\033[2m'

log() { echo -e "${C_CYAN}▶${C_RESET} $1"; }
ok() { echo -e "  ${C_GREEN}✔${C_RESET} $1"; }
warn() { echo -e "  ${C_YELLOW}⚠${C_RESET} $1"; }
fail() { echo -e "  ${C_RED}✘${C_RESET} $1"; }

echo ""
echo -e "${C_CYAN}═══════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_CYAN}  CLOUD-LAB RECOVER${C_RESET}"
echo -e "${C_CYAN}═══════════════════════════════════════════════════════${C_RESET}"
echo ""

mkdir -p "$PIDS_DIR" "$LOGS_DIR"

# ─── [1/6] K3d cluster ───
log "[1/6] K3d cluster"

if ! k3d cluster list 2>/dev/null | grep -q cps-lab; then
    fail "Cluster doesn't exist — run start-all.sh"
    exit 1
fi

# Check if running
K3D_RUNNING=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -c k3d-cps-lab-server-0)
if [ "$K3D_RUNNING" -eq 0 ]; then
    warn "K3d stopped — starting..."
    k3d cluster start cps-lab 2>&1 | tail -2

    # Wait for nodes
    for i in $(seq 1 60); do
        ready=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready" || echo 0)
        if [ "$ready" -eq 4 ]; then
            break
        fi
        sleep 2
    done
fi

ready=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready" || echo 0)
if [ "$ready" -eq 4 ]; then
    ok "K3d: 4/4 nodes Ready"
else
    warn "K3d: $ready/4 nodes Ready"
fi

# ─── [2/6] External monitoring ───
log "[2/6] External monitoring"

cd "$CLOUD_LAB/external-monitoring"
MON_UP=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -cE 'prometheus|grafana|alertmanager')
if [ "$MON_UP" -lt 3 ]; then
    warn "Monitoring down ($MON_UP/3) — starting..."
    docker compose up -d 2>&1 | tail -3
    sleep 10
fi

# Connect k3d network
for node in server-0 agent-0 agent-1 agent-2; do
    docker network connect external-monitoring_monitoring "k3d-cps-lab-$node" 2>/dev/null || true
done
docker network connect k3d-cps-lab prometheus-external 2>/dev/null || true

MON_UP=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -cE 'prometheus|grafana|alertmanager')
ok "Monitoring: $MON_UP/3 Running"

cd - >/dev/null

# ─── [2.5/6] Federation IP check ───
log "[2.5/6] Federation IP check"

CURRENT_IP=$(docker inspect k3d-cps-lab-server-0 2>/dev/null | \
    jq -r '.[0].NetworkSettings.Networks."k3d-cps-lab".IPAddress' 2>/dev/null || echo "")

if [ -n "$CURRENT_IP" ]; then
    PROM_YML="$CLOUD_LAB/external-monitoring/config/prometheus.yml"
    OLD_TARGET=$(grep -oP "targets: \['\\K[^:]+(?=:30715)" "$PROM_YML" 2>/dev/null || echo "")

    if [ "$OLD_TARGET" != "$CURRENT_IP" ]; then
        warn "Federation IP changed: $OLD_TARGET → $CURRENT_IP"
        sed -i "s|$OLD_TARGET:30715|$CURRENT_IP:30715|g" "$PROM_YML"
        cd "$CLOUD_LAB/external-monitoring"
        docker compose restart prometheus >/dev/null 2>&1
        sleep 10
        ok "Federation IP updated + prometheus restarted"
    else
        ok "Federation IP unchanged ($CURRENT_IP)"
    fi
fi

# ─── [3/6] Port-forwards ───
log "[3/6] Port-forwards"

# Clean dead PIDs
rm -f "$PIDS_DIR"/*.pid 2>/dev/null || true
pkill -f "kubectl port-forward" 2>/dev/null || true
sleep 2

# Ensure KUBECONFIG
export KUBECONFIG="$HOME/.kube/config"

ensure_pf() {
    local name="$1" ns="$2" svc="$3" ports="$4" check_url="$5"
    local pidfile="$PIDS_DIR/${name}.pid"
    local logfile="$LOGS_DIR/${name}.log"

    # Check if service exists
    if ! kubectl get svc "$svc" -n "$ns" >/dev/null 2>&1; then
        warn "$name — svc $ns/$svc not found"
        return 1
    fi

    nohup kubectl port-forward -n "$ns" "svc/$svc" "$ports" \
        > "$logfile" 2>&1 < /dev/null &
    echo $! > "$pidfile"
    sleep 2

    if [ -n "$check_url" ]; then
        for i in $(seq 1 20); do
            code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$check_url" 2>/dev/null || echo "000")
            if [ "$code" = "200" ] || [ "$code" = "302" ]; then
                ok "$name → $check_url ($code)"
                return 0
            fi
            sleep 1
        done
        warn "$name — no response after 20s"
    else
        ok "$name (no check)"
    fi
}

# Start all PFs
ensure_pf "pg-farcana-pf" "infra" "postgres" "15432:5432" ""
ensure_pf "ch-pf" "infra" "clickhouse" "8123:8123" ""
ensure_pf "visualizer-pf" "data-platform" "visualizer" "30050:5000" "http://localhost:30050/"
ensure_pf "airflow-pf" "airflow" "airflow-api-server" "8080:8080" "http://localhost:8080/"
ensure_pf "kube-prom-pf" "monitoring" "kube-prom-kube-prometheus-prometheus" "9091:9090" ""

# ─── [4/6] Services (RAG UI, etc.) ───
log "[4/6] External services"

# RAG UI
if [ -f "$PIDS_DIR/rag-ui.pid" ]; then
    OLD_PID=$(cat "$PIDS_DIR/rag-ui.pid")
    if ! kill -0 "$OLD_PID" 2>/dev/null; then
        rm -f "$PIDS_DIR/rag-ui.pid"
    fi
fi

if ! ps aux | grep -q "[r]ag_ui.py"; then
    warn "RAG UI not running — starting..."
    cd "$CLOUD_LAB/visualization"
    export PG_HOST=localhost PG_PORT=15432 PG_USER=admin PG_PASSWORD=postgres PG_DB=farcana OLLAMA_URL=http://localhost:11434
    nohup "$CLOUD_LAB/venv/bin/python" rag_ui.py > "$LOGS_DIR/rag-ui.log" 2>&1 < /dev/null &
    echo $! > "$PIDS_DIR/rag-ui.pid"
    sleep 3
    cd - >/dev/null
fi

for i in $(seq 1 10); do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://localhost:5001/" 2>/dev/null || echo "000")
    if [ "$code" = "200" ]; then
        ok "RAG UI → 200"
        break
    fi
    sleep 2
done

# ─── [5/6] Alerts check ───
log "[5/6] Alerts"

# Check kube-prom federation
FED_HEALTH=$(curl -s http://localhost:9090/api/v1/targets 2>/dev/null | jq -r '.data.activeTargets[] | select(.scrapePool=="k3d-federate") | .health' 2>/dev/null || echo "unknown")

if [ "$FED_HEALTH" = "up" ]; then
    ok "Federation: up"
else
    warn "Federation: $FED_HEALTH — проверь kube-prom pods:"
    echo -e "  ${C_DIM}kubectl get pods -n monitoring${C_RESET}"
fi

# Check active alerts
ALERTS=$(curl -s http://localhost:9090/api/v1/alerts 2>/dev/null | jq -r '.data.alerts | length' 2>/dev/null || echo "?")
if [ "$ALERTS" = "0" ]; then
    ok "Alerts: 0 firing"
else
    warn "Alerts firing: $ALERTS"
    curl -s http://localhost:9090/api/v1/alerts 2>/dev/null | jq -r '.data.alerts[] | "  - \(.labels.alertname): \(.annotations.summary)"' 2>/dev/null | head -5
fi

# ─── [6/6] Health check ───
log "[6/6] Health check"

PASS=0; FAIL=0
for url in "Airflow|http://localhost:8080/" \
           "Grafana|http://localhost:3100/api/health" \
           "RAG UI|http://localhost:5001/" \
           "Visualizer|http://localhost:30050/" \
           "Prometheus|http://localhost:9090/-/healthy" \
           "Alertmanager|http://localhost:9093/-/healthy"; do
    NAME="${url%%|*}"; U="${url##*|}"
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$U" 2>/dev/null || echo "000")
    if [ "$code" = "200" ] || [ "$code" = "302" ]; then
        printf "  ${C_GREEN}✔${C_RESET} %-15s → %s\n" "$NAME" "$code"
        PASS=$((PASS + 1))
    else
        printf "  ${C_RED}✘${C_RESET} %-15s → %s\n" "$NAME" "$code"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo -e "${C_CYAN}═══════════════════════════════════════════════════════${C_RESET}"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${C_GREEN}  ✔ RECOVER ЗАВЕРШЁН — $PASS/6 сервисов OK${C_RESET}"
else
    echo -e "${C_YELLOW}  ⚠ RECOVER — $PASS/6 OK, $FAIL FAIL${C_RESET}"
fi
echo -e "${C_CYAN}═══════════════════════════════════════════════════════${C_RESET}"
echo ""

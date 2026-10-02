#!/bin/bash
# Общая библиотека port-forward с надёжными watchdog'ами

PIDS_DIR="${PIDS_DIR:-$HOME/cloud-lab/.pids}"
LOGS_DIR="${LOGS_DIR:-$HOME/cloud-lab/logs}"
mkdir -p "$PIDS_DIR" "$LOGS_DIR"

# ─── Убить процесс + watchdog ───
pf_stop() {
    local name="$1"
    for suffix in "" "-watch"; do
        local pf="$PIDS_DIR/${name}${suffix}.pid"
        if [ -f "$pf" ]; then
            local pid=$(cat "$pf" 2>/dev/null || echo "")
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
            fi
            rm -f "$pf"
        fi
    done
}

# ─── Запустить PF + watchdog (nohup+disown — переживает shell) ───
pf_start() {
    local name="$1"        # airflow-pf
    local namespace="$2"   # airflow
    local svc="$3"         # airflow-api-server
    local ports="$4"       # 8080:8080
    local wait_url="$5"    # http://localhost:8080/ (опционально)

    pf_stop "$name"
    pkill -f "port-forward.*$svc" 2>/dev/null || true
    sleep 1

    local log="$LOGS_DIR/${name}.log"
    nohup kubectl port-forward -n "$namespace" "svc/$svc" "$ports" \
        > "$log" 2>&1 </dev/null &
    echo $! > "$PIDS_DIR/${name}.pid"

    # Watchdog — полностью отсоединяем от родителя через setsid
    # (иначе start-all.sh будет ждать завершения watchdog'а и висеть)
    setsid bash -c "
        while true; do
            sleep 30
            pf_pid=\$(cat '$PIDS_DIR/${name}.pid' 2>/dev/null)
            if [ -z \"\$pf_pid\" ] || ! kill -0 \"\$pf_pid\" 2>/dev/null; then
                pkill -f 'port-forward.*$svc' 2>/dev/null || true
                sleep 1
                nohup kubectl port-forward -n '$namespace' 'svc/$svc' '$ports' \
                    > '$log' 2>&1 </dev/null &
                echo \$! > '$PIDS_DIR/${name}.pid'
            fi
        done
    " > "$LOGS_DIR/${name}-watch.log" 2>&1 </dev/null &
    echo $! > "$PIDS_DIR/${name}-watch.pid"

    # Ждём готовности
    if [ -n "$wait_url" ]; then
        for i in $(seq 1 30); do
            code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 1 "$wait_url" 2>/dev/null || echo "000")
            if [ "$code" = "200" ] || [ "$code" = "302" ]; then
                echo "✅ $name готов ($wait_url → $code) за ${i}s"
                return 0
            fi
            sleep 1
        done
        echo "⚠️  $name не ответил за 30s ($wait_url)"
        return 1
    fi
    echo "✅ $name запущен"
}

# ─── Запустить сервис (python-скрипт) + watchdog ───
service_start() {
    local name="$1"        # rag-ui
    local cmd="$2"         # "/home/h4ku/cloud-lab/venv/bin/python rag_ui.py"
    local cwd="$3"         # рабочая директория
    local wait_url="$4"    # http://localhost:5001/
    local env_vars="${5:-}"  # опционально: env variables

    pf_stop "$name"
    pkill -f "$(basename $cmd | awk '{print $1}')" 2>/dev/null || true
    sleep 1

    local log="$LOGS_DIR/${name}.log"
    cd "$cwd"
    nohup bash -c "exec $cmd" > "$log" 2>&1 </dev/null &
    echo $! > "$PIDS_DIR/${name}.pid"

    # Watchdog
    setsid bash -c "
        while true; do
            sleep 30
            pf_pid=\$(cat '$PIDS_DIR/${name}.pid' 2>/dev/null)
            if [ -z \"\$pf_pid\" ] || ! kill -0 \"\$pf_pid\" 2>/dev/null; then
                cd '$cwd'
                nohup bash -c 'exec $cmd' > '$log' 2>&1 </dev/null &
                echo \$! > '$PIDS_DIR/${name}.pid'
            fi
        done
    " > "$LOGS_DIR/${name}-watch.log" 2>&1 </dev/null &
    echo $! > "$PIDS_DIR/${name}-watch.pid"

    if [ -n "$wait_url" ]; then
        for i in $(seq 1 30); do
            code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 1 "$wait_url" 2>/dev/null || echo "000")
            if [ "$code" = "200" ]; then
                echo "✅ $name готов ($wait_url → 200) за ${i}s"
                return 0
            fi
            sleep 1
        done
        echo "⚠️  $name не ответил за 30s"
        return 1
    fi
}

from flask import Flask, render_template_string
from flask_socketio import SocketIO
import os
import random
import threading
import time
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ============================================================
# НАСТРОЙКИ
# ============================================================
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "admin")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DB = os.getenv("PG_DB", "farcana")

CH_HOST = os.getenv("CH_HOST", "localhost")
CH_PORT = int(os.getenv("CH_PORT", "8123"))
CH_USER = os.getenv("CH_USER", "admin")
CH_PASSWORD = os.getenv("CH_PASSWORD", "admin")
CH_URL = f"http://{CH_HOST}:{CH_PORT}/"
CH_PARAMS = {"user": CH_USER, "password": CH_PASSWORD}

# Координаты серверов (для линий)
SERVER_COORDS = {
    'srv_eu_1': (52.5, 13.4),
    'srv_us_1': (40.7, -74.0),
    'srv_asia_1': (1.35, 103.8),
    'srv_jp_1': (35.7, 139.7),
    'srv_au_1': (-33.9, 151.2),
}


def ch_query(query):
    """Запрос в ClickHouse."""
    try:
        r = requests.get(CH_URL, params={**CH_PARAMS, "query": query + " FORMAT JSON"}, timeout=5)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"❌ ClickHouse error: {e}")
        return []


def pg_query(query, params=None):
    """Запрос в PostgreSQL."""
    try:
        conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, database=PG_DB)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            result = cur.fetchall()
        conn.close()
        return result
    except Exception as e:
        print(f"❌ PostgreSQL error: {e}")
        return []


def get_players_from_db():
    """Последние игроки из match_telemetry — из PG (REAL-TIME, не через ETL)."""
    rows = pg_query("""
        SELECT player_id, lat, lon, last_seen
        FROM (
            SELECT player_id, lat, lon, event_time AS last_seen,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY event_time DESC) AS rn
            FROM match_telemetry
            WHERE event_time > (SELECT MAX(event_time) FROM match_telemetry) - INTERVAL '2 minutes'
              AND player_id IS NOT NULL
              AND lat IS NOT NULL
              AND lon IS NOT NULL
        ) sub
        WHERE rn = 1
        ORDER BY last_seen DESC
        LIMIT 200
    """)
    print(f"[DEBUG get_players_from_db] rows={len(rows) if rows else 0}", flush=True)
    if rows:
        try:
            result = [{"id": r["player_id"][:8], "lat": float(r["lat"]), "lon": float(r["lon"])} for r in rows]
            print(f"[DEBUG get_players_from_db] returning {len(result)} players", flush=True)
            return result
        except Exception as e:
            print(f"[DEBUG get_players_from_db] ERROR: {e}", flush=True)
            # Показать первую строку
            if rows:
                print(f"[DEBUG get_players_from_db] first row: {dict(rows[0])}", flush=True)
            return []
    return []


def get_servers():
    """Серверы."""
    return [
        {"id": "srv_eu_1", "lat": 52.5, "lon": 13.4},
        {"id": "srv_us_1", "lat": 40.7, "lon": -74.0},
        {"id": "srv_asia_1", "lat": 1.35, "lon": 103.8},
        {"id": "srv_jp_1", "lat": 35.7, "lon": 139.7},
        {"id": "srv_au_1", "lat": -33.9, "lon": 151.2},
    ]


# Фиксированные координаты устройств (по device_id)
DEVICE_COORDS = {
    # ─── US ───
    'sensor_01': (40.7, -74.0),    # New York
    'sensor_02': (34.0, -118.2),   # Los Angeles
    'sensor_03': (41.9, -87.6),    # Chicago
    'sensor_04': (37.8, -122.4),   # San Francisco
    'edge_01':   (47.6, -122.3),   # Seattle
    # ─── Europe ───
    'sensor_05': (51.5, -0.1),     # London
    'sensor_06': (48.9, 2.3),      # Paris
    'sensor_07': (52.5, 13.4),     # Berlin
    'sensor_08': (41.9, 12.5),     # Rome
    'sensor_09': (40.4, -3.7),     # Madrid
    'edge_02':   (55.7, 12.6),     # Copenhagen
    # ─── Asia ───
    'sensor_10': (35.7, 139.7),    # Tokyo
    'sensor_11': (37.6, 127.0),    # Seoul
    'sensor_12': (31.2, 121.5),    # Shanghai
    'sensor_13': (1.35, 103.8),    # Singapore
    'sensor_14': (19.1, 72.9),     # Mumbai
    'sensor_15': (25.2, 55.3),     # Dubai
    'sensor_16': (13.7, 100.5),    # Bangkok
    'sensor_17': (22.3, 114.2),    # Hong Kong
    # ─── Australia ───
    'sensor_18': (-33.9, 151.2),   # Sydney
    'sensor_19': (-37.8, 144.9),   # Melbourne
    # ─── South America ───
    'sensor_20': (-23.5, -46.6),   # São Paulo
    'sensor_21': (-34.6, -58.4),   # Buenos Aires
    'sensor_22': (-12.0, -77.0),   # Lima
    # ─── Africa ───
    'sensor_23': (-26.2, 28.0),    # Johannesburg
    'sensor_24': (30.0, 31.2),     # Cairo
    'sensor_25': (6.5, 3.4),       # Lagos
}


def get_sensors_from_db():
    """Последние значения сенсоров — один маркер на device (не на sensor_type)."""
    rows = pg_query("""
        SELECT DISTINCT ON (device_id)
            device_id,
            sensor_type,
            value,
            unit,
            created_at AS last_seen
        FROM cps_sensors
        WHERE created_at > NOW() - INTERVAL '15 minutes'
        ORDER BY device_id, created_at DESC
        LIMIT 50
    """)
    
    sensors = []
    for r in rows:
        device_id = r['device_id']
        if device_id in DEVICE_COORDS:
            base = DEVICE_COORDS[device_id]
        else:
            # Random global location для неизвестных devices
            base = (
                random.uniform(-45, 60),
                random.uniform(-150, 150),
            )
        sensors.append({
            "id": f"{device_id}",
            "lat": base[0] + random.uniform(-1.5, 1.5),
            "lon": base[1] + random.uniform(-1.5, 1.5),
            "value": round(float(r["value"]), 2),
            "unit": r["unit"],
            "sensor_type": r["sensor_type"],
        })
    return sensors


def get_nft_tx_count():
    rows = ch_query("SELECT COUNT(*) AS cnt FROM game_analytics.nft_transactions WHERE timestamp > now() - INTERVAL 1 HOUR")
    return int(rows[0]["cnt"]) if rows else 0


def get_recent_logs(limit=15):
    events = []
    for r in ch_query("""
        SELECT event_time AS ts, match_id, event_type
        FROM game_analytics.match_telemetry
        ORDER BY event_time DESC LIMIT 5
    """):
        events.append({"ts": r["ts"], "msg": f"[FARCANA] Match {r['match_id'][:8]} {r['event_type']}"})

    for r in ch_query("""
        SELECT timestamp AS ts, nft_id, price
        FROM game_analytics.nft_transactions
        ORDER BY timestamp DESC LIMIT 5
    """):
        events.append({"ts": r["ts"], "msg": f"[CHIMERAS] NFT {r['nft_id'][:10]} sold for {r['price']:.2f}"})

    for r in ch_query("""
        SELECT timestamp AS ts, device_id, sensor_type, value, unit
        FROM game_analytics.sensor_data
        ORDER BY timestamp DESC LIMIT 5
    """):
        events.append({"ts": r["ts"], "msg": f"[CPS] {r['device_id']}/{r['sensor_type']}={r['value']:.2f}{r['unit']}"})

    events.sort(key=lambda x: x["ts"], reverse=True)
    return [e["msg"] for e in events[:limit]]


def get_connections_from_db():
    """Последние события подключений/отключений (для линий). Из PG (real-time)."""
    rows = pg_query("""
        SELECT
            c.player_id,
            c.server_id,
            c.event_type,
            p.lat AS player_lat,
            p.lon AS player_lon,
            EXTRACT(EPOCH FROM c.event_time)::bigint AS ts
        FROM match_telemetry c
        JOIN LATERAL (
            SELECT lat, lon
            FROM match_telemetry
            WHERE player_id = c.player_id
              AND lat IS NOT NULL
              AND lon IS NOT NULL
              AND lat BETWEEN -90 AND 90
              AND lon BETWEEN -180 AND 180
            ORDER BY event_time DESC
            LIMIT 1
        ) p ON true
        WHERE c.event_type IN ('player_connected', 'player_disconnected')
          AND c.event_time > (SELECT MAX(event_time) FROM match_telemetry) - INTERVAL '2 minutes'
          AND c.player_id IS NOT NULL
          AND c.server_id IS NOT NULL
          AND c.server_id != ''
        ORDER BY c.event_time DESC
        LIMIT 50
    """)

    connections = []
    for r in rows:
        sid = r.get('server_id', '')
        if sid not in SERVER_COORDS:
            continue
        slat, slon = SERVER_COORDS[sid]
        try:
            plat = float(r['player_lat'])
            plon = float(r['player_lon'])
        except (TypeError, ValueError):
            continue
        if plat == 0.0 and plon == 0.0:
            continue
        connections.append({
            'player_id': r['player_id'][:8],
            'server_id': sid,
            'type': 'connect' if r['event_type'] == 'player_connected' else 'disconnect',
            'player_lat': plat,
            'player_lon': plon,
            'server_lat': slat,
            'server_lon': slon,
            'ts': int(r['ts']),
        })
    return connections


HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Cloud-Lab Visualizer | Real Data + Connections</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        html, body { margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; background: #000; }
        #map { height: 70vh; width: 100%; background: #000; }
        #dashboard {
            height: 30vh; overflow-y: auto;
            background: #0a0a14; color: #eee;
            padding: 12px 20px;
            font-family: 'Consolas', monospace;
            font-size: 13px;
            box-sizing: border-box;
            border-top: 1px solid #222;
        }
        .metric {
            display: inline-block; margin: 5px 15px 5px 0;
            padding: 8px 14px; background: #16213e;
            border-radius: 6px; border-left: 3px solid #00d2ff;
        }
        .metric .value { color: #00d2ff; font-weight: bold; margin-left: 6px; }
        .metric.nft { border-left-color: #ff6b6b; }
        .metric.nft .value { color: #ff6b6b; }
        .metric.servers { border-left-color: #ff4444; }
        .metric.servers .value { color: #ff4444; }
        .metric.sensors { border-left-color: #ffd93d; }
        .metric.sensors .value { color: #ffd93d; }
        h3 { margin: 0 0 10px 0; color: #00d2ff; }
        #logs { margin-top: 10px; max-height: 120px; overflow-y: auto; color: #888; line-height: 1.6; }
        #status {
            position: absolute; top: 10px; right: 10px; z-index: 1000;
            padding: 6px 12px; background: rgba(0,0,0,0.8); color: #0f0;
            border-radius: 4px; font-family: monospace; font-size: 12px;
        }
        #status.disconnected { color: #f00; }
    </style>
</head>
<body>
    <div id="status" class="disconnected">Connecting...</div>
    <div id="map"></div>
    <div id="dashboard">
        <h3>Live Metrics (REAL DATA + Connections)</h3>
        <div id="metrics">
            <div class="metric">Players: <span class="value">0</span></div>
            <div class="metric servers">Servers: <span class="value">0</span></div>
            <div class="metric sensors">Sensors: <span class="value">0</span></div>
            <div class="metric nft">NFT Txs: <span class="value">0</span></div>
        </div>
        <div id="logs"></div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.0/socket.io.min.js"></script>

    <script>
        var map = L.map('map', { worldCopyJump: true, minZoom: 2 }).setView([30, 20], 2);

        L.tileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
            { attribution: 'Tiles Esri', maxZoom: 16 }
        ).addTo(map);

        var markers = {};
        var connections = {};
        var socket = io({ reconnection: true, reconnectionDelay: 1000 });
        var statusEl = document.getElementById('status');

        socket.on('connect', function() {
            statusEl.textContent = 'Connected';
            statusEl.classList.remove('disconnected');
        });
        socket.on('disconnect', function() {
            statusEl.textContent = 'Disconnected';
            statusEl.classList.add('disconnected');
        });

        // === Изогнутая линия (квадратичная кривая Безье) ===
        function curvedLine(from, to) {
            var midLat = (from[0] + to[0]) / 2;
            var midLon = (from[1] + to[1]) / 2;
            var dLat = to[0] - from[0];
            var dLon = to[1] - from[1];
            var dist = Math.sqrt(dLat * dLat + dLon * dLon) || 1;
            var offset = dist * 0.2;
            var ctrlLat = midLat + (dLon / dist) * offset;
            var ctrlLon = midLon - (dLat / dist) * offset;

            var points = [];
            for (var i = 0; i <= 20; i++) {
                var t = i / 20;
                var lat = (1-t)*(1-t)*from[0] + 2*(1-t)*t*ctrlLat + t*t*to[0];
                var lon = (1-t)*(1-t)*from[1] + 2*(1-t)*t*ctrlLon + t*t*to[1];
                points.push([lat, lon]);
            }
            return points;
        }

        // === Рисуем анимированную линию ===
        function drawConnection(conn) {
            var key = conn.player_id + '_' + conn.server_id + '_' + conn.ts;

            // Пропускаем уже нарисованные
            if (connections[key]) return;

            var points = curvedLine(
                [conn.player_lat, conn.player_lon],
                [conn.server_lat, conn.server_lon]
            );

            var color = conn.type === 'disconnect' ? '#ff4444' : '#00ff88';
            var dashArray = conn.type === 'disconnect' ? '4, 8' : '10, 6';

            var polyline = L.polyline(points, {
                color: color,
                weight: 2,
                opacity: 0.9,
                dashArray: dashArray,
                lineCap: 'round',
                className: 'animated-line'
            }).addTo(map);

            connections[key] = { polyline: polyline, createdAt: Date.now() };

            // Автоудаление через 5 секунд
            var ttl = conn.type === 'disconnect' ? 3000 : 5000;
            setTimeout(function() {
                if (connections[key]) {
                    map.removeLayer(connections[key].polyline);
                    delete connections[key];
                }
            }, ttl);
        }

        // === CSS-анимация пунктира ===
        var style = document.createElement('style');
        style.innerHTML = `
            @keyframes dash {
                to { stroke-dashoffset: -30; }
            }
            .animated-line {
                animation: dash 1s linear infinite;
            }
        `;
        document.head.appendChild(style);

        socket.on('update', function(data) {
            // === Игроки: добавляем новых, удаляем пропавших ===
            var seenPlayers = {};
            if (data.players) {
                data.players.forEach(function(p) {
                    var key = 'p_' + p.id;
                    seenPlayers[key] = true;
                    if (!markers[key]) {
                        markers[key] = L.circleMarker([p.lat, p.lon], {
                            color: '#00d2ff', fillColor: '#00d2ff',
                            fillOpacity: 0.9, radius: 5
                        }).addTo(map).bindPopup('Player ' + p.id);
                    }
                });
            }
            for (var key in markers) {
                if (key.indexOf('p_') === 0 && !seenPlayers[key]) {
                    map.removeLayer(markers[key]);
                    delete markers[key];
                }
            }

            // === Серверы: один раз, не пересоздаём ===
            var seenServers = {};
            if (data.servers) {
                data.servers.forEach(function(s) {
                    var key = 's_' + s.id;
                    seenServers[key] = true;
                    if (!markers[key]) {
                        markers[key] = L.circleMarker([s.lat, s.lon], {
                            color: '#ff4444', fillColor: '#ff4444',
                            fillOpacity: 0.6, radius: 10
                        }).addTo(map).bindPopup('Server ' + s.id);
                    }
                });
            }
            for (var key in markers) {
                if (key.indexOf('s_') === 0 && !seenServers[key]) {
                    map.removeLayer(markers[key]);
                    delete markers[key];
                }
            }

            // === Сенсоры: аналогично ===
            var seenSensors = {};
            if (data.sensors) {
                data.sensors.forEach(function(s) {
                    var key = 'c_' + s.id;
                    seenSensors[key] = true;
                    if (!markers[key]) {
                        markers[key] = L.circleMarker([s.lat, s.lon], {
                            color: '#ffd93d', fillColor: '#ffd93d',
                            fillOpacity: 0.7, radius: 6
                        }).addTo(map).bindPopup(s.id + ': ' + s.value + ' ' + s.unit);
                    }
                });
            }
            for (var key in markers) {
                if (key.indexOf('c_') === 0 && !seenSensors[key]) {
                    map.removeLayer(markers[key]);
                    delete markers[key];
                }
            }

            // === Линии подключений ===
            if (data.connections) {
                data.connections.forEach(drawConnection);
            }

            // === Метрики ===
            if (data.stats) {
                document.getElementById('metrics').innerHTML =
                    '<div class="metric">Players: <span class="value">' + data.stats.players + '</span></div>' +
                    '<div class="metric servers">Servers: <span class="value">' + data.stats.servers + '</span></div>' +
                    '<div class="metric sensors">Sensors: <span class="value">' + data.stats.sensors + '</span></div>' +
                    '<div class="metric nft">NFT Txs: <span class="value">' + data.stats.nft_tx + '</span></div>';
            }

            // === Логи ===
            if (data.logs) {
                document.getElementById('logs').innerHTML = data.logs.map(function(l) {
                    return '<div>' + l + '</div>';
                }).join('');
            }
        });
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML)


def _safe_call(name, fn, default):
    try:
        return fn()
    except Exception as e:
        import traceback
        print(f"❌ [{name}] {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        return default


def background_thread():
    print("🔄 Background thread started (REAL DATA + Connections)")
    while True:
        try:
            players = _safe_call("get_players_from_db", get_players_from_db, [])
            servers = _safe_call("get_servers", get_servers, [])
            sensors = _safe_call("get_sensors_from_db", get_sensors_from_db, [])
            nft_count = _safe_call("get_nft_tx_count", get_nft_tx_count, 0)
            logs = _safe_call("get_recent_logs", get_recent_logs, [])
            connections = _safe_call("get_connections_from_db", get_connections_from_db, [])

            print(f"✅ tick: players={len(players)} servers={len(servers)} sensors={len(sensors)} conns={len(connections)} nft={nft_count}", flush=True)

            socketio.emit('update', {
                'players': players,
                'servers': servers,
                'sensors': sensors,
                'connections': connections,
                'stats': {
                    'players': len(players),
                    'servers': len(servers),
                    'sensors': len(sensors),
                    'nft_tx': nft_count,
                },
                'logs': logs,
            })
        except Exception as e:
            print(f"❌ Background error: {e}")

        time.sleep(2)


if __name__ == '__main__':
    threading.Thread(target=background_thread, daemon=True).start()
    print("🚀 Visualizer (REAL DATA + Connections) on http://0.0.0.0:5000")
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True, debug=False)

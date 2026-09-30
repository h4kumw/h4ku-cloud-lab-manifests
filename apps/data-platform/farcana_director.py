"""Farcana симулятор — пишет только в PostgreSQL (OLTP)."""
import time
import uuid
import random
import psycopg2
from config import PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB


class FarcanaSimulator:
    HOTSPOTS = [
        (40.7, -74.0), (51.5, -0.1), (35.7, 139.7), (1.35, 103.8),
        (-33.9, 151.2), (55.7, 37.6), (52.5, 13.4), (48.9, 2.35),
        (-23.5, -46.6), (19.4, -99.1), (28.6, 77.2), (-1.3, 36.8),
        (37.6, 127.0), (25.0, 121.5), (13.7, 100.5), (22.3, 114.2),
        (30.0, 31.2), (-26.2, 28.0), (43.7, -79.4), (41.9, 12.5),
    ]

    SERVERS = [
        (52.5, 13.4, 'srv_eu_1'),
        (40.7, -74.0, 'srv_us_1'),
        (1.35, 103.8, 'srv_asia_1'),
        (35.7, 139.7, 'srv_jp_1'),
        (-33.9, 151.2, 'srv_au_1'),
    ]

    def __init__(self):
        self.pg_conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, user=PG_USER,
            password=PG_PASSWORD, database=PG_DB
        )

    def generate_player(self):
        base_lat, base_lon = random.choice(self.HOTSPOTS)
        return {
            "player_id": str(uuid.uuid4()),
            "nickname": f"Player_{random.randint(1, 1000)}",
            "skill_level": random.randint(1, 100),
            "lat": base_lat + random.uniform(-2, 2),
            "lon": base_lon + random.uniform(-2, 2),
        }

    def find_nearest_server(self, lat, lon):
        return min(self.SERVERS, key=lambda s: (s[0] - lat) ** 2 + (s[1] - lon) ** 2)

    def create_match(self, players):
        match_id = str(uuid.uuid4())
        cursor = self.pg_conn.cursor()

        cursor.execute(
            "INSERT INTO matches (match_id, status, region) VALUES (%s, %s, %s)",
            (match_id, 'pending', 'EU')
        )

        for p in players[:2]:
            cursor.execute(
                "INSERT INTO players (player_id, nickname, skill_level) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (p['player_id'], p['nickname'], p['skill_level'])
            )
            cursor.execute(
                "INSERT INTO match_players (match_id, player_id) VALUES (%s, %s)",
                (match_id, p['player_id'])
            )

        # Телеметрия — только в PostgreSQL (OLTP). Airflow потом зальёт в CH.
        for p in players[:2]:
            server = self.find_nearest_server(p['lat'], p['lon'])
            server_id = server[2]

            cursor.execute("""
                INSERT INTO match_telemetry 
                    (match_id, player_id, event_type, lat, lon, ping, server_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (match_id, p['player_id'], 'player_connected', p['lat'], p['lon'], 0, server_id))

            if random.random() < 0.2:
                cursor.execute("""
                    INSERT INTO match_telemetry 
                        (match_id, player_id, event_type, lat, lon, ping, server_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (match_id, p['player_id'], 'player_disconnected', p['lat'], p['lon'], 0, server_id))

        self.pg_conn.commit()
        print(f"[FARCANA] Match {match_id} created with {len(players[:2])} players (PG only)")
        return match_id

    def run(self):
        queue = []
        while True:
            new_players = [self.generate_player() for _ in range(random.randint(1, 3))]
            queue.extend(new_players)

            if len(queue) >= 2:
                match_players = queue[:2]
                queue = queue[2:]
                self.create_match(match_players)

            time.sleep(2)


if __name__ == "__main__":
    sim = FarcanaSimulator()
    sim.run()

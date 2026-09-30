"""Chimeras симулятор — пишет только в PostgreSQL (OLTP)."""
import random
import time
import uuid
import psycopg2
from config import PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB


class ChimerasSimulator:
    def __init__(self):
        self.pg_conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, user=PG_USER,
            password=PG_PASSWORD, database=PG_DB
        )

    def generate_nft_transaction(self):
        return {
            "tx_hash": f"0x{''.join(random.choices('0123456789abcdef', k=64))}",
            "nft_id": f"CHIM_{random.randint(1, 10000)}",
            "from_address": f"0x{''.join(random.choices('0123456789abcdef', k=40))}",
            "to_address": f"0x{''.join(random.choices('0123456789abcdef', k=40))}",
            "price": random.uniform(10, 1000),
        }

    def save_to_postgres(self, tx):
        cursor = self.pg_conn.cursor()
        cursor.execute("""
            INSERT INTO nft_transactions 
                (tx_hash, nft_id, from_address, to_address, price)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tx_hash) DO NOTHING
        """, (
            tx["tx_hash"], tx["nft_id"],
            tx["from_address"], tx["to_address"], tx["price"],
        ))
        self.pg_conn.commit()

    def run(self):
        while True:
            for _ in range(random.randint(1, 5)):
                tx = self.generate_nft_transaction()
                self.save_to_postgres(tx)
                print(f"[CHIMERAS] NFT tx {tx['tx_hash'][:10]} recorded (PG only)")
            time.sleep(10)


if __name__ == "__main__":
    sim = ChimerasSimulator()
    sim.run()

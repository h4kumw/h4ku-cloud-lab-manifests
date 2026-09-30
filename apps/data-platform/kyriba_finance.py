"""Kyriba симулятор — XML в MinIO, метаданные в PostgreSQL (OLTP)."""
import xml.etree.ElementTree as ET
import random
import time
import boto3
import psycopg2
from config import (
    MINIO_ENDPOINT, MINIO_USER, MINIO_PASSWORD,
    PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DB,
)
from datetime import datetime


class KyribaSimulator:
    def __init__(self):
        # MinIO для XML-выписок
        self.s3_client = boto3.client(
            's3',
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_USER,
            aws_secret_access_key=MINIO_PASSWORD,
        )
        self.bucket = 'fin-reports'

        # PostgreSQL для метаданных
        self.pg_conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, user=PG_USER,
            password=PG_PASSWORD, database=PG_DB,
        )

        try:
            self.s3_client.create_bucket(Bucket=self.bucket)
        except Exception:
            pass

    def generate_bank_statement(self):
        root = ET.Element("BankStatement")
        ET.SubElement(root, "Date").text = datetime.now().strftime("%Y-%m-%d")
        bank_code = f"BANK{random.randint(100, 999)}"
        ET.SubElement(root, "BankCode").text = bank_code

        transactions = ET.SubElement(root, "Transactions")
        total = 0.0
        tx_count = random.randint(5, 20)
        for _ in range(tx_count):
            tx = ET.SubElement(transactions, "Transaction")
            amount = random.uniform(-10000, 10000)
            ET.SubElement(tx, "Amount").text = str(round(amount, 2))
            ET.SubElement(tx, "Currency").text = random.choice(["USD", "EUR", "BYN"])
            ET.SubElement(tx, "Counterparty").text = f"CP_{random.randint(1, 100)}"
            total += amount

        xml_str = ET.tostring(root, encoding='unicode')

        # 1. XML в MinIO (S3)
        key = f"statements/{datetime.now().strftime('%Y/%m/%d')}/bank_{random.randint(1, 999)}.xml"
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=xml_str.encode('utf-8'),
        )

        # 2. Метаданные в PostgreSQL (OLTP)
        cursor = self.pg_conn.cursor()
        cursor.execute("""
            INSERT INTO bank_statements 
                (statement_date, bank_code, total_amount)
            VALUES (%s, %s, %s)
        """, (
            datetime.now().date(),
            bank_code,
            round(total, 2),
        ))
        self.pg_conn.commit()

        print(f"[KYRIBA] Statement uploaded: {key}, total: {round(total, 2)} (MinIO + PG only)")
        return xml_str

    def run(self):
        while True:
            self.generate_bank_statement()
            time.sleep(random.randint(30, 60))


if __name__ == "__main__":
    sim = KyribaSimulator()
    sim.run()

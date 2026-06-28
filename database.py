import os
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()


def get_database_connection():
    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            ssl_ca=os.getenv("DB_SSL_CA"),
            ssl_verify_cert=True,
            ssl_verify_identity=True,
        )

        print("Connected to TiDB Cloud")

        return connection

    except Error as e:
        print(e)
        return None

if __name__ == "__main__":

    conn = get_database_connection()

    if conn:
        cursor = conn.cursor()

        cursor.execute("SHOW TABLES")

        for table in cursor.fetchall():
            print(table)

        cursor.close()
        conn.close()
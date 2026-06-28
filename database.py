import os
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()


def get_database_connection():
    try:
        ssl_ca_path = os.getenv("DB_SSL_CA")
        
        # Fallback for Linux (Render) and Mac if the env var is missing or wrong
        if not ssl_ca_path or not os.path.exists(ssl_ca_path):
            if os.path.exists("/etc/ssl/certs/ca-certificates.crt"):
                ssl_ca_path = "/etc/ssl/certs/ca-certificates.crt"  # Render/Ubuntu
            elif os.path.exists("/etc/pki/tls/certs/ca-bundle.crt"):
                ssl_ca_path = "/etc/pki/tls/certs/ca-bundle.crt"     # Amazon Linux/CentOS
            else:
                ssl_ca_path = "/etc/ssl/cert.pem"                    # macOS / Default

        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT") or 4000),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            ssl_ca=ssl_ca_path,
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
        conn.close()§
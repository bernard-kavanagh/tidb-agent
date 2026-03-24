"""
One-time setup: verifies TiDB Cloud connectivity and applies the schema.

Usage:
  python setup.py

Prerequisites:
  1. Create a TiDB Cloud Serverless cluster at https://tidbcloud.com
  2. Copy your connection string into .env as TIDB_CONNECTION_STRING
     Format: mysql://USER:PASSWORD@HOST:4000/tidb_leads?ssl_verify_cert=true
  3. Run this script — it will verify connectivity and apply schema.sql
"""
import subprocess
import sys
import os


def run(cmd: list[str], capture: bool = False):
    return subprocess.run(
        cmd, capture_output=capture, text=True,
        cwd=os.path.dirname(__file__) or '.'
    )


def parse_dsn(dsn: str) -> dict:
    from urllib.parse import urlparse
    u = urlparse(dsn)
    return {
        'host':     u.hostname,
        'port':     str(u.port or 4000),
        'user':     u.username,
        'password': u.password or '',
    }


def main():
    print("── TiDB Cloud Lead Agent Setup ──\n")

    # Load .env
    env_path = os.path.join(os.path.dirname(__file__) or '.', '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    os.environ.setdefault(k.strip(), v.strip())

    conn_str = os.environ.get('TIDB_CONNECTION_STRING', '')
    api_key  = os.environ.get('ANTHROPIC_API_KEY', '')

    if not conn_str:
        print("❌  TIDB_CONNECTION_STRING not set in .env")
        print("   Format: mysql://USER:PASSWORD@HOST:4000/tidb_leads?ssl_verify_cert=true")
        print("   Get it from: TiDB Cloud console → Connect → Python/MySQL tab")
        sys.exit(1)

    if not api_key:
        print("⚠️   ANTHROPIC_API_KEY not set in .env — agent analysis will fail")

    # 1. Verify DB connectivity
    print("🔌  Verifying TiDB Cloud connection...")
    try:
        import certifi, pymysql
        from urllib.parse import urlparse, parse_qs
        u   = urlparse(conn_str)
        conn = pymysql.connect(
            host=u.hostname,
            port=u.port or 4000,
            user=u.username,
            password=u.password or '',
            database=u.path.lstrip('/') or 'tidb_leads',
            ssl={'ca': certifi.where()},
            connect_timeout=10,
        )
        conn.close()
        print("✅  Connected to TiDB Cloud")
    except ImportError:
        print("⚠️   pymysql/certifi not installed — run: pip install -r requirements.txt")
        print("    Skipping connectivity check.")
    except Exception as e:
        print(f"❌  Connection failed: {e}")
        print("    Check TIDB_CONNECTION_STRING in .env")
        sys.exit(1)

    # 2. Apply schema via mysql CLI
    print("\n📐  Applying schema (schema.sql)...")
    dsn = parse_dsn(conn_str)
    schema_path = os.path.join(os.path.dirname(__file__) or '.', 'schema.sql')

    mysql_cmd = [
        'mysql',
        '-h', dsn['host'],
        '-P', dsn['port'],
        '-u', dsn['user'],
        f"-p{dsn['password']}",
        '--ssl-mode=REQUIRED',
    ]

    try:
        with open(schema_path) as f:
            result = subprocess.run(mysql_cmd, stdin=f, capture_output=True, text=True)
        if result.returncode == 0:
            print("✅  Schema applied")
        else:
            print(f"⚠️   mysql returned: {result.stderr.strip()}")
            print("    You can also paste schema.sql directly into the TiDB Cloud SQL editor.")
    except FileNotFoundError:
        print("⚠️   mysql CLI not found — apply schema.sql manually via the TiDB Cloud SQL editor")

    # 3. Summary
    print("\n── Next steps ──────────────────────────────────────────────")
    print("1. Install deps:      pip install -r requirements.txt")
    print("2. Run agent:         python -m agent.run --region 'Western Europe'")
    print("3. Run dashboard:     uvicorn dashboard.main:app --reload --port 8000")
    print("   Then open:         http://localhost:8000")
    print("4. Generate pitch doc: node generate_pitch_doc.js")
    print("────────────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    main()

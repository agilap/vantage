from pathlib import Path

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

import config


_pool: ThreadedConnectionPool | None = None


def get_pool() -> ThreadedConnectionPool:
	"""Return a singleton ThreadedConnectionPool for runtime queries."""
	global _pool
	if _pool is None:
		_pool = ThreadedConnectionPool(
			minconn=int(config.POOL_MIN),
			maxconn=int(config.POOL_MAX),
			dsn=config.DATABASE_URL,
		)
	return _pool


def get_connection():
	"""Acquire a connection from the runtime pool."""
	return get_pool().getconn()


def release_connection(conn) -> None:
	"""Return a connection to the runtime pool."""
	get_pool().putconn(conn)


def init_db() -> None:
	"""Create schema objects using the direct Supabase connection."""
	schema_path = Path(__file__).resolve().parent / "schema.sql"
	schema_sql = schema_path.read_text(encoding="utf-8")

	conn = psycopg2.connect(dsn=config.DATABASE_DIRECT_URL)
	try:
		with conn.cursor() as cur:
			cur.execute(schema_sql)
		conn.commit()
	finally:
		conn.close()


# Example usage pattern for pool-based callers:
# conn = get_connection()
# try:
#     with conn.cursor() as cur:
#         cur.execute("SELECT 1")
# finally:
#     release_connection(conn)


if __name__ == "__main__":
	init_db()
	print("Schema initialized.")

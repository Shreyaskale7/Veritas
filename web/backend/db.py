import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://veritas_login:veritas@127.0.0.1:5432/veritas"
)
ADMIN_DATABASE_URL = os.environ.get(
    "ADMIN_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/veritas"
)

app_pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, kwargs={"row_factory": dict_row, "autocommit": False})
admin_pool = ConnectionPool(ADMIN_DATABASE_URL, min_size=1, max_size=4, kwargs={"row_factory": dict_row, "autocommit": False})


@contextmanager
def app_conn(user_id: int | None):
    with app_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET ROLE veritas_app")
            cur.execute("SELECT set_config('veritas.user_id', %s, false)", (str(user_id) if user_id is not None else "",))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


@contextmanager
def admin_conn():
    with admin_pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def fetchall(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def fetchone(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def execute(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        if cur.description:
            return cur.fetchall()
        return []

import os
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings import _database_from_env

KEYS = ["DB_ENGINE", "DATABASE_URL", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_SSLMODE", "SQLITE_NAME", "DB_CONN_MAX_AGE"]


def env(**kw):
    clean = {k: v for k, v in os.environ.items() if k not in KEYS}
    clean.update(kw)
    return mock.patch.dict(os.environ, clean, clear=True)


class DatabaseSwitchTests(SimpleTestCase):
    def test_default_is_sqlite(self):
        with env():
            cfg = _database_from_env()
        self.assertEqual(cfg["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(cfg["NAME"].name, "db.sqlite3")

    def test_postgres_from_individual_variables(self):
        with env(DB_ENGINE="postgres", DB_NAME="hv", DB_USER="u", DB_PASSWORD="p", DB_HOST="db", DB_PORT="6543", DB_SSLMODE="require"):
            cfg = _database_from_env()
        self.assertEqual(cfg["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual((cfg["NAME"], cfg["USER"], cfg["PASSWORD"], cfg["HOST"], cfg["PORT"]), ("hv", "u", "p", "db", "6543"))
        self.assertEqual(cfg["OPTIONS"], {"sslmode": "require"})

    def test_postgres_from_database_url(self):
        with env(DATABASE_URL="postgres://alice:s%40crt@pg.internal:5433/vision"):
            cfg = _database_from_env()
        self.assertEqual((cfg["USER"], cfg["PASSWORD"], cfg["HOST"], cfg["PORT"], cfg["NAME"]), ("alice", "s@crt", "pg.internal", "5433", "vision"))

    def test_unknown_engine_fails_loudly(self):
        with env(DB_ENGINE="oracle"):
            with self.assertRaises(ImproperlyConfigured):
                _database_from_env()

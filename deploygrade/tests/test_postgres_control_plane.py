"""Optional integration coverage for the managed PostgreSQL control plane.

Set ``DATABASE_URL`` to an isolated database after
applying ``0001`` and ``0002`` migrations.  The test is intentionally skipped
only when that URL is absent; a configured database missing psycopg, migrations,
or RLS policy fails loudly rather than producing a false green result.
"""
import os
import uuid
import unittest

from deploygrade.engine.postgres_control_plane import PostgresControlPlaneStore


@unittest.skipUnless(os.environ.get("DATABASE_URL"), "managed PostgreSQL integration URL is not configured")
class PostgresControlPlaneIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgresControlPlaneStore(os.environ["DATABASE_URL"])
        suffix = uuid.uuid4().hex
        self.org_a, self.org_b = f"pg-a-{suffix}", f"pg-b-{suffix}"
        self.engagement_a = f"eng-a-{suffix}"
        self.store.create_organization(self.org_a)
        self.store.create_organization(self.org_b)
        self.store.create_engagement(self.org_a, self.engagement_a, "healthcare")

    def tearDown(self):
        # RLS context is set independently for each tenant before cleanup.  The
        # cascade proves no test data is retained when the integration suite is
        # pointed at its dedicated ephemeral database.
        for organization_id in (self.org_a, self.org_b):
            with self.store._transaction(organization_id) as cursor:
                cursor.execute("DELETE FROM deploygrade.organizations WHERE id=%s", (organization_id,))
        self.store.close()

    def test_database_is_ready_and_tenant_rows_are_not_cross_readable(self):
        self.assertEqual(self.store.readiness(), {"backend": "postgresql", "durable": True, "ready": True})
        artifact = {"$schema": "../schemas/api_error.schema.json", "schema_version": "1.0", "error": "safe"}
        digest = self.store.store_artifact(self.org_a, self.engagement_a, artifact)
        with self.assertRaisesRegex(ValueError, "tenant-scoped engagement"):
            self.store.store_artifact(self.org_b, self.engagement_a, artifact)
        with self.store._transaction(self.org_b) as cursor:
            cursor.execute("SELECT count(*) AS count FROM deploygrade.artifacts WHERE hash=%s", (digest,))
            self.assertEqual(cursor.fetchone()["count"], 0)


if __name__ == "__main__":
    unittest.main()

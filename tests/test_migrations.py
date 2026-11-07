"""Every migration is deleted by its remove_by month: past that, this test fails."""

from datetime import date
import re
import unittest

import omadotfile.cli  # noqa: F401  (imports every module, so every migration registers)
from omadotfile.migration import MIGRATIONS, Migration, migration

MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


class MigrationTests(unittest.TestCase):
    def test_no_migration_is_past_its_remove_by_month(self):
        this_month = date.today().strftime("%Y-%m")
        for entry in MIGRATIONS:
            with self.subTest(migration=entry.name):
                self.assertLess(this_month, entry.remove_by,
                                f"{entry.name} ({entry.reason}) was due for removal in "
                                f"{entry.remove_by}: delete it, or move remove_by if some "
                                "machine may still need it")

    def test_dates_are_months_and_removal_comes_after_adding(self):
        for entry in MIGRATIONS:
            with self.subTest(migration=entry.name):
                self.assertRegex(entry.since, MONTH)
                self.assertRegex(entry.remove_by, MONTH)
                self.assertLess(entry.since, entry.remove_by)
                self.assertTrue(entry.reason.strip())

    def test_each_migration_registers_once(self):
        names = [entry.name for entry in MIGRATIONS]
        self.assertEqual(len(names), len(set(names)))

    def test_decorator_registers_and_returns_the_function_unchanged(self):
        before = list(MIGRATIONS)
        try:
            def cleanup(value):
                return value * 2

            decorated = migration(since="2026-01", reason="test", remove_by="2027-01")(cleanup)
            self.assertIs(decorated, cleanup)
            self.assertEqual(MIGRATIONS[-1], Migration(f"{__name__}.{cleanup.__qualname__}",
                                                       "2026-01", "test", "2027-01"))
        finally:
            MIGRATIONS[:] = before


if __name__ == "__main__":
    unittest.main()

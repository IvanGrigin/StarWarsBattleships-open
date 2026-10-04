"""Tests for the repository's AI commit-message contract."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_commit_message import validate  # noqa: E402


GOOD = """v0.4.1.00001/Codex: объединена базовая версия

Время: 2026-09-23T12:30:00+02:00
Что: Объединены ветки и сохранены данные.
Почему: Нужна воспроизводимая точка старта.
"""


class CommitPolicyTests(unittest.TestCase):
    def test_accepts_complete_message(self):
        self.assertEqual(validate(GOOD, previous=0), ("0.4.1", 1))

    def test_requires_next_sequence(self):
        with self.assertRaisesRegex(ValueError, "должен быть 00002"):
            validate(GOOD, previous=1)

    def test_requires_reason(self):
        with self.assertRaisesRegex(ValueError, "Почему"):
            validate(GOOD.replace("Почему: Нужна воспроизводимая точка старта.\n", ""))

    def test_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "Время"):
            validate(GOOD.replace("+02:00", ""))

    def test_rejects_unknown_worker(self):
        with self.assertRaisesRegex(ValueError, "тема должна"):
            validate(GOOD.replace("/Codex:", "/Other:"))


if __name__ == "__main__":
    unittest.main()

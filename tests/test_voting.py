import unittest

from datetime import datetime, timedelta

from config import UFA_TZ
from src.bot.handlers.voting_admin import _parse_candidates
from src.bot.keyboards.user import main_menu
from src.database.models import Voting


class VotingTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 9, 10, 12, 0, tzinfo=UFA_TZ)
        self.end = datetime(2026, 9, 20, 20, 0, tzinfo=UFA_TZ)
        self.voting = Voting(
            name="Лучший админ",
            starts_at=self.start,
            ends_at=self.end,
            active=True,
        )

    def test_first_votes_remain_available_during_final_three_days(self) -> None:
        now = self.end - timedelta(days=1)
        self.assertTrue(self.voting.accepts_votes(now))
        self.assertFalse(self.voting.allows_changes(now))

    def test_changes_lock_exactly_three_days_before_end(self) -> None:
        deadline = self.end - timedelta(days=3)
        self.assertTrue(self.voting.allows_changes(deadline - timedelta(seconds=1)))
        self.assertFalse(self.voting.allows_changes(deadline))

    def test_no_votes_after_end(self) -> None:
        self.assertFalse(self.voting.accepts_votes(self.end))


class CandidateInputTests(unittest.TestCase):
    def test_exactly_five_candidates_with_optional_descriptions(self) -> None:
        parsed = _parse_candidates("Маруна | Описание\nИся\nАнна\nОлег\nСаша")
        self.assertEqual(len(parsed), 5)
        self.assertEqual(parsed[0], ("Маруна", "Описание"))
        self.assertEqual(parsed[1], ("Ися", None))

    def test_duplicate_names_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _parse_candidates("Маруна\nмаруна\nАнна\nОлег\nСаша")


class VotingMainMenuTests(unittest.TestCase):
    def test_active_voting_is_available_from_main_menu(self) -> None:
        voting = Voting(id=2, name="Лучший админ", starts_at=datetime.now(tz=UFA_TZ), ends_at=datetime.now(tz=UFA_TZ) + timedelta(days=5))
        keyboard = main_menu([], [voting])
        button = keyboard.inline_keyboard[0][0]
        self.assertEqual(button.text, "🏆 Лучший админ")
        self.assertEqual(button.callback_data, "vote:open:2")

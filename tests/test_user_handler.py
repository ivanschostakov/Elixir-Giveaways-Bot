import ast
import unittest

from pathlib import Path


USER_HANDLER_PATH = Path(__file__).resolve().parents[1] / "src" / "helpers" / "user_handler.py"


class UserHandlerSourceTests(unittest.TestCase):
    def test_referral_confirmation_uses_ref_participant_id_in_check_context(self) -> None:
        module = ast.parse(USER_HANDLER_PATH.read_text(encoding="utf-8"))

        for node in module.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_confirm_ref_join_callback":
                for stmt in ast.walk(node):
                    if not isinstance(stmt, ast.Assign):
                        continue
                    if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name) or stmt.targets[0].id != "check_context":
                        continue
                    self.assertIsInstance(stmt.value, ast.Dict)
                    mapping = {
                        key.value: value
                        for key, value in zip(stmt.value.keys, stmt.value.values)
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    }
                    participant_value = mapping.get("participant_id")
                    self.assertIsInstance(participant_value, ast.Attribute)
                    self.assertEqual(participant_value.attr, "id")
                    self.assertIsInstance(participant_value.value, ast.Name)
                    self.assertEqual(participant_value.value.id, "ref_participant")
                    return

        self.fail("check_context assignment was not found in handle_confirm_ref_join_callback")

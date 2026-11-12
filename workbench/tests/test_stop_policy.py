import copy
import json
import unittest
from pathlib import Path

from stop_policy import decide


_FIXTURE = Path(__file__).resolve().parent.parent.joinpath("fixtures", "scenarios.json")

_EXPECT_KEYS = (
    "action",
    "next_state",
    "reason_code",
    "data_at_risk",
    "notify_human",
    "human_hold_after",
    "stop_intent",
    "from_unit",
)

_OUTPUT_KEYS = frozenset(_EXPECT_KEYS + ("ui_message",))

_PROBE_FAILURE_IDS = ("T01", "T02", "T03", "T16", "U01")


def _load():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _apply(base, updates):
    root = copy.deepcopy(base)
    for path, value in updates.items():
        node = root
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = copy.deepcopy(value)
    return root


def _call(snapshot, contract, policy, now):
    try:
        return ("value", decide(snapshot, contract, policy, now))
    except ValueError as exc:
        if type(exc) is not ValueError:
            raise
        return ("raise", "ValueError")


class TestStopPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = _load()
        cls.by_id = {row["id"]: row for row in cls.doc["scenarios"]}

    def _built(self, row):
        return _apply(self.doc["base"], row["set"])

    def _row(self, row_id):
        return self.by_id[row_id]

    def _assert_decision(self, got, expect):
        self.assertEqual(set(got), set(_OUTPUT_KEYS))
        for key in _EXPECT_KEYS:
            wanted = expect[key]
            if isinstance(wanted, bool):
                self.assertIs(got[key], wanted)
            elif wanted is None:
                self.assertIsNone(got[key])
            elif isinstance(wanted, int):
                self.assertIsInstance(got[key], int)
                self.assertNotIsInstance(got[key], bool)
                self.assertEqual(got[key], wanted)
            else:
                self.assertEqual(got[key], wanted)
        self.assertIsInstance(got["ui_message"], str)
        self.assertNotEqual(got["ui_message"], "")

    def test_each_fixture_row(self):
        for row in self.doc["scenarios"]:
            with self.subTest(row["id"]):
                built = self._built(row)
                expect = row["expect"]
                if expect == {"raises": "ValueError"}:
                    with self.assertRaises(ValueError) as caught:
                        decide(
                            built["snapshot"],
                            built["contract"],
                            built["policy"],
                            built["now"],
                        )
                    self.assertIs(type(caught.exception), ValueError)
                    continue
                got = decide(
                    built["snapshot"],
                    built["contract"],
                    built["policy"],
                    built["now"],
                )
                self._assert_decision(got, expect)

    def test_probe_failure_group_does_not_release_or_finish(self):
        for row_id in _PROBE_FAILURE_IDS:
            with self.subTest(row_id):
                built = self._built(self._row(row_id))
                got = decide(
                    built["snapshot"],
                    built["contract"],
                    built["policy"],
                    built["now"],
                )
                self.assertNotIn(got["action"], ("RELEASE", "CLOSE"))
                self.assertNotEqual(got["next_state"], "DONE")

    def test_t12_human_hold_rejects_bot_resume(self):
        built = self._built(self._row("T12"))
        got = decide(
            built["snapshot"], built["contract"], built["policy"], built["now"],
        )
        self.assertEqual(got["action"], "REJECT_REQUEST")
        self.assertEqual(got["reason_code"], "HUMAN_HOLD")
        self.assertEqual(got["next_state"], "PAUSED")
        self.assertIs(got["human_hold_after"], True)

    def test_p02_human_command_beats_bot(self):
        built = self._built(self._row("P02"))
        got = decide(
            built["snapshot"], built["contract"], built["policy"], built["now"],
        )
        self.assertEqual(got["action"], "REQUEST_SAVE")
        self.assertEqual(got["next_state"], "SAVING")
        self.assertEqual(got["reason_code"], "HUMAN_STOP")
        self.assertIs(got["human_hold_after"], True)
        self.assertEqual(got["stop_intent"], "pause")

    def test_t08_mode_c_within_grace_does_not_release(self):
        row = self._row("T08")
        built = self._built(row)
        snap = built["snapshot"]
        cont = built["contract"]
        pol = built["policy"]
        cap = cont["cu_cap"]
        self.assertLess(snap["cu_used"], cap + (cap * pol["grace_cu_ratio"]))
        self.assertLess(built["now"] - snap["limit_hit_at"], pol["grace_minutes"])
        got = decide(snap, cont, pol, built["now"])
        self.assertNotEqual(got["action"], "RELEASE")
        self.assertNotEqual(got["action"], "CLOSE")
        self.assertEqual(got["action"], "REQUEST_SAVE")
        self.assertEqual(got["reason_code"], "CU_HARD_CAP_UNSAVED")

    def test_t09_releases_when_grace_cu_is_used_up(self):
        built = self._built(self._row("T09"))
        snap = built["snapshot"]
        cont = built["contract"]
        pol = built["policy"]
        cap = cont["cu_cap"]
        self.assertGreaterEqual(snap["cu_used"], cap + (cap * pol["grace_cu_ratio"]))
        self.assertLess(built["now"] - snap["limit_hit_at"], pol["grace_minutes"])
        got = decide(snap, cont, pol, built["now"])
        self.assertEqual(got["action"], "RELEASE")
        self.assertEqual(got["next_state"], "RELEASING")
        self.assertEqual(got["reason_code"], "CU_GRACE_EXHAUSTED")
        self.assertIs(got["data_at_risk"], True)
        self.assertIs(got["notify_human"], True)

    def test_t09b_releases_when_grace_minutes_arrive_first(self):
        built = self._built(self._row("T09b"))
        snap = built["snapshot"]
        cont = built["contract"]
        pol = built["policy"]
        cap = cont["cu_cap"]
        self.assertLess(snap["cu_used"], cap + (cap * pol["grace_cu_ratio"]))
        self.assertGreaterEqual(
            built["now"] - snap["limit_hit_at"], pol["grace_minutes"],
        )
        got = decide(snap, cont, pol, built["now"])
        self.assertEqual(got["action"], "RELEASE")
        self.assertEqual(got["next_state"], "RELEASING")
        self.assertEqual(got["reason_code"], "CU_GRACE_EXHAUSTED")
        self.assertIs(got["data_at_risk"], True)
        self.assertIs(got["notify_human"], True)

    def test_inputs_stay_unchanged(self):
        for row in self.doc["scenarios"]:
            with self.subTest(row["id"]):
                built = self._built(row)
                snap = built["snapshot"]
                cont = built["contract"]
                pol = built["policy"]
                now = built["now"]
                before = copy.deepcopy((snap, cont, pol))
                outcome = _call(snap, cont, pol, now)
                if row["expect"] == {"raises": "ValueError"}:
                    self.assertEqual(outcome, ("raise", "ValueError"))
                else:
                    self.assertEqual(outcome[0], "value")
                self.assertEqual((snap, cont, pol), before)

    def test_same_input_same_output(self):
        for row in self.doc["scenarios"]:
            with self.subTest(row["id"]):
                built = self._built(row)
                snap = built["snapshot"]
                cont = built["contract"]
                pol = built["policy"]
                now = built["now"]
                first = _call(snap, cont, pol, now)
                second = _call(snap, cont, pol, now)
                self.assertEqual(first, second)

    def test_queue_empty_does_not_change_decision(self):
        healthy = self._built(self._row("T05"))
        queued = self._built(self._row("T20"))
        got_healthy = decide(
            healthy["snapshot"], healthy["contract"], healthy["policy"], healthy["now"],
        )
        got_queued = decide(
            queued["snapshot"], queued["contract"], queued["policy"], queued["now"],
        )
        for key in _EXPECT_KEYS:
            self.assertEqual(got_queued[key], got_healthy[key])
        self.assertEqual(got_healthy["action"], "CONTINUE")
        self.assertEqual(got_healthy["reason_code"], "OK")

    def test_missing_required_key_raises_valueerror(self):
        built = copy.deepcopy(self.doc["base"])
        del built["snapshot"]["probe"]["status"]
        with self.assertRaises(ValueError) as caught:
            decide(
                built["snapshot"], built["contract"], built["policy"], built["now"],
            )
        self.assertIs(type(caught.exception), ValueError)


if __name__ == "__main__":
    unittest.main()

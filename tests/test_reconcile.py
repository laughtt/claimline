import unittest

from agent.reconcile import AGREED, CONFLICT, ONLY_A, ONLY_B, Fact, reconcile


def by_field(results):
    return {r.field: r for r in results}


class ReconcileTest(unittest.TestCase):
    def test_statuses(self):
        a = [Fact("signal_state", "Red", "A"), Fact("weather", "rain", "A"), Fact("lane", "left", "A")]
        b = [Fact("signal_state", "green", "B"), Fact("weather", " RAIN ", "B"), Fact("impact_point", "rear", "B")]
        r = by_field(reconcile(a, b))
        self.assertEqual(r["signal_state"].status, CONFLICT)
        self.assertEqual(r["weather"].status, AGREED)
        self.assertEqual(r["lane"].status, ONLY_A)
        self.assertEqual(r["impact_point"].status, ONLY_B)

    def test_speed_tolerance(self):
        r = by_field(reconcile([Fact("speed_kmh", "50", "A")], [Fact("speed_kmh", "58", "B")]))
        self.assertEqual(r["speed_kmh"].status, AGREED)
        r = by_field(reconcile([Fact("speed_kmh", "50", "A")], [Fact("speed_kmh", "80", "B")]))
        self.assertEqual(r["speed_kmh"].status, CONFLICT)

    def test_same_meaning_judge(self):
        judge = lambda field, a, b: {a, b} == {"rojo", "red"}
        r = by_field(reconcile([Fact("signal_state", "rojo", "A")], [Fact("signal_state", "red", "B")], judge))
        self.assertEqual(r["signal_state"].status, AGREED)

    def test_most_confident_value_wins(self):
        a = [Fact("lane", "left", "A", confidence=0.4), Fact("lane", "right", "A", confidence=0.9)]
        r = by_field(reconcile(a, [Fact("lane", "right", "B")]))
        self.assertEqual(r["lane"].status, AGREED)

    def test_evidence_is_kept(self):
        ev = [{"type": "voice", "s3": "media/c1/a/v1.ogg", "quote": "the light was red"}]
        r = by_field(reconcile([Fact("signal_state", "red", "A", evidence=ev)], []))
        self.assertEqual(r["signal_state"].evidence_a, ev)


if __name__ == "__main__":
    unittest.main()

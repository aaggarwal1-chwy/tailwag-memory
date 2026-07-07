import math
import unittest

from tailwag_memory.affect import AffectScoringConfigurationError, _hardsigmoid_values


class AffectScoringTest(unittest.TestCase):
    def test_hardsigmoid_values_match_upstream_bounded_output(self) -> None:
        scores = _hardsigmoid_values([-3.0, 0.0, 3.0, -2.62])

        self.assertEqual(scores[:3], [0.0, 0.5, 1.0])
        self.assertAlmostEqual(scores[3], 0.0633333333)

    def test_hardsigmoid_values_reject_non_finite_logits(self) -> None:
        with self.assertRaisesRegex(AffectScoringConfigurationError, "raw affect"):
            _hardsigmoid_values([math.nan])


if __name__ == "__main__":
    unittest.main()

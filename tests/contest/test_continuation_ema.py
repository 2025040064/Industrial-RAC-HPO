"""Continuation keeps the optimiser steps but averages the epoch-end weights.

The average is what makes a warm-start round actually move the public metric;
without it consecutive epochs oscillate and the acceptance gate rejects
everything. Classification keeps the original single-shot path.
"""
import unittest

import numpy as np

from rac_hpo.contest.continuation import EMA_DECAY, fit_epochs


class FakeModel:
    """Minimal stand-in exposing exactly what fit_epochs touches."""

    def __init__(self, task, start=0.0):
        self.meta = {"task": task, "epochs": 0, "seed": 42}
        self.params = {"w": np.array([start], dtype=float)}

    def fit(self, x, y, epochs):
        losses = []
        for _ in range(epochs):
            self.params["w"] = self.params["w"] + 1.0
            self.meta["epochs"] += 1
            losses.append(float(self.params["w"][0]))
        return losses


def expected_average(epochs, start=0.0):
    shadow = np.array([start], dtype=float)
    value = start
    for _ in range(epochs):
        value += 1.0
        shadow = EMA_DECAY * shadow + (1 - EMA_DECAY) * value
    return float(shadow[0])


class ContinuationAveragingTest(unittest.TestCase):
    def test_regression_averages_epoch_end_weights(self):
        model = FakeModel("regression")
        data = {"x": np.zeros((4, 1)), "y": np.zeros(4)}
        losses = fit_epochs(model, data, 3, {"strategy": "uniform"}, None)
        self.assertEqual(losses, [1.0, 2.0, 3.0])
        self.assertAlmostEqual(float(model.params["w"][0]), expected_average(3))
        self.assertLess(float(model.params["w"][0]), 3.0)
        self.assertEqual(model.meta["epochs"], 3)

    def test_classification_keeps_the_last_weights(self):
        model = FakeModel("classification")
        data = {"x": np.zeros((4, 1)), "y": np.zeros(4)}
        fit_epochs(model, data, 3, {"strategy": "uniform"}, None)
        self.assertEqual(float(model.params["w"][0]), 3.0)

    def test_unit_balanced_regression_is_averaged_too(self):
        model = FakeModel("regression")
        data = {"x": np.zeros((6, 1)), "y": np.zeros(6)}
        groups = np.array(["u1", "u1", "u1", "u2", "u2", "u2"])
        fit_epochs(model, data, 2, {"strategy": "unit_balanced"}, groups)
        self.assertAlmostEqual(float(model.params["w"][0]), expected_average(2))
        self.assertLess(float(model.params["w"][0]), 2.0)

    def test_single_epoch_average_is_a_convex_combination(self):
        model = FakeModel("regression")
        data = {"x": np.zeros((2, 1)), "y": np.zeros(2)}
        fit_epochs(model, data, 1, {"strategy": "uniform"}, None)
        self.assertAlmostEqual(float(model.params["w"][0]), 1 - EMA_DECAY)


if __name__ == "__main__":
    unittest.main()

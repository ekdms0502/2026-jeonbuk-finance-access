from __future__ import annotations

import unittest

from build_typology import select_candidate


class TypologySelectionTests(unittest.TestCase):
    def test_selects_highest_silhouette_without_forcing_three_clusters(self):
        candidates = [
            {"k": 2, "silhouette": 0.68, "passes_project_gates": True},
            {"k": 3, "silhouette": 0.44, "passes_project_gates": True},
            {"k": 4, "silhouette": 0.51, "passes_project_gates": False},
        ]

        self.assertEqual(select_candidate(candidates)["k"], 2)

    def test_returns_none_when_no_candidate_passes_every_gate(self):
        candidates = [
            {"k": 2, "silhouette": 0.68, "passes_project_gates": False},
            {"k": 3, "silhouette": 0.44, "passes_project_gates": False},
        ]

        self.assertIsNone(select_candidate(candidates))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from array import array

from build_jeonbuk_route_scenario import reachable_nodes, transpose_unweighted_csr


class JeonbukBuilderTests(unittest.TestCase):
    def test_transpose_and_reachability_preserve_direction(self):
        # 0 -> 1 -> 2, 2 -> 1.  Node 0 can reach all nodes, but node 2
        # cannot reach 0.  Transposition reverses that fact.
        offsets = array("Q", [0, 1, 2, 3])
        neighbors = array("I", [1, 2, 1])
        forward = reachable_nodes(offsets, neighbors, 0)
        self.assertEqual(list(forward), [1, 1, 1])

        reversed_offsets, reversed_neighbors = transpose_unweighted_csr(
            offsets, neighbors
        )
        reversed_from_two = reachable_nodes(
            reversed_offsets, reversed_neighbors, 2
        )
        self.assertEqual(list(reversed_from_two), [1, 1, 1])

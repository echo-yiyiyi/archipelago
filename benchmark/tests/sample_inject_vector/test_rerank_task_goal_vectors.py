import itertools
import random
import unittest
from collections import Counter
from benchmark.sample_inject_vector.rerank_task_goal_vectors import VECTORS, COSTS, assign, identity, ranking_prompt


class TaskGoalVectorTests(unittest.TestCase):
    def test_balanced_counts_and_pair_identity(self):
        rankings = [list(VECTORS)] * 30
        counts = Counter(assign(rankings, 'balanced'))
        self.assertEqual(sorted(counts.values()), [3]*6 + [4]*3)
        self.assertNotEqual(identity({'task_id':'a','inject_goal':'1'}), identity({'task_id':'a','inject_goal':'2'}))

    def test_matches_exhaustive_small_assignment(self):
        rng = random.Random(42)
        for _ in range(5):
            rankings = [rng.sample(list(VECTORS),9) for _ in range(3)]
            def objective(vectors):
                ranks = [r.index(v) for r,v in zip(rankings,vectors)]
                return sum(r >= 3 for r in ranks), sum(COSTS[r] for r in ranks)
            expected = min(objective(v) for v in itertools.permutations(VECTORS,3))
            self.assertEqual(objective(assign(rankings,'balanced')),expected)

    def test_prompt_uses_task_and_goal_without_old_vector(self):
        row = {'task_id':'a','prompt':'TASK_TEXT','keywords':['topic'],'inject_goal':'goal','inject_vector':'OLD_VECTOR'}
        prompt = ranking_prompt(row, {'goal':'GOAL_TEXT'})
        self.assertIn('TASK_TEXT',prompt)
        self.assertIn('GOAL_TEXT',prompt)
        self.assertNotIn('OLD_VECTOR',prompt)
        self.assertEqual(assign([list(VECTORS)],'first'),['md'])

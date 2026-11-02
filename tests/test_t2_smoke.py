import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import t2_smoke as S  # noqa: E402


class TestSmokeSetup(unittest.TestCase):
    """What the smoke test trains on, checked without a GPU."""

    def test_the_sample_is_fixed(self):
        rows = list(range(82))
        a, b = S.sample(rows), S.sample(rows)
        self.assertEqual(a, b)
        self.assertEqual(len(set(a)), S.N)
        self.assertTrue(all(0 <= i < 82 for i in a))

    def test_pairs_become_conversational_preference_rows(self):
        prompt = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        (ex,) = S.examples([{"prompt": prompt, "chosen": '{"a": 1}', "rejected": '{"a": 2}'}])
        self.assertEqual(ex["prompt"], prompt)
        self.assertEqual(ex["chosen"], [{"role": "assistant", "content": '{"a": 1}'}])
        self.assertEqual(ex["rejected"], [{"role": "assistant", "content": '{"a": 2}'}])

    def test_the_doc_values(self):
        self.assertEqual((S.LORA["r"], S.LORA["lora_alpha"], S.LORA["lora_dropout"]),
                         (16, 32, 0.05))
        self.assertEqual((S.DPO["beta"], S.DPO["learning_rate"], S.DPO["num_train_epochs"]),
                         (0.1, 5e-6, 1))
        self.assertEqual((S.DPO["loss_type"], S.DPO["label_smoothing"], S.DPO["max_length"]),
                         (["sigmoid"], 0.0, 3072))
        self.assertFalse(S.DPO["disable_dropout"])     # else TRL zeroes LoRA's dropout too

    def test_only_step_2s_pairs(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "pairs.jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"prompt": [], "chosen": "x", "rejected": "y"}) + "\n")
        with self.assertRaises(SystemExit) as e:
            S.preflight(path)
        self.assertIn("not step 2's pairs", str(e.exception))


if __name__ == "__main__":
    unittest.main()

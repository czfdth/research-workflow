import unittest
from pathlib import Path

from ccfa.external_adapters import (
    probe_adapter,
    validate_adapters,
)


ROOT = Path(__file__).resolve().parents[2]


class ExternalAdapterTests(unittest.TestCase):
    def test_repository_adapters_are_valid(self):
        self.assertEqual(validate_adapters(ROOT), [])

    def test_env_adapter_is_configured_without_exposing_values(self):
        result = probe_adapter(
            ROOT,
            "exa",
            environ={"EXA_API_KEY": "secret-value"},
        )

        self.assertTrue(result["installed"])
        self.assertEqual(result["configured"], "yes")
        self.assertEqual(result["functional"], "not-checked")
        self.assertFalse(result["ready"])
        self.assertNotIn("secret-value", str(result))

    def test_local_adapter_requires_a_functional_probe(self):
        result = probe_adapter(ROOT, "zotero-local", environ={})

        self.assertTrue(result["installed"])
        self.assertEqual(result["configured"], "yes")
        self.assertEqual(result["functional"], "not-checked")
        self.assertFalse(result["ready"])

    def test_missing_required_env_is_not_configured(self):
        result = probe_adapter(ROOT, "exa", environ={})

        self.assertEqual(result["configured"], "no")
        self.assertFalse(result["ready"])

    def test_unknown_adapter_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知 adapter"):
            probe_adapter(ROOT, "does-not-exist", environ={})


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from trading_system.verify_brokers import check_etoro_credentials, check_moomoo_readiness


class VerifyBrokersTest(unittest.TestCase):
    def test_check_etoro_credentials_reports_presence_without_values(self):
        values = {
            "etoro_pub_key": "public-secret",
            "etoro_demo_key": "demo-secret",
            "etoro_real_key": "real-secret",
        }

        with patch("trading_system.verify_brokers.get_credential", side_effect=lambda key, env_var=None: values.get(key)):
            result = check_etoro_credentials()

        self.assertTrue(result["public_key_configured"])
        self.assertTrue(result["demo_key_configured"])
        self.assertTrue(result["real_key_configured"])
        self.assertNotIn("public-secret", str(result))
        self.assertNotIn("demo-secret", str(result))
        self.assertNotIn("real-secret", str(result))

    def test_check_moomoo_readiness_uses_injected_probes(self):
        result = check_moomoo_readiness(
            socket_probe=lambda host, port: (True, None),
            module_probe=lambda: (True, "10.04.6408", None),
        )

        self.assertTrue(result["opend_reachable"])
        self.assertTrue(result["moomoo_module"])
        self.assertEqual(result["moomoo_version"], "10.04.6408")
        self.assertEqual(result["trd_env"], "SIMULATE")


if __name__ == "__main__":
    unittest.main()

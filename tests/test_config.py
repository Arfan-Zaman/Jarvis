import tempfile
import unittest
from pathlib import Path

from jarvis.config import ConfigError, load_config, parse_env_file
from support import JarvisTestCase


class ConfigTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def load(self, env_text=None, environ=None):
        env_file = self.root / ".env"
        if env_text is not None:
            env_file.write_text(env_text, encoding="utf-8")
        return load_config(root=self.root, env_file=env_file, environ=environ or {})

    def test_defaults(self):
        config = self.load()
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 8765)
        self.assertEqual(config.ai_provider, "none")
        self.assertTrue(config.allow_writes)
        self.assertFalse(config.allow_external_ai)
        self.assertEqual(config.data_dir, self.root / "data")
        self.assertEqual(config.db_path, self.root / "data" / "jarvis.db")
        self.assertEqual(config.backup_dir, self.root / "data" / "backups")

    def test_env_file_is_loaded(self):
        config = self.load("# comment\nJARVIS_PORT=9001\nexport JARVIS_LOG_LEVEL=debug\n"
                           "JARVIS_AI_MODEL=\"some model\"\nJARVIS_BACKUP_KEEP=3 # inline comment\n\n")
        self.assertEqual(config.port, 9001)
        self.assertEqual(config.log_level, "DEBUG")
        self.assertEqual(config.ai_model, "some model")
        self.assertEqual(config.backup_keep, 3)

    def test_environment_overrides_env_file(self):
        config = self.load("JARVIS_PORT=9001\n", environ={"JARVIS_PORT": "9002"})
        self.assertEqual(config.port, 9002)

    def test_empty_values_fall_back_to_defaults(self):
        config = self.load("JARVIS_PORT=\n", environ={"JARVIS_HOST": ""})
        self.assertEqual(config.port, 8765)
        self.assertEqual(config.host, "127.0.0.1")

    def test_absolute_data_dir(self):
        target = self.root / "elsewhere"
        self.assertEqual(self.load(environ={"JARVIS_DATA_DIR": str(target)}).data_dir, target)

    def test_invalid_values_are_rejected(self):
        for name, value in (("JARVIS_PORT", "abc"), ("JARVIS_PORT", "80"), ("JARVIS_PORT", "70000"),
                            ("JARVIS_LOG_LEVEL", "LOUD"), ("JARVIS_ALLOW_WRITES", "maybe"),
                            ("JARVIS_BACKUP_KEEP", "0"), ("JARVIS_APPROVAL_TTL_MINUTES", "-5")):
            with self.subTest(name=name, value=value), self.assertRaises(ConfigError):
                self.load(environ={name: value})

    def test_network_hosts_are_rejected(self):
        for host in ("0.0.0.0", "192.168.1.20", "example.com"):
            with self.subTest(host=host), self.assertRaises(ConfigError):
                self.load(environ={"JARVIS_HOST": host})

    def test_search_key_is_loaded_but_never_shown(self):
        config = self.load("JARVIS_BRAVE_API_KEY=secret-123\n")
        self.assertEqual(config.brave_api_key, "secret-123")
        self.assertEqual(config.public_dict()["brave_api_key"], "set")
        self.assertNotIn("secret-123", str(config.public_dict()))

    def test_malformed_env_file(self):
        with self.assertRaises(ConfigError):
            self.load("THIS IS NOT VALID\n")

    def test_missing_env_file_is_fine(self):
        self.assertEqual(parse_env_file(self.root / "absent.env"), {})

    def test_example_file_matches_defaults(self):
        example = Path(__file__).resolve().parent.parent / ".env.example"
        from_example = load_config(root=self.root, env_file=example, environ={})
        self.assertEqual(from_example, self.load())


class SettingsTests(JarvisTestCase):
    def test_runtime_settings_round_trip(self):
        settings = self.app.settings
        self.assertEqual(settings.get("ui.theme", "default"), "default")
        settings.set("ui.theme", {"accent": "violet"})
        self.assertEqual(settings.get("ui.theme"), {"accent": "violet"})
        settings.set("ui.theme", "plain")
        self.assertEqual(self.make_app().settings.get("ui.theme"), "plain")
        self.assertTrue(settings.delete("ui.theme"))
        self.assertIsNone(settings.get("ui.theme"))


if __name__ == "__main__":
    unittest.main()

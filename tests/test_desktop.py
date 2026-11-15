import math
import random
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from jarvis import desktop
from support import JarvisTestCase, make_config
from jarvis.config import PROJECT_ROOT

HAVE_SWIFT = bool(shutil.which("swiftc")) and bool(shutil.which("codesign"))
RATE = 48000


def write_wav(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))


def recording(seconds, claps=(), knocks=()):
    random.seed(7)
    samples = [random.gauss(0, 0.004) for _ in range(int(RATE * seconds))]
    for at in claps:
        start = int(at * RATE)
        for i in range(int(0.06 * RATE)):
            samples[start + i] += random.uniform(-1, 1) * 0.7 * math.exp(-i / (0.012 * RATE))
    for at in knocks:
        start = int(at * RATE)
        for i in range(int(0.08 * RATE)):
            samples[start + i] += 0.8 * math.sin(2 * math.pi * 90 * i / RATE) * math.exp(-i / (0.02 * RATE))
    return samples


class DesktopPackagingTests(JarvisTestCase):
    def test_info_plist(self):
        info = desktop.info_plist(self.app.config)
        self.assertEqual(info["CFBundleExecutable"], "JARVIS")
        self.assertTrue(info["LSUIElement"])
        self.assertIn("stays on this Mac", info["NSMicrophoneUsageDescription"])
        self.assertEqual(info["JARVISRoot"], str(self.app.config.root))
        self.assertEqual(info["JARVISServer"], "http://127.0.0.1:8765")
        self.assertTrue(Path(info["JARVISPython"]).exists())

    def test_login_item_opens_the_app(self):
        agent = desktop.agent_plist(self.app.config)
        self.assertEqual(agent["Label"], "local.jarvis.desktop")
        self.assertEqual(agent["ProgramArguments"][:2], ["/usr/bin/open", "-g"])
        self.assertTrue(agent["ProgramArguments"][2].endswith("desktop/build/JARVIS.app"))
        self.assertTrue(agent["RunAtLoad"])
        self.assertEqual(desktop.agent_path().name, "local.jarvis.desktop.plist")
        self.assertIn("LaunchAgents", str(desktop.agent_path()))


@unittest.skipUnless(HAVE_SWIFT, "needs the Swift compiler (Xcode Command Line Tools)")
class ClapDetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        config = make_config(PROJECT_ROOT)
        cls.app = desktop.build(config, out=Path(cls.tmp.name) / "JARVIS.app")
        cls.binary = cls.app / "Contents" / "MacOS" / "JARVIS"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def detect(self, samples):
        path = Path(self.tmp.name) / "test.wav"
        write_wav(path, samples)
        out = subprocess.run([str(self.binary), "--test-clap", str(path)], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        doubles = [line for line in out.stdout.splitlines() if line.startswith("DOUBLE_CLAP")]
        claps = int(next(line for line in out.stdout.splitlines() if line.startswith("CLAPS")).split()[1])
        return len(doubles), claps

    def test_bundle_is_signed_with_microphone_reason(self):
        info = (self.app / "Contents" / "Info.plist").read_bytes()
        self.assertIn(b"NSMicrophoneUsageDescription", info)
        check = subprocess.run(["codesign", "--verify", str(self.app)], capture_output=True)
        self.assertEqual(check.returncode, 0)

    def test_double_clap_triggers(self):
        self.assertEqual(self.detect(recording(3, claps=(1.0, 1.35))), (1, 2))

    def test_single_and_slow_claps_do_not(self):
        self.assertEqual(self.detect(recording(3, claps=(1.0,))), (0, 1))
        self.assertEqual(self.detect(recording(5, claps=(1.0, 2.2, 3.4))), (0, 3))

    def test_knocks_and_silence_do_not(self):
        self.assertEqual(self.detect(recording(3, knocks=(1.0, 1.35))), (0, 0))
        self.assertEqual(self.detect(recording(2)), (0, 0))

    @unittest.skipUnless(shutil.which("say"), "needs macOS speech")
    def test_speech_does_not(self):
        path = Path(self.tmp.name) / "speech.wav"
        subprocess.run(["say", "-v", "Daniel", "--data-format=LEI16@48000", "-o", str(path),
                        "Jarvis, check check, tap tap, clap clap, put the kettle on."], check=True)
        out = subprocess.run([str(self.binary), "--test-clap", str(path)], capture_output=True, text=True, timeout=30)
        self.assertNotIn("DOUBLE_CLAP", out.stdout)


if __name__ == "__main__":
    unittest.main()

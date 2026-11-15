import http.client
import json
import threading
import unittest
from pathlib import Path
from unittest import mock

from jarvis import voice as voice_module
from jarvis.common import ValidationError
from jarvis.config import PROJECT_ROOT, ConfigError
from jarvis.voice import Voice, VoiceError, find_program, speakable
from jarvis.web import create_server
from support import JarvisTestCase, make_config

REAL_MODEL = PROJECT_ROOT / "data" / "models" / "ggml-small.en.bin"
HAVE_REAL_VOICE = bool(find_program("say") and find_program("ffmpeg") and find_program("whisper-cli")
                       and REAL_MODEL.is_file())


class SpeakableTests(unittest.TestCase):
    def test_cleans_text_for_speech(self):
        text = ("**Done.** I added the task “Call Sam”.\n- one\n- two\n"
                "See https://example.com/page for more. [memory: 3]\n\nSources: https://a.example, https://b.example")
        self.assertEqual(speakable(text), "Done. I added the task “Call Sam”. one two See a link on screen for more.")

    def test_long_text_is_cut_at_a_sentence(self):
        spoken = speakable("This is a sentence. " * 200)
        self.assertLessEqual(len(spoken), voice_module.MAX_SPOKEN_CHARS + 40)
        self.assertTrue(spoken.endswith("sentence. The rest is on screen."))

    def test_empty(self):
        self.assertEqual(speakable(""), "")
        self.assertEqual(speakable("**  **"), "")


class VoiceEngineTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.model = self.root / "model.bin"
        self.model.write_bytes(b"fake model")
        self.voice = Voice(make_config(self.root, whisper_model=str(self.model)))

    def everything_installed(self):
        return mock.patch.object(voice_module, "find_program", side_effect=lambda name: f"/fake/{name}")

    def test_status(self):
        with self.everything_installed():
            self.assertEqual(self.voice.status(), {"listening": True, "speaking": True, "voice": "Daniel", "missing": []})
        with mock.patch.object(voice_module, "find_program", return_value=None):
            status = self.voice.status()
        self.assertFalse(status["listening"] or status["speaking"])
        self.assertEqual(status["missing"], ["ffmpeg", "whisper-cli", "say"])
        self.model.unlink()
        with self.everything_installed():
            status = self.voice.status()
        self.assertEqual((status["listening"], status["missing"]), (False, ["speech model (model.bin)"]))

    def test_transcribe_pipeline(self):
        calls = []

        def fake_run(args, timeout, what):
            calls.append(args)
            if "-otxt" in args:                      # whisper: write the transcript file
                Path(args[args.index("-of") + 1] + ".txt").write_text(" Add a task to call Sam. [BLANK_AUDIO]\n")
            return None

        with self.everything_installed(), mock.patch.object(Voice, "_run", side_effect=fake_run):
            heard = self.voice.transcribe(b"audio-bytes", "audio/webm;codecs=opus")
        self.assertEqual(heard, "Add a task to call Sam.")
        self.assertEqual([c[0] for c in calls], ["/fake/ffmpeg", "/fake/whisper-cli"])
        self.assertTrue(calls[0][calls[0].index("-i") + 1].endswith("input.webm"))
        self.assertIn(str(self.model), calls[1])
        # Audio is deleted once transcribed.
        self.assertEqual(list((self.root / "data" / "voice").iterdir()), [])

    def test_transcribe_rejects_bad_input(self):
        with self.everything_installed():
            for audio, kind in ((b"", "audio/webm"), (b"x" * (voice_module.MAX_AUDIO_BYTES + 1), "audio/webm"),
                                (b"x", "video/mp4"), (b"x", "text/plain")):
                with self.subTest(kind=kind, size=len(audio)), self.assertRaises(ValidationError):
                    self.voice.transcribe(audio, kind)
        with mock.patch.object(voice_module, "find_program", return_value=None), self.assertRaises(VoiceError):
            self.voice.transcribe(b"x", "audio/webm")

    def test_speak_passes_text_in_a_file_with_the_chosen_voice(self):
        seen = {}

        def fake_run(args, timeout, what):
            seen["args"] = args
            seen["text"] = Path(args[args.index("-f") + 1]).read_text()
            Path(args[args.index("-o") + 1]).write_bytes(b"AAC")
            return None

        with self.everything_installed(), mock.patch.object(Voice, "_run", side_effect=fake_run):
            self.assertEqual(self.voice.speak("**Hello**; rm -rf / && say pwned"), b"AAC")
        self.assertEqual(seen["text"], "Hello; rm -rf / && say pwned")      # plain data, never a command
        self.assertEqual(seen["args"][:5], ["/fake/say", "-v", "Daniel", "-r", "185"])
        with self.everything_installed(), self.assertRaises(ValidationError):
            self.voice.speak("   ")

    def test_failures_are_reported(self):
        with self.everything_installed():
            with mock.patch.object(voice_module.subprocess, "run",
                                   side_effect=voice_module.subprocess.TimeoutExpired("x", 1)):
                with self.assertRaises(VoiceError) as caught:
                    self.voice.speak("hello")
            self.assertIn("took longer", str(caught.exception))


class VoiceConfigTests(unittest.TestCase):
    def test_voice_settings(self):
        root = PROJECT_ROOT
        config = make_config(root, voice="Serena", voice_rate="200")
        self.assertEqual((config.voice_name, config.voice_rate), ("Serena", 200))
        self.assertEqual(make_config(root).whisper_model, REAL_MODEL)
        for bad in ({"voice": "Daniel; rm -rf"}, {"voice_rate": "20"}, {"voice_rate": "fast"}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                make_config(root, **bad)


class VoiceApiTests(JarvisTestCase):
    def setUp(self):
        super().setUp()
        self.server = create_server(self.app, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None, content_type=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
            headers = {"Content-Type": content_type or "application/json"} if data is not None else {}
            conn.request(method, path, body=data, headers=headers)
            response = conn.getresponse()
            return response.status, response.getheader("Content-Type"), response.read(), dict(response.getheaders())
        finally:
            conn.close()

    def test_status_endpoint_and_status_report(self):
        status, _, body, _ = self.call("GET", "/api/voice/status")
        self.assertEqual(status, 200)
        self.assertIn("listening", json.loads(body))
        self.assertIn("voice", self.app.status())

    def test_transcribe_takes_raw_audio(self):
        with mock.patch.object(self.app.voice, "transcribe", return_value="hello jarvis") as transcribe:
            status, _, body, _ = self.call("POST", "/api/voice/transcribe", b"\x1aE\xdf\xa3audio", "audio/webm;codecs=opus")
        self.assertEqual((status, json.loads(body)), (200, {"text": "hello jarvis"}))
        transcribe.assert_called_once_with(b"\x1aE\xdf\xa3audio", "audio/webm;codecs=opus")
        self.assertEqual(self.app.list("conversations"), [])          # transcription alone stores nothing

    def test_speak_returns_audio(self):
        with mock.patch.object(self.app.voice, "speak", return_value=b"AACDATA"):
            status, kind, body, headers = self.call("POST", "/api/voice/speak", {"text": "Hello"})
        self.assertEqual((status, kind, body), (200, "audio/mp4", b"AACDATA"))
        self.assertIn("media-src 'self' blob:", headers["Content-Security-Policy"])

    def test_errors(self):
        with mock.patch.object(self.app.voice, "transcribe", side_effect=VoiceError("Listening is not available")):
            status, _, body, _ = self.call("POST", "/api/voice/transcribe", b"x", "audio/webm")
        self.assertEqual((status, json.loads(body)["error"]), (400, "Listening is not available"))
        status, _, _, _ = self.call("POST", "/api/voice/speak", {"text": ""})
        self.assertEqual(status, 400)


@unittest.skipUnless(HAVE_REAL_VOICE, "needs macOS say, ffmpeg, whisper-cli and the speech model")
class RealVoiceRoundTripTest(JarvisTestCase):
    def test_jarvis_can_hear_what_it_says(self):
        voice = Voice(make_config(self.root, whisper_model=str(REAL_MODEL)))
        audio = voice.speak("Good evening. All systems are operational.")
        self.assertGreater(len(audio), 1000)
        heard = voice.transcribe(audio, "audio/mp4").lower()
        self.assertIn("systems are operational", heard)


if __name__ == "__main__":
    unittest.main()

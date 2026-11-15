"""JARVIS Desktop: build, install and remove the floating orb app.

The app (`desktop/JARVISDesktop.swift`) is compiled with the Swift compiler
that ships with the Xcode Command Line Tools, wrapped as `JARVIS.app` in
`desktop/build/`, and signed locally (ad hoc) so macOS can remember its
microphone permission.

`install` also adds a login item: one LaunchAgent file,
`~/Library/LaunchAgents/local.jarvis.desktop.plist`, the only file JARVIS
places outside its own folder. `uninstall` removes it again.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from .common import JarvisError
from .config import Config

LABEL = "local.jarvis.desktop"
BUNDLE_ID = "local.jarvis.desktop"
SOURCE = "desktop/JARVISDesktop.swift"
MIC_REASON = ("JARVIS listens for a double clap and then for your request. "
              "Audio stays on this Mac and goes only to your local JARVIS server.")


class DesktopError(JarvisError):
    """Building or installing the desktop app failed."""


def app_path(config: Config) -> Path:
    return config.root / "desktop" / "build" / "JARVIS.app"


def agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def info_plist(config: Config) -> dict:
    return {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": "JARVIS",
        "CFBundleDisplayName": "JARVIS",
        "CFBundleExecutable": "JARVIS",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,                      # no Dock icon: it lives as the floating orb
        "NSMicrophoneUsageDescription": MIC_REASON,
        "JARVISRoot": str(config.root),
        "JARVISPython": str(Path(sys.executable).resolve()),
        "JARVISServer": f"http://{'127.0.0.1' if config.host == 'localhost' else config.host}:{config.port}",
    }


def agent_plist(config: Config) -> dict:
    return {
        "Label": LABEL,
        # `open` launches it as a normal app, so macOS asks for the microphone properly.
        "ProgramArguments": ["/usr/bin/open", "-g", str(app_path(config))],
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    }


def _run(args: list[str], what: str, check: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(args, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise DesktopError(f"{what} failed: {(done.stderr or done.stdout).strip()[-600:]}")
    return done


def build(config: Config, out: Path | None = None) -> Path:
    """Compile and package the app. Returns the .app path."""
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise DesktopError("The Swift compiler was not found. Install the Xcode Command Line Tools "
                           "(xcode-select --install).")
    app = out or app_path(config)
    if app.exists():
        shutil.rmtree(app)
    (app / "Contents" / "MacOS").mkdir(parents=True)
    _run([swiftc, "-swift-version", "5", "-O", str(config.root / SOURCE),
          "-o", str(app / "Contents" / "MacOS" / "JARVIS")], "Compiling the desktop app")
    with open(app / "Contents" / "Info.plist", "wb") as handle:
        plistlib.dump(info_plist(config), handle)
    _run(["codesign", "--force", "--sign", "-", str(app)], "Signing the desktop app")
    return app


def install(config: Config) -> Path:
    """Build the app, start it now, and start it automatically at every login."""
    app = build(config)
    target = agent_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as handle:
        plistlib.dump(agent_plist(config), handle)
    domain = f"gui/{os.getuid()}"
    _run(["launchctl", "bootout", f"{domain}/{LABEL}"], "Stopping the old login item", check=False)
    _run(["launchctl", "bootstrap", domain, str(target)], "Adding the login item")
    return app


def uninstall(config: Config) -> list[str]:
    """Stop the app and remove the login item. The built app stays in desktop/build."""
    done = []
    _run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], "Removing the login item", check=False)
    if agent_path().exists():
        agent_path().unlink()
        done.append(f"removed {agent_path()}")
    if _run(["pkill", "-f", "JARVIS.app/Contents/MacOS/JARVIS"], "Stopping the app", check=False).returncode == 0:
        done.append("stopped JARVIS Desktop")
    return done


def status(config: Config) -> dict:
    running = _run(["pgrep", "-f", "JARVIS.app/Contents/MacOS/JARVIS"], "Checking", check=False).returncode == 0
    return {"built": (app_path(config) / "Contents" / "MacOS" / "JARVIS").exists(),
            "starts_at_login": agent_path().exists(), "running": running, "app": str(app_path(config))}

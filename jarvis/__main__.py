"""Command line entry point: `python3 -m jarvis <command>`."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time

from . import __version__
from .common import JarvisError
from .config import load_config
from .logging_setup import setup_logging
from .orchestrator import Jarvis


def _running_pid(config) -> int | None:
    """PID of a live JARVIS server recorded in the pid file, if any."""
    try:
        pid = int(config.pid_file.read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    command = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True).stdout
    return pid if "jarvis" in command.lower() else None


def cmd_serve(config, args) -> int:
    from .web import create_server

    logger = setup_logging(config)
    existing = _running_pid(config)
    if existing:
        print(f"JARVIS is already running (pid {existing}). Stop it with: python3 -m jarvis stop")
        return 1
    app = Jarvis(config).start()
    app.announce_startup()
    if config.backup_on_start:
        app.create_backup("startup", actor="system")
    try:
        server = create_server(app)
    except OSError as exc:
        print(f"Cannot start on {config.host}:{config.port}: {exc}\n"
              "Another program may be using the port. Change JARVIS_PORT in .env.")
        return 1

    def _terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _terminate)
    config.pid_file.write_text(str(os.getpid()))
    status = app.provider.status()
    logger.info("JARVIS %s listening on http://%s:%s", __version__, config.host, config.port)
    logger.info("AI provider: %s", status.detail if not status.available else f"{status.name} ({status.model})")
    logger.info("Press Ctrl+C to stop.")
    app.learner.start()                       # continuous learning while the server runs
    app.selfreview.start()                    # weekly self-review; proposals wait for the owner
    app.briefing.start()                      # the day's headlines ready before the first "Jarvis"
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        config.pid_file.unlink(missing_ok=True)
        app.events.record("system", "shutdown", "JARVIS stopped")
        logger.info("JARVIS stopped.")
    return 0


def cmd_stop(config, args) -> int:
    pid = _running_pid(config)
    if not pid:
        print("JARVIS is not running.")
        config.pid_file.unlink(missing_ok=True)
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        time.sleep(0.1)
        if not _running_pid(config):
            print(f"JARVIS stopped (pid {pid}).")
            return 0
    print(f"JARVIS (pid {pid}) did not stop within 5 seconds.")
    return 1


def cmd_init(config, args) -> int:
    setup_logging(config, console=False)
    app = Jarvis(config).start()
    print(f"Database ready at {config.db_path} (schema v{app.db.version()}).")
    return 0


def cmd_status(config, args) -> int:
    setup_logging(config, console=False)
    app = Jarvis(config).start()
    status = app.status()
    pid = _running_pid(config)
    status["server"] = {"running": bool(pid), "pid": pid, "url": f"http://{config.host}:{config.port}"}
    print(json.dumps(status, indent=2))
    return 0


def cmd_backup(config, args) -> int:
    setup_logging(config, console=False)
    info = Jarvis(config).start().create_backup(args.label)
    print(f"Backup created: {config.backup_dir / info['name']} ({info['size_bytes']} bytes)")
    return 0


def cmd_backups(config, args) -> int:
    setup_logging(config, console=False)
    backups = Jarvis(config).start().backups.list()
    if not backups:
        print("No backups yet. Create one with: python3 -m jarvis backup")
    for item in backups:
        print(f"{item['name']}  {item['size_bytes']:>9} bytes  {item['created_at']}")
    return 0


def cmd_tools(config, args) -> int:
    setup_logging(config, console=False)
    for tool in Jarvis(config).start().tools.list():
        approval = "  (needs approval)" if tool["requires_approval"] else ""
        print(f"{tool['name']:<20} {tool['permission']:<6} {tool['description']}{approval}")
    return 0


def cmd_tool(config, args) -> int:
    setup_logging(config, console=False)
    try:
        inputs = json.loads(args.inputs)
    except ValueError:
        print("Error: inputs must be JSON, for example '{\"title\": \"Call the supplier\"}'", file=sys.stderr)
        return 1
    result = Jarvis(config).start().tools.execute(args.name, inputs)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def cmd_goal(config, args) -> int:
    setup_logging(config, console=False)
    report = Jarvis(config).start().engine.start(args.goal)
    print(json.dumps(report, indent=2))
    return 0 if report["verified_complete"] else 1


def cmd_desktop(config, args) -> int:
    from . import desktop
    if args.action == "build":
        print(f"Built {desktop.build(config)}")
    elif args.action == "install":
        app = desktop.install(config)
        print(f"Installed {app}")
        print("JARVIS Desktop is starting and will start automatically at every login.")
        print("macOS will ask once for microphone access: choose Allow.")
        print("To remove it: python3 -m jarvis desktop uninstall")
    elif args.action == "uninstall":
        done = desktop.uninstall(config)
        print("\n".join(done) if done else "JARVIS Desktop was not installed.")
    else:
        print(json.dumps(desktop.status(config), indent=2))
    return 0


def cmd_restore(config, args) -> int:
    setup_logging(config, console=False)
    if _running_pid(config):
        print("Stop JARVIS before restoring: python3 -m jarvis stop")
        return 1
    app = Jarvis(config).start()
    request = app.restore_backup(args.name)
    approval = request["approval"]
    print(f"About to: {approval['summary']}")
    print("A 'pre-restore' backup of the current database is taken first.")
    if not args.yes:
        if input("Type RESTORE to confirm: ").strip() != "RESTORE":
            app.safety.deny(approval["id"])
            print("Cancelled. Nothing was changed.")
            return 1
    app.safety.approve(approval["id"])
    result = app.restore_backup(args.name, approval_id=approval["id"])
    print(f"Restored from {result['restored_from']}. Previous state saved as {result['pre_restore_backup']}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m jarvis", description="JARVIS core")
    parser.add_argument("--version", action="version", version=f"JARVIS {__version__}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="start the local web interface (default)").set_defaults(run=cmd_serve)
    commands.add_parser("stop", help="stop a running JARVIS server").set_defaults(run=cmd_stop)
    commands.add_parser("init", help="create or upgrade the database").set_defaults(run=cmd_init)
    commands.add_parser("status", help="print system status as JSON").set_defaults(run=cmd_status)
    backup = commands.add_parser("backup", help="back up the database now")
    backup.add_argument("--label", default="manual")
    backup.set_defaults(run=cmd_backup)
    commands.add_parser("backups", help="list backups").set_defaults(run=cmd_backups)
    commands.add_parser("tools", help="list the tools JARVIS can execute").set_defaults(run=cmd_tools)
    tool = commands.add_parser("tool", help="execute one tool")
    tool.add_argument("name", help="tool name, as shown by `tools`")
    tool.add_argument("inputs", nargs="?", default="{}", help="inputs as JSON")
    tool.set_defaults(run=cmd_tool)
    goal = commands.add_parser("goal", help="plan and carry out a goal (needs an AI model)")
    goal.add_argument("goal", help="what you want done, in plain language")
    goal.set_defaults(run=cmd_goal)
    desktop_cmd = commands.add_parser("desktop", help="the floating desktop orb (double clap, then say Jarvis)")
    desktop_cmd.add_argument("action", choices=["build", "install", "uninstall", "status"])
    desktop_cmd.set_defaults(run=cmd_desktop)
    restore = commands.add_parser("restore", help="replace the database with a backup")
    restore.add_argument("name", help="backup file name, as shown by `backups`")
    restore.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    restore.set_defaults(run=cmd_restore)

    args = parser.parse_args(argv)
    try:
        config = load_config()
        return getattr(args, "run", cmd_serve)(config, args)
    except JarvisError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

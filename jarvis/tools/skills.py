"""Skills and software: JARVIS finds, installs and uses them itself (no Claude needed).

Skills are folders with a SKILL.md (instructions for a kind of work, e.g. "seo-content-writer"). They live
in `workspace/.claude/skills/<name>/`, where both JARVIS's local brain (`relevant()`) and Claude Code
(`claude.work`, run in the workspace) pick them up.

- skills.list     (read)      what is installed, with each skill's one-line description.
- skills.search   (web_read)  find skills on GitHub (repositories that contain SKILL.md files).
- skills.install  (system)    download a skill from GitHub and install it. The owner approves each install.
                              Only instructions come in (.md, .txt, .json, .yaml, .csv); scripts and binaries
                              are left out and listed, so a skill can never run code on the Mac by itself.
- system.install  (system)    install a software package with pip, npm or Homebrew. The owner approves each
                              install. Argument lists only (never a shell); package names are checked.

A skill's text is advice to JARVIS, never an instruction that overrides the owner or the safety rules.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

from ..common import JarvisError, ValidationError
from ..safety import ActionCategory
from .registry import Tool, ToolRegistry

TEXT_FILES = (".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv")
MAX_SKILL_BYTES = 2_000_000
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
GITHUB = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?"
                    r"(?:/(?:tree|blob)/([^/]+)(?:/(.*))?)?/?$")
PACKAGE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/@\-]{0,99}(\[[A-Za-z0-9,_-]{1,60}\])?([<>=!~]=?[A-Za-z0-9.*]{1,30})?$")


def skills_dir(app) -> Path:
    path = Path(app.config.workspace_dir) / ".claude" / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _frontmatter(text: str) -> dict:
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    data = {}
    for line in (match.group(1).splitlines() if match else []):
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip('"\'')
    return data


def installed(app) -> list[dict]:
    out = []
    for skill in sorted(skills_dir(app).iterdir()):
        doc = skill / "SKILL.md"
        if doc.is_file():
            meta = _frontmatter(doc.read_text(encoding="utf-8", errors="replace")[:4000])
            out.append({"name": meta.get("name") or skill.name, "folder": skill.name,
                        "description": meta.get("description", "")[:400]})
    return out


# --- using skills -----------------------------------------------------------------------
STOP = set("the a an and or of to for in on with my me i you your is are be it this that can could please what how "
           "use when need want do make help".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9]{2,}", text.lower()) if w not in STOP}


def relevant(app, request: str, limit_chars: int = 5000) -> dict | None:
    """The installed skill that fits this request best (by its name and description), with its instructions."""
    asked = _words(request)
    if len(asked) < 2:
        return None
    best, best_score = None, 0.0
    for skill in installed(app):
        about = _words(skill["name"].replace("-", " ") + " " + skill["description"])
        if not about:
            continue
        hits = asked & about
        score = len(hits) + 2 * len(asked & _words(skill["name"].replace("-", " ")))
        if score > best_score:
            best, best_score = skill, score
    if not best or best_score < 3:
        return None
    text = (skills_dir(app) / best["folder"] / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    body = re.sub(r"^---.*?\n---\s*", "", text, flags=re.S)
    return {"name": best["name"], "instructions": body[:limit_chars]}


# --- tools -------------------------------------------------------------------------------
def skills_list(app, inputs, actor):
    items = installed(app)
    return {"folder": str(skills_dir(app)).replace(str(Path.home()), "~", 1), "skills": items, "total": len(items)}


def _github_json(url: str) -> dict:
    gh = shutil.which("gh")
    if gh:                                           # signed in: higher limits, code search allowed
        done = subprocess.run([gh, "api", url.replace("https://api.github.com/", "")], capture_output=True,
                              text=True, timeout=30, stdin=subprocess.DEVNULL)
        if done.returncode == 0:
            return json.loads(done.stdout)
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "JARVIS"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except Exception as exc:  # noqa: BLE001
        raise JarvisError(f"GitHub search failed: {exc}") from exc


def skills_search(app, inputs, actor):
    query = " ".join(str(inputs.get("query") or "").split())[:100]
    if not query:
        raise ValidationError("query is required")
    limit = max(1, min(int(inputs.get("limit") or 8), 15))
    results, seen = [], set()
    try:                                            # files named SKILL.md that match the words (needs gh sign-in)
        code = _github_json("https://api.github.com/search/code?" + urllib.parse.urlencode(
            {"q": f"{query} filename:SKILL.md", "per_page": limit}))
        for item in code.get("items", []):
            repo = item["repository"]["full_name"]
            folder = item["path"].rsplit("/", 1)[0] if "/" in item["path"] else ""
            key = f"{repo}/{folder}"
            if key in seen:
                continue
            seen.add(key)
            results.append({"install": f"https://github.com/{repo}/tree/HEAD/{folder}".rstrip("/"),
                            "repository": repo, "skill_folder": folder or "(repository root)",
                            "stars": item["repository"].get("stargazers_count")})
    except JarvisError:
        pass
    if len(results) < limit:                        # repositories about skills
        repos = _github_json("https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": f"{query} skill SKILL.md", "sort": "stars", "per_page": limit}))
        for repo in repos.get("items", []):
            if repo["full_name"] not in {r["repository"] for r in results}:
                results.append({"install": repo["html_url"], "repository": repo["full_name"],
                                "description": (repo.get("description") or "")[:200],
                                "stars": repo.get("stargazers_count")})
    return {"query": query, "results": results[:limit],
            "note": "Install one with skills.install using its 'install' address. Only instruction files come in."}


def _download(owner: str, repo: str, ref: str | None) -> tarfile.TarFile:
    ref = ref or "HEAD"
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{urllib.parse.quote(ref)}"
    request = urllib.request.Request(url, headers={"User-Agent": "JARVIS"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(40_000_001)
    except Exception as exc:  # noqa: BLE001
        raise JarvisError(f"could not download {owner}/{repo}: {exc}") from exc
    if len(data) > 40_000_000:
        raise JarvisError("that repository is too big to install skills from (over 40 MB)")
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")


def skills_install(app, inputs, actor):
    match = GITHUB.match(str(inputs.get("source") or "").strip())
    if not match:
        raise ValidationError("source must be a GitHub address like https://github.com/owner/repo/tree/main/skills/name")
    owner, repo, ref, subpath = match.group(1), match.group(2), match.group(3), (match.group(4) or "").strip("/")
    archive = _download(owner, repo, ref)
    members = [m for m in archive.getmembers() if m.isfile()]
    root = members[0].name.split("/", 1)[0] if members else ""
    def rel(m):
        return m.name.split("/", 1)[1] if "/" in m.name else ""
    docs = [rel(m) for m in members if rel(m).endswith("SKILL.md") and rel(m).startswith(subpath)]
    if not docs:
        raise JarvisError(f"no SKILL.md found in {owner}/{repo}/{subpath or ''}")
    wanted = str(inputs.get("name") or "").strip().lower()
    target_root, done = skills_dir(app), []
    for doc in docs[:20]:
        folder = doc.rsplit("/", 1)[0] if "/" in doc else ""
        text = archive.extractfile(f"{root}/{doc}").read(400_000).decode("utf-8", "replace")
        meta = _frontmatter(text)
        name = re.sub(r"[^a-z0-9-]+", "-", (meta.get("name") or folder.rsplit("/", 1)[-1] or repo).lower()).strip("-")[:63]
        if not NAME.match(name) or (wanted and name != wanted):
            continue
        kept, skipped, size = [], [], 0
        target = target_root / name
        if target.exists() and not inputs.get("replace"):
            done.append({"name": name, "status": "already installed (set replace to update it)"})
            continue
        staging = target_root / f".{name}.new"
        shutil.rmtree(staging, ignore_errors=True)
        for member in members:
            path = rel(member)
            if folder and not path.startswith(folder + "/"):
                continue
            inner = path[len(folder) + 1:] if folder else path
            if not folder and "/" in inner and not inner.startswith(("references/", "reference/", "docs/")):
                continue                           # a root-level skill: only its own docs, not the whole repo
            if ".." in inner.split("/") or inner.startswith("/"):
                continue
            if not inner.lower().endswith(TEXT_FILES):
                skipped.append(inner)
                continue
            size += member.size
            if size > MAX_SKILL_BYTES:
                skipped.append(inner + " (too big)")
                continue
            out = staging / inner
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.extractfile(member).read())
            kept.append(inner)
        if "SKILL.md" not in kept:
            shutil.rmtree(staging, ignore_errors=True)
            continue
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
        (target / ".source").write_text(f"https://github.com/{owner}/{repo} {folder}\n", encoding="utf-8")
        done.append({"name": name, "status": "installed", "description": meta.get("description", "")[:300],
                     "files": kept[:30], "left_out": skipped[:30]})
    if not done:
        raise JarvisError("no skill could be installed from there" + (f" with the name {wanted!r}" if wanted else ""))
    return {"source": f"{owner}/{repo}" + (f"/{subpath}" if subpath else ""), "skills": done,
            "note": "Scripts and other non-text files are never installed; JARVIS uses the instructions."}


def system_install(app, inputs, actor):
    manager = str(inputs.get("manager") or "pip").strip().lower()
    package = str(inputs.get("package") or "").strip()
    if manager not in ("pip", "npm", "brew"):
        raise ValidationError("manager must be pip, npm or brew")
    if not PACKAGE.match(package) or package.startswith("-"):
        raise ValidationError(f"{package!r} does not look like a package name")
    if manager == "pip":
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", package]
    elif manager == "npm":
        npm = shutil.which("npm") or next(iter(sorted(Path.home().glob(".nvm/versions/node/*/bin/npm"), reverse=True)), None)
        if not npm:
            raise JarvisError("npm is not installed")
        cmd = [str(npm), "install", "--global", "--no-fund", "--no-audit", package]
    else:
        brew = shutil.which("brew") or "/opt/homebrew/bin/brew"
        if not Path(brew).exists():
            raise JarvisError("Homebrew is not installed")
        cmd = [brew, "install", package]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise JarvisError(f"installing {package} took longer than 15 minutes") from None
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    if done.returncode:
        raise JarvisError(f"{manager} could not install {package}: {output[-600:]}")
    return {"manager": manager, "package": package, "installed": True, "output": output[-1200:]}


def register_skills(registry: ToolRegistry) -> None:
    registry.register(Tool("skills.list", "List the skills JARVIS has installed, with what each is for.",
                           ActionCategory.READ, skills_list))
    registry.register(Tool(
        "skills.search", "Find skills (SKILL.md instruction packs) on GitHub for a kind of work, e.g. 'seo', "
        "'video editing', 'excel'. Returns install addresses.", ActionCategory.WEB_READ, skills_search,
        {"query": {"type": "string", "description": "What the skill should help with.", "required": True},
         "limit": {"type": "integer", "description": "How many results (1 to 15)."}}))
    registry.register(Tool(
        "skills.install", "Download a skill from GitHub and install it for JARVIS (instructions only; scripts are "
        "left out). The owner approves each install.", ActionCategory.SYSTEM, skills_install,
        {"source": {"type": "string", "description": "GitHub address of the repo or skill folder.", "required": True},
         "name": {"type": "string", "description": "Install only the skill with this name (for repos with many)."},
         "replace": {"type": "boolean", "description": "Update it if it is already installed."}}))
    registry.register(Tool(
        "system.install", "Install a software package on the Mac with pip (Python), npm (Node) or brew (Homebrew). "
        "The owner approves each install.", ActionCategory.SYSTEM, system_install,
        {"manager": {"type": "string", "description": "pip, npm or brew.", "enum": ["pip", "npm", "brew"], "required": True},
         "package": {"type": "string", "description": "The package name, optionally with a version.", "required": True}}))

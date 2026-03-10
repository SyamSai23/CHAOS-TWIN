"""Scanner V3 — Universal codebase analysis engine.

Produces a deeply accurate, structured knowledge model of any
uploaded ZIP codebase using deterministic heuristics only (no AI).
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from collections import defaultdict
from typing import Any, Optional
from xml.etree import ElementTree

import yaml  # PyYAML — already in requirements.txt

# =====================================================================
# SECTION 1 — Constants
# =====================================================================

IGNORED_DIRS: set[str] = {
    "node_modules", "__pycache__", ".git", "dist", "build", ".next",
    "venv", ".venv", "env", "__MACOSX", ".DS_Store", "coverage",
    ".pytest_cache", "target", "out", "bin", "obj", ".idea", ".vscode",
    "workspaces", "uploads",
}

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript",
    ".java": "Java",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
    ".c": "C",
    ".css": "CSS", ".scss": "CSS", ".sass": "CSS",
    ".html": "HTML",
    ".sql": "SQL",
    ".sh": "Shell", ".bash": "Shell",
    ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
}

LANGUAGE_MARKERS: dict[str, set[str]] = {
    "Python": {"requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "setup.cfg"},
    "TypeScript": {"tsconfig.json"},
    "JavaScript": {"package.json"},
    "Java": {"pom.xml", "build.gradle", "build.gradle.kts"},
    "C#": set(),  # Special: checked by file extension (.csproj, .sln)
    "Go": {"go.mod"},
    "Rust": {"Cargo.toml"},
    "Ruby": {"Gemfile"},
    "PHP": {"composer.json"},
    "Swift": {"Package.swift"},
    "Kotlin": {"build.gradle.kts"},
}

# Recognised entry files per language
ENTRY_FILES: dict[str, set[str]] = {
    "Python": {"main.py", "app.py", "wsgi.py", "asgi.py"},
    "JavaScript": {"index.js", "App.tsx", "server.js", "App.jsx"},
    "TypeScript": {"index.ts", "App.tsx", "server.ts"},
    "C#": {"Program.cs", "Startup.cs"},
    "Go": {"main.go"},
    "Rust": {"main.rs"},
    "Java": {"Main.java", "Application.java"},
    "Ruby": {"app.rb"},
    "PHP": {"index.php"},
}

RUNTIME_MARKERS: set[str] = {
    "Dockerfile", "package.json", "requirements.txt", "go.mod",
    "Cargo.toml", "pom.xml", "Gemfile",
}

SOURCE_EXTENSIONS: set[str] = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".cs", ".go",
    ".rs", ".rb", ".php", ".swift", ".kt", ".cpp", ".cc", ".cxx", ".c",
}

FRAMEWORK_MARKERS: dict[str, str] = {
    "package.json": "Node.js",
    "tsconfig.json": "TypeScript",
    "requirements.txt": "Python (pip)",
    "pyproject.toml": "Python (modern)",
    "Pipfile": "Python (pipenv)",
    "go.mod": "Go modules",
    "Cargo.toml": "Rust (Cargo)",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java (Gradle)",
    "build.gradle.kts": "Java (Gradle)",
    "Gemfile": "Ruby (Bundler)",
    "composer.json": "PHP (Composer)",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
    ".env": "Environment config",
    "Makefile": "Make",
    "vite.config.ts": "Vite",
    "vite.config.js": "Vite",
    "next.config.js": "Next.js",
    "next.config.mjs": "Next.js",
    "angular.json": "Angular",
    "manage.py": "Django",
}

# Text-like extensions whose line count is worth reading
_TEXT_EXTENSIONS: set[str] = (
    set(EXTENSION_TO_LANGUAGE.keys())
    | {".toml", ".cfg", ".ini", ".txt", ".xml", ".env", ".lock",
       ".gradle", ".kts", ".mod", ".sum", ".gemspec", ".rake"}
)


# =====================================================================
# SECTION 2 — File System Walk
# =====================================================================

def walk_files(root: str) -> list[dict]:
    """Walk the directory tree and record every file."""
    inventory: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for fname in filenames:
            if fname in IGNORED_DIRS or fname == ".DS_Store":
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root).replace("\\", "/")
            _, ext = os.path.splitext(fname)
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            line_count = 0
            if ext.lower() in _TEXT_EXTENSIONS and size < 2 * 1024 * 1024:
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        line_count = sum(1 for _ in f)
                except OSError:
                    pass
            inventory.append({
                "path": rel,
                "extension": ext,
                "size_bytes": size,
                "line_count": line_count,
            })
    return inventory


# =====================================================================
# SECTION 3 — Language Detection with Confidence Scoring
# =====================================================================

def detect_languages(
    files: list[dict],
) -> tuple[list[str], dict[str, float]]:
    """Detect languages with confidence scoring.

    Returns (language_names, confidence_dict).
    """
    lang_counts: dict[str, int] = defaultdict(int)
    for f in files:
        lang = EXTENSION_TO_LANGUAGE.get(f["extension"])
        if lang:
            lang_counts[lang] += 1

    file_names: set[str] = {os.path.basename(f["path"]) for f in files}
    file_exts: set[str] = {f["extension"] for f in files}

    lang_has_marker: dict[str, bool] = {}
    for lang, markers in LANGUAGE_MARKERS.items():
        if lang == "C#":
            lang_has_marker[lang] = ".csproj" in file_exts or ".sln" in file_exts
        else:
            lang_has_marker[lang] = bool(markers & file_names)

    max_count = max(lang_counts.values()) if lang_counts else 1
    confidence: dict[str, float] = {}

    all_langs = set(lang_counts.keys()) | {
        l for l, has in lang_has_marker.items() if has
    }

    for lang in all_langs:
        count = lang_counts.get(lang, 0)
        has_marker = lang_has_marker.get(lang, False)

        if count < 3 and not has_marker:
            continue
        if lang == "JSON" and count < 5:
            continue
        if lang == "Markdown":
            continue
        if lang == "C#" and not lang_has_marker.get("C#", False):
            continue

        norm_count = min(count / max_count, 1.0) if max_count > 0 else 0.0
        score = (norm_count * 0.4) + (0.6 if has_marker else 0.0)

        if score > 0.3:
            confidence[lang] = round(min(score, 1.0), 2)

    return sorted(confidence.keys()), confidence


# =====================================================================
# SECTION 4 — Marker File Deep Parsing
# =====================================================================

def _safe_read(filepath: str, max_size: int = 1024 * 1024) -> Optional[str]:
    try:
        if os.path.getsize(filepath) > max_size:
            return None
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _parse_package_json(root: str, rel: str) -> dict:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return {}
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {}
    return {
        "name": data.get("name", ""),
        "version": data.get("version", ""),
        "dependencies": sorted(data.get("dependencies", {}).keys()),
        "devDependencies": sorted(data.get("devDependencies", {}).keys()),
        "scripts": sorted(data.get("scripts", {}).keys()),
    }


def _parse_requirements_txt(root: str, rel: str) -> list[dict]:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return []
    deps: list[dict] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*([><=!~]+\s*[\d.a-zA-Z*]+)?", line)
        if m:
            deps.append({"name": m.group(1), "version": (m.group(2) or "").strip()})
    return deps


def _parse_pyproject_toml(root: str, rel: str) -> dict:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return {}
    result: dict[str, Any] = {"name": "", "version": "", "dependencies": []}
    nm = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, re.M)
    if nm:
        result["name"] = nm.group(1)
    vm = re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', content, re.M)
    if vm:
        result["version"] = vm.group(1)
    # dependencies = ["fastapi>=0.100", ...]
    dep_list = re.search(r"dependencies\s*=\s*\[(.*?)\]", content, re.S)
    if dep_list:
        for dm in re.finditer(r'["\']([A-Za-z0-9_.-]+)', dep_list.group(1)):
            result["dependencies"].append(dm.group(1))
    # [tool.poetry.dependencies]
    poetry = re.search(
        r"\[tool\.poetry\.dependencies\]\s*\n(.*?)(?:\n\[|\Z)", content, re.S
    )
    if poetry:
        for dm in re.finditer(r"^([A-Za-z0-9_.-]+)\s*=", poetry.group(1), re.M):
            if dm.group(1).lower() != "python":
                result["dependencies"].append(dm.group(1))
    return result


def _parse_docker_compose(root: str, rel: str) -> list[dict]:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return []
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    services_data = data.get("services", {})
    if not isinstance(services_data, dict):
        return []
    services: list[dict] = []
    for name, cfg in services_data.items():
        if not isinstance(cfg, dict):
            continue
        ports: list[str] = []
        raw_ports = cfg.get("ports", [])
        if isinstance(raw_ports, list):
            ports = [str(p) for p in raw_ports]
        depends: list[str] = []
        raw_dep = cfg.get("depends_on", [])
        if isinstance(raw_dep, list):
            depends = raw_dep
        elif isinstance(raw_dep, dict):
            depends = list(raw_dep.keys())
        services.append({
            "name": name,
            "image": cfg.get("image", ""),
            "ports": ports,
            "depends_on": depends,
        })
    return services


def _parse_dockerfile(root: str, rel: str) -> dict:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return {}
    result: dict[str, Any] = {"base_image": "", "ports": [], "cmd": ""}
    for line in content.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("FROM ") and not result["base_image"]:
            result["base_image"] = stripped[5:].strip().split(" AS ")[0].strip()
        elif upper.startswith("EXPOSE "):
            for tok in stripped[7:].split():
                if tok.split("/")[0].isdigit():
                    result["ports"].append(tok.split("/")[0])
        elif upper.startswith("CMD ") or upper.startswith("ENTRYPOINT "):
            idx = stripped.index(" ")
            result["cmd"] = stripped[idx + 1:].strip()
    return result


def _parse_env_file(root: str, rel: str) -> list[str]:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return []
    variables: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            var = line.split("=", 1)[0].strip()
            if var and re.match(r"^[A-Za-z_]\w*$", var):
                variables.append(var)
    return variables


def _parse_pom_xml(root: str, rel: str) -> dict:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return {}
    try:
        cleaned = re.sub(r'\sxmlns=["\'][^"\']*["\']', "", content, count=1)
        tree = ElementTree.fromstring(cleaned)
    except ElementTree.ParseError:
        return {}
    result: dict[str, Any] = {"groupId": "", "artifactId": "", "dependencies": []}
    gid = tree.find("groupId")
    if gid is not None and gid.text:
        result["groupId"] = gid.text
    aid = tree.find("artifactId")
    if aid is not None and aid.text:
        result["artifactId"] = aid.text
    deps_elem = tree.find("dependencies")
    if deps_elem is not None:
        for dep in deps_elem.findall("dependency"):
            daid = dep.find("artifactId")
            if daid is not None and daid.text:
                result["dependencies"].append(daid.text)
    return result


def _parse_build_gradle(root: str, rel: str) -> list[str]:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return []
    deps: set[str] = set()
    for m in re.finditer(
        r"(?:implementation|compile|api|runtimeOnly|testImplementation)"
        r"""\s*[('"]([^'"()]+)['")\s]""",
        content,
    ):
        artifact = m.group(1)
        parts = artifact.split(":")
        deps.add(parts[1] if len(parts) >= 2 else artifact)
    return sorted(deps)


def _parse_go_mod(root: str, rel: str) -> dict:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return {}
    result: dict[str, Any] = {"module": "", "go_version": "", "requires": []}
    mm = re.search(r"^module\s+(\S+)", content, re.M)
    if mm:
        result["module"] = mm.group(1)
    vm = re.search(r"^go\s+(\S+)", content, re.M)
    if vm:
        result["go_version"] = vm.group(1)
    block = re.search(r"require\s*\((.*?)\)", content, re.S)
    if block:
        for line in block.group(1).splitlines():
            line = line.strip()
            if line and not line.startswith("//"):
                parts = line.split()
                if parts:
                    result["requires"].append(parts[0])
    for sm in re.finditer(r"^require\s+(\S+)\s+", content, re.M):
        result["requires"].append(sm.group(1))
    return result


def _parse_cargo_toml(root: str, rel: str) -> dict:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return {}
    result: dict[str, Any] = {"name": "", "version": "", "dependencies": []}
    nm = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, re.M)
    if nm:
        result["name"] = nm.group(1)
    vm = re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', content, re.M)
    if vm:
        result["version"] = vm.group(1)
    sec = re.search(r"\[dependencies\]\s*\n(.*?)(?:\n\[|\Z)", content, re.S)
    if sec:
        for dm in re.finditer(r"^([A-Za-z0-9_-]+)\s*=", sec.group(1), re.M):
            result["dependencies"].append(dm.group(1))
    return result


def _parse_gemfile(root: str, rel: str) -> list[dict]:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return []
    gems: list[dict] = []
    for m in re.finditer(
        r"""gem\s+['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]*)['"]\s*)?""", content
    ):
        gems.append({"name": m.group(1), "version": m.group(2) or ""})
    return gems


def _parse_composer_json(root: str, rel: str) -> dict:
    content = _safe_read(os.path.join(root, rel))
    if not content:
        return {}
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {}
    return {
        "name": data.get("name", ""),
        "require": sorted(data.get("require", {}).keys()),
    }


def collect_marker_data(
    files: list[dict], root: str
) -> dict[str, Any]:
    """Parse all recognised marker files and collect structured data."""
    fmap: dict[str, list[str]] = defaultdict(list)
    for f in files:
        fmap[os.path.basename(f["path"])].append(f["path"])

    deps: dict[str, list[dict]] = {
        "python": [], "npm": [], "java": [], "go": [], "rust": [], "ruby": [],
    }
    env_vars: list[str] = []
    docker_svcs: list[dict] = []
    service_graph: list[dict] = []
    frameworks: set[str] = set()

    # Detect from marker filenames
    for f in files:
        bn = os.path.basename(f["path"])
        if bn in FRAMEWORK_MARKERS:
            frameworks.add(FRAMEWORK_MARKERS[bn])

    # package.json
    for rel in fmap.get("package.json", []):
        parsed = _parse_package_json(root, rel)
        if not parsed:
            continue
        for d in parsed.get("dependencies", []):
            deps["npm"].append({"name": d})
        all_npm = set(parsed.get("dependencies", []) + parsed.get("devDependencies", []))
        _npm_fw = {
            "react": "React", "vue": "Vue.js", "express": "Express",
            "next": "Next.js", "@angular/core": "Angular",
            "fastify": "Fastify", "koa": "Koa", "svelte": "Svelte",
            "nuxt": "Nuxt.js", "gatsby": "Gatsby",
        }
        for pkg, fw in _npm_fw.items():
            if pkg in all_npm:
                frameworks.add(fw)

    # requirements.txt
    for rel in fmap.get("requirements.txt", []):
        parsed_deps = _parse_requirements_txt(root, rel)
        deps["python"].extend(parsed_deps)
        names = {d["name"].lower() for d in parsed_deps}
        for pkg, fw in [("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django")]:
            if pkg in names:
                frameworks.add(fw)

    # pyproject.toml
    for rel in fmap.get("pyproject.toml", []):
        parsed = _parse_pyproject_toml(root, rel)
        for d in parsed.get("dependencies", []):
            deps["python"].append({"name": d, "version": ""})
        names = {d.lower() for d in parsed.get("dependencies", [])}
        for pkg, fw in [("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django")]:
            if pkg in names:
                frameworks.add(fw)

    # docker-compose
    for name in ("docker-compose.yml", "docker-compose.yaml"):
        for rel in fmap.get(name, []):
            svcs = _parse_docker_compose(root, rel)
            docker_svcs.extend(svcs)
            for svc in svcs:
                for dep in svc.get("depends_on", []):
                    service_graph.append({
                        "from": svc["name"], "to": dep, "reason": "depends_on",
                    })

    # .env files
    for name in (".env.example", ".env.sample"):
        for rel in fmap.get(name, []):
            env_vars.extend(_parse_env_file(root, rel))

    # pom.xml
    for rel in fmap.get("pom.xml", []):
        parsed = _parse_pom_xml(root, rel)
        for d in parsed.get("dependencies", []):
            deps["java"].append({"name": d})
        if any("spring" in d.lower() for d in parsed.get("dependencies", [])):
            frameworks.add("Spring Boot")

    # build.gradle / build.gradle.kts
    for name in ("build.gradle", "build.gradle.kts"):
        for rel in fmap.get(name, []):
            gdeps = _parse_build_gradle(root, rel)
            for d in gdeps:
                deps["java"].append({"name": d})
            if any("spring" in d.lower() for d in gdeps):
                frameworks.add("Spring Boot")

    # go.mod
    for rel in fmap.get("go.mod", []):
        parsed = _parse_go_mod(root, rel)
        for r in parsed.get("requires", []):
            deps["go"].append({"name": r})
        reqs = " ".join(parsed.get("requires", []))
        if "gin" in reqs:
            frameworks.add("Gin")
        if "echo" in reqs:
            frameworks.add("Echo")

    # Cargo.toml
    for rel in fmap.get("Cargo.toml", []):
        parsed = _parse_cargo_toml(root, rel)
        for d in parsed.get("dependencies", []):
            deps["rust"].append({"name": d})
        cdeps = " ".join(parsed.get("dependencies", []))
        if "actix" in cdeps:
            frameworks.add("Actix")
        if "rocket" in cdeps:
            frameworks.add("Rocket")

    # Gemfile
    for rel in fmap.get("Gemfile", []):
        gems = _parse_gemfile(root, rel)
        for g in gems:
            deps["ruby"].append({"name": g["name"]})
        if any(g["name"] == "rails" for g in gems):
            frameworks.add("Ruby on Rails")

    # composer.json
    for rel in fmap.get("composer.json", []):
        parsed = _parse_composer_json(root, rel)
        if "laravel/framework" in parsed.get("require", []):
            frameworks.add("Laravel")

    # Deduplicate
    env_vars = sorted(set(env_vars))
    for key in deps:
        seen: set[str] = set()
        unique: list[dict] = []
        for d in deps[key]:
            if d["name"] not in seen:
                seen.add(d["name"])
                unique.append(d)
        deps[key] = unique

    return {
        "dependencies": deps,
        "env_variables": env_vars,
        "docker_services": docker_svcs,
        "service_graph": service_graph,
        "frameworks": sorted(frameworks),
    }


# =====================================================================
# SECTION 5 — Component Detection (strict 2-of-3 rule)
# =====================================================================

_FRONTEND_MARKERS: set[str] = {
    "vite.config.ts", "vite.config.js", "next.config.js", "next.config.mjs",
    "angular.json", "nuxt.config.js", "nuxt.config.ts",
}
_BACKEND_MARKERS: set[str] = {
    "requirements.txt", "pyproject.toml", "Pipfile", "go.mod",
    "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json",
}
_FRONTEND_NAMES: set[str] = {"frontend", "client", "web", "ui"}
_BACKEND_NAMES: set[str] = {"backend", "server", "api"}
_SERVICE_NAMES: set[str] = {"service", "svc", "microservice"}
_WORKER_NAMES: set[str] = {"worker", "scheduler", "cron", "jobs", "consumer"}
_LIBRARY_NAMES: set[str] = {"lib", "library", "sdk", "packages", "shared", "common"}
_CLI_NAMES: set[str] = {"cli", "cmd", "command"}


def _classify_component_type(
    dir_path: str, dir_files: list[dict], basenames: set[str],
    direct_basenames: Optional[set[str]] = None,
) -> str:
    dn = os.path.basename(dir_path).lower() if dir_path != "." else ""
    # Use direct-level basenames for marker checks when available
    top_bn = direct_basenames if direct_basenames else basenames

    if top_bn & _FRONTEND_MARKERS:
        return "frontend"
    if top_bn & _BACKEND_MARKERS:
        return "backend"

    if dn in _FRONTEND_NAMES:
        return "frontend"
    if dn in _BACKEND_NAMES:
        return "backend"
    if dn in _SERVICE_NAMES:
        return "service"
    if dn in _WORKER_NAMES:
        return "worker"
    if dn in _LIBRARY_NAMES:
        return "library"
    if dn in _CLI_NAMES:
        return "cli"

    if basenames & {"Program.cs", "Startup.cs"}:
        return "backend"
    if basenames & {"main.go", "main.py", "app.py", "server.py"}:
        return "backend"
    if basenames & {"main.tsx", "main.jsx", "App.tsx", "App.jsx"}:
        return "frontend"

    if "package.json" in basenames:
        return "frontend"

    return "unknown"


def _find_entry_file(
    dir_files: list[dict], all_entry_names: set[str]
) -> Optional[str]:
    """Find the best entry file in a list of component files.

    Prefers files at shallower depth within the component.
    """
    _PRIORITY = [
        "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
        "Program.cs", "Startup.cs",
        "main.go", "main.rs",
        "Main.java", "Application.java",
        "server.ts", "server.js", "app.ts", "app.js",
        "main.tsx", "main.jsx", "main.ts", "main.js",
        "index.tsx", "index.jsx", "index.ts", "index.js",
        "app.rb", "index.php",
    ]
    # Group by basename → list of full paths, sorted by depth (shallowest first)
    from collections import defaultdict as _dd
    by_name: dict[str, list[str]] = _dd(list)
    for f in dir_files:
        by_name[os.path.basename(f["path"])].append(f["path"])
    for paths in by_name.values():
        paths.sort(key=lambda p: p.count("/"))
    for name in _PRIORITY:
        if name in by_name:
            return by_name[name][0]  # shallowest match
    return None


def _scoped_languages(dir_files: list[dict]) -> list[str]:
    """Detect languages scoped to a set of files."""
    counts: dict[str, int] = defaultdict(int)
    for f in dir_files:
        lang = EXTENSION_TO_LANGUAGE.get(f["extension"])
        if lang and lang not in {"Markdown", "JSON", "YAML", "HTML", "CSS"}:
            counts[lang] += 1
    return sorted(l for l, c in counts.items() if c >= 1)


def detect_components(
    files: list[dict], languages: list[str]
) -> list[dict]:
    """Detect components using strict 2-of-3 rule."""
    # Build entry file names for detected languages
    all_entry_names: set[str] = set()
    for lang in languages:
        all_entry_names |= ENTRY_FILES.get(lang, set())
    # Also include common ones always
    all_entry_names |= {
        "main.py", "app.py", "server.py", "manage.py",
        "index.ts", "index.js", "App.tsx", "server.ts", "server.js",
        "Program.cs", "Startup.cs", "main.go", "main.rs",
        "Main.java", "Application.java", "app.rb", "index.php",
    }

    # Candidate directories: top-level, second-level, and root
    candidates: set[str] = {"."}
    for f in files:
        parts = f["path"].split("/")
        if len(parts) >= 2:
            candidates.add(parts[0])
        if len(parts) >= 3:
            candidates.add(parts[0] + "/" + parts[1])

    raw: list[dict] = []
    for dir_path in sorted(candidates):
        prefix = (dir_path + "/") if dir_path != "." else ""
        dir_files = [f for f in files if f["path"].startswith(prefix)] if prefix else files
        if not dir_files:
            continue

        basenames = {os.path.basename(f["path"]) for f in dir_files}

        # Rule A — recognised entry file
        rule_a = bool(basenames & all_entry_names)

        # Rule B — 5+ source files
        src_count = sum(1 for f in dir_files if f["extension"] in SOURCE_EXTENSIONS)
        rule_b = src_count >= 5

        # Rule C — runtime marker scoped to this folder (directly in it, not nested)
        direct_files = (
            [f for f in dir_files if "/" not in f["path"]]
            if dir_path == "." else
            [f for f in dir_files
             if f["path"].count("/") == (dir_path.count("/") + 1)]
        )
        direct_basenames = {os.path.basename(f["path"]) for f in direct_files}
        rule_c = bool(direct_basenames & RUNTIME_MARKERS)

        if sum([rule_a, rule_b, rule_c]) < 2:
            continue

        comp_type = _classify_component_type(dir_path, dir_files, basenames, direct_basenames)
        entry_file = _find_entry_file(dir_files, all_entry_names)
        comp_langs = _scoped_languages(dir_files)

        raw.append({
            "name": os.path.basename(dir_path) if dir_path != "." else "root",
            "type": comp_type,
            "root_path": dir_path,
            "entry_file": entry_file,
            "file_count": len(dir_files),
            "languages": comp_langs,
            # backward compat
            "entry_points": [entry_file] if entry_file else [],
            "markers": sorted(direct_basenames & RUNTIME_MARKERS),
        })

    # Suppress nested: if a parent is a component, drop children
    raw.sort(key=lambda c: c["root_path"].count("/"))
    accepted: list[dict] = []
    for comp in raw:
        is_nested = any(
            comp["root_path"].startswith(a["root_path"] + "/")
            for a in accepted if a["root_path"] != "."
        )
        if not is_nested:
            accepted.append(comp)

    # Drop "." root only if sub-components cover all significant source files
    non_root = [c for c in accepted if c["root_path"] != "."]
    root_comp = next((c for c in accepted if c["root_path"] == "."), None)
    if non_root and root_comp:
        claimed = [c["root_path"] + "/" for c in non_root]
        unclaimed_src = sum(
            1 for f in files
            if f["extension"] in SOURCE_EXTENSIONS
            and not any(f["path"].startswith(p) for p in claimed)
        )
        if unclaimed_src >= 5:
            # Root has significant unclaimed files — keep it as a component
            root_comp["name"] = "root"
        else:
            accepted = non_root

    return accepted


# =====================================================================
# SECTION 6 — Import Graph (static, no execution)
# =====================================================================

_PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M
)
_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]"""
    r"""|require\(\s*['"]([^'"]+)['"]\s*\))""",
    re.M,
)
_JAVA_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)\s*;", re.M)
_GO_IMPORT_BLOCK = re.compile(r'import\s*\((.*?)\)', re.S)
_GO_IMPORT_SINGLE = re.compile(r'"([^"]+)"')


def _build_import_graph(
    files: list[dict],
    languages: list[str],
    root: str,
    components: list[dict],
) -> dict:
    """Build file-level and module-level import graphs."""
    file_edges: list[dict] = []
    seen: set[tuple[str, str]] = set()

    # Build lookup sets
    all_paths: set[str] = {f["path"] for f in files}
    # Local (prefix-stripped) paths per component
    comp_local: dict[str, set[str]] = {}
    for comp in components:
        prefix = (comp["root_path"] + "/") if comp["root_path"] != "." else ""
        local: set[str] = set()
        for f in files:
            p = f["path"]
            if prefix and p.startswith(prefix):
                local.add(p[len(prefix):])
            elif not prefix:
                local.add(p)
        comp_local[comp["root_path"]] = local

    def _comp_for_file(path: str) -> Optional[dict]:
        for c in components:
            pref = (c["root_path"] + "/") if c["root_path"] != "." else ""
            if pref and path.startswith(pref):
                return c
            if not pref and c["root_path"] == ".":
                return c
        return None

    def _add_edge(src: str, tgt: str) -> None:
        key = (src, tgt)
        if key not in seen and src != tgt:
            seen.add(key)
            file_edges.append({"from": src, "to": tgt})

    # ── Python imports ──
    if "Python" in languages:
        py_files = [f for f in files if f["extension"] == ".py"]
        for f in py_files:
            content = _safe_read(os.path.join(root, f["path"]))
            if not content:
                continue
            comp = _comp_for_file(f["path"])
            if not comp:
                continue
            prefix = (comp["root_path"] + "/") if comp["root_path"] != "." else ""
            local_set = comp_local.get(comp["root_path"], set())
            top_dirs = {
                p.split("/")[0] for p in local_set if "/" in p
            }

            for m in _PY_IMPORT_RE.finditer(content):
                module = m.group(1) or m.group(2)
                if not module:
                    continue
                top = module.split(".")[0]
                if top not in top_dirs:
                    continue
                as_path = module.replace(".", "/")
                resolved = None
                if as_path + ".py" in local_set:
                    resolved = as_path + ".py"
                elif (as_path + "/__init__.py") in local_set:
                    resolved = as_path + "/__init__.py"
                if resolved:
                    _add_edge(f["path"], prefix + resolved if prefix else resolved)

    # ── JS / TS imports ──
    if any(l in languages for l in ("JavaScript", "TypeScript")):
        js_exts = {".js", ".jsx", ".ts", ".tsx", ".mjs"}
        js_files = [f for f in files if f["extension"] in js_exts]
        for f in js_files:
            content = _safe_read(os.path.join(root, f["path"]))
            if not content:
                continue
            comp = _comp_for_file(f["path"])
            prefix = (comp["root_path"] + "/") if comp and comp["root_path"] != "." else ""
            local_set = comp_local.get(comp["root_path"], set()) if comp else set()

            src_local = f["path"]
            if prefix and src_local.startswith(prefix):
                src_local = src_local[len(prefix):]

            for m in _JS_IMPORT_RE.finditer(content):
                target = m.group(1) or m.group(2)
                if not target or not target.startswith("."):
                    continue
                src_dir = os.path.dirname(src_local)
                raw = os.path.normpath(os.path.join(src_dir, target)).replace("\\", "/")
                resolved = None
                if raw in local_set:
                    resolved = raw
                else:
                    for ext in (".ts", ".tsx", ".js", ".jsx"):
                        if raw + ext in local_set:
                            resolved = raw + ext
                            break
                    if not resolved:
                        for ext in (".ts", ".tsx", ".js", ".jsx"):
                            idx = raw + "/index" + ext
                            if idx in local_set:
                                resolved = idx
                                break
                if resolved:
                    _add_edge(f["path"], prefix + resolved if prefix else resolved)

    # ── Java imports ──
    if "Java" in languages:
        java_files = [f for f in files if f["extension"] == ".java"]
        # Guess base package from directory structure
        base_pkg = ""
        for jf in java_files:
            content = _safe_read(os.path.join(root, jf["path"]))
            if content:
                pm = re.search(r"^\s*package\s+([\w.]+)\s*;", content, re.M)
                if pm:
                    parts = pm.group(1).split(".")
                    if len(parts) >= 2:
                        base_pkg = ".".join(parts[:2])
                        break
        if not base_pkg:
            # Fallback: use most common top-2 package segments
            pass

        java_path_set = {f["path"] for f in java_files}
        for jf in java_files:
            content = _safe_read(os.path.join(root, jf["path"]))
            if not content:
                continue
            for m in _JAVA_IMPORT_RE.finditer(content):
                imp = m.group(1)
                if imp.startswith(("java.", "javax.", "sun.")):
                    continue
                if base_pkg and not imp.startswith(base_pkg):
                    continue
                # Convert to path
                parts = imp.split(".")
                candidate = "/".join(parts) + ".java"
                # Search in all_paths (might need src/main/java prefix)
                matched = None
                for p in java_path_set:
                    if p.endswith(candidate) or p.endswith("/" + candidate):
                        matched = p
                        break
                if matched:
                    _add_edge(jf["path"], matched)

    # ── Go imports ──
    if "Go" in languages:
        go_files = [f for f in files if f["extension"] == ".go"]
        # Find go.mod to get module name
        go_module = ""
        for f in files:
            if os.path.basename(f["path"]) == "go.mod":
                parsed = _parse_go_mod(root, f["path"])
                go_module = parsed.get("module", "")
                break

        go_path_set = {f["path"] for f in go_files}
        for gf in go_files:
            content = _safe_read(os.path.join(root, gf["path"]))
            if not content:
                continue
            # Parse import blocks and single imports
            all_imports: list[str] = []
            for block in _GO_IMPORT_BLOCK.finditer(content):
                for im in _GO_IMPORT_SINGLE.finditer(block.group(1)):
                    all_imports.append(im.group(1))
            for im in re.finditer(r'^\s*import\s+"([^"]+)"', content, re.M):
                all_imports.append(im.group(1))

            for imp in all_imports:
                if not go_module or not imp.startswith(go_module):
                    continue
                # Convert module path to file path
                rel_pkg = imp[len(go_module):].lstrip("/")
                # Find any .go file in that package directory
                for gp in go_path_set:
                    gp_dir = os.path.dirname(gp)
                    if gp_dir == rel_pkg or gp_dir.endswith("/" + rel_pkg):
                        _add_edge(gf["path"], gp)
                        break

    # ── Module-level graph ──
    # Group by parent directory
    def _module(path: str) -> str:
        d = os.path.dirname(path)
        return d if d else "(root)"

    mod_edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    for e in file_edges:
        sm = _module(e["from"])
        tm = _module(e["to"])
        if sm != tm:
            mod_edge_counts[(sm, tm)] += 1

    module_edges = [
        {"from": s, "to": t, "import_count": c}
        for (s, t), c in sorted(mod_edge_counts.items(), key=lambda x: -x[1])
    ]

    return {"file_level": file_edges, "module_level": module_edges}


# =====================================================================
# SECTION 7 — API Route Detection
# =====================================================================

_PY_ROUTE_RE = re.compile(
    r"@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*[\"']([^\"']+)[\"']",
    re.I,
)
_PY_DJANGO_URL = re.compile(
    r"""(?:path|re_path)\s*\(\s*[\"']([^\"']+)[\"']""",
)
_JS_ROUTE_RE = re.compile(
    r"(?:app|router)\.(get|post|put|delete|patch|all)\s*\(\s*[\"']([^\"']+)[\"']",
    re.I,
)
_JAVA_ROUTE_RE = re.compile(
    r"@(Get|Post|Put|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']+)[\"']",
    re.I,
)
_GO_ROUTE_RE = re.compile(
    r"""(?:http\.HandleFunc|[a-z]\.(?:GET|POST|PUT|DELETE|PATCH|Handle))\s*\(\s*[\"']([^\"']+)[\"']""",
    re.I,
)
_RUBY_ROUTE_RE = re.compile(
    r"^\s*(get|post|put|delete|patch|resources?)\s+[\"':]+([^\"',\s]+)",
    re.M | re.I,
)


def _detect_routes(
    files: list[dict], languages: list[str], root: str, components: list[dict]
) -> list[dict]:
    """Detect API routes for supported languages/frameworks."""
    routes: list[dict] = []

    def _comp_name_for(path: str) -> str:
        for c in components:
            pref = (c["root_path"] + "/") if c["root_path"] != "." else ""
            if pref and path.startswith(pref):
                return c["name"]
            if not pref and c["root_path"] == ".":
                return c["name"]
        return ""

    # Python routes
    if "Python" in languages:
        for f in files:
            if f["extension"] != ".py":
                continue
            content = _safe_read(os.path.join(root, f["path"]))
            if not content:
                continue
            for m in _PY_ROUTE_RE.finditer(content):
                routes.append({
                    "method": m.group(1).upper(),
                    "path": m.group(2),
                    "file": f["path"],
                    "component": _comp_name_for(f["path"]),
                })
            # Django url patterns
            for m in _PY_DJANGO_URL.finditer(content):
                routes.append({
                    "method": "ANY",
                    "path": m.group(1),
                    "file": f["path"],
                    "component": _comp_name_for(f["path"]),
                })

    # JS/TS routes
    if any(l in languages for l in ("JavaScript", "TypeScript")):
        for f in files:
            if f["extension"] not in {".js", ".ts", ".jsx", ".tsx", ".mjs"}:
                continue
            content = _safe_read(os.path.join(root, f["path"]))
            if not content:
                continue
            for m in _JS_ROUTE_RE.finditer(content):
                routes.append({
                    "method": m.group(1).upper(),
                    "path": m.group(2),
                    "file": f["path"],
                    "component": _comp_name_for(f["path"]),
                })
            # Next.js API routes
            if "/api/" in f["path"] and "export" in (content or ""):
                if re.search(r"export\s+default\s+function", content):
                    routes.append({
                        "method": "ANY",
                        "path": "/" + f["path"].split("/pages/")[-1].replace(".ts", "").replace(".js", ""),
                        "file": f["path"],
                        "component": _comp_name_for(f["path"]),
                    })

    # Java routes
    if "Java" in languages:
        for f in files:
            if f["extension"] != ".java":
                continue
            content = _safe_read(os.path.join(root, f["path"]))
            if not content:
                continue
            for m in _JAVA_ROUTE_RE.finditer(content):
                method_word = m.group(1).upper()
                method = {
                    "GET": "GET", "POST": "POST", "PUT": "PUT",
                    "DELETE": "DELETE", "REQUEST": "ANY",
                }.get(method_word, method_word)
                routes.append({
                    "method": method,
                    "path": m.group(2),
                    "file": f["path"],
                    "component": _comp_name_for(f["path"]),
                })

    # Go routes
    if "Go" in languages:
        for f in files:
            if f["extension"] != ".go":
                continue
            content = _safe_read(os.path.join(root, f["path"]))
            if not content:
                continue
            for m in _GO_ROUTE_RE.finditer(content):
                routes.append({
                    "method": "ANY",
                    "path": m.group(1),
                    "file": f["path"],
                    "component": _comp_name_for(f["path"]),
                })

    # Ruby routes
    if "Ruby" in languages:
        for f in files:
            if os.path.basename(f["path"]) != "routes.rb":
                continue
            content = _safe_read(os.path.join(root, f["path"]))
            if not content:
                continue
            for m in _RUBY_ROUTE_RE.finditer(content):
                method_word = m.group(1).lower()
                method = method_word.upper() if method_word in {"get", "post", "put", "delete", "patch"} else "ANY"
                routes.append({
                    "method": method,
                    "path": m.group(2),
                    "file": f["path"],
                    "component": _comp_name_for(f["path"]),
                })

    return routes


# =====================================================================
# SECTION 8 — Execution Flow Inference
# =====================================================================

def _infer_execution_flow(
    components: list[dict],
    import_graph: dict,
    routes: list[dict],
    files: list[dict],
) -> list[dict]:
    """Infer execution flow deterministically from scan data."""
    flow: list[dict] = []
    step = 0

    # Step 1: entry / startup
    entry_files = [c["entry_file"] for c in components if c.get("entry_file")]
    if entry_files:
        step += 1
        flow.append({"step": step, "phase": "entry / startup", "files": entry_files})

    # Build import edge lookup: target → list of sources
    imported_by: dict[str, list[str]] = defaultdict(list)
    imports_of: dict[str, list[str]] = defaultdict(list)
    for e in import_graph.get("file_level", []):
        imported_by[e["to"]].append(e["from"])
        imports_of[e["from"]].append(e["to"])

    all_paths_set = {f["path"] for f in files}

    # Step 2: configuration
    config_keywords = {"config", "settings", ".env", "configuration"}
    config_files = [
        f["path"] for f in files
        if any(kw in os.path.basename(f["path"]).lower() for kw in config_keywords)
        and f["extension"] in SOURCE_EXTENSIONS | {".py", ".ts", ".js", ".json", ".yaml", ".yml", ".toml"}
    ]
    if config_files:
        step += 1
        flow.append({"step": step, "phase": "configuration / settings", "files": config_files[:5]})

    # Step 3: routing
    route_files = sorted({r["file"] for r in routes})
    if route_files:
        step += 1
        flow.append({"step": step, "phase": "routing / url dispatch", "files": route_files[:5]})

    # Step 4: service / business logic — files imported by route files
    service_files: list[str] = []
    for rf in route_files:
        for target in imports_of.get(rf, []):
            if target not in route_files and target not in config_files:
                service_files.append(target)
    service_files = sorted(set(service_files))
    if not service_files:
        # Fallback: look for files in dirs named service/services/handlers
        service_files = [
            f["path"] for f in files
            if any(kw in f["path"].lower() for kw in ("/services/", "/service/", "/handlers/", "/usecases/"))
            and f["extension"] in SOURCE_EXTENSIONS
        ]
    if service_files:
        step += 1
        flow.append({"step": step, "phase": "service / business logic", "files": service_files[:5]})

    # Step 5: data access
    data_keywords = {"/db/", "/database/", "/models/", "/orm/", "/repository/", "/dao/", "/entities/", "/migrations/"}
    data_files = [
        f["path"] for f in files
        if any(kw in f["path"].lower() for kw in data_keywords)
        and f["extension"] in SOURCE_EXTENSIONS
    ]
    if data_files:
        step += 1
        flow.append({"step": step, "phase": "data access / persistence", "files": sorted(set(data_files))[:5]})

    return flow


# =====================================================================
# SECTION 9 — Key Files, Project Type, Frameworks
# =====================================================================

_KEY_FILE_ROLES: dict[str, str] = {
    "main.py": "entry", "app.py": "entry", "server.py": "entry",
    "manage.py": "entry", "Program.cs": "entry", "Startup.cs": "entry",
    "main.go": "entry", "main.rs": "entry",
    "Main.java": "entry", "Application.java": "entry",
    "server.js": "entry", "server.ts": "entry",
    "main.tsx": "entry", "main.jsx": "entry",
    "main.ts": "entry", "main.js": "entry",
    "index.tsx": "entry", "index.jsx": "entry",
    "package.json": "dependency", "requirements.txt": "dependency",
    "pyproject.toml": "dependency", "Pipfile": "dependency",
    "go.mod": "dependency", "Cargo.toml": "dependency",
    "pom.xml": "dependency", "build.gradle": "dependency",
    "Gemfile": "dependency", "composer.json": "dependency",
    "Dockerfile": "docker", "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker",
    "tsconfig.json": "config", "vite.config.ts": "config",
    "vite.config.js": "config", "next.config.js": "config",
    "angular.json": "config", "Makefile": "build",
    ".env": "config", ".env.example": "config", ".env.sample": "config",
}


def _collect_key_files(files: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for f in files:
        bn = os.path.basename(f["path"])
        role = _KEY_FILE_ROLES.get(bn)
        if role and f["path"] not in seen:
            seen.add(f["path"])
            result.append({"path": f["path"], "role": role})
    return result


def _infer_project_type(
    components: list[dict],
    languages: list[str],
    frameworks: list[str],
    files: list[dict],
) -> str:
    comp_types = {c["type"] for c in components}
    meaningful = [c for c in components if c["type"] in {"frontend", "backend", "service"}]

    has_fe = "frontend" in comp_types
    has_be = "backend" in comp_types
    has_svc = "service" in comp_types

    if len(meaningful) >= 3 or (has_fe and has_be and has_svc):
        return "monorepo / multi-component app"
    if has_fe and (has_be or has_svc):
        return "full-stack app"
    if has_be and has_svc:
        return "monorepo / multi-component app"
    if has_fe:
        return "frontend web app"
    if has_be:
        return "backend API"
    if has_svc:
        return "backend API"

    # File-level fallback
    file_names = {os.path.basename(f["path"]) for f in files}
    fe_markers = {"vite.config.ts", "vite.config.js", "next.config.js", "angular.json"}
    be_markers = {"requirements.txt", "go.mod", "pom.xml", "Cargo.toml", "manage.py"}
    has_fe_signal = bool(file_names & fe_markers) or "React" in frameworks
    has_be_signal = bool(file_names & be_markers) or any(
        fw in frameworks for fw in ("FastAPI", "Flask", "Django", "Spring Boot", "Express")
    )

    if has_fe_signal and has_be_signal:
        return "full-stack app"
    if has_be_signal:
        return "backend API"
    if has_fe_signal:
        return "frontend web app"
    if "C#" in languages:
        return ".NET backend"

    return "unknown"


# =====================================================================
# SECTION 10 — Utility functions (shared with other modules)
# =====================================================================

def extract_zip(zip_path: str, dest_dir: str) -> str:
    """Extract a ZIP file safely into dest_dir."""
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            normalized = member.filename.replace("\\", "/").lstrip("/")
            parts = normalized.split("/")
            if any(p in IGNORED_DIRS for p in parts):
                continue
            # Prevent path traversal
            real_dest = os.path.realpath(os.path.join(dest_dir, normalized))
            if not real_dest.startswith(os.path.realpath(dest_dir)):
                raise ValueError(f"Unsafe path in ZIP: {member.filename}")
            zf.extract(member, dest_dir)
    return dest_dir


def unwrap_root_dir(root_dir: str) -> str:
    """If root contains only a single wrapper folder, return the inner path."""
    try:
        entries = os.listdir(root_dir)
    except OSError:
        return root_dir
    visible = [
        e for e in entries
        if not e.startswith(".") and e not in IGNORED_DIRS
    ]
    dirs = [e for e in visible if os.path.isdir(os.path.join(root_dir, e))]
    fil = [e for e in visible if os.path.isfile(os.path.join(root_dir, e))]
    if len(dirs) == 1 and len(fil) == 0:
        return os.path.join(root_dir, dirs[0])
    return root_dir


# =====================================================================
# SECTION 11 — Main orchestrator
# =====================================================================

def run_full_scan(effective_root: str) -> dict[str, Any]:
    """Run the complete scan on an extracted project directory.

    Returns a dict conforming to the full output schema.
    """
    # 1. File walk
    files = walk_files(effective_root)

    # 2. Language detection
    languages, confidence_scores = detect_languages(files)

    # 3. Marker file parsing
    marker_data = collect_marker_data(files, effective_root)
    frameworks = marker_data["frameworks"]
    dependencies = marker_data["dependencies"]
    docker_services = marker_data["docker_services"]
    service_graph = marker_data["service_graph"]
    env_variables = marker_data["env_variables"]

    # 4. Component detection
    components = detect_components(files, languages)

    # 5. Import graph
    import_graph = _build_import_graph(files, languages, effective_root, components)

    # 6. Route detection
    routes = _detect_routes(files, languages, effective_root, components)

    # 7. Execution flow
    execution_flow = _infer_execution_flow(components, import_graph, routes, files)

    # 8. Key files + project type
    key_files = _collect_key_files(files)
    project_type = _infer_project_type(components, languages, frameworks, files)

    # 9. Collect top-level entry points
    entry_points = sorted({
        c["entry_file"] for c in components if c.get("entry_file")
    })

    # 10. Extension counts (backward compat)
    ext_counts: dict[str, int] = defaultdict(int)
    for f in files:
        if f["extension"]:
            ext_counts[f["extension"]] += 1

    # 11. Top-level dirs (backward compat)
    top_level_dirs = sorted({
        f["path"].split("/")[0]
        for f in files
        if "/" in f["path"] and f["path"].split("/")[0] not in IGNORED_DIRS
    })

    return {
        # ── New schema fields ──
        "project_type": project_type,
        "confidence_scores": confidence_scores,
        "languages": languages,
        "frameworks": frameworks,
        "components": components,
        "dependencies": dependencies,
        "service_graph": service_graph,
        "routes": routes,
        "import_graph": import_graph,
        "execution_flow": execution_flow,
        "key_files": key_files,
        "entry_points": entry_points,
        "env_variables": env_variables,
        "docker_services": docker_services,
        # ── Backward-compat fields ──
        "files": files,
        "extension_counts": dict(sorted(ext_counts.items())),
        "top_level_dirs": top_level_dirs,
    }

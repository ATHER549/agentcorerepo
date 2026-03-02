import json
import subprocess
import tomllib
import re


def normalize(pkg: str) -> str:
    """
    Normalize package names according to PEP 503
    """
    return re.split(r"[<>=!~ ]", pkg)[0].lower().replace("_", "-")


def detect_package_state():
    # -----------------------------
    # 1. Read declared dependencies
    # -----------------------------
    with open("pyproject.toml", "rb") as f:
        toml = tomllib.load(f)

    declared = set()

    # Runtime dependencies
    for dep in toml.get("project", {}).get("dependencies", []):
        declared.add(normalize(dep))

    # Optional / dev dependencies
    for group in toml.get("project", {}).get("optional-dependencies", {}).values():
        for dep in group:
            declared.add(normalize(dep))

    # -----------------------------
    # 2. Read installed packages
    # -----------------------------
    result = subprocess.check_output(
        ["uv", "pip", "list", "--format=json"],
        text=True
    )
    installed = {
        pkg["name"].lower().replace("_", "-"): pkg["version"]
        for pkg in json.loads(result)
    }

    installed_names = set(installed.keys())

    # -----------------------------
    # 3. Compare
    # -----------------------------
    declared_and_installed = sorted(declared & installed_names)

    installed_but_not_declared = sorted(installed_names - declared)

    declared_but_not_installed = sorted(declared - installed_names)

    # -----------------------------
    # 4. Return structured result
    # -----------------------------
    return {
        "declared_and_installed": [
            {"name": pkg, "version": installed[pkg]}
            for pkg in declared_and_installed
        ],
        "installed_but_not_declared": [
            {"name": pkg, "version": installed[pkg]}
            for pkg in installed_but_not_declared
        ],
        "declared_but_not_installed": declared_but_not_installed
    }

if __name__ == "__main__":
    import pprint
    pprint.pprint(detect_package_state())
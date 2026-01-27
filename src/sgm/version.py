from __future__ import annotations

import os
from dataclasses import dataclass

APP_NAME = "Sprint Game Manager"


@dataclass(frozen=True)
class BuildInfo:
    build: str | None
    git_sha: str | None


def get_build_info() -> BuildInfo:
    # 1) Explicit override (useful for CI/dev testing)
    env_build = os.environ.get("SGM_BUILD")
    env_sha = os.environ.get("SGM_GIT_SHA")
    if env_build:
        return BuildInfo(build=env_build, git_sha=env_sha)

    # 2) Generated at build time by build_exe.ps1
    try:
        from sgm._build import BUILD as build  # type: ignore
        from sgm._build import GIT_SHA as git_sha  # type: ignore

        return BuildInfo(build=str(build) if build else None, git_sha=str(git_sha) if git_sha else None)
    except Exception:
        return BuildInfo(build=None, git_sha=None)


def main_window_title() -> str:
    info = get_build_info()
    if info.build:
        return f"{APP_NAME} (build:{info.build})"
    return APP_NAME


def version_string() -> str:
    """Return a human-readable version string."""
    info = get_build_info()
    if info.build and info.git_sha:
        return f"Build {info.build} ({info.git_sha})"
    if info.build:
        return f"Build {info.build}"
    if info.git_sha:
        return f"Dev ({info.git_sha})"
    return "Development"

"""Locate experimental evidence that may live outside the repository.

The repository keeps only results (code, configs, processed dataset, catalogue, reports).
Raw experiments, campaign manifests, audits and historical documents live in an external
archive with the same relative layout (``data/raw/...``, ``data/campaigns/...``,
``data/audits/...``, ``docs/history/...``).

A repository-relative path such as ``data/raw/small_v1/<exp>`` is resolved by looking first in
the repository (new, git-ignored collections land there) and then in the archive.

Archive location: environment variable ``SMARTMALL_ARCHIVE``, otherwise the sibling folder
``../smartmall-data-archive`` next to the repository.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def archive_root():
    env = os.environ.get("SMARTMALL_ARCHIVE")
    return Path(env) if env else REPO_ROOT.parent / "smartmall-data-archive"


def search_roots():
    return [REPO_ROOT, archive_root()]


def resolve(path):
    """Return an existing location for a repository-relative evidence path.

    Absolute paths and paths that exist relative to the current directory are returned as they are.
    Otherwise the repository and then the archive are searched; if nothing exists, the
    repository location is returned so that error messages show the expected path.
    """
    p = Path(path)
    if p.is_absolute() or p.exists():
        return p
    for root in search_roots():
        if (root / p).exists():
            return root / p
    return REPO_ROOT / p

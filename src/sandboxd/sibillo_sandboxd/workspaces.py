"""Workspaces as tar archives, for backups and restores (SBX-020, ADR-0077).

An archive holds regular files, directories and symbolic links, named
relative to the workspace root. A link may point anywhere, as a Python
virtual environment's do, since nothing is written through it: an archive
with a member whose path goes through a link it made, with anything but
those three kinds, or with a path outside the workspace is refused as a
whole before a byte of it is written (ADR-0129).
"""

from __future__ import annotations

import posixpath
import tarfile
from pathlib import Path

ALLOWED_TYPES = frozenset({tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE})


class UnsafeArchiveError(ValueError):
    """An archive entry that would be written outside the workspace, or is not a plain file, folder or link."""


def _relative(name: str) -> str:
    """The entry's path inside the workspace, or an error when it leaves it."""
    if name.startswith("/"):
        raise UnsafeArchiveError(f"absolute path: {name}")
    normalized = posixpath.normpath(name)
    if normalized == ".." or normalized.startswith("../"):
        raise UnsafeArchiveError(f"path outside the workspace: {name}")
    return normalized


def check_archive(path: Path) -> None:
    """Refuse an archive with any entry the workspace must not receive."""
    links: set[str] = set()
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            name = _relative(member.name)
            if member.type not in ALLOWED_TYPES:
                raise UnsafeArchiveError(f"not a file, a folder or a link: {member.name}")
            # Nothing is written through a link the archive made: its folders are the workspace's own.
            parts = name.split("/")
            if any("/".join(parts[:depth]) in links for depth in range(1, len(parts) + 1)):
                raise UnsafeArchiveError(f"a path through a link: {member.name}")
            if member.type == tarfile.SYMTYPE:
                links.add(name)


# The skills of a sandbox are files and folders only (SBX-022, ADR-0096).
SKILL_TYPES = frozenset({tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE})


def check_skills_archive(path: Path) -> None:
    """Refuse an archive of skills with an entry outside /skills, or one that is not a file or a folder."""
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            _relative(member.name)
            if member.type not in SKILL_TYPES:
                raise UnsafeArchiveError(f"not a file or a folder: {member.name}")


def workspace_entries(source: Path, destination: Path, root: str) -> None:
    """Rewrite Docker's archive of the folder `root` as one named relative to that folder.

    Entries of other types than files, folders and links are left out, so that
    an export can always be imported again.
    """
    prefix = posixpath.basename(root.rstrip("/"))
    with tarfile.open(source, "r:") as archive, tarfile.open(destination, "w:") as result:
        for member in archive:
            if member.type not in ALLOWED_TYPES:
                continue
            name = posixpath.normpath(member.name)
            if name == prefix:
                continue
            if not name.startswith(f"{prefix}/"):
                raise UnsafeArchiveError(f"unexpected entry in the export: {member.name}")
            member.name = name.removeprefix(f"{prefix}/")
            result.addfile(member, archive.extractfile(member) if member.isreg() else None)

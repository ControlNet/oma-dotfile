"""Every write to an agent's config goes through Files.

Each method compares first and writes only when something changes. User-editable config is
backed up as `<name>.bak-<stamp>` before it is replaced; repo-owned code (plugins, extensions)
is not, since git history keeps its old versions. `changed` lists what this run wrote.
"""

import filecmp
import os
from pathlib import Path
import shutil

from omadotfile.console import info, warn

# Build artefacts in a local checkout; never installed.
IGNORED_NAMES = ("__pycache__",)


def same_tree(left: Path, right: Path) -> bool:
    """Whether two directories hold the same names and file contents, ignoring IGNORED_NAMES."""
    if not right.is_dir() or right.is_symlink():
        return False
    compare = filecmp.dircmp(left, right, ignore=list(IGNORED_NAMES))
    if compare.left_only or compare.right_only or compare.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(left, right, compare.common_files, shallow=False)
    if mismatch or errors:
        return False
    return all(same_tree(left / name, right / name) for name in compare.common_dirs)


class Files:
    def __init__(self, stamp: str, backup: bool = True, keep: int = 1):
        self.stamp = stamp
        self.backup_enabled = backup
        self.keep = keep
        self.changed: list[Path] = []

    def backup_path(self, path: Path) -> Path:
        return path.with_suffix(f"{path.suffix}.bak-{self.stamp}")

    def backup(self, path: Path) -> None:
        """Copy path to its backup for this run, unless backups are off or it does not exist."""
        if not self.backup_enabled or not path.exists():
            return
        _ = shutil.copy2(path, self.backup_path(path))
        self.prune(path)

    def prune(self, path: Path) -> None:
        """Keep only the newest `keep` backups of path."""
        # Order by the fixed-width stamp in the name: copy2 keeps the source's mtime, so a
        # config restored with an old mtime would otherwise make the newest backup look oldest.
        backups = sorted(path.parent.glob(f"{path.name}.bak-*"), key=lambda p: p.name)
        while len(backups) > self.keep:
            oldest = backups.pop(0)
            oldest.unlink()
            info(f"Removed old backup: {oldest.name}")

    def write_text(self, dst: Path, content: str, *, backup: bool = True,
                   mode: int | None = None) -> bool:
        """Write content to dst unless it is already there; `mode` applies to a new file."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.read_text(encoding="utf-8") == content:
            return False
        if backup:
            self.backup(dst)
        if mode is None:
            _ = dst.write_text(content, encoding="utf-8")
        else:
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                _ = handle.write(content)
        self.changed.append(dst)
        return True

    def copy(self, src: Path, dst: Path, *, backup: bool = True) -> bool:
        """Copy src to dst unless dst already has the same content."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file() and filecmp.cmp(src, dst, shallow=False):
            return False
        if backup:
            self.backup(dst)
        _ = shutil.copy2(src, dst)
        self.changed.append(dst)
        return True

    def replace_tree(self, src: Path, dst: Path) -> bool:
        """Make dst a copy of the src directory, removing whatever else dst holds."""
        if not src.exists():
            warn(f"Source directory not found: {src}")
            return False
        if same_tree(src, dst):
            return False
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        elif dst.exists():
            shutil.rmtree(dst)
        _ = shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
        self.changed.append(dst)
        return True

    def copy_items(self, src: Path, dst: Path) -> bool:
        """Replace each entry of the src directory in dst; other entries of dst stay."""
        if not src.exists():
            warn(f"Source directory not found: {src}")
            return False
        dst.mkdir(parents=True, exist_ok=True)
        changed = False
        for entry in sorted(src.iterdir()):
            if entry.name in IGNORED_NAMES:
                continue
            target = dst / entry.name
            if entry.is_dir():
                changed = self.replace_tree(entry, target) or changed
                continue
            if target.is_file() and not target.is_symlink() and filecmp.cmp(entry, target, shallow=False):
                continue
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            _ = shutil.copy2(entry, target)
            self.changed.append(target)
            changed = True
        return changed

    def retire(self, path: Path) -> None:
        """Rename a file that must no longer load to a backup name, even with backups off."""
        if not path.exists():
            return
        if path.suffix:
            backup_path = path.with_suffix(f"{path.suffix}.bak-{self.stamp}")
        else:
            backup_path = path.with_name(f"{path.name}.bak-{self.stamp}")
        if backup_path.exists():
            backup_path = backup_path.with_suffix(f".bak-{self.stamp}-{os.getpid()}")
        _ = path.rename(backup_path)
        self.changed.append(path)
        self.prune(path)

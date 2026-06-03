# Learnings - dynamic-folder-download

## Conventions Discovered

## Patterns to Follow

## Technical Notes


## pull.py Implementation (2026-02-04)

### Approach
- Used `git clone --depth 1 --branch {REPO_REV}` for shallow clone
- Leveraged `TemporaryDirectory` context manager for automatic cleanup
- Used `shutil.copytree(dirs_exist_ok=True)` to merge directories without deleting local files
- Maintained step numbering [1/4] through [4/4] for consistency with original shell script

### Key Design Decisions
1. **Platform detection**: `sys.platform == "win32"` for Windows-specific config path
2. **Backup strategy**: Timestamp-based suffixes (`.bak-{YYYYMMDD-HHMMSS}`)
3. **Error handling**: Capture git clone stderr and exit with code 1 on failure
4. **Directory merging**: `dirs_exist_ok=True` preserves local customizations

### Python stdlib modules used
- `subprocess`: git clone execution
- `pathlib.Path`: Cross-platform path handling
- `tempfile.TemporaryDirectory`: Auto-cleanup temp workspace
- `shutil.copy2`, `shutil.copytree`: File/directory operations with metadata preservation
- `datetime`: Timestamp generation for backups

### Verification commands
```bash
python3 -m py_compile pull.py  # Syntax check
python3 pull.py  # Actual execution (requires git)
```

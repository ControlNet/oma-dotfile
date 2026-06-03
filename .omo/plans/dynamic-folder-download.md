# Python Unified Pull Script (Git Clone Approach)

## TL;DR

> **Quick Summary**: 用单一 Python 脚本 `pull.py` 替代 `pull.sh` 和 `pull.ps1`,使用 `git clone --depth 1` 下载整个 repo,然后复制所需文件到配置目录。
>
> **Deliverables**:
> - 新建 `pull.py` (跨平台,基于 git clone)
> - 删除 `pull.sh` 和 `pull.ps1`
> - 更新 `README.md` 安装说明
> - `skills/` 目录提交到 Git (前置条件)
>
> **Estimated Effort**: Short (1-2 hours)
> **Parallel Execution**: NO - sequential (dependencies)
> **Critical Path**: Task 0 (commit skills) → Task 1 (create pull.py) → Task 2 (delete old scripts) → Task 3 (update README) → Task 4 (verify)

---

## Context

### Original Request
用户添加了 `plugins/` 和 `skills/` 目录,但 `pull.sh` 和 `pull.ps1` 使用硬编码的文件列表:
```bash
PLUGINS=("gotify-notify.js")
```
每次新增文件都需要手动更新脚本,不够灵活。

### Interview Summary
**Key Discussions**:
- **下载方式**: ~~GitHub Contents API~~ → **Git Clone** (更简单,无 API 限制)
- **目录结构**: 自动支持递归 (git clone 天然获取所有文件)
- **语言选择**: Python 3 替代 bash/ps1 (用户确认目标群体都有 Python + Git)
- **过渡策略**: 完全替换 (删除 pull.sh 和 pull.ps1)
- **文件过滤**: 下载所有文件,不按扩展名过滤

**Research Findings**:
- `plugins/`: 已 committed,扁平结构 (1 file)
- `skills/`: 未 tracked (`git status` 显示 `??`),需要先 commit
- 目录结构涉及多层嵌套 (skills/github-cli/references/)

### Why Git Clone over GitHub API

| 方面 | Git Clone | GitHub API |
|------|-----------|------------|
| **复杂度** | 简单: `git clone --depth 1` | 需要递归 API 调用 |
| **速度** | 快 (单次操作) | 慢 (多次 HTTP 请求) |
| **Rate Limit** | 无 | 60 req/hr |
| **依赖** | git (用户都有) | 无额外依赖 |
| **可靠性** | 高 | 中 (API 可能变化) |

---

## Work Objectives

### Core Objective
创建跨平台 Python 脚本替代 bash/ps1,使用 git clone 获取 repo 内容。

### Concrete Deliverables
- `pull.py`: Python 3 跨平台安装脚本 (基于 git clone)
- 删除 `pull.sh` 和 `pull.ps1`
- 更新 `README.md` 安装说明
- `skills/`: 目录 committed 到 Git

### Definition of Done
- [x] `curl ... | python3` 能自动下载所有 plugins/ 和 skills/ 文件
- [x] Windows 上 `python pull.py` 正常工作
- [x] 子目录结构正确创建 (如 skills/github-cli/references/)
- [x] 本地独有文件不被删除
- [x] git clone 失败时给出清晰错误信息

### Must Have
- 纯标准库 (subprocess, os, shutil, pathlib) — 无第三方依赖
- 使用 `git clone --depth 1` 获取 repo
- 支持指定 branch/tag/commit (REPO_REV)
- 子目录自动创建
- 跨平台路径处理 (使用 pathlib)
- 保持现有 backup 逻辑
- 环境变量配置 (REPO_OWNER, REPO_NAME, REPO_REV, CONFIG_DIR, NO_BACKUP)

### Must NOT Have (Guardrails)
- **MUST NOT** 删除本地存在但远程没有的文件 (只增不删)
- **MUST NOT** 添加第三方依赖 (只用标准库)
- **MUST NOT** 添加 retry/parallel/progress bar 等过度工程
- **MUST NOT** 改变现有的行为逻辑 (步骤顺序、backup 策略等)

---

## Verification Strategy (MANDATORY)

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**
>
> ALL tasks in this plan MUST be verifiable WITHOUT any human action.

### Test Decision
- **Infrastructure exists**: NO (standalone script)
- **Automated tests**: NO (but Python syntax check via py_compile)
- **Agent-Executed QA**: ALWAYS (mandatory)

### Agent-Executed QA Scenarios (MANDATORY — ALL tasks)

验证工具:
| Type | Tool | How Agent Verifies |
|------|------|-------------------|
| Python script | Bash (python3) | 运行脚本,检查输出和文件 |
| File comparison | Bash (diff/ls) | 比较下载结果与预期 |

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately):
└── Task 0: Commit skills/ directory to Git

Wave 2 (After Wave 1):
└── Task 1: Create pull.py with git clone approach

Wave 3 (After Wave 2):
└── Task 2: Delete pull.sh and pull.ps1

Wave 4 (After Wave 3):
└── Task 3: Update README.md with new installation commands

Wave 5 (After Wave 4):
└── Task 4: End-to-end verification

Critical Path: Task 0 → Task 1 → Task 2 → Task 3 → Task 4
Parallel Speedup: N/A (sequential dependencies)
```

### Dependency Matrix

| Task | Depends On | Blocks | Can Parallelize With |
|------|------------|--------|---------------------|
| 0 | None | 1 | None |
| 1 | 0 | 2, 3, 4 | None |
| 2 | 1 | 3 | None |
| 3 | 2 | 4 | None |
| 4 | 3 | None | None (final) |

---

## TODOs

- [x] 0. Commit skills/ directory to Git

  **What to do**:
  - 将 `skills/` 目录添加到 Git 并 commit
  - 这是后续 git clone 测试的前置条件

  **Must NOT do**:
  - 不要 push (只 commit,让用户决定何时 push)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单一简单操作,无复杂逻辑
  - **Skills**: [`git-master`]
    - `git-master`: Git commit 操作

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (alone)
  - **Blocks**: 1, 2, 3, 4
  - **Blocked By**: None

  **References**:
  - `skills/` - 需要 commit 的目录

  **Acceptance Criteria**:

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: skills/ directory is tracked by Git
    Tool: Bash
    Preconditions: skills/ directory exists locally
    Steps:
      1. git add skills/
      2. git commit -m "feat: add skills directory"
      3. git ls-files skills/ | wc -l
    Expected Result: Output > 0 (files are tracked)
    Evidence: git status output captured
  ```

  **Commit**: YES
  - Message: `feat: add skills directory for dynamic download`
  - Files: `skills/**/*`

---

- [x] 1. Create pull.py with git clone approach

  **What to do**:
  - 创建 `pull.py`,功能等同于原 `pull.sh` + `pull.ps1`:
    1. 使用 `git clone --depth 1 --branch {REV}` 克隆 repo 到临时目录
    2. 从临时目录复制 config 文件 (opencode.jsonc, oh-my-opencode.jsonc, _AGENTS.md)
    3. 从临时目录复制 plugins/ 和 skills/ 目录 (保留完整结构)
    4. 备份现有文件 (如果 NO_BACKUP != "1")
    5. 重命名 legacy .json 文件
    6. 清理临时目录
  - 使用 subprocess 调用 git
  - 使用 pathlib 实现跨平台路径处理
  - 使用 shutil.copytree() 复制目录 (自动递归)
  - 保持与原脚本相同的环境变量接口

  **Must NOT do**:
  - 不使用第三方库 (只用 subprocess, os, shutil, pathlib 等标准库)
  - 不删除用户本地已存在的文件 (使用 shutil.copytree 的 dirs_exist_ok=True)
  - 不改变原有的步骤顺序和输出格式

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
    - Reason: Python 脚本,逻辑清晰,比 API 方案更简单
  - **Skills**: []
    - 无需特殊 skills,标准 Python 操作

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2
  - **Blocks**: 2, 3, 4
  - **Blocked By**: 0

  **References**:

  **Pattern References** (原脚本逻辑,需移植到 Python):
  - `pull.sh:39-48` - `fetch()` 函数: 下载单个文件 → 改用 shutil.copy2
  - `pull.sh:52-59` - `backup_and_install_file()`: 备份并安装文件
  - `pull.sh:61-71` - `rename_json_if_exists()`: 重命名 legacy .json
  - `pull.sh:74-78` - CONFIG_DIR 决定逻辑
  - `pull.sh:99-131` - 主流程 (4 个步骤)

  **Implementation Structure**:
  ```python
  #!/usr/bin/env python3
  """
  pull.py - Sync opencode configs from GitHub repo to user-level config.

  Env:
    REPO_OWNER=ControlNet
    REPO_NAME=omo-dotfile
    REPO_REV=master
    CONFIG_DIR=<optional override>
    NO_BACKUP=1 (optional)
  """
  import os
  import sys
  import shutil
  import subprocess
  from pathlib import Path
  from datetime import datetime
  from tempfile import TemporaryDirectory

  # Config
  REPO_OWNER = os.environ.get("REPO_OWNER", "ControlNet")
  REPO_NAME = os.environ.get("REPO_NAME", "omo-dotfile")
  REPO_REV = os.environ.get("REPO_REV", "master")
  CONFIG_DIR_ENV = os.environ.get("CONFIG_DIR", "")
  NO_BACKUP = os.environ.get("NO_BACKUP", "0") == "1"

  def timestamp() -> str:
      return datetime.now().strftime("%Y%m%d-%H%M%S")

  def get_config_dir() -> Path:
      """Determine user-level config directory."""
      if CONFIG_DIR_ENV:
          return Path(CONFIG_DIR_ENV)
      if sys.platform == "win32":
          return Path.home() / ".config" / "opencode"
      # Unix: use XDG_CONFIG_HOME or default
      xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
      if xdg_config:
          return Path(xdg_config) / "opencode"
      return Path.home() / ".config" / "opencode"

  def backup_and_install(src: Path, dst: Path, stamp: str) -> None:
      """Backup existing file if needed, then install new file."""
      dst.parent.mkdir(parents=True, exist_ok=True)
      if not NO_BACKUP and dst.exists():
          backup_path = dst.with_suffix(f"{dst.suffix}.bak-{stamp}")
          shutil.copy2(dst, backup_path)
      shutil.copy2(src, dst)

  def rename_json_if_exists(json_path: Path, stamp: str) -> None:
      """Rename .json to .json.bak if exists."""
      if json_path.exists():
          backup_path = json_path.with_suffix(f".json.bak-{stamp}")
          if backup_path.exists():
              backup_path = backup_path.with_suffix(f".bak-{stamp}-{os.getpid()}")
          json_path.rename(backup_path)

  def copy_directory(src_dir: Path, dst_dir: Path) -> None:
      """Copy directory contents, preserving existing local files."""
      if not src_dir.exists():
          print(f"Warning: Source directory not found: {src_dir}", file=sys.stderr)
          return
      # Python 3.8+: dirs_exist_ok=True merges into existing dir
      shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)

  def main():
      config_dir = get_config_dir()
      config_dir.mkdir(parents=True, exist_ok=True)
      stamp = timestamp()

      repo_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git"

      with TemporaryDirectory() as tmp_dir:
          tmp_path = Path(tmp_dir)
          repo_path = tmp_path / REPO_NAME

          # Step [1/4]: Clone repo (shallow)
          print(f"[1/4] Cloning repository (branch/tag: {REPO_REV})...")
          result = subprocess.run(
              ["git", "clone", "--depth", "1", "--branch", REPO_REV, repo_url, str(repo_path)],
              capture_output=True, text=True
          )
          if result.returncode != 0:
              print(f"Error: Failed to clone repository", file=sys.stderr)
              print(result.stderr, file=sys.stderr)
              sys.exit(1)

          # Step [2/4]: Copy config files
          print(f"[2/4] Installing config files to: {config_dir}")
          config_files = [
              ("opencode.jsonc", "opencode.jsonc"),
              ("oh-my-opencode.jsonc", "oh-my-opencode.jsonc"),
              ("_AGENTS.md", "AGENTS.md"),
          ]
          for src_name, dst_name in config_files:
              src = repo_path / src_name
              dst = config_dir / dst_name
              if src.exists():
                  print(f"      - {src_name}")
                  backup_and_install(src, dst, stamp)

          # Step [3/4]: Copy plugins and skills directories
          print("[3/4] Installing plugins and skills...")
          for dir_name in ["plugins", "skills"]:
              src_dir = repo_path / dir_name
              dst_dir = config_dir / dir_name
              if src_dir.exists():
                  print(f"      - {dir_name}/")
                  copy_directory(src_dir, dst_dir)

          # Step [4/4]: Rename legacy .json files
          print("[4/4] Renaming legacy .json (if exists) so only .jsonc remains active")
          rename_json_if_exists(config_dir / "opencode.json", stamp)
          rename_json_if_exists(config_dir / "oh-my-opencode.json", stamp)

      print("Done.")
      print(f"Timestamp: {stamp}")
      if not NO_BACKUP:
          print(f"Backups: *.bak-{stamp}")

  if __name__ == "__main__":
      main()
  ```

  **Acceptance Criteria**:

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: pull.py exists and has valid Python syntax
    Tool: Bash
    Preconditions: pull.py created
    Steps:
      1. python3 -m py_compile pull.py
    Expected Result: Exit code 0 (no syntax errors)
    Evidence: Exit code captured

  Scenario: pull.py uses git clone approach
    Tool: Bash
    Preconditions: pull.py exists
    Steps:
      1. grep -n "git.*clone" pull.py
    Expected Result: git clone command found
    Evidence: grep output captured

  Scenario: pull.py uses only standard library
    Tool: Bash
    Preconditions: pull.py exists
    Steps:
      1. grep -E "^import |^from " pull.py | grep -vE "os|sys|shutil|subprocess|pathlib|datetime|tempfile" || echo "OK: only stdlib"
    Expected Result: Output is "OK: only stdlib"
    Evidence: grep output captured

  Scenario: pull.py handles environment variables
    Tool: Bash
    Preconditions: pull.py exists
    Steps:
      1. grep "REPO_OWNER" pull.py
      2. grep "REPO_NAME" pull.py
      3. grep "REPO_REV" pull.py
      4. grep "CONFIG_DIR" pull.py
      5. grep "NO_BACKUP" pull.py
    Expected Result: All environment variables are referenced
    Evidence: grep outputs captured

  Scenario: pull.py is executable
    Tool: Bash
    Preconditions: pull.py exists
    Steps:
      1. head -1 pull.py | grep "#!/usr/bin/env python"
    Expected Result: Shebang line found
    Evidence: head output captured
  ```

  **Commit**: YES
  - Message: `feat(pull.py): unified Python installer with git clone approach`
  - Files: `pull.py`
  - Pre-commit: `python3 -m py_compile pull.py`

---

- [x] 2. Delete pull.sh and pull.ps1

  **What to do**:
  - 删除 `pull.sh`
  - 删除 `pull.ps1`
  - 这两个文件被 `pull.py` 完全替代

  **Must NOT do**:
  - 不要在 pull.py 未验证前删除

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单删除操作
  - **Skills**: [`git-master`]
    - `git-master`: Git rm 操作

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3
  - **Blocks**: 3, 4
  - **Blocked By**: 1

  **References**:
  - `pull.sh` - 待删除
  - `pull.ps1` - 待删除

  **Acceptance Criteria**:

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: pull.sh is deleted
    Tool: Bash
    Preconditions: Previous task completed
    Steps:
      1. test ! -f pull.sh && echo "deleted" || echo "exists"
    Expected Result: Output is "deleted"
    Evidence: test output captured

  Scenario: pull.ps1 is deleted
    Tool: Bash
    Preconditions: Previous task completed
    Steps:
      1. test ! -f pull.ps1 && echo "deleted" || echo "exists"
    Expected Result: Output is "deleted"
    Evidence: test output captured
  ```

  **Commit**: YES
  - Message: `chore: remove legacy pull.sh and pull.ps1 (replaced by pull.py)`
  - Files: `pull.sh`, `pull.ps1` (deleted)

---

- [x] 3. Update README.md with new installation commands

  **What to do**:
  - 更新 README.md 中的安装命令:
    - Linux/Mac: `curl -fsSL ... | python3`
    - Windows: `python (Invoke-WebRequest ...).Content`
  - 保持 README 的其他内容不变

  **Must NOT do**:
  - 不修改环境变量说明等其他部分

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单文档更新
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4
  - **Blocks**: 4
  - **Blocked By**: 2

  **References**:

  **Pattern References**:
  - `README.md:5-15` - 现有安装命令,需要替换

  **New Content**:
  ```markdown
  Linux/Mac:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/ControlNet/omo-dotfile/master/pull.py | python3
  ```

  Windows (PowerShell):
  ```powershell
  (Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ControlNet/omo-dotfile/master/pull.py' -UseBasicParsing).Content | python
  ```
  ```

  **Acceptance Criteria**:

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: README contains new Python installation command for Linux/Mac
    Tool: Bash
    Preconditions: README.md exists
    Steps:
      1. grep "curl.*pull.py.*python3" README.md
    Expected Result: Command found
    Evidence: grep output captured

  Scenario: README contains new Python installation command for Windows
    Tool: Bash
    Preconditions: README.md exists
    Steps:
      1. grep "Invoke-WebRequest.*pull.py" README.md
    Expected Result: Command found
    Evidence: grep output captured

  Scenario: Old bash/ps1 commands are removed
    Tool: Bash
    Preconditions: README.md exists
    Steps:
      1. grep "pull.sh" README.md || echo "not found"
      2. grep "pull.ps1" README.md || echo "not found"
    Expected Result: Both outputs are "not found"
    Evidence: grep outputs captured
  ```

  **Commit**: YES
  - Message: `docs: update installation commands to use pull.py`
  - Files: `README.md`

---

- [x] 4. End-to-end verification

  **What to do**:
  - 运行 pull.py 并验证:
    - plugins/ 所有文件下载成功
    - skills/ 所有文件和子目录下载成功
    - config 文件下载不受影响

  **Must NOT do**:
  - 不修改任何文件 (纯验证)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯执行验证,无代码修改
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 5 (final)
  - **Blocks**: None
  - **Blocked By**: 3

  **References**:
  - Task 1 实现的 pull.py

  **Acceptance Criteria**:

  **Agent-Executed QA Scenarios:**

  ```
  Scenario: Full pull.py execution succeeds
    Tool: Bash
    Preconditions: pull.py created, git installed, internet available
    Steps:
      1. export CONFIG_DIR="$(mktemp -d)/opencode-test"
      2. python3 pull.py
      3. ls -la "$CONFIG_DIR/plugins/"
      4. ls -la "$CONFIG_DIR/skills/"
      5. ls -la "$CONFIG_DIR/skills/github-cli/references/" 2>/dev/null || echo "subdir check"
      6. test -f "$CONFIG_DIR/opencode.jsonc" && echo "config OK"
      7. rm -rf "$CONFIG_DIR"
    Expected Result:
      - Exit code 0 for pull.py
      - plugins/gotify-notify.js exists
      - skills/ directory structure created
      - opencode.jsonc exists
    Evidence: All command outputs captured

  Scenario: Local-only files preserved
    Tool: Bash
    Preconditions: pull.py created
    Steps:
      1. export CONFIG_DIR="$(mktemp -d)/opencode-test"
      2. mkdir -p "$CONFIG_DIR/plugins"
      3. echo "local" > "$CONFIG_DIR/plugins/my-local-plugin.js"
      4. python3 pull.py
      5. cat "$CONFIG_DIR/plugins/my-local-plugin.js"
      6. rm -rf "$CONFIG_DIR"
    Expected Result: my-local-plugin.js still contains "local"
    Evidence: File content captured

  Scenario: Backup logic works
    Tool: Bash
    Preconditions: pull.py created
    Steps:
      1. export CONFIG_DIR="$(mktemp -d)/opencode-test"
      2. mkdir -p "$CONFIG_DIR"
      3. echo "old" > "$CONFIG_DIR/opencode.jsonc"
      4. python3 pull.py
      5. ls "$CONFIG_DIR"/*.bak-* 2>/dev/null | head -1 || echo "no backup"
      6. rm -rf "$CONFIG_DIR"
    Expected Result: Backup file created (*.bak-TIMESTAMP)
    Evidence: ls output captured

  Scenario: Different branch/tag works
    Tool: Bash
    Preconditions: pull.py created
    Steps:
      1. export CONFIG_DIR="$(mktemp -d)/opencode-test"
      2. export REPO_REV="master"
      3. python3 pull.py
      4. test -f "$CONFIG_DIR/opencode.jsonc" && echo "OK"
      5. rm -rf "$CONFIG_DIR"
    Expected Result: Successfully clones specified branch
    Evidence: Output captured
  ```

  **Commit**: NO (verification only)

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 0 | `feat: add skills directory for dynamic download` | skills/**/* | git ls-files skills/ |
| 1 | `feat(pull.py): unified Python installer with git clone approach` | pull.py | python3 -m py_compile pull.py |
| 2 | `chore: remove legacy pull.sh and pull.ps1 (replaced by pull.py)` | pull.sh, pull.ps1 | git status |
| 3 | `docs: update installation commands to use pull.py` | README.md | - |

---

## Success Criteria

### Verification Commands
```bash
# After all tasks complete:

# 1. Test pull.py in isolated environment
export CONFIG_DIR="$(mktemp -d)/test-opencode"
python3 pull.py
ls -laR "$CONFIG_DIR"
# Expected: plugins/, skills/ with all files and subdirs

# 2. Verify recursive download
test -f "$CONFIG_DIR/skills/github-cli/references/gh-readonly.md"
# Expected: file exists

# 3. Verify config files
test -f "$CONFIG_DIR/opencode.jsonc"
# Expected: file exists

# 4. Cleanup
rm -rf "$CONFIG_DIR"
```

### Final Checklist
- [x] pull.py created with git clone approach
- [x] pull.py uses only Python standard library
- [x] shutil.copytree() used for directory copying
- [x] Local-only files are preserved (dirs_exist_ok=True)
- [x] Backup logic preserved
- [x] pull.sh and pull.ps1 deleted
- [x] README.md updated with Python commands
- [x] Cross-platform paths work (pathlib)

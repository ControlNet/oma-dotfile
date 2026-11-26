"""Tests for the scripts of the remote-gpu-run, gpu-availability and detached-gpu-queue skills.

ssh, sacct, nvidia-smi, crontab and `ps -o user=` are test-only stand-ins on a temporary PATH:
ssh runs the "remote" command locally, the others print canned GPU, job and user data from
files the test writes. HOME is a temporary directory, so the recorder, its cron entry and every
log stay inside it. The scripts target Linux machines, so the tests run on Linux only.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from support import ROOT, TestCase

SKILLS = ROOT / "skills"
AVAILABILITY = SKILLS / "gpu-availability" / "scripts" / "gpu-availability.sh"
RECORDER = SKILLS / "gpu-availability" / "scripts" / "gpu-usage-log.sh"
WATCH_QUEUE = SKILLS / "detached-gpu-queue" / "scripts" / "watch_queue.sh"
QUEUE_TEMPLATE = SKILLS / "detached-gpu-queue" / "assets" / "queue_template.sh"
REMOTE_WATCH = SKILLS / "remote-gpu-run" / "scripts" / "remote-watch.sh"

STUBS = {
    # Drops ssh's options and the host, then runs the command (or stdin) with local bash.
    "ssh": r"""
while [ $# -gt 0 ]; do
  case $1 in -o|-p|-i|-l|-F|-O) shift 2 ;; -*) shift ;; *) break ;; esac
done
shift
if [ $# -eq 0 ]; then exec bash; fi
exec bash -c "$*"
""",
    # $FAKE/gpus: "index,uuid,name,util,mem,total" lines; $FAKE/apps: "uuid, pid" lines.
    "nvidia-smi": r"""
case "$*" in
  *query-compute-apps*) cat "$FAKE/apps" 2>/dev/null ;;
  *--query-gpu=*)
    q=${*#*--query-gpu=}; q=${q%% *}
    awk -F, -v q="$q" 'BEGIN { n = split(q, f, ",") }
      { m["index"] = $1; m["uuid"] = $2; m["name"] = $3; m["utilization.gpu"] = $4
        m["memory.used"] = $5; m["memory.total"] = $6; m["temperature.gpu"] = 30; s = ""
        for (i = 1; i <= n; i++) s = s (i > 1 ? ", " : "") m[f[i]]; print s }' "$FAKE/gpus" ;;
  -L) awk -F, '{ print "GPU " $1 ": " $3 " (UUID: " $2 ")" }' "$FAKE/gpus" ;;
  *) echo "stand-in nvidia-smi table" ;;
esac
""",
    # $FAKE/users: "pid user" lines; anything else goes to the real ps.
    "ps": r"""
if [ "$1 $2 $3" = "-o user= -p" ]; then
  awk -v p="$4" '$1 == p { print $2 }' "$FAKE/users"; exit
fi
exec /bin/ps "$@"
""",
    # The crontab lives in $FAKE/crontab; $FAKE/crontab-fails makes writing it fail.
    "crontab": r"""
case $1 in
  -l) cat "$FAKE/crontab" 2>/dev/null ;;
  -) [ -e "$FAKE/crontab-fails" ] && { echo "crontab: not allowed" >&2; exit 1; }
     cat > "$FAKE/crontab" ;;
esac
""",
    # $FAKE/sacct: "JobID|State|ExitCode|Elapsed|NodeList" lines, as `sacct -X -n -P` prints.
    "sacct": r"""cat "$FAKE/sacct" 2>/dev/null""",
    # free as a host with a Chinese locale prints it: no "Mem:" label.
    "free": r"""
echo "               总计        已用        空闲      共享    缓冲/缓存    可用"
echo "内存：          31          10           5           0          15          20"
""",
}


@unittest.skipUnless(sys.platform.startswith("linux"), "the scripts target Linux GPU machines")
class ScriptTest(TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.tmp / "home"
        self.fake = self.tmp / "fake"
        bin_dir = self.tmp / "bin"
        for path in (self.home, self.fake, bin_dir):
            path.mkdir()
        for name, body in STUBS.items():
            stub = bin_dir / name
            _ = stub.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
            stub.chmod(0o755)
        self.env = {**os.environ, "HOME": str(self.home), "FAKE": str(self.fake),
                    "PATH": f"{bin_dir}:{os.environ['PATH']}", "LC_ALL": "C"}

    def write(self, name: str, text: str) -> Path:
        path = self.fake / name
        _ = path.write_text(text, encoding="utf-8")
        return path

    def run_script(self, *args: str | Path, timeout: float = 60, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", *map(str, args)], capture_output=True, text=True,
                              timeout=timeout, env={**self.env, **env}, stdin=subprocess.DEVNULL)


class GpuAvailabilityTests(ScriptTest):
    def setUp(self) -> None:
        super().setUp()
        self.write("gpus", "0,GPU-a,NVIDIA L40S,0,0,46068\n1,GPU-b,NVIDIA L40S,0,0,46068\n")

    def history(self, rows: list[tuple[int, int, int, int, str]]) -> None:
        """Recorder rows: (seconds ago, gpu index, util %, memory MiB, users)."""
        data = self.home / ".cache" / "gpu-usage"
        data.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        lines = [f"{now - ago}\t{idx}\t{util}\t{mem}\t46068\t{users}\n" for ago, idx, util, mem, users in rows]
        _ = (data / "history.tsv").write_text("".join(lines), encoding="utf-8")

    def check(self, *args: str) -> str:
        result = self.run_script(AVAILABILITY, *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result.stdout

    def test_two_users_on_one_gpu_are_both_reported(self) -> None:
        self.write("apps", "GPU-a, 101\nGPU-a, 102\n")
        self.write("users", "101 alice\n102 bob\n")
        self.history([(ago, 0, 90, 30000, "alice,bob") for ago in range(60, 3600, 60)])
        out = self.check("gpu1")
        self.assertIn("(alice,bob)", out)
        self.assertIn("by alice,bob", out)

    def test_unsupported_values_count_as_zero(self) -> None:
        self.write("gpus", "0,GPU-a,NVIDIA A100,[N/A],[N/A],81920\n")
        self.assertIn("gpu 0", self.check("gpu1"))

    def test_recorder_that_stopped_before_the_window_is_reported_with_its_real_age(self) -> None:
        self.history([(8 * 3600 + ago, idx, 0, 0, "-") for ago in range(0, 1800, 60) for idx in (0, 1)])
        out = self.check("gpu1")
        self.assertIn("recorder stopped 8.0 h ago", out)
        self.assertIn("idle GPUs [none]", out)
        self.assertIn("free right now [1,0]", out)

    def test_stopped_recorder_lists_no_idle_gpus(self) -> None:
        self.history([(600 + ago, idx, 0, 0, "-") for ago in range(0, 6 * 3600, 60) for idx in (0, 1)])
        out = self.check("gpu1")
        self.assertIn("recorder stopped 10 min ago", out)
        self.assertIn("idle GPUs [none]", out)

    def test_busy_minute_without_a_process_names_no_user(self) -> None:
        self.history([(ago, 0, 50, 20000, "-") for ago in range(60, 3600, 60)])
        out = self.check("gpu1")
        self.assertIn("last 1 min ago;", out)
        self.assertNotIn("by -", out)

    def test_a_host_given_twice_is_checked_once(self) -> None:
        out = self.check("gpu1", "gpu1")
        self.assertEqual(out.count("gpu1 ("), 1)

    def test_fractional_hours_are_rejected(self) -> None:
        result = self.run_script(AVAILABILITY, "--hours", "0.5", "gpu1")
        self.assertEqual(result.returncode, 64)

    def test_failed_cron_install_is_reported_and_leaves_no_note(self) -> None:
        self.write("crontab-fails", "")
        self.assertIn("(installing the recorder failed)", self.check("gpu1"))
        self.assertFalse((self.home / "AGENTS.md").exists())

    def test_install_note_starts_on_its_own_line(self) -> None:
        _ = (self.home / "AGENTS.md").write_text("# Machine\n- no trailing newline", encoding="utf-8")
        self.assertEqual(self.run_script(RECORDER, "install").returncode, 0)
        lines = (self.home / "AGENTS.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[1], "- no trailing newline")
        self.assertTrue(lines[2].startswith("- A cron entry"))


class WatchQueueTests(ScriptTest):
    def setUp(self) -> None:
        super().setUp()
        self.write("gpus", "0,GPU-a,NVIDIA L40S,0,0,46068\n")
        self.run_root = self.tmp / "run"
        self.run_root.mkdir()
        self.log = self.run_root / "queue_t.log"
        self.queue = subprocess.Popen(["bash", "-c", 'exec -a "bash queue_t" sleep 300'])
        self.addCleanup(self.queue.kill)

    def watch(self, *paths: Path, **env: str) -> subprocess.Popen[str]:
        env = {"INTERVAL": "1", "FAIL_REGEX": "GAVE UP", "MIN_AVAIL_GB": "0", **env}
        proc = subprocess.Popen(["bash", str(WATCH_QUEUE), "^bash queue_t", str(self.run_root / "DONE"),
                                 *map(str, paths or (self.run_root,))],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env={**self.env, **env})
        self.addCleanup(proc.kill)
        time.sleep(2)
        return proc

    def test_old_failure_marker_does_not_fire_again_after_rearming(self) -> None:
        _ = self.log.write_text("task1 GAVE UP exit 1\n", encoding="utf-8")
        proc = self.watch()
        with self.log.open("a") as log:
            _ = log.write("task2 start\n")
        time.sleep(3)
        (self.run_root / "DONE").touch()
        self.assertEqual(proc.wait(timeout=30), 0, proc.stdout.read() if proc.stdout else "")

    def test_new_failure_marker_fires(self) -> None:
        _ = self.log.write_text("task1 start\n", encoding="utf-8")
        proc = self.watch()
        with self.log.open("a") as log:
            _ = log.write("task1 GAVE UP exit 1\n")
        self.assertEqual(proc.wait(timeout=30), 4)

    def test_watched_path_given_as_a_symlink_is_followed(self) -> None:
        target = self.tmp / "data"
        target.mkdir()
        link = self.tmp / "data-link"
        link.symlink_to(target)
        proc = self.watch(link, FAIL_GLOB="*.log")
        _ = (target / "task.log").write_text("GAVE UP\n", encoding="utf-8")
        self.assertEqual(proc.wait(timeout=30), 4)

    def test_low_memory_is_read_in_any_locale(self) -> None:
        proc = self.watch(MIN_AVAIL_GB="100000000")
        self.assertEqual(proc.wait(timeout=30), 5)


class QueueTemplateTests(ScriptTest):
    def run_task(self, command: str) -> subprocess.CompletedProcess[str]:
        script = f"source {QUEUE_TEMPLATE}; run_task t1 1 {command}"
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60,
                              env={**self.env, "RUN_ROOT": str(self.tmp)})

    def test_failed_task_prints_the_failure_marker_and_keeps_its_old_log(self) -> None:
        _ = self.run_task("bash -c 'echo first try; exit 3'")
        result = self.run_task("bash -c 'echo second try; exit 3'")
        self.assertIn("t1 GAVE UP exit 3", result.stdout)
        task_log = (self.tmp / "tasks" / "t1" / "task.log").read_text(encoding="utf-8")
        self.assertEqual(task_log, "first try\nsecond try\n")

    def test_finished_task_prints_no_failure_marker(self) -> None:
        result = self.run_task("true")
        self.assertIn("t1 exit 0", result.stdout)
        self.assertNotIn("GAVE UP", result.stdout)


class RemoteWatchTests(ScriptTest):
    def watch(self, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        return self.run_script(REMOTE_WATCH, "cluster", *args, "--interval", "1", timeout=timeout)

    def test_waits_for_every_job(self) -> None:
        self.write("sacct", "11|COMPLETED|0:0|00:01:00|node1\n12|RUNNING|0:0|00:01:00|node2\n")
        proc = subprocess.Popen(["bash", str(REMOTE_WATCH), "cluster", "--job", "11", "--job", "12",
                                 "--interval", "1"], stdout=subprocess.PIPE, text=True, env=self.env)
        self.addCleanup(proc.kill)
        time.sleep(3)
        self.assertIsNone(proc.poll())
        self.write("sacct", "11|COMPLETED|0:0|00:01:00|node1\n12|COMPLETED|0:0|00:02:00|node2\n")
        self.assertEqual(proc.wait(timeout=30), 0)
        out = proc.stdout.read() if proc.stdout else ""
        self.assertIn("11 COMPLETED", out)
        self.assertIn("12 COMPLETED", out)

    def test_a_failed_job_returns_at_once(self) -> None:
        self.write("sacct", "11|FAILED|3:0|00:00:40|node1\n12|RUNNING|0:0|00:01:00|node2\n"
                            "13|PENDING|0:0|00:00:00|None assigned\n")
        result = self.watch("--job", "11,12,13")
        self.assertEqual(result.returncode, 3)
        self.assertIn("11 FAILED", result.stdout)

    def test_job_array_waits_for_all_its_tasks(self) -> None:
        self.write("sacct", "20_0|COMPLETED|0:0|00:00:20|node1\n20_1|RUNNING|0:0|00:01:00|node1\n")
        with self.assertRaises(subprocess.TimeoutExpired):
            _ = self.watch("--job", "20", timeout=4)

    def test_stage_out_is_still_running(self) -> None:
        self.write("sacct", "11|STAGE_OUT|0:0|00:01:00|node1\n")
        with self.assertRaises(subprocess.TimeoutExpired):
            _ = self.watch("--job", "11", timeout=4)

    def test_until_running_reports_a_job_that_ended_before_it_ran(self) -> None:
        self.write("sacct", "11|CANCELLED|0:0|00:00:00|None assigned\n")
        result = self.watch("--job", "11", "--until-running")
        self.assertEqual(result.returncode, 3)

    def test_until_running_returns_once_running(self) -> None:
        self.write("sacct", "11|RUNNING|0:0|00:00:05|node7\n")
        result = self.watch("--job", "11", "--until-running")
        self.assertEqual(result.returncode, 0)
        self.assertIn("node7", result.stdout)

    def test_stall_counts_from_the_watcher_start(self) -> None:
        log = self.home / "out.log"
        _ = log.write_text("old progress\n", encoding="utf-8")
        old = time.time() - 7200
        os.utime(log, (old, old))
        self.write("sacct", "11|RUNNING|0:0|02:00:00|node1\n")
        with self.assertRaises(subprocess.TimeoutExpired):
            _ = self.watch("--job", "11", "--log", "~/out.log", "--stall-min", "1", timeout=4)


if __name__ == "__main__":
    _ = unittest.main()

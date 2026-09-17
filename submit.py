#!/usr/bin/env python3
"""submit — run a lab's checks (or test suite) and post the result to Canvas.

Usage: ./submit <student-id>
(submit is a thin bash shim that execs this file with python3.)
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

LAB_JSON = "lab.json"
DEFAULT_API_URL = "https://canvassubmissionserver-production.up.railway.app/submit"

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def ok(msg):
    print(f"  {GREEN}✓{NC} {msg}")


def bad(msg):
    print(f"  {RED}✕{NC} {msg}")


def info(msg):
    print(f"  {BLUE}→{NC} {msg}")


class Checker:
    """Runs a lab's checks (file/git/node based) and tallies points."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failed_descriptions = []

    def _record(self, passed, pass_desc, fail_desc=None):
        if passed:
            ok(pass_desc)
            self.passed += 1
        else:
            desc = fail_desc if fail_desc is not None else pass_desc
            bad(desc)
            self.failed += 1
            self.failed_descriptions.append(desc)

    def file_exists(self, desc, paths):
        self._record(all(os.path.exists(p) for p in paths), desc)

    def file_not_contains(self, desc, value, paths):
        def clean(path):
            if not os.path.isfile(path):
                return True
            with open(path, encoding="utf-8", errors="ignore") as f:
                return value not in f.read()

        ok_paths = all(clean(p) for p in paths)
        self._record(ok_paths, desc, f'{desc} — found placeholder: "{value}"')

    def git_commits(self, desc, minimum):
        count = int(run_git(["rev-list", "--count", "HEAD"]) or "0")
        self._record(
            count >= minimum,
            f"{desc} ({count} commits)",
            f"{desc} — only {count} commit(s), need at least {minimum}",
        )

    def node_test(self, desc, script):
        result = subprocess.run(
            ["node", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = result.stdout + result.stderr
        passed = result.returncode == 0
        self._record(passed, desc)
        if not passed:
            for line in output.splitlines():
                if "❌" in line or "Error" in line:
                    print(f"    {line}")


def run_git(args):
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except FileNotFoundError:
        return None


def run_checks(lab):
    """Runs lab.json's "checks" array. Returns (points_earned, points_possible)."""
    checker = Checker()
    for check in lab.get("checks", []):
        check_type = check.get("type")
        desc = check.get("description", check.get("id", "check"))

        if check_type == "file_exists":
            checker.file_exists(desc, check["paths"])
        elif check_type == "file_not_contains":
            checker.file_not_contains(desc, check["value"], check["paths"])
        elif check_type == "git_commits":
            checker.git_commits(desc, check["min"])
        elif check_type == "node_test":
            checker.node_test(desc, check["script"])
        else:
            info(f"Unknown check type: {check_type} — skipping")

    return checker.passed, checker.failed, checker.failed_descriptions


def run_test_command(command):
    """Runs lab.json's "test_command". Returns (points_earned, points_possible, failed_descriptions).

    The command must print a final line "SCORE: <points_earned>/<points_possible>"
    (e.g. a suite with 8 of 10 tests passing ends with "SCORE: 8/10").
    """
    result = subprocess.run(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = result.stdout
    print(output)

    matches = re.findall(r"SCORE:\s*([0-9.]+)/([0-9.]+)", output)
    if not matches:
        desc = 'test_command did not report a score (expected a final line like "SCORE: 8/10")'
        bad(desc)
        return 0, 1, [desc]

    earned, possible = (float(x) for x in matches[-1])
    desc = f"Test suite: {earned:g}/{possible:g}"
    if earned >= possible:
        ok(desc)
        return earned, possible, []
    bad(desc)
    return earned, possible, [desc]


def main():
    student_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("STUDENT_ID", "")

    print()
    print(f"{BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{NC}")
    print(f"{BLUE}  Coding School — Lab Submission{NC}")
    print(f"{BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{NC}")
    print()

    try:
        with open(LAB_JSON, encoding="utf-8") as f:
            lab = json.load(f)
    except FileNotFoundError:
        print(f"{RED}Error: lab.json not found. Are you in the right directory?{NC}")
        sys.exit(1)

    if not student_id:
        print(f"{YELLOW}Warning: STUDENT_ID not set.{NC}")
        print("  Run: ./submit <your-student-id>")
        print()

    print(f"Lab:    {lab['title']}")
    print(f"ID:     {lab['id']}")
    print()

    print("Running checks...")
    print()

    test_command = lab.get("test_command")
    if test_command:
        points_earned, points_possible, failed_descriptions = run_test_command(test_command)
        checks_passed = 1 if not failed_descriptions else 0
        checks_failed = 1 - checks_passed
    else:
        checks_passed, checks_failed, failed_descriptions = run_checks(lab)
        points_earned, points_possible = checks_passed, checks_passed + checks_failed

    print()
    print(f"{BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{NC}")

    if checks_failed == 0:
        result = "pass"
        print(f"{GREEN}All {checks_passed} checks passed.{NC}")
    else:
        result = "fail"
        print(f"{RED}{checks_failed} check(s) failed, {checks_passed} passed.{NC}")
        print()
        print("Fix before resubmitting:")
        for desc in failed_descriptions:
            bad(desc)

    print()
    info("Submitting to Canvas...")

    score = round(points_earned / points_possible * 100, 1) if points_possible else 0

    payload = {
        "lab_id": lab["id"],
        "student_id": student_id,
        "course_id": lab["canvas"]["course_id"],
        "assignment_id": lab["canvas"]["assignment_id"],
        "result": result,
        "score": score,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "failed_checks": failed_descriptions,
        "git_branch": run_git(["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown",
        "git_commit": run_git(["rev-parse", "--short", "HEAD"]) or "unknown",
    }

    api_url = os.environ.get("SUBMIT_API_URL", DEFAULT_API_URL)
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
    except urllib.error.HTTPError as e:
        status = e.code
    except urllib.error.URLError:
        status = None

    if status in (200, 201):
        ok("Submitted. Canvas gradebook updated.")
        print()
        if result == "pass":
            print(f"{GREEN}You're done. Mentor will review shortly.{NC}")
        else:
            print(f"{YELLOW}Submission recorded with failures. Fix the issues above and run submit again.{NC}")
    else:
        print(f"{YELLOW}Warning: Could not reach submission server (status: {status or '000'}).{NC}")
        print("  Your work is saved locally. Try again or let your mentor know.")

    print()


if __name__ == "__main__":
    main()

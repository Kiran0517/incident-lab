"""Change tools: what was deployed recently, and what exactly a commit changed."""
import re
import subprocess

import psycopg

from ..config import DB_DSN, REPO_PATH

SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def get_recent_deployments(minutes: int = 180) -> dict:
    """Lists deployments in the last N minutes, newest first."""
    with psycopg.connect(DB_DSN, connect_timeout=5) as conn:
        rows = conn.execute(
            "SELECT id, service, git_sha, message, deployed_at FROM deployments "
            "WHERE deployed_at > now() - %s * interval '1 minute' ORDER BY deployed_at DESC",
            (int(minutes),),
        ).fetchall()
    return {
        "window_minutes": minutes,
        "deployments": [
            {"id": r[0], "service": r[1], "git_sha": r[2], "message": r[3], "deployed_at": r[4].isoformat()}
            for r in rows
        ],
    }


def get_commit_diff(sha: str, max_lines: int = 200) -> dict:
    """Shows the files and code lines a git commit changed."""
    if not SHA_RE.match(sha):
        raise ValueError("sha must be 7-40 hex characters")
    result = subprocess.run(
        ["git", "-C", REPO_PATH, "show", "--stat", "--patch",
         "--format=commit %H%nAuthor: %an%nDate: %aI%n%n%s%n%n%b", sha],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300])
    lines = result.stdout.splitlines()
    return {
        "sha": sha,
        "total_lines": len(lines),
        "truncated": len(lines) > max_lines,
        "diff": "\n".join(lines[:max_lines]),
    }

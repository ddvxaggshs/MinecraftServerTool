"""Checked Git operations and atomic world/host-lock publication."""
from pathlib import Path, PurePosixPath
import uuid
from .processes import run
from .paths import LOCK_REF


class WorldGit:
    def __init__(self, directory, remote, branch):
        self.directory, self.remote, self.branch = directory, remote, branch
        self.main_ref = "refs/heads/" + branch

    def command(self, *args, input=None, timeout=120, raw=False):
        result = run(["git", *args], self.directory, timeout, input=input)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "Git command failed").strip())
        return result.stdout if raw else result.stdout.strip()

    @staticmethod
    def runtime_file(path):
        # These files carry no world progress. Never classify region/player files,
        # server settings, mods, or arbitrary JSON files as disposable runtime data.
        return path == "usercache.json" or ("/" in path and PurePosixPath(path).name == "session.lock")

    def changed_paths(self):
        status = self.command("status", "--porcelain=v1", "-z", "--no-renames",
                              "--untracked-files=all", raw=True)
        return [entry[3:] for entry in status.split("\0") if entry]

    def meaningful_changes(self):
        return [p for p in self.changed_paths() if not self.runtime_file(p)]

    def sync_checkout(self, remote):
        """Fast-forward an idle checkout; preserve real local changes for resolution."""
        dirty = self.meaningful_changes()
        if dirty:
            raise RuntimeError("Local progress/settings changed: " + ", ".join(dirty[:5]) +
                               ". Recover the previous session or use Resolve World.")
        local = self.command("rev-parse", "HEAD")
        if local == remote:
            return False
        ahead = int(self.command("rev-list", "--count", remote + ".." + local))
        if ahead:
            base = self.command("merge-base", local, remote)
            paths = self.command("diff", "--name-only", "-z", base, local, raw=True).split("\0")
            if any(p and not self.runtime_file(p) for p in paths):
                differences = self.command("diff", "--name-only", "-z", local, remote, raw=True).split("\0")
                if any(p and not self.runtime_file(p) for p in differences):
                    raise RuntimeError("Local world has unpublished/diverged progress. Use Resolve World to choose which version to keep.")
        runtime = self.changed_paths()
        if any(not self.runtime_file(p) for p in runtime):
            raise RuntimeError("Local files changed during synchronization. Retry after checking local progress.")
        if runtime:
            # Keep even irrelevant legacy caches recoverable, rather than deleting them.
            self.command("stash", "push", "--include-untracked", "-m",
                         "Relay runtime files before host handoff", "--", *runtime)
        if ahead:
            self.command("branch", "backup/relay-handoff-" + uuid.uuid4().hex, local)
            self.command("reset", "--hard", remote)
        else:
            self.command("merge", "--ff-only", remote)
        return True

    def stage_session(self):
        """Save progress but stop publishing machine-local cache/lock files."""
        excluded = Path(self.command("rev-parse", "--git-path", "info/exclude"))
        if not excluded.is_absolute():
            excluded = Path(self.directory) / excluded
        excluded.parent.mkdir(parents=True, exist_ok=True)
        text = excluded.read_text(encoding="utf-8") if excluded.exists() else ""
        for pattern in ("**/session.lock", "/usercache.json"):
            if pattern not in text.splitlines():
                text = text.rstrip() + "\n" + pattern + "\n"
        excluded.write_text(text, encoding="utf-8")
        tracked = self.command("ls-files", "-z", raw=True).split("\0")
        for path in tracked:
            if path and self.runtime_file(path):
                self.command("rm", "--cached", "--ignore-unmatch", "--", path)
        self.command("add", "-A")

    def remote_refs(self):
        text = self.command("ls-remote", self.remote, self.main_ref, LOCK_REF)
        refs = {line.split()[1]: line.split()[0] for line in text.splitlines()}
        if self.main_ref not in refs:
            raise RuntimeError("Remote world branch does not exist.")
        return refs[self.main_ref], refs.get(LOCK_REF)

    def fetch(self):
        self.command("fetch", self.remote, "--prune")
        return self.command("rev-parse", "refs/remotes/" + self.remote + "/" + self.branch)

    def check_branch(self):
        if self.command("branch", "--show-current") != self.branch:
            raise RuntimeError("Server directory is not on the configured world branch.")

    def relation(self):
        self.check_branch()
        remote = self.fetch()
        local = self.command("rev-parse", "HEAD")
        ahead, behind = map(int, self.command("rev-list", "--left-right", "--count", local + "..." + remote).split())
        return {"ahead": ahead, "behind": behind, "dirty": bool(self.meaningful_changes()), "remote": remote}

    def require_owner(self, owned):
        main, lock = self.remote_refs()
        if not owned or lock != owned:
            raise RuntimeError("This recovery no longer owns the host lock. Nothing was uploaded. Use Resolve World to choose a version after all hosts stop.")
        return main

    def publish_and_unlock(self, owned):
        # Both refs change in one remote transaction, guarded by exact expected SHAs.
        # A force-release/replacement during upload rejects the entire transaction.
        before = self.require_owner(owned)
        fetched = self.fetch()
        if fetched != before:
            raise RuntimeError("Remote world changed during synchronization; retry after checking versions.")
        self.command("merge-base", "--is-ancestor", before, "HEAD")
        self.command("push", "--atomic", "--force-with-lease=" + self.main_ref + ":" + before,
                     "--force-with-lease=" + LOCK_REF + ":" + owned,
                     self.remote, "HEAD:" + self.main_ref, ":" + LOCK_REF)

    def delete_owned_lock(self, owned):
        self.require_owner(owned)
        self.command("push", "--force-with-lease=" + LOCK_REF + ":" + owned,
                     self.remote, ":" + LOCK_REF)

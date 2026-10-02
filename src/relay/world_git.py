"""Checked Git operations and atomic world/host-lock publication."""
from .processes import run
from .paths import LOCK_REF


class WorldGit:
    def __init__(self, directory, remote, branch):
        self.directory, self.remote, self.branch = directory, remote, branch
        self.main_ref = "refs/heads/" + branch

    def command(self, *args, input=None, timeout=120):
        result = run(["git", *args], self.directory, timeout, input=input)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "Git command failed").strip())
        return result.stdout.strip()

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
        return {"ahead": ahead, "behind": behind, "dirty": bool(self.command("status", "--porcelain"))}

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

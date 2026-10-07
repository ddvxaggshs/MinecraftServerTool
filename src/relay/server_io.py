"""Serialized console writes and acknowledged commands, bound to one Java process."""
import re
import threading
import time


def server_message(line):
    match = re.match(r"^\[[^\]]+\] \[Server thread/INFO\]: (.*)$", line)
    return match.group(1) if match else None


class ConsoleSession:
    def __init__(self, proc):
        self.proc = proc
        self.write_lock = threading.Lock()
        self.condition = threading.Condition()
        self.pending = []
        self.closed = False

    def send(self, command):
        with self.write_lock:
            if self.closed or self.proc.poll() is not None:
                raise RuntimeError("Minecraft is no longer running")
            self.proc.stdin.write(command.rstrip("\n") + "\n")
            self.proc.stdin.flush()

    def request(self, command, predicate, timeout=10, quiet=False):
        entry = {"predicate": predicate, "result": None, "quiet": quiet}
        with self.condition:
            self.pending.append(entry)
        try:
            self.send(command)
            deadline = time.monotonic() + timeout
            with self.condition:
                while entry["result"] is None:
                    if self.closed or self.proc.poll() is not None:
                        raise RuntimeError("Minecraft exited while waiting for a command result")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Minecraft did not acknowledge: " + command.split()[0])
                    self.condition.wait(min(remaining, .25))
            return entry["result"]
        finally:
            with self.condition:
                self.pending.remove(entry)

    def feed(self, line):
        message = server_message(line)
        if message is None:
            return False
        quiet = False
        with self.condition:
            for entry in self.pending:
                if entry["result"] is None and entry["predicate"](message):
                    entry["result"] = message
                    quiet |= entry["quiet"]
            self.condition.notify_all()
        return quiet

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()

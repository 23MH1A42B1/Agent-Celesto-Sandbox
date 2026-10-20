import re
from typing import Tuple


class CommandBlockedError(Exception):
    """Raised when a command violates sandbox security policy and is intercepted by safety hooks."""
    pass


# Patterns representing destructive attacks, unauthorized exfiltration, and malicious payloads
BLOCK_PATTERNS = [
    (re.compile(r"rm\s+-rf\s+(/|/\*|~|\$HOME)", re.IGNORECASE), "Destructive file system deletion attempted"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE), "Fork bomb attack attempted"),
    (re.compile(r"dd\s+if=/dev/(zero|urandom)\s+of=/dev/[a-z]+", re.IGNORECASE), "Raw block device overwrite attempted"),
    (re.compile(r"mkfs(\.[a-z0-9]+)?\s+/dev/", re.IGNORECASE), "Filesystem format attack attempted"),
    (re.compile(r"curl.*(evil\.attacker\.com|exfil|webhook\.site).*(\$CANARY|\$API_KEY|\.env)", re.IGNORECASE), "Prompt injection credential exfiltration attempted"),
    (re.compile(r"wget.*(evil\.attacker\.com|exfil).*(\$CANARY|\$API_KEY|\.env)", re.IGNORECASE), "Prompt injection credential exfiltration attempted"),
    (re.compile(r"nc\s+.*-e\s+/bin/(ba)?sh", re.IGNORECASE), "Reverse shell creation attempted"),
]


class SafetyHook:
    """Pre-execution safety callback running in the Celesto control channel."""

    def __init__(self, audit_callback=None):
        self.audit_callback = audit_callback

    def inspect_command(self, sandbox_name: str, command: str) -> Tuple[str, str]:
        """
        Inspects command before dispatching to the guest microVM.
        Returns (decision, reason) where decision is 'allow' or 'block'.
        """
        for pattern, reason in BLOCK_PATTERNS:
            if pattern.search(command):
                if self.audit_callback:
                    self.audit_callback(sandbox_name=sandbox_name, command=command, decision="block")
                return "block", reason

        if self.audit_callback:
            self.audit_callback(sandbox_name=sandbox_name, command=command, decision="allow")
        return "allow", "Command passed safety inspection"

    def before_command(self, sandbox_name: str, command: str) -> None:
        """Called immediately before guest execution. Raises CommandBlockedError if blocked."""
        decision, reason = self.inspect_command(sandbox_name, command)
        if decision == "block":
            raise CommandBlockedError(f"Safety hook blocked command on {sandbox_name}: {reason} ('{command}')")

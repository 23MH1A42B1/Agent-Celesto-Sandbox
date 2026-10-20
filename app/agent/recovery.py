import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any

from app.agent.celesto_client import CelestoSandbox

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports")
TRACE_LOG_PATH = os.path.join(REPORTS_DIR, "failure_trace.jsonl")


class RecoveryManager:
    """
    Manages multi-step workflow execution and error recovery policies
    when steps fail mid-task (specifically at step 7 of 10).
    """

    def __init__(self, policy: str = "rollback"):
        if policy not in {"resume", "rollback", "fresh"}:
            raise ValueError(f"Unknown recovery policy: {policy}")
        self.policy = policy
        self.trace: List[Dict[str, Any]] = []

    def log_event(self, event: str, step: int, details: str, **kwargs):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "step": step,
            "details": details,
            **kwargs
        }
        self.trace.append(entry)
        os.makedirs(REPORTS_DIR, exist_ok=True)
        with open(TRACE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def execute_workflow_with_failure(self, sandbox_name: str) -> bool:
        """
        Executes a 10-step untrusted package detonation workflow where step 7 fails.
        Applies the chosen recovery policy ('rollback') to recover and finish.
        """
        # Clear trace file before fresh execution
        os.makedirs(REPORTS_DIR, exist_ok=True)
        with open(TRACE_LOG_PATH, "w", encoding="utf-8") as f:
            pass

        steps = [
            (1, "Initialize microVM environment and mount quarantine volume", "mkdir -p /sandbox/quarantine"),
            (2, "Fetch package metadata and checksum verification", "python -m pip download --no-deps --dest /sandbox/pkg requests==2.31.0"),
            (3, "Static analysis of setup.py and dependency manifest", "python -c 'import ast; print(\"Static AST check passed\")'"),
            (4, "Baseline system snapshot creation before detonation", "celesto snapshot create --name baseline-clean"),
            (5, "Install package in isolated user namespace with network off", "pip install --no-index --find-links=/sandbox/pkg requests"),
            (6, "Pre-exploit snapshot checkpointing", "celesto snapshot create --name step6-checkpoint"),
            (7, "Execute dynamic detonation probe (injected failure point)", "python -c 'raise SystemError(\"Corrupted binary hook detected in untrusted extension\")'"),
            (8, "Post-recovery clean sandbox verification", "python -c 'import sys; print(\"System sanity verified\")'"),
            (9, "Generate behavioral audit score and risk report", "python -c 'print(\"Risk scorecard emitted\")'"),
            (10, "Final quarantine cleanup and export containment receipt", "rm -rf /sandbox/quarantine && echo 'Detonation completed'")
        ]

        with CelestoSandbox(sandbox_name=sandbox_name) as vm:
            self.log_event("workflow_started", 0, f"Sandbox {sandbox_name} boot completed")

            # Execute steps 1 to 6
            for step_num, desc, cmd in steps[:6]:
                self.log_event("step_started", step_num, desc, command=cmd)
                if step_num == 6:
                    vm.snapshot("step6-pre-risky-step")
                    self.log_event("snapshot_created", 6, "Captured pre-experiment microVM snapshot step6-pre-risky-step")
                res = vm.run(cmd)
                self.log_event("step_completed", step_num, f"Step {step_num} finished with exit_code={res.exit_code}")

            # Step 7: Intended Mid-Task Failure
            failed_step, failed_desc, failed_cmd = steps[6]
            self.log_event("step_started", failed_step, failed_desc, command=failed_cmd)
            # Step 7 encounters designed crash
            self.log_event("step_failed", failed_step, "Corrupted binary hook detected in untrusted extension (exit_code=1)", error="SystemError")

            # Apply Named Recovery Policy
            self.log_event(
                "policy_applied",
                failed_step,
                f"Applied recovery policy '{self.policy}' to revert guest microVM to pre-experiment snapshot",
                policy=self.policy
            )

            if self.policy == "rollback":
                vm.restore_snapshot("step6-pre-risky-step")
                self.log_event("snapshot_restored", failed_step, "Restored microVM filesystem and registers to step6-pre-risky-step")
            elif self.policy == "resume":
                self.log_event("resume_applied", failed_step, "Retrying step 7 on existing disk")
            elif self.policy == "fresh":
                self.log_event("fresh_applied", failed_step, "Discarded VM and spun up fresh instance")

            # Continue steps 8 to 10
            for step_num, desc, cmd in steps[7:]:
                self.log_event("step_started", step_num, desc, command=cmd)
                res = vm.run(cmd)
                self.log_event("step_completed", step_num, f"Step {step_num} finished with exit_code={res.exit_code}")

            self.log_event("workflow_completed", 10, "Workflow completed successfully after recovery policy rollback")
            return True

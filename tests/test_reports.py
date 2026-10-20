import json
import math
import os
import re
import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SBX_REGEX = re.compile(r"^sbx-[a-z0-9]{8,}$")


def test_no_live_env_file():
    """Requirement 2: Ensure live .env is not committed."""
    env_path = os.path.join(BASE_DIR, ".env")
    assert not os.path.exists(env_path), "Live .env file must NOT exist in the repository root"


def test_env_example():
    """Requirement 2: .env.example exists and contains required keys with placeholders."""
    env_example_path = os.path.join(BASE_DIR, ".env.example")
    assert os.path.exists(env_example_path), ".env.example must exist"
    
    with open(env_example_path, "r", encoding="utf-8") as f:
        content = f.read()

    required_keys = [
        "CELESTO_PROVIDER",
        "CELESTO_API_KEY",
        "LLM_API_KEY",
        "LLM_MODEL",
        "DATABASE_URL",
        "API_PORT"
    ]
    for key in required_keys:
        assert re.search(rf"^{key}=", content, re.MULTILINE), f"Missing key {key} in .env.example"
        # Verify placeholders, no real secrets
        match = re.search(rf"^{key}=(.*)$", content, re.MULTILINE)
        if match:
            val = match.group(1).strip()
            assert "sk-" not in val and "secret" not in val.lower() or "replace" in val.lower()


def test_docker_compose_and_dockerfile():
    """Requirement 1: docker-compose.yml and Dockerfile verification."""
    compose_path = os.path.join(BASE_DIR, "docker-compose.yml")
    dockerfile_path = os.path.join(BASE_DIR, "Dockerfile")

    assert os.path.exists(compose_path), "docker-compose.yml must exist"
    assert os.path.exists(dockerfile_path), "Dockerfile must exist"

    with open(compose_path, "r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)

    services = compose.get("services", {})
    assert "api" in services, "api service must be defined in docker-compose.yml"
    assert "ledger" in services, "ledger service must be defined in docker-compose.yml"

    # Ledger healthcheck
    ledger = services["ledger"]
    assert "healthcheck" in ledger, "ledger service must have a healthcheck"
    hc_ledger = ledger["healthcheck"]
    assert any("pg_isready" in str(cmd) for cmd in hc_ledger.get("test", [])), "ledger healthcheck must use pg_isready"
    for prop in ["interval", "timeout", "retries", "start_period"]:
        assert prop in hc_ledger, f"ledger healthcheck missing {prop}"

    # Ledger mount
    volumes = ledger.get("volumes", [])
    assert any("./seeds" in str(v) for v in volumes), "ledger must mount ./seeds init volume"

    # API healthcheck
    api = services["api"]
    assert "healthcheck" in api, "api service must have a healthcheck"
    hc_api = api["healthcheck"]
    assert any("http://localhost:8080/health" in str(cmd) for cmd in hc_api.get("test", [])), "api healthcheck must curl /health"
    for prop in ["interval", "timeout", "retries", "start_period"]:
        assert prop in hc_api, f"api healthcheck missing {prop}"

    # API depends on ledger healthy
    depends_on = api.get("depends_on", {})
    assert "ledger" in depends_on, "api must depend on ledger"
    assert depends_on["ledger"].get("condition") == "service_healthy", "api must wait for ledger to be service_healthy"


def test_problem_json():
    """Requirement 3: reports/problem.json schema and length constraints."""
    problem_path = os.path.join(BASE_DIR, "reports", "problem.json")
    assert os.path.exists(problem_path), "reports/problem.json must exist"

    with open(problem_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "who" in data and len(data["who"]) >= 40, "who must be at least 40 chars"
    assert "agent_work" in data and len(data["agent_work"]) >= 40, "agent_work must be at least 40 chars"
    assert "proof_output" in data and len(data["proof_output"]) >= 20, "proof_output must be at least 20 chars"
    assert data.get("idea_source") in ["idea_bank", "original"], "idea_source must be 'idea_bank' or 'original'"


def test_commands_jsonl():
    """Requirement 4: logs/commands.jsonl format and fields."""
    cmd_log_path = os.path.join(BASE_DIR, "logs", "commands.jsonl")
    assert os.path.exists(cmd_log_path), "logs/commands.jsonl must exist"

    lines_count = 0
    with open(cmd_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            lines_count += 1
            entry = json.loads(line)
            assert "ts" in entry and entry["ts"], "Missing ts"
            assert "sandbox_name" in entry and SBX_REGEX.match(entry["sandbox_name"]), f"Invalid sandbox_name {entry.get('sandbox_name')}"
            assert "command" in entry and entry["command"].strip(), "Empty command"
            assert entry.get("decision") in ["allow", "block"], f"Invalid decision {entry.get('decision')}"
            assert entry.get("execution_target") == "celesto_sandbox", f"execution_target must be exactly celesto_sandbox, got {entry.get('execution_target')}"

    assert lines_count >= 1, "logs/commands.jsonl must have at least one line"


def test_capabilities_json():
    """Requirement 5: reports/capabilities.json requirements."""
    cap_path = os.path.join(BASE_DIR, "reports", "capabilities.json")
    assert os.path.exists(cap_path), "reports/capabilities.json must exist"

    with open(cap_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    capabilities = data.get("capabilities", [])
    assert len(capabilities) >= 2, "Must have at least two capabilities"

    allowed_ids = {
        "persistence", "snapshots", "celestofs", "browser",
        "published_ports", "network_policy", "safety_hooks",
        "host_mounts", "coding_agent_preset", "agentor_durable"
    }
    seen_ids = set()
    for cap in capabilities:
        cap_id = cap.get("id")
        assert cap_id in allowed_ids, f"Disallowed capability id: {cap_id}"
        assert cap_id not in seen_ids, f"Duplicate capability id: {cap_id}"
        seen_ids.add(cap_id)

        why = cap.get("why", "")
        assert len(why) >= 80, f"Capability why must be at least 80 chars, got {len(why)}"

        evidence_path = cap.get("evidence_path", "")
        full_evidence_path = os.path.join(BASE_DIR, evidence_path)
        assert os.path.exists(full_evidence_path), f"evidence_path does not exist: {evidence_path}"


def test_lifecycle_json():
    """Requirement 6: reports/lifecycle.json requirements."""
    life_path = os.path.join(BASE_DIR, "reports", "lifecycle.json")
    assert os.path.exists(life_path), "reports/lifecycle.json must exist"

    with open(life_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("cleanup_on_success") is True, "cleanup_on_success must be true"
    assert data.get("cleanup_on_failure") is True, "cleanup_on_failure must be true"
    assert data.get("cleanup_on_interrupt") is True, "cleanup_on_interrupt must be true"

    names = data.get("sandbox_names", [])
    assert len(names) > 0, "sandbox_names must not be empty"
    assert len(names) == len(set(names)), "sandbox_names must be unique"

    # Check each name appears in commands.jsonl or reliability.json
    commands_log_path = os.path.join(BASE_DIR, "logs", "commands.jsonl")
    with open(commands_log_path, "r", encoding="utf-8") as f:
        commands_content = f.read()

    rel_path = os.path.join(BASE_DIR, "reports", "reliability.json")
    with open(rel_path, "r", encoding="utf-8") as f:
        rel_content = f.read()

    for name in names:
        assert SBX_REGEX.match(name), f"Sandbox name {name} does not match required format"
        assert (name in commands_content) or (name in rel_content), f"{name} not in commands.jsonl or reliability.json"


def test_reliability_json_and_postmortem():
    """Requirement 7: reports/reliability.json and postmortem.md calculation accuracy."""
    rel_path = os.path.join(BASE_DIR, "reports", "reliability.json")
    assert os.path.exists(rel_path), "reports/reliability.json must exist"

    with open(rel_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    runs = data.get("runs", [])
    run_count = data.get("run_count")
    assert run_count >= 20, f"run_count must be >= 20, got {run_count}"
    assert run_count == len(runs), "run_count must match length of runs"

    names = set()
    for r in runs:
        assert r.get("fresh") is True, "fresh must be true for all runs"
        name = r.get("sandbox_name", "")
        assert SBX_REGEX.match(name), f"Invalid sandbox_name {name}"
        assert name not in names, f"Duplicate sandbox_name {name}"
        names.add(name)
        assert r.get("wall_clock_s", -1) >= 0, "wall_clock_s must be >= 0"
        assert r.get("boot_to_ready_s", -1) >= 0, "boot_to_ready_s must be >= 0"
        assert r.get("cost_usd", -1) >= 0, "cost_usd must be >= 0"

    # Verify math
    successes = sum(1 for r in runs if r["success"] is True)
    expected_success_rate = successes / run_count
    assert abs(data.get("success_rate", 0) - expected_success_rate) <= 0.001

    # Sorted wall_clock
    sorted_wc = sorted(r["wall_clock_s"] for r in runs)
    n = len(sorted_wc)
    if n % 2 == 0:
        expected_median_wc = (sorted_wc[n // 2 - 1] + sorted_wc[n // 2]) / 2.0
    else:
        expected_median_wc = sorted_wc[n // 2]
    assert abs(data.get("median_wall_clock_s", 0) - expected_median_wc) <= 0.001

    p90_idx = math.ceil(0.90 * n) - 1
    expected_p90 = sorted_wc[p90_idx]
    assert abs(data.get("p90_wall_clock_s", 0) - expected_p90) <= 0.001

    # Sorted boot_to_ready
    sorted_b = sorted(r["boot_to_ready_s"] for r in runs)
    if n % 2 == 0:
        expected_median_b = (sorted_b[n // 2 - 1] + sorted_b[n // 2]) / 2.0
    else:
        expected_median_b = sorted_b[n // 2]
    assert abs(data.get("median_boot_to_ready_s", 0) - expected_median_b) <= 0.001

    # Total cost
    expected_cost = sum(r["cost_usd"] for r in runs)
    assert abs(data.get("total_cost_usd", 0) - expected_cost) <= 0.01

    # Postmortem
    postmortem_rel = data.get("postmortem_path")
    assert postmortem_rel == "reports/postmortem.md", "postmortem_path must be reports/postmortem.md"
    postmortem_full = os.path.join(BASE_DIR, postmortem_rel)
    assert os.path.exists(postmortem_full), "reports/postmortem.md must exist"
    with open(postmortem_full, "r", encoding="utf-8") as f:
        pm_content = f.read()
    assert len(pm_content) >= 200, f"postmortem.md must be at least 200 chars, got {len(pm_content)}"


def test_containment_json():
    """Requirement 8: reports/containment.json verification."""
    cont_path = os.path.join(BASE_DIR, "reports", "containment.json")
    assert os.path.exists(cont_path), "reports/containment.json must exist"

    with open(cont_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("attack") in ["prompt_injection_exfil", "destructive_command", "suspicious_package"]
    assert data.get("blocked") is True, "blocked must be true"
    assert data.get("host_untouched") is True, "host_untouched must be true"
    paths = data.get("evidence_paths", [])
    assert len(paths) >= 1, "evidence_paths must have at least one entry"
    for p in paths:
        full_p = os.path.join(BASE_DIR, p)
        assert os.path.exists(full_p), f"evidence file {p} does not exist"


def test_failure_policy_and_trace():
    """Requirement 9: reports/failure_policy.json and failure_trace.jsonl."""
    fail_path = os.path.join(BASE_DIR, "reports", "failure_policy.json")
    assert os.path.exists(fail_path), "reports/failure_policy.json must exist"

    with open(fail_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("failed_step") == 7, "failed_step must be 7"
    assert data.get("total_steps") == 10, "total_steps must be 10"
    policy = data.get("policy")
    assert policy in ["resume", "rollback", "fresh"], f"Invalid policy: {policy}"
    rationale = data.get("rationale", "")
    assert len(rationale) >= 200, f"rationale must be at least 200 chars, got {len(rationale)}"

    trace_path = os.path.join(BASE_DIR, data.get("trace_path", ""))
    assert os.path.exists(trace_path), "trace_path must exist"

    policy_applied_found = False
    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("event") == "policy_applied" and entry.get("policy") == policy:
                policy_applied_found = True
                break

    assert policy_applied_found, f"Did not find event=policy_applied with policy={policy} in trace"


def test_concurrency_json():
    """Requirement 10: reports/concurrency.json verification."""
    conc_path = os.path.join(BASE_DIR, "reports", "concurrency.json")
    assert os.path.exists(conc_path), "reports/concurrency.json must exist"

    with open(conc_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("jobs", [])
    assert len(jobs) >= 5, f"jobs must have at least 5 entries, got {len(jobs)}"

    names = set()
    for job in jobs:
        name = job.get("sandbox_name", "")
        assert SBX_REGEX.match(name), f"Invalid sandbox_name {name}"
        assert name not in names, f"Duplicate job sandbox_name {name}"
        names.add(name)
        assert job.get("started_at"), "started_at must be non-empty"

    notes = data.get("breakage_notes", "")
    assert len(notes) >= 40, f"breakage_notes must be at least 40 chars, got {len(notes)}"


def test_readme_phrases():
    """Requirement 12: README.md contains required phrases and diagram."""
    readme_path = os.path.join(BASE_DIR, "README.md")
    assert os.path.exists(readme_path), "README.md must exist"

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    required_phrases = [
        "Problem statement",
        "How I used Celesto",
        "Eval report",
        "Containment test",
        "State and failure design",
        "Setup"
    ]
    for phrase in required_phrases:
        assert phrase in content, f"Missing required phrase in README: '{phrase}'"


def test_api_endpoints():
    """Requirement 11: Ledger API health, get runs, post runs, and error handling."""
    with TestClient(app) as client:
        # GET /health
        r_health = client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json() == {"status": "ok"}

        # GET /api/runs
        r_runs = client.get("/api/runs")
        assert r_runs.status_code == 200
        runs = r_runs.json()
        assert isinstance(runs, list)
        assert any(run.get("sandbox_name") == "sbx-seeddemo1" for run in runs), "Seeded run sbx-seeddemo1 must be present"

        # POST /api/runs valid
        payload_valid = {
            "run_id": "run-test-unit-001",
            "sandbox_name": "sbx-unitrun01",
            "problem_id": "problem-detonator",
            "state": "running",
            "execution_target": "celesto_sandbox"
        }
        r_post_valid = client.post("/api/runs", json=payload_valid)
        assert r_post_valid.status_code == 201
        res_data = r_post_valid.json()
        assert res_data["run_id"] == "run-test-unit-001"
        assert res_data["sandbox_name"] == "sbx-unitrun01"

        # POST /api/runs invalid execution_target (MUST return 400)
        payload_bad_target = {
            "run_id": "run-test-unit-002",
            "sandbox_name": "sbx-unitrun02",
            "problem_id": "problem-detonator",
            "state": "running",
            "execution_target": "host"
        }
        r_post_bad_target = client.post("/api/runs", json=payload_bad_target)
        assert r_post_bad_target.status_code == 400, f"Expected 400 for target 'host', got {r_post_bad_target.status_code}"

        # POST /api/runs invalid state (MUST return 400)
        payload_bad_state = {
            "run_id": "run-test-unit-003",
            "sandbox_name": "sbx-unitrun03",
            "problem_id": "problem-detonator",
            "state": "unknown_state",
            "execution_target": "celesto_sandbox"
        }
        r_post_bad_state = client.post("/api/runs", json=payload_bad_state)
        assert r_post_bad_state.status_code == 400, f"Expected 400 for bad state, got {r_post_bad_state.status_code}"

        # POST /api/runs invalid sandbox_name (MUST return 400)
        payload_bad_name = {
            "run_id": "run-test-unit-004",
            "sandbox_name": "short",
            "problem_id": "problem-detonator",
            "state": "running",
            "execution_target": "celesto_sandbox"
        }
        r_post_bad_name = client.post("/api/runs", json=payload_bad_name)
        assert r_post_bad_name.status_code == 400, f"Expected 400 for bad sandbox_name, got {r_post_bad_name.status_code}"


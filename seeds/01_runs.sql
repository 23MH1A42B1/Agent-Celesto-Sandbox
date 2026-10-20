CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR(64) PRIMARY KEY,
    sandbox_name VARCHAR(64) NOT NULL,
    problem_id VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL,
    execution_target VARCHAR(32) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_runs_sandbox_name ON runs(sandbox_name);

INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target, created_at, updated_at)
VALUES (
    'run-seed00000001',
    'sbx-seeddemo1',
    'problem-detonation-vetting',
    'deleted',
    'celesto_sandbox',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
)
ON CONFLICT (run_id) DO UPDATE SET
    sandbox_name = EXCLUDED.sandbox_name,
    problem_id = EXCLUDED.problem_id,
    state = EXCLUDED.state,
    execution_target = EXCLUDED.execution_target,
    updated_at = CURRENT_TIMESTAMP;

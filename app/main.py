import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Depends, status, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import engine, Base, get_db
from app.models import Run
from app.schemas import RunCreate, RunResponse


def init_db():
    """Initializes tables and ensures seed row exists."""
    Base.metadata.create_all(bind=engine)
    with Session(bind=engine) as db:
        seed_exists = db.query(Run).filter(Run.sandbox_name == "sbx-seeddemo1").first()
        if not seed_exists:
            seed_run = Run(
                run_id="run-seed00000001",
                sandbox_name="sbx-seeddemo1",
                problem_id="problem-detonation-vetting",
                state="deleted",
                execution_target="celesto_sandbox"
            )
            db.add(seed_run)
            db.commit()


# Initialize immediately
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Celesto Run Ledger Control Plane API",
    version="1.0.0",
    lifespan=lifespan
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    formatted_errors = []
    for err in exc.errors():
        err_dict = {
            "type": err.get("type"),
            "loc": [str(x) for x in err.get("loc", [])],
            "msg": str(err.get("msg")),
        }
        if "ctx" in err and "error" in err["ctx"]:
            err_dict["error"] = str(err["ctx"]["error"])
        formatted_errors.append(err_dict)

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": formatted_errors}
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)}
    )


@app.get("/health", status_code=status.HTTP_200_OK)
def health():
    return {"status": "ok"}


@app.get("/api/runs", response_model=List[RunResponse], status_code=status.HTTP_200_OK)
def get_runs(db: Session = Depends(get_db)):
    runs = db.query(Run).order_by(Run.created_at.desc()).all()
    return [RunResponse(**run.to_dict()) for run in runs]


@app.post("/api/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def create_run(run_in: RunCreate, db: Session = Depends(get_db)):
    # Check if run_id already exists
    existing = db.query(Run).filter(Run.run_id == run_in.run_id).first()
    if existing:
        existing.sandbox_name = run_in.sandbox_name
        existing.problem_id = run_in.problem_id
        existing.state = run_in.state
        existing.execution_target = run_in.execution_target
        db.commit()
        db.refresh(existing)
        return RunResponse(**existing.to_dict())

    new_run = Run(
        run_id=run_in.run_id,
        sandbox_name=run_in.sandbox_name,
        problem_id=run_in.problem_id,
        state=run_in.state,
        execution_target=run_in.execution_target
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)
    return RunResponse(**new_run.to_dict())

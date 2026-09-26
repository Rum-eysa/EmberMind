"""Synthetic scenario generator endpoints (EM-104).

Deterministic, explicitly-labelled demo data: fire location, wind history,
communication outage zones and resource distribution from a seed + config.
"""
import json
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.database import Database
from src.services.synthetic import (
    PRESETS,
    SYNTHETIC_LABEL,
    SyntheticError,
    build_dataset,
    cleanup_scenario,
    get_run,
    list_runs,
    persist_dataset,
    record_run,
)

# The generator is internal (no external data source), so it carries a fixed
# attribution like the EM-103 inventory.
SYNTHETIC_ATTRIBUTION = (
    "Sentetik senaryo verisi: EmberMind demo üreteci (EM-104) — gerçek gözlem değil"
)


class ScenarioGenerateRequest(BaseModel):
    """Payload for one deterministic generation run."""

    seed: int
    preset: str | None = None
    config: dict[str, Any] | None = None
    persist: bool = False
    include_dataset: bool = True


def _bad_request(exc: SyntheticError) -> HTTPException:
    return HTTPException(status_code=400, detail={"status": "error", "error": str(exc)})


def register_synthetic_routes(api: FastAPI, database: Database, _settings: Any) -> None:
    """Attach the demo synthetic-scenario endpoints (seeded, labelled)."""

    @api.get("/api/v1/scenarios/presets", tags=["synthetic"])
    def presets() -> dict[str, Any]:
        """List the ready-made scenario presets."""
        return {
            "presets": sorted(PRESETS),
            "attribution": SYNTHETIC_ATTRIBUTION,
        }

    @api.get("/api/v1/scenarios/synthetic/runs", tags=["synthetic"])
    def runs(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
        """Recent generation runs (audit trail with hashes)."""
        with database.session() as session:
            items = [run.as_dict for run in list_runs(session, limit)]
        return {"count": len(items), "runs": items}

    @api.get("/api/v1/scenarios/synthetic/runs/{run_key}", tags=["synthetic"])
    def run_detail(run_key: str) -> dict[str, Any]:
        """One generation run with its synthetic-record sample."""
        with database.session() as session:
            run = get_run(session, run_key)
            if run is None:
                raise HTTPException(
                    status_code=404,
                    detail={"status": "not_found", "error": f"no run {run_key}"},
                )
            dataset = str(run.dataset_json)
        payload = json.loads(dataset)
        sample = (
            [payload["fire"]]
            + payload["wind_history"][:1]
            + payload["outage_zones"][:1]
        )
        return {
            "run": run.as_dict,
            "record_sample": sample,
            "synthetic_label": SYNTHETIC_LABEL,
        }

    @api.post("/api/v1/scenarios/synthetic/generate", tags=["synthetic"])
    def generate(req: ScenarioGenerateRequest) -> dict[str, Any]:
        """Generate a deterministic labelled dataset; optionally persist it."""
        try:
            dataset = build_dataset(req.seed, req.config, req.preset)
            with database.session() as session:
                counts = persist_dataset(session, dataset) if req.persist else None
                run = record_run(session, dataset, req.persist, req.preset)
                session.commit()
        except SyntheticError as exc:
            raise _bad_request(exc) from exc
        response: dict[str, Any] = {
            "status": "ok",
            "run": run.as_dict,
            "persisted_counts": counts,
            "attribution": SYNTHETIC_ATTRIBUTION,
        }
        if req.include_dataset:
            response["dataset"] = dataset
        return response

    @api.delete("/api/v1/scenarios/synthetic/{scenario_tag}", tags=["synthetic"])
    def cleanup(scenario_tag: str) -> dict[str, Any]:
        """Delete persisted synthetic rows belonging to one scenario tag."""
        try:
            with database.session() as session:
                deleted = cleanup_scenario(session, scenario_tag)
                session.commit()
        except SyntheticError as exc:
            raise _bad_request(exc) from exc
        return {"status": "deleted", "scenario_tag": scenario_tag, "deleted": deleted}

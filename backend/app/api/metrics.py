from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import Settings, get_settings
from app.schemas.metrics import SweepPoint, SweepRun
from app.services import metrics_service
from app.services.metrics_service import SweepMissingBaselineError, SweepNotFoundError

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/sweep/runs")
def get_sweep_runs(settings: Settings = Depends(get_settings)) -> list[SweepRun]:
    return metrics_service.list_available_runs(settings)


@router.get("/sweep", response_model=list[SweepPoint])
def get_sweep(
    mode: str = Query(..., pattern="^(baseline|noop)$"),
    row_count: int = Query(..., gt=0),
    settings: Settings = Depends(get_settings),
) -> list[SweepPoint]:
    try:
        return metrics_service.read_sweep(settings, mode, row_count)
    except SweepNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SweepMissingBaselineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

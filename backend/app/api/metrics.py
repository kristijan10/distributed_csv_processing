from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import Settings, get_settings
from app.schemas.metrics import SweepPoint
from app.services import metrics_service
from app.services.metrics_service import SweepMissingBaselineError, SweepNotFoundError

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/sweep/modes")
def get_sweep_modes(settings: Settings = Depends(get_settings)) -> list[str]:
    return metrics_service.list_available_modes(settings)


@router.get("/sweep", response_model=list[SweepPoint])
def get_sweep(
    mode: str = Query(..., pattern="^(baseline|noop)$"),
    settings: Settings = Depends(get_settings),
) -> list[SweepPoint]:
    try:
        return metrics_service.read_sweep(settings, mode)
    except SweepNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SweepMissingBaselineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

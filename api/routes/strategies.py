from fastapi import APIRouter

from config.strategies import STRATEGIES

router = APIRouter(tags=["strategies"])


@router.get("/strategies")
async def list_strategies():
    """Return strategy choices and implementation status for the frontend.

    This is deliberately metadata only. No strategy implementation is
    selected or executed by this endpoint.
    """
    return {"strategies": STRATEGIES}

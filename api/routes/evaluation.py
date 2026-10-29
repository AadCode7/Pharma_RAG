import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import ValidationError

from api.services.evaluation_service import evaluate_trace, summarize_results
from api.services.rbac_service import require_user
from database.client import get_service_client
from exception.exceptions import BadRequestError
from schemas.evaluation import EvaluationRunRequest

router = APIRouter(tags=["evaluation"])


@router.get("/evaluation/traces")
async def evaluation_traces(request: Request, limit: int = 50):
    """Return recent traces visible to the signed-in user for evaluation selection."""
    _user_id, user_client, _token = require_user(request)
    safe_limit = min(max(limit, 1), 100)
    response = (
        user_client.table("traces")
        .select("id,request_id,query_text,stage,latency_breakdown,created_at")
        .order("created_at", desc=True)
        .limit(safe_limit)
        .execute()
    )
    return {"traces": response.data or []}


@router.post("/evaluation/run")
async def run_evaluation(payload: EvaluationRunRequest, request: Request):
    user_id, user_client, _token = require_user(request)
    trace_ids = list(dict.fromkeys(item.trace_id for item in payload.items))
    if len(trace_ids) > 100:
        raise BadRequestError("An evaluation run can include at most 100 traces.")

    response = (
        user_client.table("traces")
        .select("id,request_id,query_text,stage,latency_breakdown,created_at")
        .in_("id", trace_ids)
        .execute()
    )
    traces_by_id = {str(row["id"]): row for row in (response.data or [])}
    missing = [trace_id for trace_id in trace_ids if trace_id not in traces_by_id]
    if missing:
        raise BadRequestError(
            "Some selected traces are no longer available to your account. Refresh the trace list and try again."
        )

    item_by_id = {item.trace_id: item.model_dump() for item in payload.items}
    results = [
        evaluate_trace(traces_by_id[trace_id], item_by_id[trace_id], payload.k)
        for trace_id in trace_ids
    ]
    summary = summarize_results(results)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Store a run snapshot so the user can compare evaluation sessions later.
    # Service-role writes are deliberate; reads remain scoped by user_id RLS.
    service = get_service_client()
    service.table("eval_trace_runs").insert({
        "id": run_id,
        "user_id": user_id,
        "config": {"k": payload.k, "method": "deterministic_trace_metrics_v1"},
        "summary": summary,
        "started_at": now,
        "completed_at": now,
    }).execute()
    service.table("eval_trace_results").insert([
        {
            "eval_run_id": run_id,
            "user_id": user_id,
            "trace_id": row["trace_id"],
            "query_text": row["query_text"],
            "metrics": row,
        }
        for row in results
    ]).execute()

    return {"run_id": run_id, "count": len(results), "summary": summary, "results": results}


@router.get("/evaluation/runs")
async def evaluation_runs(request: Request, limit: int = 10):
    user_id, user_client, _token = require_user(request)
    safe_limit = min(max(limit, 1), 50)
    response = (
        user_client.table("eval_trace_runs")
        .select("id,config,summary,started_at,completed_at")
        .eq("user_id", user_id)
        .order("started_at", desc=True)
        .limit(safe_limit)
        .execute()
    )
    return {"runs": response.data or []}


@router.get("/evaluation/runs/{run_id}")
async def evaluation_run_detail(run_id: str, request: Request):
    user_id, user_client, _token = require_user(request)
    run_response = (
        user_client.table("eval_trace_runs")
        .select("id,config,summary,started_at,completed_at")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    run = run_response.data
    if not run:
        raise BadRequestError("Evaluation run not found.")
    results_response = (
        user_client.table("eval_trace_results")
        .select("trace_id,query_text,metrics,created_at")
        .eq("eval_run_id", run_id)
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )
    return {"run": run, "results": results_response.data or []}

"""JSON-RPC 2.0 server for the Electron desktop app.

The runtime transport is newline-delimited JSON over stdio. Tests call
``handle_jsonrpc`` directly so the method surface stays stable without spawning
an Electron process.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel

from quantmind.desktop import read_model

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class RpcError(Exception):
    code: int
    message: str
    data: JsonDict | None = None


def _parse_date(value: Any, name: str = "date") -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise RpcError(-32602, "validation_error", {"field": name, "detail": "expected YYYY-MM-DD"})
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise RpcError(-32602, "validation_error", {"field": name, "detail": str(e)}) from e


def _params(raw: Any) -> JsonDict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RpcError(-32602, "validation_error", {"detail": "params must be an object"})
    return raw


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return json.loads(value.model_dump_json())
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _desktop_list_runs(params: JsonDict) -> Any:
    return read_model.list_run_summaries(limit=int(params.get("limit", 30)))


def _desktop_get_daily_summary(params: JsonDict) -> Any:
    return read_model.get_daily_summary(_parse_date(params.get("date")))


def _desktop_list_extracted_symbols(params: JsonDict) -> Any:
    return read_model.list_extracted_symbols(
        _parse_date(params.get("date")),
        code=params.get("code"),
        recommendation=params.get("recommendation"),
        min_confidence=params.get("min_confidence"),
    )


def _desktop_get_symbol_detail(params: JsonDict) -> Any:
    code = params.get("code")
    if not isinstance(code, str) or not code:
        raise RpcError(-32602, "validation_error", {"field": "code", "detail": "required"})
    return read_model.get_symbol_detail(_parse_date(params.get("date")), code)


def _desktop_get_debate_transcript(params: JsonDict) -> Any:
    code = params.get("code")
    if not isinstance(code, str) or not code:
        raise RpcError(-32602, "validation_error", {"field": "code", "detail": "required"})
    return read_model.get_debate_transcript(_parse_date(params.get("date")), code)


def _desktop_search_history(params: JsonDict) -> Any:
    return read_model.search_history(
        start_date=_parse_date(params["start_date"], "start_date")
        if params.get("start_date")
        else None,
        end_date=_parse_date(params["end_date"], "end_date") if params.get("end_date") else None,
        code=params.get("code"),
        recommendation=params.get("recommendation"),
        min_confidence=params.get("min_confidence"),
        pipeline_status=params.get("pipeline_status"),
        limit=int(params.get("limit", 100)),
    )


METHODS: dict[str, Callable[[JsonDict], Any]] = {
    "desktop.list_runs": _desktop_list_runs,
    "desktop.get_daily_summary": _desktop_get_daily_summary,
    "desktop.list_extracted_symbols": _desktop_list_extracted_symbols,
    "desktop.get_symbol_detail": _desktop_get_symbol_detail,
    "desktop.get_debate_transcript": _desktop_get_debate_transcript,
    "desktop.search_history": _desktop_search_history,
}


def handle_jsonrpc(request: JsonDict) -> JsonDict | None:
    """Handle one JSON-RPC request object."""
    request_id = request.get("id")
    if request.get("jsonrpc") != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32600, "message": "invalid_request"},
        }
    method_name = request.get("method")
    if not isinstance(method_name, str):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32600, "message": "invalid_request"},
        }
    method = METHODS.get(method_name)
    if method is None:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "method_not_found"},
        }
    try:
        result = method(_params(request.get("params")))
    except RpcError as e:
        error: JsonDict = {"code": e.code, "message": e.message}
        if e.data is not None:
            error["data"] = e.data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": "internal_error",
                "data": {"detail": f"{type(e).__name__}: {e}"},
            },
        }
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": _jsonable(result)}


def serve(input_stream: Any = sys.stdin, output_stream: Any = sys.stdout) -> None:
    """Serve newline-delimited JSON-RPC over stdio."""
    for line in input_stream:
        if not line.strip():
            continue
        response: JsonDict | None
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "parse_error",
                    "data": {"detail": str(e)},
                },
            }
        else:
            response = handle_jsonrpc(raw) if isinstance(raw, dict) else None
        if response is not None:
            output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
            output_stream.flush()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()

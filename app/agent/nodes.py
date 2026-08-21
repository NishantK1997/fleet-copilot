from typing import Any

from pydantic import ValidationError

from app.agent.huggingface import generate_grounded_answer_with_huggingface
from app.agent.planner import plan_tool_calls_hybrid
from app.agent.state import AgentState
from app.services.analytics import InsightDetectionInput
from app.services.proposals import ActionProposalInput
from app.tools import read_tools
from app.tools.proposal_tools import propose_action
from app.tools.schemas import (
    BatteryRiskDevicesInput,
    ComplianceFailuresInput,
    DeviceDetailsInput,
    DeviceMetricHistoryInput,
    Evidence,
    FleetSummaryInput,
    LowDiskDevicesInput,
    MemoryPressureDevicesInput,
    SearchDevicesInput,
    SearchTelemetryInput,
    SoftwareInventoryInput,
    ToolResult,
)


INPUT_MODELS = {
    "get_fleet_summary": FleetSummaryInput,
    "search_devices": SearchDevicesInput,
    "get_device_details": DeviceDetailsInput,
    "get_device_metric_history": DeviceMetricHistoryInput,
    "get_low_disk_devices": LowDiskDevicesInput,
    "get_memory_pressure_devices": MemoryPressureDevicesInput,
    "get_battery_risk_devices": BatteryRiskDevicesInput,
    "get_compliance_failures": ComplianceFailuresInput,
    "search_software_inventory": SoftwareInventoryInput,
    "search_telemetry": SearchTelemetryInput,
    "detect_insights": InsightDetectionInput,
    "propose_action": ActionProposalInput,
}

TOOL_FUNCTIONS = {
    **read_tools.READ_TOOLS,
    "propose_action": propose_action,
}


def planner_node(state: AgentState) -> dict[str, Any]:
    tool_calls, unsupported_reason = plan_tool_calls_hybrid(state["message"])
    return {"tool_calls": tool_calls, "unsupported_reason": unsupported_reason}


def tool_node(state: AgentState) -> dict[str, Any]:
    db = state["db"]
    context = state["context"]
    results: list[ToolResult] = []
    errors: list[str] = []

    for call in state.get("tool_calls", []):
        tool_name = call["tool"]
        tool = TOOL_FUNCTIONS.get(tool_name)
        input_model = INPUT_MODELS.get(tool_name)
        if tool is None or input_model is None:
            errors.append(f"Tool '{tool_name}' is not allowed.")
            continue
        try:
            payload = input_model(**call.get("arguments", {}))
            result = tool(db, context, payload)
        except (ValidationError, ValueError) as exc:
            errors.append(f"{tool_name} input was invalid: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{tool_name} could not return tenant-scoped evidence: {exc}")
            continue
        results.append(result)

    unsupported_reason = state.get("unsupported_reason")
    if errors:
        unsupported_reason = " ".join(errors)
    return {"tool_results": results, "unsupported_reason": unsupported_reason}


def evidence_node(state: AgentState) -> dict[str, Any]:
    evidence: list[Evidence] = []
    for result in state.get("tool_results", []):
        evidence.extend(result.evidence)
    unsupported_reason = state.get("unsupported_reason")
    if state.get("tool_calls") and not evidence:
        unsupported_reason = "The selected tools did not return evidence for this request."
    return {"evidence": evidence, "unsupported_reason": unsupported_reason}


def response_node(state: AgentState) -> dict[str, Any]:
    unsupported_reason = state.get("unsupported_reason")
    tool_results = state.get("tool_results", [])
    evidence = state.get("evidence", [])

    if unsupported_reason and not tool_results:
        return {"final_answer": f"I cannot answer that from the available telemetry. {unsupported_reason}"}

    if not evidence:
        return {"final_answer": "I cannot answer that from the available telemetry because no supporting evidence was returned."}

    hf_answer = generate_grounded_answer_with_huggingface(state["message"], tool_results, evidence)
    if hf_answer:
        return {"final_answer": hf_answer}

    return {"final_answer": _deterministic_answer(tool_results, evidence)}


def _deterministic_answer(tool_results: list[ToolResult], evidence: list[Evidence]) -> str:
    lines = []
    for result in tool_results:
        lines.append(result.summary)
        if isinstance(result.data, list):
            for row in result.data[:8]:
                device_id = row.get("device_id")
                collected_at = row.get("collected_at") or row.get("latest_collected_at")
                detail = ", ".join(f"{key}={value}" for key, value in row.items() if key not in {"company_id", "raw_payload"} and value is not None)
                prefix = f"- {device_id}: " if device_id else "- "
                suffix = f" Evidence time: {collected_at}." if collected_at else ""
                lines.append(f"{prefix}{detail}.{suffix}")
            if len(result.data) > 8:
                lines.append(f"- {len(result.data) - 8} more rows omitted.")
        else:
            lines.append(str(result.data))
    if evidence:
        cited = []
        for item in evidence[:5]:
            source = item.source
            device = f"device {item.device_id}" if item.device_id else "tenant"
            time = f" at {item.collected_at.isoformat()}" if item.collected_at else ""
            cited.append(f"{source}/{item.metric_or_check} for {device}{time}")
        lines.append("Evidence: " + "; ".join(cited) + ".")
    return "\n".join(lines)

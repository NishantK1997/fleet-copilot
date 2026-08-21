import json
import re
from typing import Any

from huggingface_hub import InferenceClient
from pydantic import ValidationError

from app.agent.huggingface import huggingface_is_configured
from app.agent.state import ToolCall
from app.config import get_settings
from app.services.analytics import InsightDetectionInput
from app.services.proposals import ActionProposalInput
from app.tools.schemas import (
    BatteryRiskDevicesInput,
    ComplianceFailuresInput,
    DeviceDetailsInput,
    DeviceMetricHistoryInput,
    FleetSummaryInput,
    LowDiskDevicesInput,
    MemoryPressureDevicesInput,
    SearchDevicesInput,
    SearchTelemetryInput,
    SoftwareInventoryInput,
)


DEVICE_ID_RE = re.compile(r"\b(?=[A-Z0-9]{8,16}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]+\b")
PLANNER_INPUT_MODELS = {
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
PLANNER_TOOL_DESCRIPTIONS = {
    "get_fleet_summary": "Fleet counts, OS distribution, compliance summary.",
    "search_devices": "Find latest tenant devices by OS, version, model, processor, employee, agent version.",
    "get_device_details": "Latest complete state for one device_id.",
    "get_device_metric_history": "Historical memory, disk, battery, or compliance series for one device_id.",
    "get_low_disk_devices": "Devices persistently low on disk/storage.",
    "get_memory_pressure_devices": "Devices persistently high in RAM/memory usage.",
    "get_battery_risk_devices": "Devices with battery condition, cycle, or capacity risk.",
    "get_compliance_failures": "Failing compliance checks by severity, check_id, or device.",
    "search_software_inventory": "Installed software search by name, version, publisher.",
    "search_telemetry": "Safe fallback search over allowed telemetry fields.",
    "detect_insights": "Fleet insights/trends: low disk, memory pressure, battery risk, compliance drift.",
    "propose_action": "Create a PENDING_APPROVAL action proposal; never executes the action.",
}


def _device_id_from(message: str) -> str | None:
    match = DEVICE_ID_RE.search(message.upper())
    return match.group(0) if match else None


def _limit_from(message: str, default: int = 50) -> int:
    match = re.search(r"\b(?:top|limit|show)\s+(\d{1,3})\b", message.lower())
    if not match:
        return default
    return max(1, min(int(match.group(1)), 200))


def _check_id_from(text: str) -> str | None:
    if "screen lock" in text:
        return "screen_lock"
    if "encryption" in text:
        return "disk_encryption"
    if "os up to date" in text or "os_up_to_date" in text:
        return "os_up_to_date"
    match = re.search(r"\b(check|check_id)\s+([a-z0-9_]+)\b", text)
    return match.group(2) if match else None


def _employee_id_from(message: str) -> str | None:
    match = re.search(r"\bemp-[a-z0-9-]+\b", message.lower())
    return match.group(0) if match else None


def plan_tool_calls_with_llm(message: str) -> tuple[list[ToolCall], str | None] | None:
    if not huggingface_is_configured():
        return None

    settings = get_settings()
    prompt = _planner_prompt(message)
    client = InferenceClient(model=settings.llm_model, token=settings.huggingface_api_key)
    try:
        response = client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You plan safe tool calls for Rayda Fleet Copilot. Return JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""
    except Exception:
        return None

    try:
        raw_plan = _extract_json(content)
        return validate_tool_plan(raw_plan)
    except Exception:
        return None


def validate_tool_plan(raw_plan: dict[str, Any]) -> tuple[list[ToolCall], str | None]:
    if not isinstance(raw_plan, dict):
        raise ValueError("planner output must be an object")
    unsupported_reason = raw_plan.get("unsupported_reason")
    raw_calls = raw_plan.get("tool_calls") or []
    if not isinstance(raw_calls, list):
        raise ValueError("tool_calls must be a list")

    calls: list[ToolCall] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise ValueError("tool call must be an object")
        tool_name = raw_call.get("tool")
        arguments = raw_call.get("arguments") or {}
        if tool_name not in PLANNER_INPUT_MODELS:
            raise ValueError(f"tool '{tool_name}' is not allowed")
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        if "company_id" in arguments:
            raise ValueError("company_id is never a tool argument")
        model = PLANNER_INPUT_MODELS[tool_name]
        try:
            validated = model(**arguments)
        except ValidationError as exc:
            raise ValueError(f"invalid arguments for {tool_name}: {exc}") from exc
        calls.append({"tool": tool_name, "arguments": validated.model_dump(mode="json", exclude_none=True)})

    if calls:
        return calls, None
    if unsupported_reason:
        return [], str(unsupported_reason)
    return [], "I could not map the request to available telemetry evidence."


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("no JSON object found")
        text = text[start : end + 1]
    return json.loads(text)


def _planner_prompt(message: str) -> str:
    tools = "\n".join(f"- {name}: {description}" for name, description in PLANNER_TOOL_DESCRIPTIONS.items())
    return (
        "Choose the minimum safe tool calls needed to answer the user question.\n"
        "Return strict JSON only with this shape:\n"
        '{"tool_calls":[{"tool":"tool_name","arguments":{}}],"unsupported_reason":null}\n\n'
        "Rules:\n"
        "- Use only listed tools.\n"
        "- Never include company_id. Tenant is injected by backend.\n"
        "- Never invent raw SQL or new tools.\n"
        "- For action requests, use propose_action and include required action arguments if present.\n"
        "- If unsupported, return no tool calls and a short unsupported_reason.\n\n"
        f"Available tools:\n{tools}\n\n"
        f"User question: {message}\n"
        "JSON:"
    )


def plan_tool_calls(message: str) -> tuple[list[ToolCall], str | None]:
    text = message.lower()
    device_id = _device_id_from(message)
    employee_id = _employee_id_from(message)
    calls: list[ToolCall] = []

    if any(term in text for term in ["create", "open", "order", "flag", "notify", "ticket", "proposal"]):
        if any(term in text for term in ["upgrade", "order", "storage", "ssd", "disk upgrade", "ram upgrade", "memory upgrade"]):
            component = "memory" if any(term in text for term in ["ram", "memory"]) else "storage"
            spec = "memory upgrade" if component == "memory" else "storage upgrade"
            return (
                [
                    {
                        "tool": "propose_action",
                        "arguments": {
                            "action_type": "create_upgrade_order",
                            "device_id": device_id,
                            "component": component,
                            "spec": spec,
                            "reason": message,
                        },
                    }
                ],
                None,
            )
        if any(term in text for term in ["remediation", "ticket", "compliance"]):
            return (
                [
                    {
                        "tool": "propose_action",
                        "arguments": {
                            "action_type": "open_remediation_ticket",
                            "device_id": device_id,
                            "check_id": _check_id_from(text),
                            "note": message,
                            "reason": message,
                        },
                    }
                ],
                None,
            )
        if any(term in text for term in ["replacement", "replace", "flag"]):
            return (
                [
                    {
                        "tool": "propose_action",
                        "arguments": {
                            "action_type": "flag_device_for_replacement",
                            "device_id": device_id,
                            "reason": message,
                        },
                    }
                ],
                None,
            )
        if "notify" in text:
            return (
                [
                    {
                        "tool": "propose_action",
                        "arguments": {
                            "action_type": "notify_employee",
                            "employee_id": employee_id,
                            "device_id": device_id,
                            "message": message,
                            "reason": message,
                        },
                    }
                ],
                None,
            )

    if any(term in text for term in ["insight", "insights", "trend", "trends", "drift", "patterns"]):
        include_types = []
        if any(term in text for term in ["disk", "storage"]):
            include_types.append("low_disk")
        if any(term in text for term in ["ram", "memory"]):
            include_types.append("memory_pressure")
        if "battery" in text:
            include_types.append("battery_risk")
        if any(term in text for term in ["compliance", "drift"]):
            include_types.append("compliance_drift")
        args = {"include_types": include_types} if include_types else {}
        return ([{"tool": "detect_insights", "arguments": args}], None)

    if any(term in text for term in ["summary", "overview", "fleet health", "how many devices", "device count"]):
        return ([{"tool": "get_fleet_summary", "arguments": {"include_compliance": True}}], None)

    if any(term in text for term in ["low disk", "storage", "disk space", "low on disk"]):
        return ([{"tool": "get_low_disk_devices", "arguments": {}}], None)

    if any(term in text for term in ["ram", "memory", "constrained"]):
        if device_id and any(term in text for term in ["history", "over time", "trend"]):
            return ([{"tool": "get_device_metric_history", "arguments": {"device_id": device_id, "metric": "memory", "limit": 30}}], None)
        return ([{"tool": "get_memory_pressure_devices", "arguments": {}}], None)

    if any(term in text for term in ["battery", "cycle", "replacement risk"]):
        if device_id and any(term in text for term in ["history", "over time", "trend"]):
            return ([{"tool": "get_device_metric_history", "arguments": {"device_id": device_id, "metric": "battery", "limit": 30}}], None)
        return ([{"tool": "get_battery_risk_devices", "arguments": {}}], None)

    if any(term in text for term in ["compliance", "failing", "failures", "screen lock", "encryption", "os up to date"]):
        args: dict[str, Any] = {"latest_only": True, "limit": _limit_from(message, 100)}
        if "high" in text:
            args["severity"] = "high"
        elif "medium" in text:
            args["severity"] = "medium"
        check_id = _check_id_from(text)
        if check_id:
            args["check_id"] = check_id
        if device_id:
            args["device_id"] = device_id
        return ([{"tool": "get_compliance_failures", "arguments": args}], None)

    if any(term in text for term in ["software", "installed", "chrome", "slack", "zoom", "1password", "vscode", "visual studio code"]):
        args = {"limit": _limit_from(message, 100)}
        for name in ["chrome", "slack", "zoom", "1password", "teamviewer", "utorrent"]:
            if name in text:
                args["name_contains"] = name
                break
        if "visual studio code" in text or "vscode" in text:
            args["name_contains"] = "Visual Studio Code"
        return ([{"tool": "search_software_inventory", "arguments": args}], None)

    if device_id:
        metric = None
        if "disk" in text:
            metric = "disk"
        elif "battery" in text:
            metric = "battery"
        elif "memory" in text or "ram" in text:
            metric = "memory"
        elif "compliance" in text:
            metric = "compliance"
        if metric and any(term in text for term in ["history", "over time", "trend"]):
            return ([{"tool": "get_device_metric_history", "arguments": {"device_id": device_id, "metric": metric, "limit": 30}}], None)
        return ([{"tool": "get_device_details", "arguments": {"device_id": device_id}}], None)

    if any(term in text for term in ["macos older than", "older than macos", "os older than"]):
        version_match = re.search(r"(?:macos|os)[^\d]*(\d+(?:\.\d+)?)", text)
        version = version_match.group(1) if version_match else "15"
        return ([{"tool": "search_devices", "arguments": {"os_product_version_lt": version, "limit": _limit_from(message, 100)}}], None)

    if any(term in text for term in ["mac", "windows", "laptop", "device", "devices"]):
        args: dict[str, Any] = {"limit": _limit_from(message, 50)}
        if "mac" in text:
            args["os_platform"] = "darwin"
        if "windows" in text:
            args["os_platform"] = "windows"
        if "laptop" in text:
            args["model_name"] = "MacBook Pro" if "mac" in text else None
        return ([{"tool": "search_devices", "arguments": {k: v for k, v in args.items() if v is not None}}], None)

    return (calls, "I could not map the request to available telemetry evidence.")


def plan_tool_calls_hybrid(message: str) -> tuple[list[ToolCall], str | None]:
    if _looks_like_action_request(message):
        return plan_tool_calls(message)
    llm_plan = plan_tool_calls_with_llm(message)
    if llm_plan is not None:
        return llm_plan
    return plan_tool_calls(message)


def _looks_like_action_request(message: str) -> bool:
    text = message.lower()
    return any(term in text for term in ["create", "open", "order", "flag", "notify", "ticket", "proposal", "approve", "reject"])

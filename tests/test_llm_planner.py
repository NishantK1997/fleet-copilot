from app.agent import planner


def test_validate_tool_plan_accepts_allowed_tool():
    calls, reason = planner.validate_tool_plan(
        {"tool_calls": [{"tool": "get_low_disk_devices", "arguments": {}}], "unsupported_reason": None}
    )
    assert reason is None
    assert calls == [{"tool": "get_low_disk_devices", "arguments": {"threshold_percent": 10, "min_ratio": 0.5, "limit": 50}}]


def test_validate_tool_plan_rejects_company_id():
    try:
        planner.validate_tool_plan(
            {
                "tool_calls": [
                    {"tool": "search_devices", "arguments": {"company_id": "globex-002", "limit": 10}}
                ]
            }
        )
    except ValueError as exc:
        assert "company_id" in str(exc)
    else:
        raise AssertionError("company_id was accepted")


def test_validate_tool_plan_rejects_unknown_tool():
    try:
        planner.validate_tool_plan({"tool_calls": [{"tool": "run_sql", "arguments": {}}]})
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("unknown tool was accepted")


def test_hybrid_falls_back_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(planner, "plan_tool_calls_with_llm", lambda message: None)
    calls, reason = planner.plan_tool_calls_hybrid("Which devices are low on disk space?")
    assert reason is None
    assert calls[0]["tool"] == "get_low_disk_devices"


def test_hybrid_uses_deterministic_path_for_action_requests(monkeypatch):
    monkeypatch.setattr(
        planner,
        "plan_tool_calls_with_llm",
        lambda message: ([{"tool": "get_device_details", "arguments": {"device_id": "1LYSSFD074BB"}}], None),
    )
    calls, reason = planner.plan_tool_calls_hybrid("Open a remediation ticket for 1LYSSFD074BB os up to date")
    assert reason is None
    assert calls[0]["tool"] == "propose_action"
    assert calls[0]["arguments"]["action_type"] == "open_remediation_ticket"


def test_extract_json_from_markdown_block():
    raw = '```json\n{"tool_calls":[{"tool":"get_fleet_summary","arguments":{}}]}\n```'
    parsed = planner._extract_json(raw)
    assert parsed["tool_calls"][0]["tool"] == "get_fleet_summary"

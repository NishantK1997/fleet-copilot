import os
from typing import Any

import requests
import streamlit as st


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
EXAMPLE_PROMPTS = [
    "Give me fleet summary",
    "Which devices are low on disk space?",
    "Show me fleet insights",
    "Show me medium severity compliance failures",
    "Open a remediation ticket for 1LYSSFD074BB os up to date",
]


st.set_page_config(page_title="Rayda Fleet Copilot", layout="wide")


def init_state() -> None:
    st.session_state.setdefault("token", None)
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("action_results", {})
    st.session_state.setdefault("pending_message", None)


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {st.session_state.token}"}


def api_post(path: str, payload: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    try:
        response = requests.post(
            f"{API_BASE_URL}{path}",
            json=payload or {},
            headers=auth_headers() if st.session_state.token else None,
            timeout=30,
        )
    except requests.RequestException as exc:
        return False, {"detail": str(exc)}
    if response.status_code >= 400:
        return False, response.json() if response.content else {"detail": response.text}
    return True, response.json()


def login(email: str, password: str) -> tuple[bool, str | None]:
    try:
        response = requests.post(
            f"{API_BASE_URL}/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
    except requests.RequestException as exc:
        return False, str(exc)
    if response.status_code != 200:
        detail = response.json().get("detail", "Login failed") if response.content else "Login failed"
        return False, detail
    body = response.json()
    st.session_state.token = body["access_token"]
    st.session_state.user = body["user"]
    st.session_state.messages = []
    st.session_state.action_results = {}
    st.session_state.pending_message = None
    return True, None


def logout() -> None:
    st.session_state.token = None
    st.session_state.user = None
    st.session_state.messages = []
    st.session_state.action_results = {}
    st.session_state.pending_message = None
    st.rerun()


def render_login() -> None:
    st.title("Rayda Fleet Copilot")
    st.caption(f"API: {API_BASE_URL}")
    with st.form("login_form"):
        email = st.text_input("Email", value="admin@acme.example")
        password = st.text_input("Password", value="AcmeAdmin123!", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        ok, error = login(email, password)
        if ok:
            st.rerun()
        st.error(error or "Login failed")


def proposal_from_response(response: dict[str, Any]) -> dict[str, Any] | None:
    for result in response.get("tool_results", []):
        if result.get("tool") != "propose_action":
            continue
        data = result.get("data") or {}
        if data.get("created") and data.get("status") == "PENDING_APPROVAL":
            return data
    return None


def render_evidence(evidence: list[dict[str, Any]]) -> None:
    if not evidence:
        return
    with st.expander(f"Evidence ({len(evidence)})", expanded=False):
        for item in evidence:
            label = item.get("metric_or_check", "evidence")
            device = item.get("device_id") or "tenant"
            st.markdown(f"**{label}** · `{device}`")
            st.json(item)


def render_tool_details(response: dict[str, Any]) -> None:
    calls = response.get("tool_calls") or []
    summaries = response.get("tool_summaries") or []
    if not calls and not summaries:
        return
    with st.expander("Tool Trace", expanded=False):
        if calls:
            st.write("Tool calls")
            st.json(calls)
        if summaries:
            st.write("Summaries")
            for summary in summaries:
                st.write(summary)


def render_proposal(proposal: dict[str, Any], message_index: int) -> None:
    proposal_id = proposal.get("proposal_id")
    if not proposal_id:
        return
    action_result = st.session_state.action_results.get(str(proposal_id))
    st.subheader("Pending Approval")
    st.write(f"Proposal `{proposal_id}` · `{proposal.get('action_type')}`")
    st.write(proposal.get("reason"))
    st.json(proposal.get("proposed_arguments", {}))

    if action_result:
        message = action_result.get("message", "Action request completed.")
        status = action_result.get("proposal_status")
        if status == "EXECUTED":
            st.success(message)
        elif status == "REJECTED":
            st.warning(message)
        else:
            st.info(message)
        return

    col1, col2 = st.columns(2)
    approve_key = f"approve_{message_index}_{proposal_id}"
    reject_key = f"reject_{message_index}_{proposal_id}"
    with col1:
        if st.button("Approve", key=approve_key):
            ok, body = api_post(f"/actions/{proposal_id}/approve")
            append_action_result(ok, body)
            st.rerun()
    with col2:
        if st.button("Reject", key=reject_key):
            ok, body = api_post(f"/actions/{proposal_id}/reject")
            append_action_result(ok, body)
            st.rerun()


def append_action_result(ok: bool, body: dict[str, Any]) -> None:
    content = body if ok else {"error": body.get("detail", body)}
    message = content.get("message", "Action request failed.")
    if ok and content.get("proposal_id"):
        st.session_state.action_results[str(content["proposal_id"])] = content
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": message,
            "response": {
                "answer": message,
                "tool_calls": [],
                "tool_summaries": [],
                "tool_results": [{"tool": "action_result", "data": content}],
                "evidence": [],
            },
        }
    )


def queue_chat(message: str) -> None:
    st.session_state.messages.append({"role": "user", "content": message})
    st.session_state.pending_message = message


def append_chat_response(message: str) -> None:
    ok, body = api_post("/chat", {"message": message})
    if not ok:
        body = {
            "answer": f"Chat request failed: {body.get('detail', body)}",
            "tool_calls": [],
            "tool_summaries": [],
            "tool_results": [],
            "evidence": [],
        }
    st.session_state.messages.append({"role": "assistant", "content": body["answer"], "response": body})
    st.session_state.pending_message = None


def render_pending_response() -> None:
    pending_message = st.session_state.pending_message
    if not pending_message:
        return

    with st.chat_message("assistant"):
        progress = st.progress(35)
        with st.spinner("Processing your request..."):
            append_chat_response(pending_message)
        progress.progress(100)
    st.rerun()


def render_app() -> None:
    user = st.session_state.user
    st.title("Rayda Fleet Copilot")
    left, right = st.columns([3, 1])
    with left:
        st.caption(f"{user['email']} · tenant `{user['company_id']}` · role `{user['role']}`")
    with right:
        if st.button("Logout"):
            logout()

    prompt_cols = st.columns(len(EXAMPLE_PROMPTS))
    for index, prompt in enumerate(EXAMPLE_PROMPTS):
        if prompt_cols[index].button(prompt, key=f"example_{index}"):
            queue_chat(prompt)
            st.rerun()

    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            response = message.get("response")
            if response:
                render_tool_details(response)
                render_evidence(response.get("evidence", []))
                proposal = proposal_from_response(response)
                if proposal:
                    render_proposal(proposal, index)

    render_pending_response()

    user_message = st.chat_input("Ask about fleet health, compliance, insights, or propose an action")
    if user_message:
        queue_chat(user_message)
        st.rerun()


init_state()
if st.session_state.token:
    render_app()
else:
    render_login()

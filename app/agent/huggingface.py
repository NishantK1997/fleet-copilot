from __future__ import annotations

from huggingface_hub import InferenceClient

from app.config import get_settings
from app.tools.schemas import Evidence, ToolResult


def huggingface_is_configured() -> bool:
    settings = get_settings()
    return bool(settings.huggingface_api_key and settings.huggingface_api_key != "replace-with-your-huggingface-key")


def generate_grounded_answer_with_huggingface(message: str, tool_results: list[ToolResult], evidence: list[Evidence]) -> str | None:
    if not huggingface_is_configured():
        return None

    settings = get_settings()
    prompt = _build_prompt(message, tool_results, evidence)
    client = InferenceClient(model=settings.llm_model, token=settings.huggingface_api_key)
    try:
        response = client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You are Rayda Fleet Copilot. Answer only from supplied tool results and evidence.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=350,
            temperature=0.1,
        )
        answer = response.choices[0].message.content
    except Exception:
        try:
            answer = client.text_generation(
                prompt,
                max_new_tokens=350,
                temperature=0.1,
                return_full_text=False,
            )
        except Exception:
            return None
    return answer or None


def _build_prompt(message: str, tool_results: list[ToolResult], evidence: list[Evidence]) -> str:
    compact_results = [
        {
            "tool": result.tool,
            "summary": result.summary,
            "data": result.data[:10] if isinstance(result.data, list) else result.data,
        }
        for result in tool_results
    ]
    compact_evidence = [item.model_dump(mode="json") for item in evidence[:20]]
    return (
        "You are Rayda Fleet Copilot. Answer only from the deterministic tool results and evidence below. "
        "The tool results are authoritative. Do not contradict counts, findings, or thresholds computed by tools. "
        "If a tool says devices met criteria, report every returned device in the data. "
        "Do not reinterpret a metric as safe when the tool already classified it as a finding. "
        "If evidence is insufficient, say so. Keep the answer concise and cite device IDs and timestamps when useful.\n\n"
        f"User question: {message}\n\n"
        f"Tool results: {compact_results}\n\n"
        f"Evidence: {compact_evidence}\n\n"
        "Grounded answer:"
    )

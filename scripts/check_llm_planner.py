import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.planner import plan_tool_calls_hybrid, plan_tool_calls_with_llm


def main() -> None:
    questions = [
        "Which laptops are almost out of storage?",
        "Show me fleet compliance drift insights",
        "Open a remediation ticket for 1LYSSFD074BB os up to date",
    ]
    for question in questions:
        llm_plan = plan_tool_calls_with_llm(question)
        plan = plan_tool_calls_hybrid(question)
        source = "hybrid"
        print(question)
        if llm_plan:
            print("llm_suggestion", llm_plan)
        print(source, plan)
        assert plan[0] or plan[1]
    print("planner check: PASS")


if __name__ == "__main__":
    main()

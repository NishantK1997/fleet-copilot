from sqlalchemy.orm import Session
from langgraph.graph import END, StateGraph

from app.agent.nodes import evidence_node, planner_node, response_node, tool_node
from app.agent.state import AgentState
from app.auth.dependencies import TenantContext


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("tools", tool_node)
    graph.add_node("collect_evidence", evidence_node)
    graph.add_node("response", response_node)
    graph.set_entry_point("planner")
    graph.add_edge("planner", "tools")
    graph.add_edge("tools", "collect_evidence")
    graph.add_edge("collect_evidence", "response")
    graph.add_edge("response", END)
    return graph.compile()


AGENT_GRAPH = build_agent_graph()


def run_agent(message: str, db: Session, context: TenantContext) -> AgentState:
    initial_state: AgentState = {
        "message": message,
        "db": db,
        "context": context,
        "tool_calls": [],
        "tool_results": [],
        "evidence": [],
        "final_answer": "",
        "unsupported_reason": None,
    }
    return AGENT_GRAPH.invoke(initial_state)

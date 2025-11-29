# app/agents/graph.py
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes import verification_node, triage_node, wellness_node, medical_node

def route_verification(state):
    return "triage" if state.get("is_verified") else "verification"

def route_intent(state):
    intent = state.get("intent", "general")
    if intent == "medical": return "medical"
    if intent == "wellness": return "wellness"
    return END

workflow = StateGraph(AgentState)

workflow.add_node("verification", verification_node)
workflow.add_node("triage", triage_node)
workflow.add_node("wellness", wellness_node)
workflow.add_node("medical", medical_node)

workflow.set_entry_point("verification")

workflow.add_conditional_edges(
    "verification",
    route_verification,
    {"verification": END, "triage": "triage"}
)

workflow.add_conditional_edges(
    "triage",
    route_intent,
    {"medical": "medical", "wellness": "wellness", END: END}
)

workflow.add_edge("wellness", END)
workflow.add_edge("medical", END)

app_graph = workflow.compile()
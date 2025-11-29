from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes import (
    verification_node,
    menu_node,
    wellness_node,
    medical_node,
    appointment_node,
)


# --- Rutas del grafo ---

def route_verification(state: AgentState):
    """
    - Si NO está verificado → nos quedamos en 'verification' (pide DNI / código).
    - Si se acaba de verificar (just_verified = True) → terminamos el flujo en este turno.
    - Si ya está verificado desde antes → vamos al menú principal.
    """
    if not state.get("is_verified"):
        return "verification"

    if state.get("just_verified"):
        # Terminamos aquí, ya enviamos el menú en verification_node
        return "verification"

    # Usuario verificado en mensajes posteriores → ir al menú
    return "menu"


def route_menu(state: AgentState):
    """
    Decide a qué nodo ir según la opción elegida en el menú.
    """
    flow = state.get("flow")
    if flow == "appointment":
        return "appointment"
    if flow == "wellness":
        return "wellness"
    if flow == "medical":
        return "medical"
    return END


# --- Definición del workflow ---

workflow = StateGraph(AgentState)

workflow.add_node("verification", verification_node)
workflow.add_node("menu", menu_node)
workflow.add_node("wellness", wellness_node)
workflow.add_node("medical", medical_node)
workflow.add_node("appointment", appointment_node)

workflow.set_entry_point("verification")

# Desde verificación → o seguimos verificando, o vamos al menú
workflow.add_conditional_edges(
    "verification",
    route_verification,
    {"verification": END, "menu": "menu"},
)

# Desde el menú → cita / wellness / info médica / fin
workflow.add_conditional_edges(
    "menu",
    route_menu,
    {"appointment": "appointment", "wellness": "wellness", "medical": "medical", END: END},
)

# Nodos terminales
workflow.add_edge("wellness", END)
workflow.add_edge("medical", END)
workflow.add_edge("appointment", END)

app_graph = workflow.compile()

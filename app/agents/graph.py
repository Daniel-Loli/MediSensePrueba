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
    Decidimos a qué nodo ir después de ejecutar 'verification':

    - Si NO está verificado → seguimos en 'verification'.
    - Si se acaba de verificar (just_verified = True) → terminamos el turno
      (ya enviamos el menú desde verification_node).
    - Si ya estaba verificado:
        * Si tiene un flujo activo (appointment / wellness / medical) → ir directo ahí.
        * Si no tiene flujo → ir al menú principal.
    """
    if not state.get("is_verified"):
        # Todavía no pasó verificación
        return "verification"

    # Turno en el que se validó el código: verification_node ya envió el menú
    if state.get("just_verified"):
        return "verification"  # mapeado a END más abajo

    # Usuario ya verificado de antes: retomamos el flujo actual
    flow = state.get("flow")
    if flow in ("appointment", "wellness", "medical"):
        return flow

    # Sin flujo activo → ir al menú
    return "menu"


def route_menu(state: AgentState):
    """
    Decide a qué nodo ir DESPUÉS de ejecutar 'menu_node',
    en función del 'flow' que dejó seteado.
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

# Después de 'verification' decidimos si:
# - seguimos verificando
# - terminamos (just_verified)
# - vamos al menú
# - retomamos un flujo ya activo (appointment / wellness / medical)
workflow.add_conditional_edges(
    "verification",
    route_verification,
    {
        "verification": END,          # cuando just_verified == True
        "menu": "menu",
        "appointment": "appointment",
        "wellness": "wellness",
        "medical": "medical",
    },
)

# Desde el menú, en el MISMO turno, saltamos a la opción elegida
workflow.add_conditional_edges(
    "menu",
    route_menu,
    {
        "appointment": "appointment",
        "wellness": "wellness",
        "medical": "medical",
        END: END,
    },
)

# Nodos terminales para este turno
workflow.add_edge("wellness", END)
workflow.add_edge("medical", END)
workflow.add_edge("appointment", END)

app_graph = workflow.compile()

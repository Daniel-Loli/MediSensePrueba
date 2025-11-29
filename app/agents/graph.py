from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes import (
    verification_node,
    menu_node,
    wellness_node,
    medical_node,
    appointment_node,
)


# ==========================================================
# RUTAS DEL GRAFO
# ==========================================================


def route_verification(state: AgentState):
    """
    Decidimos a qué nodo ir después de ejecutar 'verification':

    - Si NO está verificado → seguimos en 'verification' (pero el turno termina).
    - Si se acaba de verificar (just_verified = True) → terminamos el turno
      (ya enviamos el menú desde verification_node).
    - Si ya estaba verificado:
        * Si tiene un flujo activo (appointment / wellness / medical) → ir directo ahí.
        * Si no tiene flujo → ir al menú principal.
    """
    if not state.get("is_verified"):
        # Todavía no pasó verificación (seguimos en el flujo de verificación)
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
    Decide a qué nodo ir DESPUÉS de ejecutar 'menu_node'.

    ⚠ IMPORTANTE:
    - Para 'wellness' e 'medical' SÍ saltamos en el mismo turno.
    - Para 'appointment' NO avanzamos en este turno: solo dejamos
      flow="appointment" y terminamos. El siguiente mensaje ya entra
      directo a appointment_node.
    """
    flow = state.get("flow")

    # Saltos inmediatos (mismo turno)
    if flow == "wellness":
        return "wellness"
    if flow == "medical":
        return "medical"

    # Para 'appointment' o cualquier otra cosa, terminamos turno.
    return END


# ==========================================================
# DEFINICIÓN DEL WORKFLOW
# ==========================================================

workflow = StateGraph(AgentState)

# Nodos
workflow.add_node("verification", verification_node)
workflow.add_node("menu", menu_node)
workflow.add_node("wellness", wellness_node)
workflow.add_node("medical", medical_node)
workflow.add_node("appointment", appointment_node)

# Punto de entrada
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
        # Cualquier retorno "verification" termina el turno
        # (sea porque aún falta código/DNI o porque just_verified=True)
        "verification": END,
        "menu": "menu",
        "appointment": "appointment",
        "wellness": "wellness",
        "medical": "medical",
    },
)

# Desde el menú:
# - wellness / medical → se ejecutan en el mismo turno
# - appointment → se deja marcado el flujo pero NO se ejecuta aquí
workflow.add_conditional_edges(
    "menu",
    route_menu,
    {
        "wellness": "wellness",
        "medical": "medical",
        END: END,
    },
)

# Nodos terminales para este turno
workflow.add_edge("wellness", END)
workflow.add_edge("medical", END)
workflow.add_edge("appointment", END)

# Grafo compilado
app_graph = workflow.compile()

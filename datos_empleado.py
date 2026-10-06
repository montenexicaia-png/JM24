"""
Qué datos le faltan a un empleado cargado desde una lista (estado INCOMPLETO).

Sin dependencias del proyecto a propósito: lo importan el panel (que se conecta con `st.secrets`),
el bot y `avisos_datos.py`. Importar `database` o `main` desde el panel exigiría el `.env`
o arrancaría el scheduler.
"""

ESTADO_INCOMPLETO = "INCOMPLETO"
ROL_POR_DEFINIR = "Por definir"  # `rol` es NOT NULL en `empleados`, así que los cargados sin puesto lo llevan

# Cómo se le nombra cada dato faltante a RH en el panel
ETIQUETA_DATO = {
    "telefono": "teléfono",
    "puesto": "puesto",
    "rango": "rango",
    "obra": "obra",
    "foto": "foto",
}


def datos_faltantes(empleado: dict) -> list[str]:
    """
    Devuelve qué datos le faltan a un empleado: "telefono", "puesto", "rango", "obra", "foto".
    Lista vacía = registro completo. El nombre no se revisa: sin él el registro ni siquiera existe.
    El bot nunca pregunta "telefono": quien le escribe ya entró por su número.
    """
    faltan = []
    if not (empleado.get("telefono") or "").strip():
        faltan.append("telefono")
    rol = (empleado.get("rol") or "").strip()
    if not rol or rol == ROL_POR_DEFINIR:
        faltan.append("puesto")
    if not (empleado.get("rango") or "").strip():
        faltan.append("rango")
    obra = (empleado.get("obra_actual") or "").strip()
    if not obra or obra == "Sin Obra":
        faltan.append("obra")
    if not (empleado.get("foto_perfil_url") or "").strip():
        faltan.append("foto")
    return faltan


def filas_personal_por_completar(empleados: list[dict]) -> list[dict]:
    """Filas para la tabla del panel: solo los INCOMPLETO, con lo que le falta a cada uno."""
    filas = []
    for e in empleados:
        if e.get("estado") != ESTADO_INCOMPLETO:
            continue
        filas.append({
            "ID": e.get("empleado_id"),
            "Nombre": e.get("nombre_completo"),
            "Obra": (e.get("obra_actual") or "").strip() or "Sin Obra",
            "Puesto": (e.get("rol") or "").strip() or ROL_POR_DEFINIR,
            "Rango": (e.get("rango") or "").strip() or "—",
            "Teléfono": (e.get("telefono") or "").strip() or "—",
            "Le falta": ", ".join(ETIQUETA_DATO[d] for d in datos_faltantes(e)) or "—",
        })
    return sorted(filas, key=lambda f: (f["Obra"], f["Nombre"] or ""))

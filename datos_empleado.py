"""
Qué datos le faltan a un empleado cargado desde una lista (estado INCOMPLETO).

Sin dependencias del proyecto a propósito: lo importan el panel (que se conecta con `st.secrets`),
el bot y `avisos_datos.py`. Importar `database` o `main` desde el panel exigiría el `.env`
o arrancaría el scheduler.
"""
import re

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
    """Filas para la tabla del panel: solo los INCOMPLETO, con lo que le falta a cada uno. Sin dato = texto vacío."""
    filas = []
    for e in empleados:
        if e.get("estado") != ESTADO_INCOMPLETO:
            continue
        filas.append({
            "ID": e.get("empleado_id"),
            "Nombre": (e.get("nombre_completo") or "").strip(),
            "Teléfono": (e.get("telefono") or "").strip(),
            "Puesto": (e.get("rol") or "").strip() or ROL_POR_DEFINIR,
            "Rango": (e.get("rango") or "").strip(),
            "Obra": (e.get("obra_actual") or "").strip() or "Sin Obra",
            "Le falta": ", ".join(ETIQUETA_DATO[d] for d in datos_faltantes(e)) or "—",
        })
    return sorted(filas, key=lambda f: (f["Obra"], f["Nombre"]))


def normalizar_telefono_mx(texto) -> str | None:
    """
    Deja el teléfono en el formato que usa la base ("+52" y 10 dígitos), o None si no se entiende.
    Acepta espacios, guiones, puntos y paréntesis, y estas formas: 10 dígitos, 52 + 10, 521 + 10
    (el 1 que Meta le antepone a los celulares de México).
    """
    texto = str(texto or "").strip()
    if not texto or not re.fullmatch(r"[\d\s\-().+]+", texto):
        return None
    digitos = re.sub(r"\D", "", texto)
    if len(digitos) == 13 and digitos.startswith("521"):
        digitos = digitos[3:]
    elif len(digitos) == 12 and digitos.startswith("52"):
        digitos = digitos[2:]
    if len(digitos) != 10:
        return None
    return "+52" + digitos


def _texto(valor) -> str:
    """Texto limpio de una celda de la tabla editable (None o NaN = vacío)."""
    if valor is None or (isinstance(valor, float) and valor != valor):
        return ""
    return str(valor).strip()


def cambios_por_completar(originales: list[dict], editadas: list[dict],
                          telefonos_ocupados: dict[str, tuple[str, str]]) -> tuple[dict[str, dict], list[str]]:
    """
    Compara la tabla editable contra la original y devuelve (cambios, errores).
    cambios = {empleado_id: {columna de la base: valor nuevo}}, solo con lo que cambió, listo para un update.
    errores = mensajes para RH; si hay alguno no debe guardarse nada.
    telefonos_ocupados = {telefono: (empleado_id, nombre)} de TODOS los empleados de la base (para no repetir).
    """
    por_id = {f["ID"]: f for f in originales}
    cambios, errores, asignados = {}, [], {}  # asignados: teléfonos que se dan en esta misma tanda

    for fila in editadas:
        eid = fila.get("ID")
        orig = por_id.get(eid)
        if orig is None:
            continue
        nuevo = {}

        nombre = " ".join(_texto(fila.get("Nombre")).split())
        if not nombre:
            errores.append(f"{eid}: el nombre no puede quedar vacío.")
        elif nombre != orig["Nombre"]:
            nuevo["nombre_completo"] = nombre

        tel_texto = _texto(fila.get("Teléfono"))
        if tel_texto != orig["Teléfono"]:
            if not tel_texto:
                nuevo["telefono"] = None
            else:
                tel = normalizar_telefono_mx(tel_texto)
                dueno = telefonos_ocupados.get(tel)
                if tel is None:
                    errores.append(f"{orig['Nombre']}: el teléfono «{tel_texto}» no es válido (usa 10 dígitos, o +52 y 10 dígitos).")
                elif dueno and dueno[0] != eid:
                    errores.append(f"{orig['Nombre']}: el teléfono {tel} ya lo tiene {dueno[1]} ({dueno[0]}).")
                elif asignados.get(tel, eid) != eid:
                    errores.append(f"{orig['Nombre']}: el teléfono {tel} se repite con otra persona de esta misma tabla.")
                else:
                    asignados[tel] = eid
                    if tel != orig["Teléfono"]:
                        nuevo["telefono"] = tel

        puesto = _texto(fila.get("Puesto")) or ROL_POR_DEFINIR
        if puesto != orig["Puesto"]:
            nuevo["rol"] = puesto

        rango = _texto(fila.get("Rango"))
        if rango != orig["Rango"]:
            nuevo["rango"] = rango or None

        obra = _texto(fila.get("Obra")) or "Sin Obra"
        if obra != orig["Obra"]:
            nuevo["obra_actual"] = obra

        if nuevo:
            cambios[eid] = nuevo

    return cambios, errores

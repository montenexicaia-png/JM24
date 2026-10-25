"""
Permisos por lista: quién puede hacer qué en el bot.

Cada permiso es un código guardado en `empleados.permisos` (arreglo de texto). Quien no tiene
ningún permiso usa el registro simple (entrada, salida y nada más). Este módulo es la única
fuente del catálogo: el bot, el servidor y el panel lo importan.

NO importa `main` ni `streamlit` a propósito (importar `main` arranca el scheduler y puede
disparar mensajes reales). El cliente de Supabase se recibe como parámetro.
"""
from dataclasses import dataclass

REPORTE_SEMANAL = "REPORTE_SEMANAL"
CONTROL_ASISTENCIA = "CONTROL_ASISTENCIA"
RECIBIR_URGENCIAS = "RECIBIR_URGENCIAS"
ENVIAR_AVISOS = "ENVIAR_AVISOS"
MI_CUADRILLA = "MI_CUADRILLA"
FOTO_GRUPAL = "FOTO_GRUPAL"
REGISTRO_CON_FOTO = "REGISTRO_CON_FOTO"


@dataclass(frozen=True)
class Permiso:
    codigo: str
    icono: str
    nombre: str              # lo único que ve quien opera el panel
    descripcion: str         # una frase: qué puede hacer quien lo tiene
    exige_telefono: bool = False   # True si el permiso es "recibir" algo por WhatsApp
    nota: str = ""           # aclaración extra para el panel

    @property
    def etiqueta(self) -> str:
        return f"{self.icono} {self.nombre}"


CATALOGO = (
    Permiso(REPORTE_SEMANAL, "📄", "Recibe el reporte semanal (PDF)",
            "Le llega por WhatsApp el PDF de asistencia de la semana.", exige_telefono=True),
    Permiso(CONTROL_ASISTENCIA, "🔔", "Control de asistencia",
            "Recibe el recordatorio en la hora de corte y puede escribir AVISAR para recordarle "
            "a quien falte de registrarse.", exige_telefono=True),
    Permiso(RECIBIR_URGENCIAS, "🚨", "Recibe las urgencias",
            "Le llega un WhatsApp en cuanto alguien reporta una urgencia.", exige_telefono=True,
            nota="Quien reporta la urgencia no recibe su propia alerta. Si nadie más la recibe, llega al contratista."),
    Permiso(ENVIAR_AVISOS, "📣", "Puede reportar avisos y urgencias",
            "Ve en su menú las opciones de AVISO (novedad normal) y URGENCIA (problema crítico)."),
    Permiso(MI_CUADRILLA, "👷", "Consulta su cuadrilla",
            "Escribe MI CUADRILLA y recibe quién ya llegó y quién falta, con sus fotos."),
    Permiso(FOTO_GRUPAL, "📸", "Foto grupal de su cuadrilla",
            "Mandará una foto de su cuadrilla para registrar la asistencia de todos a la vez.",
            nota="Ya puedes elegir quién; empieza a funcionar cuando se active el reconocimiento facial."),
    Permiso(REGISTRO_CON_FOTO, "📍", "Registro con ubicación y foto (excepción)",
            "Registra entrada y salida con ubicación y foto, y deja avances y pendientes. "
            "Sin este permiso se usa el registro simple."),
)

POR_CODIGO = {p.codigo: p for p in CATALOGO}


def permisos_de(empleado: dict | None) -> set[str]:
    """Códigos de permiso de un empleado (fila de `empleados`). Vacío si no tiene o no hay fila."""
    crudo = {} if empleado is None else empleado.get("permisos")   # dict o fila de pandas
    if isinstance(crudo, str):   # '{A,B}': por si algún cliente devuelve el arreglo como texto
        crudo = crudo.strip("{}").split(",")
    if not isinstance(crudo, (list, tuple, set)):   # None, o NaN cuando viene de un DataFrame
        return set()
    return {str(p).strip().strip('"') for p in crudo if str(p).strip()}


def tiene_permiso(empleado: dict | None, codigo: str) -> bool:
    return codigo in permisos_de(empleado)


# Permisos que trae cada rol al asignarlo en Jerarquía y Cuadrillas. Solo se AGREGAN, y solo en el
# momento en que la persona cambia de rol: así un permiso que se le quitó a mano no se le devuelve.
PERMISOS_POR_ROL = {
    "DIRECTOR": (REPORTE_SEMANAL, CONTROL_ASISTENCIA, RECIBIR_URGENCIAS, MI_CUADRILLA),
    "ENCARGADO": (CONTROL_ASISTENCIA, MI_CUADRILLA, FOTO_GRUPAL, ENVIAR_AVISOS),
}


def permisos_al_cambiar_de_rol(permisos: set[str], rol_anterior, rol_nuevo: str) -> set[str]:
    """Permisos después de asignar un rol: sin cambio de rol se devuelven tal cual; con cambio se
    agregan los del rol nuevo, sin quitar nada."""
    anterior = rol_anterior if isinstance(rol_anterior, str) and rol_anterior else "TRABAJADOR"
    if rol_nuevo == anterior:
        return set(permisos)
    return set(permisos) | set(PERMISOS_POR_ROL.get(rol_nuevo, ()))


def _digitos_mx(telefono) -> str:
    """Solo los dígitos; el '1' que Meta agrega a los móviles de México (521 + 10 dígitos) se quita
    para poder comparar números escritos distinto."""
    digitos = "".join(c for c in str(telefono or "") if c.isdigit())
    if digitos.startswith("521") and len(digitos) == 13:
        digitos = "52" + digitos[3:]
    return digitos


def elegir_destinatarios_urgencia(telefonos_permiso: list[str], contratista: str | None,
                                  quien_reporta: str | None) -> list[str]:
    """A quién se avisa de una urgencia: a quienes tienen el permiso, sin mandarle la alerta a quien
    la reporta. Si nadie queda, al contratista (tampoco si es quien reporta): una urgencia no se pierde."""
    reporta = _digitos_mx(quien_reporta)
    elegidos = [t for t in telefonos_permiso if _digitos_mx(t) != reporta]
    if not elegidos and contratista and _digitos_mx(contratista) != reporta:
        elegidos = [contratista]
    return elegidos


def calcular_cambios(actuales: dict[str, set[str]], deseados: dict[str, set[str]]) -> dict[str, tuple[set[str], set[str]]]:
    """Compara los permisos de hoy con los deseados, por empleado_id.
    Devuelve solo a quien cambia: {empleado_id: (agregados, quitados)}."""
    cambios = {}
    for emp_id, antes in actuales.items():
        despues = deseados.get(emp_id, antes)
        if despues != antes:
            cambios[emp_id] = (despues - antes, antes - despues)
    return cambios


# --- Lo que ve el trabajador en WhatsApp (lo comparten el bot y la vista previa del panel) ---

def texto_menu_inicio(nombre: str) -> str:
    return (f"🤖 Hola, {nombre}. Selecciona una opción enviando el *NÚMERO*:\n\n"
            f"1️⃣ 🟢 Registrar ENTRADA")


def texto_menu_en_turno(nombre: str, permisos: set[str]) -> str:
    """Menú durante la jornada: AVISO y URGENCIA solo con el permiso; la SALIDA siempre."""
    opciones = []
    if ENVIAR_AVISOS in permisos:
        opciones += ["2️⃣ 🟡 Enviar un AVISO (Reporte normal)", "3️⃣ 🔴 Reportar URGENCIA (Crítico)"]
    opciones.append("4️⃣ 🏁 Registrar SALIDA (o escribe *SALIDA*)")
    return (f"🤖 Estás en turno, {nombre}. ¿Qué deseas hacer? (Envía el *NÚMERO*):\n\n"
            + "\n".join(opciones))


def comandos_especiales(permisos: set[str]) -> list[str]:
    """Comandos que el trabajador puede escribir además del menú."""
    comandos = []
    if CONTROL_ASISTENCIA in permisos:
        comandos.append("AVISAR")
    if MI_CUADRILLA in permisos:
        comandos.append("MI CUADRILLA")
    return comandos


def que_puede_hacer(permisos: set[str], hora_corte_salida: str) -> list[str]:
    """Frases en lenguaje llano de lo que hará esta persona con el bot (para el panel)."""
    if REGISTRO_CON_FOTO in permisos:
        frases = ["Registra su entrada con ubicación y foto, y su salida con ubicación, foto, "
                  "avances y pendientes."]
    else:
        frases = ["Registra su entrada compartiendo su ubicación (sin foto). Para salir escribe SALIDA."]
    frases.append(f"Si se le olvida registrar la salida, el sistema cierra su turno solo a las {hora_corte_salida}.")
    for permiso in CATALOGO:
        if permiso.codigo != REGISTRO_CON_FOTO and permiso.codigo in permisos:
            frases.append(f"{permiso.icono} {permiso.descripcion}")
    return frases


def empleados_con_permiso(supabase, codigo: str, columnas: str = "telefono, nombre_completo") -> list[dict]:
    """Empleados ACTIVO que tienen el permiso. Si Supabase falla lanza la excepción:
    quien llama decide qué hacer (denegar, usar un respaldo, etc.)."""
    res = supabase.table("empleados").select(columnas) \
        .eq("estado", "ACTIVO").contains("permisos", [codigo]).execute()
    return res.data or []


def telefonos_con_permiso(supabase, codigo: str) -> list[str]:
    """Teléfonos (formato +52…) de los ACTIVO con el permiso, sin repetidos ni vacíos."""
    telefonos: list[str] = []
    for e in empleados_con_permiso(supabase, codigo, "telefono"):
        tel = (e.get("telefono") or "").strip()
        if tel and tel not in telefonos:
            telefonos.append(tel)
    return telefonos

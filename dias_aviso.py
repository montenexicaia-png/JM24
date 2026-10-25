"""Días de la semana en que el bot manda los recordatorios de entrada y salida.

Se guardan en `configuracion.dias_aviso` como texto "0,1,2,3,4,5" (0 = lunes … 6 = domingo, igual que
`dia_reporte_semanal`). Sin dato o ilegible se asume lunes a sábado. Solo afecta a los recordatorios:
el cierre automático de turnos corre todos los días. Neutral: no importa `main` ni `streamlit`.
"""

DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DIAS_AVISO_POR_DEFECTO = [0, 1, 2, 3, 4, 5]


def dias_de_aviso(valor) -> list[int]:
    """Lista ordenada de días (0-6) a partir de lo guardado en la base; lunes a sábado si no se entiende."""
    if isinstance(valor, str):
        partes = valor.split(",")
    elif isinstance(valor, (list, tuple)):
        partes = valor
    else:
        return list(DIAS_AVISO_POR_DEFECTO)
    dias = set()
    for parte in partes:
        try:
            dia = int(str(parte).strip())
        except ValueError:
            continue
        if 0 <= dia <= 6:
            dias.add(dia)
    return sorted(dias) or list(DIAS_AVISO_POR_DEFECTO)


def dias_a_texto(dias) -> str:
    """Formato que se guarda en la base: "0,1,2,3,4,5"."""
    return ",".join(str(d) for d in sorted(set(dias)))

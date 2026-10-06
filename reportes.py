import io
import requests
import pandas as pd
from datetime import timedelta
from fpdf import FPDF
from PIL import Image  # noqa: F401 (se usa en exportar_matriz_excel vía app.py; se deja disponible aquí también)

# ==========================================
# PLANTILLA DE PDF EJECUTIVO
# (logo, encabezado, pie de página, marca)
# ==========================================
# Movido fuera de app.py para que main.py (el bot, sin Streamlit) también
# pueda generar PDFs sin importar st.secrets/st.session_state.
class PDFCorporativo(FPDF):
    """
    PDF con look corporativo/ejecutivo: logo + nombre de empresa arriba,
    línea con el color de marca, y pie de página con fecha local,
    aviso de confidencialidad y numeración "Página X/Y".
    Pensado para documentos que se comparten por WhatsApp/correo, por eso
    cuida que el encabezado y pie no se corten y que el logo se vea nítido.
    """
    def __init__(self, titulo_documento, empresa_nombre="Centro de Mando",
                 color_marca_hex="#0E1C36", logo_url="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.titulo_documento = titulo_documento
        self.nombre_empresa = empresa_nombre
        self.color_marca_hex = color_marca_hex
        self.set_auto_page_break(auto=True, margin=25)  # deja aire para el pie de página
        self.alias_nb_pages()  # habilita {nb} = total de páginas

        # Intentamos descargar el logo una sola vez (se reutiliza en cada página)
        self.logo_bytes = None
        if logo_url:
            try:
                resp_logo = requests.get(logo_url, timeout=6)
                if resp_logo.status_code == 200 and resp_logo.content:
                    self.logo_bytes = io.BytesIO(resp_logo.content)
            except Exception:
                self.logo_bytes = None

    @staticmethod
    def texto_seguro(texto):
        return str(texto).encode('latin-1', errors='replace').decode('latin-1')

    def _rgb_marca(self):
        h = self.color_marca_hex.lstrip("#")
        try:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return (14, 28, 54)  # azul marino de respaldo

    def header(self):
        r, g, b = self._rgb_marca()

        if self.logo_bytes is not None:
            try:
                self.logo_bytes.seek(0)
                self.image(self.logo_bytes, x=10, y=8, w=20)
            except Exception:
                pass

        x_texto = 34 if self.logo_bytes is not None else 10
        self.set_xy(x_texto, 9)
        self.set_text_color(r, g, b)
        self.set_font("helvetica", "B", 14)
        self.cell(0, 7, self.texto_seguro(self.nombre_empresa), align="L", new_x="LMARGIN", new_y="NEXT")

        self.set_xy(x_texto, 16)
        self.set_text_color(90, 90, 90)
        self.set_font("helvetica", "", 10)
        self.cell(0, 6, self.texto_seguro(self.titulo_documento), align="L", new_x="LMARGIN", new_y="NEXT")

        self.set_draw_color(r, g, b)
        self.set_line_width(0.7)
        self.line(10, 27, self.w - 10, 27)

        self.set_text_color(0, 0, 0)
        self.set_y(33)

    def footer(self):
        r, g, b = self._rgb_marca()
        self.set_y(-18)
        self.set_draw_color(r, g, b)
        self.set_line_width(0.3)
        self.line(10, self.get_y(), self.w - 10, self.get_y())

        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        fecha_pie = pd.Timestamp.now(tz='America/Mexico_City').strftime('%d/%m/%Y %H:%M')
        self.cell(
            0, 5,
            self.texto_seguro(f"Generado el {fecha_pie} hrs (CDMX) | Documento confidencial de uso interno"),
            align="L"
        )
        self.set_font("helvetica", "I", 8)
        self.cell(0, 5, f"Página {self.page_no()}/{{nb}}", align="R")


def generar_matriz_semanal(fecha_ref, df_emp, df_asist):
    """
    Calcula los días de la semana, pivotea asistencias y ahora...
    ¡Calcula automáticamente si hubo horas extras superiores a 9 horas!
    """
    if df_emp.empty:
        return pd.DataFrame(), []

    lunes = fecha_ref - timedelta(days=fecha_ref.weekday())
    dias_semana = [lunes + timedelta(days=i) for i in range(6)]

    nombres_dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO"]
    df_activos = df_emp[df_emp["estado"] == "ACTIVO"].copy()

    rows = []
    for idx, emp in enumerate(df_activos.itertuples(), 1):
        rango_valor = getattr(emp, "rango", None)
        obra_valor = getattr(emp, "obra_actual", None)
        row = {
            "Num": idx,
            "NOMBRE": emp.nombre_completo,
            "PUESTO": getattr(emp, "rol", "AYUDANTE"),
            "RANGO": rango_valor if pd.notna(rango_valor) else "N/A",
            "OBRA": obra_valor if pd.notna(obra_valor) else "Sin Obra",
            "FOTO": getattr(emp, "foto_perfil_url", "")
        }

        asistencias_count = 0
        faltas_count = 0
        bandera_horas_extras = False  # NUEVO: El vigía de la semana

        for d, nombre_dia in zip(dias_semana, nombres_dias):
            if not df_asist.empty:
                # 1. Buscamos la ENTRADA
                asistio = df_asist[
                    (df_asist["empleado_id"] == emp.empleado_id) &
                    (df_asist["tipo_registro"] == "ENTRADA") &
                    (df_asist["fecha_dt"].dt.date == d)
                ]

                if not asistio.empty:
                    asistencias_count += 1

                    # --- INICIO LÓGICA DE HORAS EXTRAS Y TIEMPOS ---
                    registro_entrada = asistio.sort_values("fecha_dt").iloc[0]
                    hora_entrada = registro_entrada["fecha_dt"]
                    str_entrada = hora_entrada.strftime("%H:%M")  # Formato 09:00

                    # NUEVO: obra REAL de ese día, tomada del registro histórico (no de la obra actual del empleado)
                    obra_dia = registro_entrada.get("obra")
                    obra_dia = obra_dia if pd.notna(obra_dia) else "Sin Obra"

                    fecha_siguiente = d + timedelta(days=1)
                    posibles_salidas = df_asist[
                        (df_asist["empleado_id"] == emp.empleado_id) &
                        (df_asist["tipo_registro"] == "SALIDA") &
                        (df_asist["fecha_dt"] > hora_entrada) &
                        (df_asist["fecha_dt"].dt.date <= fecha_siguiente)
                    ]

                    if not posibles_salidas.empty:
                        hora_salida = posibles_salidas.sort_values("fecha_dt").iloc[0]["fecha_dt"]
                        str_salida = hora_salida.strftime("%H:%M")  # Formato 18:00
                        tiempo_trabajado = hora_salida - hora_entrada

                        if tiempo_trabajado > timedelta(hours=9):
                            bandera_horas_extras = True

                        # Si tiene entrada y salida, ponemos ambas horas + la obra real de ese día
                        row[nombre_dia] = f"{str_entrada} - {str_salida} · {obra_dia}"
                    else:
                        # Si tiene entrada pero NO tiene salida, ponemos NULL + la obra real de ese día
                        row[nombre_dia] = f"{str_entrada} - NULL · {obra_dia}"
                    # --- FIN LÓGICA HORAS EXTRAS Y TIEMPOS ---

                else:
                    row[nombre_dia] = "NO"
                    faltas_count += 1

        row["HR EXTRAS"] = "SI" if bandera_horas_extras else "NO"
        row["ASISTENCIA"] = asistencias_count
        row["FALTAS"] = faltas_count
        rows.append(row)

    df_matriz = pd.DataFrame(rows)

    # NUEVO: Ordenamos las columnas estrictamente para que no choquen con el Excel
    columnas_ordenadas = ["Num", "NOMBRE", "PUESTO", "RANGO", "OBRA", "FOTO", "LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "HR EXTRAS", "ASISTENCIA", "FALTAS"]
    df_matriz = df_matriz[columnas_ordenadas]

    meses_es = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    fechas_cabecera = [f"{d.day:02d}-{meses_es[d.month-1]}" for d in dias_semana]

    return df_matriz, fechas_cabecera


def generar_pdf_matriz_semanal(df_matriz, fechas_cabecera, empresa_nombre="Centro de Mando",
                                color_marca_hex="#0E1C36", logo_url=""):
    """
    Renderiza la matriz semanal (sin fotos) como UN SOLO PDF horizontal,
    pensado para mandarse como documento adjunto al Director por WhatsApp.
    """
    dias_cortos = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB"]
    etiquetas_dias = [f"{dia} {fecha}" for dia, fecha in zip(dias_cortos, fechas_cabecera)]

    titulo = f"Reporte Semanal de Asistencia · {fechas_cabecera[0]} al {fechas_cabecera[-1]}"
    pdf = PDFCorporativo(
        titulo_documento=titulo,
        empresa_nombre=empresa_nombre,
        color_marca_hex=color_marca_hex,
        logo_url=logo_url,
        orientation="L",
        format="A4",
    )
    pdf.add_page()
    pdf.set_font("helvetica", size=7)

    columnas_pdf = ["NOMBRE", "PUESTO", "OBRA"] + ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO"] + ["HR EXTRAS", "ASISTENCIA", "FALTAS"]
    encabezados_pdf = ["Nombre", "Puesto", "Obra"] + etiquetas_dias + ["Hr Extras", "Asist.", "Faltas"]
    anchos_pdf = (38, 22, 26, 20, 20, 20, 20, 20, 20, 15, 13, 13)

    with pdf.table(col_widths=anchos_pdf, text_align="CENTER", line_height=4.2) as tabla:
        fila = tabla.row()
        for encabezado in encabezados_pdf:
            fila.cell(PDFCorporativo.texto_seguro(encabezado))

        for _, datos in df_matriz.iterrows():
            fila = tabla.row()
            for col in columnas_pdf:
                fila.cell(PDFCorporativo.texto_seguro(datos[col]))

    return bytes(pdf.output())

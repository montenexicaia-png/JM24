import streamlit as st
import pandas as pd
import google.generativeai as genai
from supabase import create_client, Client
import datetime
from fpdf import FPDF
import io
import plotly.express as px
import requests
from PIL import Image

# ==========================================
# 1. CONFIGURACIÓN DE LA PÁGINA Y ESTILOS
# ==========================================
st.set_page_config(
    page_title="Centro de Mando | Obras",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Inyección de CSS para un look futurista/oscuro empresarial
st.markdown("""
    <style>
    /* Estilos para las tarjetas de métricas */
    div[data-testid="metric-container"] {
        background-color: #1E1E2E;
        border: 1px solid #3A3A5A;
        padding: 5% 5% 5% 10%;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        transition: transform 0.2s ease-in-out;
    }
    div[data-testid="metric-container"]:hover {
        transform: scale(1.02);
        border-color: #00FFCC; /* Toque neón futurista */
    }
    /* Títulos principales */
    .big-title {
        font-family: 'Courier New', Courier, monospace;
        color: #00FFCC;
        text-transform: uppercase;
        letter-spacing: 2px;
    }
    </style>
""", unsafe_allow_html=True)

def obtener_estado_registro():
    """Lee si el registro por WhatsApp está abierto (True) o cerrado (False)"""
    try:
        # Apuntamos a la única fila con id=1 que creamos en Supabase
        respuesta = supabase.table("configuracion").select("registro_abierto").eq("id", 1).execute()
        if respuesta.data:
            return respuesta.data[0]["registro_abierto"]
        return False
    except Exception as e:
        st.error(f"Error al obtener configuración: {e}")
        return False

def actualizar_estado_registro(nuevo_estado: bool):
    """Modifica el estado del interruptor maestro en la base de datos"""
    try:
        supabase.table("configuracion").update({"registro_abierto": nuevo_estado}).eq("id", 1).execute()
    except Exception as e:
        st.error(f"Error al actualizar configuración: {e}")

def generar_matriz_semanal(fecha_ref, df_emp, df_asist):
    """
    Calcula los días de la semana, pivotea asistencias y ahora...
    ¡Calcula automáticamente si hubo horas extras superiores a 9 horas!
    """
    if df_emp.empty:
        return pd.DataFrame(), []
        
    lunes = fecha_ref - datetime.timedelta(days=fecha_ref.weekday())
    dias_semana = [lunes + datetime.timedelta(days=i) for i in range(6)]
    
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
        bandera_horas_extras = False # NUEVO: El vigía de la semana
        
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
                    hora_entrada = asistio.sort_values("fecha_dt").iloc[0]["fecha_dt"]
                    str_entrada = hora_entrada.strftime("%H:%M") # Formato 09:00
                    
                    fecha_siguiente = d + datetime.timedelta(days=1)
                    posibles_salidas = df_asist[
                        (df_asist["empleado_id"] == emp.empleado_id) &
                        (df_asist["tipo_registro"] == "SALIDA") &
                        (df_asist["fecha_dt"] > hora_entrada) &
                        (df_asist["fecha_dt"].dt.date <= fecha_siguiente)
                    ]
                    
                    if not posibles_salidas.empty:
                        hora_salida = posibles_salidas.sort_values("fecha_dt").iloc[0]["fecha_dt"]
                        str_salida = hora_salida.strftime("%H:%M") # Formato 18:00
                        tiempo_trabajado = hora_salida - hora_entrada
                        
                        if tiempo_trabajado > datetime.timedelta(hours=9):
                            bandera_horas_extras = True
                            
                        # Si tiene entrada y salida, ponemos ambas horas
                        row[nombre_dia] = f"{str_entrada} - {str_salida}"
                    else:
                        # Si tiene entrada pero NO tiene salida, ponemos NULL
                        row[nombre_dia] = f"{str_entrada} - NULL"
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


def exportar_matriz_excel(df_matriz, fechas_cabecera):
    """
    Genera el binario de Excel usando XlsxWriter.
    Descarga, recorta y uniformiza las fotos de perfil directamente en las celdas.
    """
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    
    df_matriz.to_excel(writer, sheet_name='Control_Asistencia', startrow=2, index=False, header=False)
    
    workbook = writer.book
    worksheet = writer.sheets['Control_Asistencia']
    
    # --- Estilos de Celda ---
    formato_cabecera_top = workbook.add_format({
        'bold': True, 'font_color': 'white', 'bg_color': '#1F4E78', 
        'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_name': 'Arial', 'font_size': 11
    })
    formato_subcabecera = workbook.add_format({
        'bold': True, 'bg_color': '#D9E1F2', 
        'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_name': 'Arial', 'font_size': 10
    })
    formato_celda_general = workbook.add_format({
        'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_name': 'Arial', 'font_size': 10
    })
    formato_si = workbook.add_format({
        'bg_color': '#E2EFDA', 'font_color': '#375623', 
        'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_name': 'Arial', 'font_size': 10
    })
    formato_no = workbook.add_format({
        'bg_color': '#FCE4D6', 'font_color': '#C65911', 
        'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_name': 'Arial', 'font_size': 10
    })
    formato_alerta = workbook.add_format({
        'bg_color': '#FFF2CC', 'font_color': '#B58900', # Amarillo preventivo
        'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_name': 'Arial', 'font_size': 9
    })
    formato_asistencia_hora = workbook.add_format({
        'bg_color': '#E2EFDA', 'font_color': '#375623', # Verde asistencia
        'align': 'center', 'valign': 'vcenter', 'border': 1, 'font_name': 'Arial', 'font_size': 9
    })
    
    # --- Fila 0: Cabeceras Combinadas Superiores ---
    worksheet.merge_range(0, 0, 0, 5, "PERSONAL", formato_cabecera_top) 
    for i, fecha_str in enumerate(fechas_cabecera):
        worksheet.write(0, 6 + i, fecha_str, formato_cabecera_top)
    worksheet.merge_range(0, 12, 0, 14, "ASISTENCIA", formato_cabecera_top)
    
    # --- Fila 1: Subcabeceras de Columnas ---
    columnas_layout = ["Num", "NOMBRE", "PUESTO", "RANGO", "OBRA", "FOTO", "LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "HR EXTRAS", "ASISTENCIA", "FALTAS"]
    worksheet.set_row(0, 24)
    worksheet.set_row(1, 20)
    
    for col_idx, texto in enumerate(columnas_layout):
        worksheet.write(1, col_idx, texto, formato_subcabecera)
        
    # Dimensionamiento estético de las columnas
    worksheet.set_column(0, 0, 6)   # Num
    worksheet.set_column(1, 1, 35)  # NOMBRE
    worksheet.set_column(2, 2, 18)  # 
    worksheet.set_column(3, 3, 14)  # RANGO
    worksheet.set_column(4, 4, 20)  # OBRA (un poco más ancha, los nombres de obra suelen ser largos)
    worksheet.set_column(5, 5, 14)  # FOTO (Ancho ideal)
    worksheet.set_column(6, 11, 16)  # Días de la semana
    worksheet.set_column(12, 14, 14) # Columnas de totales
    
    # --- Inyección de datos e Imágenes Uniformes ---
    for row_idx in range(len(df_matriz)):
        excel_row = row_idx + 2
        worksheet.set_row(excel_row, 60) # Altura fija para que el cuadrado 70x70 entre perfecto
        
        for col_idx, col_name in enumerate(columnas_layout):
            valor = df_matriz.iloc[row_idx, col_idx]
            
            # MAGIA 1: Procesamiento unificado de fotos
            if col_name == "FOTO":
                url_foto = valor
                worksheet.write(excel_row, col_idx, "", formato_celda_general) 
                
                if pd.notna(url_foto) and str(url_foto).startswith("http"):
                    try:
                        respuesta = requests.get(url_foto, timeout=5)
                        img = Image.open(io.BytesIO(respuesta.content))
                        
                        # 1. Convertir a RGB (previene errores con PNGs transparentes)
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")
                            
                        # 2. Recortar al centro para hacer un cuadrado perfecto
                        width, height = img.size
                        min_dim = min(width, height)
                        left = (width - min_dim) / 2
                        top = (height - min_dim) / 2
                        right = (width + min_dim) / 2
                        bottom = (height + min_dim) / 2
                        img_cuadrada = img.crop((left, top, right, bottom))
                        
                        # 3. Redimensionar exactamente a 70x70 píxeles
                        img_final = img_cuadrada.resize((70, 70))
                        
                        # 4. Guardar en la memoria para Excel
                        output_img = io.BytesIO()
                        img_final.save(output_img, format='PNG')
                        output_img.seek(0)
                        
                        # Insertar la foto a escala 1:1, porque ya viene a la medida perfecta
                        worksheet.insert_image(excel_row, col_idx, 'foto.png', {
                            'image_data': output_img,
                            'x_scale': 1, 
                            'y_scale': 1,
                            'x_offset': 15, # Ajuste fino horizontal (lo empuja al centro de la celda)
                            'y_offset': 5,  # Ajuste fino vertical
                            'object_position': 1
                        })
                    except:
                        pass # Si una foto falla, dejamos la celda limpia
                        
            # MAGIA 2: Aplicamos colores a los días (con Horas y NULL)
            elif col_name in ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO"]:
                valor_str = str(valor)
                if "NULL" in valor_str:
                    worksheet.write(excel_row, col_idx, valor, formato_alerta)
                elif "-" in valor_str:
                    # Si tiene un guion pero no dice NULL, es porque están ambas horas completas
                    worksheet.write(excel_row, col_idx, valor, formato_asistencia_hora)
                elif valor_str == "NO":
                    worksheet.write(excel_row, col_idx, valor, formato_no)
                else:
                    worksheet.write(excel_row, col_idx, valor, formato_celda_general)
                    
            # MAGIA 3: Color verde para las Horas Extras
            elif col_name == "HR EXTRAS":
                if valor == "SI":
                    worksheet.write(excel_row, col_idx, valor, formato_si)
                else:
                    worksheet.write(excel_row, col_idx, valor, formato_celda_general)
            
            # Para las demás celdas normales
            else:
                worksheet.write(excel_row, col_idx, valor, formato_celda_general)
                
    writer.close()
    return output.getvalue()

# ==========================================
# 1.5 SISTEMA DE LOGIN (Guardia de Seguridad)
# ==========================================
def check_password():
    """Devuelve True si el usuario ingresó la contraseña correcta."""
    def password_entered():
        """Verifica la contraseña ingresada."""
        if st.session_state["password"] == st.secrets["PASSWORD_ACCESO"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Borramos la contraseña de la memoria por seguridad
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # Primera vez que entra: mostramos el cuadro de texto
        st.markdown("<h3 style='text-align: center;'>🔒 Acceso Restringido</h3>", unsafe_allow_html=True)
        st.text_input("Ingresa la contraseña maestra para continuar:", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # Contraseña incorrecta: mostramos cuadro + error
        st.markdown("<h3 style='text-align: center;'>🔒 Acceso Restringido</h3>", unsafe_allow_html=True)
        st.text_input("Ingresa la contraseña maestra para continuar:", type="password", on_change=password_entered, key="password")
        st.error("❌ Contraseña incorrecta. Intento bloqueado.")
        return False
    else:
        # Contraseña correcta: lo dejamos pasar
        return True

# Si el usuario NO tiene la contraseña, detenemos TODA la página aquí mismo.
if not check_password():
    st.stop() 

# ==========================================
# 2. CONEXIÓN (Usando secretos)
# ==========================================
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
    
    # Gemini (lo usaremos más adelante para la auditoría)
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    st.sidebar.success("✅ Conectado a la Base de Datos")
except Exception as e:
    st.sidebar.error("⚠️ Error de conexión: Verifica tu archivo secrets.toml")
    st.stop() # Detiene la ejecución si no hay conexión

# ==========================================
# 3. EXTRACCIÓN DE DATOS REALES (¡100% CONECTADO!)
# ==========================================
# 1. Traemos a TODOS los empleados
respuesta_todos = supabase.table("empleados").select("*").execute()
df_empleados = pd.DataFrame(respuesta_todos.data)

# 2. Filtrar Activos (para la matemática)
if not df_empleados.empty:
    total_activos = len(df_empleados[df_empleados["estado"] == "ACTIVO"])
else:
    total_activos = 0

# 3. Traemos las Asistencias e Incidentes
respuesta_asistencias = supabase.table("registros_asistencia").select("*").order("fecha_hora", desc=True).execute()
df_asistencias = pd.DataFrame(respuesta_asistencias.data)

respuesta_incidentes = supabase.table("reportes_incidentes").select("*").order("fecha_hora", desc=True).execute()
df_incidentes = pd.DataFrame(respuesta_incidentes.data)

# --- CABECERA Y CALENDARIO (Debe ir antes de filtrar) ---
col_titulo, col_calendario = st.columns([7, 3])

with col_titulo:
    st.markdown('<h1 class="big-title">⚡ Sistema de Mando y Control de Obra</h1>', unsafe_allow_html=True)
    st.write("Panel de control en tiempo real y auditoría inteligente.")

with col_calendario:
    # AQUÍ NACE LA VARIABLE ANTES DE LAS MATEMÁTICAS
    fecha_seleccionada = st.date_input("📆 Fecha del Día Operativo", datetime.date.today())

st.divider()

# --- MOTOR DE FILTRADO: DÍA OPERATIVO Y TURNO NOCTURNO ---
kpi_entradas = 0
kpi_salidas = 0
kpi_urgentes = 0

# Convertimos las columnas y las ajustamos automáticamente al huso horario de México
if not df_asistencias.empty:
    df_asistencias["fecha_dt"] = pd.to_datetime(df_asistencias["fecha_hora"])
    try:
        # Si la base de datos ya viene con zona horaria, la convertimos a la local
        df_asistencias["fecha_dt"] = df_asistencias["fecha_dt"].dt.tz_convert('America/Mexico_City')
    except TypeError:
        # Si viene "neutra", la declaramos como UTC y luego la transformamos a México
        df_asistencias["fecha_dt"] = df_asistencias["fecha_dt"].dt.localize('UTC').dt.tz_convert('America/Mexico_City')

if not df_incidentes.empty:
    df_incidentes["fecha_dt"] = pd.to_datetime(df_incidentes["fecha_hora"])
    try:
        df_incidentes["fecha_dt"] = df_incidentes["fecha_dt"].dt.tz_convert('America/Mexico_City')
    except TypeError:
        df_incidentes["fecha_dt"] = df_incidentes["fecha_dt"].dt.localize('UTC').dt.tz_convert('America/Mexico_City')

# --- A PARTIR DE AQUÍ CONTINÚA TU LÓGICA DE FILTRADO IGUAL ---
# 1. ENTRADAS: Estrictas del día seleccionado
if not df_asistencias.empty:
    df_entradas_hoy = df_asistencias[
        (df_asistencias["tipo_registro"] == "ENTRADA") & 
        (df_asistencias["fecha_dt"].dt.date == fecha_seleccionada)
    ]
    kpi_entradas = len(df_entradas_hoy)
    
    # 2. SALIDAS INTELIGENTES (Turno Nocturno): 
    # Para cada empleado que entró en la fecha seleccionada, buscamos su salida posterior
    # permitiendo que ocurra hoy mismo o durante la madrugada del día siguiente (+1 día)
    salidas_operativas = []
    fecha_siguiente = fecha_seleccionada + datetime.timedelta(days=1)
    
    for _, entrada in df_entradas_hoy.iterrows():
        emp_id = entrada["empleado_id"]
        t_entrada = entrada["fecha_dt"]
        
        posibles_salidas = df_asistencias[
            (df_asistencias["tipo_registro"] == "SALIDA") &
            (df_asistencias["empleado_id"] == emp_id) &
            (df_asistencias["fecha_dt"] > t_entrada) &
            (df_asistencias["fecha_dt"].dt.date <= fecha_siguiente)
        ]
        if not posibles_salidas.empty:
            # Tomamos la salida más cercana cronológicamente a su entrada
            salida_correcta = posibles_salidas.sort_values("fecha_dt").iloc[0]
            salidas_operativas.append(salida_correcta)
            
    df_salidas_hoy = pd.DataFrame(salidas_operativas) if salidas_operativas else pd.DataFrame(columns=df_asistencias.columns)
    kpi_salidas = len(df_salidas_hoy)
    
    # Unificamos las asistencias del día operativo para los gráficos y tablas
    df_asistencias_hoy = pd.concat([df_entradas_hoy, df_salidas_hoy]).sort_values("fecha_hora", ascending=False)
else:
    df_asistencias_hoy = pd.DataFrame()

# 3. INCIDENTES: Vinculados al día de corte
if not df_incidentes.empty:
    df_incidentes_hoy = df_incidentes[df_incidentes["fecha_dt"].dt.date == fecha_seleccionada]
    kpi_urgentes = len(df_incidentes_hoy[df_incidentes_hoy["estado"] == "URGENTE"])
else:
    df_incidentes_hoy = pd.DataFrame()

# Cálculo de ausentes del día operativo
faltantes = total_activos - kpi_entradas

# ==========================================
# 4. INTERFAZ DE USUARIO (Layout)
# ==========================================

# --- BLOQUE 1: EL PULSO DE LA OBRA ---
st.subheader("📊 El Pulso de la Obra")
col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label="🟢 Entradas Hoy", value=kpi_entradas, delta=f"Faltan {faltantes} por llegar", delta_color="off")
with col2:
    st.metric(label="🔴 Salidas Completadas", value=kpi_salidas, delta="Jornadas terminadas", delta_color="off")
with col3:
    st.metric(label="⚠️ Incidentes URGENTES", value=kpi_urgentes, delta="Requiere atención", delta_color="inverse")

st.divider()

# --- GRÁFICOS VISUALES (Debajo de las tarjetas del Bloque 1) ---
st.markdown("<br>", unsafe_allow_html=True) # Un pequeño salto de línea para respirar
col_graf1, col_graf2 = st.columns(2)

with col_graf1:
    st.markdown("##### 👷 Distribución de Personal")
    if not df_empleados.empty:
        # Filtramos solo a los activos para la gráfica
        activos = df_empleados[df_empleados["estado"] == "ACTIVO"]
        if not activos.empty:
            # Gráfica de Anillo (Donut) con Plotly
            fig_roles = px.pie(
                activos, 
                names="rol", 
                hole=0.4,
                color_discrete_sequence=px.colors.sequential.Teal
            )
            # Hacemos el fondo transparente para que combine con tu modo oscuro
            fig_roles.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig_roles, use_container_width=True)
        else:
            st.info("No hay personal activo para graficar.")
    else:
        st.info("No hay datos en el directorio.")

with col_graf2:
    st.markdown("##### ⏱️ Flujo de Asistencias Hoy")
    if not df_asistencias_hoy.empty:
        # Contamos cuántas entradas y salidas hay
        conteo = df_asistencias_hoy["tipo_registro"].value_counts().reset_index()
        conteo.columns = ["Tipo", "Cantidad"]
        
        # Gráfica de Barras con colores de alerta
        fig_asistencias = px.bar(
            conteo, 
            x="Tipo", 
            y="Cantidad", 
            text="Cantidad",
            color="Tipo", 
            color_discrete_map={"ENTRADA": "#00FFCC", "SALIDA": "#FF4B4B"} # Verde Neón y Rojo
        )
        fig_asistencias.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", showlegend=False, margin=dict(t=0, b=0, l=0, r=0))
        st.plotly_chart(fig_asistencias, use_container_width=True)
    else:
        st.info("Aún no hay registros de asistencia para graficar.")

# --- BLOQUE 2: AUDITORÍA DE IA ---
st.subheader("🧠 Auditoría de IA (Gemini)")
st.caption("Analiza los registros del día y genera un resumen ejecutivo automático.")

# 1. El botón de ejecución
if st.button("Ejecutar Auditoría de Obra 🚀", type="primary"):
    with st.spinner("Gemini está analizando los registros y reportes de incidentes..."):
        try:
            texto_asistencias = df_asistencias_hoy[["empleado_id", "tipo_registro", "fecha_hora", "avances", "pendientes"]].to_string() if not df_asistencias_hoy.empty else f"Sin registros de asistencia para el día {fecha_seleccionada.strftime('%d/%m/%Y')}."
            texto_incidentes = df_incidentes_hoy[["empleado_id", "descripcion", "estado", "fecha_hora"]].to_string() if not df_incidentes_hoy.empty else f"Sin incidentes reportados para el día {fecha_seleccionada.strftime('%d/%m/%Y')}."

            prompt_auditoria = f"""
            Actúa como un Auditor de Obra Profesional y Supervisor de Proyectos.
            A continuación te proporciono los datos crudos extraídos de la base de datos sobre la jornada de hoy en la obra:

            --- REGISTROS DE ASISTENCIA Y AVANCES ---
            {texto_asistencias}

            --- REPORTES E INCIDENTES ---
            {texto_incidentes}

            Por favor, genera un "Resumen Ejecutivo de Obra" estructurado, analítico y fácil de leer. 
            Tu respuesta debe estar formateada en Markdown y contener obligatoriamente estas secciones:
            1. **Estado General:** Un breve resumen de cómo se desarrolló la jornada.
            2. **Avances Destacados:** Qué tareas específicas se lograron hoy según los reportes de salida.
            3. **Pendientes Críticos:** Qué tareas quedaron en cola para mañana.
            4. **Alertas y Seguridad:** Si hay incidentes marcados como AVISO o URGENTE, resáltalos inmediatamente indicando el ID del empleado. Si no hay incidentes, menciona explícitamente que la jornada transcurrió sin eventualidades de riesgo.
            
            Mantén un tono empresarial, objetivo y directo. No inventes datos que no estén en las tablas.
            """

            modelo_disponible = None
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    modelo_disponible = m.name
                    break
            
            if modelo_disponible:
                model = genai.GenerativeModel(modelo_disponible)
                respuesta = model.generate_content(prompt_auditoria)
                
                # Agregamos una firma profesional al documento
                reporte_final = f"{respuesta.text}\n\n---\n*Reporte generado automáticamente por el motor de IA de NeuroMont.*"
                
                # 2. GUARDAMOS EL REPORTE EN MEMORIA (Para verlo en pantalla)
                st.session_state['reporte_guardado'] = respuesta.text
                
                # --- NUEVO: CREACIÓN DEL PDF EN MEMORIA ---
                def generar_pdf(texto):
                    pdf = FPDF()
                    pdf.add_page()
                    
                    # Título del documento
                    pdf.set_font("helvetica", "B", 16)
                    pdf.cell(0, 10, "Resumen Ejecutivo de Obra - Auditoria IA", align="C", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("helvetica", "I", 10)
                    fecha_impresion = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    pdf.cell(0, 10, f"Generado por NeuroMont | Fecha: {fecha_impresion}", align="C", new_x="LMARGIN", new_y="NEXT")
                    pdf.ln(5)
                    
                    # Limpiamos asteriscos de Markdown para el PDF
                    texto_limpio = texto.replace("**", "").replace("*", "-")
                    
                    # Cuerpo del texto
                    pdf.set_font("helvetica", size=12)
                    pdf.multi_cell(0, 8, txt=texto_limpio)
                    
                    return bytes(pdf.output())

                # Generamos los bytes del archivo y el nombre dinámico
                st.session_state['pdf_bytes'] = generar_pdf(respuesta.text)
                
                # Timestamp para el nombre del archivo (Ej: Reporte_2026-06-21_14-30.pdf)
                marca_tiempo = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
                st.session_state['pdf_nombre'] = f"Reporte_Obra_{marca_tiempo}.pdf"
                
                st.success(f"✅ Auditoría completada con éxito. (Cerebro: {modelo_disponible})")

            else:
                st.error("❌ Tu API Key no tiene modelos habilitados para generar texto.")

        except Exception as e:
            st.error(f"❌ Error al conectar con el cerebro de IA: {str(e)}")

# 3. MOSTRAR REPORTE EN PANTALLA Y BOTÓN DE DESCARGA PDF
if 'reporte_guardado' in st.session_state and 'pdf_bytes' in st.session_state:
    st.markdown(st.session_state['reporte_guardado'])
    st.divider()
    
    # Botón nativo para descargar el PDF
    st.download_button(
        label="📑 Descargar Reporte en PDF",
        data=st.session_state['pdf_bytes'],
        file_name=st.session_state['pdf_nombre'],
        mime="application/pdf",
        type="primary",
        help="Descarga la auditoría en un formato profesional listo para compartir."
    )

# --- BLOQUE 3: EVIDENCIA Y EXPORTACIÓN ---
st.subheader("📁 Evidencia y Registros")

# Creamos el espacio para los dos bloques de botones (col_exp1 tendrá las descargas de Excel)
col_exp1, col_exp2 = st.columns([2, 8])

with col_exp1:
    # =========================================================================
    # 1. TU FUNCIONALIDAD ORIGINAL: RESPALDO DE TABLAS CRUDAS (openpyxl)
    # =========================================================================
    # Creamos un archivo Excel virtual en la memoria
    buffer = io.BytesIO()
    
    # Guardamos las tablas en diferentes pestañas del mismo Excel
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        datos_escritos = False # Bandera de seguridad
        
        if not df_asistencias_hoy.empty:
            # Eliminamos la columna matemática 'fecha_dt'
            df_excel_asist = df_asistencias_hoy.drop(columns=['fecha_dt'], errors='ignore')
            df_excel_asist.to_excel(writer, sheet_name='Asistencias', index=False)
            datos_escritos = True
            
        if not df_incidentes_hoy.empty:
            # Eliminamos la columna matemática de incidentes
            df_excel_inc = df_incidentes_hoy.drop(columns=['fecha_dt'], errors='ignore')
            df_excel_inc.to_excel(writer, sheet_name='Incidentes', index=False)
            datos_escritos = True
            
        if not df_empleados.empty:
            df_empleados.to_excel(writer, sheet_name='Directorio', index=False)
            datos_escritos = True
            
        # Si el día está completamente muerto y no se escribió nada, creamos una hoja de aviso
        if not datos_escritos:
            df_vacio = pd.DataFrame({"Aviso": [f"No hay registros en la base de datos para el día {fecha_seleccionada.strftime('%d/%m/%Y')}"]})
            df_vacio.to_excel(writer, sheet_name='Sin Datos', index=False)
            
    # Tu botón nativo de descarga original
    st.download_button(
        label="📄 Exportar Tablas Crudas",
        data=buffer.getvalue(),
        file_name=f"Base_Datos_Obra_{fecha_seleccionada.strftime('%Y-%m-%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Descargar registros completos de la base de datos en formato bruto .xlsx",
        key="btn_exportar_tablas_crudas"
    )

    # Separador visual sutil entre botones para que la interfaz se vea ordenada
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # 2. NUEVA FUNCIONALIDAD: REPORTE MATRICIAL SOLICITADO POR EL CLIENTE (xlsxwriter)
    # =========================================================================
    # Procesamos los límites y la disposición de la matriz semanal de asistencia
    df_matriz_semanal, fechas_cabecera = generar_matriz_semanal(fecha_seleccionada, df_empleados, df_asistencias)
    
    if not df_matriz_semanal.empty:
        # Generamos el binario con el estilo visual idéntico a la plantilla (Bordes, Azul, Verdes y Naranjas)
        excel_matriz_bytes = exportar_matriz_excel(df_matriz_semanal, fechas_cabecera)
        
        # Botón para descargar el reporte estilizado de cara al cliente
        st.download_button(
            label="📊 Descargar Matriz Semanal",
            data=excel_matriz_bytes,
            file_name=f"Matriz_Asistencia_Semana_{fecha_seleccionada.strftime('%Y-%m-%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Descargar el reporte matricial diseñado con formato condicional (SI/NO).",
            key="btn_descargar_matriz_semanal"
        )
    else:
        # Evitamos errores en la app mostrando un botón deshabilitado si no hay estructura
        st.button(
            label="📊 Matriz Semanal No Disponible", 
            disabled=True, 
            help="No hay suficiente personal activo para estructurar la matriz semanal."
        )

with col_exp2:
    if not df_asistencias.empty:
        def generar_pdf_asistencias(df):
            pdf = FPDF()
            pdf.add_page()
            
            # Título del Reporte
            pdf.set_font("helvetica", "B", 16)
            pdf.cell(0, 10, "Reporte Formal de Asistencias y Turnos", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "I", 10)
            fecha_actual = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')
            pdf.cell(0, 10, f"Generado por NeuroMont | Fecha de corte: {fecha_actual}", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)
            
            # Encabezados de la tabla (Ancho total A4: 190mm)
            pdf.set_font("helvetica", "B", 10)
            pdf.cell(35, 10, "Empleado ID", border=1, align="C")
            pdf.cell(25, 10, "Tipo", border=1, align="C")
            pdf.cell(45, 10, "Fecha y Hora", border=1, align="C")
            pdf.cell(85, 10, "Notas / Avance", border=1, align="C", new_x="LMARGIN", new_y="NEXT")
            
            # Filas de datos
            pdf.set_font("helvetica", "", 9)
            for _, row in df.iterrows():
                emp_id = str(row.get('empleado_id', ''))
                tipo = str(row.get('tipo_registro', ''))
                
                # Limpiar la fecha para quitar milisegundos
                fecha_raw = str(row.get('fecha_hora', ''))
                fecha_limpia = fecha_raw[:16].replace('T', ' ') if fecha_raw else ''
                
                # Ajustar las notas si no hay avances (ej. en una Entrada)
                avance = str(row.get('avances', ''))
                if avance == "None" or not avance:
                    avance = "Inicio de turno" if tipo == "ENTRADA" else "Sin comentarios"
                    
                # Truncar textos muy largos para que no rompan la estructura de la celda
                avance = avance[:50] + "..." if len(avance) > 50 else avance
                
                pdf.cell(35, 10, emp_id, border=1, align="C")
                pdf.cell(25, 10, tipo, border=1, align="C")
                pdf.cell(45, 10, fecha_limpia, border=1, align="C")
                pdf.cell(85, 10, f" {avance}", border=1, align="L", new_x="LMARGIN", new_y="NEXT")
                
            return bytes(pdf.output())

        # Generamos el PDF virtual
        pdf_asistencias_bytes = generar_pdf_asistencias(df_asistencias)
        
        # Reemplazamos el botón falso por el botón nativo de descarga
        st.download_button(
            label="📑 Generar PDF",
            data=pdf_asistencias_bytes,
            file_name=f"Reporte_Asistencias_{datetime.datetime.now().strftime('%Y-%m-%d')}.pdf",
            mime="application/pdf",
            help="Descargar reporte tabular de las asistencias del día."
        )
    else:
        # Si la base de datos está vacía hoy, mostramos el botón deshabilitado
        st.button("📑 Generar PDF", disabled=True, help="Aún no hay registros de asistencia para exportar.")

tab_tabla, tab_galeria, tab_directorio, tab_rh, tab_obras = st.tabs(["📋 Tabla de Asistencias", "📸 Galería de Campo", "👥 Directorio de Personal", "⚙️ Gestión RH", "🏗️ Gestión de Obras"])

with tab_tabla:
    if not df_asistencias_hoy.empty:
        df_mostrar = df_asistencias_hoy.copy()

        df_mostrar["Hora Registro"] = df_mostrar["fecha_dt"].dt.strftime("%d/%m/%Y %H:%M")
        
        # Marcamos visualmente si la fecha real del mensaje es del día siguiente (+1) en la madrugada
        df_mostrar["Ecosistema Turno"] = df_mostrar.apply(
            lambda r: "🌙 Turno Nocturno" if r["fecha_dt"].date() > fecha_seleccionada else "☀️ Turno Ordinario", 
            axis=1
        )
        
        # Validamos si la columna 'ubicacion' existe en la base de datos para evitar errores
        columnas_a_mostrar = ["empleado_id", "tipo_registro", "fecha_hora", "Ecosistema Turno"]
        if "ubicacion" in df_mostrar.columns:
            columnas_a_mostrar.append("ubicacion")
        columnas_a_mostrar.extend(["avances", "pendientes"])
        
        st.dataframe(df_mostrar[columnas_a_mostrar], use_container_width=True)
    else:
        st.info(f"Aún no hay registros de asistencia para el día operativo {fecha_seleccionada.strftime('%d/%m/%Y')}.")

with tab_galeria:
    # Usamos df_asistencias_hoy en lugar del general
    if not df_asistencias_hoy.empty and "foto_url" in df_asistencias_hoy.columns and not df_empleados.empty:
        
        # Preparamos las columnas a cruzar (añadimos ubicacion si existe)
        cols_asistencia = ["empleado_id", "fecha_dt", "tipo_registro", "foto_url"]
        if "ubicacion" in df_asistencias_hoy.columns:
            cols_asistencia.append("ubicacion")
            
        # 1. Cruzamos la tabla de asistencias DEL DÍA con el directorio para obtener los nombres
        df_fotos_con_nombre = pd.merge(
            df_asistencias_hoy[cols_asistencia],
            df_empleados[["empleado_id", "nombre_completo"]],
            on="empleado_id",
            how="inner"
        ).dropna(subset=["foto_url"]) # Solo eliminamos si no hay foto
        
        # Filtramos solo los enlaces de internet válidos para la foto
        df_fotos_con_nombre = df_fotos_con_nombre[df_fotos_con_nombre["foto_url"].str.startswith("http")]
        
        if not df_fotos_con_nombre.empty:
            cols_fotos = st.columns(4)
            for i, row in df_fotos_con_nombre.reset_index().iterrows():
                # Formateo de datos
                fecha_limpia = row['fecha_dt'].strftime("%d/%m/%Y %H:%M")
                tipo = row['tipo_registro']
                url_real = row['foto_url']
                nombre_corto = " ".join(row['nombre_completo'].split()[:2])
                
                # Extraemos la ubicación si existe
                url_mapa = row.get('ubicacion', '')
                
                # Pie de foto principal
                pie_foto = f"👤 {nombre_corto}\n📋 {tipo}\n⏰ {fecha_limpia}"
                
                with cols_fotos[i % 4]:
                    try:
                        st.image(url_real, caption=pie_foto, use_container_width=True)
                        
                        # UX: Si hay un enlace de Google Maps válido, dibujamos un botón limpio
                        if pd.notna(url_mapa) and str(url_mapa).startswith("http"):
                            st.markdown(f"📍 [Ver en Google Maps]({url_mapa})", unsafe_allow_html=True)
                            
                    except:
                        st.error("⚠️ Error de carga")
        else:
            st.info(f"📷 Aún no hay fotografías válidas registradas para el día operativo {fecha_seleccionada.strftime('%d/%m/%Y')}.")
    else:
        st.info(f"📷 Aún no hay fotografías registradas para el día operativo {fecha_seleccionada.strftime('%d/%m/%Y')}.")

with tab_directorio:
    st.markdown("### 👥 Directorio y Edición de Personal")
    st.write("💡 **Doble clic** en cualquier celda para editar los datos o pegar el link de la foto de perfil. Presiona **Guardar Cambios** al terminar.")
    
    if not df_empleados.empty:
        # Reseteamos los índices para evitar problemas al comparar datos editados
        df_activos = df_empleados[df_empleados["estado"] == "ACTIVO"].reset_index(drop=True)
        df_inactivos = df_empleados[df_empleados["estado"] == "INACTIVO"].reset_index(drop=True)
        
        # --- TABLA DE ACTIVOS (AHORA INTERACTIVA) ---
        st.subheader(f"🟢 Personal Activo ({len(df_activos)})")
        if not df_activos.empty:
            
            # 1. Asegurarnos de que la columna exista visualmente
            if "foto_perfil_url" not in df_activos.columns:
                df_activos["foto_perfil_url"] = ""
            if "rango" not in df_activos.columns:
                df_activos["rango"] = "Ayudante"
            # --- NUEVO: Validar obra y obtener catálogo ---
            if "obra_actual" not in df_activos.columns:
                df_activos["obra_actual"] = "Sin Obra"
                
            lista_obras = ["Sin Obra"]
            try:
                cat_obras = supabase.table("catalogo_obras").select("nombre").eq("estado", "ACTIVA").execute()
                if cat_obras.data:
                    lista_obras.extend([o["nombre"] for o in cat_obras.data])
            except:
                pass
                
            # 2. Configurar cómo se ve cada columna
            config_columnas = {
                "empleado_id": st.column_config.TextColumn("ID", disabled=True), # Bloqueado por seguridad
                "foto_perfil_url": st.column_config.ImageColumn("📸 Foto (Link Supabase)", width="medium"),
                "nombre_completo": st.column_config.TextColumn("👤 Nombre Completo"),
                "telefono": st.column_config.TextColumn("📱 Teléfono"),
                "rol": st.column_config.TextColumn("🛠️ Rol / Puesto"),
                "rango": st.column_config.SelectboxColumn("🎖️ Rango", options=["Cabo", "Oficial", "Medio", "Ayudante"]),
                "obra_actual": st.column_config.SelectboxColumn("🏗️ Obra Asignada", options=lista_obras)
            }
            
            # 3. El Editor Mágico de Streamlit
            columnas_a_editar = ["empleado_id", "foto_perfil_url", "nombre_completo", "telefono", "rol", "rango", "obra_actual"]
            df_editado = st.data_editor(
                df_activos[columnas_a_editar],
                column_config=config_columnas,
                use_container_width=True,
                hide_index=True,
                key="editor_rh_activos"
            )
            
            # 4. Botón y Lógica para Guardar en Supabase
            if st.button("💾 Guardar Cambios en la Base de Datos", type="primary"):
                try:
                    cambios_realizados = False
                    # Comparamos fila por fila buscando diferencias
                    for index, row in df_editado.iterrows():
                        emp_id = row["empleado_id"]
                        fila_original = df_activos[df_activos["empleado_id"] == emp_id].iloc[0]
                        
                        # Manejo de nulos para la comparación de fotos
                        foto_editada = row["foto_perfil_url"] if pd.notna(row["foto_perfil_url"]) else ""
                        foto_orig = fila_original["foto_perfil_url"] if pd.notna(fila_original["foto_perfil_url"]) else ""
                        rango_editado = row["rango"] if pd.notna(row["rango"]) else ""
                        rango_orig = fila_original["rango"] if pd.notna(fila_original["rango"]) else ""
                        # --- NUEVO: Extraer obra ---
                        obra_editada = row["obra_actual"] if pd.notna(row["obra_actual"]) else "Sin Obra"
                        obra_orig = fila_original["obra_actual"] if pd.notna(fila_original["obra_actual"]) else "Sin Obra"
                        
                        if (foto_editada != foto_orig or
                            row["nombre_completo"] != fila_original["nombre_completo"] or
                            row["telefono"] != fila_original["telefono"] or
                            row["rol"] != fila_original["rol"] or
                            rango_editado != rango_orig or
                            obra_editada != obra_orig): # <-- Validamos si cambió la obra
                            
                            datos_actualizados = {
                                "foto_perfil_url": foto_editada,
                                "nombre_completo": row["nombre_completo"],
                                "telefono": row["telefono"],
                                "rol": row["rol"],
                                "rango": rango_editado,
                                "obra_actual": obra_editada # <-- Lo mandamos a guardar
                            }
                        
                        if (foto_editada != foto_orig or
                            row["nombre_completo"] != fila_original["nombre_completo"] or
                            row["telefono"] != fila_original["telefono"] or
                            row["rol"] != fila_original["rol"] or
                            rango_editado != rango_orig):
                            
                            datos_actualizados = {
                                "foto_perfil_url": foto_editada,
                                "nombre_completo": row["nombre_completo"],
                                "telefono": row["telefono"],
                                "rol": row["rol"],
                                "rango": rango_editado
                            }
                            # Actualizamos solo la fila modificada
                            supabase.table("empleados").update(datos_actualizados).eq("empleado_id", emp_id).execute()
                            cambios_realizados = True
                            
                    if cambios_realizados:
                        st.success("✅ ¡Cambios guardados con éxito!")
                        st.rerun() # Recarga la página para mostrar los datos nuevos
                    else:
                        st.info("No se detectaron modificaciones.")
                        
                except Exception as e:
                    st.error(f"❌ Error al guardar: {str(e)}")
        else:
            st.info("No hay personal activo registrado en este momento.")
            
        # ==========================================
        # 📸 MÓDULO PARA SUBIR FOTO DESDE LA PC
        # ==========================================
        st.divider()
        st.subheader("📸 Actualizar Foto de Perfil")
        st.write("Selecciona a un trabajador y sube su foto directamente desde tu equipo. El panel se limpiará automáticamente después de cada carga.")
        
        # Envolvemos en un formulario para forzar la limpieza de los campos al terminar
        with st.form("form_subir_foto", clear_on_submit=True):
            # Columna para organizar el diseño dentro del formulario
            col_foto1, col_foto2 = st.columns([1, 1])
            
            with col_foto1:
                # Lista desplegable para elegir al trabajador
                lista_activos = df_activos['empleado_id'] + " - " + df_activos['nombre_completo']
                trabajador_foto = st.selectbox("1. Selecciona al trabajador:", lista_activos)
                
            with col_foto2:
                # El botón nativo para subir archivos (por defecto solo acepta 1 a la vez, pero lo forzamos visualmente)
                foto_subida = st.file_uploader("2. Sube la imagen (JPG/PNG)", type=["jpg", "jpeg", "png"], accept_multiple_files=False)
            
            # El botón de guardar ahora pertenece al formulario
            btn_guardar_foto = st.form_submit_button("Subir y Guardar Foto", type="primary")
            
            if btn_guardar_foto:
                if foto_subida is not None:
                    # Extraemos el ID y Nombre del texto seleccionado
                    id_trabajador = trabajador_foto.split(" - ")[0]
                    nombre_trabajador = trabajador_foto.split(" - ")[1]
                    
                    with st.spinner("Subiendo foto a la nube..."):
                        try:
                            # 1. Preparamos el archivo y su nombre
                            file_bytes = foto_subida.getvalue()
                            ruta_archivo = f"{id_trabajador}_{foto_subida.name}"
                            
                            # 2. Subimos el archivo a Supabase
                            supabase.storage.from_("fotos_perfil").upload(
                                file=file_bytes,
                                path=ruta_archivo,
                                file_options={"content-type": foto_subida.type}
                            )
                            
                            # 3. Obtenemos el link público oficial
                            url_publica = supabase.storage.from_("fotos_perfil").get_public_url(ruta_archivo)
                            
                            # 4. Actualizamos la base de datos
                            supabase.table("empleados").update({"foto_perfil_url": url_publica}).eq("empleado_id", id_trabajador).execute()
                            
                            # Mostramos el éxito y recargamos para reflejar el cambio en la tabla
                            st.success(f"✅ Foto de {nombre_trabajador} actualizada con éxito.")
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Hubo un error al subir la imagen. Detalles: {str(e)}")
                else:
                    st.warning("⚠️ Por favor, carga una imagen en el recuadro antes de presionar Guardar.")
        
        # --- TABLA DE BAJAS (SOLO LECTURA) ---
        st.subheader(f"🔴 Histórico de Bajas ({len(df_inactivos)})")
        if not df_inactivos.empty:
            st.dataframe(df_inactivos[["empleado_id", "nombre_completo", "telefono", "rol", "rango", "obra_actual"]], use_container_width=True, hide_index=True)
        else:
            st.info("El archivo de bajas está limpio.")
            
    else:
        st.info("No hay empleados registrados en el sistema.")

with tab_rh:

    # ==========================================
    # PANEL CLÁSICO DE RECURSOS HUMANOS (ALTAS/BAJAS MANUALES)
    # ==========================================
    st.markdown("### 🛠️ Panel de Recursos Humanos")
    st.caption("Administra las altas y bajas manuales de los trabajadores de forma segura.")
    
    # Dividimos la pantalla en dos columnas: Izquierda (Altas) y Derecha (Bajas)
    col_alta, col_baja = st.columns(2)

    # --- SECCIÓN DE ALTA ---
    with col_alta:
        st.subheader("🟢 Alta de Nuevo Empleado")
        
        # Mostrar mensaje de éxito si existe en la memoria
        if "mensaje_alta" in st.session_state:
            st.success(st.session_state["mensaje_alta"])
            del st.session_state["mensaje_alta"]

        nuevo_id = st.text_input("ID de Empleado (Ej. EMP-005)", key="alta_id")
        nuevo_nombre = st.text_input("Nombre Completo", key="alta_nombre")
        nuevo_telefono = st.text_input("Teléfono (con código de país, ej. +525512345678)", key="alta_tel")
        
        # --- NUEVO: OBTENER OBRAS ACTIVAS ---
        obras_activas = []
        try:
            resp_obras = supabase.table("catalogo_obras").select("nombre").eq("estado", "ACTIVA").execute()
            obras_activas = [o["nombre"] for o in resp_obras.data] if resp_obras.data else ["Sin Obra"]
        except:
            obras_activas = ["Sin Obra"]
            
        obra_asignada = st.selectbox("🏗️ Asignar a Obra", obras_activas, key="alta_obra")
        
        # --- LÓGICA DE ROLES DESDE EL CATÁLOGO OFICIAL ---
        roles_existentes = []
        try:
            resp_roles = supabase.table("catalogo_puestos").select("nombre").execute()
            roles_existentes = [r["nombre"] for r in resp_roles.data] if resp_roles.data else ["Técnico"]
        except:
            roles_existentes = ["Técnico"]
            
        # Un interruptor (toggle) discreto y elegante
        modo_nuevo_rol = st.toggle("➕ Agregar un rol que no está en la lista", key="alta_toggle")
        
        if modo_nuevo_rol:
            # Dividimos en dos columnas para poner el botón de guardar SOLO el rol
            col_input_rol, col_btn_rol = st.columns([4, 2])
            with col_input_rol:
                rol_final = st.text_input("✍️ Escribe el nuevo rol:", key="alta_rol_nuevo")
            with col_btn_rol:
                st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                # BOTÓN EXCLUSIVO: Guarda el rol en la BD sin pedir empleado
                if st.button("💾 Guardar Solo Rol", type="secondary"):
                    if rol_final:
                        rol_formateado = rol_final.strip().title()
                        if rol_formateado not in roles_existentes:
                            supabase.table("catalogo_puestos").insert({"nombre": rol_formateado}).execute()
                            st.success(f"Rol '{rol_formateado}' agregado.")
                            st.rerun() # Esto recarga la página para actualizar la lista
        else:
            col_sel, col_del = st.columns([5, 1])
            with col_sel:
                rol_final = st.selectbox("Selecciona el Rol en Obra", roles_existentes, key="alta_rol_select")
            with col_del:
                st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                if st.button("🗑️", help="Eliminar este rol del catálogo oficial", key="btn_del_rol"):
                    try:
                        supabase.table("catalogo_puestos").delete().eq("nombre", rol_final).execute()
                        st.success("Rol eliminado del catálogo.")
                        st.rerun()
                    except:
                        pass
        # ----------------------------------------------
        # --- NUEVO: SELECTOR DE RANGO ---
        opciones_rango = ["Cabo", "Oficial", "Medio", "Ayudante"]
        rango_final = st.selectbox("🎖️ Selecciona el Rango", opciones_rango, key="alta_rango")
        
        st.markdown("---")
        btn_alta = st.button("Registrar Empleado", type="primary")

        if btn_alta:
            if nuevo_id and nuevo_nombre and nuevo_telefono and rol_final:
                try:
                    rol_formateado = rol_final.strip().title()
                    
                    if modo_nuevo_rol and (rol_formateado not in roles_existentes):
                        supabase.table("catalogo_puestos").insert({"nombre": rol_formateado}).execute()

                    supabase.table("empleados").insert({
                        "empleado_id": nuevo_id,
                        "nombre_completo": nuevo_nombre,
                        "telefono": nuevo_telefono,
                        "rol": rol_formateado,
                        "rango": rango_final,
                        "obra_actual": obra_asignada,
                        "estado": "ACTIVO"
                    }).execute()
                    
                    st.success(f"✅ {nuevo_nombre} registrado correctamente como {rol_formateado}.")
                    
                    for campo in ["alta_id", "alta_nombre", "alta_tel", "alta_toggle", "alta_rol_nuevo", "alta_rango", "alta_obra"]:
                        if campo in st.session_state:
                            del st.session_state[campo]
                    
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error al registrar en la base de datos: {str(e)}")
            else:
                st.warning("⚠️ Todos los campos principales son obligatorios.")

    # --- SECCIÓN DE BAJAS Y ACTUALIZACIONES ---
    with col_baja:
        st.subheader("🔴 Baja o Actualización")
        if not df_empleados.empty:
            # Creamos una lista bonita para el menú desplegable (Ej. "EMP-001 - Juan Pérez")
            lista_empleados = df_empleados['empleado_id'] + " - " + df_empleados['nombre_completo']
            empleado_seleccionado = st.selectbox("Selecciona un trabajador", lista_empleados)
            
            # Extraemos solo el ID (lo que está antes del guion) para que la base de datos lo entienda
            id_seleccionado = empleado_seleccionado.split(" - ")[0]
            
            # Botones de radio para elegir el nuevo estado
            nuevo_estado = st.radio("Cambiar estado a:", ["ACTIVO", "INACTIVO"], horizontal=True)
            
            if st.button("Actualizar Estado"):
                try:
                    # Actualizamos la fila correspondiente en Supabase
                    supabase.table("empleados").update({"estado": nuevo_estado}).eq("empleado_id", id_seleccionado).execute()
                    st.success(f"✅ Estado actualizado a {nuevo_estado}.")
                    st.rerun() # Forzamos la recarga de la página
                except Exception as e:
                    st.error(f"❌ Error al actualizar: {str(e)}")
        else:
            st.info("No hay empleados registrados en el sistema.")
            
    st.subheader("⚙️ Control de Acceso y Onboarding")
    
    # 1. Inicializar el estado en la sesión si no existe
    if "registro_abierto" not in st.session_state:
        st.session_state.registro_abierto = obtener_estado_registro()

    # 2. Renderizar el interruptor visual
    interruptor = st.toggle(
        "Permitir nuevos registros desde WhatsApp", 
        value=st.session_state.registro_abierto,
        help="Si está desactivado, el bot rechazará automáticamente a cualquier número que no esté de alta."
    )

    # 3. Si el usuario cambia el interruptor en la UI, actualizamos la base de datos
    if interruptor != st.session_state.registro_abierto:
        actualizar_estado_registro(interruptor)
        st.session_state.registro_abierto = interruptor
        if interruptor:
            st.success("🔓 ¡El bot ahora acepta registros de nuevos trabajadores!")
        else:
            st.warning("🔒 Registro cerrado. El bot ignorará solicitudes de onboarding.")
        st.rerun() # Refresca para limpiar la UI
        
    st.divider()

    # ==========================================
    # NUEVO: LA SALA DE ESPERA (ONBOARDING)
    # ==========================================
    st.subheader("⏳ Sala de Espera (Pendientes de Aprobación)")
    st.caption("Los trabajadores registrados por el bot aparecerán aquí para tu revisión.")
    
    if not df_empleados.empty:
        # Filtramos a los que tienen estado PENDIENTE
        df_pendientes = df_empleados[df_empleados["estado"] == "PENDIENTE"]
        
        if not df_pendientes.empty:
            for idx, row in df_pendientes.iterrows():
                # Dibujamos una fila visual por cada trabajador pendiente
                col_info, col_foto, col_rango, col_aprobar, col_rechazar = st.columns([3, 1.5, 2, 1.5, 1.5])

                with col_info:
                    st.write(f"**{row['nombre_completo']}**")
                    st.write(f"Puesto: {row['rol']} | Tel: {row['telefono']}")

                with col_foto:
                    if pd.notna(row.get('foto_perfil_url')) and row['foto_perfil_url'].startswith('http'):
                        st.image(row['foto_perfil_url'], width=60)
                    else:
                        st.write("📷 Sin foto")

                with col_rango:
                    opciones_rango_pend = ["Cabo", "Oficial", "Medio", "Ayudante"]
                    rango_actual = row.get('rango')
                    indice_default = opciones_rango_pend.index(rango_actual) if rango_actual in opciones_rango_pend else opciones_rango_pend.index("Ayudante")
                    rango_pendiente = st.selectbox(
                        "🎖️ Rango",
                        opciones_rango_pend,
                        index=indice_default,
                        key=f"rango_{row['empleado_id']}"
                    )

                with col_aprobar:
                    if st.button("✅ Aprobar", key=f"apr_{row['empleado_id']}", type="primary"):
                        try:
                            supabase.table("empleados").update({
                                "estado": "ACTIVO",
                                "rango": rango_pendiente
                            }).eq("empleado_id", row['empleado_id']).execute()
                            st.success(f"{row['nombre_completo']} aprobado como {rango_pendiente}.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

                with col_rechazar:
                    if st.button("❌ Rechazar", key=f"rec_{row['empleado_id']}"):
                        try:
                            supabase.table("empleados").delete().eq("empleado_id", row['empleado_id']).execute()
                            st.warning("Registro eliminado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

                st.markdown("---")
        else:
            st.info("No hay trabajadores pendientes de aprobación en este momento.")
    else:
        st.info("La base de datos está vacía.")
        
    st.divider()

with tab_obras:
    st.markdown("### 🏗️ Panel de Gestión de Obras")
    st.caption("Administra los proyectos, crea nuevas obras o cierra las terminadas.")

    col_nueva, col_lista = st.columns([4, 6])

    with col_nueva:
        st.subheader("➕ Registrar Nueva Obra")
        nueva_obra = st.text_input("Nombre de la Obra (Ej. Torre Reforma):", key="input_nueva_obra")
        if st.button("Guardar Obra", type="primary"):
            if nueva_obra:
                try:
                    nombre_formateado = nueva_obra.strip().upper()
                    supabase.table("catalogo_obras").insert({"nombre": nombre_formateado, "estado": "ACTIVA"}).execute()
                    st.success(f"✅ Obra '{nombre_formateado}' registrada con éxito.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")
            else:
                st.warning("⚠️ Escribe el nombre de la obra antes de guardar.")

    with col_lista:
        st.subheader("📋 Estado de Obras")
        # Consultamos el catálogo de obras
        resp_obras = supabase.table("catalogo_obras").select("*").order("id").execute()
        df_obras = pd.DataFrame(resp_obras.data)

        if not df_obras.empty:
            # Configuramos las columnas para bloquear el ID y Nombre, dejando editable solo el estado
            config_obras = {
                "id": st.column_config.TextColumn("ID", disabled=True),
                "nombre": st.column_config.TextColumn("Nombre de la Obra", disabled=True),
                "estado": st.column_config.SelectboxColumn("Estado", options=["ACTIVA", "CERRADA"])
            }

            df_edit_obras = st.data_editor(
                df_obras[["id", "nombre", "estado"]],
                column_config=config_obras,
                hide_index=True,
                use_container_width=True,
                key="editor_obras"
            )

            if st.button("💾 Actualizar Estados"):
                try:
                    cambios = False
                    for idx, row in df_edit_obras.iterrows():
                        id_obra = row["id"]
                        estado_nuevo = row["estado"]
                        estado_viejo = df_obras[df_obras["id"] == id_obra].iloc[0]["estado"]

                        if estado_nuevo != estado_viejo:
                            supabase.table("catalogo_obras").update({"estado": estado_nuevo}).eq("id", id_obra).execute()
                            cambios = True

                    if cambios:
                        st.success("✅ Estados actualizados correctamente en la base de datos.")
                        st.rerun()
                    else:
                        st.info("No detecté modificaciones.")
                except Exception as e:
                    st.error(f"❌ Error al actualizar: {e}")
        else:
            st.info("No hay obras registradas todavía.")

    
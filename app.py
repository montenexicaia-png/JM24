import streamlit as st
import pandas as pd
import google.generativeai as genai
from supabase import create_client, Client
import datetime
import io
import plotly.express as px
import requests
from PIL import Image
from datetime import datetime, date, timedelta
from reportes import PDFCorporativo, generar_matriz_semanal, generar_pdf_matriz_semanal
from datos_empleado import ESTADO_INCOMPLETO, ROL_POR_DEFINIR, filas_personal_por_completar, cambios_por_completar
from dias_aviso import DIAS_SEMANA, dias_de_aviso, dias_a_texto
from permisos import permisos_de, permisos_al_cambiar_de_rol, MI_CUADRILLA, POR_CODIGO
from panel_permisos import render as render_permisos

# ==========================================
# 1. CONFIGURACIÓN DE LA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Centro de Mando | Obras",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 1.2 CONEXIÓN TEMPRANA Y BRANDING (NUBE)
# ==========================================
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except Exception as e:
    st.error("⚠️ Error de conexión: Verifica tu archivo secrets.toml")
    st.stop()

# Descargamos la configuración corporativa desde Supabase
if "config_cargada" not in st.session_state:
    try:
        resp_conf = supabase.table("configuracion").select("empresa_nombre, empresa_logo, color_sidebar").eq("id", 1).execute()
        if resp_conf.data:
            st.session_state["empresa_nombre"] = resp_conf.data[0].get("empresa_nombre") or "CONEXICA | Ingeniería y Construcción"
            st.session_state["empresa_logo"] = resp_conf.data[0].get("empresa_logo") or ""
            st.session_state["sidebar_color"] = resp_conf.data[0].get("color_sidebar") or "#0E1C36"
        st.session_state["config_cargada"] = True
    except Exception as e:
        st.session_state["empresa_nombre"] = "Centro de Mando"
        st.session_state["empresa_logo"] = ""
        st.session_state["sidebar_color"] = "#0E1C36"

# AHORA SÍ: Definimos la variable ANTES del CSS
color_sidebar = st.session_state.get("sidebar_color", "#0E1C36")

# ==========================================
# 1.3 INYECCIÓN DE CSS GLOBALES
# ==========================================
st.markdown(f"""
    <style>
    /* 1. Fondo dinámico del menú lateral */
    [data-testid="stSidebar"] {{
        background-color: {color_sidebar} !important;
    }}
    
    /* Asegurar que el texto principal del menú lateral sea blanco/claro para contrastar */
    [data-testid="stSidebar"] h3, [data-testid="stSidebar"] p, [data-testid="stSidebar"] label {{
        color: #FAFAFA !important;
    }}

    /* 2. Estilos para las tarjetas de métricas tipo dashboard */
    div[data-testid="metric-container"] {{
        background-color: #FFFFFF;
        border-left: 5px solid {color_sidebar};
        border-radius: 5px;
        padding: 15px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
        transition: transform 0.2s ease-in-out, box-shadow 0.2s;
    }}
    div[data-testid="metric-container"]:hover {{
        transform: translateY(-3px);
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.1);
    }}
    
    /* 3. Títulos principales sobrios y legibles */
    .big-title {{
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        color: {color_sidebar};
        font-weight: 700;
        letter-spacing: 0.5px;
        border-bottom: 2px solid #E67E22;
        padding-bottom: 10px;
    }}
    
    .sub-title {{
        color: {color_sidebar};
        font-weight: 600;
        border-left: 4px solid #E67E22;
        padding-left: 10px;
        margin-top: 15px;
        margin-bottom: 15px;
    }}
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

def obtener_config_alertas():
    """Obtiene los horarios y días de aviso desde Supabase (quién recibe los avisos está en empleados.permisos).
    Usa select("*") para no fallar si aún no existe la columna dias_aviso."""
    try:
        respuesta = supabase.table("configuracion").select("*").eq("id", 1).execute()
        if respuesta.data:
            return respuesta.data[0]
        return {"hora_corte_entrada": "08:15", "hora_corte_salida": "18:00"}
    except Exception as e:
        return {"hora_corte_entrada": "08:15", "hora_corte_salida": "18:00"}

def actualizar_config_alertas(entrada, salida, dias):
    """Guarda los nuevos horarios de corte y los días de aviso en la base de datos"""
    try:
        supabase.table("configuracion").update({
            "hora_corte_entrada": entrada,
            "hora_corte_salida": salida,
            "dias_aviso": dias_a_texto(dias)
        }).eq("id", 1).execute()
        return True
    except Exception as e:
        st.error(f"Error al guardar configuración de alertas: {e}")
        return False

def obtener_config_reporte_semanal():
    """Obtiene el día (0=Lunes...6=Domingo) y la hora en que se envía el reporte semanal al Director"""
    try:
        respuesta = supabase.table("configuracion").select("dia_reporte_semanal, hora_reporte_semanal").eq("id", 1).execute()
        if respuesta.data:
            return respuesta.data[0]
        return {"dia_reporte_semanal": 4, "hora_reporte_semanal": "11:00"}
    except Exception as e:
        return {"dia_reporte_semanal": 4, "hora_reporte_semanal": "11:00"}

def actualizar_config_reporte_semanal(dia, hora):
    """Guarda el día y la hora del reporte semanal en la base de datos"""
    try:
        supabase.table("configuracion").update({
            "dia_reporte_semanal": dia,
            "hora_reporte_semanal": hora
        }).eq("id", 1).execute()
        return True
    except Exception as e:
        st.error(f"Error al guardar la configuración del reporte semanal: {e}")
        return False

# ==========================================
# PDFCorporativo y generar_matriz_semanal ahora viven en reportes.py
# (se movieron para que main.py tambien pueda generar el PDF semanal del Director)
# ==========================================

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

def aplicar_formato_hoja(writer, df, sheet_name, color_header="#1F4E78"):
    """Le da a cualquier hoja de Excel el mismo estilo profesional de la Matriz Semanal:
    encabezado azul con texto blanco, columnas autoajustadas y fila superior congelada."""
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]

    formato_header = workbook.add_format({
        'bold': True,
        'bg_color': color_header,
        'font_color': 'white',
        'border': 1,
        'align': 'center',
        'valign': 'vcenter'
    })

    # Repintamos la fila de encabezado con el formato bonito
    for col_num, col_name in enumerate(df.columns):
        worksheet.write(0, col_num, col_name, formato_header)

    # Autoajuste aproximado del ancho de columna, según el contenido más largo
    for col_num, col_name in enumerate(df.columns):
        if not df.empty:
            max_len_datos = df[col_name].apply(lambda x: len(str(x)) if pd.notna(x) else 0).max()
            max_len = max(max_len_datos, len(str(col_name))) + 2
        else:
            max_len = len(str(col_name)) + 2
        worksheet.set_column(col_num, col_num, min(max_len, 40))

    # Inmovilizamos la fila de encabezado para que no se pierda al hacer scroll
    worksheet.freeze_panes(1, 0)

# ==========================================
# 1.5 SISTEMA DE LOGIN (Guardia de Seguridad)
# ==========================================
def check_password():
    """Devuelve True si el usuario ingresó la contraseña correcta."""
    
    # 1. Si ya comprobó la contraseña antes, lo dejamos pasar inmediatamente sin recargar.
    if st.session_state.get("password_correct", False):
        return True

    # 2. Función que valida la contraseña cuando el usuario la escribe o aprieta el botón.
    def password_entered():
        if st.session_state.get("password", "") == st.secrets["PASSWORD_ACCESO"]:
            st.session_state["password_correct"] = True
        else:
            st.session_state["password_correct"] = False

    # Obtenemos el color dinámico, nombre y logo (por si no se han configurado aún)
    color_sidebar = st.session_state.get("sidebar_color", "#0E1C36")
    nombre_empresa = st.session_state.get("empresa_nombre", "CONEXICA | Ingeniería y Construcción")
    logo_url = st.session_state.get("empresa_logo", "")

    # 3. Magia CSS: Tarjeta y Botón Elegante
    st.markdown(f"""
        <style>
        /* Ocultar elementos nativos para efecto de Landing Page */
        [data-testid="collapsedControl"] {{ display: none !important; }}
        [data-testid="stSidebar"] {{ display: none !important; }}
        [data-testid="stHeader"] {{ display: none !important; }}
        
        /* Fondo de pantalla sutil para que resalte la tarjeta blanca */
        .stApp {{
            background-color: #F4F6F9;
        }}

        /* Seleccionamos la columna del medio y la transformamos en la tarjeta elegante */
        div[data-testid="column"]:nth-of-type(2) {{
            background-color: #FFFFFF;
            padding: 40px 30px;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.08);
            border-top: 6px solid {color_sidebar};
            margin-top: 10vh;
        }}

        /* Forzar el Logo a proporción 1:1 (Cuadrado perfecto) y centrado */
        .logo-empresa {{
            width: 120px;
            height: 120px;
            object-fit: contain;
            aspect-ratio: 1/1;
            margin-bottom: 15px;
            border-radius: 8px; 
            display: block;
            margin-left: auto;
            margin-right: auto;
        }}

        /* Título estilizado */
        .login-title {{
            color: #2C3E50;
            font-size: 24px;
            font-weight: 800;
            margin-bottom: 30px;
            font-family: 'Segoe UI', Roboto, sans-serif;
            text-align: center;
            line-height: 1.4;
        }}
        
        /* Asegurar que el input ocupe todo el ancho de la tarjeta */
        div[data-testid="stTextInput"] {{
            width: 100%;
        }}

        /* --- NUEVO: Estilo del botón de Entrar --- */
        div[data-testid="stButton"] button[kind="primary"] {{
            background-color: {color_sidebar} !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 8px !important;
            padding: 0.5rem 1rem !important;
            font-weight: 600 !important;
            margin-top: 15px !important;
            transition: all 0.3s ease !important;
        }}
        div[data-testid="stButton"] button[kind="primary"]:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 15px rgba(0,0,0,0.15) !important;
            opacity: 0.95;
        }}
        </style>
    """, unsafe_allow_html=True)

    # Usamos columnas para centrar la tarjeta: 1 (vacía) - 2 (Tarjeta) - 3 (vacía)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    
    with col2:
        # A. Mostramos el Logo
        if logo_url and logo_url.strip() != "":
            st.markdown(f"<img src='{logo_url}' class='logo-empresa'>", unsafe_allow_html=True)
            
        # B. El texto de Bienvenida limpio
        st.markdown(
            f"<div class='login-title'>Bienvenido<br><span style='color: {color_sidebar};'>{nombre_empresa}</span></div>", 
            unsafe_allow_html=True
        )
        
        # C. Input de contraseña nativo
        st.text_input(
            "🔑 Clave de Acceso:", 
            type="password", 
            on_change=password_entered, 
            key="password",
            placeholder="Escribe tu contraseña..."
        )
        
        # D. NUEVO: Botón Estilizado y conectado a la función de validación
        st.button("Entrar al Sistema ➔", type="primary", on_click=password_entered, use_container_width=True)
        
        # E. Mostrar alerta de error si la bandera de incorrecto es verdadera
        if "password_correct" in st.session_state and not st.session_state["password_correct"]:
            st.error("❌ Contraseña incorrecta. Intento bloqueado.")
            
    return False

# Si el usuario NO tiene la contraseña, detenemos TODA la página aquí mismo.
if not check_password():
    st.stop()

# ==========================================
# 2. CONEXIÓN (Usando secretos)
# ==========================================
#try:
 #   url: str = st.secrets["SUPABASE_URL"]
  #  key: str = st.secrets["SUPABASE_KEY"]
   # supabase: Client = create_client(url, key)
    
    # Gemini (lo usaremos más adelante para la auditoría)
   # genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
   # st.sidebar.success("✅ Conectado a la Base de Datos")
#except Exception as e:
 #   st.sidebar.error("⚠️ Error de conexión: Verifica tu archivo secrets.toml")
  #  st.stop() # Detiene la ejecución si no hay conexión

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
    fecha_seleccionada = st.date_input("📆 Fecha del Día Operativo", date.today())

st.divider()

# --- MOTOR DE FILTRADO: DÍA OPERATIVO Y TURNO NOCTURNO ---
kpi_entradas = 0
kpi_salidas = 0
kpi_urgentes = 0

# Convertimos las columnas y las ajustamos automáticamente al huso horario de México
if not df_asistencias.empty:
    # format="ISO8601": Supabase devuelve "…:00+00:00" sin fracción cuando los microsegundos son 0 (p. ej. el
    # cierre automático) y con fracción en los demás; sin esto pandas 3 falla al mezclar los dos formatos.
    df_asistencias["fecha_dt"] = pd.to_datetime(df_asistencias["fecha_hora"], format="ISO8601")
    try:
        # Si la base de datos ya viene con zona horaria, la convertimos a la local
        df_asistencias["fecha_dt"] = df_asistencias["fecha_dt"].dt.tz_convert('America/Mexico_City')
    except TypeError:
        # Si viene "neutra", la declaramos como UTC y luego la transformamos a México
        df_asistencias["fecha_dt"] = df_asistencias["fecha_dt"].dt.localize('UTC').dt.tz_convert('America/Mexico_City')

if not df_incidentes.empty:
    df_incidentes["fecha_dt"] = pd.to_datetime(df_incidentes["fecha_hora"], format="ISO8601")
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
    fecha_siguiente = fecha_seleccionada + timedelta(days=1)
    
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

st.sidebar.markdown("### 🏢 Menú de Navegación")
menu_opcion = st.sidebar.radio(
    "Selecciona un módulo:", 
    [
        "📈 Dashboard Principal", 
        "📋 Tabla de Asistencias", 
        "📸 Galería de Campo", 
        "👥 Directorio de Personal", 
        "⚙️ Gestión RH",
        "🏗️ Gestión de Obras",
        "🪜 Jerarquía y Cuadrillas",
        "🔐 Permisos y Accesos",
        "⚙️ Configuración"
    ]
)

if menu_opcion == "📈 Dashboard Principal":

    # ---------------------------------------------------------
    # EL PULSO DE LA OBRA
    # ---------------------------------------------------------
    st.header("📈 Asistencia de Proyectos")

    # === 1. TABLA RESUMEN POR OBRA (siempre muestra TODAS las obras, es el panorama general) ===
    st.markdown("##### 🏗️ Resumen por Obra")

    if not df_empleados.empty and "obra_actual" in df_empleados.columns:
        activos_df = df_empleados[df_empleados["estado"] == "ACTIVO"].copy()
        activos_df["obra_actual"] = activos_df["obra_actual"].fillna("Sin Obra")

        resumen_obras = activos_df.groupby("obra_actual").agg(
            Personal_Activo=("empleado_id", "count")
        ).reset_index().rename(columns={"obra_actual": "Obra"})

        if not df_asistencias_hoy.empty:
            entradas_hoy = df_asistencias_hoy[df_asistencias_hoy["tipo_registro"] == "ENTRADA"]
            entradas_con_obra = entradas_hoy.merge(df_empleados[["empleado_id", "obra_actual"]], on="empleado_id", how="left")
            entradas_con_obra["obra_actual"] = entradas_con_obra["obra_actual"].fillna("Sin Obra")
            conteo_entradas = entradas_con_obra.groupby("obra_actual").size().reset_index(name="Entradas_Hoy").rename(columns={"obra_actual": "Obra"})
            resumen_obras = resumen_obras.merge(conteo_entradas, on="Obra", how="left")
        else:
            resumen_obras["Entradas_Hoy"] = 0
        resumen_obras["Entradas_Hoy"] = resumen_obras["Entradas_Hoy"].fillna(0).astype(int)
        resumen_obras["Faltantes"] = resumen_obras["Personal_Activo"] - resumen_obras["Entradas_Hoy"]

        if not df_incidentes_hoy.empty:
            urgentes_hoy = df_incidentes_hoy[df_incidentes_hoy["estado"] == "URGENTE"]
            urgentes_con_obra = urgentes_hoy.merge(df_empleados[["empleado_id", "obra_actual"]], on="empleado_id", how="left")
            urgentes_con_obra["obra_actual"] = urgentes_con_obra["obra_actual"].fillna("Sin Obra")
            conteo_urgentes = urgentes_con_obra.groupby("obra_actual").size().reset_index(name="Incidentes_Urgentes").rename(columns={"obra_actual": "Obra"})
            resumen_obras = resumen_obras.merge(conteo_urgentes, on="Obra", how="left")
        else:
            resumen_obras["Incidentes_Urgentes"] = 0
        resumen_obras["Incidentes_Urgentes"] = resumen_obras["Incidentes_Urgentes"].fillna(0).astype(int)

        resumen_obras = resumen_obras.rename(columns={
            "Personal_Activo": "👷 Personal Activo",
            "Entradas_Hoy": "🟢 Entradas Hoy",
            "Faltantes": "🟠 Faltantes",
            "Incidentes_Urgentes": "⚠️ Urgentes"
        })

        st.dataframe(resumen_obras, use_container_width=True, hide_index=True)
    else:
        st.info("Aún no hay datos suficientes para desglosar por obra.")

    st.divider()

    # === 2. SELECTOR DE OBRA (justo arriba de las gráficas que sí cambia) ===
    obras_disponibles = ["Todas las Obras"]
    if not df_empleados.empty and "obra_actual" in df_empleados.columns:
        obras_unicas = df_empleados["obra_actual"].dropna().unique().tolist()
        obras_disponibles.extend(obras_unicas)

    col_filtro, col_btn = st.columns([3, 1])
    with col_filtro:
        obra_seleccionada = st.selectbox("🏗️ Ver gráficas de:", obras_disponibles)
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Actualizar Datos"):
            st.rerun()

    # === 3. APLICAR EL FILTRO (solo alimenta las gráficas de abajo) ===
    df_empleados_kpi = df_empleados.copy()
    df_asistencias_kpi = df_asistencias_hoy.copy()

    if obra_seleccionada != "Todas las Obras":
        if not df_empleados_kpi.empty and "obra_actual" in df_empleados_kpi.columns:
            df_empleados_kpi = df_empleados_kpi[df_empleados_kpi["obra_actual"] == obra_seleccionada]

        if not df_asistencias_kpi.empty:
            df_asistencias_kpi = df_asistencias_kpi.merge(
                df_empleados[["empleado_id", "obra_actual"]], on="empleado_id", how="left"
            )
            if "obra" in df_asistencias_kpi.columns:
                df_asistencias_kpi["obra_para_filtro"] = df_asistencias_kpi["obra"].fillna(df_asistencias_kpi["obra_actual"])
            else:
                df_asistencias_kpi["obra_para_filtro"] = df_asistencias_kpi["obra_actual"]
            df_asistencias_kpi = df_asistencias_kpi[df_asistencias_kpi["obra_para_filtro"] == obra_seleccionada]

    st.divider()

    # === 4. GRÁFICAS PRINCIPALES (cambian en vivo según la obra elegida arriba) ===
    st.markdown("<br>", unsafe_allow_html=True)
    col_graf1, col_graf2 = st.columns(2)

    with col_graf1:
        st.markdown("##### 👷 Distribución de Personal")
        if not df_empleados_kpi.empty:
            activos_graf = df_empleados_kpi[df_empleados_kpi["estado"] == "ACTIVO"]
            if not activos_graf.empty:
                fig_roles = px.pie(
                    activos_graf,
                    names="rol",
                    hole=0.4,
                    color_discrete_sequence=["#1F4E78", "#27AE60", "#E67E22", "#7F8C8D"]
                )
                fig_roles.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=0, b=0, l=0, r=0))
                st.plotly_chart(fig_roles, use_container_width=True)
            else:
                st.info("No hay personal activo para graficar.")
        else:
            st.info("No hay datos en el directorio.")

    with col_graf2:
        st.markdown("##### 📊 Flujo de Asistencias Hoy")
        if not df_asistencias_kpi.empty:
            conteo = df_asistencias_kpi["tipo_registro"].value_counts().reset_index()
            conteo.columns = ["Tipo", "Cantidad"]
            fig_flujo = px.bar(
                conteo,
                x="Tipo",
                y="Cantidad",
                color="Tipo",
                text="Cantidad",
                color_discrete_sequence=["#1F4E78", "#27AE60", "#E67E22", "#7F8C8D"]
            )
            fig_flujo.update_traces(textposition='outside')
            fig_flujo.update_layout(
                showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis_title="",
                yaxis_title="",
                margin=dict(t=0, b=0, l=0, r=0)
            )
            st.plotly_chart(fig_flujo, use_container_width=True)
        else:
            st.info("Aún no hay registros de asistencia hoy para graficar.")

    # === 5. GRÁFICAS SECUNDARIAS: Personal físico por obra + Especialidades (también respetan el filtro) ===
    st.markdown("<br>", unsafe_allow_html=True)

    if not df_asistencias_kpi.empty and not df_empleados.empty:
        entradas_para_cruce = df_asistencias_kpi[df_asistencias_kpi["tipo_registro"] == "ENTRADA"]
        df_cruzado = pd.merge(
            entradas_para_cruce[["empleado_id"]],
            df_empleados[["empleado_id", "obra_actual", "rol"]],
            on="empleado_id",
            how="inner"
        )
    else:
        df_cruzado = pd.DataFrame()

    col_graf3, col_graf4 = st.columns(2)

    with col_graf3:
        st.markdown("##### 🏗️ Personal Físico por Obra (Hoy)")
        if not df_cruzado.empty and "obra_actual" in df_cruzado.columns:
            conteo_obras = df_cruzado["obra_actual"].value_counts().reset_index()
            conteo_obras.columns = ["Obra", "Trabajadores"]

            fig_obras = px.pie(
                conteo_obras,
                names="Obra",
                values="Trabajadores",
                hole=0.4,
                color_discrete_sequence=["#1F4E78", "#27AE60", "#E67E22", "#7F8C8D"]
            )
            fig_obras.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig_obras, use_container_width=True)
        else:
            st.info("Aún no hay registros de entrada para graficar las obras.")

    with col_graf4:
        st.markdown("##### 🛠️ Especialidades en Campo (Hoy)")
        if not df_cruzado.empty and "rol" in df_cruzado.columns:
            conteo_roles = df_cruzado["rol"].value_counts().reset_index()
            conteo_roles.columns = ["Especialidad", "Cantidad"]

            fig_roles2 = px.bar(
                conteo_roles,
                x="Cantidad",
                y="Especialidad",
                orientation='h',
                text="Cantidad",
                color="Especialidad",
                color_discrete_sequence=["#1F4E78", "#27AE60", "#E67E22", "#7F8C8D"]
            )
            fig_roles2.update_traces(textposition='inside')
            fig_roles2.update_layout(
                showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis_title="",
                yaxis_title="",
                margin=dict(t=0, b=0, l=0, r=0)
            )
            st.plotly_chart(fig_roles2, use_container_width=True)
        else:
            st.info("Aún no hay registros de entrada para graficar las especialidades.")

    # --- BLOQUE 2: CENTRO DE ANÁLISIS DE IA (GEMINI) ---
    st.subheader("🧠 Centro de Análisis Estratégico (IA)")
    st.caption("Selecciona el alcance del reporte. La IA analizará los datos y detectará patrones operativos.")

    # 1. Inyectamos CSS para dar el color corporativo al botón y a la caja de resumen
    st.markdown(f"""
        <style>
        .panel-auditoria {{
            background-color: #F8F9FA;
            border-left: 5px solid {color_sidebar};
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            color: #2C3E50;
        }}
        /* Forzar que todos los botones primarios en esta vista usen el color de la marca */
        div[data-testid="stButton"] button[kind="primary"] {{
            background-color: {color_sidebar} !important;
            color: #FFFFFF !important;
            border: none !important;
            transition: all 0.3s ease !important;
        }}
        div[data-testid="stButton"] button[kind="primary"]:hover {{
            box-shadow: 0 4px 10px rgba(0,0,0,0.2) !important;
            transform: translateY(-2px);
        }}
        </style>
    """, unsafe_allow_html=True)

    # 2. Selector de Alcance Temporal
    alcance_auditoria = st.radio(
        "🔎 Rango de Auditoría:",
        ["📅 Reporte Diario", "📆 Corte Semanal", "📊 Auditoría Mensual"],
        horizontal=True
    )

    # 3. Lógica matemática para filtrar fechas según el calendario superior
    fecha_fin = fecha_seleccionada
    if alcance_auditoria == "📅 Reporte Diario":
        fecha_inicio = fecha_fin
        texto_rango = f"el día {fecha_fin.strftime('%d/%m/%Y')}"
    elif alcance_auditoria == "📆 Corte Semanal":
        # Retrocede hasta el lunes de la semana seleccionada
        fecha_inicio = fecha_fin - timedelta(days=fecha_fin.weekday()) 
        texto_rango = f"la semana del {fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}"
    else:
        # Retrocede al día 1 del mes seleccionado
        fecha_inicio = fecha_fin.replace(day=1) 
        texto_rango = f"el mes de {fecha_fin.strftime('%B %Y')}"

    # 4. Filtrado de bases de datos para el Pre-vuelo
    df_asist_ia = pd.DataFrame()
    df_incid_ia = pd.DataFrame()

    if not df_asistencias.empty and "fecha_dt" in df_asistencias.columns:
        df_asist_ia = df_asistencias[
            (df_asistencias["fecha_dt"].dt.date >= fecha_inicio) & 
            (df_asistencias["fecha_dt"].dt.date <= fecha_fin)
        ]
        
    if not df_incidentes.empty and "fecha_dt" in df_incidentes.columns:
        df_incid_ia = df_incidentes[
            (df_incidentes["fecha_dt"].dt.date >= fecha_inicio) & 
            (df_incidentes["fecha_dt"].dt.date <= fecha_fin)
        ]

    # Contadores para la caja de transparencia
    total_asist_ia = len(df_asist_ia)
    total_incid_ia = len(df_incid_ia)
    urgentes_ia = len(df_incid_ia[df_incid_ia["estado"] == "URGENTE"]) if not df_incid_ia.empty else 0

    # 5. Interfaz de Transparencia (Pre-vuelo)
    st.markdown(f"""
    <div class="panel-auditoria">
        <strong>📊 Datos en cola para análisis sobre {texto_rango}:</strong><br>
        • 👷 <b>{total_asist_ia}</b> registros de campo detectados.<br>
        • ⚠️ <b>{total_incid_ia}</b> incidentes y reportes (<i>{urgentes_ia} marcados como urgentes</i>).
    </div>
    """, unsafe_allow_html=True)

    # 6. Botón de Acción Dinámico
    texto_boton = alcance_auditoria.split(' ')[1] + " " + alcance_auditoria.split(' ')[2]
    # 6. Botón de Acción Dinámico y Conexión con IA
    texto_boton = alcance_auditoria.split(' ', 1)[1]
    
    if st.button(f"Ejecutar {texto_boton} 🚀", type="primary"):
        # Utilizamos status en lugar de spinner para mostrar qué hace el sistema paso a paso
        with st.status("🧠 Inicializando auditoría inteligente...", expanded=True) as status:
            try:
                st.write("📥 Recopilando bitácoras de campo y reportes...")
                df_nombres = df_empleados[["empleado_id", "nombre_completo"]]
                df_asist_ia_nom = df_asist_ia.merge(df_nombres, on="empleado_id", how="left") if not df_asist_ia.empty else df_asist_ia
                df_incid_ia_nom = df_incid_ia.merge(df_nombres, on="empleado_id", how="left") if not df_incid_ia.empty else df_incid_ia

                texto_asistencias = df_asist_ia_nom[["nombre_completo", "tipo_registro", "fecha_hora", "avances", "pendientes"]].to_string() if not df_asist_ia_nom.empty else "Sin registros de asistencia en este periodo."
                texto_incidentes = df_incid_ia_nom[["nombre_completo", "descripcion", "estado", "fecha_hora"]].to_string() if not df_incid_ia_nom.empty else "Sin incidentes reportados en este periodo."

                st.write("⚙️ Estructurando parámetros de análisis temporal...")
                # Prompts dinámicos según el alcance elegido
                if alcance_auditoria == "📅 Reporte Diario":
                    instrucciones = f"""
                    Actúa como un Supervisor de Obra. Analiza estrictamente los datos del día {fecha_fin.strftime('%d/%m/%Y')}.
                    Genera un reporte conciso con viñetas y usa semáforos visuales (🟢 Normal, 🟡 Precaución, 🔴 Riesgo).
                    Estructura obligatoria:
                    1. **Estado General del Día:** Resumen en 2 líneas.
                    2. **Avances Destacados:** Qué se logró hoy.
                    3. **Alertas y Riesgos:** Anomalías o urgencias (Menciona el nombre del empleado).
                    4. **Acción Sugerida para Mañana:** 1 o 2 tareas tácticas para el gerente.
                    Mantén un tono objetivo. No inventes datos.
                    """
                elif alcance_auditoria == "📆 Corte Semanal":
                    instrucciones = f"""
                    Actúa como un Gerente de Proyectos. Analiza los datos de la semana del {fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}.
                    Genera un reporte analítico con viñetas y usa semáforos visuales (🟢, 🟡, 🔴).
                    Estructura obligatoria:
                    1. **Resumen de la Semana:** Balance general.
                    2. **Patrones de Campo:** Detecta si hubo ausentismo repetido de algún trabajador o mucho tiempo extra.
                    3. **Incidentes Acumulados:** Resumen de los riesgos de la semana.
                    4. **Recomendación Estratégica:** Qué debe cambiar la próxima semana.
                    Mantén un tono directivo y gerencial.
                    """
                else: # Mensual
                    instrucciones = f"""
                    Actúa como un Director de Operaciones. Analiza los datos del mes de {fecha_fin.strftime('%B %Y')}.
                    Genera un Resumen Ejecutivo de alto nivel con viñetas y usa semáforos visuales (🟢, 🟡, 🔴).
                    Estructura obligatoria:
                    1. **Panorama Operativo Mensual:** Salud del proyecto este mes.
                    2. **Tendencias de Recursos Humanos:** Nivel de constancia y asistencia de la flotilla.
                    3. **Evaluación de Riesgos:** Incidentes críticos que impactaron el mes.
                    4. **Directrices para el Siguiente Mes:** Recomendación ejecutiva.
                    Mantén un tono altamente corporativo.
                    """

                prompt_final = f"{instrucciones}\n\n--- DATOS DE ASISTENCIA ---\n{texto_asistencias}\n\n--- DATOS DE INCIDENTES ---\n{texto_incidentes}"

                st.write("🤖 Consultando a Gemini AI y redactando reporte...")
                
                modelo_disponible = None
                for m in genai.list_models():
                    if 'generateContent' in m.supported_generation_methods:
                        modelo_disponible = m.name
                        break
                
                if modelo_disponible:
                    model = genai.GenerativeModel(modelo_disponible)
                    respuesta = model.generate_content(prompt_final)
                    
                    st.session_state['reporte_guardado'] = respuesta.text
                    
                    # Generación de PDF en memoria
                    st.write("📑 Renderizando documento PDF corporativo...")

                    def generar_pdf_auditoria(texto, tipo_auditoria, rango_texto):
                        pdf = PDFCorporativo(
                            titulo_documento=f"Auditoría de Obra · {tipo_auditoria} · {rango_texto}",
                            empresa_nombre=st.session_state.get("empresa_nombre", "Centro de Mando"),
                            color_marca_hex=st.session_state.get("sidebar_color", "#0E1C36"),
                            logo_url=st.session_state.get("empresa_logo", "")
                        )
                        pdf.add_page()
                        
                        # Limpiar formato y quitar emojis para que FPDF no arroje error
                        texto_limpio = texto.replace("**", "").replace("*", "-")
                        texto_limpio = texto_limpio.encode('latin-1', 'ignore').decode('latin-1')
                        
                        pdf.set_font("helvetica", size=12)
                        pdf.multi_cell(0, 8, txt=texto_limpio)
                        
                        return bytes(pdf.output())

                    st.session_state['pdf_bytes'] = generar_pdf_auditoria(respuesta.text, texto_boton, texto_rango)
                    marca_tiempo = datetime.now().strftime("%Y-%m-%d_%H-%M")
                    st.session_state['pdf_nombre'] = f"Auditoria_{texto_boton.replace(' ', '_')}_{marca_tiempo}.pdf"
                    
                    status.update(label="✅ Análisis completado con éxito", state="complete", expanded=False)
                else:
                    status.update(label="❌ Error: Cerebro de IA apagado", state="error", expanded=True)
                    st.error("No se encontró un modelo de Gemini disponible. Verifica tu API Key.")

            except Exception as e:
                status.update(label="❌ Ocurrió un error técnico", state="error", expanded=True)
                st.error(f"Detalle: {str(e)}")

    # 7. Mostrar Reporte Visual y Botón de Descarga PDF
    if 'reporte_guardado' in st.session_state and 'pdf_bytes' in st.session_state:
        st.markdown(st.session_state['reporte_guardado'])
        st.divider()
        
        st.download_button(
            label=f"📑 Descargar PDF",
            data=st.session_state['pdf_bytes'],
            file_name=st.session_state['pdf_nombre'],
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
    
elif menu_opcion == "📋 Tabla de Asistencias":
    st.markdown("<h2 class='sub-title'>📋 Registro Detallado de Asistencias</h2>", unsafe_allow_html=True)
    
    if not df_asistencias_hoy.empty:
        df_mostrar = df_asistencias_hoy.copy()

        # Reemplazamos el ID crudo por el nombre del trabajador
        df_mostrar = df_mostrar.merge(df_empleados[["empleado_id", "nombre_completo"]], on="empleado_id", how="left")
        df_mostrar["nombre_completo"] = df_mostrar["nombre_completo"].fillna(df_mostrar["empleado_id"])

        # Ajuste de fechas y turno
        df_mostrar["fecha_dt"] = pd.to_datetime(df_mostrar["fecha_dt"], errors='coerce')
        df_mostrar["Hora Registro"] = df_mostrar["fecha_dt"].dt.strftime("%d/%m/%Y %H:%M")
        df_mostrar["Ecosistema Turno"] = df_mostrar.apply(
            lambda r: "🌙 Nocturno" if r["fecha_dt"].date() > fecha_seleccionada else "☀️ Ordinario",
            axis=1
        )

        # Validamos si la columna 'ubicacion' existe
        cols_a_mostrar = ["nombre_completo", "tipo_registro", "Hora Registro", "Ecosistema Turno"]
        if "ubicacion" in df_mostrar.columns:
            cols_a_mostrar.append("ubicacion")
        cols_a_mostrar.extend(["avances", "pendientes"])

        # ==========================================
        # MAGIA VISUAL: Pandas Styling + Column Config
        # ==========================================
        def estilo_asistencias(row):
            """Colorea toda la fila sutilmente dependiendo si es ENTRADA o SALIDA"""
            if row['tipo_registro'] == 'ENTRADA':
                return ['background-color: #F6FFF8; color: #1B5E20'] * len(row) # Verde muy pálido
            elif row['tipo_registro'] == 'SALIDA':
                return ['background-color: #FFFAFA; color: #B71C1C'] * len(row) # Rojo muy pálido
            return [''] * len(row)

        df_estilizado = df_mostrar[cols_a_mostrar].style.apply(estilo_asistencias, axis=1)

        configuracion_columnas = {
            "nombre_completo": st.column_config.TextColumn("Trabajador", width="medium"),
            "tipo_registro": st.column_config.TextColumn("Movimiento", width="small"),
            "Hora Registro": st.column_config.TextColumn("Fecha y Hora", width="medium"),
            "Ecosistema Turno": st.column_config.TextColumn("Turno", width="small"),
            "ubicacion": st.column_config.LinkColumn("Ubicación", display_text="📍 Ver en Mapa", width="small"),
            "avances": st.column_config.TextColumn("Avances / Notas", width="large"),
            "pendientes": st.column_config.TextColumn("Pendientes", width="medium")
        }

        st.dataframe(
            df_estilizado, 
            use_container_width=True, 
            hide_index=True, 
            column_config=configuracion_columnas
        )
    else:
        st.info(f"Aún no hay registros de asistencia para el día operativo {fecha_seleccionada.strftime('%d/%m/%Y')}.")
        
    st.divider()

    # =========================================================
    # SECCIÓN MUDADA: 📁 Evidencia y Registros (Exportaciones)
    # =========================================================
    st.markdown("<h3 class='sub-title'>📁 Evidencia y Exportación</h3>", unsafe_allow_html=True)
    st.write("Configura el formato y descarga los reportes operativos de tu flotilla.")

    # --- 1. ZONA DE CONFIGURACIÓN (Ocupa todo el ancho, elimina asimetrías) ---
    tipo_reporte = st.radio(
        "Formato del documento PDF:",
        ["📅 Reporte Diario", "📆 Reporte Semanal"],
        horizontal=True
    )
    
    st.markdown("<br>", unsafe_allow_html=True) # Respiro visual

    # --- 2. ZONA DE BOTONES (Alineación perfecta garantizada) ---
    col_exp1, col_exp2 = st.columns(2)

    with col_exp1:
        # Reporte Matricial Excel
        df_matriz_semanal, fechas_cabecera = generar_matriz_semanal(fecha_seleccionada, df_empleados, df_asistencias)
        
        if not df_matriz_semanal.empty:
            excel_matriz_bytes = exportar_matriz_excel(df_matriz_semanal, fechas_cabecera)
            st.download_button(
                label="📊 Descargar Matriz Semanal (Excel)",
                data=excel_matriz_bytes,
                file_name=f"Matriz_Asistencia_{fecha_seleccionada.strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary" # Mantiene el color corporativo de la nube
            )
        else:
            st.button("📊 Matriz Semanal No Disponible", disabled=True, use_container_width=True)

    with col_exp2:
        # Funciones internas para el PDF Corporativo
        def limpiar_txt(texto):
            if pd.isna(texto): return ""
            return str(texto).encode('latin-1', 'ignore').decode('latin-1')

        def generar_pdf_diario(df_asist, df_emp, fecha_op):
            pdf = PDFCorporativo(
                titulo_documento=limpiar_txt(f"Reporte Diario de Asistencias · {fecha_op.strftime('%d/%m/%Y')}"),
                empresa_nombre=st.session_state.get("empresa_nombre", "Centro de Mando"),
                color_marca_hex=st.session_state.get("sidebar_color", "#0E1C36"),
                logo_url=st.session_state.get("empresa_logo", "")
            )
            pdf.add_page()
            
            df_hoy = df_asist[df_asist['fecha_dt'].dt.date == fecha_op].copy()
            obras_activas = df_emp[df_emp['estado'] == 'ACTIVO']['obra_actual'].dropna().unique()

            for obra in obras_activas:
                emp_obra = df_emp[(df_emp['obra_actual'] == obra) & (df_emp['estado'] == 'ACTIVO')]
                if emp_obra.empty: continue
                
                pdf.set_font("helvetica", "B", 11)
                pdf.set_text_color(31, 78, 120) 
                pdf.cell(0, 10, limpiar_txt(f"🏗️ Obra: {obra}"), align="L", new_x="LMARGIN", new_y="NEXT")
                
                pdf.set_font("helvetica", "B", 9)
                pdf.set_fill_color(235, 235, 235)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(60, 8, "Trabajador", border=1, align="C", fill=True)
                pdf.cell(25, 8, "Tipo", border=1, align="C", fill=True)
                pdf.cell(25, 8, "Hora", border=1, align="C", fill=True)
                pdf.cell(80, 8, "Notas", border=1, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
                
                pdf.set_font("helvetica", "", 9)
                asist_obra = df_hoy[df_hoy['empleado_id'].isin(emp_obra['empleado_id'])]
                
                if not asist_obra.empty:
                    asist_obra = asist_obra.merge(emp_obra[['empleado_id', 'nombre_completo']], on='empleado_id', how='inner')
                    for i, row in asist_obra.iterrows():
                        nom = limpiar_txt(row['nombre_completo'])
                        nombre = nom[:22] + "..." if len(nom) > 22 else nom
                        
                        tipo = limpiar_txt(row.get('tipo_registro', ''))
                        hora = row['fecha_dt'].strftime('%H:%M') if pd.notna(row.get('fecha_dt')) else ''
                        
                        av_raw = str(row.get('avances', ''))
                        if tipo == "ENTRADA" and (av_raw == "None" or not av_raw):
                            av_raw = "Inicio de turno"
                        av = limpiar_txt(av_raw)
                        avance = av[:40] + "..." if len(av) > 40 else av
                        
                        # Fix seguro para colores alternados
                        if i % 2 == 1: 
                            pdf.set_fill_color(248, 248, 248)
                        else: 
                            pdf.set_fill_color(255, 255, 255)
                            
                        pdf.cell(60, 8, f" {nombre}", border=1, align="L", fill=True)
                        pdf.cell(25, 8, tipo, border=1, align="C", fill=True)
                        pdf.cell(25, 8, hora, border=1, align="C", fill=True)
                        pdf.cell(80, 8, f" {avance}", border=1, align="L", fill=True, new_x="LMARGIN", new_y="NEXT")
                else:
                    pdf.cell(190, 8, "Sin movimientos hoy", border=1, align="C", new_x="LMARGIN", new_y="NEXT")
                
                entradas_hoy = asist_obra[asist_obra['tipo_registro'] == 'ENTRADA']
                emp_con_entrada = entradas_hoy['empleado_id'].unique()
                faltantes_df = emp_obra[~emp_obra['empleado_id'].isin(emp_con_entrada)]
                
                if not faltantes_df.empty:
                    nombres_faltantes = ", ".join(faltantes_df['nombre_completo'].tolist())
                    pdf.set_font("helvetica", "I", 8)
                    pdf.set_text_color(200, 0, 0)
                    pdf.multi_cell(190, 6, limpiar_txt(f"🔴 Faltantes: {nombres_faltantes}"))
                
                pdf.ln(5)
                
            return bytes(pdf.output())

        def generar_pdf_semanal(df_asist, df_emp, fecha_op):
            lunes = fecha_op - timedelta(days=fecha_op.weekday())
            pdf = PDFCorporativo(
                titulo_documento=limpiar_txt(f"Reporte Semanal de Asistencias · {lunes.strftime('%d/%m')} al {fecha_op.strftime('%d/%m')}"),
                empresa_nombre=st.session_state.get("empresa_nombre", "Centro de Mando"),
                color_marca_hex=st.session_state.get("sidebar_color", "#0E1C36"),
                logo_url=st.session_state.get("empresa_logo", "")
            )
            pdf.add_page()
            
            df_sem = df_asist[(df_asist['fecha_dt'].dt.date >= lunes) & (df_asist['fecha_dt'].dt.date <= fecha_op)].copy()
            obras_activas = df_emp[df_emp['estado'] == 'ACTIVO']['obra_actual'].dropna().unique()
            dias_laborables_transcurridos = (fecha_op - lunes).days + 1

            for obra in obras_activas:
                emp_obra = df_emp[(df_emp['obra_actual'] == obra) & (df_emp['estado'] == 'ACTIVO')]
                if emp_obra.empty: continue
                
                pdf.set_font("helvetica", "B", 11)
                pdf.set_text_color(31, 78, 120)
                pdf.cell(0, 10, limpiar_txt(f"🏗️ Obra: {obra}"), align="L", new_x="LMARGIN", new_y="NEXT")
                
                pdf.set_font("helvetica", "B", 9)
                pdf.set_fill_color(235, 235, 235)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(60, 8, "Trabajador", border=1, align="C", fill=True)
                pdf.cell(30, 8, "Dias Asistidos", border=1, align="C", fill=True)
                pdf.cell(30, 8, "Faltas", border=1, align="C", fill=True)
                pdf.cell(70, 8, "Observaciones", border=1, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
                
                pdf.set_font("helvetica", "", 9)
                
                for i, row in enumerate(emp_obra.iterrows()):
                    row_emp = row[1]
                    nom = limpiar_txt(row_emp['nombre_completo'])
                    nombre = nom[:22] + "..." if len(nom) > 22 else nom
                    
                    asist_emp = df_sem[(df_sem['empleado_id'] == row_emp['empleado_id']) & (df_sem['tipo_registro'] == 'ENTRADA')]
                    dias_asistidos = asist_emp['fecha_dt'].dt.date.nunique()
                    faltas = dias_laborables_transcurridos - dias_asistidos
                    
                    obs = "Asistencia perfecta" if faltas == 0 else ("Ausencia total en la semana" if dias_asistidos == 0 else f"Faltó {faltas} dia(s)")
                    
                    # Fix seguro para colores alternados también en la semana
                    if i % 2 == 1: 
                        pdf.set_fill_color(248, 248, 248)
                    else: 
                        pdf.set_fill_color(255, 255, 255)
                        
                    pdf.cell(60, 8, f" {nombre}", border=1, align="L", fill=True)
                    pdf.cell(30, 8, str(dias_asistidos), border=1, align="C", fill=True)
                    pdf.cell(30, 8, str(faltas), border=1, align="C", fill=True)
                    pdf.cell(70, 8, f" {limpiar_txt(obs)}", border=1, align="L", fill=True, new_x="LMARGIN", new_y="NEXT")
                    
                pdf.ln(5)
                
            return bytes(pdf.output())

        # Generación Final del Botón
        if not df_asistencias.empty and not df_empleados.empty:
            if tipo_reporte == "📅 Reporte Diario":
                pdf_bytes = generar_pdf_diario(df_asistencias, df_empleados, fecha_seleccionada)
                label_btn = f"📑 Descargar PDF Diario ({fecha_seleccionada.strftime('%d/%m')})"
                file_name = f"Reporte_Diario_{fecha_seleccionada.strftime('%Y-%m-%d')}.pdf"
            else:
                pdf_bytes = generar_pdf_semanal(df_asistencias, df_empleados, fecha_seleccionada)
                label_btn = f"📑 Descargar PDF Semanal"
                file_name = f"Reporte_Semanal_{fecha_seleccionada.strftime('%Y-%m-%d')}.pdf"
                
            st.download_button(
                label=label_btn,
                data=pdf_bytes,
                file_name=file_name,
                mime="application/pdf",
                use_container_width=True,
                type="primary" # Mantiene el color corporativo de la nube
            )
        else:
            st.button("📑 Generar PDF", disabled=True, use_container_width=True, help="No hay datos suficientes.")

elif menu_opcion == "📸 Galería de Campo":
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

elif menu_opcion == "👥 Directorio de Personal":
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
                            obra_editada != obra_orig):
                            
                            datos_actualizados = {
                                "foto_perfil_url": foto_editada,
                                "nombre_completo": row["nombre_completo"],
                                "telefono": row["telefono"],
                                "rol": row["rol"],
                                "rango": rango_editado,
                                "obra_actual": obra_editada
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

elif menu_opcion == "⚙️ Gestión RH":

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
                emp_elegido = next((e for e in respuesta_todos.data if e["empleado_id"] == id_seleccionado), {})
                if nuevo_estado == "ACTIVO" and not (emp_elegido.get("telefono") or "").strip():
                    # Un ACTIVO sin teléfono rompe los selectores del panel y no se le puede avisar por WhatsApp
                    st.error("❌ No se puede activar a este trabajador porque aún no tiene teléfono registrado.")
                else:
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

    # ==========================================
    # PERSONAL POR COMPLETAR (cargados desde una lista, aún sin todos sus datos)
    # ==========================================
    filas_incompletos = filas_personal_por_completar(respuesta_todos.data or [])

    st.subheader(f"📋 Personal por completar ({len(filas_incompletos)})")
    st.caption("Trabajadores cargados desde una lista de personal a los que todavía les faltan datos. "
               "Aquí puedes corregir sus datos y capturar su teléfono. No registran asistencia hasta que completen "
               "lo que falta por WhatsApp y RH los apruebe en la Sala de Espera.")

    # Resultado del último guardado (sobrevive al st.rerun que refresca la tabla)
    for tipo_mensaje, texto_mensaje in st.session_state.pop("resultado_incompletos", []):
        getattr(st, tipo_mensaje)(texto_mensaje)

    if filas_incompletos:
        # Desplegables: el catálogo vigente más lo que ya tengan puesto (por si una obra se cerró después)
        opciones_puesto, opciones_obra = [ROL_POR_DEFINIR], ["Sin Obra"]
        try:
            opciones_puesto += [p["nombre"] for p in supabase.table("catalogo_puestos").select("nombre").order("id").execute().data]
            opciones_obra += [o["nombre"] for o in supabase.table("catalogo_obras").select("nombre").eq("estado", "ACTIVA").execute().data]
        except Exception:
            pass
        opciones_puesto = list(dict.fromkeys(opciones_puesto + [f["Puesto"] for f in filas_incompletos]))
        opciones_obra = list(dict.fromkeys(opciones_obra + [f["Obra"] for f in filas_incompletos]))

        # La versión cambia en cada guardado para que el editor no arrastre ediciones viejas sobre filas reordenadas
        version_editor = st.session_state.get("version_editor_incompletos", 0)
        df_incompletos = pd.DataFrame(filas_incompletos)
        df_incompletos["Rango"] = df_incompletos["Rango"].replace({"": None})

        df_editado = st.data_editor(
            df_incompletos,
            column_config={
                "ID": st.column_config.TextColumn("ID", disabled=True),
                "Nombre": st.column_config.TextColumn("👤 Nombre"),
                "Teléfono": st.column_config.TextColumn("📱 Teléfono", help="10 dígitos, o +52 y 10 dígitos. Vacío = sin teléfono."),
                "Puesto": st.column_config.SelectboxColumn("🛠️ Puesto", options=opciones_puesto),
                "Rango": st.column_config.SelectboxColumn("🎖️ Rango", options=["Cabo", "Oficial", "Medio", "Ayudante"]),
                "Obra": st.column_config.SelectboxColumn("🏗️ Obra", options=opciones_obra),
                "Le falta": st.column_config.TextColumn("Le falta", disabled=True),
            },
            use_container_width=True,
            hide_index=True,
            key=f"editor_incompletos_{version_editor}"
        )
        st.caption("Capturar un teléfono no manda ningún mensaje: cuando esa persona le escriba al bot desde ese número, "
                   "el bot le pedirá lo que le falte.")

        if st.button("💾 Guardar cambios", key="guardar_incompletos", type="primary"):
            telefonos_ocupados = {e["telefono"]: (e["empleado_id"], e["nombre_completo"])
                                  for e in respuesta_todos.data if e.get("telefono")}
            cambios, errores = cambios_por_completar(filas_incompletos, df_editado.to_dict("records"), telefonos_ocupados)

            if errores:
                for mensaje in errores:
                    st.error(f"❌ {mensaje}")
                st.caption("No se guardó nada. Corrige lo marcado y vuelve a intentarlo.")
            elif not cambios:
                st.info("No se detectaron modificaciones.")
            else:
                resultado, guardados = [], 0
                for emp_id, campos in cambios.items():
                    try:
                        # Solo actualiza si sigue INCOMPLETO (pudo completar sus datos por WhatsApp mientras tanto)
                        res = supabase.table("empleados").update(campos).eq("empleado_id", emp_id).eq("estado", ESTADO_INCOMPLETO).execute()
                        if res.data:
                            guardados += 1
                        else:
                            resultado.append(("warning", f"⚠️ {emp_id} ya no está en esta lista, no se modificó."))
                    except Exception as e:
                        resultado.append(("error", f"❌ No se pudo guardar a {emp_id}: {e}"))
                if guardados:
                    resultado.insert(0, ("success", f"✅ Cambios guardados en {guardados} trabajador(es)."))
                st.session_state["resultado_incompletos"] = resultado
                st.session_state["version_editor_incompletos"] = version_editor + 1
                st.rerun()
    else:
        st.info("No hay personal por completar en este momento.")

    st.divider()

elif menu_opcion == "🏗️ Gestión de Obras":
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

    # ==========================================
    # 🪜 PESTAÑA DE JERARQUÍA Y CUADRILLAS
    # ==========================================
elif menu_opcion == "🪜 Jerarquía y Cuadrillas":
    st.markdown("### 🪜 Jerarquía y Cuadrillas")
    st.caption(
        "Define quién es Director, quién es Encargado/Jefe de Cuadrilla, y qué trabajadores "
        "están a cargo de cada Encargado. El Director ve a toda la operación y cada Encargado "
        "solo a su cuadrilla. Aquí solo se arma la estructura: lo que cada quien puede hacer en el bot "
        "(recibir el PDF semanal, escribir MI CUADRILLA, etc.) se da en 🔐 Permisos y Accesos. "
        "Al nombrar a alguien Director o Encargado se le agregan solos los permisos de su rol."
    )

    if st.session_state.get("jerarquia_mensaje"):
        st.success(st.session_state.pop("jerarquia_mensaje"))

    if "jerarquia" not in df_empleados.columns:
        st.warning(
            "⚠️ Todavía no existe la columna 'jerarquia' en la base de datos. "
            "Corre primero la migración SQL en el Editor SQL de Supabase (ver plan de cambios)."
        )
    elif df_empleados.empty:
        st.info("No hay empleados registrados todavía.")
    else:
        df_activos_jer = df_empleados[df_empleados["estado"] == "ACTIVO"].copy()
        df_activos_jer["jerarquia"] = df_activos_jer.get("jerarquia", pd.Series(dtype=object)).fillna("TRABAJADOR")
        if "supervisor_id" not in df_activos_jer.columns:
            df_activos_jer["supervisor_id"] = None
        df_activos_jer["opcion_selector"] = df_activos_jer["nombre_completo"] + " (" + df_activos_jer["telefono"].fillna("sin teléfono") + ")"

        sin_acceso_cuadrilla = [
            f["nombre_completo"] for f in df_activos_jer.to_dict("records")
            if f["jerarquia"] in ("DIRECTOR", "ENCARGADO") and MI_CUADRILLA not in permisos_de(f)
        ]
        if sin_acceso_cuadrilla:
            st.warning(
                "⚠️ Estas personas son Director o Encargado pero todavía no pueden escribir *MI CUADRILLA* "
                f"en el bot: **{', '.join(sin_acceso_cuadrilla)}**. Dales el permiso «Consulta su cuadrilla» "
                "en 🔐 Permisos y Accesos."
            )

        st.subheader("1️⃣ Director")
        opciones_todas = df_activos_jer["opcion_selector"].tolist()
        directores_actuales = df_activos_jer[df_activos_jer["jerarquia"] == "DIRECTOR"]["opcion_selector"].tolist()
        directores_seleccionados = st.multiselect(
            "Director(es) — ven toda la operación:",
            options=opciones_todas, default=directores_actuales, key="sel_directores"
        )

        st.subheader("2️⃣ Encargados / Jefes de Cuadrilla")
        opciones_sin_director = df_activos_jer[~df_activos_jer["opcion_selector"].isin(directores_seleccionados)]["opcion_selector"].tolist()
        encargados_actuales_jer = [o for o in df_activos_jer[df_activos_jer["jerarquia"] == "ENCARGADO"]["opcion_selector"].tolist() if o in opciones_sin_director]
        encargados_seleccionados_jer = st.multiselect(
            "Encargado(s) / Jefe(s) de Cuadrilla:",
            options=opciones_sin_director, default=encargados_actuales_jer, key="sel_encargados_jer"
        )

        st.divider()
        st.subheader("3️⃣ Arma las Cuadrillas")
        st.caption("Por cada Encargado, selecciona qué trabajadores están bajo su cargo (sin importar la obra).")

        ids_directores_sel = df_activos_jer[df_activos_jer["opcion_selector"].isin(directores_seleccionados)]["empleado_id"].tolist()
        ids_encargados_sel = df_activos_jer[df_activos_jer["opcion_selector"].isin(encargados_seleccionados_jer)]["empleado_id"].tolist()
        df_trabajadores_disp = df_activos_jer[~df_activos_jer["empleado_id"].isin(ids_directores_sel + ids_encargados_sel)]
        opciones_trabajadores = df_trabajadores_disp["opcion_selector"].tolist()

        cuadrillas_asignadas = {}  # empleado_id del trabajador -> empleado_id del encargado

        if not encargados_seleccionados_jer:
            st.info("Selecciona al menos un Encargado arriba para poder armar su cuadrilla.")
        else:
            for opcion_enc in encargados_seleccionados_jer:
                fila_enc = df_activos_jer[df_activos_jer["opcion_selector"] == opcion_enc].iloc[0]
                id_enc = fila_enc["empleado_id"]

                default_cuadrilla = df_trabajadores_disp[df_trabajadores_disp["supervisor_id"] == id_enc]["opcion_selector"].tolist()

                seleccion = st.multiselect(
                    f"👷 Cuadrilla de {fila_enc['nombre_completo']}:",
                    options=opciones_trabajadores,
                    default=default_cuadrilla,
                    key=f"cuadrilla_{id_enc}"
                )
                for opcion_trab in seleccion:
                    id_trab = df_trabajadores_disp[df_trabajadores_disp["opcion_selector"] == opcion_trab].iloc[0]["empleado_id"]
                    cuadrillas_asignadas[id_trab] = id_enc

        st.divider()
        if st.button("💾 Guardar Jerarquía y Cuadrillas", type="primary"):
            try:
                permisos_otorgados = []   # (nombre, permisos nuevos) para avisar qué se les dio
                for _, fila in df_activos_jer.iterrows():
                    emp_id = fila["empleado_id"]
                    if emp_id in ids_directores_sel:
                        nueva_jerarquia = "DIRECTOR"
                    elif emp_id in ids_encargados_sel:
                        nueva_jerarquia = "ENCARGADO"
                    else:
                        nueva_jerarquia = "TRABAJADOR"

                    nuevo_supervisor = cuadrillas_asignadas.get(emp_id)

                    actualizacion = {"jerarquia": nueva_jerarquia, "supervisor_id": nuevo_supervisor}

                    cambio_jerarquia = nueva_jerarquia != fila["jerarquia"]
                    cambio_supervisor = nuevo_supervisor != fila.get("supervisor_id")

                    # Solo al CAMBIAR de rol se le agregan los permisos de ese rol (nunca se quitan solos),
                    # así un permiso que se le quitó a mano en "🔐 Permisos y Accesos" no se le devuelve.
                    if cambio_jerarquia and "permisos" in df_activos_jer.columns:
                        permisos_antes = permisos_de(fila)
                        permisos_despues = permisos_al_cambiar_de_rol(permisos_antes, fila["jerarquia"], nueva_jerarquia)
                        if permisos_despues != permisos_antes:
                            actualizacion["permisos"] = sorted(permisos_despues)
                            permisos_otorgados.append((fila["nombre_completo"], permisos_despues - permisos_antes))

                    if cambio_jerarquia or cambio_supervisor:
                        supabase.table("empleados").update(actualizacion).eq("empleado_id", emp_id).execute()

                mensaje = "✅ Jerarquía y cuadrillas guardadas correctamente."
                for nombre, nuevos in permisos_otorgados:
                    mensaje += f"\n\n- **{nombre}** recibió: " + ", ".join(POR_CODIGO[c].nombre for c in sorted(nuevos))
                st.session_state["jerarquia_mensaje"] = mensaje
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al guardar: {e}")

        st.divider()
        st.subheader("📋 Resumen actual")
        mapa_nombres = df_activos_jer.set_index("empleado_id")["nombre_completo"].to_dict()
        df_resumen = df_activos_jer[["nombre_completo", "jerarquia", "supervisor_id", "obra_actual"]].copy()
        df_resumen["supervisor_id"] = df_resumen["supervisor_id"].map(mapa_nombres)
        st.dataframe(
            df_resumen.rename(columns={
                "nombre_completo": "Nombre", "jerarquia": "Jerarquía",
                "supervisor_id": "Encargado Asignado", "obra_actual": "Obra"
            }),
            use_container_width=True, hide_index=True
        )

    # ==========================================
    # 🔐 PESTAÑA DE PERMISOS Y ACCESOS
    # ==========================================
elif menu_opcion == "🔐 Permisos y Accesos":
    render_permisos(supabase, df_empleados, obtener_config_alertas().get("hora_corte_salida", "18:00"))

    # ==========================================
    # ⚙️ PESTAÑA DE CONFIGURACIÓN GENERAL
    # ==========================================
elif menu_opcion == "⚙️ Configuración":
    st.header("⚙️ Configuración General del Sistema")
    st.caption("Administra las reglas de negocio y los horarios del bot. Quién recibe avisos y reportes se define en 🔐 Permisos y Accesos.")
    st.divider()

    # ==========================================
    # NUEVO: BRANDING CON SUBIDA A LA NUBE
    # ==========================================
    st.subheader("🏢 Identidad de Marca (Pantalla de Inicio)")
    st.caption("Personaliza el nombre, color y logotipo. Estos se guardarán permanentemente en la nube.")
    
    with st.form("form_branding", clear_on_submit=True):
        col_m1, col_m2 = st.columns(2)
        
        with col_m1:
            nuevo_nombre = st.text_input("Nombre de la Empresa", value=st.session_state.get("empresa_nombre", ""))
            nuevo_color = st.color_picker("🎨 Color Corporativo", value=st.session_state.get("sidebar_color", "#0E1C36"))
            
        with col_m2:
            nuevo_logo_file = st.file_uploader("Subir Logotipo desde tu PC (JPG/PNG)", type=["jpg", "jpeg", "png"])
            st.caption("Proporción recomendada 1:1 (Cuadrado)")
            
        btn_guardar_marca = st.form_submit_button("💾 Guardar Identidad de Marca", type="primary")
        
        if btn_guardar_marca:
            with st.spinner("Guardando configuración en la nube..."):
                try:
                    # Mantenemos el logo actual por si el usuario no sube uno nuevo
                    url_logo_final = st.session_state.get("empresa_logo", "")
                    
                    # 1. Si subió una imagen, la guardamos en Supabase Storage
                    if nuevo_logo_file is not None:
                        file_bytes = nuevo_logo_file.getvalue()
                        # Nombre único para no sobreescribir usando un timestamp
                        marca_tiempo = datetime.now().strftime('%Y%m%d%H%M%S')
                        ruta_archivo = f"logo_{marca_tiempo}_{nuevo_logo_file.name}"
                        
                        # Usamos el bucket "fotos_perfil" que ya configuramos en sesiones anteriores
                        supabase.storage.from_("fotos_perfil").upload(
                            file=file_bytes,
                            path=ruta_archivo,
                            file_options={"content-type": nuevo_logo_file.type}
                        )
                        url_logo_final = supabase.storage.from_("fotos_perfil").get_public_url(ruta_archivo)
                        
                    # 2. Guardamos texto, color y URL de foto en la tabla "configuracion"
                    supabase.table("configuracion").update({
                        "empresa_nombre": nuevo_nombre,
                        "empresa_logo": url_logo_final,
                        "color_sidebar": nuevo_color
                    }).eq("id", 1).execute()
                    
                    # 3. Actualizamos la memoria actual de Streamlit
                    st.session_state["empresa_nombre"] = nuevo_nombre
                    st.session_state["empresa_logo"] = url_logo_final
                    st.session_state["sidebar_color"] = nuevo_color
                    
                    st.success("✅ Identidad corporativa actualizada permanentemente.")
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error al guardar en la nube: {str(e)}")
                    
    st.divider()
    
    st.subheader("🔔 Sistema de Alarma")
    st.caption("Configura a qué hora el bot debe avisar sobre los trabajadores que faltan de registrar su Entrada o Salida. "
               "A la hora de salida también se cierran solos los turnos que sigan abiertos.")
    
    # Cargamos la configuración actual desde la base de datos
    if "config_alertas" not in st.session_state:
        st.session_state["config_alertas"] = obtener_config_alertas()
        
    config = st.session_state["config_alertas"]
    
    # Extraemos las horas para que Streamlit las entienda
    try:
        hora_ent_obj = datetime.strptime(config.get("hora_corte_entrada", "08:15"), "%H:%M").time()
        hora_sal_obj = datetime.strptime(config.get("hora_corte_salida", "18:00"), "%H:%M").time()
    except Exception:
        hora_ent_obj = datetime.strptime("08:15", "%H:%M").time()
        hora_sal_obj = datetime.strptime("18:00", "%H:%M").time()
        
    col_alerta1, col_alerta2 = st.columns(2)

    with col_alerta1:
        hora_entrada_input = st.time_input(
            "⏰ Límite de Entrada", value=hora_ent_obj,
            help="A esta hora el bot le avisa a quien tenga el permiso «Control de asistencia».")
    with col_alerta2:
        hora_salida_input = st.time_input(
            "⏰ Límite de Salida", value=hora_sal_obj,
            help="A esta hora el bot avisa a quien tenga «Control de asistencia» y cierra solo los "
                 "turnos que sigan abiertos.")

    dias_aviso_input = st.multiselect(
        "📅 Días en que avisa", DIAS_SEMANA,
        default=[DIAS_SEMANA[d] for d in dias_de_aviso(config.get("dias_aviso"))],
        help="Solo esos días el bot manda los recordatorios de entrada y salida. "
             "El cierre automático de turnos corre todos los días.")

    st.info("👷 Quién recibe estos avisos y quién puede usar AVISAR se elige en **🔐 Permisos y Accesos**.")

    # Botón para guardar los cambios
    if st.button("💾 Guardar Horarios", type="primary"):
        str_entrada = hora_entrada_input.strftime("%H:%M")
        str_salida = hora_salida_input.strftime("%H:%M")
        dias_guardar = [DIAS_SEMANA.index(d) for d in dias_aviso_input]

        if not dias_guardar:
            st.error("Elige al menos un día para los avisos.")
        elif actualizar_config_alertas(str_entrada, str_salida, dias_guardar):
            st.session_state["config_alertas"] = {
                "hora_corte_entrada": str_entrada,
                "hora_corte_salida": str_salida,
                "dias_aviso": dias_a_texto(dias_guardar)
            }
            st.success("✅ ¡Horarios guardados!")
            st.rerun()

    st.divider()

    # ==========================================
    # 📄 HORARIO DEL REPORTE SEMANAL AL DIRECTOR
    # ==========================================
    st.subheader("📄 Reporte Semanal del Director")
    st.caption(
        "Configura qué día y a qué hora se manda automáticamente el PDF de asistencia "
        "semanal a quien tenga el permiso «Recibe el reporte semanal» en 🔐 Permisos y Accesos."
    )

    if "config_reporte_semanal" not in st.session_state:
        st.session_state["config_reporte_semanal"] = obtener_config_reporte_semanal()

    config_reporte = st.session_state["config_reporte_semanal"]

    dias_semana_opciones = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_guardado_idx = config_reporte.get("dia_reporte_semanal")
    if dia_guardado_idx is None or not (0 <= dia_guardado_idx <= 6):
        dia_guardado_idx = 4  # Viernes por defecto

    try:
        hora_reporte_obj = datetime.strptime(config_reporte.get("hora_reporte_semanal") or "11:00", "%H:%M").time()
    except Exception:
        hora_reporte_obj = datetime.strptime("11:00", "%H:%M").time()

    col_rep1, col_rep2 = st.columns(2)
    with col_rep1:
        dia_reporte_input = st.selectbox("📅 Día de la semana", dias_semana_opciones, index=dia_guardado_idx)
    with col_rep2:
        hora_reporte_input = st.time_input("⏰ Hora de envío", value=hora_reporte_obj)

    if st.button("💾 Guardar Horario del Reporte Semanal", type="primary"):
        dia_guardar_idx = dias_semana_opciones.index(dia_reporte_input)
        hora_guardar = hora_reporte_input.strftime("%H:%M")

        if actualizar_config_reporte_semanal(dia_guardar_idx, hora_guardar):
            st.session_state["config_reporte_semanal"] = {
                "dia_reporte_semanal": dia_guardar_idx,
                "hora_reporte_semanal": hora_guardar
            }
            st.success(f"✅ El reporte semanal ahora se enviará cada *{dia_reporte_input}* a las *{hora_guardar}*.")
            st.rerun()

    st.divider()

    # ==========================================
    # NUEVO: BÓVEDA DE SEGURIDAD (BACKUP)
    # ==========================================
    st.subheader("🗄️ Respaldo y Seguridad de Datos")
    st.caption("Descarga una copia completa de toda la base de datos histórica. Ideal para auditorías profundas o copias de seguridad mensuales.")

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        datos_escritos = False
        
        # Ahora usamos los dataframes COMPLETOS (df_asistencias), no los filtrados (df_asistencias_hoy)
        if not df_asistencias.empty:
            df_excel_asist = df_asistencias.drop(columns=['fecha_dt'], errors='ignore')
            aplicar_formato_hoja(writer, df_excel_asist, 'Histórico Asistencias', color_header=st.session_state.get("sidebar_color", "#0E1C36"))
            datos_escritos = True
            
        if not df_incidentes.empty:
            df_excel_inc = df_incidentes.drop(columns=['fecha_dt'], errors='ignore')
            aplicar_formato_hoja(writer, df_excel_inc, 'Histórico Incidentes', color_header=st.session_state.get("sidebar_color", "#0E1C36"))
            datos_escritos = True
            
        if not df_empleados.empty:
            aplicar_formato_hoja(writer, df_empleados, 'Directorio Completo', color_header=st.session_state.get("sidebar_color", "#0E1C36"))
            datos_escritos = True
            
        if not datos_escritos:
            df_vacio = pd.DataFrame({"Aviso": ["La base de datos está completamente vacía."]})
            aplicar_formato_hoja(writer, df_vacio, 'Sin Datos', color_header=st.session_state.get("sidebar_color", "#0E1C36"))

    col_btn_backup, col_vacia = st.columns([4, 6])
    with col_btn_backup:
        st.download_button(
            label="💾 Descargar Copia de Seguridad Total",
            data=buffer.getvalue(),
            file_name=f"Backup_Histórico_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )


    
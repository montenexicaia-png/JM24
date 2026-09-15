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
from datetime import datetime, date, timedelta

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
    """Obtiene los horarios de corte y el número del jefe desde Supabase"""
    try:
        respuesta = supabase.table("configuracion").select("hora_corte_entrada, hora_corte_salida, telefono_encargado").eq("id", 1).execute()
        if respuesta.data:
            return respuesta.data[0]
        return {"hora_corte_entrada": "08:15", "hora_corte_salida": "18:00", "telefono_encargado": ""}
    except Exception as e:
        return {"hora_corte_entrada": "08:15", "hora_corte_salida": "18:00", "telefono_encargado": ""}

def actualizar_config_alertas(entrada, salida, telefono):
    """Guarda los nuevos horarios y número en la base de datos"""
    try:
        supabase.table("configuracion").update({
            "hora_corte_entrada": entrada,
            "hora_corte_salida": salida,
            "telefono_encargado": telefono
        }).eq("id", 1).execute()
        return True
    except Exception as e:
        st.error(f"Error al guardar configuración de alertas: {e}")
        return False

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
                    registro_entrada = asistio.sort_values("fecha_dt").iloc[0]
                    hora_entrada = registro_entrada["fecha_dt"]
                    str_entrada = hora_entrada.strftime("%H:%M") # Formato 09:00
                    
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
                        str_salida = hora_salida.strftime("%H:%M") # Formato 18:00
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
                texto_asistencias = df_asist_ia[["empleado_id", "tipo_registro", "fecha_hora", "avances", "pendientes"]].to_string() if not df_asist_ia.empty else "Sin registros de asistencia en este periodo."
                texto_incidentes = df_incid_ia[["empleado_id", "descripcion", "estado", "fecha_hora"]].to_string() if not df_incid_ia.empty else "Sin incidentes reportados en este periodo."

                st.write("⚙️ Estructurando parámetros de análisis temporal...")
                # Prompts dinámicos según el alcance elegido
                if alcance_auditoria == "📅 Reporte Diario":
                    instrucciones = f"""
                    Actúa como un Supervisor de Obra. Analiza estrictamente los datos del día {fecha_fin.strftime('%d/%m/%Y')}.
                    Genera un reporte conciso con viñetas y usa semáforos visuales (🟢 Normal, 🟡 Precaución, 🔴 Riesgo).
                    Estructura obligatoria:
                    1. **Estado General del Día:** Resumen en 2 líneas.
                    2. **Avances Destacados:** Qué se logró hoy.
                    3. **Alertas y Riesgos:** Anomalías o urgencias (Menciona el ID del empleado).
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
                        pdf = FPDF()
                        pdf.add_page()
                        
                        pdf.set_font("helvetica", "B", 16)
                        pdf.cell(0, 10, f"Auditoria de Obra - {tipo_auditoria}", align="C", new_x="LMARGIN", new_y="NEXT")
                        
                        pdf.set_font("helvetica", "I", 10)
                        fecha_impresion = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                        pdf.cell(0, 10, f"Periodo analizado: {rango_texto} | Generado: {fecha_impresion}", align="C", new_x="LMARGIN", new_y="NEXT")
                        pdf.ln(5)
                        
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

        # Ajuste de fechas y turno
        df_mostrar["fecha_dt"] = pd.to_datetime(df_mostrar["fecha_dt"], errors='coerce')
        df_mostrar["Hora Registro"] = df_mostrar["fecha_dt"].dt.strftime("%d/%m/%Y %H:%M")
        df_mostrar["Ecosistema Turno"] = df_mostrar.apply(
            lambda r: "🌙 Nocturno" if r["fecha_dt"].date() > fecha_seleccionada else "☀️ Ordinario", 
            axis=1
        )
        
        # Validamos si la columna 'ubicacion' existe
        cols_a_mostrar = ["empleado_id", "tipo_registro", "Hora Registro", "Ecosistema Turno"]
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
            "empleado_id": st.column_config.TextColumn("ID", width="small"),
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

    col_exp1, col_exp2 = st.columns(2)

    with col_exp1:
        # Reporte Matricial
        df_matriz_semanal, fechas_cabecera = generar_matriz_semanal(fecha_seleccionada, df_empleados, df_asistencias)
        
        if not df_matriz_semanal.empty:
            excel_matriz_bytes = exportar_matriz_excel(df_matriz_semanal, fechas_cabecera)
            st.download_button(
                label="📊 Descargar Matriz Semanal (Excel)",
                data=excel_matriz_bytes,
                file_name=f"Matriz_Asistencia_{fecha_seleccionada.strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary"
            )
        else:
            st.button("📊 Matriz Semanal No Disponible", disabled=True, use_container_width=True)

    with col_exp2:
        # Corregido: Usamos df_asistencias_hoy en lugar del global
        if not df_asistencias_hoy.empty and not df_empleados.empty:
            
            # Cruzamos los datos para obtener el nombre del trabajador
            df_pdf = df_asistencias_hoy.merge(
                df_empleados[["empleado_id", "nombre_completo"]], 
                on="empleado_id", 
                how="left"
            )
            df_pdf["nombre_completo"] = df_pdf["nombre_completo"].fillna("Usuario Desconocido")

            def generar_pdf_asistencias(df, fecha_operativa):
                def texto_seguro(texto):
                    return str(texto).encode('latin-1', errors='replace').decode('latin-1')

                pdf = FPDF()
                pdf.add_page()
                
                # Título con el color de la marca y la fecha real de la operación
                pdf.set_font("helvetica", "B", 16)
                pdf.cell(0, 10, f"Reporte Diario de Asistencias - {fecha_operativa}", align="C", new_x="LMARGIN", new_y="NEXT")
                
                pdf.set_font("helvetica", "I", 10)
                fecha_actual = datetime.now().strftime('%d/%m/%Y %H:%M')
                nombre_emp = st.session_state.get("empresa_nombre", "NeuroMont")
                pdf.cell(0, 10, f"Generado por {nombre_emp} | Impreso: {fecha_actual}", align="C", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(5)
                
                # Encabezados con anchos optimizados (Total A4: 190mm)
                pdf.set_font("helvetica", "B", 10)
                pdf.cell(60, 10, "Trabajador", border=1, align="C")      # Más ancho para el nombre
                pdf.cell(25, 10, "Tipo", border=1, align="C")
                pdf.cell(25, 10, "Hora", border=1, align="C")            # Solo necesitamos la hora
                pdf.cell(80, 10, "Notas / Avance", border=1, align="C", new_x="LMARGIN", new_y="NEXT")
                
                # Inyección de Filas
                pdf.set_font("helvetica", "", 9)
                for _, row in df.iterrows():
                    nombre_completo = texto_seguro(row.get('nombre_completo', ''))
                    # Acortamos el nombre a unos 25 caracteres para que no rompa la celda
                    nombre_corto = nombre_completo[:25] + "..." if len(nombre_completo) > 25 else nombre_completo
                    
                    tipo = texto_seguro(row.get('tipo_registro', ''))
                    
                    # Extraer solo la hora (Ej: 08:15)
                    fecha_raw = str(row.get('fecha_hora', ''))
                    hora_limpia = fecha_raw[11:16] if len(fecha_raw) > 15 else fecha_raw
                    
                    avance = str(row.get('avances', ''))
                    if avance == "None" or not avance:
                        avance = "Inicio de turno" if tipo == "ENTRADA" else "Sin comentarios"
                    avance = texto_seguro(avance)
                    avance = avance[:45] + "..." if len(avance) > 45 else avance
                    
                    pdf.cell(60, 10, f" {nombre_corto}", border=1, align="L")
                    pdf.cell(25, 10, tipo, border=1, align="C")
                    pdf.cell(25, 10, hora_limpia, border=1, align="C")
                    pdf.cell(80, 10, f" {avance}", border=1, align="L", new_x="LMARGIN", new_y="NEXT")
                    
                return bytes(pdf.output())

            fecha_str = fecha_seleccionada.strftime('%d/%m/%Y')
            pdf_asistencias_bytes = generar_pdf_asistencias(df_pdf, fecha_str)
            
            st.download_button(
                label=f"📑 Generar PDF ({fecha_str})",
                data=pdf_asistencias_bytes,
                file_name=f"Reporte_Asistencias_{fecha_seleccionada.strftime('%Y-%m-%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary"
            )
        else:
            st.button("📑 Generar PDF", disabled=True, use_container_width=True, help="Aún no hay registros en este día.")

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
    # ⚙️ PESTAÑA DE CONFIGURACIÓN GENERAL
    # ==========================================
elif menu_opcion == "⚙️ Configuración":
    st.header("⚙️ Configuración General del Sistema")
    st.caption("Administra las reglas de negocio, horarios y números de autorización del bot.")
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
    
    st.subheader("🔔 Sistema de Alarma y Autorización")
    st.caption("Configura a qué hora el bot debe avisar sobre los trabajadores que faltan de registrar su Entrada o Salida.")
    
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
        
    # --- NUEVO: Selector de Encargados de Obra ---
    if not df_empleados.empty:
        df_activos_selector = df_empleados[df_empleados["estado"] == "ACTIVO"].copy()
    else:
        df_activos_selector = pd.DataFrame()
    
    if "es_encargado" not in df_activos_selector.columns:
        df_activos_selector["es_encargado"] = False
    
    # Opciones tipo "Nombre (teléfono)" para no confundir nombres repetidos
    df_activos_selector["opcion_selector"] = df_activos_selector["nombre_completo"] + " (" + df_activos_selector["telefono"] + ")"
    opciones_encargados = df_activos_selector["opcion_selector"].tolist()
    encargados_actuales = df_activos_selector[df_activos_selector["es_encargado"] == True]["opcion_selector"].tolist()
    
    # Mostramos los campos alineados
    col_alerta1, col_alerta2 = st.columns(2)
    
    with col_alerta1:
        hora_entrada_input = st.time_input("⏰ Límite de Entrada", value=hora_ent_obj)
    with col_alerta2:
        hora_salida_input = st.time_input("⏰ Límite de Salida", value=hora_sal_obj)
    
    # --- NUEVO: Magia CSS para convertir el MultiSelect en una lista vertical de tarjetas ---
    color_actual = st.session_state.get("sidebar_color", "#0E1C36")
    st.markdown(f"""
        <style>
        /* Forzamos a que cada "chip" (etiqueta) del multiselect ocupe el 100% del ancho */
        div[data-testid="stMultiSelect"] span[data-baseweb="tag"] {{
            display: flex !important;
            width: 100% !important;
            justify-content: space-between !important;
            margin-bottom: 8px !important;
            padding: 8px 12px !important;
            border-left: 5px solid {color_actual} !important;
            background-color: #FFFFFF !important;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05) !important;
            border-radius: 6px !important;
        }}
        
        /* Estilizamos el texto dentro del chip para que sea más legible */
        div[data-testid="stMultiSelect"] span[data-baseweb="tag"] span {{
            font-size: 15px !important;
            color: #2C3E50 !important;
            font-weight: 600 !important;
        }}
        
        /* Ajustamos el botón de cerrar (la "X") */
        div[data-testid="stMultiSelect"] span[data-baseweb="tag"] svg {{
            fill: #7F8C8D !important;
            width: 18px !important;
            height: 18px !important;
        }}
        </style>
    """, unsafe_allow_html=True)

    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    
    encargados_seleccionados = st.multiselect(
        "👷 Lista de Encargados Autorizados (reciben alertas):",
        options=opciones_encargados,
        default=encargados_actuales,
        help="Busca y selecciona al personal. Cada uno aparecerá en su propio renglón de forma elegante."
    )
        
    # Botón para guardar los cambios
    if st.button("💾 Guardar Configuración de Alertas", type="primary"):
        str_entrada = hora_entrada_input.strftime("%H:%M")
        str_salida = hora_salida_input.strftime("%H:%M")
        
        telefonos_seleccionados = []
        ids_seleccionados = []
        for opcion in encargados_seleccionados:
            fila = df_activos_selector[df_activos_selector["opcion_selector"] == opcion].iloc[0]
            telefonos_seleccionados.append(fila["telefono"])
            ids_seleccionados.append(fila["empleado_id"])
        
        telefono_guardar = ",".join(telefonos_seleccionados)
        
        try:
            # Marcamos como encargado (y le limpiamos la obra) a los seleccionados
            for emp_id in ids_seleccionados:
                supabase.table("empleados").update({
                    "es_encargado": True,
                    "obra_actual": None
                }).eq("empleado_id", emp_id).execute()
            
            # A quien ya NO esté seleccionado pero antes sí lo era, lo regresamos a false
            ids_anteriores = df_activos_selector[df_activos_selector["es_encargado"] == True]["empleado_id"].tolist()
            for emp_id in ids_anteriores:
                if emp_id not in ids_seleccionados:
                    supabase.table("empleados").update({"es_encargado": False}).eq("empleado_id", emp_id).execute()
        except Exception as e:
            st.error(f"❌ Error al actualizar encargados: {e}")
        
        if actualizar_config_alertas(str_entrada, str_salida, telefono_guardar):
            st.session_state["config_alertas"] = {
                "hora_corte_entrada": str_entrada, 
                "hora_corte_salida": str_salida, 
                "telefono_encargado": telefono_guardar
            }
            st.success("✅ ¡Configuración guardada!")
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


    
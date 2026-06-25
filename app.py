import streamlit as st
import pandas as pd
import google.generativeai as genai
from supabase import create_client, Client
import datetime
from fpdf import FPDF
import io
import plotly.express as px

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

# ¡ESTA LÍNEA ES LA QUE FALTA! Creamos el espacio para los dos botones
col_exp1, col_exp2 = st.columns([2, 8])

with col_exp1:
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
            
    # Botón nativo de descarga
    st.download_button(
        label="📄 Exportar Excel",
        data=buffer.getvalue(),
        file_name=f"Base_Datos_Obra_{fecha_seleccionada.strftime('%Y-%m-%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Descargar registros completos en formato .xlsx"
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

tab_tabla, tab_galeria, tab_directorio, tab_rh = st.tabs(["📋 Tabla de Asistencias", "📸 Galería de Campo", "👥 Directorio de Personal", "⚙️ Gestión RH"])

with tab_tabla:
    if not df_asistencias_hoy.empty:
        df_mostrar = df_asistencias_hoy.copy()
        
        # Marcamos visualmente si la fecha real del mensaje es del día siguiente (+1) en la madrugada
        df_mostrar["Ecosistema Turno"] = df_mostrar.apply(
            lambda r: "🌙 Turno Nocturno" if pd.to_datetime(r["fecha_hora"]).date() > fecha_seleccionada else "☀️ Turno Ordinario", 
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
        cols_asistencia = ["empleado_id", "fecha_hora", "tipo_registro", "foto_url"]
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
                fecha_limpia = str(row['fecha_hora'])[:16].replace('T', ' ')
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
    st.markdown("### 👥 Control de Plantilla")
    
    if not df_empleados.empty:
        # Filtramos a los trabajadores según su estado
        df_activos = df_empleados[df_empleados["estado"] == "ACTIVO"]
        df_inactivos = df_empleados[df_empleados["estado"] == "INACTIVO"]
        
        # --- TABLA DE ACTIVOS ---
        st.subheader(f"🟢 Personal Activo ({len(df_activos)})")
        if not df_activos.empty:
            # Ya no mostramos la columna 'estado' porque es obvio que aquí todos son activos
            st.dataframe(df_activos[["empleado_id", "nombre_completo", "telefono", "rol"]], use_container_width=True, hide_index=True)
        else:
            st.info("No hay personal activo registrado en este momento.")
            
        st.divider()
        
        # --- TABLA DE BAJAS (Archivo Muerto) ---
        st.subheader(f"🔴 Histórico de Bajas ({len(df_inactivos)})")
        if not df_inactivos.empty:
            st.dataframe(df_inactivos[["empleado_id", "nombre_completo", "telefono", "rol"]], use_container_width=True, hide_index=True)
        else:
            st.info("El archivo de bajas está limpio.")
            
    else:
        st.info("No hay empleados registrados en el sistema.")

with tab_rh:
    st.markdown("### 🛠️ Panel de Recursos Humanos")
    st.caption("Administra las altas y bajas de los trabajadores de forma segura.")

    # Dividimos la pantalla en dos columnas: Izquierda (Altas) y Derecha (Bajas)
    col_alta, col_baja = st.columns(2)

    # --- SECCIÓN DE ALTA ---
    with col_alta:
        st.subheader("🟢 Alta de Nuevo Empleado")
        
        # --- NUEVO: Mostrar mensaje de éxito si existe en la memoria caché ---
        if "mensaje_alta" in st.session_state:
            st.success(st.session_state["mensaje_alta"])
            del st.session_state["mensaje_alta"] # Lo borramos de inmediato para que no se quede pegado siempre

        # El truco de UX: agregamos clear_on_submit=True
        with st.form("form_alta", clear_on_submit=True):
            nuevo_id = st.text_input("ID de Empleado (Ej. EMP-005)")
            nuevo_nombre = st.text_input("Nombre Completo")
            nuevo_telefono = st.text_input("Teléfono (con código de país, ej. +525512345678)")
            nuevo_rol = st.selectbox("Rol en Obra", ["Maestro de Obra", "Albañil", "Peón", "Arquitecta", "Ingeniero", "Seguridad", "Otro"])
            
            btn_alta = st.form_submit_button("Registrar Empleado", type="primary")
            
            if btn_alta:
                if nuevo_id and nuevo_nombre and nuevo_telefono:
                    try:
                        # Insertamos directamente en la tabla de Supabase
                        supabase.table("empleados").insert({
                            "empleado_id": nuevo_id,
                            "nombre_completo": nuevo_nombre,
                            "telefono": nuevo_telefono,
                            "rol": nuevo_rol,
                            "estado": "ACTIVO"
                        }).execute()
                        
                        # Guardamos el mensaje en la memoria antes de forzar el reinicio
                        st.session_state["mensaje_alta"] = f"✅ {nuevo_nombre} registrado correctamente."
                        st.rerun() # Forzamos la recarga de la página
                        
                    except Exception as e:
                        st.error(f"❌ Error al registrar en la base de datos: {str(e)}")
                else:
                    st.warning("⚠️ Todos los campos de texto son obligatorios.")

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
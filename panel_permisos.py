"""
Módulo del panel «🔐 Permisos y Accesos»: quién puede hacer qué en el bot de WhatsApp.

Vive aparte de app.py para poder probarse sin el login (ver test_panel_permisos.py). Recibe
el cliente de Supabase y los datos ya cargados; no crea conexiones propias.
"""
import streamlit as st
import pandas as pd
from permisos import (
    POR_CODIGO, REPORTE_SEMANAL, CONTROL_ASISTENCIA, RECIBIR_URGENCIAS, ENVIAR_AVISOS,
    MI_CUADRILLA, FOTO_GRUPAL, REGISTRO_CON_FOTO,
    permisos_de, calcular_cambios, texto_menu_inicio, texto_menu_en_turno,
    comandos_especiales, que_puede_hacer,
)

GRUPOS = (
    ("📬 Reciben avisos y reportes", (REPORTE_SEMANAL, CONTROL_ASISTENCIA, RECIBIR_URGENCIAS)),
    ("🛠️ Pueden hacer más en el bot", (ENVIAR_AVISOS, MI_CUADRILLA, FOTO_GRUPAL)),
)


def _estilo_multiselect():
    color = st.session_state.get("sidebar_color", "#0E1C36")
    st.markdown(f"""
        <style>
        div[data-testid="stMultiSelect"] [data-baseweb="tag"] {{
            background-color: #F8F9FA !important;
            border: 1px solid #E2E8F0 !important;
            border-left: 4px solid {color} !important;
            border-radius: 6px !important;
            padding: 2px 8px !important;
            margin: 4px !important;
        }}
        div[data-testid="stMultiSelect"] [data-baseweb="tag"] span {{
            color: #2C3E50 !important;
            font-weight: 600 !important;
            font-size: 14px !important;
            white-space: normal !important;
        }}
        div[data-testid="stMultiSelect"] [data-baseweb="tag"] svg {{
            fill: #7F8C8D !important;
        }}
        </style>
    """, unsafe_allow_html=True)


def _etiquetas(activos: pd.DataFrame) -> dict[str, str]:
    """empleado_id -> 'Nombre (teléfono)'; si dos personas salen igual, se agrega su ID."""
    base = activos["nombre_completo"].fillna("Sin nombre") + " (" + activos["telefono"].fillna("sin teléfono") + ")"
    repetido = base.duplicated(keep=False)
    base = base.where(~repetido, base + " · " + activos["empleado_id"])
    return dict(zip(activos["empleado_id"], base))


def _texto_cambio(codigos_agregados, codigos_quitados) -> str:
    partes = [f"➕ {POR_CODIGO[c].nombre}" for c in sorted(codigos_agregados) if c in POR_CODIGO]
    partes += [f"➖ {POR_CODIGO[c].nombre}" for c in sorted(codigos_quitados) if c in POR_CODIGO]
    return " · ".join(partes)


def _guardar(supabase, cambios, deseados, mensaje_ok: str):
    """Escribe solo a quien cambió. Si algo falla se avisa y NO se limpia la pantalla."""
    guardados = 0
    try:
        for emp_id in cambios:
            supabase.table("empleados").update({"permisos": sorted(deseados[emp_id])}) \
                .eq("empleado_id", emp_id).execute()
            guardados += 1
    except Exception as e:
        st.error(f"❌ Se guardaron {guardados} de {len(cambios)} personas y falló la siguiente: {e}. "
                 f"Revisa y vuelve a intentar.")
        return
    st.session_state["permisos_version"] = st.session_state.get("permisos_version", 0) + 1
    st.session_state["permisos_mensaje"] = mensaje_ok
    st.rerun()


def _avisos_de_estado(tel_por_id, actuales):
    """Avisos arriba de todo, solo cuando algo importante está sin cubrir."""
    def tienen(codigo):
        return [i for i, p in actuales.items() if codigo in p]

    def con_telefono(codigo):
        return [i for i in tienen(codigo) if tel_por_id.get(i)]

    if not con_telefono(REPORTE_SEMANAL):
        st.warning("⚠️ **Nadie recibe el reporte semanal.** Elige a quién en la sección «Recibe el reporte semanal».")
    if not con_telefono(CONTROL_ASISTENCIA):
        st.warning("⚠️ **Nadie tiene Control de asistencia.** No habrá recordatorios de hora de corte "
                   "y nadie podrá usar AVISAR.")
    if not con_telefono(RECIBIR_URGENCIAS):
        st.info("ℹ️ Nadie está elegido para recibir las urgencias: por ahora llegan al contratista.")
    for codigo in (REPORTE_SEMANAL, CONTROL_ASISTENCIA, RECIBIR_URGENCIAS):
        if len(tienen(codigo)) > len(con_telefono(codigo)):
            st.warning(f"⚠️ Hay personas con «{POR_CODIGO[codigo].nombre}» que no tienen teléfono registrado, "
                       f"así que no recibirán nada. Agrégales el teléfono en 👥 Directorio de Personal.")


def _tab_por_permiso(supabase, activos, actuales, etq, tel_por_id, ver):
    ids = list(activos.sort_values("nombre_completo")["empleado_id"])
    con_tel = {i for i in ids if tel_por_id.get(i)}
    id_por_etq = {v: k for k, v in etq.items()}
    deseados = {i: set(p) for i, p in actuales.items()}

    def selector(codigo):
        p = POR_CODIGO[codigo]
        tienen = [i for i in ids if codigo in actuales[i]]
        st.markdown(f"**{p.etiqueta}** · {len(tienen)} {'persona' if len(tienen) == 1 else 'personas'}")
        st.caption(p.descripcion + (f" {p.nota}" if p.nota else ""))
        # Para «recibir» algo se ofrece solo a quien tiene teléfono (y a quien ya lo tenía, para no quitárselo en silencio)
        ofrecidos = [i for i in ids if not p.exige_telefono or i in con_tel or i in tienen]
        elegidos = st.multiselect(
            p.nombre, options=[etq[i] for i in ofrecidos],
            default=[etq[i] for i in tienen if i in ofrecidos],
            key=f"perm_{codigo}_{ver}", label_visibility="collapsed",
            placeholder="Busca y elige personas",
        )
        ids_elegidos = {id_por_etq[e] for e in elegidos}
        for i in ofrecidos:
            if i in ids_elegidos:
                deseados[i].add(codigo)
            else:
                deseados[i].discard(codigo)

    for titulo, codigos in GRUPOS:
        st.subheader(titulo)
        for codigo in codigos:
            selector(codigo)
            st.write("")

    with st.expander("⚙️ Avanzado: registro con ubicación y foto (excepción)"):
        st.caption("Casi nadie debería estar aquí: quien no tiene ningún permiso usa el registro simple. "
                   "Úsalo solo para quien deba seguir mandando foto y avances.")
        selector(REGISTRO_CON_FOTO)

    st.divider()
    cambios = calcular_cambios(actuales, deseados)
    if not cambios:
        st.caption("✅ No hay cambios por guardar.")
        return
    st.subheader(f"📝 Cambios por guardar ({len(cambios)})")
    for emp_id, (agregados, quitados) in cambios.items():
        st.markdown(f"- **{etq[emp_id]}**: {_texto_cambio(agregados, quitados)}")
    if st.button("💾 Guardar permisos", type="primary", key=f"perm_guardar_{ver}"):
        _guardar(supabase, cambios, deseados, f"✅ Permisos guardados ({len(cambios)} persona(s)).")


def _tab_por_persona(supabase, activos, actuales, etq, tel_por_id, ver, hora_corte_salida):
    ids = list(activos.sort_values("nombre_completo")["empleado_id"])
    emp_id = st.selectbox(
        "Busca a la persona:", options=ids, index=None, format_func=lambda i: etq[i],
        placeholder="Escribe un nombre", key=f"perm_persona_{ver}",
    )
    if emp_id is None:
        st.caption("Elige a alguien para ver y cambiar sus accesos.")
        return

    fila = activos[activos["empleado_id"] == emp_id].iloc[0]
    obra = fila.get("obra_actual")
    st.markdown(f"**{fila['nombre_completo']}** · {tel_por_id.get(emp_id) or 'sin teléfono'} · "
                f"{obra if isinstance(obra, str) and obra else 'Sin obra'}")

    st.markdown("**Sus accesos** (marca lo que puede hacer):")
    deseados = set()
    for codigo, p in POR_CODIGO.items():
        if st.checkbox(p.etiqueta, value=codigo in actuales[emp_id], help=p.descripcion,
                       key=f"perm_chk_{emp_id}_{codigo}_{ver}"):
            deseados.add(codigo)

    cambios = calcular_cambios({emp_id: actuales[emp_id]}, {emp_id: deseados})
    if cambios:
        agregados, quitados = cambios[emp_id]
        st.info(f"📝 Cambios por guardar: {_texto_cambio(agregados, quitados)}")
        if st.button("💾 Guardar permisos de esta persona", type="primary", key=f"perm_guardar_p_{ver}"):
            _guardar(supabase, cambios, {emp_id: deseados}, f"✅ Permisos de {fila['nombre_completo']} guardados.")

    st.divider()
    st.markdown("#### 📱 Así lo verá en su WhatsApp")
    st.caption("Es una vista previa de cómo quedaría con los accesos marcados arriba, aunque todavía no los guardes.")
    nombre = fila["nombre_completo"]
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.caption("Al empezar el día")
            st.text(texto_menu_inicio(nombre))
    with c2:
        with st.container(border=True):
            st.caption("Ya en turno")
            st.text(texto_menu_en_turno(nombre, deseados))
    comandos = comandos_especiales(deseados)
    if comandos:
        st.markdown("**Comandos que también puede escribir:** " + ", ".join(f"`{c}`" for c in comandos))

    st.markdown("**En resumen, esta persona:**")
    for frase in que_puede_hacer(deseados, hora_corte_salida):
        st.markdown(f"- {frase}")


def _transicion(supabase, activos, actuales, etq, ver):
    with st.expander("🔄 Transición al registro simple (quitar un permiso a todos de una vez)"):
        st.write("Al empezar, todos conservan el registro con foto y los avisos para que nada cambie de golpe. "
                 "Cuando quieras pasar a la gente al registro simple, quítale el permiso a todos aquí y vuelve a "
                 "darlo solo a quien lo necesite en las secciones de arriba.")
        codigo = st.selectbox(
            "Permiso que se quitará a todos:", [REGISTRO_CON_FOTO, ENVIAR_AVISOS],
            format_func=lambda c: POR_CODIGO[c].etiqueta, key=f"perm_trans_cod_{ver}",
        )
        tienen = [i for i, p in actuales.items() if codigo in p]
        excepciones = st.multiselect(
            "Dejárselo a estas personas (opcional):", options=[etq[i] for i in tienen],
            key=f"perm_trans_exc_{ver}", placeholder="Nadie, se lo quito a todos",
        )
        ids_excepciones = {i for i in tienen if etq[i] in excepciones}
        afectados = [i for i in tienen if i not in ids_excepciones]
        st.write(f"Se le quitará a **{len(afectados)}** persona(s).")
        confirmado = st.checkbox(
            f"Entiendo que {len(afectados)} persona(s) dejarán de tener «{POR_CODIGO[codigo].nombre}»",
            key=f"perm_trans_ok_{ver}",
        )
        if st.button("Quitar a todos", disabled=not (confirmado and afectados), key=f"perm_trans_btn_{ver}"):
            deseados = {i: (p - {codigo} if i in afectados else set(p)) for i, p in actuales.items()}
            cambios = calcular_cambios(actuales, deseados)
            _guardar(supabase, cambios, deseados, f"✅ Se quitó «{POR_CODIGO[codigo].nombre}» a {len(afectados)} persona(s).")


def render(supabase, df_empleados: pd.DataFrame, hora_corte_salida: str = "18:00"):
    st.markdown("### 🔐 Permisos y Accesos")
    st.info(
        "**Cómo funciona:** todo trabajador activo puede registrar su entrada y su salida. Aquí das los "
        "accesos extra. Quien no tenga ninguna casilla usa el **registro simple**: escribe 1, comparte su "
        f"ubicación y listo; para salir escribe SALIDA, y si se le olvida el sistema cierra su turno solo a las "
        f"**{hora_corte_salida}**."
    )

    if st.session_state.get("permisos_mensaje"):
        st.success(st.session_state.pop("permisos_mensaje"))

    if df_empleados.empty:
        st.info("No hay empleados registrados todavía.")
        return
    if "permisos" not in df_empleados.columns:
        st.warning("⚠️ Todavía no existe la columna 'permisos' en la base de datos. Falta correr el SQL del paso 1.")
        return

    activos = df_empleados[df_empleados["estado"] == "ACTIVO"].copy()
    if activos.empty:
        st.info("No hay empleados activos.")
        return

    _estilo_multiselect()
    ver = st.session_state.get("permisos_version", 0)   # sube con cada guardado: los selectores arrancan limpios
    etq = _etiquetas(activos)
    actuales = {fila["empleado_id"]: permisos_de(fila) for fila in activos.to_dict("records")}
    tel_por_id = dict(zip(activos["empleado_id"], activos["telefono"].fillna("").astype(str).str.strip()))

    _avisos_de_estado(tel_por_id, actuales)

    tab_permiso, tab_persona = st.tabs(["👥 Por permiso", "🔎 Por persona"])
    with tab_permiso:
        st.caption("Elige quién tiene cada acceso. Cada pestaña se guarda por separado.")
        _tab_por_permiso(supabase, activos, actuales, etq, tel_por_id, ver)
    with tab_persona:
        st.caption("Busca a una persona para ver, cambiar y previsualizar sus accesos. Cada pestaña se guarda por separado.")
        _tab_por_persona(supabase, activos, actuales, etq, tel_por_id, ver, hora_corte_salida)

    _transicion(supabase, activos, actuales, etq, ver)

    with st.expander("🧾 Detalles técnicos"):
        st.caption("Nombre en el panel y código interno de cada permiso (por si hay que revisar la base de datos).")
        st.dataframe(
            pd.DataFrame([{"Permiso": p.etiqueta, "Código": p.codigo, "Qué permite": p.descripcion}
                          for p in POR_CODIGO.values()]),
            hide_index=True,
        )

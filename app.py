import streamlit as st
import math
import os
from datetime import datetime, timezone, timedelta
from fpdf import FPDF

# ==========================================
# 1. CONFIGURACIÓN DE LA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Tamizaje RCV - E.S.E. Hospital San Joaquín",
    page_icon="❤️",
    layout="wide"
)

LOGO_PATH = "logo.png"

# ==========================================
# 2. MOTOR DE CÁLCULO NORMATIVO (RES. 3280)
# ==========================================
def calcular_riesgo_colombia(d: dict) -> dict:
    # A. Cálculo de IMC
    imc = round(d["peso_kg"] / ((d["talla_cm"] / 100) ** 2), 2)
    if imc < 18.5:
        estado_imc = "Bajo peso"
    elif 18.5 <= imc < 25.0:
        estado_imc = "Peso normal"
    elif 25.0 <= imc < 30.0:
        estado_imc = "Sobrepeso"
    else:
        estado_imc = "Obesidad"

    # B. Cálculo de FINDRISC Colombia (ColDRISC)
    pts_findrisc = 0
    edad = d["edad"]
    if 45 <= edad <= 54: pts_findrisc += 2
    elif 55 <= edad <= 64: pts_findrisc += 3
    elif edad > 64: pts_findrisc += 4
    
    if 25 <= imc < 30: pts_findrisc += 1
    elif imc >= 30: pts_findrisc += 3
    
    # Corte de perímetro abdominal para Colombia (H >= 94 cm, M >= 90 cm)
    cintura = d["perimetro_abdominal"]
    obesidad_abdominal = "No"
    if d["sexo"] == "Masculino" and cintura >= 94:
        pts_findrisc += 4
        obesidad_abdominal = "Sí (>= 94 cm)"
    elif d["sexo"] == "Femenino" and cintura >= 90:
        pts_findrisc += 4
        obesidad_abdominal = "Sí (>= 90 cm)"
    
    if d["actividad_fisica"] == "No": pts_findrisc += 2
    if d["frutas_verduras"] == "No": pts_findrisc += 1
    if d["medicamentos_hta"] == "Sí": pts_findrisc += 2
    if d["historico_glucosa"] == "Sí": pts_findrisc += 5
    
    if d["antecedente_familiar_dm"] == "Abuelos, tíos o primos (2do grado)": pts_findrisc += 3
    elif d["antecedente_familiar_dm"] == "Padres, hermanos o hijos (1er grado)": pts_findrisc += 5
    
    if pts_findrisc < 10:
        cat_findrisc = "Riesgo Bajo (< 10 pts)"
    elif 10 <= pts_findrisc <= 11:
        cat_findrisc = "Riesgo Moderado (10 - 11 pts)"
    else:
        cat_findrisc = "Riesgo Alto (>= 12 pts)"

    # C. Cálculo de Framingham Calibrado para Colombia (Factor x0.75)
    pas = d["presion_sistolica"]
    fuma = 1 if d["fumador"] == "Sí" else 0
    trat_hta = 1 if d["medicamentos_hta"] == "Sí" else 0
    dm = 1 if d["evento_cv_o_dm_previa"] == "Sí" else 0
    
    ln_edad = math.log(max(edad, 30))
    ln_pas = math.log(pas)
    
    if d["tiene_laboratorios"] == "Sí":
        ln_ct = math.log(d["colesterol_total"])
        ln_hdl = math.log(d["colesterol_hdl"])
        if d["sexo"] == "Masculino":
            suma_beta = (3.06117 * ln_edad) + (1.12370 * ln_ct) - (0.93263 * ln_hdl) + \
                        ((1.99881 if trat_hta else 1.93303) * ln_pas) + (0.65451 * fuma) + (0.57367 * dm)
            riesgo_crudo = 1 - math.pow(0.88936, math.exp(suma_beta - 23.9802))
        else:
            suma_beta = (2.32888 * ln_edad) + (1.20904 * ln_ct) - (0.70833 * ln_hdl) + \
                        ((2.82263 if trat_hta else 2.76157) * ln_pas) + (0.52873 * fuma) + (0.69154 * dm)
            riesgo_crudo = 1 - math.pow(0.95012, math.exp(suma_beta - 26.1931))
        metodo = "Framingham con Perfil Lipídico (Calibrado Colombia x0.75)"
    else:
        ln_imc = math.log(imc)
        if d["sexo"] == "Masculino":
            suma_beta = (3.11296 * ln_edad) + (0.79277 * ln_imc) + \
                        ((1.92672 if trat_hta else 1.85508) * ln_pas) + (0.70953 * fuma) + (0.53160 * dm)
            riesgo_crudo = 1 - math.pow(0.88431, math.exp(suma_beta - 23.9388))
        else:
            suma_beta = (2.72107 * ln_edad) + (0.51125 * ln_imc) + \
                        ((2.88267 if trat_hta else 2.81291) * ln_pas) + (0.61868 * fuma) + (0.77763 * dm)
            riesgo_crudo = 1 - math.pow(0.94833, math.exp(suma_beta - 26.0145))
        metodo = "Framingham Simplificado por IMC (Calibrado Colombia x0.75)"

    porcentaje_col = round((riesgo_crudo * 100) * 0.75, 2)

    # D. Regla de Categorización Global y Conducta RIAS
    if d["evento_cv_o_dm_previa"] == "Sí" or pas >= 180:
        clasificacion_global = "RIESGO ALTO / MUY ALTO (Categorización Directa)"
        nivel_alerta = "ALTO"
        conducta = [
            "Ingreso inmediato al programa de Riesgo Cardiovascular y Metabólico (Prevención Secundaria / Alto Riesgo).",
            "Valoración prioritaria por Medicina General o Interna para ajuste farmacológico y metas estrictas de control.",
            "Solicitar paraclínicos de control: Perfil lipídico completo, HbA1c, Creatinina sérica, Microalbuminuria y EKG."
        ]
    elif porcentaje_col >= 10.0:
        clasificacion_global = "RIESGO ALTO (>= 10%)"
        nivel_alerta = "ALTO"
        conducta = [
            "Ingreso a Ruta de Riesgo Cardio-Cerebro-Vascular-Metabólico (Resolución 3280 de 2018).",
            "Valoración médica para definir inicio de terapia farmacológica (estatinas / antihipertensivos) e intervención intensiva en estilo de vida.",
            "Solicitar Glicemia Basal en ayunas, Perfil Lipídico, Creatinina y Uroanálisis."
        ]
    elif 5.0 <= porcentaje_col < 10.0:
        clasificacion_global = "RIESGO MODERADO (5.0% - 9.9%)"
        nivel_alerta = "MODERADO"
        conducta = [
            "Intervención estructurada en estilos de vida saludables (nutrición, actividad física regular, cesación de tabaco).",
            "Seguimiento clínico cada 6 a 12 meses según criterio médico."
        ]
        if pts_findrisc >= 12:
            conducta.append("ALERTA FINDRISC >= 12 pts: Solicitar Glicemia en ayunas y Perfil Lipídico para descartar Diabetes / Prediabetes.")
    else:
        clasificacion_global = "RIESGO BAJO (< 5.0%)"
        nivel_alerta = "BAJO"
        conducta = [
            "Continuar en Ruta de Promoción y Mantenimiento de la Salud (RPMS).",
            "Mantener hábitos de vida saludable y reevaluar riesgo según periodicidad de su curso de vida."
        ]
        if pts_findrisc >= 12:
            conducta.append("ALERTA FINDRISC >= 12 pts: A pesar de Framingham bajo, presenta Riesgo Metabólico Alto. Ordenar Glicemia Basal en ayunas.")

    return {
        "imc": imc,
        "estado_imc": estado_imc,
        "obesidad_abdominal": obesidad_abdominal,
        "puntaje_findrisc": pts_findrisc,
        "clasificacion_findrisc": cat_findrisc,
        "porcentaje_framingham_col": porcentaje_col,
        "metodo_framingham": metodo,
        "clasificacion_rcv_global": clasificacion_global,
        "nivel_alerta": nivel_alerta,
        "conducta_rias": conducta
    }

# ==========================================
# 3. GENERADOR DE REPORTE PDF CON LOGO
# ==========================================
def texto_seguro(texto: str) -> str:
    return str(texto).encode("latin-1", "replace").decode("latin-1")

def generar_pdf_paciente(d: dict, r: dict) -> bytes:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- ENCABEZADO INSTITUCIONAL CON ESCUDO ---
    # Fondo azul institucional (de x=10 a x=200, alto 24 mm)
    pdf.set_fill_color(20, 65, 115)
    pdf.rect(10, 10, 190, 24, "F")

    if os.path.exists(LOGO_PATH):
        # Recuadro blanco para que el escudo resalte limpio
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(12, 11.5, 21, 21, "F")
        pdf.image(LOGO_PATH, x=13, y=12, w=19, h=19)
        x_texto = 35
    else:
        x_texto = 10

    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(x_texto, 12)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(200 - x_texto, 6, texto_seguro("E.S.E. HOSPITAL SAN JOAQUÍN - NARIÑO, ANTIOQUIA"), ln=True, align="C")

    pdf.set_x(x_texto)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(200 - x_texto, 6, texto_seguro("REPORTE DE TAMIZAJE DE RIESGO CARDIOVASCULAR Y METABÓLICO"), ln=True, align="C")

    pdf.set_x(x_texto)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(200 - x_texto, 5, texto_seguro("Basado en la Resolución 3280 de 2018 (RIAS) - Ministerio de Salud y Protección Social de Colombia"), ln=True, align="C")

    # Ubicar cursor debajo del banner
    pdf.set_y(38)

    # --- 1. DATOS DEL PACIENTE ---
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(230, 236, 245)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(0, 7, texto_seguro("1. DATOS DE IDENTIFICACIÓN DEL PACIENTE"), ln=True, fill=True)
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(35, 6, texto_seguro("Nombre Completo:"))
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(90, 6, texto_seguro(d["nombre_completo"]))
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(30, 6, texto_seguro("Fecha Tamizaje:"))
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, texto_seguro(d["fecha_registro"]), ln=True)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(35, 6, texto_seguro("Identificación:"))
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(45, 6, texto_seguro(f"{d['tipo_doc']} {d['documento']}"))
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(20, 6, texto_seguro("Edad/Sexo:"))
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(35, 6, texto_seguro(f"{d['edad']} años / {d['sexo']}"))
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(20, 6, texto_seguro("Teléfono:"))
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, texto_seguro(d["telefono"] if d["telefono"] else "No reportado"), ln=True)
    pdf.ln(3)

    # --- 2. PARÁMETROS BIOMÉTRICOS Y CLÍNICOS ---
    pdf.set_fill_color(230, 236, 245)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(0, 7, texto_seguro("2. PARÁMETROS BIOMÉTRICOS Y RESPUESTAS DEL CUESTIONARIO"), ln=True, fill=True)
    pdf.ln(1)

    filas_datos = [
        ("Peso / Talla", f"{d['peso_kg']} kg / {d['talla_cm']} cm", "Índice de Masa Corporal (IMC)", f"{r['imc']} kg/m2 ({r['estado_imc']})"),
        ("Perímetro Abdominal", f"{d['perimetro_abdominal']} cm", "Obesidad Abdominal (RIAS)", r["obesidad_abdominal"]),
        ("Presión Arterial Sistólica", f"{d['presion_sistolica']} mmHg", "Toma Medicamentos HTA", d["medicamentos_hta"]),
        ("Actividad Física (>=30m/día)", d["actividad_fisica"], "Consumo Diario Frutas/Verduras", d["frutas_verduras"]),
        ("Fumador Actual", d["fumador"], "Histórico Azúcar Alta en Sangre", d["historico_glucosa"]),
        ("Antecedente Familiar Diabetes", d["antecedente_familiar_dm"], "DM / ERC / Evento CV Previo", d["evento_cv_o_dm_previa"]),
    ]

    if d["tiene_laboratorios"] == "Sí":
        filas_datos.append(("Colesterol Total", f"{d['colesterol_total']} mg/dL", "Colesterol HDL", f"{d['colesterol_hdl']} mg/dL"))
    else:
        filas_datos.append(("Perfil Lipídico", "No disponible (Cálculo por IMC)", "Método Utilizado", "Framingham por IMC x0.75"))

    for col1_lbl, col1_val, col2_lbl, col2_val in filas_datos:
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(48, 6, texto_seguro(col1_lbl + ":"), border="B")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.cell(47, 6, texto_seguro(col1_val), border="B")
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(48, 6, texto_seguro(col2_lbl + ":"), border="B")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.cell(0, 6, texto_seguro(col2_val), border="B", ln=True)

    pdf.ln(4)

    # --- 3. RESULTADOS DE LA CLASIFICACIÓN ---
    pdf.set_fill_color(230, 236, 245)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(0, 7, texto_seguro("3. RESULTADO DE ESCALAS NORMATIVAS (COLOMBIA)"), ln=True, fill=True)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 9.5)
    pdf.cell(95, 7, texto_seguro(f"Puntaje FINDRISC Colombia: {r['puntaje_findrisc']} puntos"), border=1, align="C")
    pdf.cell(0, 7, texto_seguro(f"Riesgo Framingham a 10 años (x0.75): {r['porcentaje_framingham_col']}%"), border=1, ln=True, align="C")
    
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(95, 6, texto_seguro(f"Interpretación: {r['clasificacion_findrisc']}"), border=1, align="C")
    pdf.cell(0, 6, texto_seguro(f"Método: {r['metodo_framingham']}"), border=1, ln=True, align="C")
    pdf.ln(4)

    if r["nivel_alerta"] == "ALTO":
        pdf.set_fill_color(200, 35, 51)
        pdf.set_text_color(255, 255, 255)
    elif r["nivel_alerta"] == "MODERADO":
        pdf.set_fill_color(230, 145, 0)
        pdf.set_text_color(255, 255, 255)
    else:
        pdf.set_fill_color(40, 140, 60)
        pdf.set_text_color(255, 255, 255)

    pdf.set_font("Helvetica", "B", 11.5)
    pdf.cell(0, 10, texto_seguro(f"CLASIFICACIÓN GLOBAL: {r['clasificacion_rcv_global']}"), ln=True, align="C", fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # --- 4. CONDUCTA Y RECOMENDACIONES RIAS ---
    pdf.set_fill_color(230, 236, 245)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(0, 7, texto_seguro("4. CONDUCTA SUGERIDA SEGÚN RESOLUCIÓN 3280 DE 2018 (RIAS)"), ln=True, fill=True)
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 9.5)
    for idx, item in enumerate(r["conducta_rias"], 1):
        pdf.multi_cell(0, 6, texto_seguro(f"{idx}. {item}"))
        pdf.ln(1)

    # --- 5. ESPACIO DE FIRMA Y NOTA LEGAL ---
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(95, 6, "__________________________________________", align="C")
    pdf.cell(0, 6, "__________________________________________", ln=True, align="C")
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(95, 5, texto_seguro("Firma del Paciente / Usuario"), align="C")
    pdf.cell(0, 5, texto_seguro("Firma y Sello del Profesional / Auxiliar"), ln=True, align="C")

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(
        0, 4,
        texto_seguro(
            "Nota normativa: Este reporte corresponde a una valoración de tamizaje automatizado de la E.S.E. Hospital San Joaquín "
            "(Nariño, Antioquia), basada en las ecuaciones de Framingham (calibradas por factor 0.75 para población colombiana) y el test "
            "FINDRISC validado en Colombia, conforme a los lineamientos técnicos de la Resolución 3280 de 2018. El paciente autorizó el "
            "tratamiento de datos conforme a la Ley 1581 de 2012."
        )
    )

    return bytes(pdf.output())

# ==========================================
# 4. INTERFAZ DE USUARIO (STREAMLIT)
# ==========================================
col_logo, col_titulo = st.columns([1, 8])
with col_logo:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=95)
with col_titulo:
    st.title("E.S.E. Hospital San Joaquín - Nariño, Antioquia")
    st.subheader("Tamizaje de Riesgo Cardiovascular y Metabólico (Resolución 3280 de 2018)")

st.divider()

tiene_lab = st.radio(
    "¿Cuenta el paciente con resultados recientes de exámenes de Colesterol (Total y HDL)?",
    options=["No", "Sí"],
    horizontal=True
)

with st.form("form_tamizaje_pdf", clear_on_submit=False):
    st.subheader("1. Datos de Identificación del Paciente")
    col_id1, col_id2, col_id3, col_id4 = st.columns(4)
    with col_id1:
        tipo_doc = st.selectbox("Tipo de Documento", ["CC", "TI", "CE", "PA", "PPT"])
    with col_id2:
        documento = st.text_input("Número de Documento *")
    with col_id3:
        nombre_completo = st.text_input("Nombre Completo *")
    with col_id4:
        telefono = st.text_input("Teléfono / Celular")

    st.divider()
    st.subheader("2. Datos Biométricos y Antropométricos")
    col_b1, col_b2, col_b3, col_b4, col_b5 = st.columns(5)
    with col_b1:
        sexo = st.selectbox("Sexo biológico", ["Femenino", "Masculino"])
    with col_b2:
        edad = st.number_input("Edad (años)", min_value=18, max_value=110, value=45, step=1)
    with col_b3:
        peso_kg = st.number_input("Peso (kg)", min_value=30.0, max_value=220.0, value=70.0, step=0.5)
    with col_b4:
        talla_cm = st.number_input("Estatura / Talla (cm)", min_value=120.0, max_value=220.0, value=165.0, step=1.0)
    with col_b5:
        perimetro_abdominal = st.number_input("Perímetro Abdominal / Cintura (cm)", min_value=50.0, max_value=180.0, value=88.0, step=1.0)

    st.divider()
    st.subheader("3. Cuestionario de Hábitos y Antecedentes (FINDRISC & Framingham)")
    col_h1, col_h2 = st.columns(2)
    with col_h1:
        actividad_fisica = st.selectbox(
            "¿Realiza habitualmente al menos 30 minutos diarios de actividad física?",
            ["Sí", "No"]
        )
        frutas_verduras = st.selectbox(
            "¿Come frutas y verduras todos los días?",
            ["Sí", "No"]
        )
        medicamentos_hta = st.selectbox(
            "¿Toma actualmente medicamentos para la presión arterial alta (hipertensión)?",
            ["No", "Sí"]
        )
        fumador = st.selectbox(
            "¿Fuma actualmente (o dejó de fumar hace menos de 1 año)?",
            ["No", "Sí"]
        )

    with col_h2:
        historico_glucosa = st.selectbox(
            "¿Le han encontrado alguna vez niveles altos de azúcar (glucosa) en controles o embarazo?",
            ["No", "Sí"]
        )
        antecedente_familiar_dm = st.selectbox(
            "¿Alguien en su familia ha sido diagnosticado con Diabetes (Tipo 1 o 2)?",
            ["No", "Abuelos, tíos o primos (2do grado)", "Padres, hermanos o hijos (1er grado)"]
        )
        evento_cv_o_dm_previa = st.selectbox(
            "¿Ya tiene diagnóstico médico confirmado de Diabetes, Enfermedad Renal Crónica, o ha sufrido un Infarto / ACV?",
            ["No", "Sí"]
        )
        presion_sistolica = st.number_input(
            "Presión Arterial Sistólica (mmHg). Si no la conoce, deje 120:",
            min_value=80, max_value=240, value=120, step=1
        )

    if tiene_lab == "Sí":
        st.divider()
        st.subheader("4. Resultados de Laboratorio (Perfil Lipídico)")
        col_l1, col_l2 = st.columns(2)
        with col_l1:
            colesterol_total = st.number_input("Colesterol Total (mg/dL)", min_value=100, max_value=450, value=190, step=1)
        with col_l2:
            colesterol_hdl = st.number_input("Colesterol HDL (mg/dL)", min_value=15, max_value=120, value=45, step=1)
    else:
        colesterol_total = 0
        colesterol_hdl = 0

    st.divider()
    autorizacion_datos = st.checkbox(
        "Confirmo el diligenciamiento de los datos con fines de evaluación clínica y generación de reporte individual (Ley 1581 de 2012)."
    )

    boton_evaluar = st.form_submit_button("🔍 Calcular Riesgo Cardiovascular y Generar PDF", use_container_width=True)

# ==========================================
# 5. PROCESAMIENTO Y BOTÓN DE DESCARGA PDF
# ==========================================
if boton_evaluar:
    if not documento.strip() or not nombre_completo.strip():
        st.error("⚠️ Por favor ingrese el Número de Documento y el Nombre Completo del paciente.")
    elif not autorizacion_datos:
        st.warning("⚠️ Debe marcar la casilla de confirmación antes de generar el reporte.")
    else:
        # Hora oficial de Colombia (UTC-5)
        tz_colombia = timezone(timedelta(hours=-5))
        fecha_colombia = datetime.now(tz_colombia).strftime("%Y-%m-%d %H:%M")

        datos_paciente = {
            "fecha_registro": fecha_colombia,
            "tipo_doc": tipo_doc,
            "documento": documento.strip(),
            "nombre_completo": nombre_completo.strip().upper(),
            "telefono": telefono.strip(),
            "sexo": sexo,
            "edad": edad,
            "peso_kg": peso_kg,
            "talla_cm": talla_cm,
            "perimetro_abdominal": perimetro_abdominal,
            "actividad_fisica": actividad_fisica,
            "frutas_verduras": frutas_verduras,
            "medicamentos_hta": medicamentos_hta,
            "historico_glucosa": historico_glucosa,
            "antecedente_familiar_dm": antecedente_familiar_dm,
            "fumador": fumador,
            "evento_cv_o_dm_previa": evento_cv_o_dm_previa,
            "presion_sistolica": presion_sistolica,
            "tiene_laboratorios": tiene_lab,
            "colesterol_total": colesterol_total,
            "colesterol_hdl": colesterol_hdl
        }

        resultados = calcular_riesgo_colombia(datos_paciente)
        pdf_bytes = generar_pdf_paciente(datos_paciente, resultados)

        st.session_state["ultimo_resultado"] = resultados
        st.session_state["ultimo_pdf"] = pdf_bytes
        nombre_limpio = datos_paciente["nombre_completo"].replace(" ", "_")
        st.session_state["nombre_archivo"] = f"Reporte_RCV_{tipo_doc}_{documento.strip()}_{nombre_limpio}.pdf"

if "ultimo_resultado" in st.session_state:
    res = st.session_state["ultimo_resultado"]
    st.divider()
    st.markdown("### 📋 Resultados de la Clasificación Normativa")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("IMC Calculado", f"{res['imc']} kg/m²", res["estado_imc"], delta_color="off")
    m2.metric("Puntaje FINDRISC", f"{res['puntaje_findrisc']} pts", res["clasificacion_findrisc"], delta_color="off")
    m3.metric("Riesgo Framingham (10 años)", f"{res['porcentaje_framingham_col']}%", "Calibrado Colombia (x0.75)", delta_color="off")
    m4.metric("Clasificación Global", res["clasificacion_rcv_global"])

    conducta_texto = "\n".join([f"- {item}" for item in res["conducta_rias"]])

    if res["nivel_alerta"] == "ALTO":
        st.error(f"🚨 **CLASIFICACIÓN: {res['clasificacion_rcv_global']}**\n\n**Conducta según Resolución 3280 de 2018:**\n{conducta_texto}")
    elif res["nivel_alerta"] == "MODERADO":
        st.warning(f"⚠️ **CLASIFICACIÓN: {res['clasificacion_rcv_global']}**\n\n**Conducta según Resolución 3280 de 2018:**\n{conducta_texto}")
    else:
        st.success(f"✅ **CLASIFICACIÓN: {res['clasificacion_rcv_global']}**\n\n**Conducta según Resolución 3280 de 2018:**\n{conducta_texto}")

    st.download_button(
        label="📄 Descargar Reporte Individual en PDF",
        data=st.session_state["ultimo_pdf"],
        file_name=st.session_state["nombre_archivo"],
        mime="application/pdf",
        type="primary",
        use_container_width=True
    )

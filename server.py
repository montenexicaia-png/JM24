import os
import requests
import hmac
import hashlib
from fastapi import FastAPI, Request, Response
import uvicorn
from dotenv import load_dotenv
import main
from database import supabase

# Cargar las variables del archivo .env al sistema
load_dotenv()

app = FastAPI()

# --- CREDENCIALES LLAMADAS DESDE EL .ENV ---
TOKEN_ACCESO_META = os.getenv("TOKEN_ACCESO_META")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
TELEFONO_CONTRATISTA = os.getenv("TELEFONO_CONTRATISTA")
META_APP_SECRET = os.getenv("META_APP_SECRET") # <-- AQUI LLAMAMOS AL SECRETO

def normalizar_numero_mx(numero: str) -> str:
    """Limpia el '1' extra que Meta le pone a los números de México"""
    numero = numero.strip().lstrip("+")
    if numero.startswith("521") and len(numero) == 13:
        return "52" + numero[3:]
    return numero

def enviar_mensaje_meta(telefono_destino, texto):
    """Función para disparar respuestas por la API oficial de Meta"""
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN_ACCESO_META}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "text",
        "text": {"body": texto}
    }
    try:
        respuesta = requests.post(url, json=payload, headers=headers)
        if respuesta.status_code == 200:
            print(f"✅ Mensaje enviado exitosamente a {telefono_destino}")
        else:
            print(f"⚠️ Error al enviar a Meta: {respuesta.text}")
    except Exception as e:
        print(f"❌ Error de conexión al enviar: {e}")

def procesar_foto_meta(media_id: str) -> str:
    """Descarga la foto de Meta y la sube a Supabase Storage"""
    try:
        print("⏳ Extrayendo URL secreta de Meta...")
        url_info = f"https://graph.facebook.com/v19.0/{media_id}"
        headers = {"Authorization": f"Bearer {TOKEN_ACCESO_META}"}
        info_res = requests.get(url_info, headers=headers).json()
        
        if "url" not in info_res:
            print("❌ Meta no devolvió la URL de la imagen.")
            return "ERROR_SIN_URL"
            
        url_descarga = info_res["url"]
        
        print("⏳ Descargando imagen...")
        img_res = requests.get(url_descarga, headers=headers)
        bytes_imagen = img_res.content
        
        print("⏳ Subiendo a Supabase Storage...")
        nombre_archivo = f"{media_id}.jpg"
        
        supabase.storage.from_("fotos_obra").upload(
            path=nombre_archivo,
            file=bytes_imagen,
            file_options={"content-type": "image/jpeg"}
        )
        
        url_publica = supabase.storage.from_("fotos_obra").get_public_url(nombre_archivo)
        print(f"✅ ¡Foto rescatada y guardada en la nube! -> {url_publica}")
        
        return url_publica
        
    except Exception as e:
        print(f"❌ Error al procesar la foto: {e}")
        return "ERROR_AL_SUBIR_FOTO"

@app.get("/webhook")
async def verificar_webhook(request: Request):
    """Ruta para la verificación de seguridad de Meta"""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return Response(content=challenge, media_type="text/plain")
        else:
            return Response(content="Prohibido", status_code=403)
    return {"status": "Escuchando validación de Meta"}

@app.post("/webhook")
async def recibir_mensajes(request: Request):
    """Recepción de mensajes de Meta conectada a tu cerebro (main.py)"""
    try:
        # --- CAPA 3: EL BÚNKER CRIPTOGRÁFICO ---
        cuerpo_crudo = await request.body()
        firma_meta = request.headers.get("x-hub-signature-256")
        
        if firma_meta and META_APP_SECRET:
            firma_calculada = "sha256=" + hmac.new(
                META_APP_SECRET.encode('utf-8'),
                msg=cuerpo_crudo,
                digestmod=hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(firma_calculada, firma_meta):
                print("🚨 ALERTA: Intento de conexión no autorizada. Firma matemática inválida.")
                return Response(status_code=403)
        # ---------------------------------------

        # (Se eliminó el try doble que tenías aquí para mantener la estructura limpia)
        body = await request.json()
        
        if "entry" in body:
            cambios = body["entry"][0]["changes"][0]["value"]
            
            if "statuses" in cambios:
                return Response(status_code=200)
            
            if "messages" in cambios:
                mensaje = cambios["messages"][0]
                telefono_remitente_crudo = mensaje["from"]
                tipo_mensaje = mensaje["type"]
                
                texto_para_main = None
                
                if tipo_mensaje == "text":
                    texto_para_main = mensaje["text"]["body"]
                    print(f"\n👨‍🔧 Mensaje de TEXTO de {telefono_remitente_crudo}: {texto_para_main}")
                    
                elif tipo_mensaje == "location":
                    lat = mensaje["location"]["latitude"]
                    lon = mensaje["location"]["longitude"]
                    print(f"\n📍 UBICACIÓN recibida | Lat: {lat}, Lon: {lon}")
                    texto_para_main = f"{lat},{lon}"
                    
                elif tipo_mensaje == "image":
                    id_foto = mensaje["image"]["id"]
                    print(f"\n📸 FOTO recibida | ID de Meta: {id_foto}")
                    url_supabase = procesar_foto_meta(id_foto)
                    texto_para_main = f"FOTO|{url_supabase}"
                
                if texto_para_main is not None:
                    telefono_limpio = normalizar_numero_mx(telefono_remitente_crudo)
                    telefono_formateado = f"+{telefono_limpio}"
                    
                    respuesta_del_bot = main.procesar_mensaje_whatsapp(telefono_formateado, texto_para_main)
                    print(f"🤖 Bot responde internamente: {respuesta_del_bot}")
                    
                    if respuesta_del_bot:
                        # 1. Enviar respuesta ordinaria al trabajador
                        enviar_mensaje_meta(telefono_limpio, respuesta_del_bot)
                        
                        # 2. INTERCEPCIÓN DE EMERGENCIA
                        if "🚨 *REPORTE URGENTE ENVIADO*" in respuesta_del_bot:
                            print(f"📢 [ALERTA] Disparando notificación de urgencia al contratista...")
                            
                            mensaje_alerta = (
                                f"🚨 *NOTIFICACIÓN DE EMERGENCIA EN OBRA* 🚨\n\n"
                                f"Un trabajador en turno (+{telefono_limpio}) acaba de reportar una urgencia crítica desde el frente de trabajo:\n\n"
                                f"⚠️ *Reporte:* _\"{texto_para_main}\"_\n\n"
                                f"_*Por favor, tome las medidas correspondientes de inmediato._"
                            )
                            enviar_mensaje_meta(TELEFONO_CONTRATISTA, mensaje_alerta)
                        
        return Response(status_code=200)
    
    except Exception as e:
        print(f"❌ Error interno en el webhook POST: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    print("🚀 Servidor en línea por Meta API y conectado a la Base de Datos NeuroMontAI...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
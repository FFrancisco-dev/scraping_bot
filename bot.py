import logging
import asyncio
import random
import sqlite3
from datetime import datetime
from telethon import TelegramClient, events as telethon_events
from aiogram import Bot, Dispatcher, types
from aiogram.utils.media_group import MediaGroupBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os
from dotenv import load_workbook, load_dotenv # Cargador de entornos

# Cargar las variables del archivo .env oculto
load_dotenv()

# ⚙️ CONFIGURACIÓN SEGURA DESDE EL ENTORNO
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
TOKEN_BOT = os.getenv("TOKEN_BOT")
TU_TELEGRAM_ID = int(os.getenv("TU_TELEGRAM_ID"))


# Mensaje para los privados de Sami (Tráfico de Chateamos)
MENSAJE_BIENVENIDA_PRIVADO = (
    "¡Hola, qué bueno tenerte por aquí! 😏\n\n"
    "No te quedes en la puerta. Si quieres *conocer gente genial*, compartir contenido exclusivo y hablar  "
    " con el resto de las chicas del grupo, únete ya. ¡El acceso es libre y el contenido gratis!\n\n"
    "Haz clic aquí para entrar:👉https://t.me/+iAsjgGQAhvY1ZmU0 🚀\n\n"
    "¡Te veo dentro, no te lo pierdas!"
)

logging.basicConfig(level=logging.INFO)
DB_NAME = "comunidad.db"

# Inicialización de clientes
client = TelegramClient('sesion_bot_telegram', API_ID, API_HASH)
bot = Bot(token=TOKEN_BOT)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

usuarios_respondidos = []
ID_DEL_GRUPO = None # Se detectará automáticamente cuando el bot reciba el primer usuario o mensaje

# =====================================================================
# 🗄️ BASE DE DATOS LOCAL (SQLite)
# =====================================================================
def inicializar_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contenidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_bloque TEXT,
            tipo TEXT,
            contenido TEXT,
            caption TEXT,
            enviado INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

# =====================================================================
# 📬 SECCIÓN A: TELETHON (Auto-respondedor de Chateamos)
# =====================================================================
@client.on(telethon_events.NewMessage(incoming=True))
async def manejador_de_privados(event):
    if event.is_private:
        remitente = await event.get_sender()
        usuario_id = event.chat_id
        
        if remitente and not remitente.bot and usuario_id not in usuarios_respondidos:
            nombre_usuario = remitente.first_name or "Usuario"
            print(f"🔥 [Telethon] Mensaje privado de {nombre_usuario}")
            await asyncio.sleep(random.uniform(2.0, 4.0))
            await event.respond(MENSAJE_BIENVENIDA_PRIVADO)
            usuarios_respondidos.append(usuario_id)

# =====================================================================
# 🛡️ SECCIÓN B: AIOGRAM (Bot de Gestión, Registro y Mod del Grupo)
# =====================================================================

# 🤝 Guardar contenido reenviado (Solo tú puedes hacerlo en el privado del Bot)
@dp.message(lambda msg: msg.chat.type == "private" and msg.from_user.id == TU_TELEGRAM_ID)
async def registrar_contenido(message: types.Message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Generamos un identificador de bloque basado en el tiempo para poder agrupar álbumes
    id_bloque = message.media_group_id if message.media_group_id else f"BL_SINGLE_{int(datetime.now().timestamp())}"
    caption = message.caption if message.caption else ""
    
    tipo, contenido = None, None
    
    if message.text:
        tipo, contenido = "texto", message.text
    elif message.photo:
        tipo, contenido = "foto", message.photo[-1].file_id  # Guardamos la foto con mejor calidad
    elif message.video:
        tipo, contenido = "video", message.video.file_id
        
    if tipo and contenido:
        cursor.execute(
            "INSERT INTO contenidos (id_bloque, tipo, contenido, caption) VALUES (?, ?, ?, ?)",
            (id_bloque, tipo, contenido, caption)
        )
        conn.commit()
        await message.answer(f"💾 Guardado con éxito en la base de datos (Tipo: {tipo})")
    
    conn.close()

# 🎉 Bienvenidas al Grupo
# 👥 EVENTO: Alguien se une al grupo
# 👥 EVENTO: Alguien se une al grupo (Corregido)
# 👥 EVENTO: Alguien se une al grupo (Versión Ultra-Compatible)
@dp.message(lambda message: message.new_chat_members)
async def bienvenida_usuario(message: types.Message):
    global ID_DEL_GRUPO
    ID_DEL_GRUPO = message.chat.id  # Captura el ID del grupo dinámicamente
    
    # Recorremos los usuarios que acaban de entrar (por si entran varios de golpe)
    for usuario in message.new_chat_members:
        # Evitamos darnos la bienvenida a nosotros mismos (al bot)
        if usuario.id == bot.id:
            continue
            
        username = f"@{usuario.username}" if usuario.username else usuario.first_name
        print(f"✨ [Grupo] {usuario.first_name} ({username}) ha entrado al grupo.")
        
        texto_bienvenida = (
            f"¡Hola {username}! Bienvenido/a a nuestra comunidad. 🎉\n\n"
            "Qué bueno tenerte por aquí. Preséntate, dinos de dónde eres "
            "y ponte cómodo/a. ¡A disfrutar del grupo! 😊"
        )
        
        await message.answer(texto_bienvenida)

# 🚫 Moderación básica
@dp.message()
async def moderador_mensajes(message: types.Message):
    global ID_DEL_GRUPO
    if message.chat.type in ["group", "supergroup"]:
        ID_DEL_GRUPO = message.chat.id

    if message.new_chat_members or message.left_chat_member:
        try: await message.delete()
        except: pass
        return

    if message.text and ("http" in message.text or "t.me" in message.text):
        try:
            await message.delete()
            aviso = await message.answer(f"⚠️ {message.from_user.first_name}, enlaces no permitidos.")
            await asyncio.sleep(4)
            await aviso.delete()
        except: pass

# =====================================================================
# ⏰ RECOLECTOR Y PUBLICADOR AUTOMÁTICO (Cada 2 Horas)
# =====================================================================
async def publicar_contenido_cron():
    global ID_DEL_GRUPO
    if not ID_DEL_GRUPO:
        print("⏰ [Reloj] Esperando a que el grupo tenga actividad para conocer su ID...")
        return
        
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Buscamos el primer bloque que no haya sido enviado
    cursor.execute("SELECT id_bloque FROM contenidos WHERE enviado = 0 LIMIT 1")
    fila = cursor.fetchone()
    
    if not fila:
        print("⏰ [Reloj] Base de datos vacía o todo el contenido ya fue enviado.")
        conn.close()
        return
        
    id_bloque_objetivo = fila[0]
    
    # Extraemos todos los elementos que pertenezcan a ese mismo bloque (por si es un álbum)
    cursor.execute("SELECT tipo, contenido, caption FROM contenidos WHERE id_bloque = ?", (id_bloque_objetivo,))
    elementos = cursor.fetchall()
    
    try:
        # CASO 1: Es un álbum multimedia (Múltiples fotos o vídeos)
        if len(elementos) > 1:
            media_group = MediaGroupBuilder()
            for tipo, contenido, caption in elementos:
                if tipo == "foto":
                    media_group.add_photo(media=contenido, caption=caption if caption else None)
                elif tipo == "video":
                    media_group.add_video(media=contenido, caption=caption if caption else None)
            
            await bot.send_media_group(chat_id=ID_DEL_GRUPO, media=media_group.build())
            print(f"🚀 [Reloj] Álbum enviado al grupo (Bloque: {id_bloque_objetivo})")
            
        # CASO 2: Es un elemento único (Texto, URL, 1 Foto o 1 Vídeo)
        else:
            tipo, contenido, caption = elementos[0]
            if tipo == "texto":
                await bot.send_message(chat_id=ID_DEL_GRUPO, text=contenido)
            elif tipo == "foto":
                await bot.send_photo(chat_id=ID_DEL_GRUPO, photo=contenido, caption=caption if caption else None)
            elif tipo == "video":
                await bot.send_video(chat_id=ID_DEL_GRUPO, video=contenido, caption=caption if caption else None)
            print(f"🚀 [Reloj] Contenido único enviado al grupo (Bloque: {id_bloque_objetivo})")
            
        # Marcamos todo el bloque como enviado
        cursor.execute("UPDATE contenidos SET enviado = 1 WHERE id_bloque = ?", (id_bloque_objetivo,))
        conn.commit()
        
    except Exception as e:
        print(f"❌ Error al enviar la publicación programada: {e}")
        
    finally:
        conn.close()

# =====================================================================
# 🚀 FUNCIÓN DE ARRANQUE GENERAL
# =====================================================================
async def main():
    inicializar_db()
    await client.start()
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Programamos la tarea para que corra cada 2 horas
    scheduler.add_job(publicar_contenido_cron, 'interval', hours=2)
    scheduler.start()
    
    print("\n👑 ==================================================")
    print("    SISTEMA INTEGRADO PRO: BASE DE DATOS + CRON ACTIVO")
    print("==================================================\n")
    
    await asyncio.gather(
        client.run_until_disconnected(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
import os
import asyncio
from datetime import datetime
import sqlite3
from dotenv import load_dotenv

# Librerías de Aiogram (El Bot Guardián)
from aiogram import Bot, Dispatcher, executor, types

# Librerías de Telethon (La cuenta de Sami que publica)
from telethon import TelegramClient

# Librería del Temporizador (El reloj)
from apscheduler.schedulers.asyncio import AsyncioScheduler

# 1. ⚙️ CARGAR CONFIGURACIÓN SEGURA
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
TOKEN_BOT = os.getenv("TOKEN_BOT")
TU_TELEGRAM_ID = int(os.getenv("TU_TELEGRAM_ID"))

# 🚫 LISTA NEGRA DE PALABRAS PROHIBIDAS (Moderación)
PALABRAS_PROHIBIDAS = [
    "contenido prohibido", 
    "cp", 
    "pack", 
    "telegram.me/", 
    "t.me/", 
    "links",
    "intercambio"
]

# ID del grupo donde se publicará y se moderará (Se auto-detectará al recibir contenido)
ID_GRUPO_COMUNIDAD = None 

# 2. 🔌 INICIALIZACIÓN DE MOTORES
bot = Bot(token=TOKEN_BOT)
dp = Dispatcher(bot)
client = TelegramClient('sesion_sami', API_ID, API_HASH)
scheduler = AsyncioScheduler()

# 🗄️ FUNCION PARA LA BASE DE DATOS
def inicializar_db():
    conn = sqlite3.connect("comunidad.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contenido (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT,
            file_id TEXT,
            texto TEXT,
            enviado INTEGER DEFAULT 0,
            fecha_creacion TEXT
        )
    """)
    conn.commit()
    conn.close()

inicializar_db()

# =====================================================================
# 👮‍♂️ PARTE A: EL BOT GUARDIÁN (Aiogram - Captura privado y Modera grupo)
# =====================================================================

# Handler 1: Captura de contenido en privado (Solo tú puedes enviarle cosas)
@dp.message_handler(chat_type=["private"])
async def guardar_contenido_privado(message: types.Message):
    if message.from_user.id != TU_TELEGRAM_ID:
        return # Si no eres tú, el bot pasa de largo

    tipo = "text"
    file_id = None
    texto = message.caption if message.caption else message.text

    if message.photo:
        tipo = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        tipo = "video"
        file_id = message.video.file_id

    # Guardar en la base de datos
    conn = sqlite3.connect("comunidad.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contenido (tipo, file_id, texto, fecha_creacion) VALUES (?, ?, ?, ?)",
        (tipo, file_id, texto, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

    await message.reply("💾 Guardado con éxito en la cola de publicación (Base de Datos).")


# Handler 2: Moderador automático en el grupo (Con escudo para ti)
@dp.message_handler(chat_type=["group", "supergroup"])
async def moderar_mensajes_grupo(message: types.Message):
    global ID_GRUPO_COMUNIDAD
    ID_GRUPO_COMUNIDAD = message.chat.id # Guarda el ID del grupo dinámicamente

    # 👑 ESCUDO PARA EL JEFE: Si eres tú el que escribe, el bot no te toca
    if message.from_user.id == TU_TELEGRAM_ID:
        return

    texto_usuario = message.text.lower() if message.text else ""

    # Verificar si infringe las normas
    if any(palabra in texto_usuario for palabra in PALABRAS_PROHIBIDAS):
        try:
            # 1. Borrar el mensaje feo
            await message.delete()
            
            # 2. Banear al usuario del grupo
            await message.chat.kick(user_id=message.from_user.id)
            
            # 3. Poner aviso en el chat
            await message.answer(
                f"🚷 El usuario {message.from_user.first_name} ha sido **baneado** "
                f"por incumplir las normas de la comunidad."
            )
        except Exception as e:
            print(f"Error en moderación: {e}")


# =====================================================================
# ⏰ PARTE B: EL PUBLICADOR AUTOMÁTICO (Telethon + Cron - Cuenta Sami)
# =====================================================================
async def publicar_contenido_cron():
    global ID_GRUPO_COMUNIDAD
    if not ID_GRUPO_COMUNIDAD:
        print("⚠️ Cron esperando a que se registre el ID del grupo...")
        return

    conn = sqlite3.connect("comunidad.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, tipo, file_id, texto FROM contenido WHERE enviado = 0 ORDER BY id ASC LIMIT 1")
    fila = cursor.fetchone()

    if fila:
        id_db, tipo, file_id, texto = fila
        try:
            # Publicar usando la cuenta de Sami (Telethon)
            if tipo == "text":
                await client.send_message(ID_GRUPO_COMUNIDAD, texto)
            elif tipo == "photo":
                await client.send_file(ID_GRUPO_COMUNIDAD, file_id, caption=texto)
            elif tipo == "video":
                await client.send_file(ID_GRUPO_COMUNIDAD, file_id, caption=texto, video_note=False)

            # Marcar como enviado
            cursor.execute("UPDATE contenido SET enviado = 1 WHERE id = ?", (id_db,))
            conn.commit()
            print(f"✅ Publicado con éxito elemento ID {id_db} en el grupo.")
        except Exception as e:
            print(f"❌ Error al enviar post programado: {e}")
    else:
        print("💤 Cola vacía. No hay nada nuevo que publicar.")
    
    conn.close()


# =====================================================================
# 🚀ARRANQUE SIMULTÁNEO DE AMBOS SISTEMAS
# =====================================================================
async def main():
    # Enceder el cliente de Sami (Telethon)
    await client.start()
    
    # Configurar el reloj para que publique cada 2 horas
    scheduler.add_job(publicar_contenido_cron, 'interval', hours=2)
    scheduler.start()
    print("⏰ Temporizador de publicación (2 horas) activado.")

    # Encender el bot guardián (Aiogram)
    print("👮‍♂️ Bot Guardián escuchando en directo...")
    try:
        await dp.start_polling()
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
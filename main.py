from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import os
import json
import asyncio
import firebase_admin
from firebase_admin import credentials, db
from functools import wraps

load_dotenv() 

BOT_TOKEN = os.getenv("BOT_TOKEN")
CANAL_ID = int(os.getenv("CANAL_ID"))
ADMIN_PRINCIPAL = int(os.getenv("ADMIN_PRINCIPAL"))
ADMINES = list(map(int, os.getenv("ADMINES", "").split(",")))
ADMINES_PRIVILEGIADOS = list(map(int, os.getenv("ADMINES_PRIVILEGIADOS", "").split(",")))
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
FIREBASE_PROJECT_NAME = os.getenv("FIREBASE_PROJECT_NAME", "")

cred_dict = json.loads(os.environ["FIREBASE_CREDENTIALS_JSON"])
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred, {
    "databaseURL": f"https://{FIREBASE_PROJECT_NAME}.firebaseio.com/"
})
banned_ref = db.reference("banned_users")

pendientes = {}
esperando_motivo = {}
procesadas = set()

# Utility functions
def is_banned(user_id: int) -> bool:
    return str(user_id) in banned_ref.get() or False

def ban_user(user_id: int):
    banned_ref.child(str(user_id)).set(True)

def unban_user(user_id: int):
    banned_ref.child(str(user_id)).delete()

def check_ban(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if is_banned(user_id):
            await update.message.reply_text("🚫 Estás baneado de este bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def check_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMINES:
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text("🚫 No estás autorizado para tomar esta acción.")
            elif update.message:
                await update.message.reply_text("🚫 No estás autorizado para tomar esta acción.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def check_main_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_PRINCIPAL:
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text("🚫 Solo el administrador principal puede tomar esta acción.")
            elif update.message:
                await update.message.reply_text("🚫 Solo el administrador principal puede tomar esta acción.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

@check_ban
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f'Bienvendido a {BOT_USERNAME}, publique su confesión y en breve será revisada por algún administrador, '
        "es totalmente anónimo, podrá ver los comentarios en cuanto sea publicada"
    )

@check_ban
async def obtener_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    chat_title = getattr(update.effective_chat, 'title', 'Sin título')
    await update.message.reply_text(
        f"📊 Información del chat:\n"
        f"ID: {chat_id}\n"
        f"Tipo: {chat_type}\n"
        f"Título: {chat_title}"
    )
    print(f"Chat ID: {chat_id}, Tipo: {chat_type}, Título: {chat_title}")

@check_main_admin
async def agregar_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        nuevo_id = int(context.args[0])
        if nuevo_id not in ADMINES:
            ADMINES.append(nuevo_id)
            await update.message.reply_text(f"Admin añadido: {nuevo_id}")
        else:
            await update.message.reply_text("Ese usuario ya es admin.")
    except:
        await update.message.reply_text("Uso correcto: /agregaradmin <user_id>")

@check_main_admin
async def dar_privilegios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admin_id = int(context.args[0])
        if admin_id not in ADMINES:
            await update.message.reply_text("Ese usuario no es admin. Primero añádelo con /agregaradmin")
            return
        if admin_id not in ADMINES_PRIVILEGIADOS:
            ADMINES_PRIVILEGIADOS.append(admin_id)
            await update.message.reply_text(f"✅ Privilegios otorgados al admin {admin_id}. Ahora puede ver usuarios de confesiones.")
        else:
            await update.message.reply_text("Ese admin ya tiene privilegios.")
    except:
        await update.message.reply_text("Uso correcto: /privis <user_id>")

@check_main_admin
async def quitar_privilegios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admin_id = int(context.args[0])
        if admin_id == ADMIN_PRINCIPAL:
            await update.message.reply_text("❌ No puedes quitarte los privilegios a ti mismo.")
            return
        if admin_id in ADMINES_PRIVILEGIADOS:
            ADMINES_PRIVILEGIADOS.remove(admin_id)
            await update.message.reply_text(f"❌ Privilegios quitados al admin {admin_id}. Ya no puede ver usuarios de confesiones.")
        else:
            await update.message.reply_text("Ese admin no tiene privilegios especiales.")
    except:
        await update.message.reply_text("Uso correcto: /noprivis <user_id>")

@check_admin
async def admin_confesion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso correcto: /adminconf <texto>")
        return
    texto = " ".join(context.args)
    conf_id = f"admin_{update.message.message_id}_{update.effective_user.id}"
    pendientes[conf_id] = {"texto": texto, "user_id": update.effective_user.id, "es_admin": True}
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aceptar", callback_data=f"aceptar:{conf_id}"),
         InlineKeyboardButton("❌ Rechazar", callback_data=f"rechazar:{conf_id}")]
    ])
    
    for admin in ADMINES:
        mensaje_texto = f"📝 Nueva confesión de ADMIN:\n\n{texto}"
        if admin in ADMINES_PRIVILEGIADOS:
            mensaje_texto += f"\n\n👤 Usuario: {update.effective_user.id}"
            if update.effective_user.username:
                mensaje_texto += f" (@{update.effective_user.username})"
        
        await context.bot.send_message(
            chat_id=admin,
            text=mensaje_texto,
            reply_markup=keyboard
        )
    await update.message.reply_text("Tu confesión de admin fue enviada para revisión.")

@check_ban
async def recibir_confesion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    if update.effective_user.id in ADMINES and update.effective_user.id in esperando_motivo:
        motivo = update.message.text
        datos_rechazo = esperando_motivo[update.effective_user.id]
        conf_id = datos_rechazo["conf_id"]
        user_id = datos_rechazo["user_id"]
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Tu confesión fue rechazada.\n\n📋 Motivo: {motivo}"
            )
            await update.message.reply_text("✅ Motivo de rechazo enviado al usuario.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error al enviar motivo: {e}")
        
        esperando_motivo.pop(update.effective_user.id)
        procesadas.add(conf_id)
        if conf_id in pendientes:
            pendientes.pop(conf_id)
        
        await notificar_procesada(context, conf_id)
        return
    
    if update.effective_user.id in ADMINES:
        await update.message.reply_text(
            "ℹ️ Los administradores no pueden enviar confesiones por mensaje normal.\n"
            "Si quieres confesar, usa: /adminconf <texto>"
        )
        return
    
    texto = update.message.text
    if len(texto) < 60:
        await update.message.reply_text(
            f"❌ Tu confesión debe tener al menos 60 caracteres.\n"
            f"Actualmente tiene {len(texto)} caracteres. Añade {60 - len(texto)} más."
        )
        return
    
    conf_id = f"user_{update.message.message_id}_{update.effective_user.id}"
    pendientes[conf_id] = {"texto": texto, "user_id": update.effective_user.id, "es_admin": False}
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aceptar", callback_data=f"aceptar:{conf_id}"),
         InlineKeyboardButton("❌ Rechazar", callback_data=f"rechazar:{conf_id}")]
    ])
    
    for admin in ADMINES:
        mensaje_texto = f"📝 Nueva confesión recibida ({len(texto)} caracteres):\n\n{texto}"
        if admin in ADMINES_PRIVILEGIADOS:
            if update.effective_user.id:
                mensaje_texto += f"\n\n👤 Usuario: {update.effective_user.id}"  
            if update.effective_user.username:
                mensaje_texto += f'(@{update.effective_user.username})\n\n<a href="tg://user?id={update.effective_user.id}">{update.effective_user.username}</a>'
            elif update.effective_user.first_name:
                mensaje_texto += f'\n\n<a href="tg://user?id={update.effective_user.id}">{update.effective_user.first_name}</a>'   
        await context.bot.send_message(
                    chat_id=admin,
                    text=mensaje_texto,
                    reply_markup=keyboard,
                    parse_mode='HTML'
                )
    await update.message.reply_text("Tu confesión fue enviada para revisión. Gracias.")

async def notificar_procesada(context, conf_id):
    for admin in ADMINES:
        try:
            await context.bot.send_message(
                chat_id=admin,
                text=f"✅ La confesión {conf_id} ya fue procesada por otro administrador."
            )
        except:
            pass

async def manejar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    accion, conf_id = query.data.split(":")
    
    if query.from_user.id not in ADMINES:
        await query.edit_message_text("No estás autorizado para tomar esta acción.")
        return
    
    if conf_id in procesadas:
        await query.edit_message_text("✅ Esta confesión ya fue procesada por otro administrador.")
        return
    
    if conf_id not in pendientes:
        await query.edit_message_text("✅ Esta confesión ya fue procesada.")
        return
    
    procesadas.add(conf_id)
    texto = pendientes[conf_id]["texto"]
    user_id = pendientes[conf_id]["user_id"]
    
    if accion == "aceptar":
        try:
            mensaje_confesion = f"Nueva confesión:\n\n{texto}\n\n📝 Para hacer una confesión pincha aquí {BOT_USERNAME}"
            await context.bot.send_message(chat_id=CANAL_ID, text=mensaje_confesion)
            await query.edit_message_text("✅ Confesión publicada.")
            
            if not pendientes[conf_id]["es_admin"]:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="✅ Tu confesión ha sido aceptada y publicada en el canal."
                    )
                except:
                    pass
            
            print(f"Confesión publicada exitosamente en {CANAL_ID}")
        except Exception as e:
            print(f"Error al publicar confesión: {e}")
            await query.edit_message_text("❌ Error al publicar confesión. Verifica que el bot esté en el canal.")
            procesadas.remove(conf_id)
            return
            
        await notificar_procesada(context, conf_id)
        
    elif accion == "rechazar":
        esperando_motivo[query.from_user.id] = {
            "conf_id": conf_id,
            "user_id": user_id
        }
        await query.edit_message_text(
            "❌ Confesión marcada para rechazo.\n\n"
            "📝 Escribe tu siguiente mensaje con el motivo del rechazo:"
        )
        return
    
    if conf_id in pendientes:
        pendientes.pop(conf_id)

@check_main_admin
async def identify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /identify <telegram_id>")
        return

    user_id = context.args[0]
    if not user_id.isdigit():
        await update.message.reply_text("El ID debe ser un número.")
        return

    link = f'<a href="tg://user?id={user_id}">Haz clic aquí para ver el perfil</a>'

    await update.message.reply_text(
        link,
        parse_mode='HTML',
        disable_web_page_preview=True
    )

@check_main_admin
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        ban_user(user_id)
        await update.message.reply_text(f"✅ User {user_id} has been banned.")
    except ValueError:
        await update.message.reply_text("Invalid user ID.")

@check_main_admin
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        unban_user(user_id)
        await update.message.reply_text(f"✅ User {user_id} has been unbanned.")
    except ValueError:
        await update.message.reply_text("Invalid user ID.")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("agregaradmin", agregar_admin))
    app.add_handler(CommandHandler("privis", dar_privilegios))
    app.add_handler(CommandHandler("noprivis", quitar_privilegios))
    app.add_handler(CommandHandler("adminconf", admin_confesion))
    app.add_handler(CommandHandler("chatid", obtener_chat_id))
    app.add_handler(CommandHandler("identify", identify))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_confesion))
    app.add_handler(CallbackQueryHandler(manejar_callback))
    loop = asyncio.get_event_loop()
    loop.create_task(
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 5000)),
            webhook_url=WEBHOOK_URL
        )
    )
    loop.run_forever()
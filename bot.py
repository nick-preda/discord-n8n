import os
import logging
import aiohttp
import discord
from discord.ext import commands

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
WEBHOOK_URL_JOINED = os.getenv("WEBHOOK_URL_JOINED")
WEBHOOK_URL_MESSAGE = os.getenv("WEBHOOK_URL_MESSAGE")

if not DISCORD_TOKEN:
    raise SystemExit("Devi impostare DISCORD_TOKEN.")
if not WEBHOOK_URL_JOINED:
    raise SystemExit("Devi impostare WEBHOOK_URL_JOINED.")
if not WEBHOOK_URL_MESSAGE:
    raise SystemExit("Devi impostare WEBHOOK_URL_MESSAGE.")

# Intents minimi
intents = discord.Intents.default()
intents.message_content = True   # per leggere il contenuto dei messaggi
intents.members = True           # per intercettare join dei membri (inclusi i bot)
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

def s(v):
    return str(v) if v is not None else None

def _resolve_webhook(event_type: str) -> str:
    # Mappa evento -> URL webhook
    if event_type in ("bot_added_to_guild", "new_bot_member"):
        return WEBHOOK_URL_JOINED
    if event_type == "message_create":
        return WEBHOOK_URL_MESSAGE
    # fallback: usa quello dei messaggi
    return WEBHOOK_URL_MESSAGE

async def post_event(event_type: str, payload: dict):
    """Invia l'evento al webhook corretto come JSON e chiude bene la connessione."""
    url = _resolve_webhook(event_type)
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json={"type": event_type, "payload": payload}) as resp:
                body = await resp.text()  # consuma il body per evitare 'Unclosed connection'
                if resp.status >= 400:
                    logging.error("Webhook %s ha risposto %s: %s", url, resp.status, body[:500])
    except Exception as e:
        logging.exception("Errore nell'invio al webhook: %s", e)
        
        
def _asset_url(asset):
    try:
        return asset.url if asset else None
    except Exception:
        return None

def serialize_guild(guild: discord.Guild) -> dict:
    me = guild.me  # il bot come membro nella guild (potrebbe essere None in alcuni edge-case)
    perms_value = getattr(getattr(me, "guild_permissions", None), "value", None)

    # Conta canali in modo sicuro
    def safe_len(obj, fallback=0):
        try:
            return len(obj)
        except Exception:
            return fallback

    return {
        "guild_id": s(guild.id),
        "guild_name": guild.name,
        "created_at": guild.created_at.isoformat() if getattr(guild, "created_at", None) else None,
        "owner_id": s(getattr(guild, "owner_id", None)),
        "description": getattr(guild, "description", None),
        "preferred_locale": getattr(guild, "preferred_locale", None),
        "nsfw_level": getattr(getattr(guild, "nsfw_level", None), "name", None) if hasattr(guild, "nsfw_level") else None,
        "verification_level": getattr(getattr(guild, "verification_level", None), "name", None),
        "premium_tier": getattr(getattr(guild, "premium_tier", None), "name", None),
        "features": list(getattr(guild, "features", [])),

        # Numeri utili
        "member_count": getattr(guild, "member_count", None),  # richiede SERVER MEMBERS INTENT per essere affidabile
        "roles_count": safe_len(getattr(guild, "roles", [])),
        "emojis_count": safe_len(getattr(guild, "emojis", [])),
        "stickers_count": safe_len(getattr(guild, "stickers", [])),

        # Canali
        "channels": {
            "total": safe_len(getattr(guild, "channels", [])),
            "categories": safe_len(getattr(guild, "categories", [])),
            "text": safe_len(getattr(guild, "text_channels", [])),
            "voice": safe_len(getattr(guild, "voice_channels", [])),
            "stage": safe_len(getattr(guild, "stage_channels", [])),
            "threads_active": safe_len(getattr(guild, "threads", [])),
        },

        # Impostazioni & risorse
        "system_channel_id": s(getattr(getattr(guild, "system_channel", None), "id", None)),
        "rules_channel_id": s(getattr(getattr(guild, "rules_channel", None), "id", None)),
        "public_updates_channel_id": s(getattr(getattr(guild, "public_updates_channel", None), "id", None)),
        "afk_channel_id": s(getattr(getattr(guild, "afk_channel", None), "id", None)),
        "afk_timeout": getattr(guild, "afk_timeout", None),
        "vanity_url_code": getattr(guild, "vanity_url_code", None),

        # Media
        "icon_url": _asset_url(getattr(guild, "icon", None)),
        "banner_url": _asset_url(getattr(guild, "banner", None)),
        "splash_url": _asset_url(getattr(guild, "splash", None)),

        # Permessi del bot nella guild (bitfield intero)
        "bot_permissions_value": perms_value,
    }

@bot.event
async def on_ready():
    logging.info("Connesso come %s (%s)", bot.user, bot.user.id)

@bot.event
async def on_guild_join(guild: discord.Guild):
    await post_event("bot_added_to_guild", serialize_guild(guild))

@bot.event
async def on_member_join(member: discord.Member):
    # Se entra un BOT nel server
    if member.bot:
        await post_event("new_bot_member", {
            "guild_id": s(member.guild.id),
            "guild_name": member.guild.name,
            "bot_id": s(member.id),
            "bot_tag": str(member),
        })


def serialize_attachment(att: discord.Attachment) -> dict:
    # Nota: alcuni campi possono non esistere in tutte le versioni/API → getattr
    return {
        "id": att.id,
        "filename": att.filename,
        "url": att.url,               # URL CDN pubblico di Discord
        "proxy_url": getattr(att, "proxy_url", None),
        "content_type": getattr(att, "content_type", None),  # es. "image/png", "audio/ogg"
        "size": att.size,
        "width": getattr(att, "width", None),   # immagini/video
        "height": getattr(att, "height", None),
        # campi tipici dei voice messages (se presenti)
        "duration_secs": getattr(att, "duration", getattr(att, "duration_secs", None)),
        # waveform è spesso grosso: omesso per tenere leggero il payload
    }
    
    
@bot.event
async def on_message(message: discord.Message):
    # Ignora i DM
    if message.guild is None:
        return

    # True se è un “messaggio vocale” registrato in chat (non audio in voice channel)
    is_voice_msg = False
    if hasattr(message, "flags") and message.flags is not None:
        # Compatibile con diverse versioni di discord.py
        is_voice_msg = bool(
            getattr(message.flags, "is_voice_message", False) or
            getattr(message.flags, "voice", False)
        )

    attachments = [serialize_attachment(a) for a in message.attachments]

    await post_event("message_create", {
        "guild_id": s(message.guild.id),
        "guild_name": message.guild.name,
        "channel_id": s(message.channel.id),
        "channel_name": getattr(message.channel, "name", None),
        "message_id": s(message.id),
        "author_id": s(message.author.id),
        "author_name": str(message.author),
        "author_is_bot": message.author.bot,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "is_voice_message": is_voice_msg,
        "attachments_count": len(attachments),
        "attachments": [
            { **a, "id": s(a["id"]) } for a in attachments
        ],
    })

    await bot.process_commands(message)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
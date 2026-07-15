from pyrogram import Client, filters
from info import CHANNELS
from database.ia_filterdb import save_file
from database.channels_db import get_index_channels

media_filter = filters.document | filters.video


async def index_channel_filter(_, __, message):
    """Check karo ki ye message kisi bhi tracked channel (env var + DB dono) se hai."""
    if message.chat.id in CHANNELS:
        return True
    db_channels = await get_index_channels()
    return message.chat.id in db_channels

dynamic_channels_filter = filters.create(index_channel_filter)


@Client.on_message(dynamic_channels_filter & media_filter)
async def media(bot, message):
    media = getattr(message, message.media.value, None)
    media.caption = message.caption
    await save_file(media, chat_id=message.chat.id, msg_id=message.id)

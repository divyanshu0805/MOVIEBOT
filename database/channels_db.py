import motor.motor_asyncio
from info import OTHER_DB_URI, DATABASE_NAME

client = motor.motor_asyncio.AsyncIOMotorClient(OTHER_DB_URI)
db = client[DATABASE_NAME]
col = db['index_channels']


async def add_index_channel(channel_id):
    """Ek naya channel add karo jise bot auto-index karega."""
    await col.update_one(
        {'_id': channel_id},
        {'$set': {'_id': channel_id}},
        upsert=True
    )


async def remove_index_channel(channel_id):
    """Channel ko auto-index list se hata do."""
    result = await col.delete_one({'_id': channel_id})
    return result.deleted_count > 0


async def get_index_channels():
    """Saare DB-added auto-index channels ki list do."""
    channels = []
    async for doc in col.find({}):
        channels.append(doc['_id'])
    return channels


async def is_index_channel(channel_id):
    doc = await col.find_one({'_id': channel_id})
    return doc is not None

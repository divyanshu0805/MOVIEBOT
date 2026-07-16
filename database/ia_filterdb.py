import re, base64, json
from struct import pack
from pyrogram.file_id import FileId
import motor.motor_asyncio
from pymongo.errors import DuplicateKeyError
from info import FILE_DB_URI, SEC_FILE_DB_URI, DATABASE_NAME, COLLECTION_NAME, MULTIPLE_DATABASE, USE_CAPTION_FILTER, MAX_B_TN

# First Database For File Saving (async, isse bot slow/frozen nahi hota)
client = motor.motor_asyncio.AsyncIOMotorClient(FILE_DB_URI)
db = client[DATABASE_NAME]
col = db[COLLECTION_NAME]

# Second Database For File Saving
sec_client = motor.motor_asyncio.AsyncIOMotorClient(SEC_FILE_DB_URI)
sec_db = sec_client[DATABASE_NAME]
sec_col = sec_db[COLLECTION_NAME]

# Choti si settings collection - common caption yaha store hoti hai
settings_col = db['bot_settings']


async def set_common_caption(caption):
    """Common caption ko save karo aur DB me maujood SAARI files pe turant apply karo."""
    await settings_col.update_one(
        {'_id': 'common_caption'},
        {'$set': {'value': caption}},
        upsert=True
    )
    result1 = await col.update_many({}, {'$set': {'caption': caption}})
    result2 = await sec_col.update_many({}, {'$set': {'caption': caption}})
    return result1.modified_count + result2.modified_count


async def remove_common_caption():
    """Common caption setting hata do (naye files pe ab apply nahi hogi)."""
    await settings_col.delete_one({'_id': 'common_caption'})


async def get_common_caption():
    doc = await settings_col.find_one({'_id': 'common_caption'})
    if not doc:
        return None
    caption = doc['value']
    # Safety net: agar kisi tarah 700 se lamba caption save ho gaya ho (purana data),
    # to use yaha automatically safe length tak truncate kar do taaki file delivery
    # MEDIA_CAPTION_TOO_LONG error se crash na ho.
    if len(caption) > 700:
        caption = caption[:697] + "..."
    return caption


async def save_file(media, chat_id=None, msg_id=None):
    """Save file in the database."""
    
    file_id = unpack_new_file_id(media.file_id)
    file_name = clean_file_name(media.file_name)
    new_file_name = f"@botroomz {file_name}"

    common_caption = await get_common_caption()
    caption = common_caption if common_caption else (media.caption.html if media.caption else None)
    
    file = {
        'file_id': file_id,
        'file_name': new_file_name,
        'file_size': media.file_size,
        'caption': caption,
        'chat_id': chat_id,
        'msg_id': msg_id
    }

    if await is_file_already_saved(file_id, file_name):
        return False, 0

    try:
        await col.insert_one(file)
        print(f"{file_name} is successfully saved.")
        return True, 1
    except DuplicateKeyError:
        print(f"{file_name} is already saved.")
        return False, 0
    except:
        if MULTIPLE_DATABASE:
            try:
                await sec_col.insert_one(file)
                print(f"{file_name} is successfully saved.")
                return True, 1
            except DuplicateKeyError:
                print(f"{file_name} is already saved.")
                return False, 0
        else:
            print("Your Current File Database Is Full, Turn On Multiple Database Feature And Add Second File Mongodb To Save File.")

def clean_file_name(file_name):
    """Clean and format the file name."""
    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(file_name)) 
    unwanted_chars = ['[', ']', '(', ')', '{', '}']
    
    for char in unwanted_chars:
        file_name = file_name.replace(char, '')
        
    old_file_name = ' '.join(filter(lambda x: not x.startswith('@') and not x.startswith('http') and not x.startswith('www.') and not x.startswith('t.me'), file_name.split()))
    new_file_name = add_space_between_e_and_number(old_file_name)
    return new_file_name

def add_space_between_e_and_number(input_string):
    # Use regex to find 'e' or 'E' followed by a digit and add a space
    output_string = re.sub(r'(e|E)([0-9])', r'1 2', input_string)
    return output_string
    
async def is_file_already_saved(file_id, file_name):
    """Check if the file is already saved in either collection."""
    found1 = {'file_name': file_name}
    found = {'file_id': file_id}

    for collection in [col, sec_col]:
        if await collection.find_one(found1) or await collection.find_one(found):
            print(f"{file_name} is already saved.")
            return True
            
    return False

def _safe_caption(file_doc):
    """Telegram media caption ki hard limit 1024 characters hai. DB me kisi bhi wajah se
    lamba caption ho (purana ya galti se), yahan hamesha safe length tak trim kar do —
    isse ye centralized jagah hai jaha se sab jagah (search, delivery, batch) files aati hai,
    isliye MEDIA_CAPTION_TOO_LONG error kabhi nahi aayega."""
    if file_doc and file_doc.get('caption') and len(file_doc['caption']) > 1024:
        file_doc['caption'] = file_doc['caption'][:1021] + "..."
    return file_doc


async def get_search_results(chat_id, query, file_type=None, max_results=10, offset=0, filter=False):
    """For given query return (results, next_offset)"""
    
    query = query.strip()
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r'(\b|[\.\+\-_])' + query + r'(\b|[\.\+\-_])'
    else:
        raw_pattern = query.replace(' ', r'.*[\s\.\+\-_]') 
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        regex = query
    filter = {'file_name': regex}
    files = []
    if MULTIPLE_DATABASE:
        cursor1 = col.find(filter).sort('$natural', -1).skip(offset).limit(max_results)
        cursor2 = sec_col.find(filter).sort('$natural', -1).skip(offset).limit(max_results)
        
        async for file in cursor1:
            files.append(_safe_caption(file))
        async for file in cursor2:
            files.append(_safe_caption(file))
    else:
        cursor = col.find(filter).sort('$natural', -1).skip(offset).limit(max_results)
        
        async for file in cursor:
            files.append(_safe_caption(file))

    total_results = await col.count_documents(filter) if not MULTIPLE_DATABASE else ((await col.count_documents(filter)) + (await sec_col.count_documents(filter)))
    next_offset = "" if (offset + max_results) >= total_results else (offset + max_results)

    return files, next_offset, total_results

async def get_bad_files(query, file_type=None, use_filter=False):
    """For given query return (results, next_offset)"""
    query = query.strip()
    
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = rf'(\b|[.+-_]){query}(\b|[.+-_])'
    else:
        raw_pattern = query.replace(' ', r'.*[s.+-_]')
    
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except re.error:
        return [], 0

    filter_criteria = {'file_name': regex}
    if USE_CAPTION_FILTER:
        filter_criteria = {'$or': [filter_criteria, {'caption': regex}]}

    async def count_documents(collection):
        return await collection.count_documents(filter_criteria)

    if MULTIPLE_DATABASE:
        total_results = (await count_documents(col)) + (await count_documents(sec_col))
    else:
        total_results = await count_documents(col)

    async def find_documents(collection):
        return [_safe_caption(file) async for file in collection.find(filter_criteria)]

    if MULTIPLE_DATABASE:
        files = (await find_documents(col)) + (await find_documents(sec_col))
    else:
        files = await find_documents(col)

    return files, total_results

async def get_file_details(query):
    file = await col.find_one({'file_id': query})
    if not file:
        file = await sec_col.find_one({'file_id': query})
    return _safe_caption(file)

def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")
    
def unpack_new_file_id(new_file_id):
    """Return file_id"""
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash
        )
    )
    return file_id

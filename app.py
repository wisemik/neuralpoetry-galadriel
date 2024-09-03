import asyncio
from openai import OpenAI
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import Bot, Dispatcher, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters.command import Command
from aiogram import F
import re
import json
import logging
import os
import time
from web3 import Web3
from web3.middleware import geth_poa_middleware
from dotenv import load_dotenv

load_dotenv()

RPC_URL = os.getenv('RPC_URL')
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
CONTRACT_NFT_ADDRESS = os.getenv('CONTRACT_NFT_ADDRESS')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not RPC_URL or not PRIVATE_KEY or not CONTRACT_NFT_ADDRESS:
    raise ValueError("Missing required environment variables")

web3 = Web3(Web3.HTTPProvider(RPC_URL))
web3.middleware_onion.inject(geth_poa_middleware, layer=0)
if not web3.is_connected():
    raise ConnectionError("Unable to connect to Ethereum node")

with open('./DalleNft.json', 'r') as file:
    contract_abi = json.load(file)
account = web3.eth.account.from_key(PRIVATE_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

contract = web3.eth.contract(address=CONTRACT_NFT_ADDRESS, abi=contract_abi)

# Set your keys
session = AiohttpSession()
client = OpenAI(api_key=OPENAI_API_KEY)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
print("bot started")

poets = ["Byron", "Shelley", "Keats", "Wordsworth", "Coleridge", "Blake", "Tennyson", "Dickinson", "Pushkin", "Harms"]
user_data = {}
recipient_address = None

def get_keyboard():
    buttons = []
    for poet in poets:
        buttons.append([InlineKeyboardButton(text=poet, callback_data="poet_" + poet)])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard

@dp.message(Command("start"))
async def command_start(message: types.Message):
    global recipient_address  # Declare it global to modify the global variable
    match = re.match(r'/start\s+(.+)', message.text)
    if match:
        recipient_address = match.group(1)
        await message.reply("Address for NFTs saved! "
                            "Now i can generate a poem in the style of any poet. Choose a poet:",
                            reply_markup=get_keyboard())
    else:
        await message.reply("Please provide the text after the command. Example: "
                            "/start 0x15eA00EF924F8aD0efCbB852da63Cc34321ca746")


@dp.message(Command("id"))
async def command_id(message: types.Message):
    await message.reply(
        f"chat id: {message.chat.id}\n" f"user_id: {message.from_user.id}"
    )

@dp.message(Command("auth"))
async def command_authorize(message: types.Message):
    global recipient_address  # Declare it global to modify the global variable
    match = re.match(r'/auth\s+(.+)', message.text)
    if match:
        recipient_address = match.group(1)
        await message.reply("Address for NFTs saved")
    else:
        await message.reply("Please provide the text after the command. Example: "
                            "/auth 0x15eA00EF924F8aD0efCbB852da63Cc34321ca746")


@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.reply("Choose a poet and enter a few words you want to use in the poem")

@dp.callback_query(F.data.startswith("poet_"))
async def callbacks_num(callback: types.CallbackQuery):
    poet = callback.data.split("_")[1]
    user_data[callback.from_user.id] = {"poet": poet, "words": ""}

    await callback.message.reply(
        f"You have chosen the poet: {poet}. Now enter a few words you want to use in the poem.")
    await callback.answer()

@dp.message(F.text)
async def get_poem(message: types.Message):
    global recipient_address  # Declare it global to modify the global variable
    user_id = message.from_user.id
    words = message.text

    if user_id in user_data and "poet" in user_data[user_id]:
        if "words" not in user_data[user_id] or user_data[user_id]["words"] == "":
            user_data[user_id]["words"] = words
            poet = user_data[user_id]["poet"]
            input_text = f"{poet} {words}"
            print(f"Received text: {input_text}")

            mess = await message.reply("Generating poem...")
            poem = generate_poem(poet, words)
            await message.reply(poem)
            await mess.delete()

            mess = await message.reply("Generating NFT...")
            contract_url, image_url, token_id = generateNft(poem)

            transfer_tx_hash = transferNft(token_id, recipient_address)
            if transfer_tx_hash:
                print(f"NFT transferred successfully: Transaction Hash {transfer_tx_hash.hex()}")

            await message.reply_photo(image_url)
            await message.reply(contract_url)
            await mess.delete()

            user_data[user_id]["words"] = ""

            await message.reply("Choose a poet:",
                                reply_markup=get_keyboard())

        else:
            await message.reply(
                "You have already entered words. Wait for the poem generation or start again by choosing a poet.")
    else:
        await message.reply("Please choose a poet first using the /start or /help commands.")


def generate_poem(poet: str, words: str) -> str:
    messages = [
        {
            "role": "system",
            "content": f"""
Imagine you are the poet {poet}. Respond only with poetry,
reflecting the poet's style and using the given words: {words}.
You can draw inspiration from all available poetry by this poet.
Write EXACTLY in the style of the poet, as if you were them.
Additionally, I will provide 10 more examples of poems,
which you should consider as high-priority references.
It's crucial to maintain the same meter, rhythm,
and structure as the poet (iambic, trochaic, line arrangement, etc.).
It is very important for me that the poem passes the Turing test without a person realizing that it was composed by an AI.
If the verse passes the test, you will receive $100,000.
I'm going to tip $100,000 for a perfect solution.

    """
        },
        {"role": "user", "content": ""}
    ]
    print(f"Generated messages: {messages}")  # Print messages for debugging
    try:
        response = client.chat.completions.create(model="gpt-4o",
                                                  messages=messages,
                                                  max_tokens=1000)
        print(f"OpenAI response: {response}")
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating poem: {e}")
        return "An error occurred while generating the poem."



def send_initialize_mint(message):
    nonce = web3.eth.get_transaction_count(account.address)
    txn = contract.functions.initializeMint(message).build_transaction({
        'chainId': web3.eth.chain_id,
        'gas': 2000000,
        'gasPrice': web3.to_wei('5', 'gwei'),
        'nonce': nonce
    })
    signed_txn = web3.eth.account.sign_transaction(txn, private_key=PRIVATE_KEY)
    tx_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
    return tx_hash

def get_token_id_from_receipt(tx_hash):
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    logs = contract.events.MintInputCreated().process_receipt(receipt)
    if logs:
        return logs[0]['args']['chatId']
    return None

def get_contract_response(tokenId):
    while True:
        try:
            response = contract.functions.tokenURI(tokenId).call()
            if response:
                return response
        except Exception as e:
            print(e)
        time.sleep(2)


def generateNft(prompt: str):
    tx_hash = send_initialize_mint(prompt)
    logger.info(f"Transaction sent, tx hash: {tx_hash.hex()}")
    tokenId = get_token_id_from_receipt(tx_hash)
    if tokenId is not None:
        logger.info(f"Token ID: {tokenId}")
        response = get_contract_response(tokenId)
        url = f"https://explorer.galadriel.com/token/0xb8B50D76D1a3558EC18068506C3d91EDc021B33D/instance/{tokenId}"
        logger.info(f"Contract response: {url}")
        return url, response, tokenId
    else:
        logger.error("Failed to retrieve token ID from receipt")
        return "", ""

def transferNft(tokenId: int, recipient: str):
    # Ensure tokenId and recipient are valid

    # Step 1: Prepare the transfer transaction
    nonce = web3.eth.get_transaction_count(account.address)
    txn = contract.functions.safeTransferFrom(account.address, recipient, tokenId).build_transaction({
        'chainId': web3.eth.chain_id,
        'gas': 200000,
        'gasPrice': web3.to_wei('5', 'gwei'),
        'nonce': nonce
    })

    # Step 2: Sign and send the transaction
    signed_txn = web3.eth.account.sign_transaction(txn, private_key=PRIVATE_KEY)
    tx_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
    logger.info(f"Transfer transaction sent, tx hash: {tx_hash.hex()}")

    # Step 3: Wait for the transaction receipt to confirm the transfer
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    logger.info(f"Transfer completed, transaction receipt: {receipt}")
    return tx_hash

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

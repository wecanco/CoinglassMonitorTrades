import datetime
import os
import asyncio
import websockets
import json
import requests
import logging
from typing import Dict, Set, List
from dotenv import load_dotenv

load_dotenv()

# تنظیمات
HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# تنظیم لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# لیست والت‌ها
WALLET_ADDRESSES = json.loads(open('wallets.json', 'r').read())


class TelegramSender:
    def __init__(self):
        self.message_queue = asyncio.Queue()
        self.is_running = False

    async def start(self):
        self.is_running = True
        asyncio.create_task(self._process_queue())

    async def _process_queue(self):
        while self.is_running:
            try:
                if not self.message_queue.empty():
                    message = await self.message_queue.get()
                    await self._send_message(message)
                    await asyncio.sleep(3)  # مکث 10 ثانیه بین پیام‌ها
                else:
                    await asyncio.sleep(1)  # چک کردن کیو هر ثانیه
            except Exception as e:
                logger.error(f"Error in message queue processor: {e}")
                await asyncio.sleep(5)

    async def _send_message(self, message: str):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }

            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram Message Sent.")
            else:
                logger.error(f"Send TG Message Error: {response.status_code} - {response.text}")

        except Exception as e:
            logger.error(f"TG Error: {e}")

    async def queue_message(self, message: str):
        await self.message_queue.put(message)
        logger.info(f"Message queued. Queue size: {self.message_queue.qsize()}")

    def stop(self):
        self.is_running = False


class HyperliquidMonitor:
    def __init__(self, wallet_addresses: List[str], telegram_sender: TelegramSender):
        self.wallet_addresses = [addr.lower() for addr in wallet_addresses]
        self.active_positions: Dict[str, Dict[str, Dict]] = {}  # wallet -> position_key -> position
        self.active_fills: Dict[str, Dict[str, Dict]] = {}  # wallet -> fill_key -> fill
        self.is_connected = False
        self.telegram_sender = telegram_sender

        # بارگذاری داده‌های قبلی برای هر والت
        for wallet in self.wallet_addresses:
            self.active_positions[wallet] = {}
            try:
                with open(f'storage/active_fills_{wallet[-8:]}.json', 'r') as f:
                    self.active_fills[wallet] = json.loads(f.read())
            except FileNotFoundError:
                self.active_fills[wallet] = {}

    def format_position_message(self, position: Dict, action: str, wallet_address: str) -> str:
        symbol = position.get('coin', 'N/A')
        side = position.get('side', 'N/A')
        size = position.get('szi', '0')
        entry_price = position.get('entryPx', '0')
        unrealized_pnl = position.get('unrealizedPnl', '0')
        leverage = position.get('leverage', {})
        leverage_value = leverage.get('value', 0)
        leverage_type = leverage.get('type', 0)

        try:
            size_float = float(size)
            entry_price_float = float(entry_price)
            pnl_float = float(unrealized_pnl)

            size_formatted = f"{size_float:,.4f}".rstrip('0').rstrip('.')
            entry_price_formatted = f"{entry_price_float:,.4f}".rstrip('0').rstrip('.')
            pnl_formatted = f"{pnl_float:,.2f}"

        except (ValueError, TypeError):
            size_formatted = size
            entry_price_formatted = entry_price
            pnl_formatted = unrealized_pnl
            pnl_float = 0

        if action == "Opened":
            emoji = "🟢" if side == "A" else "🔴"  # A = Long (خرید), B = Short (فروش)
        else:
            emoji = "⚪"

        pnl_emoji = "💰" if pnl_float > 0 else "💸" if pnl_float < 0 else "💱"

        side_text = "Buy (Long)" if side == "A" else "Sell (Short)" if side == "B" else side

        message = f"""
{emoji} <b>Position {action} {leverage_value}x {leverage_type}</b>

💎 <b>Coin:</b> {symbol}
📊 <b>Type:</b> {side_text}  
📏 <b>Margin:</b> {size_formatted}
💵 <b>Entry:</b> ${entry_price_formatted}
{pnl_emoji} <b>Pnl:</b> ${pnl_formatted}

🕐 <b>Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔗 <b>Wallet:</b> <code>{wallet_address[-8:]}</code>
        """.strip()

        return message

    def format_fills_message(self, position: Dict, wallet_address: str) -> str:
        symbol = position.get('coin', 'N/A')
        side = position.get('side', 'N/A')
        dir = position.get('dir', 'N/A')
        entry_price = position.get('px', '0')
        margin = float(position.get('sz', '0'))
        amount = abs(float(position.get('startPosition', '0')))
        time = position.get('time', '0')
        date = datetime.datetime.fromtimestamp(time / 1e3)
        closed_pnl = position.get('closedPnl', '0')
        leverage_type = 'Cross' if position.get('crossed') else 'Isolate'

        if (datetime.datetime.now() - date > datetime.timedelta(hours=1)) or amount < 1000:
            return ""

        try:
            size_float = float(margin)
            entry_price_float = float(entry_price)
            pnl_float = float(closed_pnl)

            size_formatted = f"{size_float:,.4f}".rstrip('0').rstrip('.')
            entry_price_formatted = f"{entry_price_float:,.4f}".rstrip('0').rstrip('.')
            pnl_formatted = f"{pnl_float:,.2f}"
            amount_formatted = f"{amount:,.2f}"

        except (ValueError, TypeError):
            size_formatted = margin
            entry_price_formatted = entry_price
            pnl_formatted = closed_pnl
            pnl_float = 0
            amount_formatted = 0
        except Exception as e:
            logger.error(f"Format Message Error: {e}")

        if "Open" in dir:
            emoji = "🔵" if side == "A" else "🔵"  # A = Long (خرید), B = Short (فروش)
        else:
            emoji = "⚪"

        if not pnl_float:
            pnl_float = 0

        pnl_emoji = "💰" if pnl_float > 0 else "💸" if pnl_float < 0 else "💱"

        side_text = "🟢 Buy (Long)" if side == "B" else "🔴 Sell (Short)" if side == "A" else str(side)

        message = f"""
{emoji} <b>{dir} ({leverage_type})</b>

🆔 <b>id:</b> <code>{position.get('tid', 'N/A')}</code>
💎 <b>Symbol:</b> {symbol}
📊 <b>Type:</b> {side_text}  
📏 <b>Margin:</b> {size_formatted} (${amount_formatted})
💵 <b>Entry:</b> {entry_price_formatted}
{pnl_emoji} <b>Pnl:</b> {pnl_formatted}
🕐 <b>Time:</b> {date.strftime('%Y-%m-%d %H:%M:%S')}
🔗 <b>Wallet:</b> <a href="https://www.coinglass.com/hyperliquid/{wallet_address}">{wallet_address}</a>
        """.strip()

        return message

    def process_position_update(self, positions: list, wallet_address: str):
        current_positions = {}

        for pos in positions:
            _type = pos.get('type')
            pos = pos.get('position')
            if not pos:
                continue
            coin = pos.get('coin')
            pos['side'] = 'short' if pos.get('entryPx') < pos.get('liquidationPx') else 'long'
            if coin:
                position_key = f"{coin}_{pos.get('side')}"
                current_positions[position_key] = pos

        # بررسی پوزیشن‌های جدید
        for key, pos in current_positions.items():
            if key not in self.active_positions[wallet_address]:
                logger.info(f"New Position Detected: {key} for wallet {wallet_address[-8:]}")
                message = self.format_position_message(pos, "Opened", wallet_address)
                asyncio.create_task(self.telegram_sender.queue_message(message))

        # بررسی پوزیشن‌های بسته شده
        for key, pos in self.active_positions[wallet_address].items():
            if key not in current_positions:
                logger.info(f"Position Closed: {key} for wallet {wallet_address[-8:]}")
                message = self.format_position_message(pos, "Closed", wallet_address)
                asyncio.create_task(self.telegram_sender.queue_message(message))

        self.active_positions[wallet_address] = current_positions.copy()

    def process_fills_update(self, fills: list, wallet_address: str):
        current_fills = {}

        for fill in fills:
            coin = fill.get('coin')
            fills_key = f"{coin}_{fill.get('tid')}"
            current_fills[fills_key] = fill

        for key, pos in current_fills.items():
            if key not in self.active_fills[wallet_address]:
                logger.info(f"New fills Detected: {key} for wallet {wallet_address[-8:]}")
                message = self.format_fills_message(pos, wallet_address)
                if message:
                    asyncio.create_task(self.telegram_sender.queue_message(message))

        self.active_fills[wallet_address] = {
            **(self.active_fills[wallet_address] if self.active_fills[wallet_address] else {}), **current_fills.copy()}

        # ذخیره فایل برای هر والت جداگانه
        with open(f'storage/active_fills_{wallet_address[-8:]}.json', 'w') as f:
            f.write(json.dumps(self.active_fills[wallet_address]))

    async def handle_message(self, message: str):
        try:
            data = json.loads(message)

            if data.get('channel') == 'userFills' and data.get('data'):
                user_data = data['data']
                user_wallet = user_data.get('user', '').lower()

                if user_wallet in self.wallet_addresses:
                    fills = user_data.get('fills')
                    if fills:
                        logger.info(f"Get {len(fills)} fills For Wallet {user_wallet[-8:]}")
                        self.process_fills_update(fills, user_wallet)

            elif data.get('channel') == 'webData2' and data.get('data'):
                user_data = data['data']
                user_wallet = user_data.get('user', '').lower()

                if user_wallet in self.wallet_addresses:
                    positions = user_data.get('clearinghouseState', {}).get('assetPositions')
                    if positions:
                        logger.info(f"Get {len(positions)} Positions For Wallet {user_wallet[-8:]}")
                        self.process_position_update(positions, user_wallet)

        except json.JSONDecodeError:
            logger.error("Error JSON")
        except Exception as e:
            logger.error(f"Process Message Error: {e}")

    async def subscribe_to_wallets(self, websocket):
        # Subscribe to userFills for all wallets
        for wallet in self.wallet_addresses:
            subscription_message = {
                "method": "subscribe",
                "subscription": {
                    "type": "userFills",
                    "user": wallet
                }
            }
            await websocket.send(json.dumps(subscription_message))
            logger.info(f"Subscribed to userFills for wallet {wallet[-8:]}")
            await asyncio.sleep(0.1)  # مکث کوتاه بین subscribe ها

        # # Subscribe to webData2 for all wallets
        # for wallet in self.wallet_addresses:
        #     subscription_message = {
        #         "method": "subscribe",
        #         "subscription": {
        #             "type": "webData2",
        #             "user": wallet
        #         }
        #     }
        #     await websocket.send(json.dumps(subscription_message))
        #     logger.info(f"Subscribed to webData2 for wallet {wallet[-8:]}")
        #     await asyncio.sleep(0.1)  # مکث کوتاه بین subscribe ها

    async def connect_and_monitor(self):
        while True:
            try:
                logger.info("Connect to Hyperliquid WebSocket...")

                async with websockets.connect(
                        HYPERLIQUID_WS_URL,
                        ping_interval=20,
                        ping_timeout=10
                ) as websocket:

                    self.is_connected = True
                    logger.info("Connected!")

                    # پیام شروع مانیتورینگ
                    start_message = f"""
🚀 <b>Multi-Wallet Monitoring Started</b>

📊 <b>Wallets:</b> {len(self.wallet_addresses)}
🕐 <b>Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ System is Ready.
                    """.strip()

                    # await self.telegram_sender.queue_message(start_message)

                    await self.subscribe_to_wallets(websocket)

                    async for message in websocket:
                        await self.handle_message(message)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket Connection Closed. retry to connect...")
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Connection Error: {e}")
                await asyncio.sleep(10)

            finally:
                self.is_connected = False


async def main():
    # ایجاد sender تلگرام
    telegram_sender = TelegramSender()
    await telegram_sender.start()

    # ایجاد مانیتور با لیست والت‌ها
    monitor = HyperliquidMonitor(WALLET_ADDRESSES, telegram_sender)

    try:
        await monitor.connect_and_monitor()
    finally:
        telegram_sender.stop()


if __name__ == "__main__":
    print("🚀 Start Multi-Wallet Hyperliquid Monitoring...")
    print(f"💼 Monitoring {len(WALLET_ADDRESSES)} wallets")
    print("💡 Stop: Ctrl+C")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️App Stopped")
    except Exception as e:
        print(f"❌ error: {e}")

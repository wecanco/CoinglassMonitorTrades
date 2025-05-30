import datetime
from time import sleep

import asyncio
import websockets
import json
import requests
import logging
from typing import Dict, Set

# تنظیمات
HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"
TELEGRAM_BOT_TOKEN = "TOKEN"
TELEGRAM_CHAT_ID = "-1002568768844"  # https://t.me/WhaleTradesMonitoring

# تنظیم لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class HyperliquidMonitor:
    def __init__(self, wallet_address: str):
        self.wallet_address = wallet_address.lower()
        self.active_positions: Dict[str, Dict] = {}
        # self.active_fills: Dict[str, Dict] = {}
        self.is_connected = False
        self.active_fills = json.loads(open('active_fills.json', 'r').read())

    async def send_telegram_message(self, message: str):
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

    def format_position_message(self, position: Dict, action: str) -> str:
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
🔗 <b>Wallet:</b> <code>{self.wallet_address}</code>
        """.strip()

        return message

    def format_fills_message(self, position: Dict) -> str:
        symbol = position.get('coin', 'N/A')
        side = position.get('side', 'N/A')
        dir = position.get('dir', 'N/A')
        entry_price = position.get('px', '0')
        margin = position.get('sz', '0')
        amount = abs(float(position.get('startPosition', '0')))
        time = position.get('time', '0')
        date = datetime.datetime.fromtimestamp(time / 1e3)
        closed_pnl = position.get('closedPnl', '0')
        leverage_type = 'Cross' if position.get('crossed') else 'Isolate'

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

        if "Open" in dir:
            emoji = "🔵" if side == "A" else "🔴"  # A = Long (خرید), B = Short (فروش)
        else:
            emoji = "⚪"

        pnl_emoji = "💰" if pnl_float > 0 else "💸" if pnl_float < 0 else "💱"

        side_text = "🟢 Buy (Long)" if side == "B" else "🔴 Sell (Short)" if side == "A" else side

        message = f"""
{emoji} <b>{dir} {leverage_type}</b>

💎 <b>id:</b> <code>{position.get('tid', 'N/A')}</code>
💎 <b>Symbol:</b> {symbol}
📊 <b>Type:</b> {side_text}  
📏 <b>Margin:</b> {size_formatted} (${amount_formatted})
💵 <b>Entry:</b> {entry_price_formatted}
{pnl_emoji} <b>Pnl:</b> ${pnl_formatted}

🕐 <b>Time:</b> {date.strftime('%Y-%m-%d %H:%M:%S')}
🔗 <b>Wallet:</b> <a href="https://www.coinglass.com/hyperliquid/{self.wallet_address}">{self.wallet_address}</a>
        """.strip()

        return message

    def process_position_update(self, positions: list):
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

        for key, pos in current_positions.items():
            if key not in self.active_positions:
                logger.info(f"New Position Detected: {key}")
                message = self.format_position_message(pos, "Opened")
                asyncio.create_task(self.send_telegram_message(message))

        for key, pos in self.active_positions.items():
            if key not in current_positions:
                logger.info(f"Position Closed: {key}")
                message = self.format_position_message(pos, "Closed")
                asyncio.create_task(self.send_telegram_message(message))

        self.active_positions = current_positions.copy()

    def process_fills_update(self, fills: list):
        current_fills = {}

        for fill in fills:
            coin = fill.get('coin')
            fills_key = f"{coin}_{fill.get('tid')}"
            current_fills[fills_key] = fill

        for key, pos in current_fills.items():
            if key not in self.active_fills:
                logger.info(f"New fills Detected: {key}")
                message = self.format_fills_message(pos)
                asyncio.create_task(self.send_telegram_message(message))

        self.active_fills = current_fills.copy()
        open('active_fills.json', 'w').write(json.dumps(self.active_fills))

    async def handle_message(self, message: str):
        try:
            data = json.loads(message)

            if data.get('channel') == 'userFills' and data.get('data'):
                user_data = data['data']

                if user_data.get('user', '').lower() == self.wallet_address:
                    fills = user_data.get('fills')
                    if fills:
                        logger.info(f"Get {len(fills)} fills For Wallet {self.wallet_address}")
                        self.process_fills_update(fills)

            elif data.get('channel') == 'webData2' and data.get('data'):
                user_data = data['data']

                if user_data.get('user', '').lower() == self.wallet_address:
                    # {
                    #     "coin": "USDC",
                    #     "token": 0,
                    #     "total": "53410.70670727",
                    #     "hold": "0.0",
                    #     "entryNtl": "0.0"
                    # },
                    spot_state = user_data.get('spotState', {}).get('balances')
                    open_orders = user_data.get('openOrders')
                    perps_at_open_interest_cap = user_data.get('perpsAtOpenInterestCap')
                    positions = user_data.get('clearinghouseState', {}).get('assetPositions')
                    if positions:
                        logger.info(f"Get {len(positions)} Positions For Wallet {self.wallet_address}")
                        # positions.reverse()
                        self.process_position_update(positions)

        except json.JSONDecodeError:
            logger.error("Error JSON")
        except Exception as e:
            logger.error(f"Process Message Error: {e}")

    async def socket_subscribe(self, websocket):
        subscription_message = {
            "method": "subscribe",
            "subscription": {
                "type": "user",
                "user": self.wallet_address
            }
        }

        await websocket.send(json.dumps(subscription_message))
        logger.info(f"Subscription on User Channel {self.wallet_address}")

    async def socket_userFills(self, websocket):
        subscription_message = {
            "method": "subscribe",
            "subscription": {
                "type": "userFills",
                "user": self.wallet_address
            }
        }

        await websocket.send(json.dumps(subscription_message))
        logger.info(f"socket userFills {self.wallet_address}")

    async def socket_webData2(self, websocket):
        subscription_message = {
            "method": "subscribe",
            "subscription": {
                "type": "webData2",
                "user": self.wallet_address
            }
        }

        await websocket.send(json.dumps(subscription_message))
        logger.info(f"socket webData2 {self.wallet_address}")

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

#                     start_message = f"""
# 🚀 <b>Monitoring Started...</b>
#
# 📍 <b>Wallet:</b> <code>{self.wallet_address}</code>
# 🕐 <b>Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
#
# ✅ System is Ready.
#                     """.strip()
#
#                     await self.send_telegram_message(start_message)

                    await self.socket_subscribe(websocket)
                    await self.socket_userFills(websocket)
                    # await self.socket_webData2(websocket)

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
    wallet_address = "0x45d26f28196d226497130c4bac709d808fed4029"

    monitor = HyperliquidMonitor(wallet_address)

    await monitor.connect_and_monitor()


if __name__ == "__main__":
    print("🚀 Start Hyperliquid Monitoring...")
    print("💡 Stop: Ctrl+C")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️App Stopped")
    except Exception as e:
        print(f"❌ error: {e}")

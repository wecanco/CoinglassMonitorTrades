import re
import base64
import zlib
import binascii
import urllib.parse
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


def Ydecoder(t_base64: str, e_key_str: str) -> str:
    try:
        # 1. Base64 decode input
        encrypted = base64.b64decode(t_base64 + '=' * ((4 - len(t_base64) % 4) % 4))

        # 2. AES decrypt (ECB mode, PKCS7 padding)
        cipher = AES.new(e_key_str.encode('utf-8'), AES.MODE_ECB)
        decrypted = unpad(cipher.decrypt(encrypted), AES.block_size)

        # 3. Convert decrypted bytes to hex string (as in .toString(qt.enc.Hex))
        hex_str = decrypted.hex()

        # 4. Convert hex string to bytes
        byte_array = bytes.fromhex(hex_str)

        # 5. zlib raw inflate (decompress)
        decompressed = zlib.decompress(byte_array, wbits=-zlib.MAX_WBITS)

        # 6. Convert bytes to string (simulate JS: String.fromCharCode.apply + escape + decodeURIComponent)
        raw_text = decompressed.decode('latin1')  # String.fromCharCode
        unescaped = urllib.parse.unquote(raw_text)  # decodeURIComponent(escape(...))

        # 7. Remove surrounding quotes if present
        if unescaped.startswith('"'):
            unescaped = unescaped[1:]
        if unescaped.endswith('"'):
            unescaped = unescaped[:-1]

        return unescaped

    except Exception as ex:
        return f"❌ Error in Ydecoder: {ex}"


# تابع ساخت کلید نهایی رمزگشایی
def build_decryption_key(url: str, user_header: str) -> str:
    # استخراج بخش "api/..." از URL
    match = re.search(r'/api/[^?]+', url)
    if not match:
        raise ValueError("URL must contain '/api/...' path")

    path_part = match.group(0)

    # ساخت رشته base64
    base = f"coinglass{path_part}coinglass"
    b64_encoded = base64.b64encode(base.encode()).decode()[:16]

    # اعمال تابع Yt روی header (user) با کلید
    # user_bytes = user_header.encode('utf-8')
    return Ydecoder(user_header, b64_encoded)


ciphertext = "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"
url = "https://capi.coinglass.com/api/hyperliquid/topPosition/action"
user_header = "bI5/hWYpJJ1vQFDUaSeT9tOvDoxI/J5tKbJpV6X7GQh/UDUoiTOfkPwwxCNuSzik"  # مقدار header `t.headers.user` از درخواست

key = build_decryption_key(url, user_header)
print("🔑 AES Key:", key)
result = Ydecoder(ciphertext, key)
print("result:", result)

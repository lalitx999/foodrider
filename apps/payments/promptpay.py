import base64
import io
import os
from decimal import Decimal, InvalidOperation
import qrcode

def _field(identifier: str, value: str) -> str:
    return f'{identifier}{len(value):02d}{value}'

def _crc16(payload: str) -> str:
    crc = 0xFFFF
    for byte in payload.encode('ascii'):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f'{crc:04X}'

def create_promptpay_qr(amount) -> tuple[str, str]:
    account = os.environ.get('PLATFORM_PROMPTPAY_ACCOUNT', '').replace('-', '').replace(' ', '')
    if not account:
        raise ValueError('ยังไม่ได้ตั้งค่า PLATFORM_PROMPTPAY_ACCOUNT')
    try:
        normalized_amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    except InvalidOperation as error:
        raise ValueError('ยอดชำระเงินไม่ถูกต้อง') from error
    if normalized_amount <= 0:
        raise ValueError('ยอดชำระเงินต้องมากกว่าศูนย์')
    if account.isdigit() and len(account) == 10:
        proxy = _field('01', '0066' + account[1:])
    elif account.isdigit() and len(account) == 13:
        proxy = _field('02', account)
    else:
        raise ValueError('PromptPay ต้องเป็นเบอร์โทร 10 หลักหรือเลขประจำตัว 13 หลัก')
    merchant_info = _field('00', 'A000000677010111') + proxy
    payload = ''.join([_field('00', '01'), _field('01', '12'), _field('29', merchant_info), _field('53', '764'), _field('54', f'{normalized_amount:.2f}'), _field('58', 'TH'), '6304'])
    payload += _crc16(payload)
    image = qrcode.make(payload)
    output = io.BytesIO(); image.save(output, format='PNG')
    return f'data:image/png;base64,{base64.b64encode(output.getvalue()).decode()}', account

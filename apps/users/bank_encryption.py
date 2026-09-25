import os

from cryptography.fernet import Fernet, InvalidToken


class BankDataEncryptionError(Exception):
    pass


def _cipher() -> Fernet:
    key = os.environ.get('BANK_DATA_ENCRYPTION_KEY', '').strip()
    if not key:
        raise BankDataEncryptionError('ยังไม่ได้ตั้งค่า BANK_DATA_ENCRYPTION_KEY')
    try:
        return Fernet(key.encode('utf-8'))
    except (ValueError, TypeError) as error:
        raise BankDataEncryptionError('BANK_DATA_ENCRYPTION_KEY ไม่อยู่ในรูปแบบ Fernet key ที่ถูกต้อง') from error


def encrypt_bank_value(value: str) -> str:
    if not value:
        return ''
    return _cipher().encrypt(value.encode('utf-8')).decode('utf-8')


def decrypt_bank_value(value: str) -> str:
    if not value:
        return ''
    try:
        return _cipher().decrypt(value.encode('utf-8')).decode('utf-8')
    except InvalidToken as error:
        raise BankDataEncryptionError('ไม่สามารถถอดรหัสข้อมูลบัญชีได้') from error


def mask_encrypted_bank_value(value: str, visible_characters: int = 4) -> str:
    plaintext = decrypt_bank_value(value)
    if len(plaintext) <= visible_characters:
        return '*' * len(plaintext)
    return f"{'*' * (len(plaintext) - visible_characters)}{plaintext[-visible_characters:]}"

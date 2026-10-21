"""Local build expiry, measured in Beijing time regardless of the PC timezone."""
from datetime import datetime, timedelta, timezone

BEIJING_TIME = timezone(timedelta(hours=8), 'Asia/Shanghai')
VALID_THROUGH = '2027-05-20'
EXPIRES_AT = datetime.fromisoformat(VALID_THROUGH).replace(tzinfo=BEIJING_TIME) + timedelta(days=1)
EXPIRY_MESSAGE = '软件已过期，请联系1564532736@qq.com'


def is_expired(now=None):
    current = now if now is not None else datetime.now(BEIJING_TIME)
    if current.tzinfo is None:
        current = current.replace(tzinfo=BEIJING_TIME)
    return current >= EXPIRES_AT


def ensure_active():
    if is_expired():
        raise RuntimeError(EXPIRY_MESSAGE)

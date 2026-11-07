"""Internal build-time activation check, measured in Beijing time."""
from datetime import datetime, timedelta, timezone

BEIJING_TIME = timezone(timedelta(hours=8), 'Asia/Shanghai')
VALID_THROUGH = '2027-05-20'
EXPIRES_AT = datetime.fromisoformat(VALID_THROUGH).replace(tzinfo=BEIJING_TIME) + timedelta(days=1)


def is_expired(now=None):
    current = now if now is not None else datetime.now(BEIJING_TIME)
    if current.tzinfo is None:
        current = current.replace(tzinfo=BEIJING_TIME)
    return current >= EXPIRES_AT

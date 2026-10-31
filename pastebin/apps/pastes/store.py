import random
import string
import threading

ALPHABET = string.ascii_letters + string.digits
MAX_SIZE = 1024 * 1024  # 1 MB


pastes = {}
idem_keys = {}
lock = threading.Lock()


def new_id():
    while True:
        pid = "".join(random.choice(ALPHABET) for _ in range(8))
        if pid not in pastes:
            return pid

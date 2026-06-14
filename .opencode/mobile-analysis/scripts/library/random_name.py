import secrets
import string

from . import config


def generate_random_name(min_len: int = config.RANDOM_NAME_MIN_LEN,
                         max_len: int = config.RANDOM_NAME_MAX_LEN) -> str:
    """Generate a random lowercase-alphanumeric name of random length in [min_len, max_len].

    Uses secrets module for cryptographically secure randomness.
    Lowercase only to avoid Android filesystem case-sensitivity issues.
    """
    length = secrets.randbelow(max_len - min_len + 1) + min_len
    return "".join(secrets.choice(config.RANDOM_NAME_CHARSET) for _ in range(length))
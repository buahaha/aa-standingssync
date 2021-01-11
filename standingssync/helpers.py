from bravado.exception import HTTPError

from .providers import esi


def is_esi_online() -> bool:
    """Checks if the Eve servers are online. Returns True if there are, else False"""
    try:
        status = esi.client.Status.get_status().results()
        if status.get("vip"):
            return False

    except HTTPError:
        return False

    return True

DEV = False


def _set_dev(value) -> None:
    global DEV  
    DEV = value


def set_dev(value) -> None:
    _set_dev(value)

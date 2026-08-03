from .epayment_form import *

def strtobool(val) -> bool:
    if not val:
        return False

    if val is True:
        return True

    val = val.lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    elif val in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    else:
        raise ValueError("invalid truth value %r" % (val,))

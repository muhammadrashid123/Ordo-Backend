import os

from dotenv import load_dotenv

load_dotenv()
STAGE = os.environ.get("STAGE")
if STAGE == "prod":  # noqa
    from .production import *  # noqa
elif STAGE == "staging":  # noqa
    from .staging import *  # noqa
else:
    from .local import *  # noqa

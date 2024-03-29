from uvicorn.workers import UvicornWorker


class OrdoUvicornWorker(UvicornWorker):
    CONFIG_KWARGS = {"loop": "uvloop", "http": "httptools", "lifespan": "on"}

import os


STAGE = os.environ.get("STAGE")


if STAGE in ["local", "test"]:
    def get_secret_value(secret_name):
        return os.environ.get(secret_name)
else:
    import botocore
    import botocore.session
    from aws_secretsmanager_caching import SecretCache, SecretCacheConfig

    client = botocore.session.get_session().create_client('secretsmanager')
    cache_config = SecretCacheConfig()
    cache = SecretCache(config=cache_config, client=client)

    def get_secret_value(secret_value):
        return cache.get_secret_string(f"{STAGE}/{secret_value}")

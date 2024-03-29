class AsyncFakeSemaphore:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return


fake_semaphore = AsyncFakeSemaphore()

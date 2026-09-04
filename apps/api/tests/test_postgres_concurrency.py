from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection

from core.models import NumberSequence


@pytest.mark.django_db(transaction=True)
def test_number_sequence_is_unique_under_postgres_concurrency():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is verified on PostgreSQL in CI")
    key = f"concurrency-{uuid4().hex}"
    workers = 8
    barrier = Barrier(workers)

    def allocate():
        close_old_connections()
        barrier.wait()
        try:
            return NumberSequence.next(key)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        values = list(pool.map(lambda _index: allocate(), range(workers)))

    assert sorted(values) == list(range(1, workers + 1))

"""Embeddings are stored as real[] and compared in Python: a user has hundreds of jobs and four resumes, so
there is nothing to index yet. pgvector (already in the database image) takes over when search across many
rows needs an index; installing the extension needs the superuser, so it waits for that migration."""

import math

from sqlalchemy import REAL
from sqlalchemy.dialects.postgresql import ARRAY

Embedding = ARRAY(REAL)


def cosine(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else None

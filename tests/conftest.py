import pathlib
import shutil
import tempfile

import pytest


@pytest.fixture
def tmp_path():
    """Override pytest tmp_path to avoid Windows permission errors on cleanup."""
    d = tempfile.mkdtemp()
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)

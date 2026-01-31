"""Tests for workspace copy operations."""
import tempfile
from pathlib import Path

import pytest

from breakfix.workspace import copy_prototype_to_production, CopyResult


@pytest.fixture
def working_dir():
    """Create a temporary working directory with a prototype."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create prototype directory with some files
        proto_dir = tmpdir / "prototype"
        proto_dir.mkdir()

        # Create src structure
        src_dir = proto_dir / "src" / "mypackage"
        src_dir.mkdir(parents=True)

        (src_dir / "__init__.py").write_text("# package init")
        (src_dir / "main.py").write_text("def main(): pass")

        # Create a nested directory
        subdir = src_dir / "utils"
        subdir.mkdir()
        (subdir / "helpers.py").write_text("def helper(): pass")

        # Create a file in prototype root
        (proto_dir / "setup.cfg").write_text("[metadata]\nname = mypackage")

        yield tmpdir


class TestCopyPrototypeToProduction:
    """Tests for copy_prototype_to_production function."""

    @pytest.mark.anyio
    async def test_copies_all_files(self, working_dir):
        """Should copy all files from prototype to production."""
        result = await copy_prototype_to_production(working_dir)

        assert result.success
        assert result.error == ""

        prod_dir = working_dir / "production"
        assert prod_dir.exists()

        # Check all files were copied
        assert (prod_dir / "setup.cfg").exists()
        assert (prod_dir / "src" / "mypackage" / "__init__.py").exists()
        assert (prod_dir / "src" / "mypackage" / "main.py").exists()
        assert (prod_dir / "src" / "mypackage" / "utils" / "helpers.py").exists()

    @pytest.mark.anyio
    async def test_preserves_file_contents(self, working_dir):
        """Should preserve file contents during copy."""
        result = await copy_prototype_to_production(working_dir)

        assert result.success

        prod_dir = working_dir / "production"
        assert (prod_dir / "src" / "mypackage" / "main.py").read_text() == "def main(): pass"
        assert (prod_dir / "setup.cfg").read_text() == "[metadata]\nname = mypackage"

    @pytest.mark.anyio
    async def test_overwrites_existing_production(self, working_dir):
        """Should overwrite existing production directory."""
        # Create an existing production directory with different content
        prod_dir = working_dir / "production"
        prod_dir.mkdir()
        (prod_dir / "old_file.txt").write_text("old content")

        result = await copy_prototype_to_production(working_dir)

        assert result.success

        # Old file should be gone
        assert not (prod_dir / "old_file.txt").exists()

        # New files should exist
        assert (prod_dir / "setup.cfg").exists()

    @pytest.mark.anyio
    async def test_copies_hidden_files(self, working_dir):
        """Should copy hidden files like .git."""
        # Create a .git directory
        git_dir = working_dir / "prototype" / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\nrepositoryformatversion = 0")
        (git_dir / "HEAD").write_text("ref: refs/heads/main")

        result = await copy_prototype_to_production(working_dir)

        assert result.success

        prod_dir = working_dir / "production"
        assert (prod_dir / ".git").exists()
        assert (prod_dir / ".git" / "config").read_text() == "[core]\nrepositoryformatversion = 0"

    @pytest.mark.anyio
    async def test_fails_if_prototype_missing(self, working_dir):
        """Should fail if prototype directory doesn't exist."""
        # Remove prototype
        import shutil
        shutil.rmtree(working_dir / "prototype")

        result = await copy_prototype_to_production(working_dir)

        assert not result.success
        assert "prototype" in result.error.lower() or "no such file" in result.error.lower()


class TestCopyResult:
    """Tests for CopyResult dataclass."""

    def test_success_result(self):
        """Should create a success result."""
        result = CopyResult(success=True)
        assert result.success
        assert result.error == ""

    def test_failure_result(self):
        """Should create a failure result with error."""
        result = CopyResult(success=False, error="Something went wrong")
        assert not result.success
        assert result.error == "Something went wrong"

import re

import wieso_mcp


def test_package_has_semver_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", wieso_mcp.__version__)


def test_screenshot_dependency_is_declared():
    """`screenshot` uses pywinauto's capture_as_image, which needs Pillow at runtime."""
    import tomllib
    from pathlib import Path

    deps = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))["project"]
    assert any(d.lower().startswith("pillow") for d in deps["dependencies"])

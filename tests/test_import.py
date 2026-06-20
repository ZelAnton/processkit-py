import processkit


def test_package_importable() -> None:
    assert isinstance(processkit.__all__, list)


def test_version_is_exposed() -> None:
    assert isinstance(processkit.__version__, str)
    assert processkit.__version__

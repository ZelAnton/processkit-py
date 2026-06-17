import processkit


def test_package_importable() -> None:
    assert isinstance(processkit.__all__, list)

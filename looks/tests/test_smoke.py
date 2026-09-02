"""The one test the 0.0.0 release needs: the package imports."""


def test_import():
    import looks

    assert looks.__version__

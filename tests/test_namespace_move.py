import pytest

def test_import_via_redirect():
    with pytest.warns(
            DeprecationWarning,
            match=r"The top-level 'flp' namespace is deprecated and has been moved to 'flpit'",
    ):
        import flp

        flp.it([])
        flp.lst([])

        from flp import FlpIt, FlpList, Grouping, OrderedIt

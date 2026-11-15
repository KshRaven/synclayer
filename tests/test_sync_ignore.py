from synclayer.client.sync import is_ignored


def test_ignore_patterns():
    pats = ["*.tmp", "build/", "docs/*.bak", "node_modules"]
    assert is_ignored("a.tmp", pats) and is_ignored("x/y/a.tmp", pats)
    assert is_ignored("build/out.bin", pats) and not is_ignored("build", pats)
    assert is_ignored("docs/old.bak", pats) and not is_ignored("other/old.bak", pats)
    assert is_ignored("web/node_modules/pkg/index.js", pats)
    assert not is_ignored("notes.txt", pats) and not is_ignored(".slignore", ["*"])

from paleonews.filter import is_dedicated_feed, keyword_match


def test_is_dedicated_feed():
    patterns = [
        "nature.com/subjects/palaeontology",
        "sciencedaily.com/rss/fossils",
    ]
    assert is_dedicated_feed("https://www.nature.com/subjects/palaeontology.rss", patterns)
    assert is_dedicated_feed("https://www.sciencedaily.com/rss/fossils_ruins.xml", patterns)
    assert not is_dedicated_feed("https://www.nature.com/nature.rss", patterns)


def test_keyword_match_positive():
    keywords = ["fossil", "dinosaur", "paleontology"]
    assert keyword_match("New fossil discovery", "", keywords)
    assert keyword_match("", "A study on dinosaur bones", keywords)
    assert keyword_match("Paleontology News", "", keywords)


def test_keyword_match_case_insensitive():
    keywords = ["fossil"]
    assert keyword_match("FOSSIL Found", "", keywords)
    assert keyword_match("Ancient Fossil site", "", keywords)


def test_keyword_match_negative():
    keywords = ["fossil", "dinosaur"]
    assert not keyword_match("Quantum physics breakthrough", "New laser technology", keywords)


def test_keyword_match_word_boundary():
    keywords = ["fossil"]
    assert keyword_match("A fossil was found", "", keywords)
    # "fossilized" should not match "fossil" with word boundary
    assert not keyword_match("Fossilized remains", "", keywords)

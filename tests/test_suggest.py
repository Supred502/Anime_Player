from animeplayer.suggest import closest_title

CATALOG = [
    ("Frieren: Beyond Journey's End", ("Sousou no Frieren", "Frieren: Beyond Journey's End", "Frieren")),
    ("ONE PIECE", ("ONE PIECE",)),
    ("JUJUTSU KAISEN", ("Jujutsu Kaisen",)),
    ("Demon Slayer: Kimetsu no Yaiba", ("Kimetsu no Yaiba", "Demon Slayer: Kimetsu no Yaiba")),
    ("Attack on Titan", ("Shingeki no Kyojin", "Attack on Titan")),
    ("Naruto: Shippuden", ("Naruto: Shippuuden", "Naruto: Shippuden")),
    # Its synonym "Demon Slave" is one letter from "demon slayr" too.
    ("Chained Soldier", ("Mato Seihei no Slave", "Demon Slave", "Chained Soldier")),
]


def test_common_typos_find_the_show():
    assert closest_title("freiren", CATALOG) == "Frieren: Beyond Journey's End"
    assert closest_title("one peice", CATALOG) == "ONE PIECE"
    assert closest_title("jujutsu kaisn", CATALOG) == "JUJUTSU KAISEN"
    assert closest_title("demon slayr", CATALOG) == "Demon Slayer: Kimetsu no Yaiba"
    assert closest_title("atack on titan", CATALOG) == "Attack on Titan"
    assert closest_title("naruto shipudden", CATALOG) == "Naruto: Shippuden"


def test_nothing_to_suggest():
    assert closest_title("one piece", CATALOG) is None          # already right
    assert closest_title("zz", CATALOG) is None                 # too short to judge
    assert closest_title("completely different", CATALOG) is None

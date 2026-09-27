"""Library tabs <-> AniList custom lists, with two devices sharing one fake
AniList account."""

from animeplayer import library_sync
from animeplayer.anilist.client import CustomListEntry, CustomLists
from animeplayer.library_sync import Pending
from animeplayer.storage.db import Database, placeholder_slug


class FakeAniList:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.entries: dict[int, tuple[str, frozenset[str]]] = {}   # id -> (status, lists)
        self.calls: list[tuple] = []

    def get_custom_lists(self, user_id: int) -> CustomLists:
        return CustomLists(tuple(self.names), {
            m: CustomListEntry(m, status, lists, f"Show {m}", f"https://img/{m}.jpg")
            for m, (status, lists) in self.entries.items()})

    def set_custom_list_names(self, names: list[str]) -> None:
        self.calls.append(("names", list(names)))
        self.names = list(names)

    def set_entry_custom_lists(self, media_id: int, names: list[str], status: str = "") -> None:
        self.calls.append(("entry", media_id, sorted(names), status))
        old_status = self.entries.get(media_id, ("", frozenset()))[0]
        self.entries[media_id] = (status or old_status, frozenset(names))


def device(tmp_path, name: str) -> Database:
    return Database(tmp_path / f"{name}.db")


def changed(db: Database, media=(), deleted="", renamed=None) -> None:
    """What the backend records on each Library action."""
    pending = Pending.load(db)
    pending.media |= set(media)
    if deleted:
        pending.deleted.append(deleted)
    if renamed:
        pending.renamed.append(renamed)
    pending.save(db)


def sync(db: Database, remote: FakeAniList, during=None) -> library_sync.Pushed:
    sent = Pending.load(db)
    known = library_sync.load_known(db)
    pushed = library_sync.push(remote, db, 1, sent, known)
    if during:
        during()
    busy = Pending.load(db).minus(sent)
    library_sync.pull(db, pushed.lists, known, busy)
    busy.save(db)
    return pushed


def add(db: Database, list_id: int, anilist_id: int, slug: str = "") -> None:
    db.add_to_library(list_id, {"slug_id": slug or f"show-{anilist_id}", "title": f"Show {anilist_id}",
                                "anilist_id": anilist_id})
    changed(db, {anilist_id} if anilist_id else ())


def tabs(db: Database) -> dict[str, set[int]]:
    return {t["name"]: db.library_anilist_ids(t["id"]) for t in db.library_lists()}


def test_first_sync_sends_everything_and_new_shows_go_to_planning(tmp_path) -> None:
    remote = FakeAniList()
    remote.names = ["From the website"]
    remote.entries[2] = ("COMPLETED", frozenset())
    pc = device(tmp_path, "pc")
    favs = pc.create_library_list("Favourites")
    # Added before sync existed: nothing pending, the first sync finds it.
    pc.add_to_library(favs, {"slug_id": "a-1", "title": "A", "anilist_id": 1})
    pc.add_to_library(favs, {"slug_id": "b-2", "title": "B", "anilist_id": 2})

    pushed = sync(pc, remote)

    assert remote.names == ["From the website", "Favourites"]
    assert remote.entries[1] == ("PLANNING", frozenset({"Favourites"}))
    assert remote.entries[2] == ("COMPLETED", frozenset({"Favourites"}))   # status left alone
    assert pushed.planned == {1}
    # The website's list arrives here as a tab.
    assert tabs(pc) == {"Favourites": {1, 2}, "From the website": set()}


def test_changes_on_one_device_reach_the_other(tmp_path) -> None:
    remote = FakeAniList()
    pc, deck = device(tmp_path, "pc"), device(tmp_path, "deck")
    sync(pc, remote)
    sync(deck, remote)

    favs = pc.create_library_list("Favourites")
    add(pc, favs, 5)
    sync(pc, remote)
    sync(deck, remote)
    assert tabs(deck) == {"Favourites": {5}}
    item = deck.library_items(deck.library_lists()[0]["id"])[0]
    assert item["slug_id"] == placeholder_slug(5)      # not matched on the Deck yet
    assert item["title"] == "Show 5"

    deck_favs = deck.library_lists()[0]["id"]
    deck.remove_from_library_by_anilist(deck_favs, 5)
    changed(deck, {5})
    sync(deck, remote)
    sync(pc, remote)
    assert tabs(pc) == {"Favourites": set()}
    assert remote.entries[5][0] == "PLANNING"          # still planned, only off the tab


def test_rename_and_delete_carry_over(tmp_path) -> None:
    remote = FakeAniList()
    pc, deck = device(tmp_path, "pc"), device(tmp_path, "deck")
    old = pc.create_library_list("Old")
    gone = pc.create_library_list("Gone")
    add(pc, old, 1)
    add(pc, gone, 2)
    sync(pc, remote)
    sync(deck, remote)
    assert tabs(deck) == {"Old": {1}, "Gone": {2}}

    pc.rename_library_list(old, "New")
    changed(pc, {1}, renamed=("Old", "New"))
    pc.delete_library_list(gone)
    changed(pc, {2}, deleted="Gone")
    sync(pc, remote)
    assert remote.names == ["New"]
    assert remote.entries[1][1] == {"New"} and remote.entries[2][1] == frozenset()

    sync(deck, remote)
    assert tabs(deck) == {"New": {1}}


def test_a_tab_made_here_is_not_mistaken_for_one_deleted_elsewhere(tmp_path) -> None:
    remote = FakeAniList()
    pc = device(tmp_path, "pc")
    sync(pc, remote)
    pc.create_library_list("Fresh")        # made while offline: nothing pending
    sync(pc, remote)
    assert remote.names == ["Fresh"] and tabs(pc) == {"Fresh": set()}


def test_a_change_made_during_the_sync_is_not_undone(tmp_path) -> None:
    remote = FakeAniList()
    pc = device(tmp_path, "pc")
    favs = pc.create_library_list("Favourites")
    sync(pc, remote)

    sync(pc, remote, during=lambda: add(pc, favs, 9))
    assert tabs(pc) == {"Favourites": {9}}           # pull didn't remove it
    assert Pending.load(pc).media == {9}              # and the next sync sends it
    sync(pc, remote)
    assert remote.entries[9][1] == {"Favourites"}


def test_shows_without_an_anilist_id_stay_on_this_device(tmp_path) -> None:
    remote = FakeAniList()
    pc = device(tmp_path, "pc")
    favs = pc.create_library_list("Favourites")
    add(pc, favs, 0, slug="only-on-the-source")
    sync(pc, remote)
    assert [i["slug_id"] for i in pc.library_items(favs)] == ["only-on-the-source"]
    assert remote.entries == {}


def test_a_show_is_looked_up_when_it_has_no_id(tmp_path) -> None:
    remote = FakeAniList()
    pc = device(tmp_path, "pc")
    favs = pc.create_library_list("Favourites")
    add(pc, favs, 0, slug="frieren-123")
    sent, known = Pending.load(pc), library_sync.load_known(pc)
    pushed = library_sync.push(remote, pc, 1, sent, known,
                               lambda slug, title: 154587 if slug == "frieren-123" else 0)
    assert remote.entries[154587] == ("PLANNING", frozenset({"Favourites"}))
    library_sync.pull(pc, pushed.lists, known, Pending())
    assert [(i["slug_id"], i["anilist_id"]) for i in pc.library_items(favs)] == [("frieren-123", 154587)]


def test_matching_later_replaces_the_placeholder(tmp_path) -> None:
    db = device(tmp_path, "deck")
    favs = db.create_library_list("Favourites")
    db.add_to_library(favs, {"slug_id": placeholder_slug(5), "title": "Show 5", "anilist_id": 5})
    assert db.lists_containing("show-5-777", 5) == [favs]
    db.add_to_library(favs, {"slug_id": "show-5-777", "title": "Show 5", "anilist_id": 5})
    assert [i["slug_id"] for i in db.library_items(favs)] == ["show-5-777"]

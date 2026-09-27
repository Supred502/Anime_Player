"""The Library tabs, kept in step with AniList custom lists of the same names,
so a tab made or filled on one device is there on every other one.

A change made in the app is written down first (`Pending`, kept in the
settings table) and sent later by `push`, so one made offline or logged out
still gets there. `pull` then makes the tabs match what AniList has: that's
how changes made elsewhere arrive.

What AniList can't tell apart on its own -- a tab deleted on another device
versus one just made here -- is settled by remembering which names AniList had
at the last sync (KNOWN_KEY). No memory yet means this is the first sync, and
everything here is sent up rather than anything being deleted.

A show AniList doesn't know is kept, but only on this device. Shows put on
a custom list that weren't on the user's AniList list go into Planning, since
AniList needs a list entry to hang the custom list on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from animeplayer.anilist.client import AniListClient, CustomListEntry, CustomLists
from animeplayer.storage.db import Database, placeholder_slug

PENDING_KEY = "library_sync_pending"
KNOWN_KEY = "library_sync_known"


@dataclass
class Pending:
    media: set[int] = field(default_factory=set)             # anime whose tabs changed
    deleted: list[str] = field(default_factory=list)          # tab names
    renamed: list[tuple[str, str]] = field(default_factory=list)   # (old, new)

    @classmethod
    def load(cls, db: Database) -> "Pending":
        try:
            data = json.loads(db.get_setting(PENDING_KEY) or "{}")
        except ValueError:
            data = {}
        return cls(set(data.get("media", [])), list(data.get("deleted", [])),
                   [tuple(pair) for pair in data.get("renamed", [])])

    def save(self, db: Database) -> None:
        db.set_setting(PENDING_KEY, json.dumps(
            {"media": sorted(self.media), "deleted": self.deleted, "renamed": self.renamed}))

    def empty(self) -> bool:
        return not (self.media or self.deleted or self.renamed)

    def minus(self, sent: "Pending") -> "Pending":
        """What was added since `sent` was read."""
        return Pending(self.media - sent.media,
                       [n for n in self.deleted if n not in sent.deleted],
                       [r for r in self.renamed if r not in sent.renamed])

    def names(self) -> set[str]:
        return set(self.deleted) | {n for pair in self.renamed for n in pair}


def load_known(db: Database) -> set[str] | None:
    raw = db.get_setting(KNOWN_KEY)
    if raw is None:
        return None
    try:
        return set(json.loads(raw))
    except ValueError:
        return None


@dataclass
class Pushed:
    lists: CustomLists          # AniList as it is after the push
    planned: set[int]           # anime this put into Planning


def push(client: AniListClient, db: Database, user_id: int, pending: Pending,
         known: set[str] | None, find_id: Callable[[str, str], int] | None = None) -> Pushed:
    """Sends this device's changes. Runs on a worker thread.

    `find_id(slug, title)` looks up the AniList id of a tab's show that
    doesn't have one yet (added from a search result, say); 0 if unknown."""
    remote = client.get_custom_lists(user_id)
    names = list(remote.names)
    for old, new in pending.renamed:
        if old in names:
            if new in names:
                names.remove(old)
            else:
                names[names.index(old)] = new
        elif new not in names:
            names.append(new)
    for name in pending.deleted:
        if name in names:
            names.remove(name)
    for tab in db.library_lists():
        # New here, not deleted elsewhere.
        if tab["name"] not in names and (known is None or tab["name"] not in known):
            names.append(tab["name"])
    if names != list(remote.names):
        client.set_custom_list_names(names)

    media = set(pending.media)
    if known is None:
        media |= db.library_anilist_ids()
    if find_id is not None:
        for item in db.library_items_without_anilist():
            anilist_id = find_id(item["slug_id"], item["title"])
            if anilist_id:
                db.set_library_anilist_id(item["slug_id"], anilist_id)
                media.add(anilist_id)

    entries = dict(remote.entries)
    planned: set[int] = set()
    for anilist_id in sorted(media):
        wanted = [n for n in db.library_names_for(anilist_id) if n in names]
        entry = entries.get(anilist_id)
        if entry is None and not wanted:
            continue
        if entry is not None and set(wanted) == entry.lists:
            continue
        status = "" if entry is not None else "PLANNING"
        client.set_entry_custom_lists(anilist_id, wanted, status)
        if status:
            planned.add(anilist_id)
        entries[anilist_id] = CustomListEntry(
            media_id=anilist_id, status=entry.status if entry else status, lists=frozenset(wanted),
            title=entry.title if entry else "", cover_url=entry.cover_url if entry else "")
    return Pushed(CustomLists(tuple(names), entries), planned)


def pull(db: Database, lists: CustomLists, known: set[str] | None, busy: Pending) -> None:
    """Makes the tabs match AniList. Runs on the GUI thread. Leaves alone
    whatever changed here while the push was running (`busy`): the next
    sync sends that."""
    busy_names = busy.names()
    by_name = {tab["name"]: tab["id"] for tab in db.library_lists()}
    for name, list_id in list(by_name.items()):
        if name not in lists.names and name not in busy_names and known is not None and name in known:
            db.delete_library_list(list_id)      # deleted on another device
            del by_name[name]
    for name in lists.names:
        if name not in by_name and name not in busy_names:
            by_name[name] = db.create_library_list(name)

    for name in lists.names:
        list_id = by_name.get(name)
        if list_id is None:
            continue
        wanted = {m for m, entry in lists.entries.items() if name in entry.lists}
        have = db.library_anilist_ids(list_id)
        for anilist_id in have - wanted - busy.media:
            db.remove_from_library_by_anilist(list_id, anilist_id)
        for anilist_id in wanted - have - busy.media:
            entry = lists.entries[anilist_id]
            mapping = db.get_anidb_mapping(anilist_id)
            db.add_to_library(list_id, {
                "slug_id": mapping.slug_id if mapping else placeholder_slug(anilist_id),
                "numeric_id": mapping.numeric_id if mapping else "",
                "title": entry.title or (mapping.title if mapping else ""),
                "poster_url": entry.cover_url or (mapping.poster_url if mapping else ""),
                "anilist_id": anilist_id,
            })
    db.set_setting(KNOWN_KEY, json.dumps(list(lists.names)))

#!/bin/sh
# -P: don't put the current directory on the import path. The sandbox can
# see home, so started from a folder holding an "animeplayer" directory (a
# checkout of this repo) it would run that instead of the installed app.
exec python3 -P -m animeplayer "$@"

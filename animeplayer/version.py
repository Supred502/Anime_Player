"""The app's version, and where new ones are published.

scripts/release.py bumps VERSION, tags the commit v<VERSION> and pushes; the
GitHub workflow in .github/workflows/release.yml then builds the Windows
installer and publishes it as a release, which is what every copy of the app
checks for (see updates.py).
"""

VERSION = "0.2.0"

# owner/name on GitHub. Releases must be public for the check to see them.
REPO = "Supred502/Anime_Player"

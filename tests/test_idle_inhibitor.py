"""The riskiest thing this class can do is fail to release -- that would
leave the machine unable to sleep until reboot. These cover the contract
that protects against it, without needing a particular desktop to be
running: the calls are all no-ops or clean failures when there's no
session bus or no screensaver service to answer.
"""

from animeplayer.player.idle_inhibitor import IdleInhibitor


def test_starts_inactive() -> None:
    assert IdleInhibitor().active is False


def test_release_without_inhibit_is_a_noop() -> None:
    inhibitor = IdleInhibitor()
    inhibitor.release()  # must not raise
    assert inhibitor.active is False


def test_inhibit_release_cycle_leaves_nothing_held() -> None:
    inhibitor = IdleInhibitor()
    inhibitor.inhibit("test")
    inhibitor.release()
    assert inhibitor.active is False


def test_repeated_calls_are_idempotent() -> None:
    """Callers drive this from a plain "is it playing" boolean, so both
    directions have to tolerate being called again in the same state --
    a second inhibit() must not strand the first connection unreleased."""
    inhibitor = IdleInhibitor()
    inhibitor.inhibit("test")
    first = inhibitor._connection_name
    inhibitor.inhibit("test")
    assert inhibitor._connection_name == first
    inhibitor.release()
    inhibitor.release()
    assert inhibitor.active is False


def test_failed_inhibit_does_not_report_active() -> None:
    """If nothing answers, the inhibitor must say so rather than claim a
    hold it doesn't have -- otherwise release() would skip the cleanup."""
    inhibitor = IdleInhibitor()
    inhibitor.inhibit("test")
    # Either it really is held, or it reported failure; never "active" with
    # no connection behind it.
    assert inhibitor.active == (inhibitor._connection_name is not None)

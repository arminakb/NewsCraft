from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StoryStatus = Literal["inbox", "shortlisted", "rejected", "drafted", "telegram_provisional"]
EditorialStoryStatus = Literal["inbox", "shortlisted", "rejected", "drafted"]
EditableStoryStatus = Literal["inbox", "shortlisted", "rejected"]

INBOX: StoryStatus = "inbox"
SHORTLISTED: StoryStatus = "shortlisted"
REJECTED: StoryStatus = "rejected"
DRAFTED: StoryStatus = "drafted"
TELEGRAM_PROVISIONAL: StoryStatus = "telegram_provisional"

STORY_STATUSES: tuple[StoryStatus, ...] = (
    INBOX,
    SHORTLISTED,
    REJECTED,
    DRAFTED,
    TELEGRAM_PROVISIONAL,
)

_ALLOWED_TRANSITIONS: dict[StoryStatus, frozenset[StoryStatus]] = {
    INBOX: frozenset({SHORTLISTED, REJECTED, DRAFTED}),
    SHORTLISTED: frozenset({INBOX, REJECTED, DRAFTED}),
    REJECTED: frozenset({INBOX, SHORTLISTED}),
    DRAFTED: frozenset({INBOX, SHORTLISTED, REJECTED}),
    TELEGRAM_PROVISIONAL: frozenset(),
}


@dataclass(frozen=True, slots=True)
class StoryTransition:
    current: str
    target: StoryStatus
    allowed: bool
    changed: bool
    reason: Literal["changed", "unchanged", "unknown_state", "transition_not_allowed"]


def decide_story_transition(current: str, target: StoryStatus) -> StoryTransition:
    if current not in STORY_STATUSES:
        return StoryTransition(current, target, allowed=False, changed=False, reason="unknown_state")
    if current == target:
        return StoryTransition(current, target, allowed=True, changed=False, reason="unchanged")
    if target not in _ALLOWED_TRANSITIONS[current]:
        return StoryTransition(current, target, allowed=False, changed=False, reason="transition_not_allowed")
    return StoryTransition(current, target, allowed=True, changed=True, reason="changed")

from app.stories.states import DRAFTED, INBOX, SHORTLISTED, TELEGRAM_PROVISIONAL, decide_story_transition


def test_editorial_transition_rules_are_explicit():
    decision = decide_story_transition(INBOX, SHORTLISTED)

    assert decision.allowed is True
    assert decision.changed is True
    assert decision.reason == "changed"


def test_same_state_is_an_idempotent_noop():
    decision = decide_story_transition(DRAFTED, DRAFTED)

    assert decision.allowed is True
    assert decision.changed is False
    assert decision.reason == "unchanged"


def test_provisional_and_unknown_states_cannot_be_edited():
    assert decide_story_transition(TELEGRAM_PROVISIONAL, INBOX).allowed is False
    assert decide_story_transition("legacy-state", INBOX).reason == "unknown_state"

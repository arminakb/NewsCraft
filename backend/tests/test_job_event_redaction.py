from app.jobs.events import redact_event_data


def test_redact_event_data_masks_nested_secret_like_keys_without_mutating_input():
    source = {
        "Authorization": "Bearer real-token",
        "nested": {"api_key": "real-key", "safe": "visible"},
        "items": [{"cookie": "session=value"}, "plain"],
    }

    assert redact_event_data(source) == {
        "Authorization": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "safe": "visible"},
        "items": [{"cookie": "[REDACTED]"}, "plain"],
    }
    assert source["Authorization"] == "Bearer real-token"


def test_redact_event_data_masks_secret_like_keys_case_insensitively_in_sequences():
    source = {
        "values": (
            {"access_token": "token-value"},
            [{"PASSWORD": "password-value"}, {"client-secret": "secret-value"}],
        )
    }

    assert redact_event_data(source) == {
        "values": [
            {"access_token": "[REDACTED]"},
            [{"PASSWORD": "[REDACTED]"}, {"client-secret": "[REDACTED]"}],
        ]
    }

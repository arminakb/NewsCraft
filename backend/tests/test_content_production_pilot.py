from app.content_production.pilot import parser


def test_pilot_commands_keep_human_approvals_explicit():
    root = parser()
    assert root.parse_args(["start", "--topic", "AI"]).command == "start"
    assert root.parse_args(["process"]).command == "process"
    assert root.parse_args(
        [
            "approve-shortlist",
            "--request-id",
            "11111111-1111-1111-1111-111111111111",
            "--selection-execution-id",
            "22222222-2222-2222-2222-222222222222",
            "--content-item-id",
            "33333333-3333-3333-3333-333333333333",
        ]
    ).command == "approve-shortlist"
    assert root.parse_args(
        ["approve-package", "--package-id", "44444444-4444-4444-4444-444444444444"]
    ).command == "approve-package"


def test_process_command_has_no_automatic_approval_or_publish_switch():
    options = {action.dest for action in parser()._subparsers._group_actions[0].choices["process"]._actions}
    assert "approve" not in options
    assert "publish" not in options
    assert "telegram_token" not in options

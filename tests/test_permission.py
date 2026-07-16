from playwait.permission import shell_needs_permission_interrupt


def test_shell_off() -> None:
    assert shell_needs_permission_interrupt("sudo apt", mode="off") is False


def test_shell_ask_always() -> None:
    assert shell_needs_permission_interrupt("ls", mode="ask-always") is True


def test_shell_patterns_match() -> None:
    assert shell_needs_permission_interrupt("curl https://x", mode="patterns") is True
    assert shell_needs_permission_interrupt("git push origin main", mode="patterns") is True
    assert shell_needs_permission_interrupt("echo hi", mode="patterns") is False

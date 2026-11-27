from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        from ai_agent_cli.terminal_chat import run_api_chat

        return run_api_chat()
    if args == ["--local"]:
        from ai_agent_cli.local_server import run_local_chat

        return run_local_chat()
    if args[0] == "login":
        from ai_agent_cli.login import main as login_main

        return login_main(args[1:])
    if args[0] == "logout":
        from ai_agent_cli.login import logout

        return logout()
    if args[0] == "server-url":
        from ai_agent_cli.server_config import main as server_url_main

        return server_url_main(args[1:])
    print(
        "usage: ai-agent-chat [--local | login | logout | server-url ...]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
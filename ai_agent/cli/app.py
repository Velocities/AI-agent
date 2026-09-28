from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] in {"start", "stop", "restart", "status"}:
        from ai_agent.cli.service_cmd import main as service_main

        return service_main(args)
    if args and args[0] == "serve":
        if len(args) != 1:
            print("usage: ai-agent serve", file=sys.stderr)
            return 2
        from ai_agent.service.supervisor import main as serve_main

        return serve_main()
    if args and args[0] == "config":
        from ai_agent.cli.config_cmd import main as config_main

        return config_main(args[1:])
    if args and args[0] == "host-setup":
        from ai_agent.cli.host_setup import main as host_setup_main

        return host_setup_main(args[1:])
    if args and args[0] == "server-url":
        from ai_agent_cli.server_config import main as server_url_main

        return server_url_main(args[1:])
    if args and args[0] == "login":
        from ai_agent_cli.login import main as login_main

        return login_main(args[1:])
    if args and args[0] == "logout":
        from ai_agent_cli.login import logout

        return logout()
    from ai_agent_cli.remote_repl import run_remote_repl

    return run_remote_repl()


if __name__ == "__main__":
    raise SystemExit(main())

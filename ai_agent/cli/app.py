from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if not args:
        print(
            "usage: ai-agent {serve|config|apk|host-setup|start|stop|restart|status}\n"
            "\n"
            "Server operator commands for this deployment.\n"
            "Terminal chat: ai-agent-chat  (or ai-agent-chat --local for loopback mode)",
            file=sys.stderr,
        )
        return 2
    if args[0] in {"start", "stop", "restart", "status"}:
        from ai_agent.cli.service_cmd import main as service_main

        return service_main(args)
    if args[0] == "serve":
        if len(args) != 1:
            print("usage: ai-agent serve", file=sys.stderr)
            return 2
        from ai_agent.service.supervisor import main as serve_main

        return serve_main()
    if args[0] == "config":
        from ai_agent.cli.config_cmd import main as config_main

        return config_main(args[1:])
    if args[0] == "apk":
        from ai_agent.cli.apk_cmd import main as apk_main

        return apk_main(args[1:])
    if args[0] == "host-setup":
        from ai_agent.cli.host_setup import main as host_setup_main

        return host_setup_main(args[1:])
    print(
        f"unknown command: {args[0]}\n"
        "Chat client: ai-agent-chat",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
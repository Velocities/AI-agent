"""Entry point for the Discord bot (`ai-agent-discord`)."""

from __future__ import annotations

import sys

from ai_agent_discord.config import load_config, redirect_url
from ai_agent_discord.oauth import LoginBroker, OAuthServer
from ai_agent_discord.store import UserStore


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        config = load_config()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        from ai_agent_discord.bot import AgentBot
    except ImportError as exc:
        if "discord" in str(exc).lower() or exc.name == "discord":
            print(
                "Discord support is not installed. Run: pip install 'ai-agent[discord]'",
                file=sys.stderr,
            )
            return 1
        raise
    store = UserStore(config.state_path)
    broker = LoginBroker(store, redirect_url=redirect_url(config.public_url))
    oauth = OAuthServer(broker, config.oauth_host, config.oauth_port)
    try:
        oauth.start()
    except OSError as exc:
        print(
            f"Could not listen on {config.oauth_host}:{config.oauth_port}: {exc}",
            file=sys.stderr,
        )
        return 1
    bot = AgentBot(store, broker, guild_id=config.guild_id)
    try:
        import discord

        bot.run(config.token)
    except discord.LoginFailure:
        print("Discord rejected the bot token.", file=sys.stderr)
        return 1
    finally:
        oauth.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

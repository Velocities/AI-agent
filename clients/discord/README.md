# AI Agent — Discord bot

A Discord bot that chats with any deployment of this project over the same HTTP API as `ai-agent-chat`. Install `discord.py` with the extra:

```bash
pip install 'ai-agent[discord]'
```

The bot token is the gateway login. Each person still signs in with their own Discord account through the deployment's Supabase project, so `/list` shows the chats they already have on the Android app or the terminal.

## Discord application

1. Create an application in the Discord developer portal and add a bot.
2. Enable the **Message Content** privileged intent. The bot reads a message only when it is mentioned, when someone replies to it, or in a direct message. Other channel chatter is ignored.
3. Invite the bot with the `bot` and `applications.commands` scopes. The server starts with no deployments and no sign-ins.
4. Put the bot's public origin in `DISCORD_PUBLIC_URL`. The sign-in redirect is `{DISCORD_PUBLIC_URL}/callback`. Add that exact URL to the Supabase redirect allow list of every deployment people will log into.

`DISCORD_PUBLIC_URL` is the origin browsers can reach. The process listens on `DISCORD_OAUTH_HOST` (default `0.0.0.0`) and `DISCORD_OAUTH_PORT` (default `53683`). Point a proxy or tunnel from the public origin at that port.

## Run

```bash
export DISCORD_BOT_TOKEN=...
export DISCORD_PUBLIC_URL=https://bot.example.com
ai-agent-discord
```

Optional:

| Variable | Role |
|---|---|
| `AI_AGENT_DISCORD_STATE` | JSON file for deployments and sign-ins. Default `~/.config/ai-agent-discord/state.json`. Mode `600`. |
| `DISCORD_GUILD_ID` | Publish slash commands to this server immediately. Leave unset to publish them globally, which can take about an hour and is what you want when the bot is in more than one server. |
| `DISCORD_OAUTH_HOST` | Bind address for `/callback`. |
| `DISCORD_OAUTH_PORT` | Bind port for `/callback`. |

## Commands

Slash commands match the terminal client. An ordinary message that mentions the bot (or a reply to the bot, or a DM) is a chat turn. Images attached to that message are uploaded with it. PNG, JPEG, and WebP only.

| Command | What it does |
|---|---|
| `/server use URL` | Add a deployment or switch to it. The bot fetches `/api/client-config`. |
| `/server list` | List saved deployments. `*` is the active one. |
| `/server remove URL` | Forget a deployment and its sign-in. |
| `/login` | Discord sign-in for the active deployment. The link is only visible to you. |
| `/logout` | Forget the active deployment's sign-in. |
| `/new` | Start a new chat. |
| `/list` | List your chats. The menu continues one, including chats started on another client. |
| `/workflow` | List workflows. `/workflow name key=value` starts one. |
| `/model-info` | Model id, engine, and whether it accepts images and tools. |

Every reply names the active deployment in the embed author line. If the deployment does not answer, the reply says it is unreachable.

When someone else is already in a turn on that same deployment, the bot replies immediately, mentions you, and says how many people are ahead. You are mentioned again on the reply. People using a different deployment are not in that line. The line is inside this bot process; a phone client talking to the same deployment is not counted.

Approvals are buttons on the message. Approve, reject, or allow the same risk for the rest of the server session. When several commands are listed, choose some and press Confirm. If nobody answers, the commands are rejected so the line can move.

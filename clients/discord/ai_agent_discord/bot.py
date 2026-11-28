"""Discord gateway: slash commands, mentions, approvals, and the per-deployment line."""

from __future__ import annotations

import asyncio
import logging
import threading

import discord
import httpx
from discord import app_commands

from ai_agent_client.api import AgentApiClient, AgentApiError
from ai_agent_discord.chat import (
    ChatProblem,
    Reply,
    TurnText,
    bind_conversation,
    client_for,
    continue_chat,
    ensure_images_allowed,
    forget_deployment,
    guard,
    images_from_parts,
    list_chats,
    list_deployments,
    login_message,
    logout,
    message_for_bot,
    model_text,
    require_deployment,
    start_new,
    use_deployment,
    workflow_command,
    workflow_gate,
)
from ai_agent_discord.oauth import LoginBroker
from ai_agent_discord.present import (
    approval_grant,
    decisions_for,
    explain_api_error,
    explain_unreachable,
    explain_wait,
    format_approval,
    pages,
)
from ai_agent_discord.queue import DeploymentQueue
from ai_agent_discord.store import Deployment, UserStore

logger = logging.getLogger(__name__)

_APPROVAL_TIMEOUT = 900


def embeds_for(deployment: str | None, text: str) -> list[discord.Embed]:
    built: list[discord.Embed] = []
    for page in pages(text):
        embed = discord.Embed(description=page)
        if deployment:
            name = deployment if len(deployment) <= 256 else deployment[:253] + "..."
            if len(deployment) <= 2048:
                embed.set_author(name=name, url=deployment)
            else:
                embed.set_author(name=name)
        built.append(embed)
    return built


class Choice:
    def __init__(
        self,
        *,
        approved: bool,
        grant_scope: str | None = None,
        decisions: list[dict] | None = None,
    ):
        self.approved = approved
        self.grant_scope = grant_scope
        self.decisions = decisions


class CommandPick(discord.ui.Select):
    def __init__(self, commands: list[dict]):
        options = []
        for index, command in enumerate(commands, start=1):
            rendered = ""
            if isinstance(command, dict):
                rendered = str(command.get("command") or "")
            label = (rendered or f"Command {index}")[:100]
            risk = str(command.get("risk") or "") if isinstance(command, dict) else ""
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(index),
                    description=(risk[:100] or None),
                )
            )
        super().__init__(
            placeholder="Choose which commands to run",
            min_values=0,
            max_values=len(options),
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ApprovalView):
            return
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                "This approval is for someone else.",
                ephemeral=True,
            )
            return
        view.picked = {int(value) for value in self.values}
        await interaction.response.defer()


class ApprovalView(discord.ui.View):
    def __init__(
        self,
        owner_id: int,
        commands: list[dict],
        *,
        allow_grant: bool,
        grant_scope: str | None,
    ):
        super().__init__(timeout=_APPROVAL_TIMEOUT)
        self.owner_id = owner_id
        self.commands = commands
        self.grant_scope = grant_scope
        self.choice: Choice | None = None
        self.picked: set[int] = set()
        self.add_item(_button("Approve", discord.ButtonStyle.success, self._approve, row=0))
        self.add_item(_button("Reject", discord.ButtonStyle.danger, self._reject, row=0))
        if allow_grant:
            self.add_item(
                _button("Allow for this session", discord.ButtonStyle.primary, self._allow, row=0)
            )
        selectable = [command for command in commands if isinstance(command, dict)]
        if 1 < len(selectable) <= 25:
            self.add_item(CommandPick(commands))
            self.add_item(
                _button("Confirm selection", discord.ButtonStyle.secondary, self._confirm, row=2)
            )

    async def _approve(self, interaction: discord.Interaction) -> None:
        if not await _owns(interaction, self.owner_id):
            return
        self.choice = Choice(approved=True)
        self.stop()
        await interaction.response.send_message("Approved.", ephemeral=True)

    async def _reject(self, interaction: discord.Interaction) -> None:
        if not await _owns(interaction, self.owner_id):
            return
        self.choice = Choice(approved=False)
        self.stop()
        await interaction.response.send_message("Rejected.", ephemeral=True)

    async def _allow(self, interaction: discord.Interaction) -> None:
        if not await _owns(interaction, self.owner_id):
            return
        self.choice = Choice(approved=True, grant_scope=self.grant_scope)
        self.stop()
        await interaction.response.send_message(
            "Approved for the rest of this server session.",
            ephemeral=True,
        )

    async def _confirm(self, interaction: discord.Interaction) -> None:
        if not await _owns(interaction, self.owner_id):
            return
        self.choice = Choice(
            approved=False,
            decisions=decisions_for(self.commands, self.picked),
        )
        self.stop()
        await interaction.response.send_message("Selection sent.", ephemeral=True)


class ResumePick(discord.ui.Select):
    def __init__(self, rows: list[dict]):
        options = []
        seen: dict[str, int] = {}
        for row in rows[:25]:
            title = str(row.get("title") or "Untitled").strip() or "Untitled"
            label = title[:100]
            seen[label] = seen.get(label, 0) + 1
            if seen[label] > 1:
                suffix = f" ({seen[label]})"
                label = label[: 100 - len(suffix)] + suffix
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(row.get("id") or "")[:100],
                    description=str(row.get("id") or "")[:100] or None,
                )
            )
        super().__init__(
            placeholder="Continue a chat",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ResumeView):
            return
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                "This list belongs to someone else.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        try:
            reply = await asyncio.to_thread(
                continue_chat,
                view.store,
                interaction.user.id,
                self.values[0],
            )
        except ChatProblem as exc:
            await interaction.followup.send(
                embeds=embeds_for(exc.deployment, str(exc)),
            )
            return
        await interaction.followup.send(embeds=embeds_for(reply.deployment, reply.text))


class ResumeView(discord.ui.View):
    def __init__(self, store: UserStore, owner_id: int, rows: list[dict]):
        super().__init__(timeout=_APPROVAL_TIMEOUT)
        self.store = store
        self.owner_id = owner_id
        self.add_item(ResumePick(rows))


class ServerGroup(app_commands.Group):
    def __init__(self, bot: AgentBot):
        super().__init__(name="server", description="Choose which agent deployment to use")
        self.bot = bot

    @app_commands.command(name="list", description="List the deployments you have saved")
    async def list_saved(self, interaction: discord.Interaction) -> None:
        await self.bot.run_command(interaction, lambda: list_deployments(self.bot.store, interaction.user.id))

    @app_commands.command(name="use", description="Add a deployment or switch to it")
    @app_commands.describe(url="Deployment origin, such as https://agent.example.com")
    async def use(self, interaction: discord.Interaction, url: str) -> None:
        await self.bot.run_command(
            interaction,
            lambda: use_deployment(self.bot.store, interaction.user.id, url),
        )

    @app_commands.command(name="remove", description="Forget a deployment and its sign-in")
    @app_commands.describe(url="Deployment origin to forget")
    async def remove(self, interaction: discord.Interaction, url: str) -> None:
        await self.bot.run_command(
            interaction,
            lambda: forget_deployment(self.bot.store, interaction.user.id, url),
        )


class AgentBot(discord.Client):
    def __init__(
        self,
        store: UserStore,
        broker: LoginBroker,
        *,
        guild_id: int | None = None,
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=True,
                replied_user=False,
            ),
        )
        self.store = store
        self.broker = broker
        self.guild_id = guild_id
        self.queue = DeploymentQueue()
        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(ServerGroup(self))
        self._register_commands()

    def _register_commands(self) -> None:
        @self.tree.command(name="login", description="Sign in to the active deployment with Discord")
        async def login(interaction: discord.Interaction) -> None:
            await self.run_command(
                interaction,
                lambda: self._login_reply(interaction.user.id),
                ephemeral=True,
            )

        @self.tree.command(name="logout", description="Forget your sign-in on the active deployment")
        async def logout_command(interaction: discord.Interaction) -> None:
            await self.run_command(interaction, lambda: logout(self.store, interaction.user.id))

        @self.tree.command(name="new", description="Start a new chat on the active deployment")
        async def new_chat(interaction: discord.Interaction) -> None:
            await self.run_command(interaction, lambda: start_new(self.store, interaction.user.id))

        @self.tree.command(name="list", description="List your chats on the active deployment")
        async def list_command(interaction: discord.Interaction) -> None:
            await self.run_command(interaction, lambda: list_chats(self.store, interaction.user.id))

        @self.tree.command(name="workflow", description="List workflows, or start one")
        @app_commands.describe(argument="Workflow name and key=value parameters. Omit to list.")
        async def workflow(interaction: discord.Interaction, argument: str | None = None) -> None:
            await self.run_command(
                interaction,
                lambda: workflow_command(self.store, interaction.user.id, argument or ""),
            )

        @self.tree.command(name="model-info", description="Show the model this deployment is running")
        async def model_info(interaction: discord.Interaction) -> None:
            await self.run_command(interaction, lambda: model_text(self.store, interaction.user.id))

    async def setup_hook(self) -> None:
        # A guild sync shows commands immediately in that server. Syncing the
        # same commands globally as well makes Discord list them twice there.
        if self.guild_id is not None:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            return
        await self.tree.sync()

    async def on_ready(self) -> None:
        logger.info("Discord bot ready as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return
        replies_to_bot = await self._replies_to_bot(message)
        content = message_for_bot(
            is_dm=message.guild is None,
            mentions_bot=self.user in message.mentions,
            replies_to_bot=replies_to_bot,
            content=message.content or "",
            bot_id=self.user.id,
            has_images=bool(message.attachments),
        )
        if content is None:
            return
        await self.conduct(message.channel, message.author, content, message.attachments)

    async def conduct(self, channel, author, content: str, attachments) -> None:
        try:
            deployment = require_deployment(self.store, author.id)
            if self.store.session_for(author.id, deployment.server_url) is None:
                raise ChatProblem(
                    f"Not signed in to {deployment.server_url}. Run /login.",
                    deployment=deployment.server_url,
                )
        except ChatProblem as exc:
            await self.send_channel(channel, exc.deployment, str(exc))
            return
        blobs: list[tuple[str, bytes]] = []
        for attachment in attachments:
            try:
                blobs.append((attachment.filename, await attachment.read()))
            except discord.HTTPException:
                await self.send_channel(
                    channel,
                    deployment.server_url,
                    f"Could not download {attachment.filename}.",
                )
                return
        try:
            images = images_from_parts(blobs) if blobs else []
        except ChatProblem as exc:
            await self.send_channel(
                channel,
                deployment.server_url,
                str(exc),
            )
            return
        if not content and not images:
            return
        ticket = await self.queue.join(deployment.server_url)
        try:
            if ticket.ahead:
                await self.send_channel(
                    channel,
                    deployment.server_url,
                    explain_wait(ticket.ahead),
                    mention=author.mention,
                )
            await ticket.wait()
            mention = author.mention if ticket.ahead else None
            fresh = self.store.find(author.id, deployment.server_url)
            if fresh is None:
                await self.send_channel(
                    channel,
                    deployment.server_url,
                    "That deployment was removed before your turn.",
                    mention=mention,
                )
                return
            deployment = fresh
            try:
                reply = await self._turn(channel, author, deployment, content, images)
            except ChatProblem as exc:
                await self.send_channel(
                    channel,
                    exc.deployment or deployment.server_url,
                    str(exc),
                    mention=mention,
                )
                return
            await self.send_channel(channel, deployment.server_url, reply, mention=mention)
        finally:
            await ticket.close()

    async def run_command(self, interaction: discord.Interaction, fn, *, ephemeral: bool = False) -> None:
        try:
            await interaction.response.defer(ephemeral=ephemeral)
            reply = await asyncio.to_thread(fn)
        except ChatProblem as exc:
            await self.send_interaction(interaction, exc.deployment, str(exc), ephemeral=ephemeral)
            return
        except Exception:
            logger.exception("Discord command failed")
            await self.send_interaction(
                interaction,
                None,
                "Something went wrong running that command.",
                ephemeral=True,
            )
            return
        view = None
        if reply.conversations:
            view = ResumeView(self.store, interaction.user.id, reply.conversations)
        await self.send_interaction(
            interaction,
            reply.deployment,
            reply.text,
            ephemeral=ephemeral or reply.ephemeral,
            view=view,
        )

    def _login_reply(self, user_id: int) -> Reply:
        deployment = require_deployment(self.store, user_id)
        if not deployment.supabase_url or not deployment.supabase_publishable_key:
            raise ChatProblem(
                "This deployment did not provide sign-in settings.",
                deployment=deployment.server_url,
            )
        url = self.broker.begin(user_id, deployment)
        return login_message(url, deployment, self.broker.redirect_url)

    async def _turn(
        self,
        channel,
        author,
        deployment: Deployment,
        content: str,
        images,
    ) -> str:
        prompt = content.strip() or "See the attached image."

        def prepare() -> tuple[str, str, str]:
            with client_for(self.store, author.id, deployment) as client:
                if images:
                    ensure_images_allowed(client)
                conversation_id, notice = bind_conversation(
                    client,
                    self.store,
                    author.id,
                    deployment,
                )
                document = client.get_conversation(conversation_id)
                blocked = workflow_gate(document)
                if blocked:
                    raise ChatProblem(
                        blocked + " Sending waits until the workflow is ready.",
                        deployment=deployment.server_url,
                    )
                return conversation_id, notice, client.access_token

        conversation_id, notice, token = await asyncio.to_thread(
            lambda: guard(deployment.server_url, prepare)
        )
        client = AgentApiClient(deployment.server_url, token)
        try:
            body = await self._stream(
                channel,
                author,
                client,
                conversation_id,
                prompt,
                images,
            )
        finally:
            client.close()
        return "\n".join(part for part in (notice, body) if part).strip() or "(no reply)"

    async def _stream(self, channel, author, client: AgentApiClient, conversation_id, content, images) -> str:
        loop = asyncio.get_running_loop()
        events: asyncio.Queue = asyncio.Queue()

        def produce() -> None:
            try:
                for event in client.stream_turn(conversation_id, content, images or None):
                    loop.call_soon_threadsafe(events.put_nowait, ("event", event))
            except Exception as exc:
                loop.call_soon_threadsafe(events.put_nowait, ("error", exc))
            finally:
                loop.call_soon_threadsafe(events.put_nowait, ("end", None))

        threading.Thread(target=produce, name="discord-turn", daemon=True).start()
        text = TurnText()
        failure: str | None = None
        transport: BaseException | None = None
        while True:
            kind, payload = await events.get()
            if kind == "end":
                break
            if kind == "error":
                if isinstance(payload, BaseException):
                    transport = payload
                continue
            if failure or transport or not isinstance(payload, dict):
                continue
            if payload.get("type") == "approval_required":
                try:
                    await self._resolve_approval(
                        channel,
                        author,
                        client,
                        conversation_id,
                        payload,
                    )
                except ChatProblem as exc:
                    failure = str(exc)
                continue
            failure = text.feed(payload)
        if transport is not None:
            raise _transport_problem(client.base_url, transport)
        if failure:
            raise ChatProblem(failure, deployment=client.base_url)
        return text.finish()

    async def _resolve_approval(self, channel, author, client, conversation_id: str, event: dict) -> None:
        commands = list(event.get("commands") or [])
        allow, grant = approval_grant(
            [command for command in commands if isinstance(command, dict)]
        )
        view = ApprovalView(author.id, commands, allow_grant=allow, grant_scope=grant)
        await self.send_channel(channel, client.base_url, format_approval(event), view=view)
        await view.wait()
        approval_id = str(event.get("approval_id") or "")

        def send() -> None:
            if view.choice is None:
                client.resolve_approval(conversation_id, approval_id, approved=False)
                return
            if view.choice.decisions is not None:
                client.resolve_approval(
                    conversation_id,
                    approval_id,
                    decisions=view.choice.decisions,
                )
                return
            client.resolve_approval(
                conversation_id,
                approval_id,
                approved=view.choice.approved,
                grant_scope=view.choice.grant_scope,
            )

        await asyncio.to_thread(lambda: guard(client.base_url, send))
        if view.choice is None:
            await self.send_channel(
                channel,
                client.base_url,
                "Approval timed out. The commands were rejected.",
                mention=author.mention,
            )

    async def _replies_to_bot(self, message: discord.Message) -> bool:
        if self.user is None or message.reference is None:
            return False
        resolved = message.reference.resolved
        if resolved is None and message.reference.message_id is not None:
            try:
                resolved = await message.channel.fetch_message(message.reference.message_id)
            except discord.HTTPException:
                return False
        return resolved is not None and resolved.author.id == self.user.id

    async def send_channel(self, channel, deployment, text, *, mention: str | None = None, view=None) -> None:
        embeds = embeds_for(deployment, text)
        try:
            await channel.send(
                content=mention,
                embeds=embeds[:10],
                view=view,
            )
        except discord.Forbidden:
            logger.warning("Missing permission to reply in channel %s", getattr(channel, "id", ""))
        for extra in embeds[10:]:
            try:
                await channel.send(embed=extra)
            except discord.Forbidden:
                return

    async def send_interaction(
        self,
        interaction: discord.Interaction,
        deployment: str | None,
        text: str,
        *,
        ephemeral: bool = False,
        view=None,
    ) -> None:
        embeds = embeds_for(deployment, text)
        kwargs = {"embeds": embeds[:10], "ephemeral": ephemeral}
        if view is not None:
            kwargs["view"] = view
        try:
            if interaction.response.is_done():
                await interaction.followup.send(**kwargs)
            else:
                await interaction.response.send_message(**kwargs)
        except discord.HTTPException:
            logger.exception("Could not send a Discord reply")
            return
        for extra in embeds[10:]:
            try:
                await interaction.followup.send(embed=extra, ephemeral=ephemeral)
            except discord.HTTPException:
                return


def _button(label: str, style: discord.ButtonStyle, callback, *, row: int) -> discord.ui.Button:
    button = discord.ui.Button(label=label, style=style, row=row)
    button.callback = callback
    return button


async def _owns(interaction: discord.Interaction, owner_id: int) -> bool:
    if interaction.user.id == owner_id:
        return True
    await interaction.response.send_message("This approval is for someone else.", ephemeral=True)
    return False


def _transport_problem(deployment: str, exc: BaseException) -> ChatProblem:
    if isinstance(exc, AgentApiError):
        return ChatProblem(explain_api_error(exc), deployment=deployment)
    if isinstance(exc, httpx.HTTPError):
        return ChatProblem(explain_unreachable(deployment, exc), deployment=deployment)
    logger.exception("Turn failed", exc_info=exc)
    return ChatProblem("The turn failed.", deployment=deployment)

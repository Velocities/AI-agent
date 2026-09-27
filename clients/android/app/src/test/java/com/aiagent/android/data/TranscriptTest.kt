package com.aiagent.android.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TranscriptTest {

    private fun meta(raw: String): JsonObject = Json.parseToJsonElement(raw).jsonObject

    private fun message(position: Int, role: String, content: String = "", metadata: String = "{}") =
        ChatMessage(id = "m$position", role = role, content = content, metadata = meta(metadata), position = position)

    @Test
    fun pairsCommandsWithResultsAndHidesPlumbing() {
        val messages = listOf(
            message(0, "user", "disk?"),
            message(
                1,
                "assistant",
                metadata = """{"tool_calls":[{"id":"c1","name":"run_command","arguments":{
                    "reason":"check disk","target":"box",
                    "command":{"type":"pipe","left":{"type":"single","argv":["df","-h"]},"right":["grep","/dev"]}}}]}""",
            ),
            message(
                2,
                "tool",
                content = """{"success":true,"exit_status":0,"stdout":"/dev/sda1 50%","stderr":"",
                    "duration_ms":12,"rendered_command":"df -h | grep /dev",
                    "metadata":{"execution_target":"box"},
                    "execution_target":{"name":"box","kind":"ssh"}}""",
                metadata = """{"tool_call_id":"c1","name":"run_command"}""",
            ),
            message(3, "user", "internal nudge", """{"internal":true}"""),
            message(
                4,
                "assistant",
                metadata = """{"tool_calls":[{"id":"r1","name":"respond","arguments":{"finished":true,"message":"Half full."}}]}""",
            ),
            message(5, "tool", """{"success":true,"finished":true}""", """{"tool_call_id":"r1","name":"respond"}"""),
        )

        val items = Transcript.build(messages)

        assertEquals(3, items.size)
        assertEquals(ChatItem.User("m0", "disk?"), items[0])
        val command = items[1] as ChatItem.Command
        assertEquals("df -h | grep /dev", command.command)
        assertEquals("ssh", command.targetKind)
        assertEquals("box", command.targetName)
        assertEquals("check disk", command.reason)
        assertEquals(CommandOutcome.SUCCEEDED, command.outcome)
        assertEquals("/dev/sda1 50%", command.stdout)
        assertEquals(0, command.exitStatus)
        assertEquals(ChatItem.Assistant("m4:r1", "Half full."), items[2])
    }

    @Test
    fun commandWithoutResultIsStillRunningAndRendersItsArguments() {
        val items = Transcript.build(
            listOf(
                message(
                    0,
                    "assistant",
                    metadata = """{"tool_calls":[{"id":"c1","name":"run_command","arguments":{
                        "command":{"type":"and","left":{"type":"single","argv":["ls","my dir"]},
                        "right":{"type":"redirect","cmd":{"type":"single","argv":["echo","hi"]},"op":">","path":"/tmp/x"}}}}]}""",
                ),
            ),
        )
        val command = items.single() as ChatItem.Command
        assertEquals(CommandOutcome.RUNNING, command.outcome)
        assertEquals("ls 'my dir' && (echo hi > /tmp/x)", command.command)
        assertNull(command.targetKind)
    }

    @Test
    fun batchResultsMapToEachCommandAndDenialsAreKept() {
        val items = Transcript.build(
            listOf(
                message(
                    0,
                    "assistant",
                    metadata = """{"tool_calls":[{"id":"b","name":"run_commands","arguments":{"commands":[
                        {"type":"single","argv":["uptime"]},{"type":"single","argv":["rm","x"]}]}}]}""",
                ),
                message(
                    1,
                    "tool",
                    content = """[{"success":true,"exit_status":0,"stdout":"up","rendered_command":"uptime",
                        "execution_target":{"name":"local","kind":"local"}},
                        {"success":false,"error":"User denied command execution","user_denied":true,
                        "rendered_command":"rm x","execution_target":{"name":"local","kind":"local"}}]""",
                    metadata = """{"tool_call_id":"b"}""",
                ),
            ),
        )
        val first = items[0] as ChatItem.Command
        val second = items[1] as ChatItem.Command
        assertEquals(CommandOutcome.SUCCEEDED, first.outcome)
        assertEquals(CommandOutcome.DENIED, second.outcome)
        assertEquals("User denied command execution", second.stderr)
        assertEquals("local", second.targetKind)
    }

    @Test
    fun approvalGrantFollowsTheCliRule() {
        fun request(vararg risks: String) = ApprovalRequest(
            "a",
            "c",
            risks.map { PendingCommand("x", it, null, true, null, null, null) },
        )
        assertEquals(ApprovalRequest.GRANT_READ_ONLY, request("READ_ONLY").sessionGrantScope)
        assertEquals(ApprovalRequest.GRANT_REVERSIBLE, request("READ_ONLY", "REVERSIBLE").sessionGrantScope)
        assertNull(request("DESTRUCTIVE").sessionGrantScope)
        assertEquals(true, request("REVERSIBLE", "DESTRUCTIVE").isDestructive)
    }

    @Test
    fun parsesStreamEvents() {
        val event = TurnEvent.parse(
            """{"type":"approval_required","approval_id":"a1","conversation_id":"c1","commands":[
                {"command":"docker ps","risk":"READ_ONLY","reason":"list","allowed":true,
                 "target":"web (docker:web)","target_name":"web","target_kind":"docker"}]}""",
        ) as TurnEvent.ApprovalRequired
        assertEquals("docker", event.request.commands.single().targetKind)
        assertEquals(TurnEvent.Token("hi"), TurnEvent.parse("""{"type":"token","text":"hi"}"""))
        val message = TurnEvent.parse(
            """{"type":"message","message":{"id":"m","role":"user","content":"x","created_at":"t","metadata":{},"position":2}}""",
        ) as TurnEvent.Message
        assertEquals(2, message.message.position)
        assertEquals(TurnEvent.Done("", "cancelled"), TurnEvent.parse("""{"type":"done","message":"","error":"cancelled"}"""))
    }

    @Test
    fun readsAccessGateErrors() {
        val error = AgentApi.errorFrom(403, """{"detail":{"code":"access_pending","message":"Wait."}}""")
        assertEquals("Wait.", error.message)
        assertEquals(true, error.isAccessGate)
        assertEquals("Not found", AgentApi.errorFrom(404, """{"detail":"Not found"}""").message)
    }
}

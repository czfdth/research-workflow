"""The read-only MCP gate server."""

import contextlib
import io
import json
import unittest
from unittest import mock

from ccfa import mcp_gates

# The complete surface. Anything that could change state must never appear here.
READ_ONLY_TOOLS = {
    "argument_audit",
    "brief",
    "doctor",
    "e2e_check",
    "readiness",
    "worklist",
}

REPORT = {
    "ready": False,
    "stage": {"current": "internal-review", "gate": "review_cleared"},
    "blocking": ["argument-audit gate failed"],
    "dimensions": {"schema-valid": "pass"},
    "human_review": {"pending": ["proof"]},
    "gate_results": [
        {
            "name": "argument-audit",
            "status": "problem",
            "problem_count": 1,
            "problems": [{"code": "proof-review-not-verified"}],
        }
    ],
}


class DescriptorTests(unittest.TestCase):
    def test_the_surface_is_exactly_the_read_only_allowlist(self):
        names = {item["name"] for item in mcp_gates.tool_descriptors()}

        self.assertEqual(names, READ_ONLY_TOOLS)

    def test_every_tool_is_annotated_read_only(self):
        for item in mcp_gates.tool_descriptors():
            with self.subTest(tool=item["name"]):
                self.assertTrue(item["annotations"]["readOnlyHint"])

    def test_every_tool_declares_a_valid_object_schema(self):
        for item in mcp_gates.tool_descriptors():
            with self.subTest(tool=item["name"]):
                schema = item["inputSchema"]
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
                for key in schema["required"]:
                    self.assertIn(key, schema["properties"])

    def test_no_tool_name_suggests_a_mutation(self):
        forbidden = ("apply", "write", "advance", "set", "fix", "resolve", "run")
        for item in mcp_gates.tool_descriptors():
            with self.subTest(tool=item["name"]):
                self.assertFalse(
                    any(word in item["name"] for word in forbidden),
                    f"{item['name']} 看起来会改状态",
                )


class CallToolTests(unittest.TestCase):
    def test_an_unknown_tool_is_refused(self):
        with self.assertRaisesRegex(ValueError, "未知工具"):
            mcp_gates.call_tool("apply", {})

    def test_a_missing_required_argument_is_refused(self):
        with self.assertRaisesRegex(ValueError, "缺少参数"):
            mcp_gates.call_tool("readiness", {})

    def test_blank_required_arguments_are_refused(self):
        with self.assertRaisesRegex(ValueError, "缺少参数"):
            mcp_gates.call_tool("worklist", {"paper_root": "   "})

    def test_non_object_arguments_are_refused(self):
        with self.assertRaisesRegex(ValueError, "必须是对象"):
            mcp_gates.call_tool("doctor", ["nope"])  # type: ignore[arg-type]

    def test_calling_readiness_does_not_reimplement_the_gate(self):
        with mock.patch.object(
            mcp_gates.readiness, "build_report", return_value=REPORT
        ) as builder:
            payload = mcp_gates.call_tool(
                "readiness", {"paper_root": "papers/demo"}
            )

        builder.assert_called_once()
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["stage"], "internal-review")
        self.assertIn("argument-audit", payload["gates"])

    def test_the_profile_is_passed_through(self):
        with mock.patch.object(
            mcp_gates.readiness, "build_report", return_value=REPORT
        ) as builder:
            mcp_gates.call_tool(
                "readiness", {"paper_root": "p", "profile": "high-assurance"}
            )

        self.assertEqual(builder.call_args.kwargs.get("profile"), "high-assurance")

    def test_worklist_delegates_to_the_worklist_module(self):
        with mock.patch.object(
            mcp_gates.worklist, "collect", return_value={"items": []}
        ) as collector:
            mcp_gates.call_tool("worklist", {"paper_root": "p"})

        collector.assert_called_once()

    def test_argument_audit_reports_codes_only(self):
        class _Item:
            def __init__(self, code):
                self.code = code
                self.message = f"{code} 说明"

        with mock.patch.object(
            mcp_gates.argument_audit,
            "check",
            return_value=([_Item("proof-review-not-verified")], []),
        ):
            payload = mcp_gates.call_tool("argument_audit", {"paper_root": "p"})

        self.assertEqual(payload["problem_count"], 1)
        self.assertEqual(payload["problems"][0]["code"], "proof-review-not-verified")

    def test_doctor_reports_counts_not_raw_statuses(self):
        with mock.patch.object(
            mcp_gates.doctor,
            "check_environment",
            return_value=([], [], ["installed x", "MISSING y"]),
        ):
            payload = mcp_gates.call_tool("doctor", {})

        self.assertEqual(payload["problem_count"], 0)
        self.assertEqual(payload["status_count"], 2)
        self.assertNotIn("statuses", payload)


class ProtocolTests(unittest.TestCase):
    def test_initialize_returns_the_protocol_and_server_info(self):
        response = mcp_gates.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )

        result = response["result"]
        self.assertEqual(result["protocolVersion"], mcp_gates.PROTOCOL_VERSION)
        self.assertEqual(result["serverInfo"]["name"], "ccfa-gates")
        self.assertIn("tools", result["capabilities"])

    def test_notifications_get_no_response(self):
        self.assertIsNone(
            mcp_gates.handle(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        )

    def test_tools_list_returns_the_descriptors(self):
        response = mcp_gates.handle(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )

        self.assertEqual(
            {item["name"] for item in response["result"]["tools"]},
            READ_ONLY_TOOLS,
        )

    def test_ping_returns_an_empty_result(self):
        response = mcp_gates.handle({"jsonrpc": "2.0", "id": 3, "method": "ping"})

        self.assertEqual(response["result"], {})

    def test_an_unknown_method_is_a_method_not_found(self):
        response = mcp_gates.handle(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/apply"}
        )

        self.assertEqual(response["error"]["code"], -32601)

    def test_a_bad_tools_call_is_an_invalid_params_error(self):
        response = mcp_gates.handle(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "readiness", "arguments": {}},
            }
        )

        self.assertEqual(response["error"]["code"], -32602)

    def test_a_successful_call_wraps_text_content(self):
        with mock.patch.object(
            mcp_gates.readiness, "build_report", return_value=REPORT
        ):
            response = mcp_gates.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {
                        "name": "readiness",
                        "arguments": {"paper_root": "p"},
                    },
                }
            )

        content = response["result"]["content"][0]
        self.assertEqual(content["type"], "text")
        self.assertFalse(json.loads(content["text"])["ready"])
        self.assertFalse(response["result"]["isError"])


class ServeTests(unittest.TestCase):
    def _serve(self, lines):
        stdin = io.StringIO("\n".join(lines) + "\n")
        stdout = io.StringIO()
        with mock.patch.object(
            mcp_gates.readiness, "build_report", return_value=REPORT
        ):
            code = mcp_gates.serve(stdin, stdout)
        responses = [
            json.loads(line)
            for line in stdout.getvalue().splitlines()
            if line.strip()
        ]
        return code, responses

    def test_a_round_trip_answers_each_request(self):
        code, responses = self._serve(
            [
                '{"jsonrpc":"2.0","id":1,"method":"initialize"}',
                '{"jsonrpc":"2.0","method":"notifications/initialized"}',
                '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual([item["id"] for item in responses], [1, 2])

    def test_malformed_lines_are_reported_and_the_loop_continues(self):
        code, responses = self._serve(
            ["not json", '{"jsonrpc":"2.0","id":9,"method":"ping"}']
        )

        self.assertEqual(code, 0)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["id"], 9)

    def test_blank_lines_are_skipped(self):
        code, responses = self._serve(["", "   ", '{"jsonrpc":"2.0","id":1,"method":"ping"}'])

        self.assertEqual(code, 0)
        self.assertEqual(len(responses), 1)


class CliTests(unittest.TestCase):
    def _run(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = mcp_gates.main(["mcp-gates", *argv])
        return code, stdout.getvalue()

    def test_list_tools_prints_the_allowlist(self):
        code, output = self._run(["list-tools"])

        self.assertEqual(code, 0)
        self.assertEqual(
            {item["name"] for item in json.loads(output)}, READ_ONLY_TOOLS
        )

    def test_call_parses_key_value_arguments(self):
        with mock.patch.object(
            mcp_gates.readiness, "build_report", return_value=REPORT
        ):
            code, output = self._run(
                ["call", "--tool", "readiness", "--arg", "paper_root=p"]
            )

        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output)["ready"])

    def test_an_unknown_tool_is_a_setup_error(self):
        code, _output = self._run(["call", "--tool", "apply"])

        self.assertEqual(code, 2)

    def test_a_malformed_arg_is_a_setup_error(self):
        code, _output = self._run(["call", "--tool", "doctor", "--arg", "nope"])

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()

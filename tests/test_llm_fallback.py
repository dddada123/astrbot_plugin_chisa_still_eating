"""离线回归：模拟 LLM 和消息事件，执行真实回复生成及抽菜流程。"""
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
ERROR_TEXT = (
    "All chat models failed: InternalServerError: Error code: 503 - "
    "No available channel for model private-model under group private-group "
    "(request id: private-request-id)"
)


def load_plugin():
    # 仅替代框架导入和装饰器；不启动 AstrBot、WebUI 或网络请求。
    package = ModuleType("chisa_fallback_test")
    package.__path__ = [str(ROOT)]
    star = ModuleType("astrbot.api.star")
    star.Context = star.Star = object
    star.register = lambda *args: lambda cls: cls
    event = ModuleType("astrbot.api.event")
    event.AstrMessageEvent = object
    event.filter = SimpleNamespace(event_message_type=lambda *args: lambda fn: fn)
    event_filter = ModuleType("astrbot.api.event.filter")
    event_filter.EventMessageType = SimpleNamespace(ALL="all")
    quart = ModuleType("quart")
    quart.jsonify = quart.request = quart.send_file = None
    stubs = {
        package.__name__: package,
        "astrbot": ModuleType("astrbot"),
        "astrbot.api": ModuleType("astrbot.api"),
        "astrbot.api.star": star,
        "astrbot.api.event": event,
        "astrbot.api.event.filter": event_filter,
        "quart": quart,
        "aiohttp": ModuleType("aiohttp"),
        "requests": ModuleType("requests"),
    }
    with patch.dict(sys.modules, stubs):
        return importlib.import_module(f"{package.__name__}.main")


plugin = load_plugin()


def make_context(api, response=None, error=None):
    call = AsyncMock(return_value=response, side_effect=error)
    if api == "tool_loop_agent":
        context = SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value="test-provider"),
            tool_loop_agent=call,
        )
    else:
        service = SimpleNamespace(**{api: call})
        context = SimpleNamespace(get_llm_service=Mock(return_value=service))
    return context, call


class Message:
    def __init__(self):
        self.text = ""
        self.images = []

    def message(self, text):
        self.text = text
        return self

    def file_image(self, path):
        self.images.append(path)
        return self


class Event:
    def __init__(self, group_id="test-group"):
        self.unified_msg_origin = "test-origin"
        self.message_obj = SimpleNamespace(group_id=group_id)
        self.should_call_llm = Mock()
        self.stop_event = Mock()

    def get_sender_id(self):
        return "test-user"

    def make_result(self):
        return Message()


class ResponderTests(unittest.IsolatedAsyncioTestCase):
    APIS = ("tool_loop_agent", "text_chat", "generate_text")

    async def respond(self, api, response=None, error=None):
        context, call = make_context(api, response, error)
        text = await plugin.Responder().generate_response(
            context, Event(), "推荐官", "测试世界", "炒饭", "food", "none", False
        )
        call.assert_awaited_once()
        return text

    async def test_valid_replies_are_preserved(self):
        for api in self.APIS:
            for text in ("  这份炒饭香气十足，快来尝尝！\n", "推荐503号套餐，429克食材，吃饭别超时！"):
                with self.subTest(api=api, text=text):
                    response = SimpleNamespace(role="assistant", completion_text=text) if api == "tool_loop_agent" else text
                    self.assertEqual(await self.respond(api, response), text.strip())

    async def test_empty_or_invalid_content_falls_back(self):
        for api in self.APIS:
            for content in (None, "", " \n\t", [], {}):
                with self.subTest(api=api, content=content), self.assertLogs("astrbot", level="WARNING"):
                    response = SimpleNamespace(role="assistant", completion_text=content) if api == "tool_loop_agent" else content
                    self.assertEqual(await self.respond(api, response), "")
        with self.assertLogs("astrbot", level="WARNING"):
            self.assertEqual(await self.respond("tool_loop_agent", None), "")
            self.assertEqual(await self.respond("tool_loop_agent", object()), "")

    async def test_error_role_falls_back_without_relying_on_keywords(self):
        response = SimpleNamespace(role="err", completion_text="private provider diagnostic")
        with self.assertLogs("astrbot", level="WARNING") as logs:
            self.assertEqual(await self.respond("tool_loop_agent", response), "")
        self.assertIn("private provider diagnostic", "\n".join(logs.output))

    async def test_plain_error_text_falls_back_on_every_api(self):
        for api in self.APIS:
            for text in (
                ERROR_TEXT,
                "all CHAT models FAILED: upstream unavailable",
                "All available chat models are unavailable.",
                "HTTP 503 Service Unavailable",
                "Error code: 429 - Too Many Requests",
                "APITimeoutError: request timed out",
                "Request timed out.",
                'Traceback (most recent call last):\n  private diagnostic',
                '{"error": {"message": "private diagnostic"}}',
            ):
                with self.subTest(api=api, text=text), self.assertLogs("astrbot", level="WARNING") as logs:
                    response = SimpleNamespace(role="assistant", completion_text=text) if api == "tool_loop_agent" else text
                    self.assertEqual(await self.respond(api, response), "")
                self.assertIn(text, "\n".join(logs.output))

    async def test_exceptions_fall_back_and_remain_in_logs(self):
        for api in self.APIS:
            for error in (RuntimeError("HTTP 503"), RuntimeError("Error code: 429"), TimeoutError("upstream timeout")):
                with self.subTest(api=api, error=error), self.assertLogs("astrbot", level="ERROR") as logs:
                    self.assertEqual(await self.respond(api, error=error), "")
                self.assertIn(str(error), "\n".join(logs.output))

    async def test_provider_lookup_failure_does_not_call_model(self):
        context, call = make_context("tool_loop_agent")
        context.get_current_chat_provider_id.side_effect = RuntimeError("provider unavailable")
        with self.assertLogs("astrbot", level="ERROR"):
            text = await plugin.Responder().generate_response(
                context, Event(), "推荐官", "测试世界", "炒饭", "food", "none", False
            )
        self.assertEqual(text, "")
        call.assert_not_awaited()


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def run_flow(self, response=None, error=None, enable_ai=True, category="food", group_id="test-group"):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            food_dir = data_dir / "food"
            food_dir.mkdir()
            food_image = food_dir / "炒饭.png"
            meme_image = data_dir / "meme.png"
            # 真实文件路径；消息链只记录文件，不连接平台发送。
            png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b49444154789c6364600000000600023081d02f0000000049454e44ae426082")
            food_image.write_bytes(png)
            meme_image.write_bytes(png)
            bot = object.__new__(plugin.FlavorFusionUltimate)
            bot.config = {
                "enable_ai": enable_ai, "ai_probability": 100,
                "repeat_prob": 0, "egg_prob": 0, "global_meme_prob": 100,
                "convert_meme_to_gif": False,
                "generic_templates": ["本地推荐：{food}。"],
                "generic_drink_templates": ["本地饮品：{food}。"],
                "dark_templates": ["黑暗料理：{food}！"],
            }
            bot.wv_settings = {"world1": {"1.世界名称": "测试世界", "3.自称池": ["推荐官"]}}
            bot.context, call = make_context("tool_loop_agent", response, error)
            bot.responder = plugin.Responder()
            bot.limiter = plugin.RateLimiter()
            bot.data_mgr = object.__new__(plugin.FoodDataManager)
            bot.data_mgr.config = bot.config
            bot.data_mgr.history_limit = 30
            bot.data_mgr.group_history = {}
            bot.data_mgr.history_path = str(data_dir / "history.json")
            bot.image_mgr = SimpleNamespace(
                data_dir=tmp,
                cached_pools={category: [{
                    "wv": "common", "food": "炒饭", "raw_name": "炒饭",
                    "chef": "none", "has_image": True, "path": str(food_image),
                }]},
                get_bot_meme=Mock(return_value=str(meme_image)),
            )
            event = Event(group_id)
            results = [result async for result in bot.execute_flow(event, category)]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].images, [str(food_image), str(meme_image)])
            history_key = group_id or "test-user"
            self.assertEqual(list(bot.data_mgr.group_history[history_key]), ["炒饭"])
            event.stop_event.assert_called_once()
            if enable_ai:
                call.assert_awaited_once()
            else:
                call.assert_not_awaited()
            return results[0].text

    async def test_failures_keep_local_text_food_image_and_meme(self):
        for response, error in (
            (SimpleNamespace(role="err", completion_text=ERROR_TEXT), None),
            (SimpleNamespace(role="assistant", completion_text=ERROR_TEXT), None),
            (SimpleNamespace(role="assistant", completion_text=" \n"), None),
            (None, RuntimeError("HTTP 503")),
            (None, RuntimeError("Error code: 429")),
            (None, TimeoutError("private upstream timeout")),
        ):
            with self.subTest(response=response, error=error), self.assertLogs("astrbot", level="WARNING"):
                self.assertEqual(await self.run_flow(response, error), "本地推荐：炒饭。")

    async def test_private_message_failure_also_falls_back(self):
        with self.assertLogs("astrbot", level="WARNING"):
            self.assertEqual(await self.run_flow(ERROR_TEXT, group_id=None), "本地推荐：炒饭。")

    async def test_valid_ai_reply_keeps_images(self):
        text = "炒饭香气十足，快来尝尝！"
        self.assertEqual(await self.run_flow(SimpleNamespace(role="assistant", completion_text=text)), text)

    async def test_non_ai_template_mode_is_unchanged(self):
        self.assertEqual(await self.run_flow(enable_ai=False), "本地推荐：炒饭。")

    async def test_drink_and_dark_templates_still_work_after_failure(self):
        for category, expected in (("drink", "本地饮品：炒饭。"), ("dark", "黑暗料理：炒饭！")):
            with self.subTest(category=category), self.assertLogs("astrbot", level="WARNING"):
                self.assertEqual(await self.run_flow(ERROR_TEXT, category=category), expected)


if __name__ == "__main__":
    unittest.main()

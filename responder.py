import logging
import re

class Responder:
    """高阶AI拟人化沉浸回复接入总线：仅提供情境，完全依赖 AstrBot 原生人格进行回复"""
    # 兼容未标记 role="err"、而是把上游错误作为普通文本返回的接口。
    _ERROR_TEXT = re.compile(
        r"all chat models failed\b|all available chat models are unavailable\b|"
        r"no available channel for model\b|"
        r"\b(?:InternalServerError|RateLimitError|APITimeoutError|"
        r"APIConnectionError|TimeoutError)\s*:|"
        r"\b(?:error code|http(?:/\d(?:\.\d)?)?(?: error)?|status(?: code)?)"
        r"\s*[:=]?\s*[45]\d{2}\b|"
        r"\b(?:request|connection) (?:timed out|timeout)\b|"
        r'Traceback \(most recent call last\):|^\s*\{\s*"error"\s*:',
        re.IGNORECASE,
    )

    def __init__(self):
        self.logger = logging.getLogger("astrbot")

    async def generate_response(self, context, event, bot_name: str, world_name: str, food_name: str, category: str, chef_name: str, is_crossover: bool) -> str:
        # 精细化物品描述
        cat_desc = "饮品" if category == "drink" else "黑暗料理" if category == "dark" else "食物"
        
        # 告诉 LLM 当前的突发情况（只给事件，不教它做事）
        if is_crossover:
            context_desc = f"你偶然得到了一份来自异世界（{world_name}）的{cat_desc}【{food_name}】。"
        elif chef_name != "none":
            context_desc = f"【{chef_name}】刚刚做好了{cat_desc}【{food_name}】，并交给了你。"
        else:
            context_desc = f"你手里现在有一份{cat_desc}【{food_name}】。"

        # 🎯 针对动词、情绪和【菜品评价】的脑补引导
        if category == "drink":
            action_hint = "请你把这杯饮品递给群友（玩家），并顺嘴凭借你的想象，简单评价一下它的香气、外观或你猜它的味道。⚠️注意：台词中必须用“喝”、“干杯”等词汇，绝不能说“吃”。"
        elif category == "dark":
            action_hint = "请把这份东西拿给群友（玩家）。⚠️注意：这是极度可怕的黑暗料理！你必须表现出嫌弃、警惕或疯狂吐槽的语气，并脑补描述一下它诡异可怕的卖相。"
        else:
            action_hint = "请你顺势把这个食物递给群友（玩家），并在台词中凭借你的想象，简单评价一下它的卖相、香气，或者表达你想不想吃。"

        # 🚀 纯情境提示词：彻底移除强制角色扮演，100% 依赖 AstrBot 系统原生人格
        prompt = (
            f"[系统情境注入：{context_desc} {action_hint}]\n"
            f"请你完全保持你当前已被设定的系统人格与口癖，针对这个情境，直接对群友说一句互动台词。\n"
            f"【必须遵守的规则】：\n"
            f"1. 零AI前摇：严禁说“好的”、“没问题”，第一个字必须是你的台词。\n"
            f"2. 拒绝报菜名：不要机械地复述“这是一份由xx特制的xx”，像真人水群一样自然引出。\n"
            f"3. 纯净输出：严禁包含任何中括号、括号()、旁白动作描写、或者多余的系统解释。\n"
            f"4. 字数控制：台词严格控制在 20-60 字以内，既要精炼又要有画面感。\n"
            f"请直接说出这句台词："
        )

        try:
            response = None
            # === 适配 AstrBot 最新版 API 调用大模型 ===
            if hasattr(context, "get_current_chat_provider_id") and hasattr(context, "tool_loop_agent"):
                umo = event.unified_msg_origin
                prov_id = await context.get_current_chat_provider_id(umo)
                response = await context.tool_loop_agent(
                    event=event,
                    chat_provider_id=prov_id,
                    prompt=prompt
                )
            
            # === 向下兼容旧版 API ===
            elif hasattr(context, "get_llm_service"):
                llm_service = context.get_llm_service()
                if llm_service:
                    if hasattr(llm_service, "text_chat"):
                        response = await llm_service.text_chat(prompt)
                    elif hasattr(llm_service, "generate_text"):
                        response = await llm_service.generate_text(prompt)
            
            # AstrBot 的失败响应可能包含非空 completion_text，不能当作台词发送。
            if getattr(response, "role", None) == "err":
                self.logger.warning(
                    "[FlavorFusion AI] 大模型返回错误，使用本地文案: %s",
                    getattr(response, "completion_text", ""),
                )
                return ""

            result_text = response if isinstance(response, str) else getattr(response, "completion_text", "")
            if isinstance(result_text, str) and result_text.strip():
                result_text = result_text.strip()
                if self._ERROR_TEXT.search(result_text):
                    self.logger.warning(
                        "[FlavorFusion AI] 大模型返回错误文本，使用本地文案: %s", result_text
                    )
                    return ""
                return result_text

            self.logger.warning("[FlavorFusion AI] 未能找到兼容的 AstrBot 大模型接口或模型返回为空")
            return ""
        except Exception as e:
            self.logger.error(f"[FlavorFusion AI] 大模型沉浸回复总线调用失败: {str(e)}")
            return ""

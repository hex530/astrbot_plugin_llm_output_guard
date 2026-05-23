from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
import logging
import re

logger = logging.getLogger("astrbot")

@register("llm_output_guard", "夕小柠 & 陆渊", "高情商输出卫兵：双模型校验与自动重写", "1.3.0")
class LLMOutputGuard(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

    @filter.on_decorating_result()
    async def guard_output(self, event: AstrMessageEvent):
        # 1. 基础配置读取
        limit = self.config.get("limit", 100)
        enable_group = self.config.get("enable_group", True)
        enable_private = self.config.get("enable_private", False)
        
        # 兼容性判定 group_id
        is_group = event.message_obj.group_id if event.message_obj else None
        
        # 2. 场景开关判定
        if is_group:
            if not enable_group: return
            blacklist = [x.strip() for x in str(self.config.get("group_blacklist", "")).split(",") if x.strip()]
            if str(is_group) in blacklist: return
        else:
            if not enable_private: return

        # 3. 内容获取与预处理
        chain = event.get_result()
        if not chain: return
        text = chain.get_plain_text().strip()
        
        # 🛡️ 无论字数多少，先处理 think 标签（防止思考过程泄露）
        if "<think>" in text.lower():
            text = re.sub(r'(?i)<think>.*?</think>', '', text, flags=re.DOTALL).strip()
            # 如果切完后是空的，给个兜底
            if not text: text = "..." 
            event.set_result(event.make_result().plain(text))

        # 4. 字数拦截判定
        if len(text) <= limit:
            return

        # --- 核心拦截与重写逻辑 ---
        logger.info(f"[OutputGuard] 检测到输出超长({len(text)}字)，启动监工模型校验...")
        
        try:
            llm_service = self.context.get_llm_service()
            
            default_prompt = (
                "你是一个输出质量监工。以下是一段 AI 生成的回复内容：\n"
                "---内容开始---\n{text}\n---内容结束---\n"
                "你的任务：\n"
                "1. 判定这段内容是否为‘复读’、‘胡言乱语’或‘无意义的碎碎念’。\n"
                "2. 如果内容是在认真、详细地解答问题，请原样返回这段内容。\n"
                "3. 如果内容存在问题，请将其重写为一段简短、得体、高情商的回复（不超过 50 字）。\n"
                "请直接输出最终的回复内容，不要包含任何解释。"
            )
            system_prompt = self.config.get("monitor_prompt", default_prompt).format(text=text)
            
            model_id = self.config.get("monitor_model", "")
            # 使用标准的 LLM 请求接口
            resp = await llm_service.request_llm(system_prompt, model_id=model_id if model_id else None)
            final_text = resp.completion_text.strip() # 修正字段为 completion_text
            
            if final_text:
                event.set_result(event.make_result().plain(final_text))
                logger.info("[OutputGuard] 校验完成，已应用重写/放行逻辑。")
            
        except Exception as e:
            logger.error(f"[OutputGuard] 监工校验出错: {e}")
            # 兜底：截断输出
            event.set_result(event.make_result().plain(text[:limit] + "..."))

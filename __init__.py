"""ComfyUI entry point. No network calls or credential reads at import time."""

from .nodes import (SamuelEnhancerService, SamuelEnhancerTemplate, SamuelEnhancerConfig, SamuelEnhancerGeneration,
                    SamuelEnhancerReverse, SamuelEnhancerEdit, SamuelEnhancerTextInput, SamuelEnhancerPreview,
                    SamuelEnhancerPromptEditor)

NODE_CLASS_MAPPINGS = {
    "SamuelEnhancerService": SamuelEnhancerService,
    "SamuelEnhancerTemplate": SamuelEnhancerTemplate,
    "SamuelEnhancerConfig": SamuelEnhancerConfig,
    "SamuelEnhancerGeneration": SamuelEnhancerGeneration,
    "SamuelEnhancerReverse": SamuelEnhancerReverse,
    "SamuelEnhancerEdit": SamuelEnhancerEdit,
    "SamuelEnhancerTextInput": SamuelEnhancerTextInput,
    "SamuelEnhancerPreview": SamuelEnhancerPreview,
    "SamuelEnhancerPromptEditor": SamuelEnhancerPromptEditor,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "SamuelEnhancerService": "Samuel-Enhancer · LLM 服务配置",
    "SamuelEnhancerTemplate": "Samuel-Enhancer · 模板预设编辑器",
    "SamuelEnhancerConfig": "Samuel-Enhancer · 任务配置",
    "SamuelEnhancerGeneration": "Samuel-Enhancer · 文本创作",
    "SamuelEnhancerReverse": "Samuel-Enhancer · 参考图反推",
    "SamuelEnhancerEdit": "Samuel-Enhancer · 图片编辑",
    "SamuelEnhancerTextInput": "Samuel-Enhancer · 文本输入",
    "SamuelEnhancerPreview": "Samuel-Enhancer · 文本预览",
    "SamuelEnhancerPromptEditor": "Samuel-Enhancer · 提示词编辑与预览",
}
WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

from .routes import register_routes
register_routes()

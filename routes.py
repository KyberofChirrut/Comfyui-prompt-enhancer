"""Local preset loading only; no remote calls and no user-selected file paths."""
from .prompts import PRESETS, TASK_RULES, load_preset


def register_routes():
    try:
        from server import PromptServer
        from aiohttp import web
    except ImportError:
        return
    instance = getattr(PromptServer, 'instance', None)
    if instance is None or getattr(instance, '_samuel_enhancer_presets_registered', False):
        return

    @instance.routes.get('/samuel_enhancer/presets/{preset}')
    async def preset(request):
        name = request.match_info['preset']
        if name not in PRESETS:
            return web.json_response({'error': 'Unknown preset'}, status=404)
        return web.json_response({'preset': name, 'text': load_preset(name), 'task_rules': TASK_RULES})

    instance._samuel_enhancer_presets_registered = True

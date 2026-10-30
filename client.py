"""Small OpenAI-compatible HTTP client; no SDK dependency and no automatic retries."""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


class ExpansionError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_connection(provider, api_type, local_base_url, api_key_env):
    if provider not in ("local", "openai"):
        raise ExpansionError("服务类型必须为 local 或 openai。")
    if api_type not in ("auto", "chat_completions", "responses"):
        raise ExpansionError("不支持的 API 类型。")
    kind = ("responses" if provider == "openai" else "chat_completions") if api_type == "auto" else api_type
    base = "https://api.openai.com/v1" if provider == "openai" else local_base_url.strip().rstrip("/")
    try:
        url = urllib.parse.urlsplit(base)
        valid = (url.scheme in ("http", "https") and url.hostname and not url.username
                 and not url.password and not url.query and not url.fragment and url.port != 0
                 and not any(c.isspace() for c in base))
    except ValueError:
        valid = False
    if not valid:
        raise ExpansionError("服务地址须为 http(s) 基础地址，不能包含账号、密码、查询参数或片段。")
    if url.path.rstrip("/").endswith(("/chat/completions", "/responses")):
        raise ExpansionError("请填写 API 基础地址（通常以 /v1 结尾），不要填写完整接口路径。")
    env_name = api_key_env.strip() or ("OPENAI_API_KEY" if provider == "openai" else "SAMUEL_ENHANCER_API_KEY")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise ExpansionError("api_key_env 填写环境变量名称，不能填写密钥本身。")
    key = os.environ.get(env_name, "").strip()
    if (provider == "openai" or api_key_env.strip()) and not key:
        raise ExpansionError("未找到 API Key 环境变量；请在 ComfyUI 服务端配置并重新启动。")
    if "\n" in key or "\r" in key:
        raise ExpansionError("API Key 环境变量格式无效。")
    endpoint = base + ("/responses" if kind == "responses" else "/chat/completions")
    return kind, endpoint, key


def build_payload(kind, provider, model, system, user, image_url, max_tokens,
                  use_temperature=False, temperature=0.6, extra_json="{}", *, response_schema=None):
    if not isinstance(model, str) or not model.strip():
        raise ExpansionError("请填写服务实际提供的模型 ID。")
    if kind == "chat_completions":
        content = user
        if image_url:
            content = [{"type": "text", "text": user},
                       {"type": "image_url", "image_url": {"url": image_url}}]
        payload = {"model": model.strip(), "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": content}],
            "stream": False}
        payload["max_completion_tokens" if provider == "openai" else "max_tokens"] = max_tokens
    else:
        content = [{"type": "input_text", "text": user}]
        if image_url:
            content.append({"type": "input_image", "image_url": image_url})
        payload = {"model": model.strip(), "instructions": system,
                   "input": [{"role": "user", "content": content}],
                   "max_output_tokens": max_tokens, "stream": False, "store": False}
    if use_temperature:
        payload["temperature"] = temperature
    try:
        extras = json.loads(extra_json or "{}")
    except (ValueError, TypeError):
        raise ExpansionError("高级参数必须是合法 JSON 对象。") from None
    # Keep credentials, endpoint, prompts and token budgets under node control.
    allowed = {"top_p", "presence_penalty", "frequency_penalty", "seed", "stop",
               "reasoning_effort", "reasoning", "chat_template_kwargs", "top_k", "min_p"}
    if not isinstance(extras, dict) or set(extras) - allowed:
        raise ExpansionError("高级参数包含不支持的字段；允许字段见 README。")
    payload.update(extras)
    if response_schema is not None:
        output_format = {'type': 'json_schema', 'json_schema': {
            'name': 'prompt_enhancer_result', 'strict': True, 'schema': response_schema}}
        if kind == 'chat_completions':
            payload['response_format'] = output_format
        else:
            payload['text'] = {'format': {'type': 'json_schema', **output_format['json_schema']}}
    return payload


def request_json(endpoint, key, payload, timeout):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers=headers, method="POST")
    try:
        # Do not forward credentials to redirects; respect configured HTTP(S)_PROXY/NO_PROXY.
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ExpansionError("接口响应过大，已停止读取。")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ExpansionError("接口返回的 JSON 不是对象。")
        return result
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        hints = {400: "检查模型、图像支持和高级参数", 401: "检查服务端 API Key", 403: "检查账户权限",
                 404: "检查基础地址、API 类型和模型 ID", 429: "请求过多或额度不足"}
        raise ExpansionError(f"LLM 接口 HTTP {code}；{hints.get(code, '检查服务状态；不会自动重试')}。") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ExpansionError("LLM 网络请求失败或超时。请从运行 ComfyUI 的机器检查连通性；未自动重试。") from None
    except (ValueError, UnicodeError):
        raise ExpansionError("LLM 返回的不是有效 JSON；检查接口类型。") from None


def clean_text(text, allow_json=False):
    if not isinstance(text, str):
        raise ExpansionError("模型没有返回可用的文本正文。")
    text = text.strip()
    # Some compatible servers place reasoning tags in content rather than a separate field.
    while text.startswith("<think>"):
        end = text.find("</think>")
        if end < 0:
            raise ExpansionError("模型只返回了未完成的思考过程；请增加输出额度或关闭服务端思考模式。")
        text = text[end + len("</think>"):].strip()
    if "<think>" in text or "</think>" in text:
        raise ExpansionError("正文混入无法安全分离的思考标签；请检查模型输出配置。")
    tags = "text|plaintext|json" if allow_json else "text|plaintext"
    fence = re.fullmatch(r"```(?:" + tags + r")?\s*\n([\s\S]*?)\n```", text)
    if fence:
        text = fence.group(1).strip()
    if not text:
        raise ExpansionError("模型没有输出最终提示词；思考字段不会作为提示词返回。")
    if text.startswith("```"):
        raise ExpansionError("模型返回了不符合正文要求的代码块，请重新扩写。")
    return text


def parse_response(kind, data, allow_json=False):
    if data.get("error"):
        raise ExpansionError("LLM 返回错误对象；检查服务端日志（节点不显示可能含敏感内容的错误正文）。")
    if kind == "chat_completions":
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ExpansionError("Chat Completions 响应缺少 choices。")
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish == "length":
            raise ExpansionError("提示词输出被截断；请增大 max_output_tokens 或缩短目标长度。")
        if finish != "stop":
            raise ExpansionError("模型未正常完成文本输出（过滤、工具调用或未知结束状态）。")
        message = choice.get("message", {})
        if not isinstance(message, dict) or message.get("refusal"):
            raise ExpansionError("模型拒绝或未返回有效消息。")
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(p["text"] for p in content
                                if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str))
    else:
        if data.get("status") != "completed":
            raise ExpansionError("Responses 输出未完成或被截断；检查输出额度与服务状态。")
        output = data.get("output")
        if not isinstance(output, list):
            raise ExpansionError("Responses 响应缺少 output。")
        parts = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            contents = item.get("content", [])
            if not isinstance(contents, list):
                raise ExpansionError("Responses 消息 content 格式无效。")
            for part in contents:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "refusal":
                    raise ExpansionError("模型拒绝了本次扩写请求。")
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    parts.append(part["text"])
        content = "\n".join(parts)
    usage = data.get("usage", {})
    # Return token counts only; never pass through arbitrary server metadata.
    usage = {k: v for k, v in usage.items() if k in (
        "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
             and isinstance(v, int)} if isinstance(usage, dict) else {}
    return clean_text(content, allow_json=allow_json), usage

# 0.3.5 Samuel-Enhancer 统一命名

全部 9 个节点的显示名采用 Samuel-Enhancer 前缀，分类统一到 Samuel-Enhancer/任务、配置、文本。注册 ID 与 Python 类采用 SamuelEnhancer 前缀，配置端口采用 SAMUEL_ENHANCER 前缀，前端扩展、持久属性和预设接口同步更新。

| 注册 ID | 显示名称 |
|---|---|
| SamuelEnhancerGeneration | Samuel-Enhancer · 文本创作 |
| SamuelEnhancerReverse | Samuel-Enhancer · 参考图反推 |
| SamuelEnhancerEdit | Samuel-Enhancer · 图片编辑 |
| SamuelEnhancerService | Samuel-Enhancer · LLM 服务配置 |
| SamuelEnhancerTemplate | Samuel-Enhancer · 模板预设编辑器 |
| SamuelEnhancerConfig | Samuel-Enhancer · 任务配置 |
| SamuelEnhancerTextInput | Samuel-Enhancer · 文本输入 |
| SamuelEnhancerPreview | Samuel-Enhancer · 文本预览 |
| SamuelEnhancerPromptEditor | Samuel-Enhancer · 提示词编辑与预览 |

## 旧工作流

浏览器加载 0.3.x 工作流时，在查找缺失节点前迁移注册 ID、子图端口及链接类型、原稿预览和模板手稿属性。用户文本、服务参数、模板正文、手动编辑文本、节点位置和连接关系保留。旧的自定义节点标题保留说明文字并加上统一前缀，原生配置子图标题也同步更新。

迁移后保存工作流即可持久化新名称。不注册旧节点别名，节点搜索中只出现新名称。旧标识只存在于导入兼容映射及对应测试夹具中，不作为当前节点标识展示。

直接提交旧 API 格式 prompt 的调用方须更新 class_type；建议在浏览器打开迁移后重新导出 API 工作流。0.1/0.2 的旧单体节点不在本次兼容范围内，需换用新示例。

## 安装与配置

安装目录继续使用 Comfyui-prompt-enhancer，覆盖安装后重启后端并强制刷新网页，搜索 Samuel-Enhancer。示例中的 7 份工作流已更新。

本地默认密钥环境变量改为 SAMUEL_ENHANCER_API_KEY；工作流中显式填写的 api_key_env 保留。若曾依赖旧默认变量，请改为新变量或显式指定已有变量。官方 OPENAI_API_KEY 保持不变。

两份生产模板与推理流程保持原有行为。本轮没有调用远端 LLM。旧品牌的原始素材与早期命名记录留在工作区归档，不纳入本版安装包的当前说明。

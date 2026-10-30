import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const find = (node, name) => node.widgets?.find((widget) => widget.name === name);
const dirty = (node) => {
    node.setDirtyCanvas(true, true);
    node.graph?.change?.();
};
function readOnly(node, name, value = "") {
    const widget = ComfyWidgets.STRING(node, name, ["STRING", { multiline: true }], app).widget;
    widget.value = value;
    widget.inputEl.readOnly = true;
    widget.inputEl.style.opacity = "1";
    widget.options = { ...widget.options, serialize: false };
    return widget;
}

const labels = {
    task_mode: "任务模式", length: "篇幅", quality_mode: "生成方式",
    language: "输出语言", output_policy: "输出优先级", refresh_id: "重新扩写编号（非 seed）",
    template_text: "完整模板正文", task_rules: "任务适配规则（可编辑）",
    edited_text: "最终提示词（手动编辑）", addition: "追加补充（不自动消除冲突）",
    mode: "文本使用方式", text: "用户文本", preset: "模板预设",
};

const presetNames = { generation: "生图／反推", editing: "图片编辑" };
const snapshotTemplate = (node) => ({
    text: find(node, "template_text").value,
    task_rules: find(node, "task_rules").value,
});
function templateState(node) {
    node.properties ??= {};
    let state = node.properties.samuelEnhancerTemplateState;
    if (!state || !Object.hasOwn(presetNames, state.active) || !state.drafts || typeof state.drafts !== "object") {
        state = { active: find(node, "preset").value, drafts: {} };
        node.properties.samuelEnhancerTemplateState = state;
    }
    return state;
}
function saveTemplateDraft(node) {
    const state = templateState(node);
    state.drafts[state.active] = snapshotTemplate(node);
    return state;
}
function templateStatus(node, message) {
    if (node.samuelEnhancerPresetStatus) node.samuelEnhancerPresetStatus.value = message;
    node.setDirtyCanvas(true, true);
}
async function switchTemplate(node, target, reset = false) {
    if (!Object.hasOwn(presetNames, target)) return;
    const state = saveTemplateDraft(node);
    const sequence = node.samuelEnhancerPresetSequence = (node.samuelEnhancerPresetSequence ?? 0) + 1;
    // Keep the visible preset paired with its actual text while a request is pending.
    // A failed request must never leave an editing label attached to generation rules.
    find(node, "preset").value = state.active;
    templateStatus(node, `正在载入：${presetNames[target]}…`);
    try {
        let draft = reset ? null : state.drafts[target];
        if (!draft || typeof draft.text !== "string" || typeof draft.task_rules !== "string") {
            const response = await api.fetchApi(`/samuel_enhancer/presets/${encodeURIComponent(target)}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const preset = await response.json();
            if (preset.preset !== target || typeof preset.text !== "string" || typeof preset.task_rules !== "string") {
                throw new Error("无效模板数据");
            }
            draft = { text: preset.text, task_rules: preset.task_rules };
        }
        if (sequence !== node.samuelEnhancerPresetSequence) return;
        // Preserve edits made while the asynchronous preset request was in flight.
        saveTemplateDraft(node);
        find(node, "template_text").value = draft.text;
        find(node, "task_rules").value = draft.task_rules;
        find(node, "preset").value = target;
        state.active = target;
        state.drafts[target] = { ...draft };
        node.properties.samuelEnhancerLoadedPreset = target;
        templateStatus(node, `当前：${presetNames[target]}；切换时保留各自手稿`);
        dirty(node);
    } catch (error) {
        if (sequence !== node.samuelEnhancerPresetSequence) return;
        find(node, "preset").value = state.active;
        templateStatus(node, `载入失败，已保留${presetNames[state.active]}：${String(error)}`);
        app.extensionManager?.toast?.add?.({ severity: "error", summary: "模板载入失败", detail: String(error) });
        console.error("Samuel-Enhancer preset loading failed", error);
    }
}

app.registerExtension({
    name: "SamuelEnhancer.Editors",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!nodeData.name.startsWith("SamuelEnhancer")) return;
        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            for (const widget of this.widgets ?? []) {
                if (labels[widget.name]) {
                    widget.label = labels[widget.name];
                    if (widget.inputEl) widget.inputEl.placeholder = labels[widget.name];
                }
            }
            const portLabels = { config: "任务配置", user_text: "用户文本", must_keep: "保持项（可选）", image: "参考图片", source: "生成原稿", addition: "追加文本（可选）" };
            for (const input of this.inputs ?? []) if (portLabels[input.name]) input.label = portLabels[input.name];
            if (nodeData.name === "SamuelEnhancerTemplate") {
                const node = this;
                templateState(node);
                const selection = find(node, "preset");
                const originalChanged = selection.callback;
                selection.callback = function (value) {
                    originalChanged?.apply(this, arguments);
                    return switchTemplate(node, value ?? selection.value);
                };
                this.samuelEnhancerPresetStatus = this.addWidget("text", "预设状态", "切换预设自动载入，并保留各自手稿", () => {}, { serialize: false });
                this.samuelEnhancerPresetStatus.disabled = true;
                this.addWidget("button", "恢复当前预设默认内容（覆盖当前手稿）", null,
                    () => switchTemplate(node, templateState(node).active, true), { serialize: false });
                this.setSize([620, 800]);
            }
            if (nodeData.name === "SamuelEnhancerTextInput") this.setSize([440, 260]);
            if (nodeData.name === "SamuelEnhancerPromptEditor") {
                this.properties ??= {};
                this.samuelEnhancerSource = readOnly(this, "生成原稿（只读）", this.properties.samuelEnhancerSource ?? "");
                // Keep generated DOM widgets after backend widgets: moving a nonserialized
                // preview between them makes some frontends restore values to the wrong field.
                this.addWidget("button", "载入原稿到编辑框／恢复原稿", null, () => {
                    const source = this.samuelEnhancerSource.value;
                    if (!source) return;
                    find(this, "edited_text").value = source;
                    find(this, "mode").value = "完整编辑";
                    dirty(this);
                }, { serialize: false });
                this.setSize([620, 680]);
            }
            return result;
        };
        if (nodeData.name === "SamuelEnhancerTemplate") {
            const originalConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (data) {
                const result = originalConfigure?.apply(this, arguments);
                this.samuelEnhancerPresetSequence = (this.samuelEnhancerPresetSequence ?? 0) + 1;
                const named = data?.widgets_values_named;
                const values = data?.widgets_values;
                for (const [index, name] of ["preset", "template_text", "task_rules"].entries()) {
                    const value = named?.[name] ?? values?.[index];
                    if (typeof value === "string" && (name !== "preset" || Object.hasOwn(presetNames, value))) find(this, name).value = value;
                }
                const state = templateState(this);
                state.active = find(this, "preset").value;
                saveTemplateDraft(this);
                templateStatus(this, `当前：${presetNames[state.active]}；切换时保留各自手稿`);
                return result;
            };
            const originalSerialize = nodeType.prototype.onSerialize;
            nodeType.prototype.onSerialize = function (data) {
                const result = originalSerialize?.apply(this, arguments);
                const state = saveTemplateDraft(this);
                data.properties = { ...data.properties, samuelEnhancerTemplateState: JSON.parse(JSON.stringify(state)) };
                return result;
            };
            const originalRemoved = nodeType.prototype.onRemoved;
            nodeType.prototype.onRemoved = function () {
                this.samuelEnhancerPresetSequence = (this.samuelEnhancerPresetSequence ?? 0) + 1;
                return originalRemoved?.apply(this, arguments);
            };
        }
        if (nodeData.name !== "SamuelEnhancerPromptEditor") return;
        const originalExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            originalExecuted?.apply(this, arguments);
            const source = (message?.source ?? []).join("\n");
            this.properties ??= {};
            this.properties.samuelEnhancerSource = source;
            if (this.samuelEnhancerSource) this.samuelEnhancerSource.value = source;
            // Never replace edited_text on execution. Explicit button action is required.
            this.setDirtyCanvas(true, true);
        };
        const originalConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (data) {
            const result = originalConfigure?.apply(this, arguments);
            // Named restoration also tolerates optional ports/promoted widgets changing
            // the frontend's positional widget migration on a save/reload round-trip.
            const named = data?.widgets_values_named;
            const values = data?.widgets_values;
            const mode = named?.mode ?? values?.[0];
            const edited = named?.edited_text ?? values?.[1];
            if (["直接使用", "完整编辑", "追加补充"].includes(mode)) find(this, "mode").value = mode;
            if (typeof edited === "string") find(this, "edited_text").value = edited;
            if (this.samuelEnhancerSource) this.samuelEnhancerSource.value = this.properties?.samuelEnhancerSource ?? "";
            return result;
        };
    },
});

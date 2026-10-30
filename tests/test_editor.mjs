import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../web/editor.js", import.meta.url), "utf8").replace(/^import .*;\r?\n/gm, "");
let extension;
let requestCount = 0;
let failLoad = false;
let deferredLoad = null;
const app = { registerExtension(value) { extension = value; }, extensionManager: { toast: { add() {} } } };
const api = { async fetchApi(url) {
    requestCount++;
    assert.ok(["/samuel_enhancer/presets/editing", "/samuel_enhancer/presets/generation"].includes(url));
    const gate = deferredLoad;
    deferredLoad = null;
    if (gate) await gate;
    const preset = url.endsWith("editing") ? "editing" : "generation";
    return { ok: !failLoad, status: 500, async json() { return {
        preset, text: preset === "editing" ? "编辑模板" : "生图模板", task_rules: "适配规则"
    }; } };
} };
const ComfyWidgets = { STRING(node, name) {
    const widget = { name, inputEl: { style: {} }, options: {}, value: "" };
    node.widgets.push(widget);
    return { widget };
} };
vm.runInNewContext(source, { app, api, ComfyWidgets, console: { error() {} } });
const widget = (node, name) => node.widgets.find((w) => w.name === name);
class Base {
    constructor() { this.widgets = []; this.properties = {}; this.size = [100, 100]; this.graph = { change() {} }; }
    addWidget(type, name, value, callback, options) { const w = { type, name, value, callback, options }; this.widgets.push(w); return w; }
    setSize(size) { this.size = size; }
    setDirtyCanvas() { this.dirty = true; }
}

class Editor extends Base {}
await extension.beforeRegisterNodeDef(Editor, { name: "SamuelEnhancerPromptEditor" });
const editor = new Editor();
for (const [name, value] of [["mode", "直接使用"], ["edited_text", ""], ["addition", ""]]) editor.addWidget("text", name, value);
editor.onNodeCreated();
editor.onExecuted({ source: ["第一稿"], text: ["第一稿"] });
assert.equal(widget(editor, "edited_text").value, "");
assert.equal(editor.samuelEnhancerSource.value, "第一稿");
assert.equal(editor.samuelEnhancerSource.inputEl.readOnly, true);
assert.equal(editor.samuelEnhancerSource.options.serialize, false);
widget(editor, "载入原稿到编辑框／恢复原稿").callback();
assert.equal(widget(editor, "edited_text").value, "第一稿");
assert.equal(widget(editor, "mode").value, "完整编辑");
widget(editor, "edited_text").value = "手动版本";
editor.onExecuted({ source: ["第二稿"], text: ["手动版本"] });
assert.equal(widget(editor, "edited_text").value, "手动版本");
assert.equal(editor.samuelEnhancerSource.value, "第二稿");
const savedProperties = JSON.parse(JSON.stringify(editor.properties));
editor.properties = savedProperties;
editor.samuelEnhancerSource.value = "";
editor.onConfigure();
assert.equal(editor.samuelEnhancerSource.value, "第二稿");
widget(editor, "mode").value = "错误迁移值";
widget(editor, "edited_text").value = "被错位的原稿";
editor.onConfigure({ widgets_values_named: { mode: "完整编辑", edited_text: "保存的手稿" } });
assert.equal(widget(editor, "mode").value, "完整编辑");
assert.equal(widget(editor, "edited_text").value, "保存的手稿");

class Template extends Base {}
await extension.beforeRegisterNodeDef(Template, { name: "SamuelEnhancerTemplate" });
const template = new Template();
for (const [name, value] of [["preset", "generation"], ["template_text", "手改模板"], ["task_rules", "手改规则"]]) template.addWidget("text", name, value);
template.onNodeCreated();
async function select(node, name) {
    widget(node, "preset").value = name;
    await widget(node, "preset").callback(name);
}
await select(template, "editing");
assert.equal(widget(template, "template_text").value, "编辑模板");
assert.equal(widget(template, "task_rules").value, "适配规则");
widget(template, "template_text").value = "编辑手稿";
await select(template, "generation");
assert.equal(widget(template, "template_text").value, "手改模板");
assert.equal(widget(template, "task_rules").value, "手改规则");
await select(template, "editing");
assert.equal(widget(template, "template_text").value, "编辑手稿");
assert.equal(requestCount, 1, "Cached drafts should switch without another request");
await widget(template, "恢复当前预设默认内容（覆盖当前手稿）").callback();
assert.equal(widget(template, "template_text").value, "编辑模板");
failLoad = true;
widget(template, "template_text").value = "保留手改";
await widget(template, "恢复当前预设默认内容（覆盖当前手稿）").callback();
assert.equal(widget(template, "template_text").value, "保留手改");
assert.equal(widget(template, "preset").value, "editing");
assert.equal(requestCount, 3);
failLoad = false;

const saved = { properties: {} };
template.onSerialize(saved);
const restored = new Template();
for (const [name, value] of [["preset", "generation"], ["template_text", "默认"], ["task_rules", "默认"]]) restored.addWidget("text", name, value);
restored.onNodeCreated();
restored.properties = JSON.parse(JSON.stringify(saved.properties));
restored.onConfigure({ widgets_values_named: { preset: "editing", template_text: "保留手改", task_rules: "适配规则" } });
await select(restored, "generation");
assert.equal(widget(restored, "template_text").value, "手改模板");
await select(restored, "editing");
assert.equal(widget(restored, "template_text").value, "保留手改");

function newTemplate() {
    const node = new Template();
    for (const [name, value] of [["preset", "generation"], ["template_text", "原生图手稿"], ["task_rules", "原规则"]]) node.addWidget("text", name, value);
    node.onNodeCreated();
    return node;
}
const failed = newTemplate();
failLoad = true;
await select(failed, "editing");
assert.equal(widget(failed, "preset").value, "generation");
assert.equal(widget(failed, "template_text").value, "原生图手稿");
failLoad = false;

const racing = newTemplate();
let release;
deferredLoad = new Promise(resolve => { release = resolve; });
const pending = select(racing, "editing");
assert.equal(widget(racing, "preset").value, "generation", "Pending loads must keep label/text aligned");
await select(racing, "generation");
release();
await pending;
assert.equal(widget(racing, "preset").value, "generation");
assert.equal(widget(racing, "template_text").value, "原生图手稿");

const concurrent = newTemplate();
deferredLoad = new Promise(resolve => { release = resolve; });
const switching = select(concurrent, "editing");
widget(concurrent, "template_text").value = "请求期间的新手改";
release();
await switching;
await select(concurrent, "generation");
assert.equal(widget(concurrent, "template_text").value, "请求期间的新手改");
console.log("Editor/preset tests passed: automatic switching, per-preset drafts, reset, reload, failure and races.");

for (const name of ["SamuelEnhancerGeneration", "SamuelEnhancerReverse", "SamuelEnhancerEdit"]) {
    class Task extends Base {}
    await extension.beforeRegisterNodeDef(Task, { name });
    const task = new Task();
    task.inputs = [{ name: "user_text" }, { name: "must_keep" }];
    task.addWidget("combo", "length", "详细");
    task.onNodeCreated();
    assert.equal(widget(task, "length").label, "篇幅");
    assert.equal(task.inputs[0].label, "用户文本");
}
console.log("Renamed task node frontend hooks passed.");

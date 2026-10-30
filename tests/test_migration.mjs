import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

let extension;
const source = readFileSync(new URL("../web/migration.js", import.meta.url), "utf8").replace(/^import .*;\r?\n/gm, "");
vm.runInNewContext(source, { app: { registerExtension(value) { extension = value; } } });
assert.equal(extension.name, "SamuelEnhancer.WorkflowMigration");

const legacy = JSON.parse(readFileSync(new URL("fixtures/legacy-0.3.4-workflow.json", import.meta.url), "utf8"));
const original = structuredClone(legacy);
extension.beforeConfigureGraph(legacy);
const editor = legacy.nodes.find(n => n.type === "SamuelEnhancerPromptEditor");
assert.ok(editor);
assert.deepEqual(editor.widgets_values, ["完整编辑", "用户保存的手动正文"]);
assert.equal(editor.properties.samuelEnhancerSource, "保存的生成原稿");
assert.ok(!Object.hasOwn(editor.properties, "fisherMossSource"));
const subgraph = legacy.definitions.subgraphs[0];
assert.equal(subgraph.name, "Samuel-Enhancer · 生图配置");
const template = subgraph.nodes.find(n => n.type === "SamuelEnhancerTemplate");
assert.equal(template.properties.samuelEnhancerTemplateState.drafts.editing.text, "保存的编辑手稿");
assert.equal(template.widgets_values[1], "保存的生图手稿");
assert.equal(subgraph.outputs[0].type, "SAMUEL_ENHANCER_CONFIG");
assert.equal(subgraph.links[2].type, "SAMUEL_ENHANCER_CONFIG");
assert.equal(legacy.links[0][5], "SAMUEL_ENHANCER_CONFIG");
assert.equal(legacy.nodes.find(n => n.id === 3).type, "SamuelEnhancerGeneration");
assert.deepEqual(legacy.links.map(link => link.slice(0, 5)), original.links.map(link => link.slice(0, 5)));
assert.deepEqual(legacy.nodes.map(node => [node.id, node.pos]), original.nodes.map(node => [node.id, node.pos]));
for (const node of subgraph.nodes) {
    const previous = original.definitions.subgraphs[0].nodes.find(n => n.id === node.id);
    assert.deepEqual(node.widgets_values, previous.widgets_values);
    assert.equal(node.properties["Node name for S&R"], node.type);
}
const once = JSON.stringify(legacy);
extension.beforeConfigureGraph(legacy);
assert.equal(JSON.stringify(legacy), once, "Migration must be idempotent");

const allTypes = {
    FisherMossService: "SamuelEnhancerService", FisherMossTemplate: "SamuelEnhancerTemplate",
    FisherMossConfig: "SamuelEnhancerConfig", FisherMossTextInput: "SamuelEnhancerTextInput",
    FisherMossPreview: "SamuelEnhancerPreview", FisherMossPromptEditor: "SamuelEnhancerPromptEditor",
    "prompt-generation-production": "SamuelEnhancerGeneration", "prompt-reverse-production": "SamuelEnhancerReverse",
    "prompt-edit-production": "SamuelEnhancerEdit",
};
const all = { nodes: Object.keys(allTypes).map(type => ({ type, properties: {}, inputs: [], outputs: [] })) };
extension.beforeConfigureGraph(all);
assert.deepEqual(all.nodes.map(node => node.type), Object.values(allTypes));

const unrelated = { nodes: [{ type: "OtherPluginNode", title: "用户自己的标题", widgets_values: ["FISHER MOSS is user text"],
    properties: { fisherMossSource: "属于其他节点的数据" } }] };
const untouched = JSON.stringify(unrelated);
extension.beforeConfigureGraph(unrelated);
assert.equal(JSON.stringify(unrelated), untouched, "Do not rewrite user prompts or unrelated nodes");

const mixed = { nodes: [{ type: "SamuelEnhancerPromptEditor", properties: { fisherMossSource: "旧稿", samuelEnhancerSource: "新稿" } }] };
extension.beforeConfigureGraph(mixed);
assert.equal(mixed.nodes[0].properties.samuelEnhancerSource, "新稿");
assert.ok(!Object.hasOwn(mixed.nodes[0].properties, "fisherMossSource"));

for (const filename of ["text-create", "image-edit", "reference-describe"]) {
    const current = JSON.parse(readFileSync(new URL(`../examples/${filename}.json`, import.meta.url), "utf8"));
    const before = JSON.stringify(current);
    extension.beforeConfigureGraph(current);
    assert.equal(JSON.stringify(current), before);
}
console.log("Workflow migration passed: all nine IDs, native subgraph types, links, saved drafts, idempotence and unrelated data.");

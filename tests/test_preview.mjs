import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../web/preview.js", import.meta.url), "utf8").replace(/^import .*;\r?\n/gm, "");
let extension;
const app = { registerExtension(value) { extension = value; } };
const ComfyWidgets = { STRING() { return { widget: { inputEl: { style: {} }, options: {}, value: "" } }; } };
vm.runInNewContext(source, { app, ComfyWidgets });
class Preview {
    constructor() { this.size = [100, 100]; }
    setSize(size) { this.size = size; }
    setDirtyCanvas() { this.dirty = true; }
}
await extension.beforeRegisterNodeDef(Preview, { name: "SamuelEnhancerPreview" });
const preview = new Preview();
preview.onNodeCreated();
preview.onExecuted({ text: ["天宫", "云海"] });
assert.equal(preview.samuelEnhancerPreview.value, "天宫\n云海");
assert.equal(preview.samuelEnhancerPreview.inputEl.readOnly, true);
assert.equal(preview.samuelEnhancerPreview.options.serialize, false);
assert.equal(preview.dirty, true);
console.log("Preview hook contract passed (mock ComfyWidgets; not browser integration).");

import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

app.registerExtension({
    name: "SamuelEnhancer.TextPreview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SamuelEnhancerPreview") return;
        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            const widget = ComfyWidgets.STRING(this, "preview", ["STRING", { multiline: true }], app).widget;
            widget.inputEl.readOnly = true;
            widget.inputEl.style.opacity = "1";
            widget.options = { ...widget.options, serialize: false };
            this.samuelEnhancerPreview = widget;
            this.setSize([Math.max(this.size[0], 520), Math.max(this.size[1], 360)]);
            return result;
        };
        const originalExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            originalExecuted?.apply(this, arguments);
            if (this.samuelEnhancerPreview) {
                this.samuelEnhancerPreview.value = (message?.text ?? []).join("\n");
                this.setDirtyCanvas(true, true);
            }
        };
    },
});

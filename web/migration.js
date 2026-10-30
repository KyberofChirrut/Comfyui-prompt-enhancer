import { app } from "../../scripts/app.js";

// Import-only compatibility data. Old registrations are not exposed in the node menu.
const legacyNodes = {
    FisherMossService: "SamuelEnhancerService",
    FisherMossTemplate: "SamuelEnhancerTemplate",
    FisherMossConfig: "SamuelEnhancerConfig",
    "prompt-generation-production": "SamuelEnhancerGeneration",
    "prompt-reverse-production": "SamuelEnhancerReverse",
    "prompt-edit-production": "SamuelEnhancerEdit",
    FisherMossTextInput: "SamuelEnhancerTextInput",
    FisherMossPreview: "SamuelEnhancerPreview",
    FisherMossPromptEditor: "SamuelEnhancerPromptEditor",
};
const legacyPorts = {
    FISHER_MOSS_SERVICE: "SAMUEL_ENHANCER_SERVICE",
    FISHER_MOSS_TEMPLATE: "SAMUEL_ENHANCER_TEMPLATE",
    FISHER_MOSS_CONFIG: "SAMUEL_ENHANCER_CONFIG",
};
const legacyProperties = {
    fisherMossSource: "samuelEnhancerSource",
    fisherMossTemplateState: "samuelEnhancerTemplateState",
    fisherMossLoadedPreset: "samuelEnhancerLoadedPreset",
};
const taskTitles = {
    "prompt-generation-production": "Samuel-Enhancer · 文本创作",
    "prompt-reverse-production": "Samuel-Enhancer · 参考图反推",
    "prompt-edit-production": "Samuel-Enhancer · 图片编辑",
};
const mapped = (table, value) => typeof value === "string" && Object.hasOwn(table, value) ? table[value] : value;
function title(value) {
    if (typeof value !== "string") return value;
    return mapped(taskTitles, value).replace(/^FISHER MOSS(?=\s|$)/i, "Samuel-Enhancer");
}
function ports(values) {
    for (const port of values ?? []) port.type = mapped(legacyPorts, port.type);
}
function migrateGraph(graph, seen = new WeakSet()) {
    if (!graph || typeof graph !== "object" || seen.has(graph)) return;
    seen.add(graph);
    if (typeof graph.name === "string") graph.name = title(graph.name);
    ports(graph.inputs);
    ports(graph.outputs);
    for (const node of graph.nodes ?? []) {
        const originalType = node.type;
        node.type = mapped(legacyNodes, node.type);
        const managed = typeof node.type === "string" && node.type.startsWith("SamuelEnhancer");
        if (managed || originalType !== node.type) {
            if (typeof node.title === "string") {
                node.title = title(node.title);
                if (!node.title.startsWith("Samuel-Enhancer")) node.title = "Samuel-Enhancer · " + node.title;
            }
            const properties = node.properties;
            if (properties && typeof properties === "object") {
                const searchName = properties["Node name for S&R"];
                if (typeof searchName === "string") properties["Node name for S&R"] = mapped(legacyNodes, searchName);
                for (const [oldName, newName] of Object.entries(legacyProperties)) {
                    if (!Object.hasOwn(properties, oldName)) continue;
                    if (!Object.hasOwn(properties, newName)) properties[newName] = properties[oldName];
                    delete properties[oldName];
                }
            }
        } else if (typeof node.title === "string" && /^FISHER MOSS(?=\s|$)/i.test(node.title)) {
            // Native configuration subgraph instances use a UUID instead of a node class ID.
            node.title = title(node.title);
        }
        ports(node.inputs);
        ports(node.outputs);
        if (node.subgraph) migrateGraph(node.subgraph, seen);
    }
    for (const link of graph.links ?? []) {
        if (Array.isArray(link)) link[5] = mapped(legacyPorts, link[5]);
        else if (link && typeof link === "object") link.type = mapped(legacyPorts, link.type);
    }
    for (const group of graph.groups ?? []) if (typeof group.title === "string") group.title = title(group.title);
    for (const subgraph of graph.definitions?.subgraphs ?? []) migrateGraph(subgraph, seen);
    for (const subgraph of Object.values(graph.extra?.groupNodes ?? {})) migrateGraph(subgraph, seen);
}

app.registerExtension({
    name: "SamuelEnhancer.WorkflowMigration",
    beforeConfigureGraph(graph) {
        migrateGraph(graph);
    },
});

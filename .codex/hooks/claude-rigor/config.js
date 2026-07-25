"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.DEFAULT_CONFIG = void 0;
exports.mergeConfig = mergeConfig;
exports.loadConfig = loadConfig;
/**
 * User configuration.
 *
 * Optional file `<.claude>/claude-rigor.json`. Missing or malformed config
 * falls back to defaults, so the tool works zero-config. `mergeConfig` is pure
 * and validates each field defensively (untrusted JSON in -> typed config out).
 */
const node_fs_1 = require("node:fs");
const node_path_1 = require("node:path");
exports.DEFAULT_CONFIG = {
    speculation: { enabled: true, lookbackMessages: 5 },
    goal: { enabled: true, lookbackMessages: 20 },
};
function pickBool(value, fallback) {
    return typeof value === "boolean" ? value : fallback;
}
function pickNum(value, fallback) {
    return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}
function pickStrArr(value, fallback) {
    if (!Array.isArray(value))
        return fallback;
    const cleaned = value.filter((v) => typeof v === "string");
    return cleaned.length > 0 ? cleaned : fallback;
}
/** Merge untrusted override data onto a base config. Pure. */
function mergeConfig(base, override) {
    if (!override || typeof override !== "object")
        return base;
    const o = override;
    return {
        speculation: {
            enabled: pickBool(o.speculation?.enabled, base.speculation.enabled),
            phrases: pickStrArr(o.speculation?.phrases, base.speculation.phrases),
            lookbackMessages: pickNum(o.speculation?.lookbackMessages, base.speculation.lookbackMessages),
        },
        goal: {
            enabled: pickBool(o.goal?.enabled, base.goal.enabled),
            markers: pickStrArr(o.goal?.markers, base.goal.markers),
            lookbackMessages: pickNum(o.goal?.lookbackMessages, base.goal.lookbackMessages),
        },
    };
}
/** Load config from `<claudeDir>/claude-rigor.json`, falling back to defaults. */
function loadConfig(claudeDir) {
    try {
        const path = (0, node_path_1.join)(claudeDir, "claude-rigor.json");
        if (!(0, node_fs_1.existsSync)(path))
            return exports.DEFAULT_CONFIG;
        const parsed = JSON.parse((0, node_fs_1.readFileSync)(path, "utf8"));
        return mergeConfig(exports.DEFAULT_CONFIG, parsed);
    }
    catch {
        return exports.DEFAULT_CONFIG;
    }
}

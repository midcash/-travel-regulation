"use strict";
/**
 * Settings installation logic.
 *
 * `mergeSettings` is pure: it takes the existing parsed `settings.json` and the
 * directory the hook scripts live in, and returns a NEW settings object with
 * the claude-rigor hooks added. It never removes or overwrites existing hooks,
 * and it is idempotent (re-running does not duplicate entries). All filesystem
 * work lives in cli.ts.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.nodeCommand = nodeCommand;
exports.buildGroups = buildGroups;
exports.mergeSettings = mergeSettings;
const PRETOOL_SCRIPT = "pretool-goal.js";
const STOP_SCRIPT = "stop-speculation.js";
/** Build a `node "..."` command with forward slashes (portable across OSes). */
function nodeCommand(scriptPath) {
    return `node "${scriptPath.replace(/\\/g, "/")}"`;
}
/** Build the two hook groups for a given install directory. */
function buildGroups(scriptDir) {
    const dir = scriptDir.replace(/\\/g, "/").replace(/\/+$/, "");
    return {
        preTool: {
            matcher: "Write|Edit|MultiEdit",
            hooks: [{ type: "command", command: nodeCommand(`${dir}/hooks/${PRETOOL_SCRIPT}`) }],
        },
        stop: {
            hooks: [{ type: "command", command: nodeCommand(`${dir}/hooks/${STOP_SCRIPT}`) }],
        },
    };
}
function hasScript(groups, scriptName) {
    return groups.some((g) => g.hooks?.some((h) => h.command.includes(scriptName)));
}
/**
 * Return a new settings object with claude-rigor hooks merged in.
 * Existing hooks are preserved; re-running is a no-op (idempotent).
 */
function mergeSettings(existing, scriptDir) {
    const { preTool, stop } = buildGroups(scriptDir);
    const hooks = { ...(existing.hooks ?? {}) };
    const preToolGroups = [...(hooks.PreToolUse ?? [])];
    if (!hasScript(preToolGroups, PRETOOL_SCRIPT))
        preToolGroups.push(preTool);
    const stopGroups = [...(hooks.Stop ?? [])];
    if (!hasScript(stopGroups, STOP_SCRIPT))
        stopGroups.push(stop);
    return {
        ...existing,
        hooks: { ...hooks, PreToolUse: preToolGroups, Stop: stopGroups },
    };
}

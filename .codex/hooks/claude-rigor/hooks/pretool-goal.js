#!/usr/bin/env node
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
/**
 * PreToolUse hook (matcher Write|Edit|MultiEdit): denies a destructive edit
 * unless a goal was declared in recent assistant output. Returns a JSON deny
 * decision per the Claude Code hooks protocol.
 *
 * Fails open: any error or missing transcript exits 0 (never blocks on a bug).
 */
const node_path_1 = require("node:path");
const node_fs_1 = require("node:fs");
const stdin_1 = require("../stdin");
const transcript_1 = require("../transcript");
const goal_declaration_1 = require("../detectors/goal-declaration");
const config_1 = require("../config");
async function main() {
    const raw = await (0, stdin_1.readStdin)();
    let input;
    try {
        input = JSON.parse(raw);
    }
    catch {
        process.exit(0);
    }
    const transcriptPath = input.transcript_path;
    if (!transcriptPath || !(0, node_fs_1.existsSync)(transcriptPath))
        process.exit(0);
    const claudeDir = (0, node_path_1.resolve)(__dirname, "..", "..", "..");
    const cfg = (0, config_1.loadConfig)(claudeDir);
    if (!cfg.goal.enabled)
        process.exit(0);
    const markers = cfg.goal.markers ?? goal_declaration_1.DEFAULT_GOAL_MARKERS;
    const combined = (0, transcript_1.lastAssistantTexts)((0, transcript_1.readTranscript)(transcriptPath), cfg.goal.lookbackMessages).join("\n");
    if ((0, goal_declaration_1.hasGoalDeclaration)(combined, markers))
        process.exit(0);
    const decision = {
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: 'claude-rigor: declare a goal before editing. Add a line like "Goal: <what this change achieves>" (or "ゴール:") to your message, then retry the edit.',
        },
    };
    process.stdout.write(JSON.stringify(decision));
    process.exit(0);
}
main().catch(() => process.exit(0));

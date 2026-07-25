#!/usr/bin/env node
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
/**
 * Stop hook: blocks the agent from ending its turn while its recent output
 * contains speculative / unverified language. Exits 2 with guidance so the
 * agent continues and replaces the claim with evidence.
 *
 * Fails open: any error or missing transcript exits 0 (never blocks on a bug).
 */
const node_path_1 = require("node:path");
const node_fs_1 = require("node:fs");
const stdin_1 = require("../stdin");
const transcript_1 = require("../transcript");
const speculation_1 = require("../detectors/speculation");
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
    if (!cfg.speculation.enabled)
        process.exit(0);
    const rules = cfg.speculation.phrases
        ? (0, speculation_1.compilePhrases)(cfg.speculation.phrases)
        : speculation_1.DEFAULT_SPECULATION_RULES;
    const combined = (0, transcript_1.lastAssistantTexts)((0, transcript_1.readTranscript)(transcriptPath), cfg.speculation.lookbackMessages).join("\n");
    if (!combined)
        process.exit(0);
    const matches = (0, speculation_1.detectSpeculation)(combined, rules);
    if (matches.length === 0)
        process.exit(0);
    const reasons = [...new Set(matches.map((m) => m.reason))];
    process.stderr.write("[claude-rigor] Speculative language detected before stopping:\n");
    for (const r of reasons)
        process.stderr.write(`  - ${r}\n`);
    process.stderr.write("\nReplace assertion with evidence:\n");
    process.stderr.write("  1. Run a command or test that confirms the claim.\n");
    process.stderr.write('  2. Rewrite "should work"/"probably" as "confirmed: <observed output>".\n');
    process.exit(2);
}
main().catch(() => process.exit(0));

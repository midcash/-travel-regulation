#!/usr/bin/env node
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
/**
 * claude-rigor CLI.
 *
 *   claude-rigor init            install into ./.claude
 *   claude-rigor init --global   install into ~/.claude
 *   claude-rigor init --dir DIR  install into DIR (a .claude directory)
 *
 * Installation copies the compiled hook scripts into
 * `<.claude>/hooks/claude-rigor/` and merges the hook entries into
 * `<.claude>/settings.json` without overwriting existing settings.
 */
const node_fs_1 = require("node:fs");
const node_os_1 = require("node:os");
const node_path_1 = require("node:path");
const install_1 = require("./install");
function out(message) {
    process.stdout.write(message + "\n");
}
function parseArgs(argv) {
    const args = argv.slice(2);
    const command = args[0] ?? "help";
    let global = false;
    let dir;
    for (let i = 1; i < args.length; i++) {
        if (args[i] === "--global" || args[i] === "-g")
            global = true;
        else if (args[i] === "--dir")
            dir = args[++i];
    }
    return { command, global, dir };
}
function targetClaudeDir(opts) {
    if (opts.dir)
        return (0, node_path_1.resolve)(opts.dir);
    if (opts.global)
        return (0, node_path_1.join)((0, node_os_1.homedir)(), ".claude");
    return (0, node_path_1.resolve)(".claude");
}
function init(opts) {
    const claudeDir = targetClaudeDir(opts);
    const installDir = (0, node_path_1.join)(claudeDir, "hooks", "claude-rigor");
    const distDir = __dirname; // the compiled dist/ folder
    (0, node_fs_1.mkdirSync)(installDir, { recursive: true });
    (0, node_fs_1.cpSync)(distDir, installDir, { recursive: true });
    const settingsPath = (0, node_path_1.join)(claudeDir, "settings.json");
    let existing = {};
    if ((0, node_fs_1.existsSync)(settingsPath)) {
        try {
            existing = JSON.parse((0, node_fs_1.readFileSync)(settingsPath, "utf8"));
        }
        catch {
            existing = {};
        }
    }
    const merged = (0, install_1.mergeSettings)(existing, installDir);
    (0, node_fs_1.mkdirSync)((0, node_path_1.dirname)(settingsPath), { recursive: true });
    (0, node_fs_1.writeFileSync)(settingsPath, JSON.stringify(merged, null, 2) + "\n");
    out(`claude-rigor installed:`);
    out(`  hooks  -> ${installDir}`);
    out(`  config -> ${settingsPath}`);
    out(`Restart Claude Code (or start a new session) to load the hooks.`);
}
function help() {
    out("claude-rigor — evidence-over-assertion guardrails for Claude Code");
    out("");
    out("Usage:");
    out("  claude-rigor init             install into ./.claude");
    out("  claude-rigor init --global    install into ~/.claude");
    out("  claude-rigor init --dir DIR   install into a specific .claude dir");
}
function run() {
    const opts = parseArgs(process.argv);
    switch (opts.command) {
        case "init":
            init(opts);
            break;
        default:
            help();
    }
}
run();

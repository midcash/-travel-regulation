"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.extractAssistantText = extractAssistantText;
exports.lastAssistantTexts = lastAssistantTexts;
exports.readTranscript = readTranscript;
/**
 * Claude Code transcript parsing.
 *
 * A transcript is a JSONL file: one JSON object per line. Assistant turns have
 * the shape `{ message: { role: "assistant", content: ... } }` where `content`
 * is either a string or an array of blocks; text blocks are `{ type: "text",
 * text: string }`. Anything that does not parse is skipped.
 *
 * `extractAssistantText` and `lastAssistantTexts` are pure (testable);
 * `readTranscript` is the only I/O boundary.
 */
const node_fs_1 = require("node:fs");
function blockToText(block) {
    if (typeof block === "string")
        return block;
    if (block && typeof block === "object") {
        const b = block;
        if (b.type === "text" && typeof b.text === "string")
            return b.text;
    }
    return "";
}
/** Extract the assistant text from a single JSONL line, or "" if not applicable. */
function extractAssistantText(line) {
    let parsed;
    try {
        parsed = JSON.parse(line);
    }
    catch {
        return "";
    }
    const entry = parsed;
    if (entry?.message?.role !== "assistant")
        return "";
    const content = entry.message.content;
    if (typeof content === "string")
        return content;
    if (Array.isArray(content)) {
        return content.map(blockToText).filter(Boolean).join(" ");
    }
    return "";
}
/** Return the text of the last `count` assistant messages from JSONL content. */
function lastAssistantTexts(jsonl, count = 5) {
    if (!jsonl)
        return [];
    const lines = jsonl.trim().split(/\r?\n/);
    const texts = [];
    for (const line of lines) {
        const t = extractAssistantText(line);
        if (t)
            texts.push(t);
    }
    return texts.slice(-count);
}
/** Read a transcript file from disk (I/O boundary). */
function readTranscript(path) {
    return (0, node_fs_1.readFileSync)(path, "utf8");
}

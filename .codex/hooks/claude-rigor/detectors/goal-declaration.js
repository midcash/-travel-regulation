"use strict";
/**
 * Goal-declaration detector.
 *
 * Decides whether recent assistant text contains an explicit statement of
 * intent before a destructive edit. The markers are configurable; defaults
 * cover English ("Goal:") and Japanese ("ゴール:").
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.DEFAULT_GOAL_MARKERS = void 0;
exports.hasGoalDeclaration = hasGoalDeclaration;
/** Default markers that count as a declared goal. */
exports.DEFAULT_GOAL_MARKERS = ["Goal:", "ゴール:", "ゴール：", "## Goal", "## ゴール"];
/**
 * Returns true if any marker appears in the text (case-insensitive).
 * Empty text returns false.
 */
function hasGoalDeclaration(text, markers = exports.DEFAULT_GOAL_MARKERS) {
    if (!text)
        return false;
    const haystack = text.toLowerCase();
    return markers.some((m) => haystack.includes(m.toLowerCase()));
}

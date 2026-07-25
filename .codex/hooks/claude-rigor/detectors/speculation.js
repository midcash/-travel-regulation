"use strict";
/**
 * Speculation detector.
 *
 * Pure functions that find speculative / unverified language in a block of
 * assistant text. Code spans (inline `...` and fenced ```...```) are stripped
 * before matching so that *discussing* a banned word in documentation or code
 * does not trigger a false positive.
 *
 * The rule list is data, not control flow, so callers (and user config) can
 * replace or extend it.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.DEFAULT_SPECULATION_RULES = void 0;
exports.stripCodeSpans = stripCodeSpans;
exports.detectSpeculation = detectSpeculation;
exports.compilePhrases = compilePhrases;
/** Default rules: common English and Japanese speculative phrasing. */
exports.DEFAULT_SPECULATION_RULES = [
    { pattern: /\bprobably\b/gi, reason: "probably (speculation)" },
    { pattern: /\bshould\s+work\b/gi, reason: "should work (unverified claim)" },
    { pattern: /\bshould\s+be\s+fine\b/gi, reason: "should be fine (unverified claim)" },
    { pattern: /\bshould\s+be\s+good\b/gi, reason: "should be good (unverified claim)" },
    { pattern: /\bmight\s+work\b/gi, reason: "might work (speculation)" },
    { pattern: /\bI\s+think\b/gi, reason: "I think (speculation)" },
    { pattern: /\bI\s+believe\b/gi, reason: "I believe (speculation)" },
    { pattern: /\bI\s+assume\b/gi, reason: "I assume (speculation)" },
    { pattern: /\b(?:most\s+likely|presumably)\b/gi, reason: "most likely/presumably (speculation)" },
    // Japanese
    { pattern: /たぶん/g, reason: "たぶん (speculation)" },
    { pattern: /(?:^|[^「『])多分[、,]/g, reason: "多分 (speculation)" },
    { pattern: /おそらく/g, reason: "おそらく (speculation)" },
    { pattern: /だと思(?:う|います?)/g, reason: "だと思う (speculation)" },
    { pattern: /かもしれない/g, reason: "かもしれない (speculation)" },
    { pattern: /可能性が高(?:い|そう)/g, reason: "可能性が高い (speculation)" },
    { pattern: /はず(?:です|だ|だよ|でしょう)/g, reason: "はず (speculation)" },
];
/** Remove fenced and inline code spans so their contents are not matched. */
function stripCodeSpans(text) {
    return text
        .replace(/```[\s\S]*?```/g, " ")
        .replace(/`[^`\n]*`/g, " ");
}
function ensureGlobal(re) {
    return re.flags.includes("g") ? re : new RegExp(re.source, re.flags + "g");
}
/**
 * Find every speculative phrase in `text`.
 * Returns matches sorted by position. Empty input yields an empty list.
 */
function detectSpeculation(text, rules = exports.DEFAULT_SPECULATION_RULES) {
    if (!text)
        return [];
    const haystack = stripCodeSpans(text);
    const matches = [];
    for (const rule of rules) {
        const re = ensureGlobal(rule.pattern);
        re.lastIndex = 0;
        let m;
        while ((m = re.exec(haystack)) !== null) {
            matches.push({ phrase: m[0].trim(), reason: rule.reason, index: m.index });
            if (m.index === re.lastIndex)
                re.lastIndex++; // guard against zero-width matches
        }
    }
    return matches.sort((a, b) => a.index - b.index);
}
/**
 * Compile plain string phrases (from user config) into rules.
 * ASCII phrases are matched on word boundaries; non-ASCII (e.g. Japanese)
 * are matched literally since `\b` is meaningless there.
 */
function compilePhrases(phrases, caseInsensitive = true) {
    return phrases.map((p) => {
        const escaped = p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const isAscii = /^[\x00-\x7F]+$/.test(p);
        const source = isAscii ? `\\b${escaped}\\b` : escaped;
        return { pattern: new RegExp(source, caseInsensitive ? "gi" : "g"), reason: `${p} (speculation)` };
    });
}

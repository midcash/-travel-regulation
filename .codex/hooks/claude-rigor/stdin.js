"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.readStdin = readStdin;
/** Read all of stdin as a string, with a safety timeout. I/O boundary. */
function readStdin(timeoutMs = 5000) {
    return new Promise((resolve) => {
        let buf = "";
        process.stdin.on("data", (chunk) => (buf += chunk));
        process.stdin.on("end", () => resolve(buf));
        setTimeout(() => resolve(buf), timeoutMs);
    });
}

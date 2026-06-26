import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const files = ["index.html", "app.js", "styles.css"].map((file) =>
  readFileSync(join(root, file), "utf8"),
);
const combined = files.join("\n");

const requiredText = [
  "Project 1 - Double-Entry Ledger Control Room",
  "Ledger Balanced",
  "Total Debits",
  "Total Credits",
  "Trial Balance",
  "Replay Settlement Demo",
];

const missing = requiredText.filter((text) => !combined.includes(text));
if (missing.length > 0) {
  console.error(`Missing required dashboard text: ${missing.join(", ")}`);
  process.exit(1);
}

if (combined.includes("market data") || combined.includes("stock chart")) {
  console.error("Dashboard text should stay scoped to ledger integrity, not market data.");
  process.exit(1);
}

console.log("Static dashboard checks passed.");

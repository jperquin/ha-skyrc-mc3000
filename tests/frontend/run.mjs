import { mkdirSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

mkdirSync(".test-artifacts", { recursive: true });
const directory = new URL("./", import.meta.url);
for (const name of readdirSync(directory).filter(name => name.endsWith(".mjs") && name !== "run.mjs").sort()) {
  console.log(`\nRunning ${name}`);
  const result = spawnSync(process.execPath, [fileURLToPath(new URL(name, directory))], { stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

// Build-time only (Node): reads the sample notes and their pre-generated one-pagers from the
// repo's samples/ folder. Run from web/, which is where npm workspaces run scripts.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { OnePager, Sample } from "./types";

export const SAMPLE_ORDER = ["dc-migration", "crm-rollout", "office-move", "vendor-transition"];

export function samplesDir(): string {
  return resolve(process.cwd(), "..", "samples");
}

export function loadSamples(dir = samplesDir()): Sample[] {
  return SAMPLE_ORDER.map((id) => {
    const read = (suffix: string) => readFileSync(resolve(dir, `${id}${suffix}`), "utf8");
    const labels = JSON.parse(read(".labels.json")) as { title: string };
    // Titles look like "Data center migration: raw meeting notes".
    const [name, format = ""] = labels.title.split(": ");
    return {
      id,
      name: name!,
      format: format.charAt(0).toUpperCase() + format.slice(1),
      notes: read(".txt"),
      onepager: JSON.parse(read(".onepager.json")) as OnePager,
    };
  });
}

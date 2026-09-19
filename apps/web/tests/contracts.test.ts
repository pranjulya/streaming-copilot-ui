import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { expect, test } from "vitest";

const root = fileURLToPath(new URL("../../../contracts/", import.meta.url));
const types = [
  "response.started",
  "message.delta",
  "usage.updated",
  "heartbeat",
  "message.completed",
  "response.completed",
  "response.cancelled",
  "response.failed",
  "response.snapshot",
];

test("the web toolchain accepts every frozen V1 fixture", () => {
  const ajv = new Ajv2020({ allErrors: true });
  addFormats(ajv);
  const validate = ajv.compile(
    JSON.parse(readFileSync(`${root}/stream-events.schema.json`, "utf8")),
  );
  const events = readdirSync(`${root}/examples`)
    .filter((name) => name.endsWith(".json"))
    .map((name) =>
      JSON.parse(readFileSync(`${root}/examples/${name}`, "utf8")),
    );
  expect(events.map((event) => event.type).sort()).toEqual(types.sort());
  for (const event of events) {
    expect(validate(event), JSON.stringify(validate.errors)).toBe(true);
    const wire = JSON.stringify(event) + "\n";
    expect(wire.split("\n")).toHaveLength(2);
    expect(JSON.parse(wire)).toEqual(event);
    if (["heartbeat", "response.snapshot"].includes(event.type)) {
      expect(event.sequence).toBe(event.data.last_sequence);
    }
  }
  const delta = events.find((event) => event.type === "message.delta");
  expect(delta.data.delta).toContain("👍");
  expect(Array.from("👍")).toHaveLength(1);
});

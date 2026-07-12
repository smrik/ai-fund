import { describe, expect, it } from "vitest";

// @ts-expect-error Vite resolves resource imports with the `?raw` query.
import globalCss from "@/styles/global.css?raw";

const DRIVER_GRID_SELECTOR = ".professional-model-driver-inputs > div";

type CssBlock = {
  header: string;
  body: string;
};

type DriverGridRule = {
  context: string;
  columns: string;
};

function stripComments(value: string): string {
  return value.replace(/\/\*[\s\S]*?\*\//g, "").trim();
}

function parseTopLevelBlocks(css: string): CssBlock[] {
  const blocks: CssBlock[] = [];
  let comment = false;
  let depth = 0;
  let escaped = false;
  let headerStart = 0;
  let bodyStart = 0;
  let quote: "\"" | "'" | null = null;

  for (let index = 0; index < css.length; index += 1) {
    const character = css[index];
    const next = css[index + 1];

    if (comment) {
      if (character === "*" && next === "/") {
        comment = false;
        index += 1;
      }
      continue;
    }

    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === quote) {
        quote = null;
      }
      continue;
    }

    if (character === "/" && next === "*") {
      comment = true;
      index += 1;
      continue;
    }

    if (character === "\"" || character === "'") {
      quote = character;
      continue;
    }

    if (character === "{") {
      if (depth === 0) {
        bodyStart = index + 1;
      }
      depth += 1;
      continue;
    }

    if (character !== "}") {
      continue;
    }

    depth -= 1;
    if (depth < 0) {
      throw new Error("CSS contains an unmatched closing brace.");
    }
    if (depth === 0) {
      blocks.push({
        header: stripComments(css.slice(headerStart, bodyStart - 1)),
        body: css.slice(bodyStart, index),
      });
      headerStart = index + 1;
    }
  }

  if (depth !== 0 || quote || comment) {
    throw new Error("CSS contains an unterminated block, string, or comment.");
  }

  return blocks;
}

function gridTemplateColumns(body: string): string {
  const declaration = body.match(/(?:^|;)\s*grid-template-columns\s*:\s*([^;]+)\s*;/);
  if (!declaration) {
    throw new Error("Driver-grid rule does not declare grid-template-columns.");
  }
  return declaration[1].trim();
}

function collectDriverGridRules(
  blocks: CssBlock[],
  context: string[] = [],
): DriverGridRule[] {
  return blocks.flatMap((block) => {
    if (block.header === DRIVER_GRID_SELECTOR) {
      return [{ context: context.join(" > ") || "top-level", columns: gridTemplateColumns(block.body) }];
    }
    if (block.header.startsWith("@")) {
      return collectDriverGridRules(parseTopLevelBlocks(block.body), [...context, block.header]);
    }
    return [];
  });
}

describe("Professional Model responsive CSS", () => {
  it("keeps driver inputs at 5/3/1 columns across base, tablet, and mobile scopes", () => {
    expect(collectDriverGridRules(parseTopLevelBlocks(globalCss))).toEqual([
      {
        context: "top-level",
        columns: "repeat(5, minmax(84px, 1fr))",
      },
      {
        context: "@media (max-width: 1080px)",
        columns: "repeat(3, minmax(84px, 1fr))",
      },
      {
        context: "@media (max-width: 760px)",
        columns: "1fr",
      },
    ]);
  });
});

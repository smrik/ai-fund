import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { IntrinsicValueBridgePanel } from "@/pages/ValuationPage";

afterEach(() => cleanup());

const basePayload = {
  iv_base: 228.89,
  iv_gordon: 161.4,
  iv_exit: 330.11,
  gordon_weight: null,
  exit_weight: null,
};

describe("IntrinsicValueBridgePanel", () => {
  it("marks the exit component unavailable for Gordon-only runs", () => {
    render(<IntrinsicValueBridgePanel payload={{ ...basePayload, method_used: "gordon_only" }} />);

    expect(screen.getByText("Gordon-only")).toBeInTheDocument();
    expect(screen.getByText("$161.40")).toBeInTheDocument();
    expect(screen.getByText("$228.89")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("Blend weights were not applied.")).toBeInTheDocument();
  });

  it("marks the Gordon component unavailable for Exit-only runs", () => {
    render(<IntrinsicValueBridgePanel payload={{ ...basePayload, method_used: "exit_only" }} />);

    expect(screen.getByText("Exit-only")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("$330.11")).toBeInTheDocument();
    expect(screen.getByText("Blend weights were not applied.")).toBeInTheDocument();
  });
});

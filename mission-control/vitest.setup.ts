import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(cleanup);

// next/link needs a mounted App Router; tests render it as a plain anchor.
vi.mock("next/link", async () => {
  const { createElement } = await import("react");
  return {
    default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; scroll?: boolean }) => {
      const anchorProps = { ...rest };
      delete anchorProps.scroll;
      return createElement("a", { href, ...anchorProps }, children);
    },
  };
});

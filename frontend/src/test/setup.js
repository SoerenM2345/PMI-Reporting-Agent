import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// `main.jsx` renders under StrictMode, so effects double-fire in development.
// Tests must never assume a single invocation; unmounting between them keeps
// one test's effects out of the next one's assertions.
afterEach(cleanup);

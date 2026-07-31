import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Composer from "./Composer";

/**
 * The composer's contract, in the orders a user actually works in.
 *
 * The reported bug was that attaching a file worked only if you had not typed
 * anything first. `handleFiles` dereferenced the live `FileList` *inside* a
 * state updater; React runs an updater eagerly only while the fiber is clean,
 * so after the first `setText` the read was deferred to render — by which time
 * `event.target.value = ""` had cleared the input, and with it `input.files`.
 *
 * **These tests do not reproduce that mechanism, and it is worth knowing why.**
 * I checked, by rendering the old shape and running the failing order against
 * it: it passes under jsdom. Setting `value = ""` clears `files` in a browser
 * but not in jsdom's implementation, so the deferred read still finds the file.
 * Reproducing it needs a real browser — Playwright, which is a different tool
 * for a different question.
 *
 * What these do guard is the contract: every order of typing and attaching ends
 * with both reaching `onSend`. The guard against the timing bug specifically is
 * the code shape — the array is materialised before any state call, so there is
 * no deferred read left to break.
 */
function file(name, contents = "x") {
  return new File([contents], name, { type: "application/octet-stream" });
}

function setup(props = {}) {
  const onSend = vi.fn().mockResolvedValue(undefined);
  const onStop = vi.fn();
  render(<Composer onSend={onSend} onStop={onStop} {...props} />);
  return { onSend, onStop, user: userEvent.setup() };
}

const attach = (files) =>
  screen.getByLabelText("Attach files").parentElement.querySelector(
    'input[type="file"]',
  );

describe("attachment order", () => {
  it("attach, then type, then send", async () => {
    const { onSend, user } = setup();
    await user.upload(attach(), file("tracker.xlsx"));
    await user.type(screen.getByLabelText("Message"), "here is this week");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(onSend).toHaveBeenCalledTimes(1);
    const [text, files] = onSend.mock.calls[0];
    expect(text).toBe("here is this week");
    expect(files.map((f) => f.name)).toEqual(["tracker.xlsx"]);
  });

  it("type, THEN attach, then send", async () => {
    // The order that failed in the browser. See the note above on why jsdom
    // cannot show it failing.
    const { onSend, user } = setup();
    await user.type(screen.getByLabelText("Message"), "here is this week");
    await user.upload(attach(), file("tracker.xlsx"));
    await user.click(screen.getByRole("button", { name: "Send" }));

    const [text, files] = onSend.mock.calls[0];
    expect(text).toBe("here is this week");
    expect(files.map((f) => f.name)).toEqual(["tracker.xlsx"]);
  });

  it("shows the staged file as soon as it is attached, after typing", async () => {
    const { user } = setup();
    await user.type(screen.getByLabelText("Message"), "hello");
    await user.upload(attach(), file("tracker.xlsx"));

    // The chip is the user's only confirmation that the file was taken.
    expect(await screen.findByText("tracker.xlsx")).toBeInTheDocument();
  });

  it("keeps several attachments across edits to the text", async () => {
    const { onSend, user } = setup();
    await user.type(screen.getByLabelText("Message"), "one");
    await user.upload(attach(), [file("a.xlsx"), file("b.pdf")]);
    await user.type(screen.getByLabelText("Message"), " two");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const [text, files] = onSend.mock.calls[0];
    expect(text).toBe("one two");
    expect(files.map((f) => f.name)).toEqual(["a.xlsx", "b.pdf"]);
  });

  it("removes one attachment and sends the rest", async () => {
    const { onSend, user } = setup();
    await user.upload(attach(), [file("a.xlsx"), file("b.pdf")]);
    await user.type(screen.getByLabelText("Message"), "text");
    await user.click(screen.getByLabelText("Remove a.xlsx"));
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(onSend.mock.calls[0][1].map((f) => f.name)).toEqual(["b.pdf"]);
  });

  it("sends files with no text", async () => {
    const { onSend, user } = setup();
    await user.upload(attach(), file("tracker.xlsx"));
    await user.click(screen.getByRole("button", { name: "Send" }));

    const [text, files] = onSend.mock.calls[0];
    expect(text).toBe("");
    expect(files).toHaveLength(1);
  });

  it("sends text with no files", async () => {
    const { onSend, user } = setup();
    await user.type(screen.getByLabelText("Message"), "what are the risks?");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(onSend.mock.calls[0]).toEqual(["what are the risks?", []]);
  });

  it("does not duplicate the same file attached twice", async () => {
    const { onSend, user } = setup();
    await user.upload(attach(), file("tracker.xlsx"));
    await user.upload(attach(), file("tracker.xlsx"));
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(onSend.mock.calls[0][1]).toHaveLength(1);
  });

  it("refuses an empty turn", async () => {
    const { onSend, user } = setup();
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();
    await user.click(send);
    expect(onSend).not.toHaveBeenCalled();
  });
});

describe("the draft survives a failure", () => {
  it("puts the text and files back when the turn throws", async () => {
    const onSend = vi.fn().mockRejectedValue(new Error("network"));
    render(<Composer onSend={onSend} onStop={vi.fn()} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Message"), "do not lose this");
    await user.upload(attach(), file("tracker.xlsx"));
    await user.click(screen.getByRole("button", { name: "Send" }));

    // The old composer cleared the box *before* handing over, so a failed turn
    // took the user's sentence with it.
    await waitFor(() =>
      expect(screen.getByLabelText("Message")).toHaveValue("do not lose this"),
    );
    expect(screen.getByText("tracker.xlsx")).toBeInTheDocument();
  });
});

describe("stop", () => {
  it("offers Stop instead of Send while a turn is running", async () => {
    const { onStop, user } = setup({ busy: true });

    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    await user.click(screen.getByLabelText("Stop generating"));
    expect(onStop).toHaveBeenCalled();
  });

  it("goes back to Send when the turn ends", () => {
    const { rerender } = render(
      <Composer onSend={vi.fn()} onStop={vi.fn()} busy />,
    );
    rerender(<Composer onSend={vi.fn()} onStop={vi.fn()} busy={false} />);

    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Stop generating")).toBeNull();
  });
});

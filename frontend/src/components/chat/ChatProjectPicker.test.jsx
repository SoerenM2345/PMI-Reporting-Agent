import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ChatProjectPicker from "./ChatProjectPicker";

const projects = [
  { project_id: "finance", name: "Finance Integration", icon: "📊" },
  { project_id: "people", name: "People Integration", icon: "🧠" },
];

describe("chat project picker", () => {
  it("moves the open chat to the selected project", async () => {
    const onChange = vi.fn();
    render(
      <ChatProjectPicker
        chat={{ chat_id: "chat-1", project_id: null }}
        projects={projects}
        onChange={onChange}
      />,
    );

    await userEvent.selectOptions(screen.getByLabelText("Chat project"), "finance");
    expect(onChange).toHaveBeenCalledWith("finance");
  });

  it("is hidden once the chat belongs to a project", () => {
    render(
      <ChatProjectPicker
        chat={{ chat_id: "chat-1", project_id: "finance" }}
        projects={projects}
      />,
    );

    expect(screen.queryByLabelText("Chat project")).not.toBeInTheDocument();
  });
});

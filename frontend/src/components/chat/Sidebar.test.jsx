import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Sidebar from "./Sidebar";

function transfer() {
  const values = {};
  return {
    dropEffect: "none",
    effectAllowed: "all",
    setData: (type, value) => {
      values[type] = value;
    },
    getData: (type) => values[type] || "",
  };
}

const projects = [
  { project_id: "finance", name: "Finance Integration", icon: "📊" },
  { project_id: "people", name: "People Integration", icon: "🧠" },
];

const chats = [
  { chat_id: "outside", title: "Weekly status", project_id: null },
  { chat_id: "inside", title: "People risks", project_id: "people" },
];

describe("sidebar chat filing", () => {
  it("moves an unfiled chat onto a project by drag and drop", () => {
    const onMoveChat = vi.fn();
    render(
      <Sidebar chats={chats} projects={projects} onMoveChat={onMoveChat} />,
    );
    const dataTransfer = transfer();

    fireEvent.dragStart(screen.getByLabelText("Chat: Weekly status"), {
      dataTransfer,
    });
    const target = screen.getByLabelText("Project drop area: Finance Integration");
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });

    expect(onMoveChat).toHaveBeenCalledWith("outside", "finance");
  });

  it("does not allow an assigned chat to move to another project", () => {
    const onMoveChat = vi.fn();
    render(
      <Sidebar chats={chats} projects={projects} onMoveChat={onMoveChat} />,
    );
    const dataTransfer = transfer();

    fireEvent.dragStart(screen.getByLabelText("Chat: People risks"), {
      dataTransfer,
    });
    expect(screen.getByLabelText("Chat: People risks"))
      .toHaveAttribute("draggable", "false");

    const target = screen.getByLabelText("Project drop area: Finance Integration");
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });

    expect(onMoveChat).not.toHaveBeenCalled();
  });
});

describe("sidebar navigation helpers", () => {
  it("shows six chats per list until Show more is clicked", () => {
    const manyChats = Array.from({ length: 8 }, (_, index) => ({
      chat_id: `chat-${index}`,
      title: `General chat ${index + 1}`,
      project_id: null,
    }));
    render(<Sidebar chats={manyChats} projects={projects} />);

    expect(screen.getByText("General chat 6")).toBeInTheDocument();
    expect(screen.queryByText("General chat 7")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show more (2)" }));
    expect(screen.getByText("General chat 7")).toBeInTheDocument();
    expect(screen.getByText("General chat 8")).toBeInTheDocument();
  });

  it("applies the same six-chat limit inside a project", () => {
    const projectChats = Array.from({ length: 7 }, (_, index) => ({
      chat_id: `project-chat-${index}`,
      title: `Project chat ${index + 1}`,
      project_id: "finance",
    }));
    render(<Sidebar chats={projectChats} projects={[projects[0]]} />);

    const project = screen.getByLabelText("Project drop area: Finance Integration");
    expect(within(project).queryByText("Project chat 7")).not.toBeInTheDocument();
    fireEvent.click(within(project).getByRole("button", { name: "Show more (1)" }));
    expect(within(project).getByText("Project chat 7")).toBeInTheDocument();
  });

  it("offers persistent pin actions for chats and projects", () => {
    const onPinChat = vi.fn();
    const onPinProject = vi.fn();
    render(
      <Sidebar
        chats={chats}
        projects={projects}
        onPinChat={onPinChat}
        onPinProject={onPinProject}
      />,
    );

    fireEvent.click(
      within(screen.getByLabelText("Chat: Weekly status")).getByLabelText("Pin chat"),
    );
    fireEvent.click(
      within(screen.getByLabelText("Project drop area: Finance Integration"))
        .getByLabelText("Pin project"),
    );

    expect(onPinChat).toHaveBeenCalledWith("outside", true);
    expect(onPinProject).toHaveBeenCalledWith("finance", true);
  });

  it("renders whole-app search results and opens the selected chat", () => {
    const onOpen = vi.fn();
    const onSearchQueryChange = vi.fn();
    render(
      <Sidebar
        chats={chats}
        projects={projects}
        searchQuery="baseline"
        searchResults={[{
          type: "chat",
          chat_id: "outside",
          title: "Weekly status",
          snippet: "The synergy baseline needs review",
        }]}
        onOpen={onOpen}
        onSearchQueryChange={onSearchQueryChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Weekly status/i }));
    expect(onOpen).toHaveBeenCalledWith("outside");
  });

  it("keeps a collapsed rail so the open button cannot cover page headings", () => {
    const { container } = render(<Sidebar chats={chats} projects={projects} />);
    fireEvent.click(screen.getByLabelText("Close sidebar"));

    expect(screen.getByLabelText("Open sidebar")).toBeInTheDocument();
    expect(container.querySelector("aside")).toHaveClass("w-16");
  });
});

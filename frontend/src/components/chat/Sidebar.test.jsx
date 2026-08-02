import { fireEvent, render, screen } from "@testing-library/react";
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

  it("drops a project chat back into the unfiled chat list", () => {
    const onMoveChat = vi.fn();
    render(
      <Sidebar chats={chats} projects={projects} onMoveChat={onMoveChat} />,
    );
    const dataTransfer = transfer();

    fireEvent.dragStart(screen.getByLabelText("Chat: People risks"), {
      dataTransfer,
    });
    const target = screen.getByLabelText("Chats outside projects drop area");
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });

    expect(onMoveChat).toHaveBeenCalledWith("inside", null);
  });
});

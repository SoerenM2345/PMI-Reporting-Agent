import { useState } from "react";

const PROJECT_ICONS = [
  "📁",
  "📊",
  "🚀",
  "🏢",
  "💼",
  "🧠",
  "⚙️",
  "🔍",
  "📝",
  "🎯",
];

const CHAT_PREVIEW_LIMIT = 6;

/**
 * Expected data structure:
 *
 * projects = [
 *   {
 *     project_id: "project-1",
 *     name: "Finance Integration",
 *     icon: "📊",
 *   },
 * ];
 *
 * chats = [
 *   {
 *     chat_id: "chat-1",
 *     title: "Weekly status report",
 *     message_count: 4,
 *     project_id: "project-1", // null = chat outside a project
 *   },
 * ];
 */
export default function Sidebar({
  chats = [],
  projects = [],
  activeChatId,
  activeProjectId,

  onNew,
  onOpen,
  onRename,
  onDelete,
  onPinChat,

  onCreateProject,
  onRenameProject,
  onChangeProjectIcon,
  onDeleteProject,
  onOpenProject,
  onMoveChat,
  onPinProject,

  searchQuery = "",
  searchResults = [],
  searchBusy = false,
  onSearchQueryChange,

  busy = false,
}) {
  const [isOpen, setIsOpen] = useState(true);

  const [editingChatId, setEditingChatId] = useState(null);
  const [chatDraft, setChatDraft] = useState("");

  const [editingProjectId, setEditingProjectId] = useState(null);
  const [projectDraft, setProjectDraft] = useState("");

  const [expandedProjects, setExpandedProjects] = useState({});
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectIcon, setNewProjectIcon] = useState("📁");

  const [iconPickerProjectId, setIconPickerProjectId] = useState(null);
  const [draggingChatId, setDraggingChatId] = useState(null);
  const [dropTarget, setDropTarget] = useState(null);
  const [showAllGeneralChats, setShowAllGeneralChats] = useState(false);

  const chatsWithoutProject = pinnedFirst(
    chats.filter((chat) => !chat.project_id),
  );
  const orderedProjects = pinnedFirst(projects);
  const visibleGeneralChats = showAllGeneralChats
    ? chatsWithoutProject
    : chatsWithoutProject.slice(0, CHAT_PREVIEW_LIMIT);
  const isSearching = Boolean(searchQuery.trim());

  const startChatRename = (chat) => {
    setEditingChatId(chat.chat_id);
    setChatDraft(chat.title);
  };

  const commitChatRename = (chatId) => {
    const title = chatDraft.trim();

    if (title) {
      onRename?.(chatId, title);
    }

    setEditingChatId(null);
    setChatDraft("");
  };

  const startProjectRename = (project) => {
    setEditingProjectId(project.project_id);
    setProjectDraft(project.name);
  };

  const commitProjectRename = (projectId) => {
    const name = projectDraft.trim();

    if (name) {
      onRenameProject?.(projectId, name);
    }

    setEditingProjectId(null);
    setProjectDraft("");
  };

  const createProject = () => {
    const name = newProjectName.trim();

    if (!name) return;

    onCreateProject?.({
      name,
      icon: newProjectIcon,
    });

    setNewProjectName("");
    setNewProjectIcon("📁");
    setShowCreateProject(false);
  };

  const toggleProject = (projectId) => {
    setExpandedProjects((current) => ({
      ...current,
      [projectId]: !current[projectId],
    }));
  };

  const handleProjectOpen = (projectId) => {
    onOpenProject?.(projectId);

    setExpandedProjects((current) => ({
      ...current,
      [projectId]: true,
    }));
  };

  const startChatDrag = (event, chatId) => {
    const chat = chats.find((candidate) => candidate.chat_id === chatId);
    if (!chat || chat.project_id) {
      event.preventDefault();
      return;
    }
    setDraggingChatId(chatId);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", chatId);
  };

  const finishChatDrag = () => {
    setDraggingChatId(null);
    setDropTarget(null);
  };

  const allowChatDrop = (event, target) => {
    const draggedId =
      event.dataTransfer.getData("text/plain") || draggingChatId;
    const dragged = chats.find((candidate) => candidate.chat_id === draggedId);
    if (busy || !target || !dragged || dragged.project_id) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropTarget(target);
  };

  const leaveChatDrop = (event, target) => {
    if (event.currentTarget.contains(event.relatedTarget)) return;
    setDropTarget((current) => (current === target ? null : current));
  };

  const dropChat = (event, projectId) => {
    event.preventDefault();
    event.stopPropagation();
    const draggedId =
      event.dataTransfer.getData("text/plain") || draggingChatId;
    const dragged = chats.find((candidate) => candidate.chat_id === draggedId);
    // Filing is one-time: only an unassigned chat can enter a project. This
    // guard also rejects synthetic drag events for already-assigned chats.
    if (dragged && !dragged.project_id && projectId) {
      onMoveChat?.(draggedId, projectId);
      setExpandedProjects((current) => ({ ...current, [projectId]: true }));
    }
    finishChatDrag();
  };

  return (
    <>
      <aside
        className={`relative flex h-full shrink-0 flex-col border-r
                    border-slate-200 bg-white transition-all duration-300
                    ${
                      isOpen
                        ? "w-72 translate-x-0"
                        : "w-16 overflow-hidden"
                    }`}
      >
        {!isOpen ? (
          <button
            type="button"
            onClick={() => setIsOpen(true)}
            aria-label="Open sidebar"
            title="Open sidebar"
            className="mx-auto mt-3 flex h-9 w-9 shrink-0 items-center
                       justify-center rounded-lg border border-slate-200
                       bg-white text-base text-slate-700 shadow-sm
                       transition hover:bg-slate-100"
          >
            ☰
          </button>
        ) : (
          <>
        <SidebarHeader onClose={() => setIsOpen(false)} />

        <div className="space-y-2 border-b border-slate-100 p-2.5">
          <button
            type="button"
            onClick={() => onNew?.(null)}
            disabled={busy}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg
                       bg-slate-900 px-3 py-2 text-[13px] font-semibold
                       text-white transition hover:bg-slate-700
                       disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="text-base leading-none">＋</span>
            New chat
          </button>

          <button
            type="button"
            onClick={() => setShowCreateProject(true)}
            disabled={busy}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg
                       border border-slate-300 bg-white px-3 py-2 text-[13px]
                       font-semibold text-slate-700 transition
                       hover:bg-slate-50 disabled:cursor-not-allowed
                       disabled:opacity-40"
          >
            <span className="text-sm">📁</span>
            Create project
          </button>

          <label className="relative block">
            <span className="sr-only">Search all chats and projects</span>
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-xs text-slate-400">
              ⌕
            </span>
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => onSearchQueryChange?.(event.target.value)}
              placeholder="Search everything"
              className="w-full rounded-lg border border-slate-200 bg-slate-50
                         py-2 pl-8 pr-3 text-[13px] text-slate-700 outline-none
                         placeholder:text-slate-400 focus:border-slate-400
                         focus:bg-white focus:ring-2 focus:ring-slate-100"
            />
          </label>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-2 py-2.5">
          {isSearching ? (
            <SearchResults
              query={searchQuery}
              results={searchResults}
              busy={searchBusy}
              onOpenChat={onOpen}
              onOpenProject={handleProjectOpen}
            />
          ) : (
            <>
          <SidebarSectionTitle>Projects</SidebarSectionTitle>

          {projects.length === 0 && (
            <p className="px-3 py-4 text-center text-xs text-slate-400">
              No projects yet.
            </p>
          )}

          <div className="space-y-1">
            {orderedProjects.map((project) => {
              const projectChats = pinnedFirst(chats.filter(
                (chat) => chat.project_id === project.project_id,
              ));

              const isExpanded =
                expandedProjects[project.project_id] ?? true;

              const isActive = project.project_id === activeProjectId;

              return (
                <ProjectItem
                  key={project.project_id}
                  project={project}
                  chats={projectChats}
                  activeChatId={activeChatId}
                  isActive={isActive}
                  isExpanded={isExpanded}
                  editingProjectId={editingProjectId}
                  projectDraft={projectDraft}
                  editingChatId={editingChatId}
                  chatDraft={chatDraft}
                  iconPickerProjectId={iconPickerProjectId}
                  busy={busy}
                  isDropTarget={dropTarget === project.project_id}
                  onDragOver={(event) =>
                    allowChatDrop(event, project.project_id)
                  }
                  onDragLeave={(event) =>
                    leaveChatDrop(event, project.project_id)
                  }
                  onDrop={(event) => dropChat(event, project.project_id)}
                  onToggle={() => toggleProject(project.project_id)}
                  onOpenProject={() =>
                    handleProjectOpen(project.project_id)
                  }
                  onNewChat={() => onNew?.(project.project_id)}
                  onOpenChat={onOpen}
                  onStartProjectRename={() =>
                    startProjectRename(project)
                  }
                  onProjectDraftChange={setProjectDraft}
                  onCommitProjectRename={() =>
                    commitProjectRename(project.project_id)
                  }
                  onCancelProjectRename={() => {
                    setEditingProjectId(null);
                    setProjectDraft("");
                  }}
                  onToggleIconPicker={() =>
                    setIconPickerProjectId((current) =>
                      current === project.project_id
                        ? null
                        : project.project_id,
                    )
                  }
                  onSelectIcon={(icon) => {
                    onChangeProjectIcon?.(project.project_id, icon);
                    setIconPickerProjectId(null);
                  }}
                  onDeleteProject={() =>
                    onDeleteProject?.(project.project_id, project.name)
                  }
                  onPinProject={() =>
                    onPinProject?.(project.project_id, !project.pinned)
                  }
                  onStartChatRename={startChatRename}
                  onChatDraftChange={setChatDraft}
                  onCommitChatRename={commitChatRename}
                  onCancelChatRename={() => {
                    setEditingChatId(null);
                    setChatDraft("");
                  }}
                  onDeleteChat={onDelete}
                  onPinChat={onPinChat}
                  onChatDragStart={startChatDrag}
                  onChatDragEnd={finishChatDrag}
                />
              );
            })}
          </div>

          <div className="my-4 border-t border-slate-100" />

          <div className="rounded-xl border border-transparent p-1">
            <SidebarSectionTitle>Chats</SidebarSectionTitle>

            {chatsWithoutProject.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-slate-400">
                No chats outside projects.
              </p>
            ) : (
              <div className="space-y-1">
                {visibleGeneralChats.map((chat) => (
                  <ChatItem
                    key={chat.chat_id}
                    chat={chat}
                    active={chat.chat_id === activeChatId}
                    editing={editingChatId === chat.chat_id}
                    draft={chatDraft}
                    busy={busy}
                    movable
                    dragging={draggingChatId === chat.chat_id}
                    onDragStart={startChatDrag}
                    onDragEnd={finishChatDrag}
                    onOpen={() => onOpen?.(chat.chat_id)}
                    onStartRename={() => startChatRename(chat)}
                    onDraftChange={setChatDraft}
                    onCommitRename={() => commitChatRename(chat.chat_id)}
                    onCancelRename={() => {
                      setEditingChatId(null);
                      setChatDraft("");
                    }}
                    onDelete={() => onDelete?.(chat.chat_id, chat.title)}
                    onPin={() => onPinChat?.(chat.chat_id, !chat.pinned)}
                  />
                ))}
                {chatsWithoutProject.length > CHAT_PREVIEW_LIMIT && (
                  <ShowMoreButton
                    expanded={showAllGeneralChats}
                    hiddenCount={chatsWithoutProject.length - CHAT_PREVIEW_LIMIT}
                    onClick={() => setShowAllGeneralChats((current) => !current)}
                  />
                )}
              </div>
            )}
          </div>
            </>
          )}
        </nav>
          </>
        )}
      </aside>

      {showCreateProject && (
        <CreateProjectModal
          name={newProjectName}
          icon={newProjectIcon}
          busy={busy}
          onNameChange={setNewProjectName}
          onIconChange={setNewProjectIcon}
          onCancel={() => {
            setShowCreateProject(false);
            setNewProjectName("");
            setNewProjectIcon("📁");
          }}
          onCreate={createProject}
        />
      )}
    </>
  );
}

function SidebarHeader({ onClose }) {
  return (
    <div className="flex h-12 items-center justify-between border-b border-slate-100 px-3">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-900 text-xs text-white">
          AI
        </div>

        <span className="text-[13px] font-semibold text-slate-800">
          PMI Assistant
        </span>
      </div>

      <button
        type="button"
        onClick={onClose}
        aria-label="Close sidebar"
        title="Close sidebar"
        className="flex h-8 w-8 items-center justify-center rounded-lg
                   text-base text-slate-500 transition hover:bg-slate-100
                   hover:text-slate-800"
      >
        ‹
      </button>
    </div>
  );
}

function SidebarSectionTitle({ children }) {
  return (
    <div className="mb-2 flex items-center justify-between px-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
        {children}
      </h2>
    </div>
  );
}

function SearchResults({ query, results, busy, onOpenChat, onOpenProject }) {
  return (
    <div>
      <SidebarSectionTitle>Search results</SidebarSectionTitle>

      {busy ? (
        <p className="px-3 py-5 text-center text-xs text-slate-400">
          Searching…
        </p>
      ) : results.length === 0 ? (
        <p className="px-3 py-5 text-center text-xs text-slate-400">
          No results for “{query.trim()}”.
        </p>
      ) : (
        <div className="space-y-1">
          {results.map((result) => (
            <button
              key={`${result.type}-${result.chat_id || result.project_id}`}
              type="button"
              onClick={() =>
                result.type === "project"
                  ? onOpenProject?.(result.project_id)
                  : onOpenChat?.(result.chat_id)
              }
              className="block w-full rounded-lg px-3 py-2 text-left
                         transition hover:bg-slate-100"
            >
              <div className="flex items-center gap-2">
                <span className="text-xs">
                  {result.type === "project" ? result.icon || "📁" : "💬"}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-slate-700">
                  {result.title}
                </span>
              </div>
              {result.snippet && result.snippet !== result.title && (
                <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">
                  {result.snippet}
                </p>
              )}
              {result.project_name && (
                <p className="mt-1 truncate text-[11px] text-slate-400">
                  In {result.project_name}
                </p>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ShowMoreButton({ expanded, hiddenCount, onClick, compact = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-lg px-3 py-1.5 text-left text-[11px] font-medium
                  text-slate-400 transition hover:bg-slate-50
                  hover:text-slate-600 ${compact ? "ml-5 w-[calc(100%-1.25rem)]" : ""}`}
    >
      {expanded ? "Show less" : `Show more (${hiddenCount})`}
    </button>
  );
}

function ProjectItem({
  project,
  chats,
  activeChatId,
  isActive,
  isExpanded,
  editingProjectId,
  projectDraft,
  editingChatId,
  chatDraft,
  iconPickerProjectId,
  busy,
  isDropTarget,
  onDragOver,
  onDragLeave,
  onDrop,
  onToggle,
  onOpenProject,
  onNewChat,
  onOpenChat,
  onStartProjectRename,
  onProjectDraftChange,
  onCommitProjectRename,
  onCancelProjectRename,
  onToggleIconPicker,
  onSelectIcon,
  onDeleteProject,
  onPinProject,
  onStartChatRename,
  onChatDraftChange,
  onCommitChatRename,
  onCancelChatRename,
  onDeleteChat,
  onPinChat,
  onChatDragStart,
  onChatDragEnd,
}) {
  const isEditing = editingProjectId === project.project_id;
  const showIconPicker = iconPickerProjectId === project.project_id;
  const [showAllChats, setShowAllChats] = useState(false);
  const visibleChats = showAllChats
    ? chats
    : chats.slice(0, CHAT_PREVIEW_LIMIT);

  return (

    <div
      aria-label={`Project drop area: ${project.name}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={`rounded-xl border transition ${
        isDropTarget
          ? "border-blue-400 bg-blue-50 ring-2 ring-blue-100"
          : isActive
          ? "border-slate-300 bg-slate-50"
          : "border-transparent hover:bg-slate-50"
      }`}
    >

      <div className="group/project relative flex items-center gap-0.5 p-1">
        <button
          type="button"
          onClick={onToggle}
          aria-label={isExpanded ? "Collapse project" : "Expand project"}
          className="flex h-7 w-7 shrink-0 items-center justify-center
                     rounded-lg text-xs text-slate-400 hover:bg-slate-200
                     hover:text-slate-700"
        >
          {isExpanded ? "⌄" : "›"}
        </button>

        <button
          type="button"
          onClick={onToggleIconPicker}
          aria-label="Change project icon"
          title="Change project icon"
          className="flex h-8 w-8 shrink-0 items-center justify-center
                     rounded-lg text-base transition hover:bg-slate-200"
        >
          {project.icon || "📁"}
        </button>

        {isEditing ? (
          <input
            autoFocus
            value={projectDraft}
            onChange={(event) =>
              onProjectDraftChange(event.target.value)
            }
            onBlur={onCommitProjectRename}
            onKeyDown={(event) => {
              if (event.key === "Enter") onCommitProjectRename();
              if (event.key === "Escape") onCancelProjectRename();
            }}
            className="min-w-0 flex-1 rounded-lg border border-slate-300
                       bg-white px-2 py-1 text-[13px] font-medium
                       text-slate-800 outline-none focus:border-slate-500"
          />
        ) : (
          <button
            type="button"
            onClick={onOpenProject}
            className="min-w-0 flex-1 truncate text-left text-[13px]
                       font-semibold text-slate-800 transition-[padding]
                       group-hover/project:pr-[5.5rem]
                       group-focus-within/project:pr-[5.5rem]"
            title={project.name}
          >
            {project.name}
          </button>
        )}

        {!isEditing && (
          <div
            className="absolute right-1 top-1/2 flex -translate-y-1/2
                       items-center gap-0.5 rounded-lg bg-white opacity-0
                       shadow-sm transition group-hover/project:opacity-100
                       focus-within:opacity-100"
          >
            <IconButton
              label={project.pinned ? "Unpin project" : "Pin project"}
              onClick={onPinProject}
              active={project.pinned}
            >
              📌
            </IconButton>

            <IconButton
              label="Rename project"
              onClick={onStartProjectRename}
            >
              ✎
            </IconButton>

            <IconButton
              label="Delete project"
              onClick={onDeleteProject}
              danger
            >
              🗑
            </IconButton>
          </div>
        )}
      </div>

      {showIconPicker && (
        <IconPicker
          selectedIcon={project.icon}
          onSelect={onSelectIcon}
        />
      )}

      {isExpanded && (
        <div className="px-2 pb-2">
          <button
            type="button"
            onClick={onNewChat}
            disabled={busy}
            className="mb-1 flex w-full items-center gap-1.5 rounded-lg
                       px-2 py-1.5 text-left text-[11px] font-medium
                       text-slate-500 transition hover:bg-slate-200
                       hover:text-slate-800 disabled:opacity-40"
          >
            <span className="text-sm">＋</span>
            New chat in project
          </button>

          {chats.length === 0 ? (
            <p className="px-3 py-2 text-xs text-slate-400">
              No project chats yet.
            </p>
          ) : (
            <div className="space-y-1">
              {visibleChats.map((chat) => (
                <ChatItem
                  key={chat.chat_id}
                  chat={chat}
                  compact
                  active={chat.chat_id === activeChatId}
                  editing={editingChatId === chat.chat_id}
                  draft={chatDraft}
                  busy={busy}
                  dragging={false}
                  onDragStart={onChatDragStart}
                  onDragEnd={onChatDragEnd}
                  onOpen={() => onOpenChat?.(chat.chat_id)}
                  onStartRename={() => onStartChatRename(chat)}
                  onDraftChange={onChatDraftChange}
                  onCommitRename={() =>
                    onCommitChatRename(chat.chat_id)
                  }
                  onCancelRename={onCancelChatRename}
                  onDelete={() =>
                    onDeleteChat?.(chat.chat_id, chat.title)
                  }
                  onPin={() => onPinChat?.(chat.chat_id, !chat.pinned)}
                />
              ))}
              {chats.length > CHAT_PREVIEW_LIMIT && (
                <ShowMoreButton
                  compact
                  expanded={showAllChats}
                  hiddenCount={chats.length - CHAT_PREVIEW_LIMIT}
                  onClick={() => setShowAllChats((current) => !current)}
                />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ChatItem({
  chat,
  active,
  editing,
  draft,
  compact = false,
  busy = false,
  movable = false,
  dragging = false,
  onDragStart,
  onDragEnd,
  onOpen,
  onStartRename,
  onDraftChange,
  onCommitRename,
  onCancelRename,
  onDelete,
  onPin,
}) {
  return (
    <div
      draggable={movable && !editing && !busy}
      onDragStart={(event) => {
        if (movable) onDragStart?.(event, chat.chat_id);
      }}
      onDragEnd={onDragEnd}
      aria-label={`Chat: ${chat.title}`}
      className={`group/chat rounded-lg transition ${
        compact ? "ml-4" : ""
      } ${dragging ? "opacity-40" : ""} ${
        active ? "bg-slate-200" : "hover:bg-slate-100"
      }`}
    >
      {editing ? (
        <div className="p-1.5">
          <input
            autoFocus
            value={draft}
            onChange={(event) => onDraftChange(event.target.value)}
            onBlur={onCommitRename}
            onKeyDown={(event) => {
              if (event.key === "Enter") onCommitRename();
              if (event.key === "Escape") onCancelRename();
            }}
            className="w-full rounded-lg border border-slate-300 bg-white
                       px-2 py-1 text-[13px] text-slate-800 outline-none
                       focus:border-slate-500"
          />
        </div>
      ) : (
        <div className="relative flex items-center gap-0.5 p-1">
          <button
            type="button"
            onClick={onOpen}
            className="min-w-0 flex-1 px-2 py-1 text-left transition-[padding]
                       group-hover/chat:pr-[5.5rem]
                       group-focus-within/chat:pr-[5.5rem]"
          >
            <div
              className="truncate text-[13px] font-medium text-slate-700"
              title={chat.title}
            >
              {chat.title}
            </div>

            <div className="mt-0.5 text-[10px] text-slate-400">
              {chat.message_count || 0} message
              {chat.message_count === 1 ? "" : "s"}
            </div>
          </button>

          <div
            className="absolute right-1 top-1/2 flex -translate-y-1/2
                       shrink-0 items-center gap-0.5 rounded-lg bg-white
                       opacity-0 shadow-sm transition group-hover/chat:opacity-100
                       focus-within:opacity-100"
          >
            <IconButton
              label={chat.pinned ? "Unpin chat" : "Pin chat"}
              onClick={onPin}
              active={chat.pinned}
            >
              📌
            </IconButton>

            <IconButton label="Rename chat" onClick={onStartRename}>
              ✎
            </IconButton>

            <IconButton label="Delete chat" onClick={onDelete} danger>
              🗑
            </IconButton>
          </div>
        </div>
      )}
    </div>
  );
}

function IconPicker({ selectedIcon, onSelect }) {
  return (
    <div className="mx-2 mb-2 rounded-lg border border-slate-200 bg-white p-2 shadow-sm">
      <p className="mb-2 px-1 text-[11px] font-medium text-slate-500">
        Choose project icon
      </p>

      <div className="grid grid-cols-5 gap-1">
        {PROJECT_ICONS.map((icon) => (
          <button
            key={icon}
            type="button"
            onClick={() => onSelect(icon)}
            className={`flex h-8 w-8 items-center justify-center rounded-lg
                        text-base transition hover:bg-slate-100 ${
                          selectedIcon === icon
                            ? "bg-slate-200 ring-1 ring-slate-300"
                            : ""
                        }`}
          >
            {icon}
          </button>
        ))}
      </div>
    </div>
  );
}

function CreateProjectModal({
  name,
  icon,
  busy,
  onNameChange,
  onIconChange,
  onCancel,
  onCreate,
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center
                 bg-slate-950/30 p-4 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl">
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              Create a project
            </h2>

            <p className="mt-1 text-sm text-slate-500">
              Group chats and project knowledge in one place.
            </p>
          </div>

          <button
            type="button"
            onClick={onCancel}
            className="flex h-9 w-9 items-center justify-center rounded-lg
                       text-lg text-slate-400 hover:bg-slate-100
                       hover:text-slate-700"
          >
            ×
          </button>
        </div>

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-slate-700">
            Project name
          </span>

          <input
            autoFocus
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onCreate();
              if (event.key === "Escape") onCancel();
            }}
            placeholder="For example: Finance Integration"
            className="w-full rounded-lg border border-slate-300 px-3 py-2.5
                       text-sm text-slate-900 outline-none
                       placeholder:text-slate-400 focus:border-slate-500
                       focus:ring-2 focus:ring-slate-200"
          />
        </label>

        <div className="mt-4">
          <span className="mb-2 block text-sm font-medium text-slate-700">
            Project icon
          </span>

          <div className="grid grid-cols-5 gap-2">
            {PROJECT_ICONS.map((projectIcon) => (
              <button
                key={projectIcon}
                type="button"
                onClick={() => onIconChange(projectIcon)}
                className={`flex h-11 items-center justify-center rounded-lg
                            border text-xl transition hover:bg-slate-50 ${
                              icon === projectIcon
                                ? "border-slate-500 bg-slate-100 ring-2 ring-slate-200"
                                : "border-slate-200"
                            }`}
              >
                {projectIcon}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-slate-300 px-4 py-2.5
                       text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={onCreate}
            disabled={busy || !name.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm
                       font-semibold text-white hover:bg-slate-700
                       disabled:cursor-not-allowed disabled:opacity-40"
          >
            Create project
          </button>
        </div>
      </div>
    </div>
  );
}

function IconButton({ label, onClick, children, danger = false, active = false }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        onClick?.();
      }}
      className={`flex h-7 w-7 items-center justify-center rounded-md
                  text-sm transition ${
                    danger
                      ? "text-slate-400 hover:bg-red-50 hover:text-red-600"
                      : active
                      ? "bg-slate-200 text-slate-700 hover:bg-slate-300"
                      : "text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                  }`}
    >
      {children}
    </button>
  );
}

function pinnedFirst(items) {
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) =>
      Number(Boolean(right.item.pinned)) - Number(Boolean(left.item.pinned)) ||
      left.index - right.index,
    )
    .map(({ item }) => item);
}

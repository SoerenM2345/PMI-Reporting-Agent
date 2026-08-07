"""Simple LLM-driven conversation loop for document generation.

This is the new core of the agent:
1. User uploads files
2. User requests output (powerpoint, excel, etc)
3. LLM generates document content directly
4. User sees preview, can revise via chat
5. User approves and file is rendered
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.generation.content_schema import GeneratedContent
from app.generation.llm_generator import generate_document, regenerate_document
from app.storage import json_store

log = logging.getLogger("pmi.agent.llm_loop")


class DocumentSession:
    """Manages a document generation session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.file_text: Optional[str] = None
        self.current_content: Optional[GeneratedContent] = None
        self.approved_content: Optional[GeneratedContent] = None
        self.generation_request: Optional[str] = None
        self.audience: Optional[str] = None
        self.output_format: Optional[str] = None

    def load_files(self, file_contents: list[str]) -> str:
        """Load file contents and return as concatenated text."""
        self.file_text = "\n\n---FILE SEPARATOR---\n\n".join(file_contents)
        return self.file_text

    def generate(
        self,
        request: str,
        output_format: str = "PowerPoint",
        audience: Optional[str] = None,
    ) -> tuple[GeneratedContent, list[str]]:
        """Generate initial document content."""
        if not self.file_text:
            return (
                GeneratedContent(
                    title="No Files",
                    subtitle="Upload files first",
                    sections=[]
                ),
                ["No files uploaded"]
            )

        self.generation_request = request
        self.output_format = output_format or "PowerPoint"
        self.audience = audience

        self.current_content, warnings = generate_document(
            file_text=self.file_text,
            request=request,
            output_format=output_format,
            audience=audience,
        )

        return self.current_content, warnings

    def revise(self, revision_request: str) -> tuple[GeneratedContent, list[str]]:
        """Revise current document based on user request."""
        if not self.current_content or not self.file_text:
            return (
                GeneratedContent(
                    title="Error",
                    subtitle="No document to revise",
                    sections=[]
                ),
                ["No document in progress"]
            )

        self.current_content, warnings = regenerate_document(
            file_text=self.file_text,
            current_content=self.current_content,
            revision=revision_request,
            output_format=self.output_format or "PowerPoint",
            audience=self.audience,
        )

        return self.current_content, warnings

    def approve(self) -> GeneratedContent:
        """Approve current content for rendering."""
        if not self.current_content:
            raise ValueError("No content to approve")
        self.approved_content = self.current_content
        return self.approved_content

    def save(self) -> None:
        """Save session state to storage."""
        state = {
            "file_text": self.file_text,
            "current_content": (
                self.current_content.model_dump() if self.current_content else None
            ),
            "approved_content": (
                self.approved_content.model_dump() if self.approved_content else None
            ),
            "generation_request": self.generation_request,
            "audience": self.audience,
            "output_format": self.output_format,
        }
        json_store.save_session_state(self.session_id, "llm_loop", state)

    def load(self) -> bool:
        """Load session state from storage. Returns True if successful."""
        state = json_store.load_session_state(self.session_id, "llm_loop")
        if not state:
            return False

        self.file_text = state.get("file_text")
        if state.get("current_content"):
            self.current_content = GeneratedContent(**state["current_content"])
        if state.get("approved_content"):
            self.approved_content = GeneratedContent(**state["approved_content"])
        self.generation_request = state.get("generation_request")
        self.audience = state.get("audience")
        self.output_format = state.get("output_format")

        return True


def get_session(session_id: str) -> DocumentSession:
    """Get or create a session."""
    session = DocumentSession(session_id)
    session.load()
    return session

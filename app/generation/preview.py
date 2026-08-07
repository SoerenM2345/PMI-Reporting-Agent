"""Convert GeneratedContent to HTML preview for user review."""
from __future__ import annotations

from app.generation.content_schema import GeneratedContent


def content_to_html(content: GeneratedContent) -> str:
    """Convert generated content to HTML for preview."""
    html_parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        "  <title>Document Preview</title>",
        "  <style>",
        _CSS,
        "  </style>",
        "</head>",
        "<body>",
        "  <div class='container'>",
    ]

    # Header
    html_parts.append(f"    <h1>{_escape(content.title)}</h1>")
    if content.subtitle:
        html_parts.append(f"    <p class='subtitle'>{_escape(content.subtitle)}</p>")

    # Metadata
    if content.metadata:
        html_parts.append("    <div class='metadata'>")
        for key, value in content.metadata.items():
            if key not in ["document_type", "audience", "reporting_date"]:
                continue
            label = key.replace("_", " ").title()
            html_parts.append(f"      <div><strong>{label}:</strong> {_escape(str(value))}</div>")
        html_parts.append("    </div>")

    # Sections
    for section in content.sections:
        html_parts.append("    <section>")
        html_parts.append(f"      <h2>{_escape(section.title)}</h2>")

        if section.type == "text":
            html_parts.append(f"      <p>{_escape(str(section.content))}</p>")

        elif section.type == "bullets":
            if isinstance(section.content, str):
                # Single string - split by newlines
                items = [line.strip() for line in section.content.split("\n") if line.strip()]
            else:
                items = section.content
            html_parts.append("      <ul>")
            for item in items:
                html_parts.append(f"        <li>{_escape(str(item))}</li>")
            html_parts.append("      </ul>")

        elif section.type == "table":
            html_parts.append("      <div class='table-wrapper'>")
            html_parts.append("        <table>")
            if isinstance(section.content, list) and section.content:
                for row in section.content:
                    html_parts.append("          <tr>")
                    if isinstance(row, list):
                        for cell in row:
                            html_parts.append(f"            <td>{_escape(str(cell))}</td>")
                    else:
                        html_parts.append(f"            <td>{_escape(str(row))}</td>")
                    html_parts.append("          </tr>")
            html_parts.append("        </table>")
            html_parts.append("      </div>")

        elif section.type == "chart":
            html_parts.append(
                f"      <div class='chart-placeholder'>[Chart: {_escape(section.title)}]</div>"
            )

        html_parts.append("    </section>")

    html_parts.extend([
        "  </div>",
        "</body>",
        "</html>",
    ])

    return "\n".join(html_parts)


def _escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


_CSS = """
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        line-height: 1.6;
        color: #333;
        background: #f5f5f5;
    }

    .container {
        max-width: 900px;
        margin: 0 auto;
        padding: 3rem 2rem;
        background: white;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }

    h1 {
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
        color: #1a1a1a;
    }

    .subtitle {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 1.5rem;
        font-weight: 500;
    }

    .metadata {
        background: #f9f9f9;
        border-left: 3px solid #2563eb;
        padding: 1rem;
        margin-bottom: 2rem;
        font-size: 0.95rem;
    }

    .metadata > div {
        margin: 0.5rem 0;
    }

    section {
        margin-bottom: 3rem;
    }

    h2 {
        font-size: 1.5rem;
        font-weight: 700;
        margin-bottom: 1rem;
        color: #1a1a1a;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #2563eb;
    }

    p {
        margin-bottom: 1rem;
        color: #333;
        line-height: 1.8;
    }

    ul {
        margin-left: 2rem;
        margin-bottom: 1rem;
    }

    li {
        margin-bottom: 0.5rem;
        color: #333;
    }

    .table-wrapper {
        overflow-x: auto;
        margin: 1rem 0;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        background: white;
        border: 1px solid #ddd;
    }

    th {
        background: #f5f5f5;
        padding: 1rem;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid #ddd;
    }

    td {
        padding: 0.75rem 1rem;
        border-bottom: 1px solid #ddd;
    }

    tr:hover {
        background: #f9f9f9;
    }

    .chart-placeholder {
        background: #f0f0f0;
        border: 2px dashed #ccc;
        padding: 2rem;
        text-align: center;
        color: #666;
        border-radius: 4px;
    }

    @media print {
        body {
            background: white;
        }
        .container {
            box-shadow: none;
            max-width: 100%;
        }
    }
"""

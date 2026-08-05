import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FormatPreview from "./FormatPreview";

describe("format-specific report review", () => {
  it("shows slide numbering, divider status, layout, and complete text", () => {
    render(
      <FormatPreview
        preview={{
          format: "powerpoint",
          pages: [
            {
              page_id: "chapter-risks",
              label: "Slide",
              number: 2,
              is_divider: true,
              layout: "Section divider",
              title: "Risk outlook",
              subtitle: "What requires Steering Committee attention",
              content: [
                {
                  kind: "prose",
                  block_id: "risk.body",
                  text: "Three decisions require attention.",
                },
              ],
              source_note: "Source: risk-register.xlsx",
              warnings: [],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("Slide 2")).toBeInTheDocument();
    expect(screen.getByText("Divider")).toBeInTheDocument();
    expect(screen.getByText("Layout: Section divider")).toBeInTheDocument();
    expect(screen.getByText("Risk outlook")).toBeInTheDocument();
    expect(screen.getByText("Three decisions require attention.")).toBeInTheDocument();
    expect(screen.getByText("Source: risk-register.xlsx")).toBeInTheDocument();
  });

  it("shows a chart's message, axes, categories, and exact plotted values", () => {
    render(
      <FormatPreview
        preview={{
          format: "chart",
          charts: [
            {
              block_id: "progress.chart",
              chart_type: "column",
              title: "Workstream progress is uneven",
              intended_message: "Finance trails the other workstreams.",
              category_axis: { title: "Workstream" },
              value_axis: { title: "Progress" },
              legend: "bottom",
              data_labels: "all",
              categories: ["Finance", "IT"],
              series: [
                {
                  name: "Progress",
                  points: [
                    { label: "Finance", display: "45%" },
                    { label: "IT", display: "80%" },
                  ],
                },
              ],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("Workstream progress is uneven")).toBeInTheDocument();
    expect(screen.getByText(/Finance trails/)).toBeInTheDocument();
    expect(screen.getByText("Workstream · Progress")).toBeInTheDocument();
    expect(screen.getByText("45%")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
  });
});

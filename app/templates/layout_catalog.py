"""Pick a native layout for a page's intent — and say so when it cannot.

The planner says "this page is a chart with commentary beside it". The catalog
turns that into a real `TemplateLayout` from the master, so the slide inherits
the template's typography, background and spacing instead of being drawn from
scratch on white.

The important behaviour is the *failure* mode. When a composition asks for four
columns and the chosen family has none, the answer is not to fall back to
absolutely-positioned textboxes — that is exactly how the previous renderer
ended up ignoring 57 of 59 layouts. It degrades to the nearest layout that does
exist and returns a reason, which the page carries as a warning and the design
critic can read. A silently wrong layout is worse than a visibly compromised one.
"""
from __future__ import annotations

import logging
from typing import Iterable, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from app.templates.extract_layouts import LayoutFamily, TemplateLayout

log = logging.getLogger("pmi.templates.catalog")

Composition = Literal[
    "single", "two_column", "three_column", "four_column",
    "hero_chart", "chart_plus_commentary", "matrix", "table_full",
    "kpi_banner", "full_bleed", "quote",
]
PagePurpose = Literal["cover", "agenda", "divider", "content", "appendix", "closing"]

#: A divider whose title sits below this line is a full-width statement band —
#: one sentence in large type, nothing else. Above it, the layout is an ordinary
#: section break. Measured: this template's section dividers put their title at
#: y=1.84 and its two statement layouts put theirs at y=3.39.
_STATEMENT_BAND_IN = 2.5

#: How many content columns each composition wants. Compositions that draw their
#: own geometry into a single content box (a matrix, a KPI banner, a full-width
#: chart) ask for one column and place shapes inside it.
COMPOSITION_COLUMNS: dict[str, int] = {
    "single": 1, "hero_chart": 1, "matrix": 1, "table_full": 1, "kpi_banner": 1,
    "two_column": 2, "chart_plus_commentary": 2,
    "three_column": 3, "four_column": 4,
    "full_bleed": 0, "quote": 0,
}

#: Which layout role serves each page purpose.
PURPOSE_ROLE: dict[str, str] = {
    "cover": "title", "divider": "divider", "closing": "end",
    "agenda": "content", "content": "content", "appendix": "content",
}


class LayoutChoice(BaseModel):
    layout: TemplateLayout
    exact: bool = True
    #: Empty when exact. Otherwise a sentence fit for a page warning.
    reason: str = ""
    #: Columns actually available, which may be fewer than the composition asked.
    columns: int = 0
    requested_columns: int = 0

    @property
    def degraded(self) -> bool:
        return not self.exact


class LayoutCatalog(BaseModel):
    layouts: list[TemplateLayout] = Field(default_factory=list)

    # ---------------------------------------------------------- accessors
    def by_id(self, layout_id: str) -> Optional[TemplateLayout]:
        for layout in self.layouts:
            if layout.layout_id == layout_id:
                return layout
        return None

    def by_index(self, index: int) -> Optional[TemplateLayout]:
        for layout in self.layouts:
            if layout.index == index:
                return layout
        return None

    def by_name(self, name: str) -> Optional[TemplateLayout]:
        """Lookup tolerant of the template's own naming inconsistencies.

        Seven layouts carry trailing spaces and `Title only - Black` differs
        from `Title Only` only by the case of one word.
        """
        wanted = " ".join(name.split()).casefold()
        for layout in self.layouts:
            if layout.normalized_name == wanted:
                return layout
        return None

    def with_role(self, role: str,
                  family: Optional[LayoutFamily] = None) -> list[TemplateLayout]:
        return [lay for lay in self.layouts
                if lay.role == role and (family is None or lay.family == family)]

    @property
    def families(self) -> list[LayoutFamily]:
        seen: list[LayoutFamily] = []
        for layout in self.layouts:
            if layout.family not in seen:
                seen.append(layout.family)
        return seen

    def content_layouts(self, family: LayoutFamily = "white") -> list[TemplateLayout]:
        return sorted(self.with_role("content", family), key=lambda lay: lay.columns)

    # ------------------------------------------------------------ choosing
    def choose(self, *, composition: str = "single", purpose: str = "content",
               family: LayoutFamily = "white", needs_subtitle: bool = False,
               needs_picture: bool = False) -> LayoutChoice:
        """The best native layout for this intent, plus why if it is not exact."""
        role = PURPOSE_ROLE.get(purpose, "content")
        if composition == "quote":
            choice = self._quote(family)
            if choice is not None:
                return choice
        if composition == "full_bleed" or needs_picture:
            choice = self._picture(role, family, full_bleed=composition == "full_bleed")
            if choice is not None:
                return choice
        if role != "content":
            return self._non_content(role, family, purpose)
        return self._content(composition, family, needs_subtitle)

    def degrade(self, composition: str,
                family: LayoutFamily = "white") -> LayoutChoice:
        """The fallback for `composition`, with the reason spelled out."""
        return self.choose(composition=composition, family=family)

    # ---------------------------------------------------------- internals
    def _content(self, composition: str, family: LayoutFamily,
                 needs_subtitle: bool) -> LayoutChoice:
        wanted = COMPOSITION_COLUMNS.get(composition, 1) or 1
        pool = [lay for lay in self.content_layouts(family) if lay.slot("title")]
        if not pool:
            pool = [lay for lay in self.content_layouts() if lay.slot("title")]
            if pool:
                log.info("no usable %s content layout; using the default family", family)
        if not pool:
            return self._last_resort(wanted)

        exact = [lay for lay in pool if lay.columns == wanted
                 and (not needs_subtitle or lay.has_subtitle_slot)]
        if exact:
            return LayoutChoice(layout=exact[0], columns=wanted,
                                requested_columns=wanted)

        # Prefer more columns over fewer: an unused column can be released,
        # whereas content that will not fit has to be dropped or overflow.
        richer = [lay for lay in pool if lay.columns > wanted]
        poorer = [lay for lay in pool if 0 < lay.columns < wanted]
        chosen = (min(richer, key=lambda lay: lay.columns) if richer
                  else max(poorer, key=lambda lay: lay.columns) if poorer
                  else pool[-1])
        return LayoutChoice(
            layout=chosen, exact=False, columns=chosen.columns,
            requested_columns=wanted,
            reason=(f"This page was designed for {wanted} columns; the template's "
                    f"closest native layout is {chosen.raw_name.strip()!r} with "
                    f"{chosen.columns}. The content was fitted to that layout."),
        )

    def _non_content(self, role: str, family: LayoutFamily,
                     purpose: str) -> LayoutChoice:
        pool = self.with_role(role, family) or self.with_role(role)
        if role == "divider":
            # Reserve the low, full-width statement band for `quote`. An
            # ordinary section break wants its title in the upper third, where
            # the eye goes first and where the following content page's title
            # will also sit.
            upper = [lay for lay in pool
                     if (lay.slot("title") or lay.slots[0]).top_in <= _STATEMENT_BAND_IN]
            pool = upper or pool
        if pool:
            exact = family in {lay.family for lay in pool}
            return LayoutChoice(
                layout=pool[0], exact=exact,
                reason="" if exact else
                (f"The template has no {family.replace('_', ' ')} "
                 f"{purpose} layout; used {pool[0].raw_name.strip()!r} instead."),
            )
        fallback = self._content("single", family, needs_subtitle=False)
        fallback.exact = False
        fallback.reason = (f"The template defines no {purpose} layout; this page "
                           f"uses a content layout instead.")
        return fallback

    def _picture(self, role: str, family: LayoutFamily,
                 full_bleed: bool) -> Optional[LayoutChoice]:
        pool = [lay for lay in self.layouts if lay.has_picture_slot
                and (lay.role == role or role == "content")]
        if full_bleed:
            # A full-bleed page still has to carry its message, so prefer one
            # that exposes a title slot. And unless a cover was asked for,
            # prefer a layout that is not a cover: a cover's title sits at the
            # bottom-left, which reads as a title slide wherever it appears.
            bleed = sorted(
                (lay for lay in pool if lay.is_full_bleed),
                key=lambda lay: (lay.slot("title") is None,
                                 lay.role == "title" and role != "title",
                                 lay.index),
            )
            if bleed:
                return LayoutChoice(layout=bleed[0], columns=0)
        preferred = [lay for lay in pool if lay.family == family] or pool
        if not preferred:
            return None
        return LayoutChoice(
            layout=preferred[0], exact=not full_bleed,
            reason="" if not full_bleed else
            ("The template has no full-bleed image layout; this page uses the "
             f"nearest picture layout, {preferred[0].raw_name.strip()!r}."),
        )

    def _quote(self, family: LayoutFamily) -> Optional[LayoutChoice]:
        """A single-sentence statement page.

        A divider whose only text slot sits away from the top of the slide is
        designed to hold one line of large type and nothing else — exactly the
        governing-message page a consulting deck opens with.
        """
        candidates = [lay for lay in self.with_role("divider")
                      if lay.slot("title")
                      and lay.slot("title").top_in > _STATEMENT_BAND_IN]
        if not candidates:
            return None
        preferred = [lay for lay in candidates if lay.family == family] or candidates
        return LayoutChoice(layout=preferred[0], columns=0)

    def _last_resort(self, wanted: int) -> LayoutChoice:
        if not self.layouts:
            raise LookupError("the template exposes no layouts at all")
        return LayoutChoice(
            layout=self.layouts[0], exact=False, columns=0, requested_columns=wanted,
            reason="No layout in this template exposes a title slot; the page was "
                   "placed on the first available layout.",
        )


def build(layouts: Iterable[TemplateLayout]) -> LayoutCatalog:
    catalog = LayoutCatalog(layouts=list(layouts))
    usable = [lay for lay in catalog.layouts if lay.role == "content" and lay.columns]
    log.info("catalog: %d layouts, %d usable content layouts, families %s",
             len(catalog.layouts), len(usable), ", ".join(catalog.families))
    return catalog


def describe(choices: Sequence[LayoutChoice]) -> str:
    """A one-line summary for logs and the design critic."""
    used = sorted({c.layout.raw_name.strip() for c in choices})
    degraded = sum(1 for c in choices if c.degraded)
    return f"{len(used)} distinct layouts ({', '.join(used)}); {degraded} degraded"

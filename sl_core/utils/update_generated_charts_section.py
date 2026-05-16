import os
import sys
from pathlib import Path

MARKER_START = "<!-- GENERATED_CHARTS_START -->"
MARKER_END = "<!-- GENERATED_CHARTS_END -->"

DEFAULT_BASE_URL = "https://golder-development.github.io/UK_Socio_Economic_Modelling/"
DEFAULT_CHARTS_DIR = "generated_charts"
DEFAULT_INDEX_MD = "index.md"

ALLOWED_EXTS = {".html", ".htm", ".png", ".jpg", ".jpeg", ".svg"}

# Special-case display names for known files
SPECIAL_NAMES = {
    "mortality_dashboard_interactive.html": "Mortality Dashboard — Interactive",
    "mortality_dashboard_filtered.html": "Mortality Dashboard — Filtered",
    "mortality_dashboard_drilldown.html": "Mortality Dashboard — Drilldown",
    "political_posts_mindmap.html": "Political Posts Mind Map — 2D",
    "political_posts_mindmap_3d.html": "Political Posts Mind Map — 3D",
    "mortality_dashboard_age_preschool.html": "Mortality Dashboard — Preschool (≤5)",
    "mortality_dashboard_age_school.html": "Mortality Dashboard — School Age (6–19)",
    "mortality_dashboard_age_young_adults.html": "Mortality Dashboard — Young Adults (20–34)",
    "mortality_dashboard_age_older_adults.html": "Mortality Dashboard — Older Adults (35–64)",
    "mortality_dashboard_age_young_oaps.html": "Mortality Dashboard — Young OAPs (65–84)",
    "mortality_dashboard_age_old_oaps.html": "Mortality Dashboard — Old OAPs (85+)",
}


def categorize(filename: str) -> str:
    name = filename.lower()
    if name.startswith("mortality_dashboard"):
        return "Mortality Dashboards"
    if name.startswith("political_posts_mindmap"):
        return "Political Mind Maps"
    return "Other Outputs"


def to_display_name(filename: str) -> str:
    if filename in SPECIAL_NAMES:
        return SPECIAL_NAMES[filename]
    stem = Path(filename).stem
    text = stem.replace("_", " ").replace("-", " ")
    # Title-case words, but keep all-caps and numbers intact
    words = [w if w.isupper() else w.capitalize() for w in text.split()]
    return " ".join(words)


def build_content(base_url: str, charts_dir: Path) -> str:
    entries_by_cat = {}
    for fname in sorted(os.listdir(charts_dir)):
        if fname.startswith("."):
            continue
        ext = Path(fname).suffix.lower()
        if ext not in ALLOWED_EXTS:
            continue
        cat = categorize(fname)
        url = base_url.rstrip("/") + "/" + charts_dir.name + "/" + fname
        label = to_display_name(fname)
        entries_by_cat.setdefault(cat, []).append((label, url))

    lines = []
    # Intro line sits above markers in index.md; here we only emit the list
    # grouped by themed sub-headers for clarity.
    # Generate categories in a stable order
    for cat in ["Mortality Dashboards", "Political Mind Maps", "Other Outputs"]:
        items = entries_by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"### {cat}")
        lines.append("")
        for label, url in items:
            lines.append(f"- {label}: <{url}>")
        lines.append("")
    # Trim trailing blank line
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def update_index(index_md: Path, generated_block: str) -> None:
    text = index_md.read_text(encoding="utf-8")
    if MARKER_START in text and MARKER_END in text:
        pre, rest = text.split(MARKER_START, 1)
        _, post = rest.split(MARKER_END, 1)
        new_text = pre + MARKER_START + "\n" + generated_block + MARKER_END + post
        index_md.write_text(new_text, encoding="utf-8")
        print("Updated existing generated charts section.")
        return
    # If markers are missing, try to find the '## Generated Charts' heading and insert
    heading = "## Generated Charts"
    if heading in text:
        parts = text.split(heading)
        # Reconstruct with markers after heading
        new = parts[0] + heading + "\n\n" + "Explore the published outputs hosted via GitHub Pages:\n\n" + MARKER_START + "\n" + generated_block + MARKER_END
        if len(parts) > 1:
            new += parts[1]
        index_md.write_text(new, encoding="utf-8")
        print("Inserted generated charts section after heading.")
        return
    # Otherwise, append a new section at the end
    new_text = text.rstrip() + "\n\n---\n\n" + heading + "\n\n" + "Explore the published outputs hosted via GitHub Pages:\n\n" + MARKER_START + "\n" + generated_block + MARKER_END + "\n"
    index_md.write_text(new_text, encoding="utf-8")
    print("Appended new generated charts section.")


def main():
    base_url = os.environ.get("GENERATED_CHARTS_BASE_URL", DEFAULT_BASE_URL)
    charts_dir_arg = os.environ.get("GENERATED_CHARTS_DIR", DEFAULT_CHARTS_DIR)
    index_md_arg = os.environ.get("INDEX_MD_PATH", DEFAULT_INDEX_MD)

    charts_dir = Path(charts_dir_arg)
    index_md = Path(index_md_arg)

    if not charts_dir.exists() or not charts_dir.is_dir():
        print(f"Error: charts directory not found: {charts_dir}", file=sys.stderr)
        sys.exit(1)
    if not index_md.exists():
        print(f"Error: index.md not found: {index_md}", file=sys.stderr)
        sys.exit(1)

    block = build_content(base_url, charts_dir)
    update_index(index_md, block)


if __name__ == "__main__":
    main()

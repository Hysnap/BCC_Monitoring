# Next Steps

The immediate objective is a slow, polite rendered-page extraction pipeline that starts from the Birmingham 2026 election results by ward pages, navigates ward by ward, and captures the results without creating bursty traffic or unnecessary load for the service team.

## Recommended Python libraries

Use a small stack first, then add only what you need:

- `playwright` for navigating ward pages and extracting rendered content when the HTML is generated client-side or needs scripted interaction.
- `beautifulsoup4` for parsing static HTML once the page markup has been captured.
- `lxml` for faster and more resilient HTML parsing if the ward pages are inconsistent.
- `tenacity` for controlled retries with exponential backoff and jitter.
- `requests-cache` to avoid re-fetching unchanged pages during development and reruns.
- `pandas` for shaping extracted records into tabular form once the crawl is stable.
- `sqlalchemy` or `sqlite3` for storing normalized records in a relational structure.
- `python-dotenv` for keeping any local configuration out of source files.

## Extraction rules to keep traffic gentle

- Keep concurrency at 1 unless you have explicit approval to increase it.
- Add fixed delays and random jitter between requests.
- Cache GET responses during development and limit repeated refreshes.
- Use conditional requests where the CMIS supports them.
- Stop early on repeated failures instead of hammering the same endpoint.
- Store progress so runs can resume without re-crawling everything.

## Suggested implementation sequence

1. Start at the 2026 election results by ward page and confirm the ward navigation pattern.
2. Build a single-ward fetcher that captures the rendered page, extracts candidate names, party labels, vote counts, and elected status, and then moves on after a delay.
3. Persist raw page snapshots or HTML for traceability before normalizing anything.
4. Add checkpointing so each run can resume from the last successful ward.
5. Add structured logging for request count, latency, retries, wards visited, and failures.
6. Add a councillor-directory pass that links current councillors to profile pages and merges them with election people records.
7. Only after the ward-by-ward flow is stable, add broader historical elections, committees, meetings, attendance, or other page families if they are needed.

## Data model

Use the canonical structure in [docs/relational-schema.md](docs/relational-schema.md). That document is the single source for the SQLAlchemy/SQLite model, including the normalized entity tables, the hierarchical label design, and the event timeline model.

When extending the schema, prefer adding a new entity or event table rather than widening the existing ones with ad hoc columns. The model is intended to stay normalized so candidate, party, ward, committee, and meeting data can evolve independently.

## Output publishing

- Publish curated outputs to GitHub Pages so stakeholders can review the collated data without accessing the extraction workflow.
- Treat publishing as a separate build step that reads generated artifacts from disk.
- Keep the published site lightweight so refreshes stay predictable and easy to audit.

## Run state

- Store a checkpoint per ward so interrupted runs can resume without starting over.
- Record both `page_last_updated` and `last_pulled_at` so unchanged pages can be skipped on subsequent runs.
- Use `--force-refresh` only when you want to ignore the checkpoint and re-pull every ward.

## Councillor enrichment

- Scrape `https://www.birmingham.gov.uk/councillors` and `https://www.birmingham.gov.uk/councillors/name` to build the canonical profile list.
- Join the councillor directory to election people by normalized name first, then record the profile URL and council-service history where it matches.
- Capture simple boolean flags from profile pages such as whether a surgery is published and whether the councillor has a public register-of-interests link.
- Use the profile page as the starting point for later committee and meeting extraction rather than trying to model everything at once.
- Keep committee, meeting, attendance, and video links as separate normalized tables so they can be filled incrementally.

## CMIS committee sources

- Use `https://birmingham.cmis.uk.com/birmingham/Committee.aspx` as the committee index and follow the contained links into each public committee page.
- Keep the first pass privacy-safe: store committee names, committee URLs, public webcast/video links, and embedded source links only.
- Do not store attendance or member-level details until the target person is clearly an elected representative or public official and the record is being compiled from a public source page.
- Treat deep meeting content as CMIS-restricted: note that users need to register for CMIS access before depending on the fuller history or meeting pages.
- When committee pages reference councillors no longer in post, preserve the source URL and committee context, but keep person data limited to public-office references and normalized IDs.

## Decision points to confirm

- Whether the ward pages require login, cookies, or anti-bot handling.
- Whether the page structure is stable enough for HTML parsing or needs browser automation.
- Which person identity fields are available consistently enough to build a stable person ID.
- Whether historical ward results should be added after the 2026 extraction is working.

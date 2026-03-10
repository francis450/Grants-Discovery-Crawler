"""
Site profile for Charity Excellence (charityexcellence.co.uk) — Playwright + Login.

Charity Excellence requires free registration and login to access their Funding
Finder.  Once authenticated, the Funding Finder is a filter-based search tool
that returns results in a jQuery DataTables table.

Flow:
  1. Login at myaccount.charityexcellence.co.uk/Account/Login
  2. Navigate to the Funding Finder search page
  3. Set geographic/sector/category filters
  4. Click Search → parse DataTables results
  5. Paginate via DataTables "Next" button
  6. Return structured grant dicts (no LLM needed for extraction)

Because the data is already structured in a table with clear columns, this
profile bypasses the LLM extraction pipeline and parses rows directly.
Relevance scoring (Stage 2) still runs on each grant.
"""

from typing import List, Optional, Set, Tuple

from playwright.async_api import BrowserContext, Page

from config import (
    CE_EMAIL,
    CE_PASSWORD,
    CE_PEOPLE_GROUPS,
    CE_REGION,
    CE_REGION_PARTS,
    CE_SECTOR_TYPES,
    MAX_PAGES,
    MIN_RELEVANCE_SCORE,
    PLAYWRIGHT_DEFAULT_TIMEOUT,
)
from utils.data_utils import is_complete_grant, is_duplicate_grant, is_how_it_helps_valid
from utils.logging_utils import logger, MetricsLogger
from utils.playwright_utils import new_stealth_page

from .base_playwright_profile import BasePlaywrightProfile

metrics_logger = MetricsLogger()

# -- Constants ----------------------------------------------------------------
LOGIN_URL = "https://myaccount.charityexcellence.co.uk/Account/Login"
FINDER_URL = "https://myaccount.charityexcellence.co.uk/Funder/Index?id=0"
ROWS_PER_PAGE = 25  # DataTables default


class CharityExcellenceProfile(BasePlaywrightProfile):
    """
    Playwright + login profile for Charity Excellence Funding Finder.

    Overrides ``run()`` entirely because the data is extracted from a
    structured DataTable rather than free-form HTML.
    """

    # -- Site metadata --------------------------------------------------------
    site_name = "Charity Excellence"
    site_url = "https://www.charityexcellence.co.uk"
    description = "Free funding finder for charities (login required)"

    # base_urls is not used for navigation (we use FINDER_URL), but kept for
    # compatibility with BaseSiteProfile's interface.
    base_urls = [FINDER_URL]

    css_selector = "#tblfunderlist tbody tr"
    pagination_type = "none"  # Pagination handled internally via DataTables

    # -- BaseSiteProfile compatibility ----------------------------------------

    def get_page_url(self, base_url: str, page_number: int) -> str:
        return base_url

    async def fetch_page_content(self, page: Page, url: str) -> Optional[str]:
        """Not used — results are parsed from DataTables directly."""
        return None

    async def detect_end_of_results_pw(self, page: Page, url: str) -> bool:
        return True

    # =========================================================================
    # Custom run() — login → filter → search → parse DataTables
    # =========================================================================

    async def run(
        self,
        context: BrowserContext,
        llm_strategy,  # unused — extraction is table-based
        required_keys: List[str],
        seen_titles: Set[str],
        relevance_analyzer,
    ) -> List[dict]:
        if not CE_EMAIL or not CE_PASSWORD:
            logger.error(
                "[CharityExcellence] CHARITY_EXCELLENCE_EMAIL / PASSWORD not set "
                "in .env — skipping."
            )
            return []

        page = await new_stealth_page(context)
        all_grants: List[dict] = []

        try:
            # 1. Login
            logged_in = await self._login(page)
            if not logged_in:
                return []

            # 2. Navigate to Funding Finder
            logger.info("[CharityExcellence] Opening Funding Finder …")
            await page.goto(FINDER_URL, wait_until="networkidle", timeout=PLAYWRIGHT_DEFAULT_TIMEOUT)
            await page.wait_for_timeout(2000)

            # 3. Set filters & search
            await self._set_filters_and_search(page)

            # 4. Read total count
            total = await self._get_total_entries(page)
            logger.info(f"[CharityExcellence] Search returned {total} entries.")

            if total == 0:
                logger.warning("[CharityExcellence] No funders matched filters.")
                return []

            # 5. Paginate and parse
            dt_page = 1
            max_dt_pages = (total // ROWS_PER_PAGE) + (1 if total % ROWS_PER_PAGE else 0)
            max_dt_pages = min(max_dt_pages, MAX_PAGES)

            while dt_page <= max_dt_pages:
                logger.info(
                    f"[CharityExcellence] Parsing DataTables page {dt_page}/{max_dt_pages} …"
                )

                with metrics_logger.measure(
                    "ce_parse_table", site=self.site_name, url=FINDER_URL
                ) as ctx:
                    rows = await self._parse_current_page(page)
                    ctx.items = len(rows)

                if not rows:
                    logger.info("[CharityExcellence] No rows on this page — stopping.")
                    break

                # Process each row through the filter/dedup/relevance pipeline
                for grant in rows:
                    if not is_complete_grant(grant, required_keys):
                        continue
                    if is_duplicate_grant(grant.get("title"), seen_titles):
                        logger.debug(f"  Duplicate: {grant.get('title')} — skip.")
                        continue

                    # Relevance scoring
                    logger.info(f"  Analyzing relevance: {grant.get('title', '?')} …")
                    analysis = await relevance_analyzer(grant)

                    if analysis:
                        # Normalize field names for consistency
                        if "score" in analysis and "relevance_score" not in analysis:
                            analysis["relevance_score"] = int(analysis.pop("score", 0))
                        if "reasoning" in analysis and "relevance_reasoning" not in analysis:
                            analysis["relevance_reasoning"] = analysis.pop("reasoning", "")
                        grant.update(analysis)
                        score = grant.get("relevance_score", grant.get("score", 0))
                        if score >= MIN_RELEVANCE_SCORE:
                            # Reject if the LLM admits the grant doesn't help
                            hih = grant.get("how_it_helps", "")
                            if not is_how_it_helps_valid(hih):
                                logger.info(f"  ✗ Rejected ({score}): how_it_helps='Not applicable' — {grant['title']}")
                                continue
                            logger.info(f"  ✓ Relevant ({score}/100): {grant['title']}")
                            grant["source_website"] = self.site_name
                            seen_titles.add(grant["title"])
                            all_grants.append(grant)
                        else:
                            logger.info(f"  ✗ Low score ({score}): {grant['title']}")
                    else:
                        logger.warning(
                            f"  Could not score: {grant.get('title', '?')}"
                        )

                logger.info(
                    f"[CharityExcellence] Page {dt_page} done — "
                    f"{len(all_grants)} grants total so far."
                )

                # Advance DataTables pagination
                has_next = await self._click_next_page(page)
                if not has_next:
                    break
                dt_page += 1

                # Polite delay
                await page.wait_for_timeout(1500)

        except Exception as exc:
            logger.error(f"[CharityExcellence] run() failed: {exc}", exc_info=True)
        finally:
            await page.close()

        logger.info(
            f"[CharityExcellence] Finished — {len(all_grants)} grants passed "
            f"relevance threshold."
        )
        return all_grants

    # =========================================================================
    # Private helpers
    # =========================================================================

    async def _login(self, page: Page) -> bool:
        """Authenticate and return True on success."""
        logger.info("[CharityExcellence] Logging in …")
        try:
            await page.goto(LOGIN_URL, wait_until="networkidle", timeout=PLAYWRIGHT_DEFAULT_TIMEOUT)

            await page.fill("#LoginViewModel_Email", CE_EMAIL)
            await page.fill("#LoginViewModel_Password", CE_PASSWORD)

            # The T&C checkbox is hidden (styled via CSS), so set it via JS
            await page.evaluate(
                'document.getElementById("LoginViewModel_TermsAndConditions").checked = true'
            )

            await page.click("#btnLogin")

            # Wait for redirect to dashboard
            await page.wait_for_load_state("networkidle", timeout=15000)
            await page.wait_for_timeout(2000)

            if "Dashboard" in page.url or "Index" in page.url:
                logger.info(f"[CharityExcellence] Login successful → {page.url}")
                return True

            logger.error(
                f"[CharityExcellence] Login may have failed — landed on {page.url}"
            )
            return False

        except Exception as exc:
            logger.error(f"[CharityExcellence] Login error: {exc}")
            return False

    async def _set_filters_and_search(self, page: Page) -> None:
        """Set the multi-select filter dropdowns and click Search."""
        logger.info("[CharityExcellence] Setting search filters …")

        # Build JS that selects option values in each multi-select
        # and refreshes the jQuery multiselect widget.
        js = """
        (config) => {
            function selectOptions(selectId, values) {
                const sel = document.getElementById(selectId);
                if (!sel || !values.length) return;
                Array.from(sel.options).forEach(o => {
                    if (values.includes(o.value)) o.selected = true;
                });
                sel.dispatchEvent(new Event('change', {bubbles: true}));
                try { $(sel).multiselect('refresh'); } catch(e) {}
            }

            // Region master dropdown (plain <select>)
            const regionMaster = document.getElementById('ddlregionlistS');
            if (regionMaster) {
                regionMaster.value = config.region;
                regionMaster.dispatchEvent(new Event('change', {bubbles: true}));
            }

            selectOptions('ddlregionpartlist', config.regionParts);
            selectOptions('ddlsectortype', config.sectorTypes);
            selectOptions('ddlpeoplegroups', config.peopleGroups);
        }
        """

        await page.evaluate(
            js,
            {
                "region": CE_REGION,
                "regionParts": CE_REGION_PARTS,
                "sectorTypes": CE_SECTOR_TYPES,
                "peopleGroups": CE_PEOPLE_GROUPS,
            },
        )

        await page.wait_for_timeout(500)

        # Click Search (#btnserarch — note the typo is in their source code)
        await page.click("#btnserarch")
        logger.info("[CharityExcellence] Search submitted — waiting for results …")

        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

    async def _get_total_entries(self, page: Page) -> int:
        """Read the DataTables info line: 'Showing 1 to 25 of 157 entries'."""
        info_text = await page.evaluate("""
        () => {
            const el = document.querySelector('#tblfunderlist_info');
            return el ? el.textContent.trim() : '';
        }
        """)
        # Parse "Showing X to Y of Z entries"
        if "of" in info_text:
            try:
                part = info_text.split("of")[1].strip()
                total = int(part.split()[0].replace(",", ""))
                return total
            except (IndexError, ValueError):
                pass
        return 0

    async def _parse_current_page(self, page: Page) -> List[dict]:
        """Extract grant dicts from the currently visible DataTables page."""
        rows_data = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('#tblfunderlist tbody tr');
            return Array.from(rows).map(row => {
                const cells = row.querySelectorAll('td');
                if (cells.length < 5) return null;

                // Column 0: Funder name — may contain <a> with href
                const nameCell = cells[0];
                const link = nameCell.querySelector('a[href]');
                const title = link
                    ? link.textContent.trim()
                    : nameCell.textContent.trim();
                const applicationUrl = link ? link.href : '';

                // Column 1: Funder Detail (description)
                const description = cells[1] ? cells[1].textContent.trim() : '';

                // Column 2: Region/Country
                const region = cells[2] ? cells[2].textContent.trim() : '';

                // Column 3: City/County
                const city = cells[3] ? cells[3].textContent.trim() : '';

                // Column 4: Category
                const category = cells[4] ? cells[4].textContent.trim() : '';

                // Column 5: Deadline
                const deadline = cells[5] ? cells[5].textContent.trim() : '';

                return {title, description, applicationUrl, region, city, category, deadline};
            }).filter(Boolean);
        }
        """)

        # Convert raw JS objects to grant dicts matching our schema
        grants = []
        for r in rows_data:
            title = (r.get("title") or "").strip()
            # Filter out non-grant rows: empty, "No data", and UI error messages
            if not title or title == "No data available in table":
                continue
            if title.startswith(". Found something") or len(title) < 3:
                continue

            grant = {
                "title": title,
                "description": r.get("description", ""),
                "application_url": r.get("applicationUrl", ""),
                "geographic_focus": ", ".join(
                    filter(None, [r.get("region", ""), r.get("city", "")])
                ),
                "thematic_areas": r.get("category", ""),
                "deadline": r.get("deadline", ""),
                "funding_organization": title,  # funder name = org name
                "source_website": self.site_name,
            }
            grants.append(grant)

        return grants

    async def _click_next_page(self, page: Page) -> bool:
        """Click the DataTables 'Next' button. Returns False if on last page."""
        # Use JavaScript click — the button may be off-screen or briefly hidden
        # after long processing on a page, causing Playwright's visibility check
        # to time out.
        clicked = await page.evaluate("""
        () => {
            let btn = document.querySelector('#tblfunderlist_next:not(.disabled)');
            if (!btn) btn = document.querySelector('.paginate_button.next:not(.disabled)');
            if (btn) { btn.click(); return true; }
            return false;
        }
        """)

        if clicked:
            # Wait for DataTables AJAX to refresh
            await page.wait_for_timeout(2000)
            return True

        return False

    # -- Info ------------------------------------------------------------------

    def get_site_info(self) -> dict:
        info = super().get_site_info()
        info.update(
            {
                "rendering": "Playwright + Login (DataTables search)",
                "requires_auth": True,
                "search_filters": {
                    "region": CE_REGION,
                    "region_parts": CE_REGION_PARTS,
                    "sector_types": CE_SECTOR_TYPES,
                    "people_groups": CE_PEOPLE_GROUPS,
                },
                "results_format": "jQuery DataTables (25 per page)",
            }
        )
        return info

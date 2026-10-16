# Public search and AI discovery

Canonical product: Anumana, https://anumana.aolbeam.com/.
The deployed application is a static public site from site/, as configured in
vercel.json. This project has no account, dashboard or API implementation and no
About page. Related projects therefore appear on the homepage at
#explore-aolbeam, with a footer link.

## Files and policy

- site/index.html: clear product/audience description, canonical metadata,
  Open Graph/Twitter summary fields, factual WebSite/WebPage/software JSON-LD,
  and separate crawlable Aolbeam AI and Ask links.
- site/styles.css: responsive related-project cards and wrapping footer links.
- site/llms.txt and site/llm.txt: identical public Markdown overview and alias.
  No API/authentication or JavaScript rendering is required to read them.
- site/robots.txt: permits public content for general crawlers and PerplexityBot;
  excludes account, admin, dashboard, API, internal, private and login/settings
  paths. No robots.txt existed in the repository; the canonical live endpoint
  returned 404 during the initial inspection. No existing file-level crawler
  policy was removed. Dashboard/firewall policies were not accessed or changed.
- site/sitemap.xml: only the launched canonical homepage. Section fragments,
  discovery files, external projects, unlaunched pages and private routes are
  excluded. No guessed lastmod timestamps.
- vercel.json: retains the static output directory, clean URLs, trailing-slash
  setting and build/install configuration. Adds appropriate discovery-file
  content types and X-Robots-Tag: noindex, nofollow for private route families.
  No catch-all rewrite, authentication change or deployment is introduced.

Robots directives and noindex headers are indexing guidance, not authorization.
Future real private routes must enforce access controls separately. Do not place
credentials or private files under the static site/ output directory.

## Source verification (2026-10-16)

Read-only requests returned HTTP 200 with no login for:

- https://anumana.aolbeam.com/ — currently serves the older public homepage.
- https://ask.aolbeam.com/ — verifies a Python CLI for AI questions, attached-file
  code inspection and web search; no command execution or code editing.
- https://www.aolbeam.com/practice — verifies AI-generated practice across maths,
  science, languages, humanities, business and computing, answer feedback and
  personal learning paths. The page discloses sign-in for paths and usage limits.

Related-product descriptions remain separate from Anumana's functionality.
There is no Anumana self-link in the related-project cards or optional related
section of llms.txt. No ratings, reviews, prices or business affiliations were
invented in structured data.

The existing live robots.txt and sitemap.xml returned 404 before this change.
Discovery additions are local until a separately authorized deployment.

## Repeatable checks

```sh
.venv/bin/python -m pytest tests/
node --check site/app.js
python3 packaging/verify_public_site.py
```

The last command starts and stops a temporary server for site/ only. It checks
HTTP 200/no login redirects on /, /llms.txt, /llm.txt, /robots.txt and /sitemap.xml
for a normal user agent and PerplexityBot; compares the alias contents; follows
sitemap paths; and checks unavailable private/internal paths. It does not emulate
Vercel's headers or firewall. Local socket permission may be needed in a sandbox.
The offline tests verify metadata, canonical consistency, structured data,
robots rules, related links, sitemap scope and deployment-output boundaries.

After a separately authorized deployment, use:

```sh
python3 packaging/verify_public_site.py --base-url https://anumana.aolbeam.com
```

This is read-only. It intentionally fails if discovery files are still missing,
a sitemap destination is not public, or a private probe unexpectedly returns 200.
A request with a crawler user agent is not proof that the crawler's real IP
infrastructure can pass a hosting firewall.

## Owner actions

1. Review the changes and deploy separately when ready. No deployment, push or
   publication is part of this task. Recheck discovery files and Vercel headers
   on the canonical production domain afterward.
2. Verify ownership in Google Search Console/Bing Webmaster Tools and submit
   https://anumana.aolbeam.com/sitemap.xml. No verification token is fabricated
   or added to source.
3. Check Vercel deployment protection and firewall/bot-management settings for
   public paths. Allow legitimate verified search crawler traffic, including
   PerplexityBot, without disabling protection for actual private applications.
4. If the older anumana.vercel.app domain remains public, configure a deliberate
   redirect to the canonical custom domain in hosting settings. Preserve the
   intended audience of preview deployments; do not open private previews.
5. Keep llms.txt/llm.txt identical and update coverage when engine readiness or a
   published server release changes. Replace the Agensi homepage link only after
   the real Anumana listing exists.

These files improve clarity and machine access; no search rankings, indexing,
rich results, AI recommendations or crawler uptake are guaranteed.

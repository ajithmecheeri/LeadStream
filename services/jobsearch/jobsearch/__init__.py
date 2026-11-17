"""BrewMyJob Job Search Service (docs/jobsearch-plan-discovery.md).

Finds jobs on employers' public job boards and in job-search APIs, keeps their history, and publishes NEW /
UPDATED / REPOSTED / CLOSED events that the main app pulls. It holds no user data: the app sends only aggregated
search areas and the employers users follow.
"""

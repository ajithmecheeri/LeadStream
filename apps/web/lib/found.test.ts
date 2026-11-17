import { describe, expect, it } from "vitest";
import { googleUrl, guessFromLink } from "./found";

describe("googleUrl", () => {
  it("searches Google for the query in the chosen period", () => {
    const url = new URL(googleUrl('site:linkedin.com/jobs/view "Head of Engineering" (Bengaluru OR Bangalore)', "day"));
    expect(url.origin + url.pathname).toBe("https://www.google.com/search");
    expect(url.searchParams.get("q")).toBe('site:linkedin.com/jobs/view "Head of Engineering" (Bengaluru OR Bangalore)');
    expect(url.searchParams.get("tbs")).toBe("qdr:d");
    expect(new URL(googleUrl("x", "week")).searchParams.get("tbs")).toBe("qdr:w");
  });
});

describe("guessFromLink", () => {
  it("reads the title and company a LinkedIn link spells out", () => {
    expect(
      guessFromLink(
        "https://in.linkedin.com/jobs/view/head-of-engineering-service-enablement-platforms-at-woolworths-group-4490581539?trk=x",
      ),
    ).toEqual({ title: "Head of Engineering Service Enablement Platforms", company: "Woolworths Group" });
    expect(guessFromLink("https://www.linkedin.com/jobs/view/vp-of-ai-at-acme-1234567/")).toEqual({
      title: "VP of AI",
      company: "Acme",
    });
  });

  it("gives nothing for bare ids and other sites", () => {
    expect(guessFromLink("https://www.linkedin.com/jobs/view/4490581539/")).toBeNull();
    expect(guessFromLink("https://www.naukri.com/job-listings-head-engineering-acme-bengaluru-140525901234")).toBeNull();
    expect(guessFromLink("not a link")).toBeNull();
  });
});

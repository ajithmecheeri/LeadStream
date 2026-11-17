import type { MetadataRoute } from "next";
import { SITE_URL } from "./_home/site";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: SITE_URL, changeFrequency: "weekly", priority: 1 },
    ...["privacy", "terms", "contact"].map((p) => ({ url: `${SITE_URL}/${p}`, changeFrequency: "monthly" as const, priority: 0.3 })),
  ];
}
